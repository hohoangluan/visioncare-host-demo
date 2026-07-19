from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    """Đọc chữ trong ảnh. Mặc định dịch sang tiếng Việt.

    Nếu lệnh yêu cầu "nguyên văn"/"chuyên ngành" -> đọc thô, không dịch.
    """
    # TODO: nối model OCR; nếu cần thì dịch kết quả sang tiếng Việt.
    raw = command_text.lower()
    no_translate = "nguyên văn" in raw or "chuyên ngành" in raw
    if no_translate:
        return Result(speech="[OCR] chưa cài model — đọc nguyên văn (kết quả giả)")
    return Result(speech="[OCR] chưa cài model — đọc và dịch sang tiếng Việt (kết quả giả)")
