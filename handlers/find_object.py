from collections.abc import Iterator

from models import vlm

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị (có thể mù bẩm sinh, chưa từng thấy hình "
    "ảnh) tìm đồ vật và di chuyển. Nhìn ảnh và trả lời đúng 1 câu tiếng Việt "
    "ngắn gọn, có đủ: hướng (theo giờ đồng hồ hoặc trái/phải), khoảng cách "
    "ước lượng (mét), và vật cản trên đường đi nếu phát hiện được. Nếu giúp "
    "nhận biết bằng tay khi chạm tới vật, có thể thêm hình dạng/kích thước "
    "cầm nắm (ví dụ: \"dẹt, hình chữ nhật\", \"tròn, to bằng nắm tay\"). "
    "TUYỆT ĐỐI không mô tả màu sắc — người nghe không cảm nhận được màu. "
    "Không liệt kê chung chung những gì nhìn thấy, chỉ nói thông tin giúp "
    "định vị và di chuyển. Ví dụ: \"Cửa ở phía trước, hướng 1 giờ, cách "
    "khoảng 4 mét. Giữa đường có một cái ghế lệch sang trái, đi thẳng rồi "
    "hơi chuyển phải để tránh.\"\n\n"
    "TUYỆT ĐỐI không đoán bừa khi không chắc chắn — người dùng sẽ dựa vào câu "
    "trả lời để di chuyển thật, đoán sai có thể khiến họ va chạm/vấp ngã. Nếu "
    "không thấy rõ vật cần tìm trong ảnh (mờ, thiếu sáng, quá xa, bị che "
    "khuất, hoặc không có trong ảnh), PHẢI nói thẳng: \"Tôi không thấy rõ "
    "[tên vật], vui lòng chụp lại gần hơn/rõ hơn.\" — không tự bịa hướng hay "
    "khoảng cách khi không xác định được. Câu lệnh của người dùng: "
    "\"{command_text}\""
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    prompt = _PROMPT.format(command_text=command_text)
    return vlm.generate_stream(prompt, image=image)
