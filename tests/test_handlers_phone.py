from handlers import call_phone, send_message


def test_call_extracts_name_and_action():
    r = call_phone.handle(b"", "gọi cho mẹ")
    assert r.action == {"type": "call", "name": "mẹ"}
    assert "mẹ" in r.speech.lower()
    assert "gọi" in r.speech.lower()


def test_call_without_cho():
    r = call_phone.handle(b"", "gọi bố")
    assert r.action["name"] == "bố"


def test_message_action_shape():
    r = send_message.handle(b"", "nhắn tin cho chị")
    assert r.action["type"] == "message"
    assert r.action["name"] == "chị"
    assert "text" in r.action
    assert "nhắn" in r.speech.lower()
