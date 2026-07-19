from datetime import datetime
from schemas import Result

_THU = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
        "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]  # weekday(): 0=Mon


def handle(image: bytes, command_text: str) -> Result:
    """Trả ngày giờ hiện tại (handler thật, không cần model/API)."""
    now = datetime.now()
    thu = _THU[now.weekday()]
    speech = (f"Bây giờ là {now.hour} giờ {now.minute} phút, "
              f"{thu} ngày {now.day} tháng {now.month} năm {now.year}")
    return Result(speech=speech)
