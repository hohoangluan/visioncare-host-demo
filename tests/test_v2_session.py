"""`WS /v2/session`: hello/token, một lượt đầu-cuối, huỷ khi có lượt mới, phiên mới thay phiên cũ."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import app
from models import clef
from pipeline import cues, pending_action
from tests.conftest import TEST_DEVICE_TOKEN
from tests.test_v2_api import _adpcm_chunks, _gemma, world  # noqa: F401 (fixture)

client = TestClient(app)


def _hello(ws, device="ws-dev", token=TEST_DEVICE_TOKEN):
    ws.send_text(json.dumps({"t": "hello", "device": device, "token": token,
                             "cue_version": cues.CUE_VERSION, "fw": "t", "accept": "audio/wav;codec=ima_adpcm"}))


def _send_turn(ws, turn, end=True):
    ws.send_text(json.dumps({"t": "turn_start", "turn": turn, "t_press_ms": 0}))
    for chunk in _adpcm_chunks():
        ws.send_bytes(b"\x03" + chunk)
    if end:
        ws.send_text(json.dumps({"t": "turn_end", "turn": turn, "t_release_ms": 0}))


def _recv_until_end(ws, turn):
    """-> (khung reply, số byte audio 0x02, thứ tự 'reply' < audio < 'reply_end')."""
    reply, audio, order = None, 0, []
    while True:
        msg = ws.receive()
        assert msg["type"] == "websocket.send", msg
        if msg.get("bytes") is not None:
            assert msg["bytes"][0] == 0x02
            audio += len(msg["bytes"]) - 1
            order.append("audio")
            continue
        frame = json.loads(msg["text"])
        if frame["t"] == "reply":
            reply = frame
            order.append("reply")
        elif frame["t"] == "end":
            raise AssertionError("live bị kết thúc ngoài ý muốn")
        elif frame["t"] == "reply_end":
            assert frame["turn"] == turn
            order.append("end")
            return reply, audio, order


def _chat(world):  # noqa: F811
    rec, labels, _ = world
    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    labels["kể chuyện cười đi"] = clef.ClefResult("chat", 0.9)


def test_bad_token_closes_4401(world):  # noqa: F811
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, token="sai-token")
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401


def test_turn_roundtrip_chat(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        ok = json.loads(ws.receive_text())
        assert ok["t"] == "hello_ok" and ok["ping_s"] == 25 and ok["session"]
        _send_turn(ws, "t1")
        reply, audio, order = _recv_until_end(ws, "t1")
        assert reply["turn"] == "t1" and reply["audio"]["sample_rate"] == 16000
        assert audio > 1000 and order[0] == "reply" and order[-1] == "end"
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}


def _sync(ws):
    """ping/pong: mọi khung gửi trước đó đã được server xử lý xong."""
    ws.send_text('{"t":"ping"}')
    while True:
        msg = ws.receive()
        if msg.get("text") and json.loads(msg["text"]) == {"t": "pong"}:
            return


@pytest.fixture
def cancelled_turns(monkeypatch):
    """Ghi lại các lượt bị huỷ giữa chừng trong turn.run (CancelledError)."""
    import asyncio

    from live import device_session

    seen = []
    original = device_session.turn_v2.run

    async def spy(device, turn_id, *args, **kwargs):
        try:
            return await original(device, turn_id, *args, **kwargs)
        except asyncio.CancelledError:
            seen.append(turn_id)
            raise

    monkeypatch.setattr(device_session.turn_v2, "run", spy)
    return seen


def test_new_turn_cancels_previous(world, cancelled_turns):  # noqa: F811
    _chat(world)
    fired = []
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-cancel")
        ws.receive_text()
        _send_turn(ws, "A", end=False)  # lượt A còn dở, chưa nhả nút
        _sync(ws)  # A đã begin_turn xong
        pending_action.schedule("ws-cancel", 30, lambda: fired.append(1), "gọi mẹ",
                                gen=pending_action.generation("ws-cancel"))
        _send_turn(ws, "B")  # chỉ lượt B mới được huỷ lệnh chờ
        reply, audio, _ = _recv_until_end(ws, "B")
        assert reply["turn"] == "B" and audio > 1000
        assert cancelled_turns == ["A"]
        assert not pending_action.cancel("ws-cancel", "kiểm")  # đã bị huỷ từ trước
    assert fired == []


def test_new_session_replaces_old(world, cancelled_turns):  # noqa: F811
    _chat(world)
    fired = []
    with client.websocket_connect("/v2/session") as old:
        _hello(old, device="ws-replace")
        old.receive_text()
        _send_turn(old, "A", end=False)
        _sync(old)
        pending_action.schedule("ws-replace", 30, lambda: fired.append(1), "gọi mẹ",
                                gen=pending_action.generation("ws-replace"))
        gen_before = pending_action.generation("ws-replace")
        with client.websocket_connect("/v2/session") as new:
            _hello(new, device="ws-replace")
            assert json.loads(new.receive_text())["t"] == "hello_ok"
            # Phiên mới chưa gửi lượt nào: chính việc thay phiên phải huỷ lệnh chờ + lượt A.
            assert pending_action.generation("ws-replace") > gen_before
            assert fired == [] and not pending_action.cancel("ws-replace", "kiểm")
            assert cancelled_turns == ["A"]
            msg = old.receive()
            assert msg["type"] == "websocket.close" and msg["code"] == 4000
            _send_turn(new, "B")
            reply, _, _ = _recv_until_end(new, "B")
            assert reply["turn"] == "B"
    assert fired == []


def test_nav_live_survives_new_chat_turn(world):  # noqa: F811
    from live.session import sessions

    rec, labels, _ = world
    rec.text = "DẪN TÔI TỚI CHỢ BẾN THÀNH"
    labels["dẫn tôi tới chợ bến thành"] = _gemma("nav_start")
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-nav")
        ws.receive_text()
        _send_turn(ws, "N")
        reply, _, _ = _recv_until_end(ws, "N")
        assert reply["live"] == "nav"
        assert json.loads(ws.receive_text())["t"] == "cam"
        assert sessions.active("ws-nav") is not None
        _chat(world)
        _send_turn(ws, "C")
        reply, audio, _ = _recv_until_end(ws, "C")  # `end` của nav mà chen vào sẽ làm vỡ assert này
        assert reply["turn"] == "C" and audio > 1000
        assert sessions.active("ws-nav") is not None  # nav vẫn chạy sau lượt chat
