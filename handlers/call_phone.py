from schemas import Result
from handlers.text_utils import extract_name

# Dài/cụ thể trước, ngắn sau: "gọi điện thoại cho" phải đứng trước
# "gọi điện thoại" và "gọi điện cho"/"gọi điện", nếu không nó sẽ bị
# tiền tố ngắn hơn bắt trước và để lại phần thừa trong tên.
_CALL_PREFIXES = [
    "gọi điện thoại cho",
    "gọi điện thoại",
    "gọi điện cho",
    "gọi điện",
    "gọi cho",
    "gọi",
]


def handle(image: bytes, command_text: str) -> Result:
    name = extract_name(command_text, _CALL_PREFIXES)
    if not name.strip():
        return Result(speech="Bạn muốn gọi cho ai?", action=None)
    return Result(speech=f"Đang gọi {name}",
                  action={"type": "call", "name": name})
