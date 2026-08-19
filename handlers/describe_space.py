from collections.abc import Iterator

from models import vlm

# Prompt này đã qua vài vòng đo, và bài học lớn nhất là: RÚT NGẮN BẰNG CÁCH XẾP
# HẠNG, không phải bằng cách dặn "ngắn thôi".
#
# Bản đầu (2-4 câu, "đầy đủ chi tiết quan trọng") cho ra 310 ký tự ~ 20 GIÂY đọc
# lên cho câu hỏi "trước mặt có gì", mà một câu trọn vẹn dành cho quần áo và
# logo trên áo một người lạ. Bản chỉ thêm trần "dưới 40 từ" thì model tụt xuống
# 10 từ và bỏ sạch phần bố cục — thứ người dùng thật sự cần. Nên ở đây có cả
# sàn lẫn trần, và có thứ tự ưu tiên nói rõ cái gì bỏ được trước.
#
# Mục tiêu: 25-40 từ, khoảng 9-11 giây nghe.
_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị (có thể mù bẩm sinh, chưa từng thấy hình "
    "ảnh) hình dung không gian phía trước bằng lời. KHÔNG phải để né vật cản "
    "(đã có chức năng cảnh báo riêng) mà để hiểu khung cảnh xung quanh và biết "
    "mình có đang ở đúng nơi cần đến hay không.\n"
    "\n"
    "Nói đủ ba phần, đúng thứ tự:\n"
    # Vài từ thôi, nhưng BẮT BUỘC và phải đứng đầu: thiếu nó thì mọi chi tiết
    # sau mất chỗ bám — "bên trái có cột lớn" chẳng nói lên gì nếu người nghe
    # không biết mình đang trong quán cà phê hay ngoài vỉa hè.
    "1. Loại không gian, vài từ: phòng khách, phòng học, quán cà phê, hành "
    "lang, vỉa hè, trong nhà, ngoài trời. Không chắc thì nói ước chừng, nhưng "
    "không được bỏ.\n"
    # Phần dài nhất và là lý do chức năng này tồn tại.
    "2. Bố cục — phần chính, chiếm phần lớn câu trả lời: đồ đạc lớn kê phía "
    "nào, lối đi trống ở đâu, có mấy người và họ đứng hay ngồi phía nào. Nói "
    "theo hướng trái, phải, giữa, phía sau so với người chụp.\n"
    "3. Biển báo hoặc bảng hiệu NGẮN giúp nhận ra chỗ này — tên quán, số phòng, "
    "biển chỉ dẫn. Đọc nguyên văn, tối đa một câu.\n"
    "\n"
    "Độ dài: 2-3 câu, TỔNG CỘNG 25 đến 40 từ. Dưới 20 từ nghĩa là bạn đã bỏ "
    "mất phần 2.\n"
    "\n"
    "KHÔNG được:\n"
    # Đo thật: "Đây là một không gian trong nhà" tốn 6 từ cho thứ "trong nhà"
    # nói bằng 2. Trong ngân sách 40 từ, mở bài là một phần bảy trôi đi.
    "- Mở đầu bằng \"Đây là\", \"Ảnh chụp\", \"Trước mặt bạn là\". Vào thẳng.\n"
    # Đo thật: "Không thấy biển hiệu nào trong khung hình này" — trọn một câu
    # để báo một thứ KHÔNG có.
    "- Kể thứ không có. Không có biển hiệu thì im về biển hiệu.\n"
    # Đo thật: "nam thanh niên tóc đen đeo kính gọng đen, mặc áo thun đen có chữ
    # PARADOX và logo màu cam" — hết một câu cho quần áo một người lạ, trong khi
    # người dùng chỉ cần biết là có người đứng đó.
    "- Tả quần áo, tóc, kính, hay chữ và logo in trên áo người trong ảnh. Chỉ "
    "nói có mấy người và họ ở phía nào.\n"
    # Đo thật trên `tests/fixtures/ocr_screenshot.png`: chép nguyên mục lục tài
    # liệu, 46 từ. Đọc trọn văn bản là việc của chức năng đọc chữ, chức năng đó
    # có chế độ dịch và đọc nguyên văn riêng.
    "- Đọc hết một trang văn bản hay tài liệu. Ảnh chủ yếu là chữ thì chỉ nói "
    "đó là trang giấy hoặc màn hình có chữ, rồi nhắc người dùng hỏi riêng để "
    "đọc chữ.\n"
    # Đo thật trên `storage/request1.jpg` (tờ 5.000đ): mô tả đọc thành "2.000
    # đồng", sai y hệt nhau cả hai lần chạy. Người khiếm thị không có cách nào
    # kiểm lại một con số đọc lên bằng giọng nói, và họ có thể tiêu tiền theo
    # nó. Đọc mệnh giá là việc của chức năng đọc tiền — chức năng đó có cơ chế
    # từ chối khi không chắc, còn ở đây thì không.
    "- Đọc mệnh giá tờ tiền. Thấy tiền thì chỉ nói là có tờ tiền, rồi nhắc hỏi "
    "riêng để đọc mệnh giá. Cũng không đoán con số nào bạn không đọc rõ.\n"
    # 337 ký tự đo được ~16 giây đọc lên, mà câu 1 và câu 2 nhắc lại cùng một
    # con số. Người nghe không tua lại được, nên mỗi câu phải mang thông tin mới.
    "- Nhắc lại thứ câu trước đã nói, dù bằng chữ khác. Hết ý thì dừng.\n"
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    return vlm.generate_stream(_PROMPT, image=image)
