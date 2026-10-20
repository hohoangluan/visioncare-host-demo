"""Khung debug của `WS /v2/session` (chỉ demo): bật bằng `hello.debug`, kính thật không gửi nên không đổi gì."""

import json
import time

from fastapi.testclient import TestClient

from app import app
from live import hazard
from tests.test_v2_api import _jpeg, _gemma, world  # noqa: F401 (fixture)
from tests.test_v2_session import _chat, _hello_debug, _send_turn, _hello

client = TestClient(app)
DEBUG_FRAMES = {"trace", "say", "det", "ocr", "mode"}


def _frames_until_end(ws, turn):
    """Mọi khung text từ lúc gọi tới `reply_end` của `turn` (bỏ audio)."""
    frames = []
    while True:
        msg = ws.receive()
        if msg.get("text") is None:
            continue
        frame = json.loads(msg["text"])
        frames.append(frame)
        if frame["t"] == "reply_end" and frame["turn"] == turn:
            return frames


def test_no_debug_flag_means_no_debug_frames(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="dbg-off")
        ok = json.loads(ws.receive_text())
        assert ok["t"] == "hello_ok" and "debug" not in ok
        _send_turn(ws, "t1")
        frames = _frames_until_end(ws, "t1")
        ws.send_text('{"t":"ping"}')
        while True:  # sau pong không còn khung debug nào đến muộn
            msg = ws.receive()
            if msg.get("text"):
                frame = json.loads(msg["text"])
                frames.append(frame)
                if frame["t"] == "pong":
                    break
    assert not DEBUG_FRAMES & {f["t"] for f in frames}, frames


def test_debug_turn_emits_mode_trace_say(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/session") as ws:
        _hello_debug(ws, device="dbg-on")
        ok = json.loads(ws.receive_text())
        assert ok["t"] == "hello_ok" and ok["debug"] is True
        assert json.loads(ws.receive_text()) == {
            "t": "mode", "obstacle": False, "ocr": False, "navigating": False, "music": False, "call": None}
        _send_turn(ws, "t1")
        frames = _frames_until_end(ws, "t1")
        ws.send_text('{"t":"ping"}')
        while frames[-1]["t"] != "pong":  # khung mode sau lượt đến trước pong
            frames.append(json.loads(ws.receive_text()))
    kinds = [f["t"] for f in frames]
    assert kinds.index("trace") < kinds.index("reply")  # trace đi trước reply
    trace = next(f for f in frames if f["t"] == "trace")
    assert trace["turn"] == "t1" and trace["transcript"] and trace["intent"] == "chat" and trace["lane"] == "A"
    assert trace["source"] and trace["params"] == {} and trace["cues"] == [] and trace["live"] is None
    assert trace["pending"] is None
    assert {"audio_s", "upload_s", "final_stt_s", "intent_s", "route_s", "release_to_reply_s"} <= set(trace["timings"])
    said = [f for f in frames if f["t"] == "say"]
    assert said and all(f["turn"] == "t1" and f["text"].strip() for f in said)
    assert "Phía trước có một cái bàn." in " ".join(f["text"] for f in said)
    assert "mode" in kinds[kinds.index("reply_end"):]  # device_state có thể đổi sau lượt


def test_debug_nav_frame_has_boxes_and_sent(world, monkeypatch):  # noqa: F811
    class FakeYolo:
        def detect(self, bgr):
            return [hazard.Detection("motorbike", "vehicle", 0.9, (0.35, 0.2, 0.75, 0.95))]

    monkeypatch.setattr(hazard, "detector", lambda: FakeYolo())
    rec, labels, _ = world
    rec.text = "DẪN TÔI TỚI CHỢ BẾN THÀNH"
    labels["dẫn tôi tới chợ bến thành"] = _gemma("nav_start")
    with client.websocket_connect("/v2/session") as ws:
        _hello_debug(ws, device="dbg-nav")
        ws.receive_text(), ws.receive_text()  # hello_ok + mode
        _send_turn(ws, "N")
        frames = _frames_until_end(ws, "N")
        assert next(f for f in frames if f["t"] == "reply")["live"] == "nav"
        assert next(f for f in frames if f["t"] == "trace")["live"] == "nav"
        modes = [f for f in frames if f["t"] == "mode"]
        ws.send_bytes(bytes([4]) + _jpeg(320, 240))
        det, deadline = None, time.monotonic() + 10
        while det is None and time.monotonic() < deadline:
            msg = ws.receive()
            if msg.get("text"):
                frame = json.loads(msg["text"])
                if frame["t"] == "mode":
                    modes.append(frame)
                if frame["t"] == "det":
                    det = frame
    assert any(m["obstacle"] for m in modes)  # live nav bật -> khung mode báo obstacle
    assert det is not None and (det["w"], det["h"]) == (320, 240)
    box = det["boxes"][0]
    assert box["kind"] == "motorbike" and box["level"] == 3 and box["box"] == [0.35, 0.2, 0.75, 0.95]
    assert det["hazard"] == {"level": 3, "dir": "center", "kind": "motorbike"} and det["sent"] is True


def test_ocr_live_debug_frame_has_pixel_boxes(monkeypatch):
    import asyncio

    from lanes import ocr_live
    from live import text_align
    from live.session import LiveSession
    from tests.test_v2_units import _FakeNavWS

    monkeypatch.setattr(text_align, "detector", lambda: text_align.MorphDetector())
    seen = []

    class Ws(_FakeNavWS):
        debug = staticmethod(seen.append)

    async def go():
        ws, session = Ws(), LiveSession("tok", "dev", "ocr", {"mode": "read"})
        task = asyncio.create_task(ocr_live.run(ws, session))
        await ws.inbox.put({"type": "websocket.receive", "bytes": bytes([1]) + _jpeg(640, 480, text_lines=True)})
        for _ in range(300):
            if seen:
                break
            await asyncio.sleep(0.01)
        session.closed.set()
        await ws.inbox.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    frame = seen[0]
    assert frame["t"] == "ocr" and (frame["w"], frame["h"]) == (640, 480)
    assert frame["boxes"] and all(0 <= b[0] < b[2] <= 640 and 0 <= b[1] < b[3] <= 480 for b in frame["boxes"])
    assert frame["capture"] is False and (frame["cue"] is None or isinstance(frame["cue"], str))


def test_pending_question_reports_what_the_next_turn_answers():
    from lanes import phone

    phone._CONFIRM.clear()
    phone._PENDING.clear()
    assert phone.pending_question("pq") is None
    phone.set_pending("pq", "nav_start")
    assert phone.pending_question("pq") == "Bạn muốn đi đâu?"
    phone.set_pending_confirm("pq", "nav_start", {"destination": "chợ Bến Thành"})
    assert phone.pending_question("pq").endswith("phải không?")
    phone._CONFIRM.clear()
    phone._PENDING.clear()
