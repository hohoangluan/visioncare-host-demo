"""C7: nhắn tin bằng giọng nói + tin của người thân tới kính.

Dùng lại `rig` của C6 (kính DEV có token riêng, AB giả `httpx.MockTransport`, một portal chung với client callback).
TTS giả ghi lại từng câu được đọc để kiểm đúng lời nói, không chỉ có audio.
"""

import asyncio
import json
import threading

import pytest

import config
from handlers import phone as phone_handlers
from lanes import phone
from live import messages
from models import llm
from pipeline import intent_early, tts
from services import visioncare_client  # noqa: F401 (rig vá client AB)
from tests.test_v2_api import _gemma, world  # noqa: F401 (fixture)
from tests.test_v2_calls_routing import (  # noqa: F401 (fixture rig)
    CB_TOKEN, DEV, _hello, _ok, _say, _starts, _wait, rig,
)
from tests.test_v2_session import _recv_result_reply, _recv_until_end, _send_turn


@pytest.fixture
def mrig(rig, monkeypatch):  # noqa: F811
    """`rig` + handler nhắn tin thật + TTS ghi lại câu đọc + Gemma trích tham số theo bảng `rig.extract`."""
    monkeypatch.setitem(phone.HANDLERS, "message_send", phone_handlers.handle_message_send)
    monkeypatch.setitem(phone.HANDLERS, "message_read", phone_handlers.handle_message_read)
    phone._BODY.clear()
    messages.reset()
    spoken: list[str] = []
    extract: dict = {"contact_name": "mẹ", "text": ""}

    def record(text):
        spoken.append(text)
        yield b"\x10\x00" * 8000

    async def fake_json(prompt, schema, max_tokens=120):
        return dict(extract)

    monkeypatch.setattr(tts, "synthesize_stream", record)
    monkeypatch.setattr(llm, "generate_json", fake_json)
    rig.spoken, rig.extract = spoken, extract
    return rig


def _said(rig, needle):
    return any(needle in line for line in rig.spoken)


def _said_before(rig, later, earlier):
    """`later` được đọc trước `earlier`? (cả hai đều đã được đọc)"""
    first = lambda needle: next(i for i, line in enumerate(rig.spoken) if needle in line)  # noqa: E731
    return first(later) < first(earlier)


def _incoming(rig, message_id="m-1", name="Mẹ", text="con ăn cơm chưa"):
    body = {"event": "message_received", "message_id": message_id, "glasses_device_id": DEV,
            "from_display_name": name, "text": text}
    return rig.cb.post("/internal/messages", json=body, headers={
        "Authorization": f"Bearer {CB_TOKEN}", "Idempotency-Key": f"message-{message_id}"})


def test_message_send_readback_then_sends(mrig):
    """Đọc lại "Nhắn cho {name}: {text}." tới kính TRƯỚC; AB `messages/send` chỉ đi sau cửa sổ huỷ."""
    mrig.extract.update(contact_name="mẹ", text="tôi về muộn nhé")
    mrig.replies["/messages/send"] = _ok({"message_id": "m-9", "relative": {"display_name": "Mẹ"}})
    _say(mrig, "nhắn cho mẹ là tôi về muộn nhé", "message_send")
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "S1")
        reply, _, _ = _recv_until_end(ws, "S1")
        assert reply["turn"] == "S1" and _said(mrig, "Nhắn cho mẹ: tôi về muộn nhé.")
        assert not _starts(mrig, "/messages/send")  # câu đọc lại vừa xong, cửa sổ huỷ còn mở
        assert _wait(lambda: _starts(mrig, "/messages/send"))
        body = _starts(mrig, "/messages/send")[0]
        assert "user_id" not in body and body["glasses_device_id"] == DEV and body["contact_alias"] == "mẹ"
        assert body["text"] == "tôi về muộn nhé" and len(body["request_id"]) >= 32
        assert "device_id" not in body  # AB khai extra="forbid"
        _recv_result_reply(ws)  # "Đã gửi."
        assert _said(mrig, "Đã gửi")


def test_message_send_asks_text_when_missing(mrig):
    """Có người nhận, thiếu lời nhắn: hỏi "Bạn muốn nhắn gì cho mẹ?"; lượt sau là lời nhắn, rồi đọc lại + gửi."""
    mrig.replies["/messages/send"] = _ok({"message_id": "m-8", "relative": {"display_name": "Mẹ"}})
    _say(mrig, "nhắn tin cho mẹ", "message_send")
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "A1")
        _recv_until_end(ws, "A1")
        assert _said(mrig, "Bạn muốn nhắn gì cho mẹ?")
        assert phone._BODY[DEV][0] == "mẹ"
        rec, labels, _ = mrig.world
        rec.text = "NGÀY MAI MẸ QUA NHÀ"
        labels["ngày mai mẹ qua nhà"] = _gemma("chat")  # lời nhắn nghe như câu trò chuyện
        _send_turn(ws, "A2")
        _recv_until_end(ws, "A2")
        assert any("nhắn cho mẹ: ngày mai mẹ qua nhà." in line.lower() for line in mrig.spoken)
        assert _wait(lambda: _starts(mrig, "/messages/send"))
        assert _starts(mrig, "/messages/send")[0]["text"].lower() == "ngày mai mẹ qua nhà"
        _recv_result_reply(ws)  # "Đã gửi." (TestClient huỷ phiên ngay khi thoát `with`: để phiên rảnh trước khi thoát)


def test_message_read_reads_unread(mrig):
    """"Đọc tin nhắn": mỗi tin đọc "{name} nhắn: {text}" rồi báo AB đã đọc; tin đã đọc không đọc lại."""
    _say(mrig, "đọc tin nhắn", "message_read")
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        assert _wait(lambda: any(p.endswith("/messages/unread") for p, _ in mrig.ab))  # lấy bù lúc vào phiên: rỗng
        mrig.replies["/messages/unread"] = _ok({"messages": [
            {"message_id": "m-1", "from_display_name": "Mẹ", "text": "con ăn cơm chưa", "created_at": "t1"},
            {"message_id": "m-2", "from_display_name": "Bố", "text": "bố đón con lúc năm giờ", "created_at": "t2"},
        ]})
        _send_turn(ws, "R1")
        _recv_until_end(ws, "R1")
        assert _said(mrig, "Mẹ nhắn: con ăn cơm chưa") and _said(mrig, "Bố nhắn: bố đón con lúc năm giờ")
        assert _wait(lambda: {p for p, _ in mrig.ab if p.endswith("/read")} >= {
            "/api/v1/service/messages/m-1/read", "/api/v1/service/messages/m-2/read"})
        assert all(b == {"glasses_device_id": DEV} for p, b in mrig.ab if p.endswith("/read"))


def test_message_read_none(mrig):
    mrig.replies["/messages/unread"] = _ok({"messages": []})
    _say(mrig, "có tin nhắn mới không", "message_read")
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "N1")
        _recv_until_end(ws, "N1")
        assert _said(mrig, "Không có tin nhắn mới.")
        assert not any(p.endswith("/read") for p, _ in mrig.ab)


def test_incoming_message_announced_when_idle(mrig):
    """Kính rảnh: tin tới được đọc ngay ("Mẹ nhắn: ...") rồi báo AB đã đọc; AB gửi lại cùng tin thì không đọc lại."""
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        assert _incoming(mrig).status_code == 200
        res, audio, _ = _recv_result_reply(ws)
        assert res["turn"] == "result-msg-m-1" and audio > 500
        assert _said(mrig, "Mẹ nhắn: con ăn cơm chưa")
        assert _wait(lambda: any(p.endswith("/messages/m-1/read") for p, _ in mrig.ab))
        # báo đã đọc chạy ở executor: phải mang đúng kính của phiên (không rơi về VISIONCARE_DEVICE_ID mặc định)
        assert [b for p, b in mrig.ab if p.endswith("/messages/m-1/read")] == [{"glasses_device_id": DEV}]
        n = len(mrig.spoken)
        assert _incoming(mrig).status_code == 200  # AB thử lại
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}
        assert len(mrig.spoken) == n


def test_incoming_message_queued_while_busy(mrig, monkeypatch):
    """Tin tới lúc lượt đang chạy (chưa có audio nào): không chen trước câu trả lời, không mất, đọc ngay khi rảnh."""
    gate = threading.Event()
    rec, labels, _ = mrig.world

    async def slow_classify(text, device=None):
        await asyncio.to_thread(gate.wait, 10)  # lượt "đang nghe/phân loại": chưa có khung reply nào
        return labels.get(text.lower())

    monkeypatch.setattr(intent_early.classifier, "classify", slow_classify)
    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    labels["kể chuyện cười đi"] = _gemma("chat")
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "B1")
        assert _incoming(mrig, "m-7", "Bố", "tối nay bố về trễ").status_code == 200
        assert not _wait(lambda: _said(mrig, "Bố nhắn"), timeout=0.6)  # đang bận: chưa đọc
        gate.set()
        _recv_until_end(ws, "B1")  # nếu tin chen ngang, reply_end đầu tiên là của result-msg-m-7 -> AssertionError
        _recv_result_reply(ws)
        assert _said(mrig, "Bố nhắn: tối nay bố về trễ")
        assert not _said_before(mrig, "Bố nhắn", "Phía trước")  # câu trả lời của lượt (Gemma giả) đọc trước tin
        assert _wait(lambda: any(p.endswith("/messages/m-7/read") for p, _ in mrig.ab))


def test_hello_fetches_unread(mrig):
    """Callback AB có thể đã bỏ sau 8 lần: vào phiên là lấy `unread` và đọc như tin tới."""
    mrig.replies["/messages/unread"] = _ok({"messages": [
        {"message_id": "m-5", "from_display_name": "Chị Hoa", "text": "chị gửi tiền rồi nhé", "created_at": "t"}]})
    with mrig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        res, _, _ = _recv_result_reply(ws)
        assert res["turn"] == "result-msg-m-5" and _said(mrig, "Chị Hoa nhắn: chị gửi tiền rồi nhé")
        unread = [b for p, b in mrig.ab if p.endswith("/messages/unread")]
        assert unread and all(b == {"glasses_device_id": DEV} for b in unread)  # chủ kính do AB suy từ kính
