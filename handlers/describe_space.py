from models import vlm
from schemas import Result

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị (có thể mù bẩm sinh, chưa từng thấy hình "
    "ảnh) hình dung không gian phía trước để di chuyển an toàn. Miêu tả không "
    "gian trong ảnh bằng 1-2 câu tiếng Việt ngắn gọn, tập trung vào lối đi, "
    "vật cản, khoảng cách ước lượng theo hướng giờ đồng hồ hoặc trái/phải. "
    "TUYỆT ĐỐI không mô tả màu sắc hay bất cứ chi tiết thị giác nào (ánh "
    "sáng, thẩm mỹ, hình ảnh) — chỉ nói thông tin giúp di chuyển an toàn."
)


def handle(image: bytes, command_text: str) -> Result:
    return Result(speech=vlm.generate(_PROMPT, image=image))
