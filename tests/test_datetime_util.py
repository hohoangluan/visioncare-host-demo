from datetime import datetime
from handlers import datetime_util
from schemas import Result


def test_datetime_speech_contains_now():
    r = datetime_util.handle(b"", "bây giờ là mấy giờ")
    assert isinstance(r, Result) and r.action is None
    now = datetime.now()
    assert str(now.year) in r.speech
    assert f"tháng {now.month}" in r.speech
    assert "giờ" in r.speech
