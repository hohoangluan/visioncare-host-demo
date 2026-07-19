from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision tìm đồ vật + hướng ra.
    return Result(speech="[FIND] chưa nối API — hướng đồ vật (kết quả giả)")
