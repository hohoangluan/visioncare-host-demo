"""Dựng sẵn audio cho những câu nói cố định, để không phải tổng hợp lúc chạy.

Phần lớn thứ người dùng nghe không phải do model viết ra: câu xác nhận, câu
trấn an, câu báo lỗi, câu nhắc bấm thông báo đều viết cứng trong code và không
đổi giữa các lần chạy. Trước đây chúng vẫn đi qua TTS như mọi câu khác — đo
được 1.2 tới 2.6 giây một câu — nên đúng những câu sinh ra để lấp quãng chờ lại
tự tạo thêm quãng chờ.

Ở đây tổng hợp chúng một lần rồi giữ PCM lại: trong RAM cho lượt chạy này, trên
đĩa cho các lần khởi động sau. Lúc chạy, `tts._sentence_pcm()` chỉ còn việc cắt
bytes ra gửi — hết chờ.

Chỉ những câu KHÔNG chèn biến mới dựng sẵn được. Câu có tên bài hát, tên người,
địa chỉ thì vẫn phải tổng hợp lúc chạy; nhưng chúng thường được tách thành nhiều
câu (`tts._sentences()` cắt ở dấu chấm), nên nửa cố định vẫn trúng cache — ví dụ
"Đang mở nhạc, tìm bài X." tổng hợp thật, còn "Nếu màn hình đang bật, hãy nhấn
vào thông báo trên điện thoại." lấy sẵn.
"""

import hashlib
import logging
import os
import time
from collections.abc import Iterable

import config
from pipeline import image_quality, tts

logger = logging.getLogger("blind_assist")

# Phiên bản định dạng file cache. PCM trên đĩa là 16-bit mono ở
# `tts.OUTPUT_SAMPLE_RATE`; đổi định dạng mà quên đổi số này thì lần chạy sau
# đọc lại file cũ và phát ra tiếng rè.
_CACHE_VERSION = "1"

# Ngưỡng tin được của một file cache, tính theo giây audio.
#
# Câu ngắn nhất trong danh sách ("Đang gọi xe.") đo được 0.86s, nên bất cứ file
# nào ngắn hơn ngưỡng này đều là hỏng chứ không phải câu thật: bị ngắt lúc ghi,
# hoặc do một lần chạy nào đó ghi vào bằng TTS giả. Đã gặp thật — bộ test ghi
# đè PCM 2 byte vào đây, và vì "khác rỗng" nên lần chạy sau nạp lại nguyên
# xi: server im lặng ở đúng những câu đáng lẽ phát ngay, mà không báo lỗi gì.
_MIN_CACHED_SECONDS = 0.2
_MIN_CACHED_BYTES = int(_MIN_CACHED_SECONDS * tts.OUTPUT_SAMPLE_RATE * 2)


def _speech_modules() -> tuple:
    """Các module có câu nói cố định.

    Import trong hàm chứ không ở đầu file: `pipeline/tts.py` phải nạp được mà
    không kéo theo cả tầng handler (test TTS chạy độc lập, và handler kéo theo
    client HTTP).
    """
    from handlers import action_flow, music, navigation, phone, result_speech, ride, waiting
    from pipeline import router

    return (
        waiting, action_flow, result_speech,
        music, navigation, phone, ride,
        router, image_quality,
    )


def collect(extra: Iterable[str] = ()) -> tuple[str, ...]:
    """Mọi câu cố định, đã tách thành từng câu như lúc chạy thật.

    Tách bằng đúng `tts._sentences()` mà đường phát dùng: hằng số hai câu như
    "Đã mở ứng dụng đặt xe. Vui lòng nhấn..." lúc chạy có thể bị cắt làm đôi, nên
    dựng sẵn cả cụm là dựng một khoá không bao giờ được tra tới.

    Mỗi hằng số đưa vào `_sentences()` RIÊNG một lượt, đúng như lúc chạy handler
    đẩy ra từng câu trọn vẹn. Nối chúng lại rồi cắt một thể sẽ ra kết quả khác:
    luật gộp câu ngắn (`_MIN_SENTENCE_CHARS`) sẽ dính câu này vào câu kia, và
    khoá dựng ra không khớp với thứ người dùng thật sự nghe.
    """
    sources: list[str] = []
    for module in _speech_modules():
        sources.extend(getattr(module, "STATIC_SPEECH", ()))
    sources.extend(extra)

    seen: dict[str, None] = {}
    for text in sources:
        if not text.strip():
            continue
        for sentence in tts._sentences([text]):
            seen.setdefault(tts.phrase_key(sentence), None)
    return tuple(seen)


def _cache_path(sentence: str) -> str:
    """Đường dẫn file PCM của một câu.

    Khoá gồm cả giọng và style: đổi `TTS_VOICE` mà vẫn đọc file cũ thì server
    phát ra hai giọng khác nhau xen kẽ trong cùng một câu trả lời.
    """
    key = "|".join(
        [_CACHE_VERSION, config.TTS_VOICE, config.TTS_STYLE,
         str(tts.OUTPUT_SAMPLE_RATE), sentence]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(config.PHRASE_CACHE_DIR, f"{digest}.pcm")


def _prune(keep: set[str]) -> None:
    """Xoá file PCM của những câu không còn trong code.

    Sửa một chữ trong câu là sinh hash mới; không dọn thì thư mục cache phình
    theo từng lần sửa chữ mà không ai để ý.
    """
    try:
        stale = [
            name for name in os.listdir(config.PHRASE_CACHE_DIR)
            if name.endswith(".pcm") and os.path.join(config.PHRASE_CACHE_DIR, name) not in keep
        ]
    except OSError:
        return

    for name in stale:
        try:
            os.remove(os.path.join(config.PHRASE_CACHE_DIR, name))
        except OSError:
            pass
    if stale:
        logger.info("Dọn %d câu dựng sẵn không còn dùng", len(stale))


def generate_chime_pcm(duration: float = 1.5, sample_rate: int = 16000) -> bytes:
    """Sinh âm thanh tiếng đàn Piano đệm êm dịu, ấm áp ("Bính Boong" Piano Earcon, 16kHz PCM)."""
    import numpy as np
    t = np.linspace(0, duration, int(sample_rate * duration), False)

    def piano_note(freq: float, start_time: float, decay: float = 2.2) -> np.ndarray:
        t_note = t - start_time
        mask = (t_note >= 0)
        tn = np.maximum(0, t_note)
        # Bội âm dây đàn Piano tự nhiên (f0, 2f0, 3f0, 4f0, 5f0)
        harms = (
            1.00 * np.sin(2 * np.pi * freq * 1.0 * tn) +
            0.45 * np.sin(2 * np.pi * freq * 2.0 * tn) +
            0.20 * np.sin(2 * np.pi * freq * 3.0 * tn) +
            0.10 * np.sin(2 * np.pi * freq * 4.0 * tn) +
            0.04 * np.sin(2 * np.pi * freq * 5.0 * tn)
        )
        env = np.exp(-decay * tn)
        attack = np.minimum(tn / 0.005, 1.0)
        return harms * env * attack * mask

    # Rải phím đàn Piano: C4 (261.6Hz), G4 (392Hz), C5 (523.25Hz), E5 (659.25Hz)
    n1 = piano_note(261.63, 0.00, decay=1.8)
    n2 = piano_note(392.00, 0.08, decay=2.2)
    n3 = piano_note(523.25, 0.16, decay=2.6)
    n4 = piano_note(659.25, 0.24, decay=3.2)
    signal = (n1 * 0.38 + n2 * 0.30 + n3 * 0.20 + n4 * 0.12)
    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal = signal / max_val * 0.40
    return (signal * 32767).astype(np.int16).tobytes()


def generate_warm_melodic_pcm() -> bytes:
    """Đọc warm_melodic.wav và resample về 16kHz PCM mono."""
    wav_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "warm_melodic.wav")
    if not os.path.exists(wav_path):
        return generate_chime_pcm()
    try:
        import wave
        import numpy as np
        with wave.open(wav_path, "rb") as w:
            sr_in = w.getframerate()
            frames = w.readframes(w.getnframes())
        pcm_in = np.frombuffer(frames, dtype=np.int16)
        if sr_in != 16000:
            from scipy import signal
            num_samples = int(len(pcm_in) * 16000 / sr_in)
            pcm_16k = signal.resample(pcm_in, num_samples).astype(np.int16)
            return pcm_16k.tobytes()
        return pcm_in.tobytes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không đọc được warm_melodic.wav: %s", exc)
        return generate_chime_pcm()


def warm(extra: Iterable[str] = ()) -> int:
    """Nạp audio dựng sẵn vào bộ nhớ, tổng hợp những câu chưa có trên đĩa.

    Chạy đồng bộ lúc khởi động, cố ý: lần đầu tốn một hai phút (mỗi câu một lần
    gọi model), các lần sau chỉ là đọc vài chục file nhỏ. Làm ở luồng nền thì
    tiết kiệm được lần khởi động đầu, đổi lại có hai luồng cùng gọi vào một
    phiên ONNX — không đáng đổi.

    Trả về số câu đã nạp.
    """
    if not config.TTS_PRERENDER:
        logger.info("TTS_PRERENDER=0, bỏ qua dựng sẵn câu nói")
        return 0

    sentences = collect(extra)
    os.makedirs(config.PHRASE_CACHE_DIR, exist_ok=True)

    started = time.monotonic()
    paths: set[str] = set()
    synthesized = 0

    for sentence in sentences:
        path = _cache_path(sentence)
        paths.add(path)

        pcm = b""
        mode = getattr(config, "AUDIO_PREROLL_MODE", "warm_melodic")
        if sentence == "Đã tiếp nhận yêu cầu" and mode != "voice":
            if mode == "warm_melodic":
                pcm = generate_warm_melodic_pcm()
            elif mode == "chime":
                pcm = generate_chime_pcm()
        elif os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    pcm = f.read()
            except OSError:
                pcm = b""
            if 0 < len(pcm) < _MIN_CACHED_BYTES:
                logger.warning("Bỏ file cache quá ngắn, dựng lại: %s", sentence)
                pcm = b""

        if not pcm:
            try:
                pcm = b"".join(tts.synthesize_stream(sentence))
            except Exception:  # noqa: BLE001 - thiếu một câu không được chặn server
                logger.exception("Không dựng sẵn được câu: %s", sentence)
                continue
            synthesized += 1
            try:
                # Ghi ra file tạm rồi đổi tên: bị ngắt giữa chừng thì lần sau
                # đọc phải file PCM cụt và phát ra tiếng rè, chứ không hỏng rõ.
                tmp = f"{path}.tmp"
                with open(tmp, "wb") as f:
                    f.write(pcm)
                os.replace(tmp, path)
            except OSError:
                logger.warning("Không ghi được cache câu: %s", sentence)

        tts.register_phrase(sentence, pcm)

    _prune(paths)
    logger.info(
        "Dựng sẵn %d câu nói (%d câu tổng hợp mới) trong %.1fs",
        tts.phrase_count(), synthesized, time.monotonic() - started,
    )
    return tts.phrase_count()
