from schemas import Result
from handlers.text_utils import has_vietnamese


def handle(image: bytes, command_text: str) -> Result:
    """Dịch câu người nói. Có ký tự tiếng Việt -> VI->EN, ngược lại EN->VI."""
    # TODO: nối model dịch; áp dụng đúng hướng lên nội dung thật.
    direction = "VI->EN" if has_vietnamese(command_text) else "EN->VI"
    return Result(speech=f"[TRANSLATE] chưa cài model — hướng {direction} (kết quả giả)")
