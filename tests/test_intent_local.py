"""Bộ phân loại cục bộ đứng trước Gemini: khi nào nó tự quyết, khi nào nhường."""
import numpy as np
import pytest

import config
from handlers import action_flow
from pipeline import intent as intent_mod
from pipeline import intent_local
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean():
    action_flow.reset_state()
    yield
    action_flow.reset_state()
    # `_load` có thể đang là bản giả do monkeypatch (chưa gỡ ở thời điểm này),
    # nên đừng giả định nó còn là hàm bọc lru_cache.
    clear = getattr(intent_local._load, "cache_clear", None)
    if clear:
        clear()


def _fake_local(label, confidence=0.99, margin=0.9):
    return intent_local.LocalPrediction(label, confidence, margin)


# ── Ngưỡng ────────────────────────────────────────────────────────────────


def _stub_probs(monkeypatch, probs, classes):
    """Giả lập toàn bộ phần nạp model, chỉ giữ lại phần tính ngưỡng."""
    coef = np.log(np.array(probs, dtype=np.float32) + 1e-9)[None, :].repeat(4, 0).T
    monkeypatch.setattr(intent_local, "_load", lambda: {
        "session": None, "inputs": set(), "tokenizer": None,
        "coef": coef, "intercept": np.zeros(len(classes), dtype=np.float32),
        "classes": np.array(classes),
    })


def test_classify_returns_none_when_no_model(monkeypatch):
    """Máy chưa dựng model thì đi đường Gemini, không chết lúc khởi động."""
    monkeypatch.setattr(config, "INTENT_LOCAL_ENABLED", True)
    monkeypatch.setattr(intent_local, "_load", lambda: None)
    assert intent_local.classify("đọc chữ này") is None


def test_classify_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "INTENT_LOCAL_ENABLED", False)
    assert intent_local.classify("đọc chữ này") is None


def test_classify_returns_none_on_empty_text(monkeypatch):
    monkeypatch.setattr(intent_local, "_load", lambda: object())
    assert intent_local.classify("   ") is None


# ── Đường đi trong detect_with_params ────────────────────────────────────


def test_param_free_label_skips_gemini(monkeypatch):
    """5 nhãn ảnh không cần tham số -> xong tại chỗ, không gọi Gemini."""
    called = []
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.OCR))
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: called.append(1) or {"intent": "chat"})

    name, params = intent_mod.detect_with_params("đọc chữ này")
    assert name == Intent.OCR
    assert params == {}
    assert called == []


def test_label_needing_params_still_calls_gemini(monkeypatch):
    """SetFit chỉ sinh nhãn, không trích slot — `song` vẫn phải hỏi Gemini."""
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.MUSIC_PLAY))
    monkeypatch.setattr(
        intent_mod.vlm, "generate_json",
        lambda *a, **k: {"intent": Intent.MUSIC_PLAY, "params": {"song": "nơi này có anh"}},
    )
    name, params = intent_mod.detect_with_params("mở bài nơi này có anh")
    assert name == Intent.MUSIC_PLAY
    assert params["song"] == "nơi này có anh"


def test_low_confidence_falls_through_to_gemini(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", lambda t: None)
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: {"intent": Intent.HAZARD, "params": {}})
    assert intent_mod.detect_with_params("phía trước sao rồi")[0] == Intent.HAZARD


# ── Trạng thái gỡ mơ hồ cho nhãn cục bộ ──────────────────────────────────


def test_local_stop_label_resolved_by_music_state(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.NAV_STOP))
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: pytest.fail("không được gọi Gemini"))
    action_flow.note_result("music_play", {"request_state": "succeeded"})

    assert intent_mod.detect_with_params("tắt đi")[0] == Intent.MUSIC_STOP


def test_local_stop_label_resolved_by_nav_state(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.MUSIC_STOP))
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: pytest.fail("không được gọi Gemini"))
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "n-1"}},
    )
    assert intent_mod.detect_with_params("dừng lại")[0] == Intent.NAV_STOP


def test_both_running_picks_most_recent(monkeypatch):
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.MUSIC_STOP))
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: pytest.fail("không được gọi Gemini"))
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "n-1"}},
    )
    assert intent_mod.detect_with_params("tắt đi")[0] == Intent.NAV_STOP


def test_nothing_running_defers_stop_label_to_gemini(monkeypatch):
    """Không có gì đang chạy thì nhãn cục bộ không đủ căn cứ — để Gemini đọc lại
    nguyên câu, vì "tắt nhạc" (rõ) và "tắt đi" (trống không) khác nhau."""
    seen = []
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.MUSIC_STOP))
    monkeypatch.setattr(
        intent_mod.vlm, "generate_json",
        lambda *a, **k: seen.append(1) or {"intent": Intent.UNKNOWN, "params": {}},
    )
    assert intent_mod.detect_with_params("tắt đi")[0] == Intent.UNKNOWN
    assert seen == [1]


def test_non_stop_label_untouched_by_state():
    assert intent_mod._apply_state(Intent.OCR, {"music_playing": True}) == Intent.OCR


# ── Câu nói rõ phải THẮNG bối cảnh ───────────────────────────────────────
# Bug đo được ở lần E2E đầu: "tắt nhạc" trong lúc đang chỉ đường ra `nav_stop`,
# vì `_apply_state` xét trạng thái trước câu chữ. Người dùng nói gì làm nấy.


@pytest.mark.parametrize("text,expected", [
    ("tắt nhạc", Intent.MUSIC_STOP),
    ("dừng nhạc đi", Intent.MUSIC_STOP),
    ("tắt bài hát này", Intent.MUSIC_STOP),
    ("dừng chỉ đường", Intent.NAV_STOP),
    ("tắt điều hướng", Intent.NAV_STOP),
    ("thôi không dẫn đường nữa", Intent.NAV_STOP),
])
def test_explicit_command_beats_device_state(text, expected):
    """Bối cảnh NGƯỢC hẳn với câu lệnh — câu lệnh vẫn phải thắng."""
    opposite = (
        {"navigating": True, "most_recent": "navigating"}
        if expected == Intent.MUSIC_STOP
        else {"music_playing": True, "most_recent": "music_playing"}
    )
    # Nhãn cục bộ cố tình cho SAI luôn, để chắc chắn kết quả đến từ mặt chữ.
    wrong = Intent.NAV_STOP if expected == Intent.MUSIC_STOP else Intent.MUSIC_STOP
    assert intent_mod._apply_state(wrong, opposite, text) == expected


@pytest.mark.parametrize("text", ["tắt đi", "dừng lại", "thôi đủ rồi"])
def test_bare_command_uses_state(text):
    """Câu không nói ra cái gì thì mới tới lượt bối cảnh."""
    music = {"music_playing": True, "most_recent": "music_playing"}
    assert intent_mod._apply_state(Intent.NAV_STOP, music, text) == Intent.MUSIC_STOP


def test_bare_command_with_nothing_running_defers():
    assert intent_mod._apply_state(Intent.MUSIC_STOP, {}, "tắt đi") is None


# ── Head tham số ─────────────────────────────────────────────────────────


def test_binary_head_uses_sigmoid_not_softmax():
    """Bài nhị phân: sklearn lưu MỘT hàng hệ số, dùng sigmoid — không phải
    softmax trên hai hàng.

    Bug đo được: softmax trên vector một phần tử luôn ra 1.0 ở chỉ số 0, nên mọi
    câu đều trả lớp đầu bảng chữ cái ("tăng âm lượng" ra `down`, "xác nhận đặt
    xe" ra `confirm=False`). Head huấn luyện đúng 96.7%; chỉ phần đọc lại lúc
    chạy sai.
    """
    coef = np.array([[2.0, 0.0]], dtype=np.float32)      # 1 hàng = nhị phân
    intercept = np.array([0.0], dtype=np.float32)

    pos = intent_local._probabilities(np.array([1.0, 0.0]), coef, intercept)
    neg = intent_local._probabilities(np.array([-1.0, 0.0]), coef, intercept)

    assert len(pos) == 2 and abs(pos.sum() - 1.0) < 1e-6
    assert pos.argmax() == 1, "vector dương phải nghiêng về lớp thứ HAI"
    assert neg.argmax() == 0, "vector âm phải nghiêng về lớp thứ NHẤT"


def test_multiclass_head_uses_softmax():
    coef = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0]], dtype=np.float32)
    intercept = np.zeros(3, dtype=np.float32)
    prob = intent_local._probabilities(np.array([1.0, 0.0]), coef, intercept)
    assert len(prob) == 3 and abs(prob.sum() - 1.0) < 1e-6
    assert prob.argmax() == 0


def test_read_params_returns_none_when_any_field_unsure(monkeypatch):
    """Nửa bộ tham số còn tệ hơn không trả: handler không phân biệt được
    "thiếu cờ" với "cờ bằng false".

    Không nhãn nào ĐANG dùng nhiều head cùng lúc — `chat` là nhãn cuối cùng như
    vậy và đã bỏ hai head của nó. Nên test này dựng một nhãn hai head giả để giữ
    cái chốt sống: ai thêm nhãn nhiều head sau này vẫn được nó bảo vệ.

    Chính vì luật "một trường không chắc là cả nhãn đi Gemini" mà `chat` từng
    chết: hai head nhận 20.0% và 3.3%, nhân lại còn ~4%, đo ra 0/18 câu chat
    xong được ở bước cục bộ.
    """
    sure = (np.array([[50.0]], dtype=np.float32), np.array([0.0], dtype=np.float32),
            np.array(["false", "true"]))
    unsure = (np.zeros((1, 1), dtype=np.float32), np.array([0.0], dtype=np.float32),
              np.array(["false", "true"]))
    monkeypatch.setattr(intent_local, "_PARAM_HEADS", {
        "hai_head": {"a": "head_chac", "b": "head_khong_chac"}
    })
    monkeypatch.setattr(intent_local, "_load", lambda: {
        "param_heads": {"head_chac": sure, "head_khong_chac": unsure}
    })
    pred = intent_local.LocalPrediction("hai_head", 0.9, 0.8, np.array([1.0], dtype=np.float32))
    assert intent_local.read_params("hai_head", pred) is None


def test_chat_finishes_locally_without_gemini(monkeypatch):
    """`chat` là nhãn phổ biến nhất; nó phải xong ở bước cục bộ.

    Trước khi bỏ hai cờ `needs_location`/`needs_web`, mọi câu chat đều rơi xuống
    Gemini để lấy đúng hai giá trị boolean — đo trên tập eval: 0/18 câu thoát
    được. Đó là ~0.9s chờ trắng trên nhãn dùng nhiều nhất.
    """
    called = []
    monkeypatch.setattr(intent_local, "classify", lambda t: _fake_local(Intent.CHAT))
    monkeypatch.setattr(intent_mod.vlm, "generate_json",
                        lambda *a, **k: called.append(1) or {"intent": "chat"})

    name, params = intent_mod.detect_with_params("xin chào")

    assert name == Intent.CHAT
    assert params == {}
    assert called == [], "chat không được gọi Gemini để phân loại nữa"


def test_read_params_none_for_span_labels(monkeypatch):
    """`contact_call`/`nav_start`/`music_play` cần trích tên riêng — không head
    phân loại nào làm được, phải để Gemini."""
    pred = intent_local.LocalPrediction(Intent.CONTACT_CALL, 0.9, 0.8,
                                        np.array([1.0], dtype=np.float32))
    for label in (Intent.CONTACT_CALL, Intent.NAV_START, Intent.MUSIC_PLAY,
                  Intent.RIDE_QUOTE, Intent.EMERGENCY_CALL):
        assert intent_local.read_params(label, pred) is None
