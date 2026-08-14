from collections.abc import Iterator

from models import ocr


def handle(image: bytes, command_text: str) -> Iterator[str]:
    """Đọc chữ trong ảnh. Mặc định dịch sang tiếng Việt.

    "nguyên văn" -> đọc thô, không dịch. "chuyên ngành" -> dịch nhưng giữ
    nguyên thuật ngữ chuyên ngành.
    """
    raw = command_text.lower()
    if "nguyên văn" in raw:
        mode = ocr.Mode.RAW
    elif "chuyên ngành" in raw:
        mode = ocr.Mode.SPECIALIZED
    else:
        mode = ocr.Mode.NORMAL
    return ocr.read_stream(image, mode)
