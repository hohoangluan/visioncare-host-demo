from schemas import Result

_MSG_PREFIXES = ["nhắn tin cho", "nhắn cho", "nhắn tin", "nhắn"]


def _extract_name(command_text: str) -> str:
    t = command_text.strip().lower()
    for prefix in _MSG_PREFIXES:
        if t.startswith(prefix):
            return t[len(prefix):].strip()
    return t


def handle(image: bytes, command_text: str) -> Result:
    name = _extract_name(command_text)
    # TODO: tách nội dung tin nhắn từ lệnh; giờ để rỗng.
    return Result(speech=f"Đã nhắn {name}",
                  action={"type": "message", "name": name, "text": ""})
