from collections.abc import Iterator

from models import vlm

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị (có thể mù bẩm sinh, chưa từng thấy hình "
    "ảnh) hình dung không gian phía trước để di chuyển an toàn. Miêu tả không "
    "gian trong ảnh bằng 1-2 câu tiếng Việt ngắn gọn, tập trung vào lối đi, "
    "vật cản, khoảng cách ước lượng theo hướng giờ đồng hồ hoặc trái/phải. "
    "TUYỆT ĐỐI không mô tả màu sắc hay bất cứ chi tiết thị giác nào (ánh "
    "sáng, thẩm mỹ, hình ảnh) — chỉ nói thông tin giúp di chuyển an toàn."
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    # T16/E6 — đây là chức năng AN TOÀN: phải báo mọi vật cản trong khung hình.
    # Nhét command_text/focus/lịch sử/OCR/vị trí vào prompt sẽ làm model thiên
    # về đúng thứ người dùng vừa hỏi và giảm báo cáo thứ họ không hỏi — có thể
    # chính là vật sắp làm họ vấp. Vì vậy logic dưới đây cố ý giữ prompt cố định.
    return vlm.generate_stream(_PROMPT, image=image)
