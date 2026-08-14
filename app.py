import glob
import io
import logging
import os
import re
import time
import wave
from collections.abc import Callable, Iterable, Iterator
from itertools import chain

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response, StreamingResponse

import config
from pipeline import intent_local, phrases, router, stt, tts

logger = logging.getLogger("blind_assist")

# Uvicorn chỉ cấu hình logger của riêng nó; không có dòng này thì log INFO đo
# thời gian bên dưới bị root logger (mặc định WARNING) nuốt mất.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="Blind-Assist Audio Server")

PCM_FORMAT = f"pcm_s16le;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"
_BYTES_PER_SAMPLE = 2


MP3_FORMAT = f"mp3;bitrate={tts.MP3_BITRATE_KBPS}kbps;rate={tts.OUTPUT_SAMPLE_RATE};channels=1"


def _stream_headers(response_format: str) -> dict[str, str]:
    """Đủ thông tin để MCU tự cấu hình I2S/decoder và tính buffer, không hardcode gì.

    Tách thành từng header số riêng thay vì bắt firmware parse chuỗi ghép: trên
    MCU, `atoi` một header là xong, còn tách chuỗi là thêm một chỗ để sai.
    """
    # Số giây audio đã nằm sẵn trong mảnh đầu. MCU phát ngay khi nhận được
    # mảnh đó; đây là quãng an toàn nó có trước khi cần mảnh tiếp theo.
    preroll = str(config.AUDIO_PREROLL_SECONDS)

    if response_format == "mp3_stream":
        return {
            "X-Audio-Format": MP3_FORMAT,  # dạng gộp, cho người debug bằng curl
            "X-Audio-Encoding": "mp3",
            "X-Audio-Sample-Rate": str(tts.OUTPUT_SAMPLE_RATE),
            "X-Audio-Channels": "1",
            # CBR nên cố định suốt stream. Nhân trực tiếp ra kích thước buffer
            # theo giây, khỏi tự tính. Không có X-Audio-Bits: không áp dụng
            # cho dữ liệu đã nén.
            "X-Audio-Byte-Rate": str(tts.MP3_BYTE_RATE),
            "X-Audio-Preroll-Seconds": preroll,
        }

    return {
        "X-Audio-Format": PCM_FORMAT,  # dạng gộp, cho người debug bằng curl
        "X-Audio-Encoding": "pcm_s16le",
        "X-Audio-Sample-Rate": str(tts.OUTPUT_SAMPLE_RATE),
        "X-Audio-Bits": str(_BYTES_PER_SAMPLE * 8),
        "X-Audio-Channels": "1",
        # Nhân trực tiếp ra kích thước buffer theo giây, khỏi tự tính.
        "X-Audio-Byte-Rate": str(tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE),
        "X-Audio-Preroll-Seconds": preroll,
    }

_ERROR_MESSAGE = "Có lỗi xảy ra, vui lòng thử lại"

# Chỉ audio là bắt buộc: đó là câu lệnh, không có nó thì không biết người dùng
# muốn gì. Ảnh thì tuỳ câu hỏi — "gọi cho mẹ" hay "kể chuyện cười" không cần ảnh
# nào, nên đòi đủ cả hai ở đây là chặn oan. Câu hỏi thật sự cần ảnh mà thiếu ảnh
# thì `pipeline/image_quality.py` nói, vì chỉ ở đó mới biết intent là gì.
_MISSING_AUDIO_MESSAGE = "Không nhận được âm thanh, vui lòng nói lại."

# Câu đầu tiên, phát ngay khi gói tin vào tới server — trước cả STT.
#
# Người khiếm thị bấm gửi xong không có gì để nhìn: im lặng 2-3 giây đầu là
# không phân biệt được với "gửi hụt, phải bấm lại". Câu này chỉ nói đúng một
# điều có thật ở thời điểm đó: yêu cầu đã tới nơi và đang được xử lý.
#
# Chỉ nói được ngay vì audio của nó đã dựng sẵn (`pipeline/phrases.py`). Tổng
# hợp lúc chạy thì chính nó lại là quãng chờ mới, đúng thứ nó sinh ra để xoá.
_RECEIVED_MESSAGE = "Đã nhận yêu cầu của bạn, hệ thống đang xử lý."

STATIC_SPEECH: tuple[str, ...] = (
    _RECEIVED_MESSAGE,
    _ERROR_MESSAGE,
    _MISSING_AUDIO_MESSAGE,
)


def _next_debug_index() -> int:
    """Số thứ tự kế tiếp, dựa trên request*.wav đã có trong STORAGE_DIR."""
    os.makedirs(config.STORAGE_DIR, exist_ok=True)
    indices = [
        int(m.group(1))
        for f in glob.glob(os.path.join(config.STORAGE_DIR, "request*.wav"))
        if (m := re.match(r"request(\d+)\.wav$", os.path.basename(f)))
    ]
    return max(indices, default=0) + 1


def _save_debug_audio(name: str, audio_bytes: bytes) -> None:
    path = os.path.join(config.STORAGE_DIR, name)
    with open(path, "wb") as f:
        f.write(audio_bytes)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tts.OUTPUT_SAMPLE_RATE)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def _save_debug_pcm_as_wav(name: str, pcm_bytes: bytes) -> None:
    """Ghi PCM ra WAV để mở được bằng player khi debug.

    Ở chế độ stream, MCU nhận PCM trần; file trên đĩa mà thiếu header thì người
    debug không phát được — nên bọc header ở riêng đường ghi file này.
    """
    with open(os.path.join(config.STORAGE_DIR, name), "wb") as f:
        f.write(_pcm_to_wav(pcm_bytes))


def _image_extension(image_bytes: bytes) -> str:
    if image_bytes[:2] == b"\xff\xd8":
        return "jpg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "jpg"


def _save_debug_image(idx: int, image_bytes: bytes) -> None:
    ext = _image_extension(image_bytes)
    path = os.path.join(config.STORAGE_DIR, f"request{idx}.{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)


def _dummy_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)  # 0.1s im lặng
    return buf.getvalue()


@app.on_event("startup")
def preload_models() -> None:
    """Load STT/TTS và chạy thử mỗi model 1 lần.

    Lần infer đầu tiên của mỗi model tốn thêm thời gian khởi tạo (warm-up
    kernel, dựng batch engine...) so với các lần sau. Trả trước chi phí đó ở
    đây để request thật đầu tiên của người dùng không phải gánh thêm warm-up
    này — bấm gửi post là có kết quả ngay.

    Không còn model cục bộ nào cho ảnh: cả 4 handler đều đọc ảnh qua Gemini.
    """
    stt._load_asr()
    stt.transcribe(_dummy_wav())
    intent_local.warm()
    tts._load_tts()
    # Tiêu thụ hết generator: warm-up phải đi đúng đường stream mà /process
    # dùng, vì phiên giải mã theo frame của infer_stream có warm-up riêng.
    for _ in tts.synthesize_stream("Khởi động"):
        pass

    # Dựng sẵn audio cho mọi câu cố định. Lần đầu tốn một hai phút; các lần sau
    # đọc lại từ đĩa nên gần như tức thì.
    phrases.warm(extra=STATIC_SPEECH)

    lead_in = tts.prerendered(_RECEIVED_MESSAGE)
    if lead_in is None:
        logger.warning("Chưa dựng sẵn được câu chào đầu, nó sẽ phải tổng hợp lúc chạy")
    else:
        # Câu chào đầu cũng là thứ lấp đầy khoản đệm preroll. Ngắn hơn đệm thì
        # server vẫn phải chờ STT sinh thêm audio mới gửi được byte đầu, và cái
        # lợi "nghe ngay" mất sạch — nên nói rõ ra ở log thay vì để im.
        seconds = len(lead_in) / (tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE)
        logger.info(
            "Câu chào đầu dài %.2fs (đệm preroll %.2fs)%s",
            seconds, config.AUDIO_PREROLL_SECONDS,
            "" if seconds >= config.AUDIO_PREROLL_SECONDS else " - NGẮN HƠN ĐỆM",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


def _stream_audio(
    speech_pieces: Iterable[str],
    idx: int,
    started: float,
    processing: float,
    encode: Callable[[Iterator[bytes]], Iterator[bytes]] | None = None,
    byte_rate: int | None = None,
) -> Iterator[bytes]:
    """Đọc các mảnh text thành từng mảnh audio, vừa gửi vừa gom lại để ghi debug.

    `started` là mốc lúc request vào, `processing` là số giây STT/Gemini đã
    tiêu trước khi tới đây — cả hai chỉ dùng để ghi log đo thời gian.

    `encode` (vd. `tts.encode_mp3`) bọc thêm quanh PCM để nén trước khi gửi;
    bỏ trống thì gửi PCM trần như cũ. `byte_rate` phải khớp định dạng đã chọn
    để đệm preroll tính đúng số byte cần gom trước khi gửi mảnh đầu.
    """
    collected: list[bytes] = []
    first_chunk_at = None
    stream = tts.synthesize_text_stream(speech_pieces)
    if encode is not None:
        stream = encode(stream)

    rate = byte_rate if byte_rate is not None else tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE

    # Gom sẵn `AUDIO_PREROLL_SECONDS` giây audio rồi mới gửi byte đầu. Nhờ vậy
    # server luôn đi trước người nghe một quãng và MCU cứ đọc socket là có dữ
    # liệu — không cần ring buffer lớn phía thiết bị.
    preroll_bytes = int(config.AUDIO_PREROLL_SECONDS * rate)
    holding: list[bytes] = []
    held = 0

    recovered = False

    while True:
        try:
            chunk = next(stream)
        except StopIteration:
            break
        except Exception:  # noqa: BLE001
            if first_chunk_at is None:
                # Chưa gửi byte nào -> để lỗi nổi lên cho endpoint đổi thành
                # câu báo lỗi. Nuốt ở đây thì MCU nhận HTTP 200 rỗng và người
                # khiếm thị không nghe gì, cũng không biết vì sao.
                raise

            logger.exception("stream response%d đứt giữa chừng", idx)
            if recovered:
                break  # câu báo lỗi cũng hỏng nốt, không thử vòng nữa
            # Byte đầu đã rời server nên không đổi header được nữa, nhưng vẫn
            # nối thêm câu báo lỗi vào cuối. Dừng ngang ở đây thì người dùng
            # nghe cụt giữa câu rồi im — không có cách nào biết là hỏng hay hết.
            recovered = True
            stream = tts.synthesize_text_stream([_ERROR_MESSAGE])
            if encode is not None:
                stream = encode(stream)
            continue

        collected.append(chunk)

        if first_chunk_at is None:
            holding.append(chunk)
            held += len(chunk)
            if held < preroll_bytes:
                continue  # chưa đủ đệm, chưa gửi gì
            chunk = b"".join(holding)
            holding = []

        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - started
        yield chunk

    # Câu trả lời ngắn hơn mức đệm (ví dụ câu báo lỗi) vẫn phải phát ra.
    if holding:
        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - started
        yield b"".join(holding)

    payload = b"".join(collected)
    # ttfb là con số người dùng cảm nhận được (lúc bắt đầu nghe thấy tiếng);
    # tổng chỉ nói khi nào câu nói kết thúc. audio dài hơn (tổng - ttfb) nghĩa
    # là MCU phát kịp, không bị hụt tiếng giữa chừng. `rate` là byte-rate của
    # đúng định dạng đã gửi (PCM hoặc MP3 CBR) nên phép chia này luôn ra giây
    # audio thật, không riêng gì PCM.
    logger.info(
        "request%d | xử lý=%.2fs ttfb=%.2fs tổng=%.2fs audio=%.2fs",
        idx,
        processing,
        first_chunk_at if first_chunk_at is not None else 0.0,
        time.monotonic() - started,
        len(payload) / rate,
    )

    if payload:
        if encode is None:
            _save_debug_pcm_as_wav(f"response{idx}.wav", payload)
        else:
            _save_debug_audio(f"response{idx}.mp3", payload)


@app.post("/process")
def process(
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Xử lý một lệnh ảnh+audio, trả lời bằng audio stream phát dần được.

    Toàn bộ STT/OCR/Gemini chạy xong trước khi byte đầu tiên rời server, nên
    lỗi ở các bước đó vẫn đổi được thành câu báo lỗi bình thường. Chỉ bước TTS
    được stream — đó cũng là bước tốn giây, và là lý do người dùng phải đứng
    chờ trước khi nghe được gì.

    Sync def (không async): FastAPI chạy nó trong threadpool riêng thay vì
    trên event loop chính, nên STT/OCR/gọi Gemini/TTS của một request không
    chặn các request khác đang xử lý song song.
    """
    started = time.monotonic()
    idx = _next_debug_index()
    response_format = config.RESPONSE_FORMAT

    if response_format == "mp3_stream":
        # Nén MP3 CBR 32kbps trước khi gửi: 1/8 dung lượng so với PCM trần,
        # đỡ tải WiFi/MCU. `wav` vẫn cần PCM trần (đóng gói WAV, không nén).
        encode, byte_rate, media_type = (
            tts.encode_mp3,
            tts.MP3_BYTE_RATE,
            "audio/mpeg",
        )
    else:
        encode, byte_rate, media_type = (
            None,
            tts.OUTPUT_SAMPLE_RATE * _BYTES_PER_SAMPLE,
            "application/octet-stream",
        )

    try:
        if audio is None:
            pieces: Iterable[str] = [_MISSING_AUDIO_MESSAGE]
        else:
            # Ảnh không bắt buộc: `resolve_speech` nhận `None` và chỉ than phiền
            # khi intent thật sự cần ảnh.
            image_bytes = image.file.read() if image is not None else None
            audio_bytes = audio.file.read()
            _save_debug_audio(f"request{idx}.wav", audio_bytes)
            if image_bytes:
                _save_debug_image(idx, image_bytes)

            # Câu chào đi TRƯỚC, và `chain` giữ nó lười: `resolve_speech`
            # (kéo theo STT) chỉ chạy khi TTS đã lấy xong câu chào, nên
            # người dùng nghe thấy tiếng trong lúc STT còn đang chạy.
            # Xuống dòng ở cuối là dấu "câu trọn vẹn, đọc ngay" cho
            # `tts._sentences()`; thiếu nó thì câu chào nằm chờ mảnh text
            # sau, tức là chờ đúng STT mà nó sinh ra để khỏi phải chờ.
            # Câu chào này CŨNG là câu trấn an đầu tiên, nên câu kế tiếp phải
            # đếm từ lúc nó đọc xong. Đo chính xác vì audio của nó đã dựng sẵn.
            pieces = chain(
                [_RECEIVED_MESSAGE + "\n"],
                router.resolve_speech(
                    image_bytes, audio_bytes,
                    opening_seconds=tts.speaking_seconds(_RECEIVED_MESSAGE),
                ),
            )

        # Kéo tới MẢNH ĐẦU TIÊN ở đây, còn trong try. Mọi thứ trên đường tới
        # đó — gọi Gemini, mất mạng giữa luồng text, TTS/encode lỗi — vẫn đổi
        # được thành câu báo lỗi nghe được. Sau mảnh này thì header 200 đã
        # gửi, không rút lại được nữa.
        audio_stream = _stream_audio(
            pieces, idx, started, time.monotonic() - started,
            encode=encode, byte_rate=byte_rate,
        )
        body: Iterator[bytes] = chain([next(audio_stream)], audio_stream)
    except Exception:  # noqa: BLE001 - MCU must receive audio, never a JSON error.
        logger.exception("process() request%d thất bại", idx)
        body = _stream_audio(
            [_ERROR_MESSAGE], idx, started, time.monotonic() - started,
            encode=encode, byte_rate=byte_rate,
        )

    if response_format == "wav":
        # Gom trọn rồi mới gửi: mất thời gian chờ, đổi lại MCU nhận một file
        # hoàn chỉnh có Content-Length, không phụ thuộc việc đường truyền có
        # giữ đều 32 KB/s hay không.
        return Response(
            content=_pcm_to_wav(b"".join(body)),
            media_type="audio/wav",
        )

    return StreamingResponse(
        body,
        media_type=media_type,
        headers=_stream_headers(response_format),
    )
