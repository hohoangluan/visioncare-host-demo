from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision miêu tả không gian.
    return Result(speech="[SPACE] chưa nối API — miêu tả không gian (kết quả giả)")
