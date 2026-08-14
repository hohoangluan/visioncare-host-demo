"""Trạng thái thiết bị (đang phát nhạc? đang chỉ đường?) và cách nó gỡ mơ hồ.

"Tắt đi", "dừng lại", "thôi đủ rồi" không tự nó cho biết tắt cái gì. Đo trên bộ
câu huấn luyện, đây là cặp lẫn nhau nhiều nhất (`nav_stop` <-> `music_stop`) và
KHÔNG chữa được bằng thêm dữ liệu — chính người nghe cũng không phân biệt được
nếu không biết cái gì đang chạy.
"""
import pytest

from handlers import action_flow
from pipeline import intent as intent_mod
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def test_no_activity_by_default():
    state = action_flow.device_state()
    assert state["music_playing"] is False
    assert state["navigating"] is False


def test_music_play_success_marks_music_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    assert action_flow.device_state()["music_playing"] is True


def test_music_play_failure_does_not_mark_playing():
    """Lệnh gửi đi mà điện thoại báo hỏng thì nhạc KHÔNG chạy — đánh dấu là chạy
    sẽ khiến "tắt đi" ngay sau đó bị hiểu thành tắt một thứ không hề bật."""
    action_flow.note_result("music_play", {"request_state": "failed"})
    assert action_flow.device_state()["music_playing"] is False


def test_music_stop_success_clears_music_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result("music_stop", {"request_state": "succeeded"})
    assert action_flow.device_state()["music_playing"] is False


def test_navigation_start_marks_navigating_and_keeps_id():
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )
    assert action_flow.device_state()["navigating"] is True
    assert action_flow.recall("navigation_id") == "nav-9"


def test_navigation_stop_clears_navigating():
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )
    action_flow.note_result("navigation_stop", {"request_state": "succeeded"})
    assert action_flow.device_state()["navigating"] is False


def test_both_active_reports_which_started_last():
    """Cả nhạc lẫn chỉ đường cùng chạy thì "tắt đi" vẫn mơ hồ — cần biết cái nào
    vừa bật để còn chọn được cái gần nhất thay vì chọn bừa."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    state = action_flow.device_state()
    assert state["music_playing"] and state["navigating"]
    assert state["most_recent"] == "navigating"


def test_pending_ride_quote_shows_in_state():
    action_flow.remember("quote_id", "q-1")
    assert action_flow.device_state()["ride_quote_pending"] is True


# ── Trạng thái đi vào prompt phân loại ────────────────────────────────────


def test_prompt_states_nothing_running_when_idle():
    prompt = intent_mod._build_prompt("tắt đi", action_flow.device_state())
    assert "Nhạc: không phát" in prompt
    assert "Chỉ đường: không chạy" in prompt


def test_prompt_tells_model_music_is_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    prompt = intent_mod._build_prompt("tắt đi", action_flow.device_state())
    assert "Nhạc: ĐANG PHÁT" in prompt


def test_prompt_includes_disambiguation_rule():
    """Nói cho model biết trạng thái mà không nói dùng nó thế nào thì vô ích."""
    prompt = intent_mod._build_prompt("dừng lại", action_flow.device_state())
    assert "music_stop" in prompt and "nav_stop" in prompt


def test_detect_passes_state_into_prompt(monkeypatch):
    seen = {}

    def fake_json(prompt, schema=None, model=None):
        seen["prompt"] = prompt
        return {"intent": Intent.MUSIC_STOP, "params": {}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake_json)
    action_flow.note_result("music_play", {"request_state": "succeeded"})

    name, _ = intent_mod.detect_with_params("tắt đi")
    assert name == Intent.MUSIC_STOP
    assert "Nhạc: ĐANG PHÁT" in seen["prompt"]


def test_detect_works_without_state(monkeypatch):
    """Gọi cũ (không truyền state) vẫn phải chạy — router cũ và test cũ dùng nó."""
    monkeypatch.setattr(
        intent_mod.vlm,
        "generate_json",
        lambda prompt, schema=None, model=None: {"intent": Intent.OCR, "params": {}},
    )
    assert intent_mod.detect_with_params("đọc chữ")[0] == Intent.OCR
