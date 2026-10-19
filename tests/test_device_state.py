"""Trạng thái thiết bị (đang phát nhạc? đang chỉ đường?) và cách nó gỡ mơ hồ.

"Tắt đi", "dừng lại", "thôi đủ rồi" không tự nó cho biết tắt cái gì. Đo trên bộ
câu huấn luyện, đây là cặp lẫn nhau nhiều nhất (`nav_stop` <-> `music_stop`) và
KHÔNG chữa được bằng thêm dữ liệu — chính người nghe cũng không phân biệt được
nếu không biết cái gì đang chạy.
"""
import pytest

from handlers import action_flow


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


def test_starting_new_task_clears_previous_active_task():
    """Quy tắc Single Active State: Bật tác vụ mới tự động tắt tác vụ cũ."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    state = action_flow.device_state()
    assert state["music_playing"] is False
    assert state["navigating"] is True
    assert state["most_recent"] == "navigating"


def test_pending_ride_quote_shows_in_state():
    action_flow.remember("quote_id", "q-1")
    assert action_flow.device_state()["ride_quote_pending"] is True


def test_single_active_state_mutual_exclusion():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    assert action_flow.device_state()["music_playing"] is True

    # Khởi chạy navigation -> tự động ngắt music_playing (Single Active State)
    action_flow.note_result("navigation_start", {"request_state": "succeeded", "result": {"navigation_id": "nav-10"}})
    assert action_flow.device_state()["music_playing"] is False
    assert action_flow.device_state()["navigating"] is True


def test_history_isolated_per_device():
    from handlers import chat
    from pipeline import device_ctx
    chat.reset_history()
    with device_ctx.use("kinh-A"):
        chat._HISTORY.append(("hỏi A", "đáp A", 1e12))
    with device_ctx.use("kinh-B"):
        assert chat._recent_turns() == []
    with device_ctx.use("kinh-A"):
        assert chat._recent_turns() == [("hỏi A", "đáp A")]
    chat.reset_history()


def test_device_state_isolated():
    from pipeline import device_ctx
    with device_ctx.use("kinh-A"):
        action_flow.note_result("music_play", {"request_state": "succeeded"})
        action_flow.remember("quote_id", "q1")
        assert action_flow.device_state()["music_playing"] is True
    with device_ctx.use("kinh-B"):
        state = action_flow.device_state()
        assert state["music_playing"] is False
        assert state["most_recent"] is None
        assert action_flow.recall("quote_id") is None


def test_background_thread_keeps_device():
    from pipeline import device_ctx
    seen = []
    with device_ctx.use("kinh-A"):
        t = device_ctx.run_in_thread(lambda: seen.append(device_ctx.current.get()))
    t.join(2)
    assert seen == ["kinh-A"]
