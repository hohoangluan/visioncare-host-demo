from collections.abc import Callable, Iterator

import config
from models import vlm

from . import prompts
from .prompts import NO_TEXT_SENTINEL

__all__ = ["Mode", "read_stream", "answer_followup_stream", "NO_TEXT_SENTINEL"]

_NO_TEXT_MESSAGE = "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."

# Chỉ cần giữ lại nhiều hơn độ dài mốc quy ước một chút là đủ kết luận câu trả
# lời không phải mốc đó, rồi thả chữ đi ngay. Giữ nhiều hơn là bắt người dùng
# chờ vô ích.
_PEEK_CHARS = len(NO_TEXT_SENTINEL) + 4


class Mode:
    NORMAL = "normal"
    SPECIALIZED = "specialized"
    RAW = "raw"


def read_stream(
    image: bytes,
    mode: str = Mode.NORMAL,
    command_text: str = "",
    *,
    on_complete: Callable[[str], None] | None = None,
    on_no_text: Callable[[], str] | None = None,
) -> Iterator[str]:
    """Nhận ảnh + mode, trả từng mảnh câu tiếng Việt ngay khi Gemini viết ra.

    Một lượt gọi Gemini duy nhất: đọc chữ, chỉnh hướng và dịch cùng lúc.
    """
    stream = vlm.generate_stream(
        prompts.build(mode, command_text),
        image=image,
        model=config.GEMINI_OCR_MODEL,
    )
    head = ""

    for piece in stream:
        head += piece
        if len(head.strip()) <= _PEEK_CHARS:
            continue  # chưa đủ chữ để loại trừ mốc KHONG_CO_CHU
        yield head
        transcript = [head]
        for tail in stream:
            transcript.append(tail)
            yield tail
        if on_complete is not None:
            on_complete("".join(transcript))
        return

    # Stream kết thúc mà vẫn ngắn: đủ ngắn để là mốc quy ước.
    if head.strip().strip(".").strip() == NO_TEXT_SENTINEL:
        yield on_no_text() if on_no_text is not None else _NO_TEXT_MESSAGE
    elif head.strip():
        yield head
        if on_complete is not None:
            on_complete(head)


def answer_followup_stream(transcript: str, command_text: str) -> Iterator[str]:
    """Trả lời follow-up chỉ từ text cache; tuyệt đối không đính kèm ảnh mới."""
    yield from vlm.generate_stream(
        prompts.build_followup(transcript, command_text),
        image=None,
        model=config.GEMINI_OCR_MODEL,
    )
