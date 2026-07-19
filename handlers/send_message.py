from schemas import Result
from handlers.text_utils import extract_name

# Dài/cụ thể trước, ngắn sau: "gửi tin nhắn cho" phải đứng trước
# "gửi tin nhắn"/"nhắn tin cho", nếu không nó sẽ bị tiền tố ngắn hơn
# bắt trước (hoặc không khớp gì cả) và để lại phần thừa trong tên.
_MSG_PREFIXES = [
    "gửi tin nhắn cho",
    "nhắn tin cho",
    "gửi tin nhắn",
    "nhắn cho",
    "nhắn tin",
    "nhắn",
]


def handle(image: bytes, command_text: str) -> Result:
    name = extract_name(command_text, _MSG_PREFIXES)
    if not name.strip():
        return Result(speech="Bạn muốn nhắn tin cho ai?", action=None)
    # TODO: tách nội dung tin nhắn từ lệnh; giờ để rỗng.
    return Result(speech=f"Đã nhắn {name}",
                  action={"type": "message", "name": name, "text": ""})
