from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision tìm đồ vật + chỉ đường.
    # Mỗi lần hỏi trả 1 câu (stateless — người dùng tự hỏi lại khi đã di
    # chuyển để cập nhật hướng), nhưng câu đó phải chi tiết: hướng (giờ
    # hoặc trái/phải), khoảng cách ước lượng, và vật cản trên đường đi
    # nếu phát hiện được. Ví dụ câu thật khi nối API xong:
    # "Cửa ở phía trước, hướng 1 giờ, cách khoảng 4 mét. Giữa đường có
    # một cái ghế lệch sang trái, đi thẳng rồi hơi chuyển phải để tránh."
    return Result(
        speech="[FIND] chưa nối API — hướng, khoảng cách, vật cản (kết quả giả)"
    )
