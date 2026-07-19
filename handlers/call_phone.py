from schemas import Result

_CALL_PREFIXES = ["gọi điện cho", "gọi cho", "gọi điện", "gọi"]


def _extract_name(command_text: str) -> str:
    t = command_text.strip().lower()
    for prefix in _CALL_PREFIXES:  # dài trước, ngắn sau
        if t.startswith(prefix):
            return t[len(prefix):].strip()
    return t


def handle(image: bytes, command_text: str) -> Result:
    name = _extract_name(command_text)
    return Result(speech=f"Đang gọi {name}",
                  action={"type": "call", "name": name})
