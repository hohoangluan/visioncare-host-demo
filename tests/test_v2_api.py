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
    # Audio ở đây là âm tổng hợp, Silero không coi là tiếng người; VAD có test riêng trong test_v2_units.
    monkeypatch.setattr(config, "VAD_ENABLED", False)
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
    phone._CONFIRM.clear()
    image_buffer.clear()
    sessions.clear()
    monkeypatch.setattr(text_align, "detector", lambda: text_align.MorphDetector())
    yield rec, labels, calls
    sessions.clear()


def _gemma(intent, confidence=0.9995):
    """Nhãn do Gemma gán (làn D chỉ tin nguồn này)."""
    result = clef.ClefResult(intent, confidence)
    result.source = "gemma"
    return result


def _wait_actions(calls, n=1, timeout=3.0):
    import time
    end = time.monotonic() + timeout
    while len(calls["actions"]) < n and time.monotonic() < end:
        time.sleep(0.02)


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
    labels["dẫn tôi tới chợ bến thành"] = _gemma("nav_start")
    r = _turn("t6")
    assert r.headers["x-cue"] == "nav_alert_on"
    assert r.headers["x-live"] == "nav" and r.headers["x-live-token"]
    import time
    for _ in range(150):
        if calls["actions"]:
            break
        time.sleep(0.02)
    assert calls["actions"] == [("nav_start", {"destination": "chợ Bến Thành"})]


def test_missing_slot_asks_then_next_turn_fills_it(world):
    rec, labels, calls = world
    rec.text = "GỌI ĐIỆN"
    labels["gọi điện"] = _gemma("contact_call")

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
    assert calls["actions"] == []  # câu điền chỗ trống chưa đủ tin -> hỏi lại, chưa gọi
    assert len(r.content) > 1000
    rec.text = "ĐÚNG"
    labels["đúng"] = clef.ClefResult("chat", 0.9)
    r = _turn("t8b")
    _wait_actions(calls)
    assert calls["actions"] == [("contact_call", {"contact_name": "Mẹ"})]


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


# ── cổng an toàn làn D (Task 6) ───────────────────────────────────────────────

def test_keyword_only_never_triggers_lane_d(world):
    rec, labels, calls = world  # bộ phân loại không có nhãn -> trả None
    rec.text = "GỌI CHO MẸ"
    r = _turn("k1")
    assert r.headers["x-cue"] == "system_busy"
    import time
    time.sleep(0.5)
    assert calls["actions"] == []


def test_low_confidence_asks_back(world):
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    labels["gọi cho mẹ"] = _gemma("contact_call", 0.6)
    r = _turn("l1")
    assert "x-cue" not in r.headers and len(r.content) > 1000  # câu hỏi lại
    import time
    time.sleep(0.5)
    assert calls["actions"] == []
    assert phone.take_pending_confirm("aa:bb")[0] == "contact_call"


def test_missing_logprobs_asks_back_on_lane_d_but_other_lanes_run(world):
    """Gemma không trả logprobs (confidence_known=False): lệnh làn D hỏi lại, KHÔNG chạy; làn A vẫn trả lời."""
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    result = _gemma("contact_call", 1.0)
    result.confidence_known = False
    labels["gọi cho mẹ"] = result
    r = _turn("nl1")
    assert len(r.content) > 1000  # câu hỏi lại "... phải không?"
    import time
    time.sleep(0.5)
    assert calls["actions"] == []
    assert phone.take_pending_confirm("aa:bb")[0] == "contact_call"

    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    chat = _gemma("chat", 1.0)
    chat.confidence_known = False
    labels["kể chuyện cười đi"] = chat
    r = _turn("nl2")
    assert len(r.content) > 1000 and calls["llm"]  # làn A chạy như thường


def test_clef_backend_asks_back(world):
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    result = clef.ClefResult("contact_call", 0.9995)
    result.source = "clef"
    labels["gọi cho mẹ"] = result
    _turn("c1")
    import time
    time.sleep(0.5)
    assert calls["actions"] == []


def test_confident_gemma_reads_back_then_fires(world):
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    labels["gọi cho mẹ"] = _gemma("contact_call")
    r = _turn("g1")
    assert len(r.content) > 1000
    _wait_actions(calls)
    assert calls["actions"] == [("contact_call", {"contact_name": "mẹ"})]


def test_new_turn_cancels_pending_action(world, monkeypatch):
    rec, labels, calls = world
    monkeypatch.setattr(config, "ACTION_TTS_LEAD_S", 2.0)  # cửa sổ huỷ rộng, test không phụ thuộc tốc độ
    rec.text = "GỌI CHO MẸ"
    labels["gọi cho mẹ"] = _gemma("contact_call")
    _turn("n1")
    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    labels["kể chuyện cười đi"] = clef.ClefResult("chat", 0.9)
    _turn("n2")  # lượt mới ngay -> huỷ lệnh chờ
    import time
    time.sleep(3.0)
    assert calls["actions"] == []


def test_rubbish_transcript_no_action(world):
    rec, labels, calls = world
    rec.text = "Ờ Ờ"
    labels["ờ ờ"] = clef.ClefResult("chat", 0.5)
    _turn("r1")
    import time
    time.sleep(0.5)
    assert calls["actions"] == []


def test_confirmed_no_cancels(world):
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    labels["gọi cho mẹ"] = _gemma("contact_call", 0.5)
    _turn("no1")
    rec.text = "KHÔNG"
    labels["không"] = clef.ClefResult("chat", 0.9)
    r = _turn("no2")
    assert len(r.content) > 1000  # "Đã huỷ."
    import time
    time.sleep(0.5)
    assert calls["actions"] == []
    assert phone.take_pending_confirm("aa:bb") is None


def test_question_starting_with_yes_word_does_not_confirm(world):
    rec, labels, calls = world
    rec.text = "GỌI CHO MẸ"
    labels["gọi cho mẹ"] = _gemma("contact_call", 0.5)
    _turn("q1")
    rec.text = "CÓ GÌ TRƯỚC MẶT"
    labels["có gì trước mặt"] = clef.ClefResult("chat", 0.9)
    _turn("q2")
    import time
    time.sleep(0.5)
    assert calls["actions"] == []


def test_yes_no_matching_is_whole_utterance():
    assert phone.is_yes("Đúng rồi".replace(" rồi", "")) and phone.is_yes("Ừ, đồng ý!")
    assert not phone.is_yes("có gì trước mặt") and not phone.is_yes("được rồi gọi cho bố")
    assert phone.is_no("Thôi.") and not phone.is_no("không phải, gọi cho bố đi")


def test_stale_turn_does_not_schedule():
    from pipeline import pending_action
    fired = []
    gen_a = pending_action.begin_turn("dev-x")
    pending_action.begin_turn("dev-x")  # lượt B bắt đầu trong lúc A còn ở router
    assert pending_action.schedule("dev-x", 0.0, lambda: fired.append(1), "t", gen=gen_a) is None
    import time
    time.sleep(0.2)
    assert fired == []


def test_keyword_still_allows_music_stop_when_model_down(world):
    rec, labels, calls = world
    rec.text = "TẮT NHẠC"
    _turn("ms1")
    _wait_actions(calls)
    assert calls["actions"] and calls["actions"][0][0] == "music_stop"


def test_client_disconnect_cancels_llm(world, monkeypatch):
    """POST bị client ngắt giữa lượt: Gemma bị huỷ, TTS dừng <= 0,5 s, lệnh chờ làn D bị huỷ."""
    import asyncio
    import time

    from app import _v2_response
    from pipeline import pending_action, speech
    from pipeline.reply import Reply

    monkeypatch.setattr(config, "V2_AUDIO_PREROLL_SECONDS", 0.1)
    seen = {"cancelled": None}

    async def blocking_stream(messages, max_tokens=None, **extra):
        try:
            yield "Phía trước có một cái bàn. Bên phải "
            await asyncio.Event().wait()  # Gemma "nghĩ" mãi
        except asyncio.CancelledError:
            seen["cancelled"] = time.monotonic()
            raise

    monkeypatch.setattr(llm, "stream_chat", blocking_stream)
    fired = []

    async def go():
        loop = asyncio.get_running_loop()
        pending_action.schedule("dc-dev", 30, lambda: fired.append(1), "gọi mẹ",
                                gen=pending_action.generation("dc-dev"))
        reply = Reply(speech=speech.sync_iter(llm.stream_chat([]), loop))
        resp = await _v2_response(reply, True, "adpcm_stream", time.monotonic(), "dc-dev")
        got_audio = asyncio.Event()

        async def reader():  # như Starlette: `async for` trên body_iterator, bị huỷ khi client rớt
            async for _ in resp.body_iterator:
                got_audio.set()

        task = asyncio.create_task(reader())
        await asyncio.wait_for(got_audio.wait(), 5)
        t0 = time.monotonic()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        while seen["cancelled"] is None and time.monotonic() - t0 < 2:
            await asyncio.sleep(0.01)
        return t0

    t0 = asyncio.run(go())
    assert seen["cancelled"] is not None and seen["cancelled"] - t0 <= 0.5
    assert not pending_action.cancel("dc-dev", "kiểm")  # đã bị huỷ lúc ngắt
    assert fired == []

# ── /process (firmware cũ) chạy pipeline v2 — Task 12 ─────────────────────

def _process(files_audio=True, image=None, headers=None):
    pcm = (np.random.default_rng(0).standard_normal(16000) * 2000).astype("<i2").tobytes()
    files = {"audio": ("a.adpcm", adpcm.encode_blocks(pcm),
                       "audio/x-adpcm-ima; rate=16000; channels=1; block=256")}
    if image is not None:
        files["image"] = ("i.jpg", image, "image/jpeg")
    return client.post("/process", files=files, headers={"Accept": "audio/wav;codec=ima_adpcm", **(headers or {})})


def test_process_routes_through_v2(world):
    """Firmware cũ: STT -> Clef -> Gemma của v2 (không còn Gemini), ảnh qua Image Buffer."""
    rec, labels, calls = world
    rec.text = "TRƯỚC MẶT TÔI CÓ GÌ"
    labels["trước mặt tôi có gì"] = clef.ClefResult("space", 0.9)
    r = _process(image=_scene())
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF" and len(r.content) > 1000
    assert r.headers["x-audio-encoding"] == "ima_adpcm"
    assert "x-live" not in r.headers
    assert [t.lower() for t in calls["clef"]] == ["trước mặt tôi có gì"]
    assert calls["llm"][-1][1]["content"][0]["type"] == "image_url"  # ảnh /process tới được Gemma


def test_process_nav_no_live(world):
    """Làn C trên /process: chỉ gửi lệnh điện thoại + câu xác nhận, không mở phiên live."""
    rec, labels, calls = world
    rec.text = "DẪN TÔI TỚI CHỢ BẾN THÀNH"
    labels["dẫn tôi tới chợ bến thành"] = _gemma("nav_start")
    r = _process()
    assert r.status_code == 200 and len(r.content) > 1000
    assert "x-live" not in r.headers and "x-live-token" not in r.headers
    assert sessions.active(config.VISIONCARE_DEVICE_ID) is None
    import time
    # /process: cửa sổ huỷ = câu mở đầu + đệm 2 s + câu đọc lại (đếm từ byte đầu gửi đi), nên lệnh tới muộn hơn /v2.
    for _ in range(600):
        if calls["actions"]:
            break
        time.sleep(0.02)
    assert calls["actions"] == [("nav_start", {"destination": "chợ Bến Thành"})]
