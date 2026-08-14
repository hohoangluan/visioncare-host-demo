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
        if os.path.exists(path):
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
