from models import vlm
from schemas import Result

_PROMPT = (
    "Nhìn ảnh tờ tiền Việt Nam Đồng và xác định mệnh giá. Tiền có thể bị che một "
    "phần, gấp nếp, cầm nghiêng hoặc chỉ thấy mặt sau — dùng mọi manh mối thị giác "
    "trong ảnh (số in trên tờ tiền, kích thước tương đối, hoạ tiết, hình chân dung/"
    "di tích) để xác định, không chỉ dựa vào chữ số rõ nét.\n\n"
    "QUAN TRỌNG: người nghe khiếm thị, có thể mù bẩm sinh và chưa từng thấy màu "
    "sắc hay hình ảnh — câu trả lời TUYỆT ĐỐI không được mô tả màu sắc, hoạ tiết "
    "hay bất cứ đặc điểm thị giác nào, chỉ nói kết quả mệnh giá. Trả lời đúng 1 câu "
    "tiếng Việt ngắn gọn, ví dụ: \"Đây là tờ 50 nghìn đồng.\" Nếu ảnh có nhiều tờ, "
    "đọc từng tờ trong cùng 1 câu, ví dụ: \"Có 2 tờ: 50 nghìn đồng và 20 nghìn "
    "đồng.\"\n\n"
    "CHỈ trả lời mệnh giá khi thật sự chắc chắn đọc được số hoặc nhận diện rõ "
    "đặc điểm tờ tiền — người dùng tin tưởng tuyệt đối vào câu trả lời để tiêu "
    "tiền, đoán sai một chữ số cũng gây thiệt hại thực tế. TUYỆT ĐỐI không đoán "
    "bừa giữa các mệnh giá gần giống nhau khi ảnh mờ/thiếu sáng/quá nhỏ. Nếu "
    "không đủ manh mối để chắc chắn, PHẢI nói thẳng: \"Tôi không chắc chắn, "
    "ảnh không đủ rõ để xác định mệnh giá, vui lòng chụp lại rõ hơn.\" — thà "
    "nói không biết còn hơn đoán sai."
)


def handle(image: bytes, command_text: str) -> Result:
    return Result(speech=vlm.generate(_PROMPT, image=image))
