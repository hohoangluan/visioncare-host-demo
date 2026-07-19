from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision đọc mệnh giá tiền.
    return Result(speech="[MONEY] chưa nối API — mệnh giá (kết quả giả)")
