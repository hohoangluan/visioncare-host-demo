"""T05 — schema slot mới (A1), khối sửa lỗi STT (A2), vị trí chỉ khi có thật
(A3), pending bỏ qua SetFit (B3), nhãn thoát cancel/repeat (B5).

Xem docs/tasks/T05-intent-slots.md và docs/tasks/reports/T05.md.
"""
import time

import pytest

import config
from handlers import action_flow
from handlers import chat as chat_mod
from handlers.action_flow import Pending
from pipeline import intent as intent_mod
from pipeline import intent_local
from schemas import Intent


def _pending(
    kind="fill", slot="song_title", intent=Intent.MUSIC_PLAY,
    question="Bạn muốn nghe bài hát nào?",
) -> Pending:
    return Pending(
        slot=slot, intent=intent, known={}, question=question,
        candidates=[], asked_at=time.monotonic(), kind=kind,
    )


def _refuse_setfit(text):
    raise AssertionError("SetFit (intent_local.classify) không được gọi ở đây")


def _refuse_gemini(*args, **kwargs):
    raise AssertionError("Gemini (vlm.generate_json) không được gọi ở đây")


# ─── A1 — schema có đủ 7 slot mới, "song" còn alias ─────────────────────


def test_schema_has_new_slots():
    props = intent_mod._SCHEMA["properties"]["params"]["properties"]
    for name in (
        "song_title", "artist", "song_is_specific",
        "destination", "destination_raw", "slot_confidence", "focus",
    ):
        assert name in props, f"thiếu slot '{name}' trong _SCHEMA"
    assert props["slot_confidence"]["enum"] == ["high", "low"]
    assert props["focus"]["enum"] == ["left", "right", "front", "behind"]


def test_song_alias_still_works(monkeypatch):
    """`song` alias cũ phải còn nguyên trong schema VÀ trong luồng dữ liệu —
    `handlers/music.py` và hợp đồng host (`endpoint.md:131`) vẫn dùng chuỗi
    "Tên - Ca sĩ" này, không đọc `song_title`/`artist`."""
    assert "song" in intent_mod._SCHEMA["properties"]["params"]["properties"]

    monkeypatch.setattr(
        intent_mod.vlm, "generate_json",
        lambda *a, **k: {
            "intent": Intent.MUSIC_PLAY,
            "params": {"song": "Nơi này có anh - Sơn Tùng"},
        },
    )
    name, params = intent_mod.detect_with_params("mở bài nơi này có anh")
    assert name == Intent.MUSIC_PLAY
    assert params["song"] == "Nơi này có anh - Sơn Tùng"


# ─── A2 — khối chỉ dẫn sửa lỗi STT: kiểm CẢ BA vế bằng string-match ──────


def test_prompt_contains_stt_correction_block(monkeypatch):
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {"intent": Intent.CHAT, "params": {}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake)
    intent_mod.detect_with_params("chỉ đường tới Bát Khoa")
    prompt = captured["prompt"]

    # Vế 1 — SỬA: có ví dụ cụ thể, không chỉ nói chung chung.
    assert "Bát Khoa" in prompt and "Bách Khoa" in prompt, "thiếu ví dụ sửa lỗi nghe nhầm"
    # Vế 2 — THÚ NHẬN khi không sửa được: nhắc rõ tên field + giá trị "low".
    assert "slot_confidence" in prompt and "\"low\"" in prompt
    # Vế 3 — CẤM BỊA: cấm bịa số nhà/tên đường/tên album.
    assert "bịa" in prompt.lower()
    assert "số nhà" in prompt and "tên đường" in prompt and "album" in prompt


# ─── A3 — vị trí CHỈ chèn khi có thật (khác `chat`/C1) ──────────────────


def test_prompt_contains_location_when_available(monkeypatch):
    monkeypatch.setattr(
        chat_mod, "_LOCATION_CACHE", ("123 Lê Lợi, Quận 1, TP.HCM", time.monotonic())
    )
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {"intent": Intent.CHAT, "params": {}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake)
    intent_mod.detect_with_params("quán cà phê gần đây")
    assert "123 Lê Lợi, Quận 1, TP.HCM" in captured["prompt"]


def test_prompt_omits_location_when_empty(monkeypatch):
    """Cache rỗng -> KHÔNG chèn dòng nào cả. Khác `handlers/chat.py` (T07/C1),
    nơi vị trí rỗng vẫn PHẢI chèn khối cấm bịa vì đó là bước SINH CÂU TRẢ LỜI
    tự do. Ở đây là bước PHÂN LOẠI NHÃN — im lặng bỏ qua là đúng, chèn "chưa
    rõ vị trí" chỉ tốn token cho những nhãn không cần vị trí (ocr/money...)."""
    monkeypatch.setattr(chat_mod, "_LOCATION_CACHE", (None, 0.0))
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {"intent": Intent.CHAT, "params": {}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake)
    intent_mod.detect_with_params("quán cà phê gần đây")

    assert "Vị trí hiện tại" not in captured["prompt"]
    assert chat_mod._LOCATION_UNAVAILABLE not in captured["prompt"]


# ─── B3 — pending mở slot (`kind == "fill"`): SetFit KHÔNG được gọi ─────


def test_pending_skips_setfit(monkeypatch):
    """Ca chính: pending(song_title) mở + "Sơn Tùng" -> SetFit không được
    gọi, Gemini được gọi kèm nguyên văn câu hỏi vừa hỏi."""
    pending = _pending(
        kind="fill", slot="song_title", intent=Intent.MUSIC_PLAY,
        question="Bạn muốn nghe của ca sĩ nào?",
    )
    monkeypatch.setattr(intent_local, "classify", _refuse_setfit)

    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {"intent": Intent.MUSIC_PLAY, "params": {"song_title": "Sơn Tùng"}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake)

    name, params = intent_mod.detect_with_params("Sơn Tùng", pending=pending)

    assert name == Intent.MUSIC_PLAY
    assert params["song_title"] == "Sơn Tùng"
    assert pending.question in captured["prompt"]


def test_pending_prompt_allows_unrelated(monkeypatch):
    """Vế bắt buộc của B3: câu hoàn toàn khác (không liên quan pending) vẫn
    phải phân loại đúng nhãn của NÓ, không bị ép về slot đang chờ."""
    pending = _pending(
        kind="fill", slot="song_title", intent=Intent.MUSIC_PLAY,
        question="Bạn muốn nghe bài hát nào?",
    )
    monkeypatch.setattr(intent_local, "classify", _refuse_setfit)
    monkeypatch.setattr(
        intent_mod.vlm, "generate_json",
        lambda *a, **k: {"intent": Intent.CONTACT_CALL, "params": {"contact_name": "mẹ"}},
    )

    name, params = intent_mod.detect_with_params("gọi cho mẹ", pending=pending)

    assert name == Intent.CONTACT_CALL
    assert params["contact_name"] == "mẹ"


def test_deterministic_answer_skips_gemini(monkeypatch):
    """Ngoại lệ pha 2 (T04): pending `confirm`/`select` KHÔNG đi qua nhánh B3
    — hàm coi như không có pending, dùng lại đường SetFit-trước-Gemini bình
    thường. Ngân sách pha 2 là < 400ms (T21/G1), không kịp một lượt Gemini."""
    pending = _pending(
        kind="confirm", slot="ride_confirm", intent=Intent.RIDE_CONFIRM,
        question="Bạn có muốn xác nhận chuyến xe này không?",
    )
    monkeypatch.setattr(
        intent_local, "classify",
        lambda t: intent_local.LocalPrediction(Intent.CHAT, 0.99, 0.9),
    )
    monkeypatch.setattr(intent_mod.vlm, "generate_json", _refuse_gemini)

    name, _ = intent_mod.detect_with_params("ừ", pending=pending)
    assert name == Intent.CHAT


# ─── B5 — cancel/repeat: tất định, không SetFit, không Gemini, < 300ms ──


def test_cancel_label(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", _refuse_setfit)
    monkeypatch.setattr(intent_mod.vlm, "generate_json", _refuse_gemini)

    name, params = intent_mod.detect_with_params("thôi bỏ đi")
    assert name == "cancel"
    assert params == {}


def test_repeat_label(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", _refuse_setfit)
    monkeypatch.setattr(intent_mod.vlm, "generate_json", _refuse_gemini)

    name, params = intent_mod.detect_with_params("nói lại đi")
    assert name == "repeat"
    assert params == {}


def test_cancel_repeat_are_param_free():
    assert "cancel" in intent_mod._PARAM_FREE
    assert "repeat" in intent_mod._PARAM_FREE


def test_cancel_repeat_under_300ms(monkeypatch):
    """Đo THẬT (T21/G1: ngân sách < 300ms) — không mạng ngoài, không SetFit."""
    monkeypatch.setattr(intent_local, "classify", _refuse_setfit)
    monkeypatch.setattr(intent_mod.vlm, "generate_json", _refuse_gemini)

    for text in ("thôi bỏ đi", "huỷ đi", "nói lại đi", "gì cơ", "sao cơ"):
        started = time.perf_counter()
        intent_mod.detect_with_params(text)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.3, f"{text!r} mất {elapsed * 1000:.1f}ms, vượt ngân sách 300ms"


# ─── 4.2 — bảng ca STT sai, cần Gemini THẬT (docs/tasks/measurements/A2.md) ──
#
# `@pytest.mark.llm` không đăng ký trong pytest.ini (file đó không nằm trong
# "FILE BẠN ĐƯỢC SỬA" của T05) -> pytest chỉ cảnh báo unregistered-mark, không
# fail. Skip cứng khi thiếu key thật, đúng pattern `tests/test_bang_am_thanh.py`
# đã dùng — máy không có key vẫn `pytest -q` xanh, không fail cứng.
pytestmark_llm = pytest.mark.skipif(
    not config.GEMINI_API_KEY, reason="cần GEMINI_API_KEY thật để đo A2"
)


@pytest.mark.llm
@pytestmark_llm
def test_stt_error_destination_corrected_high_confidence():
    """"Bát Khoa" -> "Bách Khoa", sửa được -> slot_confidence=high."""
    action_flow.reset_state()
    name, params = intent_mod.detect_with_params("chỉ đường tới Bát Khoa")
    assert name == Intent.NAV_START
    assert params.get("destination") == "Bách Khoa"
    assert params.get("destination_raw") == "Bát Khoa"
    assert params.get("slot_confidence") == "high"


@pytest.mark.llm
@pytestmark_llm
def test_stt_error_song_and_artist_split():
    """Tách được artist khỏi tên bài khi câu nói cả hai."""
    action_flow.reset_state()
    name, params = intent_mod.detect_with_params(
        "mở nhạc của Sơn Tùng bài Nơi này có anh"
    )
    assert name == Intent.MUSIC_PLAY
    assert params.get("song_title") == "Nơi này có anh"
    assert "Sơn Tùng" in (params.get("artist") or "")
    # alias cũ vẫn phải có mặt song song (T05 A1: không phá đường cũ).
    assert params.get("song")


@pytest.mark.llm
@pytestmark_llm
def test_stt_error_destination_kept_unchanged_when_already_correct():
    """"Bưu điện Thành Phố" không phải lỗi nghe nhầm -> giữ nguyên nội dung
    (cho phép model tự chuẩn hoá hoa/thường, KHÔNG cho phép đổi sang địa danh
    khác)."""
    action_flow.reset_state()
    name, params = intent_mod.detect_with_params("chỉ đường tới Bưu điện Thành Phố")
    assert name == Intent.NAV_START
    assert (params.get("destination") or "").lower() == "bưu điện thành phố"


@pytest.mark.llm
@pytestmark_llm
def test_stt_error_unrecognizable_name_not_invented():
    """Tên lạ không đoán được -> GIỮ NGUYÊN đúng nguyên văn đã nghe, KHÔNG bịa
    một địa danh nghe có vẻ hợp lý; slot_confidence=low."""
    action_flow.reset_state()
    text = "chỉ đường tới Oa Kha Klon Tơ Rờ"
    name, params = intent_mod.detect_with_params(text)
    assert name == Intent.NAV_START
    assert params.get("slot_confidence") == "low"
    # CẤM BỊA: destination phải TRÙNG với đúng cái đã nghe (destination_raw),
    # không được thay bằng một tên khác nghe "hợp lý" hơn.
    assert params.get("destination") == params.get("destination_raw")
