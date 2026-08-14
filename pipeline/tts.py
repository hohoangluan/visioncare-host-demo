import io
import re
import threading
import wave
from collections.abc import Iterable, Iterator
from functools import lru_cache
from queue import Full, Queue

import numpy as np

import config

# VieNeu-TTS v3 Turbo outputs 48 kHz mono float32 audio.
SAMPLE_RATE = 48000

# Tốc độ lấy mẫu của PCM stream gửi về MCU. 16 kHz phủ đủ dải giọng nói mà chỉ
# tốn 32 KB/s thay vì 96 KB/s, nên MCU cần buffer nhỏ hơn và WiFi nhẹ tải hơn.
OUTPUT_SAMPLE_RATE = 16000

_DECIMATION = SAMPLE_RATE // OUTPUT_SAMPLE_RATE

# Cắt câu ở dấu kết câu KÈM khoảng trắng theo sau, hoặc ở xuống dòng. Đòi hỏi
# khoảng trắng là để "50.000 đồng" không bị xẻ đôi — tiếng Việt dùng dấu chấm
# làm dấu phân cách hàng nghìn, cắt ở đó thì TTS đọc thành "năm mươi" rồi
# "không nghìn đồng".
_SENTENCE_END = re.compile(r"[.!?…]\s|\n")

# Text dài mà không có dấu câu nào (model liệt kê một mạch) vẫn phải cắt, nếu
# không câu đầu phải chờ tới lúc Gemini viết xong. 200 nằm dưới ngưỡng chia
# chunk 256 ký tự của VieNeu nên không tạo thêm lần cắt thứ hai bên trong model.
_MAX_SENTENCE_CHARS = 200

# Mảnh ngắn hơn ngưỡng này thì gộp vào phần text theo sau thay vì đọc riêng.
# Chủ yếu để cứu đầu mục đánh số: "1. Ràng buộc bộ nhớ..." bị luật cắt-ở-dấu-
# chấm xẻ thành "1." và phần còn lại, khiến TTS đọc rời "một." rồi mới tới nội
# dung — nghe cụt. Mỗi lệnh gọi TTS còn có chi phí cố định đáng kể: đo thật
# thấy 3 mảnh "1." "2." "3." tốn 2.94s để sinh 1.68s audio.
_MIN_SENTENCE_CHARS = 24

# Trần hàng đợi PCM giữa thread tổng hợp và luồng gửi. Mảnh PCM đo được trung
# bình ~0.8s audio, nên 32 mảnh ~ 25 giây audio ~ 800 KB — đủ để thread nền
# không bao giờ phải chờ luồng gửi, mà vẫn chặn trần bộ nhớ mỗi request.
_PIPELINE_QUEUE_CHUNKS = 32

# CBR để byte-rate cố định suốt stream — server tính đệm preroll bằng phép
# nhân đơn giản (giây * byte-rate), giống cách đã làm với PCM trần.
MP3_BITRATE_KBPS = 32
MP3_BYTE_RATE = MP3_BITRATE_KBPS * 1000 // 8


def _split_long(text: str) -> tuple[str, str]:
    """Cắt `text` quá dài ở khoảng trắng gần cuối nhất. Trả (phần đọc, phần dư)."""
    cut = text.rfind(" ", 0, _MAX_SENTENCE_CHARS)
    if cut == -1:  # một từ dài hơn cả ngưỡng: cắt cứng, thà đọc còn hơn treo
        cut = _MAX_SENTENCE_CHARS
    return text[:cut], text[cut:]


def _sentences(text_chunks: Iterable[str]) -> Iterator[str]:
    """Gom mảnh text rời rạc thành từng câu đủ nghĩa để đưa sang TTS.

    Trả câu ngay khi đủ, không đợi đọc hết nguồn — đó là điều kiện để giọng
    nói bắt đầu trong lúc Gemini còn đang viết.
    """
    buffer = ""

    for chunk in text_chunks:
        buffer += chunk
        while True:
            match = _SENTENCE_END.search(buffer)
            if match:
                if match.end() < _MIN_SENTENCE_CHARS and "\n" not in match.group():
                    # Mảnh quá ngắn để đọc riêng ("1.", "Xong."): chờ thêm text
                    # rồi gộp. Tìm dấu kết câu tiếp theo đủ xa để cắt.
                    #
                    # Trừ khi cắt ở xuống dòng: đó là dấu người GỌI chủ động đặt
                    # để báo "câu này trọn vẹn rồi, đọc đi" (xem `_UTTERANCE_END`
                    # ở `handlers/action_flow.py`). Chờ gộp một câu như vậy là
                    # giữ nó lại tới lúc có mảnh sau — mà mảnh sau của handler
                    # điều khiển điện thoại là cả chục giây nữa.
                    later = _SENTENCE_END.search(buffer, _MIN_SENTENCE_CHARS)
                    if later is None:
                        break
                    match = later
                sentence, buffer = buffer[: match.end()], buffer[match.end():]
            elif len(buffer) > _MAX_SENTENCE_CHARS:
                sentence, buffer = _split_long(buffer)
            else:
                break
            if sentence.strip():
                yield sentence.strip()

    # Phần đuôi luôn phải đọc, kể cả khi ngắn hơn ngưỡng gộp — không được nuốt.
    if buffer.strip():
        yield buffer.strip()


# Câu nói cố định đã tổng hợp sẵn: khoá text -> PCM 16 kHz trọn câu.
#
# Toàn bộ câu trấn an, câu báo lỗi, câu nhắc bấm thông báo đều viết cứng trong
# code — chữ không đổi giữa các lần chạy, nhưng trước đây vẫn gọi model mỗi lần
# và bắt người dùng chờ đúng lúc họ đang cần nghe ngay. Xem `pipeline/phrases.py`
# để biết chỗ nạp.
_PHRASE_PCM: dict[str, bytes] = {}

# Kích thước mảnh khi phát lại câu dựng sẵn: ~0.5s audio, cùng cỡ với mảnh model
# sinh ra, để phần đệm preroll và hàng đợi phía dưới không phải xử lý khác đi.
_PHRASE_CHUNK_BYTES = OUTPUT_SAMPLE_RATE * 2 // 2


# Ước lượng thời gian đọc cho câu KHÔNG dựng sẵn, khớp tuyến tính trên 96 câu
# đã dựng sẵn (giọng Ngọc Linh, style tự nhiên). Đổi giọng thì đo lại bằng
# `speaking_seconds` trên chính cache mới.
_SECONDS_PER_CHAR = 0.0466
_SPEECH_FIXED_SECONDS = 0.324

_PCM_BYTES_PER_SAMPLE = 2


def phrase_key(text: str) -> str:
    """Khoá tra câu dựng sẵn.

    Gộp mọi khoảng trắng về một dấu cách: câu đi tới đây đã qua `_sentences()`
    (ghép từ nhiều mảnh, cắt ở dấu câu) nên có thể lệch khoảng trắng so với
    hằng số gốc, mà lệch một dấu cách là trượt cache và mất hết cái lợi.
    """
    return " ".join(text.split())


def register_phrase(text: str, pcm: bytes) -> None:
    """Nạp sẵn PCM cho một câu cố định."""
    _PHRASE_PCM[phrase_key(text)] = pcm


def prerendered(text: str) -> bytes | None:
    """PCM đã dựng sẵn cho `text`, hoặc None nếu phải tổng hợp lúc chạy."""
    return _PHRASE_PCM.get(phrase_key(text))


def speaking_seconds(text: str) -> float:
    """Đọc `text` lên mất bao nhiêu giây.

    Câu đã dựng sẵn thì đo chính xác từ chính PCM sắp phát. Câu động (có tên
    bài, tên người, địa chỉ) chưa tồn tại lúc hỏi, nên ước lượng theo độ dài —
    khớp tuyến tính trên 96 câu dựng sẵn cho sai số trung bình 0.17s, tối đa
    1.30s. Đủ chính xác cho việc duy nhất nó phục vụ: giãn câu trấn an kế tiếp
    ra sau câu đang nói, thay vì đếm từ lúc bắt đầu nói.
    """
    pcm = prerendered(text)
    if pcm is not None:
        return len(pcm) / (OUTPUT_SAMPLE_RATE * _PCM_BYTES_PER_SAMPLE)
    return _SECONDS_PER_CHAR * len(text) + _SPEECH_FIXED_SECONDS


def clear_phrases() -> None:
    _PHRASE_PCM.clear()


def phrase_count() -> int:
    return len(_PHRASE_PCM)


@lru_cache(maxsize=1)
def _load_tts():
    from vieneu import Vieneu

    # ONNX/CPU backend của TTS đã đủ nhanh (~1-3s/câu) và nhẹ. Ép device="cpu"
    # để không tranh VRAM/CUDA context với STT (GPU 4GB, chỉ đủ chỗ thoải mái
    # cho một model torch lớn chạy GPU cùng lúc).
    return Vieneu(device="cpu")


def synthesize(text: str) -> bytes:
    """Text tiếng Việt -> WAV bytes (VieNeu-TTS v3 Turbo, giọng nữ)."""
    tts = _load_tts()
    audio = tts.infer(text, voice=config.TTS_VOICE, style=config.TTS_STYLE)

    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize_stream(text: str) -> Iterator[bytes]:
    """Text tiếng Việt -> từng mảnh PCM 16-bit little-endian mono 16 kHz.

    Khác `synthesize()` ở chỗ mảnh đầu tiên sẵn sàng ngay khi model giải mã
    xong nhóm frame đầu, không phải chờ tổng hợp hết câu. Người nghe bắt đầu
    nghe được sau vài trăm ms thay vì vài giây.

    Không có header WAV: MCU biết trước định dạng nên đẩy thẳng byte vào I2S.
    """
    tts = _load_tts()
    # Số mẫu mỗi mảnh không chắc chia hết cho _DECIMATION. Phần dư được giữ lại
    # để ghép vào đầu mảnh sau, nên không mẫu nào rơi mất ở biên giữa hai mảnh.
    carry = np.empty(0, dtype=np.float32)

    for chunk in tts.infer_stream(text, voice=config.TTS_VOICE, style=config.TTS_STYLE):
        samples = np.clip(np.asarray(chunk, dtype=np.float32), -1.0, 1.0)
        buf = np.concatenate((carry, samples))
        usable = len(buf) - len(buf) % _DECIMATION
        carry = buf[usable:]
        if usable == 0:
            continue

        # Trung bình từng nhóm 3 mẫu, không phải buf[::3]: decimate trần bỏ qua
        # bước lọc nên mọi tần số trên 8 kHz gập ngược vào dải giọng nói.
        downsampled = buf[:usable].reshape(-1, _DECIMATION).mean(axis=1)
        yield (downsampled * 32767).astype("<i2").tobytes()


def _sentence_pcm(sentence: str) -> Iterator[bytes]:
    """PCM của một câu: lấy bản dựng sẵn nếu có, không thì gọi model.

    Đây là chỗ ăn tiền của cache. Câu như "Hệ thống đang xử lý yêu cầu, bạn chờ
    một chút." đo được 1.4s tổng hợp — mà nó tồn tại chính là để lấp quãng chờ,
    nên trả nó chậm là tự tạo thêm đúng quãng chờ cần lấp.
    """
    cached = prerendered(sentence)
    if cached is None:
        yield from synthesize_stream(sentence)
        return

    for start in range(0, len(cached), _PHRASE_CHUNK_BYTES):
        yield cached[start:start + _PHRASE_CHUNK_BYTES]


def _pause_pcm() -> bytes:
    """Khoảng lặng chèn giữa hai câu liền nhau.

    Đọc `config` mỗi lần chứ không tính sẵn ở module: test cần chỉnh được độ dài
    này, mà hằng số tính lúc import thì monkeypatch không với tới.
    """
    samples = int(config.SPEECH_SENTENCE_PAUSE_SECONDS * OUTPUT_SAMPLE_RATE)
    return b"\x00\x00" * samples


def _spoken_pcm(sentence: str, first: bool) -> Iterator[bytes]:
    """PCM của một câu, kèm chỗ thở trước nó nếu không phải câu đầu.

    Model chỉ tổng hợp trong phạm vi từng câu, nên nối thẳng đầu câu sau vào
    đuôi câu trước là một tràng tiếng liên tục không có chỗ ngắt. Người khiếm
    thị chỉ có kênh âm thanh để theo dõi: câu chào, câu trấn an, câu báo kết quả
    và câu trả lời của model dính liền nhau thì không nghe ra được đâu là ranh
    giới giữa chúng.

    Chèn ở đây, giữa MỌI cặp câu liền nhau, chứ không riêng chỗ giáp ranh giữa
    hai loại câu: `_sentences()` cắt xong thì không còn biết câu nào từ nguồn
    nào, và một đoạn model viết dài cũng cần ngắt hơi y như vậy.
    """
    if not first:
        pause = _pause_pcm()
        if pause:
            yield pause
    yield from _sentence_pcm(sentence)


def synthesize_text_stream(text_chunks: Iterable[str]) -> Iterator[bytes]:
    """Mảnh text (từ Gemini) -> mảnh PCM, không đợi text đầy đủ.

    Tổng hợp chạy ở thread nền và luôn đi trước người nghe. Làm tuần tự thì
    giữa hai câu có khoảng lặng đúng bằng thời gian phonemize + prefill của câu
    sau (đo được 0.91s) — nghe rõ là ngắt quãng. Chạy nền thì câu sau đã sẵn
    sàng trước khi câu trước phát hết, khoảng lặng biến mất.

    An toàn về thread: chỉ thread nền gọi model, luồng chính chỉ lấy từ hàng
    đợi — không có hai thread nào cùng đụng vào ONNX session.
    """
    queue: Queue = Queue(maxsize=_PIPELINE_QUEUE_CHUNKS)
    done = object()
    failure: list[BaseException] = []
    stop = threading.Event()

    def worker() -> None:
        try:
            for index, sentence in enumerate(_sentences(text_chunks)):
                for pcm in _spoken_pcm(sentence, first=index == 0):
                    while not stop.is_set():
                        try:
                            queue.put(pcm, timeout=0.1)
                            break
                        except Full:
                            continue
                    if stop.is_set():
                        return
        except BaseException as exc:  # noqa: BLE001 - chuyển nguyên vẹn sang consumer
            failure.append(exc)
        finally:
            queue.put(done)

    thread = threading.Thread(target=worker, name="tts-pipeline", daemon=True)
    thread.start()

    try:
        while True:
            item = queue.get()
            if item is done:
                break
            yield item
    finally:
        # Consumer bỏ đi giữa chừng (client ngắt kết nối): báo thread nền dừng
        # thay vì để nó tổng hợp nốt cả bài rồi mới chết.
        stop.set()

    if failure:
        raise failure[0]


def encode_mp3(pcm_stream: Iterator[bytes]) -> Iterator[bytes]:
    """PCM 16-bit/16kHz mono -> mảnh MP3 CBR, để giảm băng thông gửi MCU.

    32 kbps thay vì PCM trần 256 kbps (32 KB/s) — 1/8 dung lượng, chấp nhận
    được cho thoại. `encoder.encode()` chỉ trả bytes khi tích luỹ đủ một
    frame MPEG, nên nhiều lần gọi liên tiếp có thể ra rỗng; bỏ qua thay vì
    yield mảnh rỗng.

    `lameenc` trả `bytearray`, không phải `bytes` — ép kiểu trước khi yield vì
    Starlette's `StreamingResponse` chỉ chấp nhận `bytes`/`memoryview`.
    """
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_in_sample_rate(OUTPUT_SAMPLE_RATE)
    encoder.set_channels(1)
    encoder.set_bit_rate(MP3_BITRATE_KBPS)

    for pcm in pcm_stream:
        mp3 = encoder.encode(pcm)
        if mp3:
            yield bytes(mp3)

    tail = encoder.flush()
    if tail:
        yield bytes(tail)
