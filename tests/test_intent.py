import pytest
from pipeline import intent
from schemas import Intent


@pytest.mark.parametrize("text,expected", [
    ("đọc chữ giúp tôi", Intent.OCR),
    ("dịch câu này sang tiếng anh", Intent.TRANSLATE),
    ("tìm cái điều khiển ở đâu", Intent.FIND),
    ("đây là tờ tiền mệnh giá bao nhiêu", Intent.MONEY),
    ("miêu tả xung quanh tôi", Intent.SPACE),
    ("bây giờ là mấy giờ", Intent.DATETIME),
    ("gọi cho mẹ", Intent.CALL),
    ("nhắn tin cho bố", Intent.MESSAGE),
])
def test_detect_keywords(text, expected):
    assert intent.detect(text) == expected


def test_detect_default_is_space():
    assert intent.detect("xyz không khớp gì cả") == Intent.SPACE
