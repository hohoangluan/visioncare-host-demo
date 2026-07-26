from models import ocr
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
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
    return Result(speech=ocr.read(image, mode))
