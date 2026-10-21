"""`WS /v2/observe`: phiên chỉ xem của trang demo. Thấy mọi thứ kính gửi/nhận mà không thay phiên của kính."""

import json
import time

from fastapi.testclient import TestClient

from app import app
from live import hazard
from live.observers import observers
from tests.conftest import TEST_DEVICE_TOKEN
from tests.test_debug_frames import DEBUG_FRAMES
from tests.test_device_tokens import TOK_A, TOK_B, per_device_tokens  # noqa: F401 (fixture)
from tests.test_v2_api import _gemma, _jpeg, world  # noqa: F401 (fixture)
from tests.test_v2_session import _chat, _hello, _send_turn, _sync

client = TestClient(app)


def _observe_hello(ws, token=TEST_DEVICE_TOKEN, **extra):
    ws.send_text(json.dumps({"t": "hello", "token": token, **extra}))


def _read(ws, until, limit=200):
    """Đọc (kind, nội dung) tới khi `until(frame)` đúng cho một khung JSON; trả toàn bộ danh sách đã đọc."""
    seen = []
    for _ in range(limit):
        msg = ws.receive()
        if msg.get("bytes") is not None:
            seen.append(("bin", msg["bytes"]))
            continue
        frame = json.loads(msg["text"])
        seen.append(("json", frame))
        if until(frame):
            return seen
    raise AssertionError(f"không thấy khung mong đợi: {seen[-5:]}")


def _hello_ok(ws):
    return _read(ws, lambda f: f["t"] == "hello_ok")[-1][1]


def test_bad_token_closes_4401(world):  # noqa: F811
    with client.websocket_connect("/v2/observe") as ws:
        _observe_hello(ws, token="sai-token")
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401


def test_first_frame_must_be_hello(world):  # noqa: F811
    with client.websocket_connect("/v2/observe") as ws:
        ws.send_text('{"t":"ping"}')
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4400


def test_hello_ok_says_glasses_offline_then_online(world):  # noqa: F811
    with client.websocket_connect("/v2/observe") as obs:
        _observe_hello(obs)
        ok = _hello_ok(obs)
        assert ok["role"] == "observer" and ok["glasses"] is False and ok["watch"] == "*"
        with client.websocket_connect("/v2/session") as glasses:
            _hello(glasses, device="obs-on")
            online = _read(obs, lambda f: f["t"] == "glasses" and f["online"])[-1][1]
            assert online["device"] == "obs-on" and online["session"]
            mode = _read(obs, lambda f: f["t"] == "mode")[-1][1]
            assert mode["obstacle"] is False and mode["call"] is None
        _read(obs, lambda f: f["t"] == "glasses" and not f["online"])


def test_observer_joining_late_gets_glasses_and_mode(world):  # noqa: F811
    with client.websocket_connect("/v2/session") as glasses:
        _hello(glasses, device="obs-late")
        assert json.loads(glasses.receive_text())["t"] == "hello_ok"
        with client.websocket_connect("/v2/observe") as obs:
            _observe_hello(obs, device="obs-late")
            ok = _hello_ok(obs)
            assert ok["glasses"] is True and ok["watch"] == "obs-late"
            _read(obs, lambda f: f["t"] == "glasses" and f["online"])
            _read(obs, lambda f: f["t"] == "mode")


def test_observer_sees_the_whole_turn_and_glasses_get_no_debug(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/observe") as obs, client.websocket_connect("/v2/session") as glasses:
        _observe_hello(obs)
        _hello_ok(obs)
        _hello(glasses, device="obs-turn")  # kính KHÔNG khai debug
        assert json.loads(glasses.receive_text())["t"] == "hello_ok"
        _send_turn(glasses, "t1")
        seen = _read(obs, lambda f: f["t"] == "reply_end" and f.get("turn") == "t1")
        kinds = [k if k == "bin" else v["t"] for k, v in seen]
        assert kinds.index("turn_start") < kinds.index("trace") < kinds.index("reply") < kinds.index("reply_end")
        assert "turn_end" in kinds
        trace = next(v for k, v in seen if k == "json" and v["t"] == "trace")
        assert trace["turn"] == "t1" and trace["transcript"] and trace["intent"] == "chat"
        said = " ".join(v["text"] for k, v in seen if k == "json" and v["t"] == "say")
        assert "Phía trước có một cái bàn." in said
        audio = [v for k, v in seen if k == "bin" and v[0] == 0x02]
        assert audio and sum(len(a) - 1 for a in audio) > 1000  # tiếng trả lời kính nghe, người xem cũng nghe
        # Kính thật vẫn y như cũ: không có khung debug nào lọt sang kính.
        got = []
        glasses.send_text('{"t":"ping"}')
        while True:
            msg = glasses.receive()
            if msg.get("text"):
                frame = json.loads(msg["text"])
                got.append(frame["t"])
                if frame["t"] == "pong":
                    break
        assert not DEBUG_FRAMES & set(got), got


def test_turn_image_is_relayed_as_0x01(world):  # noqa: F811
    _chat(world)
    image = _jpeg(320, 240)
    with client.websocket_connect("/v2/observe") as obs, client.websocket_connect("/v2/session") as glasses:
        _observe_hello(obs)
        _hello_ok(obs)
        _hello(glasses, device="obs-img")
        glasses.receive_text()
        glasses.send_text(json.dumps({"t": "turn_start", "turn": "i1", "t_press_ms": 0}))
        glasses.send_bytes(b"\x01" + image)
        _sync(glasses)
        seen = _read(obs, lambda f: f["t"] == "turn_start")
        glasses.send_text(json.dumps({"t": "turn_end", "turn": "i1", "t_release_ms": 0}))
        more = _read(obs, lambda f: f["t"] == "turn_end")
        frames = seen + more
        imgs = [v for k, v in frames if k == "bin" and v[0] == 0x01]
        assert imgs == [b"\x01" + image]


def test_observer_does_not_replace_glasses_session(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/session") as glasses:
        _hello(glasses, device="obs-keep")
        glasses.receive_text()
        with client.websocket_connect("/v2/observe") as obs:
            _observe_hello(obs, device="obs-keep")
            _hello_ok(obs)
        _send_turn(glasses, "t1")  # kính vẫn sống và vẫn chạy lượt được sau khi người xem vào/ra
        while True:
            msg = glasses.receive()
            assert msg["type"] == "websocket.send", msg
            if msg.get("text") and json.loads(msg["text"]).get("t") == "reply_end":
                break


def test_nav_det_comes_with_the_exact_jpeg_it_was_computed_on(world, monkeypatch):  # noqa: F811
    class FakeYolo:
        def detect(self, bgr):
            return [hazard.Detection("motorbike", "vehicle", 0.9, (0.35, 0.2, 0.75, 0.95))]

    monkeypatch.setattr(hazard, "detector", lambda: FakeYolo())
    rec, labels, _ = world
    rec.text = "BẬT CẢNH BÁO VẬT CẢN"
    labels["bật cảnh báo vật cản"] = _gemma("alert_on")
    frame = _jpeg(320, 240)
    with client.websocket_connect("/v2/observe") as obs, client.websocket_connect("/v2/session") as glasses:
        _observe_hello(obs)
        _hello_ok(obs)
        _hello(glasses, device="obs-nav")  # kính không khai debug
        glasses.receive_text()
        _send_turn(glasses, "N")
        _read(obs, lambda f: f["t"] == "reply_end" and f.get("turn") == "N")
        glasses.send_bytes(bytes([4]) + frame)
        seen = _read(obs, lambda f: f["t"] == "det")
        det = seen[-1][1]
        assert (det["w"], det["h"]) == (320, 240) and det["sent"] is True
        assert "_jpeg" not in det and det["boxes"][0]["kind"] == "motorbike"
        assert seen[-2] == ("bin", bytes([4]) + frame)  # khung 0x04 đi NGAY trước JSON det của nó
        # Kính nhận hazard nhưng không nhận det.
        got = []
        glasses.send_text('{"t":"ping"}')
        while True:
            msg = glasses.receive()
            if msg.get("text"):
                t = json.loads(msg["text"])["t"]
                got.append(t)
                if t == "pong":
                    break
        assert "det" not in got and "hazard" in got


def test_observer_registry_is_cleaned_up(world):  # noqa: F811
    with client.websocket_connect("/v2/observe") as obs:
        _observe_hello(obs)
        _hello_ok(obs)
        assert observers.any("whoever")
    deadline = time.monotonic() + 3
    while observers.any("whoever") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not observers.any("whoever")


def test_per_device_token_observes_only_its_own_glasses(world, per_device_tokens):  # noqa: F811
    with client.websocket_connect("/v2/observe") as obs:
        _observe_hello(obs, token=TOK_A)
        ok = _hello_ok(obs)
        assert ok["watch"] == "dev-a"
        with client.websocket_connect("/v2/session") as other:  # kính khác: người xem token A không thấy
            _hello(other, device="dev-b", token=TOK_B)
            other.receive_text()
            with client.websocket_connect("/v2/session") as mine:
                _hello(mine, device="dev-a", token=TOK_A)
                mine.receive_text()
                online = _read(obs, lambda f: f["t"] == "glasses")[-1][1]
                assert online["device"] == "dev-a"  # frame đầu tiên người xem nhận là của dev-a, không phải dev-b


def test_per_device_token_cannot_claim_another_device(world, per_device_tokens):  # noqa: F811
    with client.websocket_connect("/v2/observe") as obs:
        _observe_hello(obs, token=TOK_A, device="dev-b")
        msg = obs.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401


def test_observer_sees_phone_result_for_the_phone_panel(world):  # noqa: F811
    """Ô "Điện thoại" của bảng giám sát lấy kết quả lệnh từ `/v2/observe`: `reply`/`say`/`reply_end` mang turn `result-<id>`."""
    import threading

    from live import device_session

    with client.websocket_connect("/v2/observe") as obs, client.websocket_connect("/v2/session") as glasses:
        _observe_hello(obs)
        _hello_ok(obs)
        _hello(glasses, device="obs-phone")
        glasses.receive_text()
        pusher = threading.Thread(target=device_session.push_result, args=("obs-phone", "Đã mở nhạc trên điện thoại.", "req-9"))
        pusher.start()
        pusher.join()
        seen = _read(obs, lambda f: f["t"] == "reply_end" and f.get("turn") == "result-req-9")
    frames = [v for k, v in seen if k == "json"]
    assert any(f["t"] == "reply" and f["turn"] == "result-req-9" for f in frames)
    assert any(f["t"] == "say" and f["turn"] == "result-req-9" and f["text"] == "Đã mở nhạc trên điện thoại." for f in frames)
