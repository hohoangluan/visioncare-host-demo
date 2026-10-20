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

    async def gemma_ok(prompt, schema, max_tokens=120, logprobs=False):
        assert prompt.rstrip().endswith('"tắt đi"\nTrả JSON.')  # câu lệnh đứng cuối (prefix cache)
        return {"intent": "music_stop", "ocr_mode": "read", "needs_web": False}

    async def gemma_down(prompt, schema, max_tokens=120, logprobs=False):
        raise llm.LLMError("down")

    async def clef_ok(text, device=None):
        return clef.ClefResult("nav_stop", 0.9)

    monkeypatch.setattr(intent_classifier.clef, "classify", clef_ok)
    monkeypatch.setattr(config, "INTENT_FORMAT", "json")
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


def _lp_choice(content_tokens):
    """Response giả của vLLM: token ghép lại thành content, kèm logprob từng token."""
    return {
        "message": {"content": "".join(t for t, _ in content_tokens)},
        "logprobs": {"content": [{"token": t, "logprob": lp} for t, lp in content_tokens]},
    }


def test_label_prob_from_logprobs(monkeypatch):
    """Xác suất nhãn = tích các token phủ giá trị `intent` (music + _play), bỏ token khác."""
    import math
    from models import llm

    choice = _lp_choice([('{"', -0.5), ("intent", -0.1), ('":"', -0.0),
                         ("music", -0.2), ("_play", -0.3), ('"', -0.7), (',"ocr_mode":"read"}', -0.9)])

    async def fake_raw(messages, max_tokens=None, **extra):
        assert extra["logprobs"] is True
        return choice

    monkeypatch.setattr(llm.client, "complete_raw", fake_raw)
    out = asyncio.run(llm.generate_json("p", {}, logprobs=True))
    assert out["_label_prob"] == pytest.approx(math.exp(-0.5))
    assert out["intent"] == "music_play"


def test_missing_logprobs_keeps_routing_confidence_but_marks_it_unknown(monkeypatch):
    from models import llm
    from pipeline import intent_classifier

    async def fake_raw(messages, max_tokens=None, **extra):
        return {"message": {"content": '{"intent":"music_stop","ocr_mode":"read","needs_web":false}'},
                "logprobs": None}

    monkeypatch.setattr(llm.client, "complete_raw", fake_raw)
    monkeypatch.setattr(config, "INTENT_FORMAT", "json")
    monkeypatch.setattr(intent_classifier, "_warned_no_logprobs", False)
    res = asyncio.run(intent_classifier._gemma("tắt đi", None))
    # Định tuyến làn vẫn chạy (1.0) nhưng độ tin cậy KHÔNG được coi là đã biết: cổng làn D sẽ hỏi lại.
    assert res.confidence == 1.0 and res.source == "gemma" and res.confidence_known is False
    assert intent_classifier._warned_no_logprobs is True


def test_clef_result_source():
    assert clef.ClefResult("chat", 0.9).source == "clef"


def test_ocr_mode_raw_prompt():
    from lanes import ocr_live
    from models.ocr import prompts

    assert ocr_live._prompt("raw") == prompts._RAW
    assert ocr_live._prompt("specialized") == prompts._SPECIALIZED
    assert ocr_live._prompt("read") == prompts._NORMAL


def test_keyword_raw_mode():
    assert keyword_rule("đọc nguyên văn tờ giấy này") == ("ocr", "raw")
    assert keyword_rule("đọc từng chữ giúp tôi") == ("ocr", "raw")
    assert keyword_rule("đọc toa thuốc này") == ("ocr", "specialized")
    assert keyword_rule("đọc giúp tôi") == ("ocr", "read")


def test_timeout_prefers_uxga_fallback():
    from lanes import ocr_live

    assert ocr_live.pick_image(None, b"uxga", b"vga") == b"uxga"
    assert ocr_live.pick_image(b"new", b"uxga", b"vga") == b"new"
    assert ocr_live.pick_image(None, None, b"vga") == b"vga"

def test_choice_format_confidence_and_aux_calls(monkeypatch):
    """Task 4c: intent là một nhãn; confidence = xác suất nhãn; chỉ chat/ocr mới hỏi thêm một lượt."""
    import math
    from models import llm
    from pipeline import intent_classifier

    monkeypatch.setattr(config, "INTENT_FORMAT", "choice")
    monkeypatch.setattr(config, "INTENT_AUX", "gemma")
    asked = []

    def choice(content, lps):
        return {"message": {"content": content},
                "logprobs": {"content": [{"token": t, "logprob": lp} for t, lp in lps]}}

    async def fake_raw(messages, max_tokens=None, **extra):
        asked.append(extra["structured_outputs"]["choice"])
        prompt = messages[0]["content"]
        if "Trả nhãn." in prompt:
            return choice("music_play", [("music", -0.2), ("_", 0.0), ("play", -0.3)])
        raise AssertionError("music_play không được hỏi thêm")

    monkeypatch.setattr(llm.client, "complete_raw", fake_raw)
    res = asyncio.run(intent_classifier._gemma("phát nhạc", None))
    assert res.intent == "music_play" and res.confidence == pytest.approx(math.exp(-0.5))
    assert len(asked) == 1

    async def ocr_raw(messages, max_tokens=None, **extra):
        if "Trả nhãn." in messages[0]["content"]:
            return choice("ocr", [("ocr", -0.1)])
        return choice("raw", [("raw", -0.1)])

    monkeypatch.setattr(llm.client, "complete_raw", ocr_raw)
    res = asyncio.run(intent_classifier._gemma("đọc từng chữ", None))
    assert (res.intent, res.ocr_mode, res.needs_web) == ("ocr", "raw", False)


@pytest.mark.parametrize("text,expected", [
    ("Hôm nay thời tiết thế nào", True),
    ("Giá vàng bây giờ bao nhiêu", True),
    ("Quán ăn bình dân quanh đây ở đâu", True),
    ("Bưu điện gần nhất nằm ở đâu", True),
    ("Trạm xe buýt phía trước ở đâu", False),
    ("Vịnh hạ long thuộc tỉnh nào vậy kính", False),
    ("Kể nghe chuyện ma", False),
])
def test_needs_web_rule(text, expected):
    from pipeline.intent_early import needs_web_rule
    assert needs_web_rule(text) is expected


def test_aux_rules_skip_second_call(monkeypatch):
    """Task 4d: INTENT_AUX=rules -> chỉ MỘT lượt Gemma, ocr_mode/needs_web từ luật từ khoá."""
    from models import llm
    from pipeline import intent_classifier

    monkeypatch.setattr(config, "INTENT_FORMAT", "choice")
    monkeypatch.setattr(config, "INTENT_AUX", "rules")
    calls = []

    def make(label):
        async def fake_raw(messages, max_tokens=None, **extra):
            calls.append(label)
            return {"message": {"content": label},
                    "logprobs": {"content": [{"token": label, "logprob": -0.01}]}}
        return fake_raw

    monkeypatch.setattr(llm.client, "complete_raw", make("chat"))
    res = asyncio.run(intent_classifier._gemma("thời tiết hôm nay", None))
    assert (res.intent, res.needs_web) == ("chat", True)
    monkeypatch.setattr(llm.client, "complete_raw", make("ocr"))
    res = asyncio.run(intent_classifier._gemma("đọc nguyên văn tờ này", None))
    assert (res.intent, res.ocr_mode) == ("ocr", "raw")
    assert calls == ["chat", "ocr"]


def test_choice_rejects_label_outside_set(monkeypatch):
    from models import llm

    async def fake_raw(messages, max_tokens=None, **extra):
        return {"message": {"content": "Hello!"}, "logprobs": None}

    monkeypatch.setattr(llm.client, "complete_raw", fake_raw)
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.generate_choice("p", ["a", "b"]))

# ── VAD (Task 2b) ────────────────────────────────────────────────────────

class _EnergyDetector:
    """Thay Silero: khung nào to hơn ngưỡng năng lượng thì là tiếng."""

    def __init__(self):
        self._on = False

    def accept_waveform(self, w):
        self._on = float(np.sqrt(np.mean(w * w))) > 0.05

    def is_speech_detected(self):
        return self._on

    def empty(self):
        return True

    def pop(self):
        pass


from pipeline import vad as _vad_mod
_RealSegmenter = _vad_mod.Segmenter


def _vad_segmenter():
    return _RealSegmenter(_EnergyDetector(), end_silence_s=0.35, pad_s=0.2)


def _adpcm_parts(*parts):
    """parts: (giây, biên độ) nối nhau; biên độ 0 = im lặng."""
    out = []
    for sec, amp in parts:
        t = np.arange(int(16000 * sec)) / 16000
        out.append((np.sin(2 * np.pi * 300 * t) * amp).astype("<i2"))
    return adpcm.encode_blocks(np.concatenate(out).tobytes())


def test_vad_trims_silence(fake_asr):
    tr = StreamingTranscriber(vad=_vad_segmenter())
    tr.feed(_adpcm_parts((1.0, 0), (0.5, 12000), (1.0, 0)))
    assert tr.final() == "Đọc giúp tôi"
    # 0,5 s tiếng + 0,2 s đệm mỗi đầu (đo từ khung đầu có tiếng), không phải 2,5 s
    assert 0.8 * 16000 <= fake_asr.seen[0] <= 1.0 * 16000
    quiet = StreamingTranscriber(vad=_vad_segmenter())
    quiet.feed(_adpcm_parts((1.0, 0)))
    assert quiet.final() == "" and not quiet.has_speech
    assert len(fake_asr.seen) == 1  # lượt im lặng không gọi ASR


def _run_turn(monkeypatch, fake_asr, parts, hold_s):
    """Chạy turn.run với VAD giả; trả (kết quả, số lần phân loại, text đưa vào route)."""
    from pipeline import final_router, turn, vad
    from pipeline.reply import Reply

    calls, routed = [], []

    async def fake_clef(text, state=None):
        calls.append(text)
        return clef.ClefResult("chat", 0.9)

    async def fake_route(ctx, decision, text):
        routed.append((decision.source, text))
        return Reply(cues=["no_speech"] if decision.source == "no_speech" else [])

    monkeypatch.setattr(turn.vad, "available", lambda: True)
    monkeypatch.setattr(vad, "Segmenter", _vad_segmenter)
    monkeypatch.setattr(turn.config, "STT_PARTIAL_INTERVAL_S", 0.05)
    monkeypatch.setattr(intent_early.classifier, "available", lambda: True)
    monkeypatch.setattr(intent_early.classifier, "classify", fake_clef)
    monkeypatch.setattr(final_router, "route", fake_route)
    audio = _adpcm_parts(*parts)

    async def body():
        for i in range(0, len(audio), 2048):
            yield audio[i:i + 2048]
        await asyncio.sleep(hold_s)  # nút còn giữ sau khi nói xong

    result = asyncio.run(turn.run("d", "1", "audio/x-adpcm-ima; rate=16000; block=256", body(), {}))
    return result, calls, routed


def test_early_final_reused_on_release(monkeypatch, fake_asr):
    result, calls, routed = _run_turn(monkeypatch, fake_asr, [(0.3, 0), (0.5, 12000), (0.6, 0)], hold_s=0.8)
    # VAD thấy hết câu khi nút còn giữ -> chốt sớm đúng một lần, nhả nút dùng lại
    assert result.timings["final_stt_s"] < 0.01 and result.timings["intent_s"] < 0.01
    assert fake_asr.decodes == 1  # giải đúng một lần (chốt sớm), nhả nút không giải lại
    assert routed == [("model", "Đọc giúp tôi")]


def test_no_speech_skips_classifier(monkeypatch, fake_asr):
    result, calls, routed = _run_turn(monkeypatch, fake_asr, [(1.0, 0)], hold_s=0.1)
    assert fake_asr.decodes == 0 and calls == []  # không giải, không gọi Gemma/Clef
    assert routed == [("no_speech", "")] and result.reply.cues == ["no_speech"]


# ── Task 14: quan sát ─────────────────────────────────────────────────────

def test_record_turn_appends_jsonl(tmp_path, monkeypatch):
    import json
    import logging

    from pipeline import device_ctx, metrics

    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    metrics.record_turn({"device": "d1", "turn": "t1", "transport": "ws", "intent": "chat", "glasses": None})
    metrics.record_turn({"turn": "t1", "glasses": {"first_byte_ms": 400, "first_audio_ms": 450}})
    metrics.flush()
    rows = [json.loads(line) for line in (tmp_path / "metrics" / "turns.jsonl").read_text().splitlines()]
    assert [r["turn"] for r in rows] == ["t1", "t1"] and rows[0]["ts"] > 0
    assert rows[0]["intent"] == "chat" and rows[1]["glasses"]["first_audio_ms"] == 450

    # Log filter: mỗi dòng log của lượt mang device + turn id.
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", (), None)
    with device_ctx.use("kinh-A"):
        token = device_ctx.turn.set("t9")
        try:
            metrics.TurnLogFilter().filter(record)
        finally:
            device_ctx.turn.reset(token)
    assert (record.device, record.turn) == ("kinh-A", "t9")


def test_played_frame_recorded(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from app import app
    from pipeline import metrics
    from tests.conftest import TEST_DEVICE_TOKEN

    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    with TestClient(app).websocket_connect("/v2/session") as ws:
        ws.send_text(json.dumps({"t": "hello", "device": "ws-played", "token": TEST_DEVICE_TOKEN,
                                 "cue_version": cues.CUE_VERSION}))
        assert json.loads(ws.receive_text())["t"] == "hello_ok"
        ws.send_text(json.dumps({"t": "played", "turn": "t7", "first_byte_ms": 412, "first_audio_ms": 455}))
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}  # played đã xử lý xong trước ping
    metrics.flush()
    rows = [json.loads(line) for line in (tmp_path / "metrics" / "turns.jsonl").read_text().splitlines()]
    assert rows[-1]["turn"] == "t7" and rows[-1]["device"] == "ws-played"
    assert rows[-1]["glasses"] == {"first_byte_ms": 412, "first_audio_ms": 455}


def test_cue_manifest_complete():
    import json
    import os

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "cues")
    manifest = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
    assert manifest["cue_version"] == cues.CUE_VERSION  # đổi chữ cue mà quên sinh lại clip thì đỏ ở đây
    assert set(manifest["clips"]) == set(cues.CUES)
    for cue_id, info in manifest["clips"].items():
        data = open(os.path.join(root, info["file"]), "rb").read()
        assert len(data) == info["bytes"] and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
        assert int.from_bytes(data[20:22], "little") == adpcm.FORMAT_TAG
        assert int.from_bytes(data[24:28], "little") == adpcm.SAMPLE_RATE
        assert (len(data) - adpcm.WAV_HEADER_BYTES) % adpcm.BLOCK_ALIGN == 0, cue_id

class _FakeNavWS:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def receive(self):
        return await self.inbox.get()

    async def send_text(self, text):
        self.sent.append(("t", text))

    async def send_bytes(self, data):
        self.sent.append(("b", data))


def _fake_speech(monkeypatch, chunks=40):
    from pipeline import speech

    async def fake_adpcm(text):
        for _ in range(chunks):
            await asyncio.sleep(0.01)
            yield b"x" * 8

    monkeypatch.setattr(speech, "adpcm_stream", fake_adpcm)


def test_hazard_preempts_outbox_audio(monkeypatch):
    """Hazard mức >= 2 ngắt audio outbox đang gửi, chặn gửi tiếp, rồi đọc lại cả câu khi yên."""
    from lanes import nav_live
    from live.session import LiveSession

    monkeypatch.setattr(nav_live, "HAZARD_QUIET_S", 0.4)
    _fake_speech(monkeypatch)

    async def go():
        ws, session, clock = _FakeNavWS(), LiveSession("tok", "dev", "nav"), nav_live._HazardClock()
        session.outbox.put("Đã mở lộ trình tới chợ Bến Thành.")
        task = asyncio.create_task(nav_live._speak_outbox(ws, session, clock))
        while len(ws.sent) < 5:
            await asyncio.sleep(0.005)
        clock.mark()
        n = len(ws.sent)
        await asyncio.sleep(0.25)  # còn trong 0,4 s im lặng: không được gửi thêm
        during = len(ws.sent) - n
        await asyncio.sleep(1.0)  # yên rồi: đọc lại từ đầu
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return during, len(ws.sent)

    during, total = asyncio.run(go())
    assert during <= 1  # tối đa khối đang bay lúc hazard tới
    assert total >= 5 + 40  # phần đã gửi + cả câu đọc lại


def test_nav_run_hazard_goes_first_and_silences_outbox(monkeypatch):
    from lanes import nav_live
    from live.session import LiveSession

    class FakeYolo:
        def detect(self, bgr):
            return [hazard.Detection("motorbike", "vehicle", 0.9, (0.35, 0.2, 0.75, 0.95))]

    monkeypatch.setattr(hazard, "detector", lambda: FakeYolo())
    _fake_speech(monkeypatch)

    async def go():
        ws, session = _FakeNavWS(), LiveSession("tok", "dev", "nav")
        task = asyncio.create_task(nav_live.run(ws, session))
        await ws.inbox.put({"type": "websocket.receive", "bytes": bytes([1]) + _jpeg(320, 240)})
        for _ in range(300):
            if any(k == "t" and '"hazard"' in v for k, v in ws.sent):
                break
            await asyncio.sleep(0.01)
        session.outbox.put("Đã mở lộ trình.")  # tới SAU hazard, trong 1,5 s im lặng
        await asyncio.sleep(0.4)
        session.closed.set()
        await ws.inbox.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.gather(task, return_exceptions=True)
        return ws.sent

    sent = asyncio.run(go())
    assert any(k == "t" and '"hazard"' in v and '"level": 3' in v for k, v in sent)
    assert not any(k == "b" for k, _ in sent)


def test_live_old_cue_version_speaks_cue(monkeypatch):
    from live import protocol
    from live.ws_adapter import LiveSocket
    from pipeline import speech

    spoken = []

    async def fake_adpcm(text):
        spoken.extend(text)
        yield b"aa"

    monkeypatch.setattr(speech, "adpcm_stream", fake_adpcm)
    cue_id = next(c for c in cues.CUES if cues.fallback_text(c))

    async def run(speak_cues):
        sent = []

        async def st(s):
            sent.append(("t", s))

        async def sb(b):
            sent.append(("b", b))

        await LiveSocket(st, sb, speak_cues=speak_cues).send_text(protocol.cue(cue_id))
        return sent

    assert asyncio.run(run(False)) == [("t", protocol.cue(cue_id))]  # kính mới: gửi mã cue
    old = asyncio.run(run(True))  # kính cũ: nói câu
    assert old == [("b", protocol.audio(b"aa"))] and spoken == [cues.fallback_text(cue_id)]


# ── Đợt sửa cuối plan 1 ───────────────────────────────────────────────────────

def test_pending_action_counts_down_only_after_arm():
    """Lệnh làn D chưa armed thì không bao giờ chạy; arm() mới bắt đầu đếm; huỷ trước arm thì mãi không chạy."""
    from pipeline import pending_action

    fired = []
    action = pending_action.schedule("arm-dev", None, lambda: fired.append("a"), "t")
    time.sleep(0.3)
    assert fired == []  # chưa armed: đứng yên
    assert action.arm(0.15) is True and action.arm(0.0) is False  # armed một lần
    time.sleep(0.05)
    assert fired == []  # đang đếm ngược
    time.sleep(0.4)
    assert fired == ["a"]

    cancelled = pending_action.schedule("arm-dev2", None, lambda: fired.append("b"), "t")
    assert pending_action.cancel("arm-dev2", "kiểm") is True
    assert cancelled.arm(0.0) is False
    time.sleep(0.2)
    assert fired == ["a"]


def test_process_arm_waits_for_first_byte_and_adds_opening_line():
    from app import _ProcessArm

    got = []
    a = _ProcessArm()
    a.set(got.append)
    assert got == []  # lượt xong nhưng chưa byte nào rời server
    a.first_chunk()
    assert len(got) == 1 and got[0] >= config.AUDIO_PREROLL_SECONDS  # câu mở đầu + đệm 2 s đứng trước câu đọc lại
    a.first_chunk()
    assert len(got) == 1  # chỉ một lần
    b = _ProcessArm()
    b.first_chunk()  # byte đầu đi trước khi lượt xong (đệm nhỏ)
    got2 = []
    b.set(got2.append)
    assert len(got2) == 1


def test_stream_until_disconnect_arms_on_first_chunk_and_cancels_on_drop():
    from app import _stream_until_disconnect
    from pipeline import pending_action
    from pipeline.reply import Reply

    async def go():
        armed = []
        action = pending_action.schedule("sud-dev", None, lambda: armed.append("fired"), "t")
        body = iter([b"1", b"2", b"3"])
        gen = _stream_until_disconnect(body, Reply(), "sud-dev", lambda: armed.append("arm"))
        assert await gen.__anext__() == b"1"
        assert armed == []  # callback chạy sau khi chunk đầu đã được giao đi
        assert await gen.__anext__() == b"2"
        assert armed == ["arm"]
        await gen.aclose()  # client ngắt giữa chừng
        assert action.cancelled.is_set()  # lệnh chờ bị huỷ (/process cũng đi đường này)

    asyncio.run(go())


def test_stt_stream_clamps_declared_rate_and_channels():
    """Rate/kênh do client khai không được phồng trần audio (rate=1e9 -> ~60 GB)."""
    import struct

    tr = StreamingTranscriber("audio/x-adpcm-ima; rate=1000000000; channels=1; block=0")
    assert tr._rate == adpcm.SAMPLE_RATE and tr._block_align == adpcm.BLOCK_ALIGN
    tr = StreamingTranscriber("audio/x-adpcm-ima; rate=abc")
    assert tr._rate == adpcm.SAMPLE_RATE

    fmt = struct.pack("<HHIIHH", 0x0001, 2000, 2_000_000_000, 4, 2, 16)
    wav = b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt)) + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data"
    tr = StreamingTranscriber("audio/wav")
    tr.feed(wav)
    assert tr._rate == adpcm.SAMPLE_RATE and tr._channels == 1
    cap = config.DEVICE_MAX_AUDIO_S * adpcm.SAMPLE_RATE * 2 + 65536
    tr.feed(b"\x00" * int(cap + 10))
    tr.feed(b"\x00" * 10)
    assert tr.capped  # trần byte theo rate đã kẹp, không phải 2e9


def test_httpx_logs_do_not_carry_the_search_key(monkeypatch, caplog):
    import logging

    import app  # noqa: F401  (cấu hình logging khi nạp)

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_stt_misheard_alert_and_message_rules():
    """Minor 1-2: STT nghe "bật cảnh báo vật cản" thành "cảnh báo bất cản" và "Nhắn cho" thành "Nhanh cho"."""
    for text in ("cảnh báo bất cản", "Cảnh báo bất cản", "bật cảnh báo bất cản", "mở cảnh báo vất cản", "cảnh báo vật cản"):
        assert keyword_rule(text.lower())[0] == "alert_on", text
    assert keyword_rule("tắt cảnh báo bất cản")[0] == "alert_off"
    assert keyword_rule("có vật cản không")[0] == "hazard"  # hỏi vẫn là hazard
    assert keyword_rule("nhanh cho mẹ là con về muộn")[0] == "message_send"
    assert (keyword_rule("gọi nhanh cho bố") or ("",))[0] != "message_send"  # "nhanh cho" không ở đầu câu: giao Gemma
    from lanes import phone as lane
    assert lane.fallback_message("Nhanh cho mẹ là con về muộn") == {"contact_name": "mẹ", "text": "con về muộn"}
