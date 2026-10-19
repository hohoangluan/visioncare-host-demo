"""Test đầu-cuối `/v2/image`, `/v2/turn`, `/v2/live` với model/mạng giả."""

import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from app import app
from handlers import action_flow
from lanes import ocr_live, phone
from live import hazard, text_align
from live.session import sessions
from models import clef, llm
from pipeline import adpcm, cues, intent_early, stt, tts
from pipeline.image_buffer import image_buffer

client = TestClient(app)

TOKEN_HEADERS = {"X-Device-Id": "aa:bb", "X-Cue-Version": str(cues.CUE_VERSION),
                 "Accept": "audio/wav;codec=ima_adpcm"}


class _Rec:
    text = ""

    def create_stream(self):
        rec = self

        class S:
            result = type("R", (), {"text": ""})()

            def accept_waveform(self, rate, samples):
                pass
        s = S()
        s.result = type("R", (), {"text": rec.text})()
        return s

    def decode_stream(self, stream):
        pass


@pytest.fixture
def world(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(stt, "_load_asr", lambda: rec)
    calls = {"clef": [], "llm": [], "actions": []}
    labels: dict[str, clef.ClefResult] = {}

    async def fake_clef(text, device=None):
        calls["clef"].append(text)
        return labels.get(text.lower())

    monkeypatch.setattr(intent_early.classifier, "available", lambda: True)
    monkeypatch.setattr(intent_early.classifier, "classify", fake_clef)

    async def fake_stream(messages, max_tokens=None, **extra):
        calls["llm"].append(messages)
        for piece in ("Phía trước có ", "một cái bàn. ", "Bên phải là cửa ra vào."):
            yield piece

    async def fake_json(prompt, schema, max_tokens=120):
        slot = next(iter(schema["properties"]))
        return {slot: "chợ Bến Thành" if slot == "destination" else "mẹ"}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    monkeypatch.setattr(llm, "generate_json", fake_json)
    monkeypatch.setattr(llm, "prewarm", noop)

    def fake_pcm(text):
        yield b"\x10\x00" * 8000  # 0,5 s

    monkeypatch.setattr(tts, "synthesize_stream", fake_pcm)

    def fake_handler(name):
        def handle(image, text, params=None):
            calls["actions"].append((name, params))
            yield f"Đã làm {name}."
        return handle

    for name in list(phone.HANDLERS):
        monkeypatch.setitem(phone.HANDLERS, name, fake_handler(name))

    action_flow.reset_state()
    image_buffer.clear()
    sessions.clear()
    monkeypatch.setattr(text_align, "detector", lambda: text_align.MorphDetector())
    yield rec, labels, calls
    sessions.clear()


def _adpcm_chunks(seconds=1.0, chunk=512):
    pcm = (np.random.default_rng(0).standard_normal(int(16000 * seconds)) * 2000).astype("<i2").tobytes()
    data = adpcm.encode_blocks(pcm)
    for i in range(0, len(data), chunk):
        yield data[i:i + chunk]


def _turn(turn_id, headers=None):
    return client.post(
        "/v2/turn", content=_adpcm_chunks(),
        headers={**TOKEN_HEADERS, "X-Turn-Id": turn_id,
                 "Content-Type": "audio/x-adpcm-ima; rate=16000; channels=1; block=256",
                 **(headers or {})},
    )


def _jpeg(w, h, text_lines=False) -> bytes:
    import cv2

    img = np.full((h, w, 3), 255, np.uint8)
    if text_lines:
        for i, y in enumerate(range(int(h * 0.35), int(h * 0.65), max(30, h // 12))):
            cv2.putText(img, "Chuong %d noi dung sach rat dai" % i, (int(w * 0.15), y),
                        cv2.FONT_HERSHEY_SIMPLEX, w / 700, (0, 0, 0), max(2, w // 400))
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def _scene() -> bytes:
    """Ảnh "chụp thật": độ sáng vừa phải, có chi tiết (ảnh trắng trơn bị chặn vì quá sáng)."""
    import cv2

    img = np.random.default_rng(1).integers(60, 190, (1200, 1600, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _post_image(turn_id, jpeg):
    r = client.post("/v2/image", content=jpeg, headers={**TOKEN_HEADERS, "X-Turn-Id": turn_id})
    assert r.status_code == 204


def test_chat_turn_streams_adpcm_answer(world):
    rec, labels, calls = world
    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    labels["kể chuyện cười đi"] = clef.ClefResult("chat", 0.9)
    r = _turn("t1")
    assert r.status_code == 200
    assert r.headers["x-audio-encoding"] == "ima_adpcm"
    assert r.content[:4] == b"RIFF" and len(r.content) > 1000
    assert "x-live" not in r.headers
    assert len(calls["llm"]) == 1  # câu trả lời song song với Clef được dùng lại, không gọi lần 2


def test_space_turn_uses_buffered_image(world):
    rec, labels, calls = world
    rec.text = "TRƯỚC MẶT TÔI CÓ GÌ"
    labels["trước mặt tôi có gì"] = clef.ClefResult("space", 0.9)
    _post_image("t2", _scene())
    r = _turn("t2")
    assert r.status_code == 200 and len(r.content) > 1000
    content = calls["llm"][-1][1]["content"]
    assert content[0]["type"] == "image_url"  # ảnh đứng trước chữ (prefix cache)


def test_space_without_image_answers_with_cue(world):
    rec, labels, _ = world
    rec.text = "TRƯỚC MẶT TÔI CÓ GÌ"
    labels["trước mặt tôi có gì"] = clef.ClefResult("space", 0.9)
    config_wait = config.IMAGE_WAIT_S
    try:
        config.IMAGE_WAIT_S = 0.05
        r = _turn("t3")
    finally:
        config.IMAGE_WAIT_S = config_wait
    assert r.headers["x-cue"] == "no_image" and r.content == b""


def test_old_firmware_hears_cue_as_speech(world):
    rec, labels, _ = world
    rec.text = ""
    r = _turn("t4", headers={"X-Cue-Version": ""})
    assert "x-cue" not in r.headers
    assert r.content[:4] == b"RIFF" and len(r.content) > 1000


def test_no_speech_is_a_cue(world):
    rec, _, _ = world
    rec.text = ""
    r = _turn("t5")
    assert r.headers["x-cue"] == "no_speech" and r.content == b""


def test_nav_start_opens_live_and_runs_phone_action(world):
    rec, labels, calls = world
    rec.text = "DẪN TÔI TỚI CHỢ BẾN THÀNH"
    labels["dẫn tôi tới chợ bến thành"] = clef.ClefResult("nav_start", 0.9)
    r = _turn("t6")
    assert r.headers["x-cue"] == "nav_alert_on"
    assert r.headers["x-live"] == "nav" and r.headers["x-live-token"]
    import time
    for _ in range(50):
        if calls["actions"]:
            break
        time.sleep(0.02)
    assert calls["actions"] == [("nav_start", {"destination": "chợ Bến Thành"})]


def test_missing_slot_asks_then_next_turn_fills_it(world):
    rec, labels, calls = world
    rec.text = "GỌI ĐIỆN"
    labels["gọi điện"] = clef.ClefResult("contact_call", 0.9)

    async def empty_json(prompt, schema, max_tokens=120):
        return {"contact_name": ""}

    llm_json = llm.generate_json
    llm.generate_json = empty_json
    try:
        r = _turn("t7")
    finally:
        llm.generate_json = llm_json
    assert r.headers["x-cue"] == "ask_contact_name"
    rec.text = "MẸ"
    labels["mẹ"] = clef.ClefResult("chat", 0.6)
    r = _turn("t8")
    assert calls["actions"] == [("contact_call", {"contact_name": "Mẹ"})]
    assert len(r.content) > 1000


def test_ocr_reads_buffer_directly_when_frame_is_good(world):
    rec, labels, calls = world
    rec.text = "ĐỌC GIÚP TÔI TRANG SÁCH NÀY"
    labels["đọc giúp tôi trang sách này"] = clef.ClefResult("ocr", 0.9, "read")
    _post_image("t9", _jpeg(1600, 1200, text_lines=True))
    r = _turn("t9")
    assert "x-live" not in r.headers, r.headers
    assert len(r.content) > 1000
    assert ocr_live.last_text("aa:bb")


def test_ocr_opens_live_alignment_when_frame_is_bad(world):
    rec, labels, _ = world
    rec.text = "ĐỌC GIÚP TÔI TRANG SÁCH NÀY"
    labels["đọc giúp tôi trang sách này"] = clef.ClefResult("ocr", 0.9, "read")
    _post_image("t10", _jpeg(1600, 1200))  # trắng trơn, không chữ
    r = _turn("t10")
    assert r.headers["x-cue"] == "ocr_start" and r.headers["x-live"] == "ocr"


def test_live_rejects_unknown_token(world):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v2/live?token=nope") as ws:
            ws.receive_text()


def test_nav_live_sends_hazard_for_close_vehicle(world, monkeypatch):
    class FakeYolo:
        def detect(self, bgr):
            return [hazard.Detection("motorbike", "vehicle", 0.9, (0.35, 0.2, 0.75, 0.95))]

    monkeypatch.setattr(hazard, "detector", lambda: FakeYolo())
    session = sessions.create("aa:bb", "nav")
    frame = bytes([1]) + _jpeg(320, 240)
    with client.websocket_connect(f"/v2/live?token={session.token}") as ws:
        ws.send_text(json.dumps({"t": "hello", "device": "aa:bb", "cue_version": 2}))
        assert json.loads(ws.receive_text()) == {"t": "cam", "size": "qvga", "fps": 8, "quality": 15}
        ws.send_bytes(frame)
        msg = json.loads(ws.receive_text())
        assert msg == {"t": "hazard", "level": 3, "dir": "center", "kind": "motorbike"}


def test_ocr_live_aligns_captures_and_reads(world, monkeypatch):
    monkeypatch.setattr(config, "OCR_GOOD_FRAMES", 2)
    session = sessions.create("aa:bb", "ocr", {"mode": "read"})
    good = bytes([1]) + _jpeg(640, 480, text_lines=True)
    with client.websocket_connect(f"/v2/live?token={session.token}") as ws:
        assert json.loads(ws.receive_text())["t"] == "cam"
        ws.send_bytes(good)
        ws.send_bytes(good)
        assert json.loads(ws.receive_text()) == {"t": "capture", "size": "uxga"}
        ws.send_bytes(bytes([1]) + _jpeg(1600, 1200, text_lines=True))
        audio = ws.receive_bytes()
        assert audio[0] == 0x02 and len(audio) > 1
        while True:
            msg = ws.receive()
            if msg.get("text"):
                assert json.loads(msg["text"]) == {"t": "end"}
                break
    assert ocr_live.last_text("aa:bb")
