import inspect
import logging
import time
from collections.abc import Iterator

from schemas import Intent
from pipeline import image_quality, stt, intent as intent_mod
from handlers import (
    ocr, find_object, read_money, describe_space, describe_hazard, chat,
    nav_start, nav_stop, contact_call, emergency_call, ride_quote, ride_confirm,
    music_play, music_stop, music_volume
)
from handlers.waiting import with_progress_notice

logger = logging.getLogger("blind_assist")

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
    Intent.HAZARD: describe_hazard,
    Intent.CHAT: chat,
    Intent.NAV_START: nav_start,
    Intent.NAV_STOP: nav_stop,
    Intent.CONTACT_CALL: contact_call,
    Intent.EMERGENCY_CALL: emergency_call,
    Intent.RIDE_QUOTE: ride_quote,
    Intent.RIDE_CONFIRM: ride_confirm,
    Intent.MUSIC_PLAY: music_play,
    Intent.MUSIC_STOP: music_stop,
    Intent.MUSIC_VOLUME: music_volume,
}

# Chỉ còn HAI câu, và cả hai đều nói về một trạng thái LỖI của hệ thống, không
# phải về việc người dùng nói khó hiểu.
#
# Câu thứ ba ("tôi chưa hiểu bạn muốn gì") đã bỏ cùng với nhãn `unknown`: câu
# nghe ra chữ mà không ra nghĩa giờ về `chat`, và chính Gemini nói mình chưa
# hiểu — nó đọc được nguyên văn nên nói được câu sát tình huống, thay vì đọc một
# câu soạn sẵn cho mọi trường hợp.
_NO_SPEECH_MESSAGE = "Xin lỗi, tôi không nghe rõ, vui lòng nói lại."
# Không nhận là "tôi chưa hiểu": lúc này hệ thống chưa hiểu được câu nào cả, kể
# cả câu hoàn hảo. Nói đúng thứ đang xảy ra để người dùng biết cứ thử lại.
_CLASSIFY_FAILED_MESSAGE = "Hệ thống đang bận, bạn vui lòng thử lại sau giây lát."

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (_NO_SPEECH_MESSAGE, _CLASSIFY_FAILED_MESSAGE)


def resolve_speech(
    image: bytes | None, audio: bytes, opening_seconds: float = 0.0
) -> Iterator[str]:
    """Pipeline audio -> STT -> intent -> handler -> từng mảnh câu cần đọc.

    Trả luồng mảnh text chứ không phải chuỗi hoàn chỉnh, và không tự gọi TTS:
    `app.py` bắt đầu tổng hợp giọng nói từ câu đầu trong lúc Gemini còn đang
    viết phần sau.

    Câu trấn an bọc quanh CẢ pipeline, không riêng handler: STT với phân loại
    intent tốn khoảng 2 giây trước khi handler chạy dòng đầu tiên, nên đặt đồng
    hồ ở trong là 2 giây đó không ai đếm và người dùng chờ dài hơn đúng ngần ấy.

    `opening_seconds`: độ dài câu chào `app.py` vừa nói trước khi gọi vào đây.
    """
    return with_progress_notice(_resolve(image, audio), opening_seconds=opening_seconds)


def _resolve(image: bytes | None, audio: bytes) -> Iterator[str]:
    from handlers.action_flow import device_state
    state = device_state()
    if state.get("music_playing"):
        logger.info("Fast-Bypass: đang nghe nhạc -> dừng nhạc ngắt STT/Intent")
        from handlers import music
        yield from music.handle_stop(image, "", {})
        return
    if state.get("navigating"):
        logger.info("Fast-Bypass: đang chỉ đường -> dừng chỉ đường ngắt STT/Intent")
        from handlers import navigation
        yield from navigation.handle_stop(image, "", {})
        return

    started = time.monotonic()
    command_text = stt.transcribe(audio)
    stt_seconds = time.monotonic() - started

    intent_started = time.monotonic()
    res = intent_mod.detect_with_params(command_text)
    # Đo riêng, không gộp vào `handler`: đây là một lượt gọi Gemini TRỌN VẸN nằm
    # nối tiếp giữa STT và handler, và người dùng chờ hết nó trước khi công việc
    # thật bắt đầu. Gộp vào chỗ khác thì không ai thấy nó tốn bao nhiêu.
    intent_seconds = time.monotonic() - intent_started
    if isinstance(res, tuple):
        intent_name, params = res
    else:
        intent_name, params = res, {}

    if intent_name == Intent.UNKNOWN:
        # `unknown` không còn là kết quả phân loại — nó chỉ còn là trạng thái
        # LỖI, và hai lỗi này người dùng phải xử lý theo hai cách khác nhau:
        # không nghe ra chữ nào thì nói to hơn / gần mic hơn, còn hệ thống bận
        # thì chỉ cần thử lại, không phải nói khác đi.
        logger.info(
            "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs handler=0.00s",
            command_text, intent_name, stt_seconds, intent_seconds,
        )
        yield _CLASSIFY_FAILED_MESSAGE if params.get("classify_failed") else _NO_SPEECH_MESSAGE
        return

    # Chất lượng ảnh chỉ xét được khi đã biết câu hỏi cần gì ở ảnh. Đặt trước
    # gate này thì "gọi cho mẹ" bị một tấm ảnh xấu chặn mất, dù handler gọi
    # điện không hề mở ảnh ra xem.
    reject_reason = image_quality.reject_reason(intent_name, image)
    if reject_reason is not None:
        logger.info(
            "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs -> từ chối ảnh",
            command_text, intent_name, stt_seconds, intent_seconds,
        )
        yield reject_reason
        return

    handler_started = time.monotonic()
    handler_mod = _HANDLERS.get(intent_name, chat)

    sig = inspect.signature(handler_mod.handle)
    if "params" in sig.parameters:
        pieces = handler_mod.handle(image, command_text, params=params)
    else:
        pieces = handler_mod.handle(image, command_text)

    first = next(iter(pieces), "")
    # handler đo tới MẢNH ĐẦU, không phải tới lúc Gemini viết xong
    logger.info(
        "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs handler=%.2fs",
        command_text, intent_name, stt_seconds, intent_seconds,
        time.monotonic() - handler_started,
    )

    if first:
        yield first
    yield from pieces
