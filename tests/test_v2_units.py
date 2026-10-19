"""Unit test cho các mô-đun voice server v2 (không mạng, không model thật)."""

import asyncio
import io
import time

import numpy as np
import pytest
from PIL import Image

import config
from lanes import general, phone
from live import hazard, text_align
from live.session import SessionManager
from models import clef
from pipeline import adpcm, cues, intent_early, stt
from pipeline.final_router import Speculation
from pipeline.image_buffer import ImageBuffer, resize_jpeg
from pipeline.intent_early import EarlyIntent, keyword_rule
from pipeline.stt_stream import StreamingTranscriber


def _jpeg(w: int, h: int, color=(128, 128, 128)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, format="JPEG")
    return out.getvalue()


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ── cues ──────────────────────────────────────────────────────────────────

def test_cue_version_gate():
    assert cues.supported(str(cues.CUE_VERSION))
    assert not cues.supported(None)
    assert not cues.supported("1")
    assert not cues.supported("abc")


def test_sound_only_cues_have_no_fallback_speech():
    assert cues.fallback_text("shutter") is None
    assert cues.fallback_text("ask_destination") == "Bạn muốn đi đâu?"
    assert "Bạn muốn đi đâu?" in cues.STATIC_SPEECH


# ── image buffer ──────────────────────────────────────────────────────────

def test_resize_jpeg_shrinks_uxga_and_keeps_small():
    big = _jpeg(1600, 1200)
    small = resize_jpeg(big, 896)
    assert max(Image.open(io.BytesIO(small)).size) <= 896
    tiny = _jpeg(320, 240)
    assert resize_jpeg(tiny, 896) is tiny


def test_image_buffer_put_get_and_wait():
    buf = ImageBuffer()
    assert buf.get("d", "1") is None
    entry = buf.put("d", "1", _jpeg(1600, 1200))
    assert buf.get("d", "1") is entry
    assert max(Image.open(io.BytesIO(entry.llm_jpeg())).size) <= config.LLM_IMAGE_MAX_SIDE
    assert buf.get("d", "2") is None


def test_image_buffer_wait_returns_when_image_arrives():
    import threading

    buf = ImageBuffer()
    threading.Timer(0.05, lambda: buf.put("d", "t", _jpeg(64, 48))).start()
    started = time.monotonic()
    assert buf.wait("d", "t", 2.0) is not None
    assert time.monotonic() - started < 1.0


def test_image_buffer_expires(monkeypatch):
    buf = ImageBuffer()
    buf.put("d", "1", _jpeg(64, 48))
    monkeypatch.setattr(config, "IMAGE_BUFFER_TTL_S", -1.0)
    assert buf.get("d", "1") is None


# ── pseudo-streaming STT ─────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, owner):
        self.owner = owner
        self.result = type("R", (), {"text": ""})()

    def accept_waveform(self, rate, samples):
        self.owner.seen.append(samples.size)


class _FakeRecognizer:
    def __init__(self, text="ĐỌC GIÚP TÔI"):
        self.text, self.seen, self.decodes = text, [], 0

    def create_stream(self):
        return _FakeStream(self)

    def decode_stream(self, stream):
        self.decodes += 1
        stream.result.text = self.text


@pytest.fixture
def fake_asr(monkeypatch):
    rec = _FakeRecognizer()
    monkeypatch.setattr(stt, "_load_asr", lambda: rec)
    return rec


def _adpcm(seconds: float) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    pcm = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2").tobytes()
    return adpcm.encode_blocks(pcm)


def test_incremental_adpcm_decode_matches_whole_file(fake_asr):
    data = _adpcm(1.0)
    whole = adpcm.decode_blocks(data)
    tr = StreamingTranscriber("audio/x-adpcm-ima; rate=16000; block=256")
    for i in range(0, len(data), 100):  # mảnh không trùng biên khối
        tr.feed(data[i:i + 100])
    tr.final()
    assert fake_asr.seen == [whole.size]


def test_wav_header_stream_is_parsed(fake_asr):
    data = _adpcm(0.5)
    tr = StreamingTranscriber("audio/wav")
    wav = adpcm.wav_header(len(data)) + data
    for i in range(0, len(wav), 7):
        tr.feed(wav[i:i + 7])
    assert tr.final() == "Đọc giúp tôi"
    assert fake_asr.seen == [adpcm.decode_blocks(data).size]


def test_final_reuses_partial_when_no_new_audio(fake_asr):
    tr = StreamingTranscriber()
    tr.feed(_adpcm(0.5))
    assert tr.partial() == "Đọc giúp tôi"
    assert not tr.has_new_audio()
    assert tr.final() == "Đọc giúp tôi"
    assert fake_asr.decodes == 1  # bản ghi cuối không giải lại


def test_final_decodes_again_after_new_audio(fake_asr):
    tr = StreamingTranscriber()
    tr.feed(_adpcm(0.5))
    tr.partial()
    tr.feed(_adpcm(0.5))
    tr.final()
    assert fake_asr.decodes == 2


# ── early / final intent ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Đọc giúp tôi trang sách này", ("ocr", "read")),
    ("Tóm tắt nội dung này", ("ocr", "summarize")),
    ("Đọc lại cho tôi", ("ocr", "reread")),
    ("Trước mặt tôi có gì vậy", ("space", "read")),
    ("Dẫn tôi tới chợ Bến Thành", ("nav_start", "read")),
    ("Tắt cảnh báo", ("alert_off", "read")),
    ("Bật cảnh báo", ("alert_on", "read")),
    ("Gọi cho mẹ", ("contact_call", "read")),
    ("Cứu tôi với", ("emergency_call", "read")),
    ("Tờ tiền này bao nhiêu", ("money", "read")),
    ("Kể chuyện cười đi", None),
])
def test_keyword_rules(text, expected):
    assert keyword_rule(text) == expected


def _clef_available(monkeypatch, fn):
    monkeypatch.setattr(intent_early.classifier, "available", lambda: True)
    monkeypatch.setattr(intent_early.classifier, "classify", fn)


def test_decide_reuses_clef_from_identical_partial(monkeypatch):
    calls = []

    async def fake(text, device=None):
        calls.append(text)
        return clef.ClefResult("chat", 0.9)

    _clef_available(monkeypatch, fake)
    monkeypatch.setattr(config, "EARLY_CLASSIFY_STABLE_S", 0.0)

    async def scenario():
        early = EarlyIntent()
        early.on_partial("kể chuyện cười đi nào", now=0.0)
        early.on_partial("kể chuyện cười đi nào", now=1.0)  # đứng yên -> Clef
        await asyncio.sleep(0)
        return await early.decide("kể chuyện cười đi nào")

    decision = asyncio.run(scenario())
    assert decision.intent == "chat" and decision.source == "model-cache"
    assert calls == ["kể chuyện cười đi nào"]


def test_decide_falls_back_to_keyword_then_chat(monkeypatch):
    async def broken(text, device=None):
        return None

    _clef_available(monkeypatch, broken)
    d = asyncio.run(EarlyIntent().decide("đọc giúp tôi"))
    assert (d.intent, d.source, d.lane) == ("ocr", "keyword", "B")
    d = asyncio.run(EarlyIntent().decide("hôm nay thế nào"))
    assert (d.intent, d.source, d.lane) == ("chat", "fallback-chat", "A")


def test_decide_hedges_a_slow_partial_clef(monkeypatch):
    """Lượt Clef trên partial treo: lượt mới bắn song song về trước thì dùng nó."""
    calls = []

    async def fake(text, device=None):
        calls.append(text)
        if len(calls) == 1:
            await asyncio.sleep(5)  # lượt trên partial treo
        return clef.ClefResult("space", 0.9)

    _clef_available(monkeypatch, fake)
    monkeypatch.setattr(config, "EARLY_CLASSIFY_STABLE_S", 0.0)

    async def scenario():
        early = EarlyIntent()
        early.on_partial("trước mặt có gì", now=0.0)
        early.on_partial("trước mặt có gì", now=1.0)
        await asyncio.sleep(0)
        started = time.monotonic()
        d = await early.decide("trước mặt có gì")
        early.cancel()
        return d, time.monotonic() - started

    d, seconds = asyncio.run(scenario())
    assert d.intent == "space" and d.source == "model" and seconds < 0.5
    assert len(calls) == 2


def test_classifier_prefers_gemma_and_falls_back_to_clef(monkeypatch):
    from models import llm
    from pipeline import intent_classifier

    async def gemma_ok(prompt, schema, max_tokens=120):
        assert prompt.rstrip().endswith('"tắt đi"\nTrả JSON.')  # câu lệnh đứng cuối (prefix cache)
        return {"intent": "music_stop", "ocr_mode": "read", "needs_web": False}

    async def gemma_down(prompt, schema, max_tokens=120):
        raise llm.LLMError("down")

    async def clef_ok(text, device=None):
        return clef.ClefResult("nav_stop", 0.9)

    monkeypatch.setattr(intent_classifier.clef, "classify", clef_ok)
    monkeypatch.setattr(llm, "generate_json", gemma_ok)
    assert asyncio.run(intent_classifier.classify("tắt đi", {"music_playing": True})).intent == "music_stop"
    monkeypatch.setattr(llm, "generate_json", gemma_down)
    assert asyncio.run(intent_classifier.classify("tắt đi")).intent == "nav_stop"
    monkeypatch.setattr(config, "INTENT_BACKEND", "gemma")
    assert asyncio.run(intent_classifier.classify("tắt đi")) is None


def test_reread_goes_to_lane_a():
    assert intent_early.Decision("ocr", "reread").lane == "A"
    assert intent_early.Decision("ocr", "read").lane == "B"


def test_early_guess_triggers_callback_once_per_change():
    seen = []
    early = EarlyIntent(on_guess=lambda i, m, s: seen.append((i, m, s)))
    early.on_partial("đọc", now=0)
    early.on_partial("đọc giúp", now=0.3)
    early.on_partial("đọc giúp tôi tóm tắt", now=0.6)
    assert seen == [("ocr", "read", "keyword"), ("ocr", "summarize", "keyword")]


# ── làn A: câu TTS đầu ngắn ──────────────────────────────────────────────

def _collect(agen):
    async def run():
        return [x async for x in agen]
    return asyncio.run(run())


async def _chunks(*items):
    for item in items:
        yield item


def test_first_sentence_cut_at_punctuation():
    out = _collect(general.short_first_sentence(_chunks("Bên trái có ", "một cái ghế, ", "bên phải là cửa.")))
    assert out[0] == "Bên trái có một cái ghế,\n"
    assert "".join(out[1:]).strip() == "bên phải là cửa."


def test_first_sentence_cut_at_max_words_and_strips_markdown():
    words = "một hai ba bốn năm sáu bảy tám chín mười"
    out = _collect(general.short_first_sentence(_chunks("**" + words + " "), max_words=8))
    assert out[0] == "một hai ba bốn năm sáu bảy tám\n"
    assert "*" not in "".join(out)


def test_short_answer_still_spoken():
    assert _collect(general.short_first_sentence(_chunks("Dạ"))) == ["Dạ\n"]


def test_speculation_replays_everything():
    async def run():
        spec = Speculation(("chat", "x"), _chunks("a", "b", "c"))
        await asyncio.sleep(0.01)
        return [x async for x in spec.replay()]
    assert asyncio.run(run()) == ["a", "b", "c"]


# ── làn B: căn khung ─────────────────────────────────────────────────────

def test_assess_rules():
    W, H = 640, 480
    s = 1600 / W
    assert text_align.assess([], W, H, s) == "look_around"
    assert text_align.assess([(0, 200, 300, 230)], W, H, s) == "look_left"
    assert text_align.assess([(300, 200, W, 230)], W, H, s) == "look_right"
    assert text_align.assess([(200, 0, 400, 30)], W, H, s) == "look_up"
    assert text_align.assess([(200, 450, 400, H)], W, H, s) == "look_down"
    assert text_align.assess([(0, 0, W, H)], W, H, s) == "move_away"
    assert text_align.assess([(200, 200, 400, 205)], W, H, s) == "move_closer"  # 5px*2.5 < 28
    assert text_align.assess([(100, 100, 500, 115), (100, 130, 500, 145)], W, H, s) is None


def test_aligner_speaks_only_after_two_frames_and_spaces_cues():
    clock = _Clock()
    aligner = text_align.Aligner(clock)
    assert aligner._decide("look_left") is None
    action = aligner._decide("look_left")
    assert action.kind == "cue" and action.cue == "look_left"
    clock.t += 0.5
    assert aligner._decide("look_left") is None  # < 1,5 s
    clock.t += 1.1
    assert aligner._decide("look_left").cue == "look_left"


def test_aligner_captures_after_three_good_frames():
    aligner = text_align.Aligner(_Clock())
    assert aligner._decide(None) is None
    assert aligner._decide(None) is None
    assert aligner._decide(None).kind == "capture"


def test_morph_detector_finds_text_lines():
    import cv2

    img = np.full((480, 640), 255, np.uint8)
    for i, y in enumerate(range(150, 330, 40)):
        cv2.putText(img, "Hello reading line %d" % i, (100, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    boxes = text_align.MorphDetector().detect(img)
    assert len(boxes) >= 3
    assert text_align.assess(boxes, 640, 480, 1600 / 640) is None


# ── làn C: mức + chống làm phiền ─────────────────────────────────────────

def _det(group="vehicle", box=(0.4, 0.3, 0.7, 0.9), kind="motorbike"):
    return hazard.Detection(kind, group, 0.9, box)


def test_level_rules():
    assert hazard.level_of(_det(box=(0.35, 0.2, 0.75, 0.9)), False) == 3  # xe to giữa đường
    assert hazard.level_of(_det(box=(0.45, 0.4, 0.6, 0.7)), False) == 2   # xe vừa, giữa
    assert hazard.level_of(_det("static", (0.0, 0.3, 0.15, 0.6), "bench"), False) == 1
    assert hazard.level_of(_det("static", (0.0, 0.0, 0.05, 0.05), "bench"), False) == 0


def test_tracker_marks_approaching():
    tracker = hazard.HazardTracker()
    tracker.assess([_det(box=(0.45, 0.45, 0.6, 0.65))])
    out = tracker.assess([_det(box=(0.4, 0.4, 0.68, 0.72))])  # lớn dần ~0,09
    assert out.level == 3 and out.dir == "center"


def test_anti_annoy_rules():
    clock = _Clock()
    anti = hazard.AntiAnnoy(clock)
    assert anti.step(2) is False  # cần 2 khung
    assert anti.step(2) is True
    clock.t += 0.5
    assert anti.step(2) is False  # chưa tới nhịp nhắc 2 s
    clock.t += 2.0
    assert anti.step(2) is True   # nhắc lại
    assert anti.step(3) is True   # level 3 gửi ngay
    assert anti.step(0) is False
    assert anti.step(0) is False


def test_level_one_rate_limited():
    clock = _Clock()
    anti = hazard.AntiAnnoy(clock)
    anti.step(1)
    assert anti.step(1) is True
    for lvl in (0, 0, 1, 1):
        clock.t += 1
        assert anti.step(lvl) is False  # < 5 s
    clock.t += 5
    anti.step(0); anti.step(0)
    anti.step(1)
    assert anti.step(1) is True


# ── phiên live ───────────────────────────────────────────────────────────

def test_session_token_single_use_and_ttl(monkeypatch):
    mgr = SessionManager()
    s = mgr.create("d", "nav")
    assert mgr.claim(s.token) is s
    assert mgr.claim(s.token) is None
    s2 = mgr.create("d", "ocr")
    monkeypatch.setattr(config, "LIVE_TOKEN_TTL_S", -1.0)
    assert mgr.claim(s2.token) is None


def test_new_session_closes_old_one():
    mgr = SessionManager()
    a = mgr.claim(mgr.create("d", "nav").token)
    b = mgr.claim(mgr.create("d", "ocr").token)
    assert a.closed.is_set() and not b.closed.is_set()
    assert mgr.close_device("d", "nav") is False
    assert mgr.close_device("d") is True and b.closed.is_set()


# ── làn D: tham số ───────────────────────────────────────────────────────

def test_rule_params_need_no_llm():
    assert asyncio.run(phone.extract("ride_confirm", "huỷ chuyến đi")) == {"confirm": False}
    assert asyncio.run(phone.extract("ride_confirm", "xác nhận đặt xe")) == {"confirm": True}
    assert asyncio.run(phone.extract("music_volume", "chỉnh âm lượng 70")) == {"volume": 70}
    assert asyncio.run(phone.extract("music_volume", "tăng âm lượng")) == {"direction": "up"}


def test_fallback_slot_strips_politeness():
    assert phone.fallback_slot("contact_name", "gọi cho mẹ giúp tôi nhé") == "mẹ"
    assert phone.fallback_slot("destination", "dẫn tôi tới chợ Bến Thành") == "chợ Bến Thành"


def test_extract_falls_back_to_rules_when_llm_fails(monkeypatch):
    from models import llm

    async def boom(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "generate_json", boom)
    assert asyncio.run(phone.extract("contact_call", "gọi cho anh Nam")) == {"contact_name": "anh Nam"}


def test_ocr_speech_starts_with_a_short_first_sentence(monkeypatch):
    """Câu đầu của trang sách dài: phải bị cắt ở <= 8 từ để TTS đọc ngay."""
    from lanes import ocr_live

    async def fake_read(jpeg, mode, device):
        yield "Chương một. Hành trình bắt đầu từ một buổi sáng "
        yield "rất đẹp trời ở ngôi làng nhỏ ven sông, nơi mọi người đều dậy sớm."

    monkeypatch.setattr(ocr_live, "read_image", fake_read)
    out = _collect(ocr_live.spoken(b"", "read", "d"))
    assert out[0] == "Chương một.\n"
    assert "".join(out[1:]).startswith("Hành trình bắt đầu")


def test_cancel_before_fire():
    from pipeline import pending_action as pa
    ran = []
    act = pa.schedule("dev-c", 0.15, lambda: ran.append(1), "gọi điện")
    assert pa.cancel("dev-c", "lượt mới") is True
    time.sleep(0.25)
    assert not ran and act.cancelled.is_set() and not act.fired.is_set()
    assert pa.cancel("dev-c", "lần hai") is False


def test_new_schedule_replaces_old():
    from pipeline import pending_action as pa
    ran = []
    a = pa.schedule("dev-r", 0.1, lambda: ran.append("a"), "a")
    b = pa.schedule("dev-r", 0.1, lambda: ran.append("b"), "b")
    assert b.fired.wait(0.3)
    assert a.cancelled.is_set() and ran == ["b"]
    assert pa.cancel("dev-r", "sau khi chạy") is False


def test_devices_independent():
    from pipeline import pending_action as pa
    ran = []
    a = pa.schedule("dev-1", 0.1, lambda: ran.append(1), "a")
    b = pa.schedule("dev-2", 0.1, lambda: ran.append(2), "b")
    assert pa.cancel("dev-1", "ngắt kết nối") is True
    assert b.fired.wait(0.3)
    time.sleep(0.1)
    assert ran == [2] and not a.fired.is_set()


def test_serpapi_answer_box_first():
    from models.search import client

    rows = client.parse({
        "answer_box": {"type": "weather_result", "location": "Hà Nội", "temperature": "30", "unit": "C",
                       "weather": "Nắng"},
        "organic_results": [{"title": "A", "snippet": "a"}, {"title": "B", "snippet": "b"}],
    })
    assert rows[0]["title"] == "Thời tiết" and "30" in rows[0]["snippet"] and len(rows) == 3


def _web_turn(monkeypatch, *, available, found):
    from models import llm, search
    from pipeline import final_router

    seen = {}

    async def fake_search(query, num=5):
        return found

    async def fake_stream(messages):
        seen["messages"] = messages
        yield "Xin chào bạn."

    monkeypatch.setattr(search, "available", lambda: available)
    monkeypatch.setattr(search, "search", fake_search)
    monkeypatch.setattr(llm, "stream_chat", fake_stream)

    async def run():
        d = intent_early.Decision("chat", "read", needs_web=True)
        return [p async for p in final_router._web_answer(d, "thời tiết hôm nay")]

    return asyncio.run(run()), seen["messages"]


def test_search_ok_answer_uses_results(monkeypatch):
    pieces, msgs = _web_turn(monkeypatch, available=True, found=[{"title": "Hà Nội", "snippet": "30 độ"}])
    assert pieces[0].startswith("Để tôi tra cứu") and "30 độ" in msgs[-1]["content"]
    assert "KHÔNG tra cứu được" not in msgs[0]["content"]


@pytest.mark.parametrize("available,found", [(False, None), (True, None)])
def test_search_unavailable_or_failed_injects_warning(monkeypatch, available, found):
    pieces, msgs = _web_turn(monkeypatch, available=available, found=found)
    assert "KHÔNG tra cứu được" in msgs[0]["content"] and pieces[-1]
