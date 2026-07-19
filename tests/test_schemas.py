from schemas import Intent, Result


def test_intent_has_eight_values():
    vals = {Intent.OCR, Intent.TRANSLATE, Intent.FIND, Intent.MONEY,
            Intent.SPACE, Intent.DATETIME, Intent.CALL, Intent.MESSAGE}
    assert vals == {"ocr", "translate", "find", "money", "space",
                    "datetime", "call", "message"}


def test_result_defaults_action_none():
    r = Result(speech="xin chào")
    assert r.speech == "xin chào"
    assert r.action is None


def test_result_with_action():
    r = Result(speech="Đang gọi Mẹ", action={"type": "call", "name": "Mẹ"})
    assert r.action["type"] == "call"
