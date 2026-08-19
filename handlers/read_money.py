from collections.abc import Iterator

from models import vlm

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị nhận biết mệnh giá tiền mặt Việt Nam Đồng (VND) qua camera.\n"
    "Nhìn vào ảnh và trả lời ĐÚNG TRỌNG TÂM mệnh giá tiền mặt đọc được.\n\n"
    "QUY TẮC NGUYÊN TẮC:\n"
    "- Mở đầu ngay bằng mệnh giá, KHÔNG dùng các từ dẫn dắt hoặc từ thừa như: "
    "\"Đây là\", \"Ảnh chụp\", \"Trước mặt bạn là\", \"Trong hình có\", \"Tôi thấy\".\n"
    "- Nếu có 1 tờ: đọc trực tiếp mệnh giá (ví dụ: \"50 nghìn đồng\", \"500 nghìn đồng\", \"10 nghìn đồng\").\n"
    "- Nếu có nhiều tờ: liệt kê ngắn gọn từng mệnh giá (ví dụ: \"10 nghìn đồng và 50 nghìn đồng\").\n"
    "- KHÔNG mô tả màu sắc (người nghe không cảm nhận được màu).\n"
    "- Nếu ảnh quá mờ, bị che khuất, tối đen hoặc không thấy rõ tờ tiền nào, PHẢI nói thẳng: "
    "\"Không thấy rõ tiền, vui lòng chụp lại.\"\n"
    "- TUYỆT ĐỐI không đoán bừa khi không chắc chắn."
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    return vlm.generate_stream(_PROMPT, image=image)
