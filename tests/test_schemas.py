import schemas
from schemas import Intent


def test_intent_has_four_values():
    vals = {Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE}
    assert vals == {"ocr", "find", "money", "space"}


def test_no_result_wrapper_left():
    """Handler trả thẳng luồng mảnh text; không còn dataclass một trường bọc lại."""
    assert not hasattr(schemas, "Result")
