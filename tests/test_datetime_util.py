from datetime import datetime
from handlers import datetime_util
from schemas import Result


def test_datetime_speech_contains_now():
    # Capture time before and after to handle minute/midnight boundary flakes
    # Handler reads once; we read twice, so they could differ at boundaries
    time_before = datetime.now()
    r = datetime_util.handle(b"", "bây giờ là mấy giờ")
    time_after = datetime.now()

    # Basic checks: Result type and no action
    assert isinstance(r, Result) and r.action is None

    speech = r.speech

    # Try to match against either time_before or time_after
    # Accept if speech contains all components for at least one of them
    matched_time = None
    for now in [time_before, time_after]:
        # Build expected components for this time
        year_str = str(now.year)
        month_str = f"tháng {now.month}"
        day_str = f"ngày {now.day}"
        time_str = f"{now.hour} giờ {now.minute} phút"

        # Vietnamese weekday names (Monday=0 per datetime.weekday())
        weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
                        "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        weekday_str = weekday_names[now.weekday()]

        # Check if this time matches all components
        if (year_str in speech and month_str in speech and
            day_str in speech and time_str in speech and weekday_str in speech):
            matched_time = now
            break

    assert matched_time is not None, (
        f"Speech did not match expected date/time components.\n"
        f"Speech: {speech}\n"
        f"Time before: {time_before}\n"
        f"Time after: {time_after}"
    )
