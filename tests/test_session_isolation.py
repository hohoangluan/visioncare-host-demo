"""T03 — cách ly theo `device_id` (B6) + dọn session (câu 2 mục 6).

`device_id` được set qua `app.DEVICE_ID_CTX` (ContextVar của T01) bằng cùng
cách `app.py:_resolve_device_turn` làm thật trong request — không tự dựng lại
cơ chế định danh khác.

CHỦ Ý bỏ hai ca so với danh sách gốc ở `docs/tasks/T03-session-pending.md`
mục 4.2 — xem "Cần người dùng chốt" / "Lệch với task file" trong
`docs/tasks/reports/T03.md`:
  - `test_history_isolated_between_devices` viết ở ĐÂY vẫn có, nhưng chỉ kiểm
    hạ tầng `record_history_turn`/`recent_history` của `action_flow.py` —
    KHÔNG kiểm `handlers/chat.py` (B4, ngoài phạm vi sửa của T03).
  - `test_location_cache_shared_or_isolated` KHÔNG viết: câu hỏi 🔴 #9 ở
    CONTRACTS.md mục 7 chưa chốt, và cache đó nằm ở `handlers/chat.py` (ngoài
    phạm vi sửa của T03) — cả hai lý do đều chặn, không chỉ một.

Thêm sau review (bug Critical — xem "Sửa theo review" ở
`docs/tasks/reports/T03.md`): `note_result()` được ĐĂNG KÝ làm callback trong
`run_action()` lúc CÓ `DEVICE_ID_CTX` đúng, nhưng được GỌI LẠI từ hai nơi
KHÔNG có ContextVar nào — `POST /internal/action-results` (request khác) và
luồng nền `reconcile_late` (`threading.Thread` mới). `test_music_state_
isolated_between_devices` ở trên KHÔNG bắt được bug này vì nó gọi
`note_result` trực tiếp bên trong `_as_device(...)` — mô phỏng SAI đường thật.
`test_action_result_callback_lands_in_correct_device_session_from_bare_thread`
dưới đây gọi callback đã đăng ký từ một thread THẬT không set ContextVar gì,
đúng như hai đường production.
"""
import contextlib
import threading
import uuid

import pytest

import app as app_module
from handlers import action_flow
from services.action_callbacks import action_callbacks


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


@contextlib.contextmanager
def _as_device(device_id: str):
    """Mô phỏng đúng cách `app.py:_resolve_device_turn` gán ContextVar trong
    scope một request — set/reset bằng token, không set ở module level."""
    token = app_module.DEVICE_ID_CTX.set(device_id)
    try:
        yield
    finally:
        app_module.DEVICE_ID_CTX.reset(token)


def test_pending_isolated_between_devices():
    with _as_device("kinh-a"):
        action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")

    with _as_device("kinh-b"):
        assert action_flow.get_pending() is None
        action_flow.set_pending("destination", "navigation_start", {}, "Đi đâu?")

    with _as_device("kinh-a"):
        pending_a = action_flow.get_pending()
        assert pending_a is not None
        assert pending_a.slot == "song_title"

    with _as_device("kinh-b"):
        pending_b = action_flow.get_pending()
        assert pending_b is not None
        assert pending_b.slot == "destination"


def test_music_state_isolated_between_devices():
    with _as_device("kinh-a"):
        action_flow.note_result("music_play", {"request_state": "succeeded"})

    with _as_device("kinh-b"):
        assert action_flow.device_state()["music_playing"] is False

    with _as_device("kinh-a"):
        assert action_flow.device_state()["music_playing"] is True


def test_history_isolated_between_devices():
    """Hạ tầng lịch sử theo device của `action_flow.py` (chưa nối vào
    `handlers/chat.py` — xem docstring module này)."""
    with _as_device("kinh-a"):
        action_flow.record_history_turn("đặt xe đi Bách Khoa", "đã mở Grab")

    with _as_device("kinh-b"):
        assert action_flow.recent_history() == []

    with _as_device("kinh-a"):
        history = action_flow.recent_history()
        assert history == [("đặt xe đi Bách Khoa", "đã mở Grab")]


def test_session_gc_removes_idle_device():
    with _as_device("kinh-cu"):
        action_flow.remember("navigation_id", "nav-1")

    assert "kinh-cu" in action_flow._SESSIONS

    # Thiết bị "không hoạt động" 25 giờ -> quá ngưỡng mặc định 24h.
    far_future = action_flow._SESSIONS["kinh-cu"].last_seen + 25 * 3600
    removed = action_flow.gc_idle_sessions(now=far_future)

    assert removed == 1
    assert "kinh-cu" not in action_flow._SESSIONS


def test_session_gc_keeps_active_device():
    with _as_device("kinh-moi"):
        action_flow.remember("navigation_id", "nav-1")

    near_future = action_flow._SESSIONS["kinh-moi"].last_seen + 60  # 1 phút, còn mới
    removed = action_flow.gc_idle_sessions(now=near_future)

    assert removed == 0
    assert "kinh-moi" in action_flow._SESSIONS


def test_action_result_callback_lands_in_correct_device_session_from_bare_thread(
    monkeypatch,
):
    """Bug thật đã sửa: callback đăng ký trong `run_action()` (lúc CÓ device
    context) bị GỌI LẠI từ một luồng KHÔNG có ContextVar nào — đúng như
    `POST /internal/action-results` (request khác) và `reconcile_late()`
    (`threading.Thread` mới) làm trong production. Kết quả PHẢI vào đúng
    session của thiết bị đã tạo ra action, KHÔNG phải session dùng chung
    (`_NO_DEVICE_CONTEXT_KEY`).

    Chỉ chạy `run_action()` tới NGAY SAU khi nó đăng ký callback (một
    `next()`) — dừng ở đó tránh phải chờ `action_callbacks.wait()` (vài giây,
    không liên quan tới bug đang kiểm) và tránh gọi mạng thật.
    """
    request_id = f"req-{uuid.uuid4().hex[:8]}"

    def fake_call_service_api(endpoint, payload):
        return {
            "data": {
                "request_id": request_id,
                "operation": "navigation_start",
                "request_state": "processing",
            }
        }

    def fake_get_request_status(_request_id):
        return {"request_state": "processing"}

    monkeypatch.setattr(action_flow, "call_service_api", fake_call_service_api)
    monkeypatch.setattr(action_flow, "get_request_status", fake_get_request_status)

    with _as_device("kinh-that"):
        gen = action_flow.run_action(
            "navigation_start",
            "api/v1/service/navigation/start",
            {"destination": {"address": "Bách Khoa"}},
            ack="Đang mở chỉ đường.",
            failure="Không thể mở chỉ đường.",
        )
        next(gen)  # chạy tới ngay sau `action_callbacks.register(...)`, dừng ở yield ack

    # Ra khỏi `with` -> DEVICE_ID_CTX đã reset, giống lúc request `/process`
    # gốc đã trả lời xong từ lâu trước khi kết quả action về tới.
    assert app_module.DEVICE_ID_CTX.get() is None

    result_holder = {}

    def resolve_from_bare_thread():
        # Không set bất kỳ ContextVar nào ở đây — đúng thread mới thật, giống
        # `reconcile_late()`/handler của `POST /internal/action-results`.
        result_holder["resolved"] = action_callbacks.resolve(
            request_id,
            {
                "request_state": "succeeded",
                "result": {"navigation_id": "nav-99"},
            },
        )

    t = threading.Thread(target=resolve_from_bare_thread)
    t.start()
    t.join(timeout=5)

    assert result_holder.get("resolved") is True

    # ĐÚNG thiết bị phải thấy kết quả.
    with _as_device("kinh-that"):
        assert action_flow.recall("navigation_id") == "nav-99"
        assert action_flow.device_state()["navigating"] is True

    # Session dùng chung (ambient, không context) PHẢI sạch — trước khi sửa,
    # bug này ghi đúng vào đây thay vì "kinh-that".
    assert action_flow.recall("navigation_id") is None
    assert action_flow.device_state()["navigating"] is False
