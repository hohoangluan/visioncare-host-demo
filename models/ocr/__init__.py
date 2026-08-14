from collections.abc import Iterator

from models import vlm

from . import prompts
from .prompts import NO_TEXT_SENTINEL

__all__ = ["Mode", "read_stream", "NO_TEXT_SENTINEL"]

_NO_TEXT_MESSAGE = "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."

# Chỉ cần giữ lại nhiều hơn độ dài mốc quy ước một chút là đủ kết luận câu trả
# lời không phải mốc đó, rồi thả chữ đi ngay. Giữ nhiều hơn là bắt người dùng
# chờ vô ích.
_PEEK_CHARS = len(NO_TEXT_SENTINEL) + 4


class Mode:
    NORMAL = "normal"
    SPECIALIZED = "specialized"
    RAW = "raw"


def read_stream(image: bytes, mode: str = Mode.NORMAL) -> Iterator[str]:
    """Nhận ảnh + mode, trả từng mảnh câu tiếng Việt ngay khi Gemini viết ra.

    Một lượt gọi Gemini duy nhất: đọc chữ, chỉnh hướng và dịch cùng lúc.
    """
    stream = vlm.generate_stream(prompts.build(mode), image=image)
    head = ""

    for piece in stream:
        head += piece
        if len(head.strip()) <= _PEEK_CHARS:
            continue  # chưa đủ chữ để loại trừ mốc KHONG_CO_CHU
        yield head
        yield from stream
        return

    # Stream kết thúc mà vẫn ngắn: đủ ngắn để là mốc quy ước.
    if head.strip().strip(".").strip() == NO_TEXT_SENTINEL:
        yield _NO_TEXT_MESSAGE
    elif head.strip():
        yield head
