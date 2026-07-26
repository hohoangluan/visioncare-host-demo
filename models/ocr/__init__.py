from models import vlm

from . import engine, prompts

__all__ = ["Mode", "read"]


class Mode:
    NORMAL = "normal"
    SPECIALIZED = "specialized"
    RAW = "raw"


def read(image: bytes, mode: str = Mode.NORMAL) -> str:
    """Nhận ảnh + mode, trả câu tiếng Việt sẵn sàng cho TTS."""
    raw_text = engine.extract_text(image)
    if not raw_text:
        return "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."
    if mode == Mode.RAW:
        return raw_text
    return vlm.generate_text(prompts.build(raw_text, mode))
