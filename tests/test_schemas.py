from schemas import Intent, Result


def test_intent_has_five_values():
    vals = {Intent.OCR, Intent.TRANSLATE, Intent.FIND, Intent.MONEY, Intent.SPACE}
    assert vals == {"ocr", "translate", "find", "money", "space"}


def test_result_holds_speech():
    r = Result(speech="xin chào")
    assert r.speech == "xin chào"


def test_result_has_no_action_field():
    # Phạm vi chỉ còn chức năng AI -> không còn action đẩy sang điện thoại.
    assert not hasattr(Result(speech="x"), "action")
