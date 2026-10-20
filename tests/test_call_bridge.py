"""C5: cầu âm thanh cuộc gọi kính <-> app, `WS /v2/call`, `/internal/calls`, chế độ gọi trong phiên kính.

Kính giả và app giả đều là WebSocket của `TestClient` dùng CHUNG một portal (một event loop, như server thật),
nên không gọi `with TestClient(app)` (khỏi chạy startup nạp model). AB giả bằng `httpx.MockTransport`.
"""

import asyncio
import hashlib
import json
import time

import anyio.from_thread
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
from app import app
from live import call_bridge, device_session
from live.call_bridge import ACTIVE, ENDED, RINGING_IN, RINGING_OUT, calls
from live.jitter import JitterBuffer
from pipeline import adpcm, cues, guard
from services import visioncare_client
from tests.test_v2_api import world  # noqa: F401 (fixture)

TOK = "tok-kinh-call-" + "c" * 20
CB_TOKEN = "test-callback-token"
DEV = "dev-call"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Một kính có token riêng, AB giả ghi lại request, hai client TestClient chung một portal."""
    path = tmp_path / "device_tokens.json"
    path.write_text(json.dumps({DEV: hashlib.sha256(TOK.encode()).hexdigest()}))
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_TOKENS", str(path))
    monkeypatch.setattr(config, "VISIONCARE_CALLBACK_TOKEN", CB_TOKEN)
    monkeypatch.setattr(config, "CALL_HALF_DUPLEX", False)
    guard.reset()
    with calls._lock:
        calls._by_id.clear(), calls._by_device.clear(), calls._by_token.clear()
    call_bridge._seen_events.clear()

    sent: list[tuple[str, dict]] = []

    def ab(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append((request.url.path, body))
        return httpx.Response(200, json={"status": "ok", "data": {"call_id": "x", "state": "ended"}})

    monkeypatch.setattr(visioncare_client, "_CLIENT", httpx.Client(transport=httpx.MockTransport(ab)))
    with anyio.from_thread.start_blocking_portal() as portal:
        glasses_client = TestClient(app)
        glasses_client.portal = portal
        cb_client = TestClient(app, client=("127.0.0.1", 12345))
        cb_client.portal = portal
        yield type("Env", (), {"client": glasses_client, "cb": cb_client, "ab": sent})
    visioncare_client.reset_client()


def _hello(ws):
    ws.send_text(json.dumps({"t": "hello", "device": DEV, "token": TOK, "cue_version": cues.CUE_VERSION}))
    assert json.loads(ws.receive_text())["t"] == "hello_ok"


def _until_state(ws, state):
    """Đọc khung của kính tới khi gặp `call_state` mong đợi."""
    for _ in range(50):
        msg = ws.receive()
        if msg.get("text"):
            frame = json.loads(msg["text"])
            if frame.get("t") == "call_state" and frame["state"] == state:
                return frame
    raise AssertionError(f"không thấy call_state {state}")


def _event(env, event, call_id="c1", key=None, **extra):
    body = {"event": event, "call_id": call_id, "glasses_device_id": DEV, "peer_display_name": "Mẹ", **extra}
    return env.cb.post("/internal/calls", json=body,
                       headers={"Authorization": f"Bearer {CB_TOKEN}", "Idempotency-Key": key or f"k-{event}-{call_id}"})


def _active_call(env, glasses, call_id="c1"):
    """Kính gọi đi, AB báo người thân đã nghe -> Call `active`; trả (call, trạng thái kính nhận được)."""
    call = calls.create(call_id, DEV, "Mẹ", "to_relative")
    assert _until_state(glasses, RINGING_OUT)["peer"] == "Mẹ"
    assert _event(env, "call_answered", call_id).status_code == 200
    _until_state(glasses, ACTIVE)
    return call


def _app_state(app_ws):
    return json.loads(app_ws.receive_text())


def _sine(seconds, freq=440.0, amp=9000):
    t = np.arange(int(16000 * seconds))
    return (np.sin(2 * np.pi * freq * t / 16000) * amp).astype("<i2").tobytes()


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _corr(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b)) // 2
    x, y = np.frombuffer(a, "<i2")[:n].astype(float), np.frombuffer(b, "<i2")[:n].astype(float)
    return float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))


# ---------- test ----------
def test_token_single_use(env):
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = _active_call(env, glasses)
        url = f"/v2/call?token={call.media_token}"
        with env.client.websocket_connect(url) as app_ws:
            assert _app_state(app_ws)["state"] == "active"
            # cùng token lần hai khi lần một còn sống (cuộc gọi vẫn active): từ chối, lần một không bị đá
            with env.client.websocket_connect(url) as again:
                msg = again.receive()
                assert msg["type"] == "websocket.close" and msg["code"] == 4401
            assert call.state == ACTIVE
        with env.client.websocket_connect(url) as after:  # cuộc gọi đã kết thúc: cũng từ chối
            assert after.receive()["code"] == 4401
        with env.client.websocket_connect("/v2/call?token=khong-co") as bad:
            assert bad.receive()["code"] == 4401


def test_audio_glasses_to_app_pcm16(env):
    pcm = _sine(1.0)
    data = adpcm.encode_blocks(pcm)
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = _active_call(env, glasses)
        with env.client.websocket_connect(f"/v2/call?token={call.media_token}") as app_ws:
            assert _app_state(app_ws)["state"] == "active"
            # chia mảnh lẻ (không theo ranh giới khối) như firmware có thể làm
            for i in range(0, len(data), 300):
                glasses.send_bytes(b"\x05" + data[i:i + 300])
            frames = []
            while len(frames) < 40:
                frames.append(app_ws.receive_bytes())
            assert all(len(f) == 640 for f in frames)  # PCM16 20 ms
            want = adpcm.decode_blocks(data).tobytes()[:len(frames) * 640]
            assert b"".join(frames) == want  # bộ giải vô hướng bit-exact với adpcm.decode_blocks


def test_audio_app_to_glasses_adpcm(env):
    pcm = _sine(1.0)
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = _active_call(env, glasses)
        with env.client.websocket_connect(f"/v2/call?token={call.media_token}") as app_ws:
            assert _app_state(app_ws)["state"] == "active"
            for i in range(0, len(pcm), 640):
                app_ws.send_bytes(pcm[i:i + 640])
            blocks = b""
            while len(blocks) < 256 * 20:
                msg = glasses.receive()
                if msg.get("bytes") is not None:
                    assert msg["bytes"][0] == 0x02 and (len(msg["bytes"]) - 1) % 256 == 0
                    blocks += msg["bytes"][1:]
            got = adpcm.decode_blocks(blocks).tobytes()
            assert _corr(got, pcm) > 0.95  # khung đầu phát đầu tiên, không lệch pha


def test_jitter_reorders_and_drops_late():
    jb = JitterBuffer(target_ms=60, max_late_ms=200)
    f = {ts: bytes([ts // 20 + 1]) * 640 for ts in range(0, 200, 20)}
    now = 10_000.0
    assert jb.pop() is None  # chưa gom đủ
    for ts in (40, 0, 20):  # tới sai thứ tự
        jb.push(f[ts], ts, now_ms=now + ts)
    assert jb.playing
    assert [jb.pop(), jb.pop(), jb.pop()] == [f[0], f[20], f[40]]
    # khung 60 mất, 80 tới: giữ nhịp bằng 1 khung im lặng rồi mới tới 80
    jb.push(f[80], 80, now_ms=now + 80)
    jb.push(f[100], 100, now_ms=now + 100)
    jb.push(f[120], 120, now_ms=now + 120)
    assert jb.pop() == bytes(640)
    assert [jb.pop(), jb.pop(), jb.pop()] == [f[80], f[100], f[120]]
    assert jb.concealed == 1
    # khung có ts đã phát qua: bỏ; khung trễ > 200 ms so với nhịp nguồn: bỏ
    assert jb.push(f[60], 60, now_ms=now + 130) is False and jb.dropped_old == 1
    assert jb.push(f[140], 140, now_ms=now + 140 + 250) is False and jb.dropped_late == 1


def test_glasses_hangup_notifies_ab(env):
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = _active_call(env, glasses, "c-hang")
        glasses.send_text(json.dumps({"t": "call_hangup", "call": "c-hang"}))
        assert _until_state(glasses, ENDED)["reason"] == "glasses_hangup"
        assert _wait(lambda: any(p.endswith("/call/c-hang/hangup") for p, _ in env.ab))
        body = dict(env.ab)["/api/v1/service/call/c-hang/hangup"]
        assert body["reason"] == "glasses_hangup" and body["device_id"] == DEV
        assert calls.by_device(DEV) is None and call.state == ENDED


def test_bridge_peer_disconnect_ends_call(env):
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = _active_call(env, glasses, "c-drop")
        with env.client.websocket_connect(f"/v2/call?token={call.media_token}") as app_ws:
            assert _app_state(app_ws)["state"] == "active"
        # app rớt mạng (không gửi hangup): kính được báo ended, AB được báo, không còn Call/task treo
        assert _until_state(glasses, ENDED)["reason"] == "peer_disconnect"
        assert _wait(lambda: any(p.endswith("/call/c-drop/hangup") for p, _ in env.ab))
        assert calls.by_device(DEV) is None and calls.get("c-drop") is None
        assert _wait(lambda: not call._tasks)


def test_turn_start_ignored_during_call(env, world, monkeypatch):  # noqa: F811
    ran = []

    async def spy(*args, **kwargs):
        ran.append(args)
        raise AssertionError("turn.run không được chạy khi đang gọi")

    monkeypatch.setattr(device_session.turn_v2, "run", spy)
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        call = calls.create("c-turn", DEV, "Mẹ", "to_relative")
        _until_state(glasses, RINGING_OUT)
        for _ in range(2):  # ringing_out rồi active: cả hai đều bỏ qua turn_start
            glasses.send_text(json.dumps({"t": "turn_start", "turn": "t1", "t_press_ms": 0}))
            glasses.send_bytes(b"\x03" + bytes(256))
            glasses.send_text(json.dumps({"t": "turn_end", "turn": "t1", "t_release_ms": 0}))
            glasses.send_text('{"t":"ping"}')
            while True:
                msg = glasses.receive()
                assert msg.get("bytes") is None, "không có audio trả lời"
                frame = json.loads(msg["text"])
                assert frame["t"] != "reply"
                if frame["t"] == "pong":
                    break
            if call.state == RINGING_OUT:
                assert _event(env, "call_answered", "c-turn").status_code == 200
                _until_state(glasses, ACTIVE)
        assert ran == []


def test_half_duplex_ducks_mic(monkeypatch):
    monkeypatch.setattr(config, "CALL_HALF_DUPLEX", True)
    mic = adpcm.encode_blocks(_sine(0.2, amp=9000))
    loud = _sine(0.02, 300, amp=6000)  # đầu app đang nói: >> -40 dBFS

    async def run(app_talking: bool) -> float:
        call = call_bridge.Call("c-hd", DEV, "Mẹ", "to_relative")
        call.state = ACTIVE
        call._to_app = asyncio.Queue()
        if app_talking:
            call._on_app_frame(loud)
        call.from_glasses(mic)
        _, frame = call._to_app.get_nowait()
        return call_bridge.rms_dbfs(frame)

    plain, ducked = asyncio.run(run(False)), asyncio.run(run(True))
    assert plain - ducked == pytest.approx(config.CALL_HALF_DUPLEX_DUCK_DB, abs=0.5)


def test_incoming_call_answer_and_busy(env):
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        assert _event(env, "call_incoming", "c-in", direction="to_glasses").status_code == 200
        _until_state(glasses, RINGING_IN)
        # callback lặp (cùng Idempotency-Key) và cuộc gọi thứ hai trên cùng kính: 2xx, AB được báo busy
        assert _event(env, "call_incoming", "c-in", direction="to_glasses").status_code == 200
        r = _event(env, "call_incoming", "c-in2", direction="to_glasses")
        assert r.status_code == 200 and r.json()["data"]["matched"] is False
        assert _wait(lambda: ("/api/v1/service/call/c-in2/hangup", {"reason": "busy"}) in
                     [(p, {"reason": b.get("reason")}) for p, b in env.ab])
        # kính bấm nghe: VH gửi AB media_token (VH tự sinh), xong mới active
        glasses.send_text(json.dumps({"t": "call_answer", "call": "c-in"}))
        _until_state(glasses, ACTIVE)
        answer = next(b for p, b in env.ab if p.endswith("/call/c-in/answer"))
        call = calls.by_device(DEV)
        assert answer["media_token"] == call.media_token and call.state == ACTIVE


def test_internal_calls_requires_callback_token(env):
    r = env.cb.post("/internal/calls", json={"event": "call_ended", "call_id": "x"})
    assert r.status_code == 401


def test_call_ended_while_ringing(env):
    """AB thu hồi liên kết (`revoked`) khi kính còn đang chuông: dừng chuông, ended + lý do, không báo AB lại."""
    with env.client.websocket_connect("/v2/session") as glasses:
        _hello(glasses)
        assert _event(env, "call_incoming", "c-rev", direction="to_glasses").status_code == 200
        _until_state(glasses, RINGING_IN)
        assert _event(env, "call_ended", "c-rev", reason="revoked").status_code == 200
        assert _until_state(glasses, ENDED)["reason"] == "revoked"
        assert calls.by_device(DEV) is None
        assert not any(p.endswith("/c-rev/hangup") for p, _ in env.ab)  # sự kiện từ AB không dội ngược
