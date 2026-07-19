import pytest

from handlers import call_phone, send_message

# Danh sách tiền tố kỳ vọng cuối cùng (dài trước, ngắn sau) - dùng để
# kiểm tra MỌI nhánh tiền tố được nhận diện đúng, bao gồm các phrasing
# còn thiếu ở Fix A ("gọi điện thoại cho") và Fix B ("gửi tin nhắn cho").
CALL_PREFIXES = [
    "gọi điện thoại cho",
    "gọi điện thoại",
    "gọi điện cho",
    "gọi điện",
    "gọi cho",
    "gọi",
]

MSG_PREFIXES = [
    "gửi tin nhắn cho",
    "nhắn tin cho",
    "gửi tin nhắn",
    "nhắn cho",
    "nhắn tin",
    "nhắn",
]


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


@pytest.mark.parametrize("prefix", CALL_PREFIXES)
def test_call_every_prefix_extracts_name(prefix):
    r = call_phone.handle(b"", f"{prefix} mẹ")
    assert r.action == {"type": "call", "name": "mẹ"}


@pytest.mark.parametrize("prefix", MSG_PREFIXES)
def test_message_every_prefix_extracts_name(prefix):
    r = send_message.handle(b"", f"{prefix} mẹ")
    assert r.action["type"] == "message"
    assert r.action["name"] == "mẹ"


def test_call_prefix_goi_dien_thoai_cho():
    # Fix A: "gọi điện thoại cho" từng bị "gọi điện" bắt trước, ra tên sai.
    r = call_phone.handle(b"", "gọi điện thoại cho mẹ")
    assert r.action == {"type": "call", "name": "mẹ"}


def test_message_prefix_gui_tin_nhan_cho():
    # Fix B: "gửi tin nhắn cho" trước đây không khớp tiền tố nào cả.
    r = send_message.handle(b"", "gửi tin nhắn cho mẹ")
    assert r.action["name"] == "mẹ"


def test_call_empty_name_asks_who():
    r = call_phone.handle(b"", "gọi cho")
    assert r.action is None
    assert "ai" in r.speech.lower()


def test_message_empty_name_asks_who():
    r = send_message.handle(b"", "nhắn cho")
    assert r.action is None
    assert "ai" in r.speech.lower()


def test_call_preserves_capitalization():
    # Fix E: không được hạ chữ thường tên riêng.
    r = call_phone.handle(b"", "Gọi Cho Lan")
    assert r.action["name"] == "Lan"


def test_message_preserves_capitalization():
    r = send_message.handle(b"", "Nhắn Tin Cho Lan")
    assert r.action["name"] == "Lan"
