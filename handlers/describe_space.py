from collections.abc import Iterator

from models import vlm

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị (có thể mù bẩm sinh, chưa từng thấy hình "
    "ảnh) hình dung không gian phía trước bằng lời, KHÔNG phải để né vật cản "
    "(đã có chức năng cảnh báo riêng) mà để hiểu khung cảnh xung quanh và xác "
    "nhận có đang ở đúng nơi cần đến hay không. Mô tả chi tiết những gì có "
    "trong ảnh: loại không gian (phòng khách, hành lang, sân...), đồ vật và "
    "bàn ghế cùng cách bố trí, màu sắc chủ đạo. Nếu có biển báo, bảng hiệu, "
    "hoặc chữ nổi bật trong ảnh thì đọc nguyên văn nội dung đó. Trả lời bằng "
    "2-4 câu tiếng Việt tự nhiên, đầy đủ chi tiết quan trọng, không cần né "
    "tránh màu sắc hay chi tiết thị giác.\n"
    # Đo thật trên `storage/request1.jpg` (tờ 5.000đ): mô tả đọc thành "2.000
    # đồng", sai y hệt nhau cả hai lần chạy. Người khiếm thị không có cách nào
    # kiểm lại một con số đọc lên bằng giọng nói, và họ có thể tiêu tiền theo
    # nó. Đọc mệnh giá là việc của chức năng đọc tiền — chức năng đó có cơ chế
    # từ chối khi không chắc, còn ở đây thì không.
    "TUYỆT ĐỐI không đọc mệnh giá tờ tiền. Thấy tiền thì chỉ nói là có tờ tiền, "
    "rồi nhắc người dùng hỏi riêng để đọc mệnh giá. Cũng không đoán bất kỳ con "
    "số nào bạn không đọc được rõ ràng trong ảnh.\n"
    # 337 ký tự đo được ~16 giây đọc lên, mà câu 1 và câu 2 nhắc lại cùng một
    # con số. Người nghe không tua lại được, nên mỗi câu phải mang thông tin mới.
    "Mỗi câu nói một điều MỚI. Không nhắc lại thứ câu trước đã nói, dù bằng chữ "
    "khác. Nói hết ý thì dừng, không cần đủ 4 câu."
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    return vlm.generate_stream(_PROMPT, image=image)
