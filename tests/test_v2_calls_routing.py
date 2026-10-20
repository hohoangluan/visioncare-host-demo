"""C6: làn D gọi điện + khẩn cấp đi luồng mới (AB + cầu âm thanh).

Kính giả là WebSocket của `TestClient` dùng CHUNG một portal với client callback (một event loop như server thật);
AB giả bằng `httpx.MockTransport`, trả theo bảng `ab.replies` (khoá = đuôi đường dẫn).
"""

import asyncio
import hashlib
import json
import time

import anyio.from_thread
import httpx
import pytest
from fastapi.testclient import TestClient

import config
from app import app
from handlers import phone as phone_handlers
from lanes import phone
from live import call_bridge, device_session
from live.call_bridge import ACTIVE, ENDED, RINGING_OUT, calls
from pipeline import cues, device_ctx, final_router, guard
from pipeline.intent_early import Decision
from services import visioncare_client
from tests.test_v2_api import _gemma, world  # noqa: F401 (fixture)
from tests.test_v2_session import _hello as _hello_frame, _recv_result_reply, _recv_until_end, _send_turn

TOK, DEV, CB_TOKEN = "tok-kinh-c6-" + "c" * 20, "dev-c6", "test-callback-token"
REAL_BLOCKER = final_router._call_blocker  # `world` thay bằng bản không chặn; test chặn khôi phục bản thật


def _ok(data):
    return 200, {"status": "ok", "data": data}


def _err(status, code, **details):
    return status, {"status": "error", "error": {"code": code, "message": code, "details": details}}


@pytest.fixture
def rig(tmp_path, monkeypatch, world):  # noqa: F811
    """Kính DEV có token riêng (KHÔNG có user chung: AB suy chủ từ glasses_device_id) + AB giả ghi lại mọi request."""
    path = tmp_path / "device_tokens.json"
    path.write_text(json.dumps({DEV: hashlib.sha256(TOK.encode()).hexdigest()}))
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_TOKENS", str(path))
    monkeypatch.setattr(config, "VISIONCARE_CALLBACK_TOKEN", CB_TOKEN)
    monkeypatch.setattr(config, "CALL_HALF_DUPLEX", False)
    monkeypatch.setitem(phone.HANDLERS, "contact_call", phone_handlers.handle_contact_call)
    monkeypatch.setitem(phone.HANDLERS, "emergency_call", phone_handlers.handle_emergency_call)
    monkeypatch.setattr(final_router, "_call_blocker", REAL_BLOCKER)
    guard.reset()
    phone._CHOICE.clear(), phone._OFFER.clear()
    with calls._lock:
        calls._by_id.clear(), calls._by_device.clear(), calls._by_token.clear()
    call_bridge._seen_events.clear()

    replies: dict[str, tuple[int, dict]] = {}
    sent: list[tuple[str, dict]] = []

    def ab(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else dict(request.url.params)  # GET: ghi query
        sent.append((request.url.path, body))
        for suffix, (status, out) in replies.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(status, json=out)
        return httpx.Response(200, json={"status": "ok", "data": {}})

    monkeypatch.setattr(visioncare_client, "_CLIENT", httpx.Client(transport=httpx.MockTransport(ab)))
    with anyio.from_thread.start_blocking_portal() as portal:
        client = TestClient(app)
        client.portal = portal
        cb = TestClient(app, client=("127.0.0.1", 12345))
        cb.portal = portal
        yield type("Rig", (), {"client": client, "cb": cb, "ab": sent, "replies": replies, "world": world})
    visioncare_client.reset_client()


def _wait(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _hello(ws):
    _hello_frame(ws, device=DEV, token=TOK)
    assert json.loads(ws.receive_text())["t"] == "hello_ok"


def _until_state(ws, state):
    for _ in range(80):
        msg = ws.receive()
        if msg.get("text"):
            frame = json.loads(msg["text"])
            if frame.get("t") == "call_state" and frame["state"] == state:
                return frame
    raise AssertionError(f"không thấy call_state {state}")


def _event(rig, event, call_id, **extra):
    body = {"event": event, "call_id": call_id, "glasses_device_id": DEV, "peer_display_name": "Mẹ", **extra}
    return rig.cb.post("/internal/calls", json=body, headers={
        "Authorization": f"Bearer {CB_TOKEN}", "Idempotency-Key": f"k-{event}-{call_id}-{time.monotonic()}"})


def _starts(rig, suffix):
    return [b for p, b in rig.ab if p.endswith(suffix)]


def _say(rig, text, intent):
    rec, labels, _ = rig.world
    rec.text = text.upper()
    labels[text.lower()] = _gemma(intent)


def test_contact_call_starts_ab_call_after_readback(rig):
    """Cổng an toàn giữ nguyên: đọc lại tới kính TRƯỚC, AB `call/start` chỉ đi sau cửa sổ huỷ; kính thấy chuông."""
    rig.replies["/call/start"] = _ok({"call_id": "c-1", "relative": {"display_name": "Mẹ"}})
    _say(rig, "gọi cho mẹ", "contact_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "G1")
        reply, _, _ = _recv_until_end(ws, "G1")
        assert reply["turn"] == "G1"
        assert not _starts(rig, "/call/start")  # câu đọc lại vừa xong, cửa sổ huỷ còn mở
        _until_state(ws, RINGING_OUT)  # chuông báo kính ngay khi Call được tạo, trước khi `start` tới AB
        assert _wait(lambda: _starts(rig, "/call/start"))
        start = _starts(rig, "/call/start")[0]
        call = calls.by_device(DEV)
        assert "user_id" not in start and start["glasses_device_id"] == DEV
        assert start["contact_alias"] == "mẹ" and start["emergency"] is False
        assert start["media_token"] == call.media_token and len(start["media_token"]) >= 8
        assert "device_id" not in start  # AB khai extra="forbid": không chèn trường lạ
        assert _wait(lambda: call.call_id == "c-1") and call.peer == "Mẹ"


def test_multiple_candidates_asks_then_calls_choice(rig):
    rig.replies["/call/start"] = _err(409, "MULTIPLE_CONTACTS_FOUND", candidates=["Mẹ Lan", "Mẹ Hoa"])
    _say(rig, "gọi cho mẹ", "contact_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "M1")
        _recv_until_end(ws, "M1")
        _recv_result_reply(ws)  # "Bạn muốn gọi ai: Mẹ Lan hay Mẹ Hoa?"
        assert phone._CHOICE[DEV][1] == ["Mẹ Lan", "Mẹ Hoa"]
        assert _wait(lambda: calls.by_device(DEV) is None)  # cuộc gọi chưa thành đã được bỏ
        # lượt sau: chọn không dấu, câu không phải lệnh gọi; vẫn đọc lại rồi mới gọi
        rig.replies["/call/start"] = _ok({"call_id": "c-2", "relative": {"display_name": "Mẹ Hoa"}})
        rec, labels, _ = rig.world
        rec.text = "ME HOA"
        _send_turn(ws, "M2")
        _recv_until_end(ws, "M2")
        assert len(_starts(rig, "/call/start")) == 1
        _until_state(ws, RINGING_OUT)
        assert _wait(lambda: len(_starts(rig, "/call/start")) == 2)
        starts = _starts(rig, "/call/start")
        assert [b["contact_alias"] for b in starts] == ["mẹ", "Mẹ Hoa"]
        assert phone._CHOICE.get(DEV) is None


def test_emergency_start_and_stop_on_press(rig):
    rig.replies["/emergency/start"] = _ok({"emergency_id": "em-1", "state": "running", "call_id": "e-c1",
                                           "relative": {"display_name": "Mẹ"}, "contacts": 2})
    _say(rig, "cứu tôi với", "emergency_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "E1")
        _recv_until_end(ws, "E1")
        assert not _starts(rig, "/emergency/start")
        _until_state(ws, RINGING_OUT)
        assert _wait(lambda: _starts(rig, "/emergency/start"))
        start = _starts(rig, "/emergency/start")[0]
        call = calls.by_device(DEV)
        tokens = start["media_tokens"]
        assert "user_id" not in start and start["glasses_device_id"] == DEV
        assert 24 <= len(tokens) <= 30 and len(set(tokens)) == len(tokens) and tokens[0] == call.media_token
        assert call.emergency and _wait(lambda: call.emergency_id == "em-1" and call.call_id == "e-c1")
        # mọi token của chuỗi mở được cuộc gọi này (VH không biết trước call_id lượt sau)
        assert calls.claim_token(tokens[5]) is call
        # bấm nút khi đang chuông: dừng CẢ chuỗi (emergency stop), không chỉ cúp một cuộc
        ws.send_text(json.dumps({"t": "call_hangup"}))
        assert _until_state(ws, ENDED)["reason"] == "glasses_hangup"
        assert _wait(lambda: any(p.endswith("/emergency/em-1/stop") for p, _ in rig.ab))
        assert not any(p.endswith("/call/e-c1/hangup") for p, _ in rig.ab)
        assert calls.by_device(DEV) is None


def test_emergency_survives_session_drop_and_reattaches(rig):
    """Ruling C4: kính rớt phiên khi chuỗi khẩn cấp còn chuông KHÔNG dừng chuỗi (không `emergency/stop`);
    phiên mới của kính gắn lại, người thân nghe máy sau đó vẫn nối được; bấm nút lúc này mới dừng chuỗi."""
    rig.replies["/emergency/start"] = _ok({"emergency_id": "em-7", "state": "running", "call_id": "e-d1",
                                           "relative": {"display_name": "Mẹ"}, "contacts": 2})
    _say(rig, "cứu tôi với", "emergency_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "D1")
        _recv_until_end(ws, "D1")
        _until_state(ws, RINGING_OUT)
        call = calls.by_device(DEV)
        assert _wait(lambda: call.emergency_id == "em-7" and call.call_id == "e-d1")
    # socket kính đóng (rớt mạng): phiên shutdown
    assert _wait(lambda: call.session is None)
    time.sleep(0.3)
    assert call.state == RINGING_OUT and calls.by_device(DEV) is call
    assert not any("/stop" in p or p.endswith("/hangup") for p, _ in rig.ab)
    with rig.client.websocket_connect("/v2/session") as ws2:
        _hello(ws2)
        _until_state(ws2, RINGING_OUT)  # gắn lại: kính biết chuỗi vẫn đang chuông
        assert call.session is not None
        assert _event(rig, "call_answered", "e-d2", emergency=True, peer_display_name="Bố").status_code == 200
        _until_state(ws2, ACTIVE)
        assert call.peer == "Bố"
    assert not any("/stop" in p for p, _ in rig.ab)


def test_emergency_stop_race_answered_hangs_up_active_call(rig):
    """Minor 7: bấm dừng đúng lúc người thân nghe máy -> AB trả `answered` + call_id -> VH cúp thêm cuộc còn active."""
    rig.replies["/emergency/start"] = _ok({"emergency_id": "em-5", "state": "running", "call_id": "e-r1",
                                           "relative": {"display_name": "Mẹ"}, "contacts": 2})
    rig.replies["/emergency/em-5/stop"] = _ok({"emergency_id": "em-5", "state": "answered", "call_id": "e-r2"})
    _say(rig, "cứu tôi với", "emergency_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "R1")
        _recv_until_end(ws, "R1")
        _until_state(ws, RINGING_OUT)
        assert _wait(lambda: calls.by_device(DEV).emergency_id == "em-5")
        ws.send_text(json.dumps({"t": "call_hangup"}))
        assert _until_state(ws, ENDED)["reason"] == "glasses_hangup"
        assert _wait(lambda: any(p.endswith("/call/e-r2/hangup") for p, _ in rig.ab))
    assert _wait(lambda: DEV not in device_session._registry)  # phiên dọn xong trước khi loop của test đóng


def test_emergency_button_after_reattach_stops_chain(rig):
    """Sau khi gắn lại, bấm nút vẫn dừng cả chuỗi như thường."""
    rig.replies["/emergency/start"] = _ok({"emergency_id": "em-8", "state": "running", "call_id": "e-f1",
                                           "relative": {"display_name": "Mẹ"}, "contacts": 2})
    _say(rig, "cứu tôi với", "emergency_call")
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        _send_turn(ws, "F1")
        _recv_until_end(ws, "F1")
        _until_state(ws, RINGING_OUT)
        call = calls.by_device(DEV)
        assert _wait(lambda: call.emergency_id == "em-8")
    assert _wait(lambda: call.session is None)
    with rig.client.websocket_connect("/v2/session") as ws2:
        _hello(ws2)
        _until_state(ws2, RINGING_OUT)
        ws2.send_text(json.dumps({"t": "call_hangup"}))
        assert _until_state(ws2, ENDED)["reason"] == "glasses_hangup"
        assert _wait(lambda: any(p.endswith("/emergency/em-8/stop") for p, _ in rig.ab))
    assert _wait(lambda: DEV not in device_session._registry)


def test_emergency_chain_rebinds_next_call_and_exhausted(rig, monkeypatch):
    """AB gọi lần lượt: người đầu không nghe -> chuỗi vẫn chuông; người sau nghe (call_id mới) -> active."""
    spoken = []
    real_push = device_session.push_result
    monkeypatch.setattr(device_session, "push_result", lambda dev, text, rid="": spoken.append(text) or real_push(dev, text, rid))
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        call = calls.create("e-c1", DEV, "Mẹ", "to_relative", emergency=True)
        call.emergency_id = "em-9"
        _until_state(ws, RINGING_OUT)
        assert _event(rig, "call_missed", "e-c1", emergency=True).status_code == 200
        assert call.state == RINGING_OUT  # không kết thúc, không đọc câu thường
        assert _event(rig, "call_answered", "e-c2", emergency=True, peer_display_name="Bố").status_code == 200
        _until_state(ws, ACTIVE)
        assert call.state == ACTIVE and call.call_id == "e-c2" and call.peer == "Bố"
        assert _event(rig, "call_missed", "e-c1", emergency=True).json()["data"]["matched"] is False  # muộn: bỏ
        assert call.state == ACTIVE
        # chuỗi khác: hết 3 vòng không ai nghe -> kính bị báo
        call.hangup_threadsafe("test", by="ab")
        _until_state(ws, ENDED)
        calls.create("e-c3", DEV, "Mẹ", "to_relative", emergency=True)
        _until_state(ws, RINGING_OUT)
        _event(rig, "emergency_exhausted", "e-c3", emergency=True, reason="exhausted")
        assert _until_state(ws, ENDED)["reason"] == "emergency_exhausted"
        assert spoken == [call_bridge.EMERGENCY_NONE_REACHED]  # và không có câu "chưa nghe máy" thường


def test_post_only_glasses_cannot_call(rig, monkeypatch):
    """Kính không có phiên WS -> 'cần cập nhật'; có phiên nhưng token chung -> 'cần token riêng'; AB không bị gọi."""
    assert call_bridge.unavailable_reason("dev-khong-phien", True) == call_bridge.NEED_UPDATE
    ctx = final_router.TurnContext("dev-khong-phien", "t", None, None)
    d = Decision("contact_call", source="gemma", backend="gemma", confidence=1.0)
    with device_ctx.use("dev-khong-phien", per_device=True):
        reply = asyncio.run(final_router.route(ctx, d, "gọi cho mẹ"))
    assert list(reply.speech) == [call_bridge.NEED_UPDATE]
    with rig.client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        assert call_bridge.unavailable_reason(DEV, True) is None
        assert call_bridge.unavailable_reason(DEV, False) == call_bridge.NEED_OWN_TOKEN
    # Vào phiên có token riêng thì VH lấy tin nhắn chưa đọc (C7); ngoài ra AB không bị gọi (không call/start).
    assert not [p for p, _ in rig.ab if "/messages/unread" not in p]


def test_bind_after_ended_does_not_resurrect_call(rig):
    """Minor 5: huỷ sớm rồi mới `bind` id của AB thì Call ENDED không được quay lại sổ (rò bộ nhớ)."""
    call = calls.create(None, DEV, "Mẹ", "to_relative")
    call.hangup_threadsafe("glasses_hangup", by="glasses")  # chưa có phiên/loop: đánh ENDED + gỡ khỏi sổ ngay
    assert call.state == ENDED and calls.get(call.call_id) is None
    calls.bind(call, "ab-late", "Mẹ")
    assert call.call_id == "ab-late" and calls.get("ab-late") is None and calls.by_device(DEV) is None
    live = calls.create(None, DEV, "Mẹ", "to_relative")
    calls.bind(live, "ab-live")
    assert calls.get("ab-live") is live  # cuộc còn sống vẫn ghi bình thường
    live.hangup_threadsafe("test", by="ab")
