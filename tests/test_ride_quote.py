import inspect
import time

import pytest

import config
from handlers import action_flow, chat, result_speech, ride


@pytest.fixture(autouse=True)
def clean_state():
    action_flow.reset_state()
    chat.reset_location_cache()
    yield
    action_flow.reset_state()
    chat.reset_location_cache()


def _set_location(*, age_seconds: float = 0.0) -> dict:
    fix = {
        "lat": 10.1234,
        "lng": 106.5678,
        "address": "Vị trí thật từ điện thoại",
    }
    chat._LOCATION_FIX_CACHE = (fix, time.monotonic() - age_seconds)
    return fix


def test_no_location_refuses_to_book(monkeypatch):
    monkeypatch.setattr(
        action_flow,
        "run_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("không được gọi host khi thiếu vị trí")
        ),
    )

    out = "".join(ride.handle_quote(b"", "", {"destination": "Bách Khoa"}))

    assert "chưa xác định được vị trí" in out.lower()
    assert action_flow.get_pending() is None


def test_demo_location_constant_is_gone():
    source = inspect.getsource(ride)
    assert "_DEMO_CURRENT_LOCATION" not in source
    assert "10.7769" not in source
    assert "106.7009" not in source


def test_destination_readback_uses_session_pending():
    _set_location()

    out = "".join(ride.handle_quote(b"", "", {"destination": "Bách Khoa"}))
    pending = action_flow.get_pending()

    assert "Bách Khoa" in out and "đúng không" in out
    assert pending is not None
    assert pending.slot == "ride_destination"
    assert pending.intent == "ride_confirm"
    assert pending.kind == "confirm"
    assert pending.known["destination"]["address"] == "Bách Khoa"


def test_text_only_destination_fails_closed_before_host_call(monkeypatch):
    _set_location()
    list(ride.handle_quote(b"", "", {"destination": "Bách Khoa"}))
    monkeypatch.setattr(
        action_flow,
        "run_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("không được dùng toạ độ mặc định cho điểm đến")
        ),
    )

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert "tọa độ chính xác" in out
    assert "nhầm chỗ" in out


def test_real_cached_location_is_sent_without_demo_fallback(monkeypatch):
    fix = _set_location()
    captured = {}

    def fake_run_action(operation, endpoint, payload, **kwargs):
        captured.update(
            operation=operation, endpoint=endpoint, payload=payload, kwargs=kwargs
        )
        yield "Đã mở."

    monkeypatch.setattr(action_flow, "run_action", fake_run_action)
    list(
        ride.handle_quote(
            b"",
            "",
            {
                "destination": "Bách Khoa",
                "destination_lat": 10.7721,
                "destination_lng": 106.6578,
            },
        )
    )

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert out == "Đã mở."
    assert captured["operation"] == "ride_quote"
    assert captured["payload"]["current_location"] == fix
    assert captured["payload"]["destination"] == {
        "address": "Bách Khoa",
        "lat": 10.7721,
        "lng": 106.6578,
    }


def test_stale_location_refuses_on_confirm(monkeypatch):
    _set_location()
    list(
        ride.handle_quote(
            b"",
            "",
            {
                "destination": "Bách Khoa",
                "destination_lat": 10.7721,
                "destination_lng": 106.6578,
            },
        )
    )
    _set_location(age_seconds=config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS + 1)
    monkeypatch.setattr(
        action_flow,
        "run_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("không được gửi điểm đón đã cũ")
        ),
    )

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert "chưa xác định được vị trí" in out.lower()


def test_handover_says_one_more_tap():
    speech = ride._OPENING_RIDE_APP + " " + result_speech._RIDE_APP_OPENED
    lowered = speech.lower()
    assert "còn phải chạm một lần" in lowered
    assert "bạn chờ một chút" not in lowered


def test_waiting_in_app_admits_no_tracking():
    lowered = ride._WAITING_IN_APP.lower()
    assert "không theo dõi được chuyến xe" in lowered
    assert "chạm nút đặt xe" in lowered


@pytest.mark.xfail(
    reason="R4: pending select 45s cần services[] thật từ Farefeed", strict=True
)
def test_pending_ttl_45s_not_120s():
    _set_location()
    list(ride.handle_quote(b"", "", {"destination": "Bách Khoa"}))
    pending = action_flow.get_pending()
    assert pending is not None
    assert pending.kind == "select"
    assert pending.ttl == 45.0


@pytest.mark.xfail(
    reason="R4: chưa có Farefeed để refetch bảng giá hết hạn", strict=True
)
def test_expired_pending_refetches():
    pytest.fail("chưa có nguồn Farefeed để refetch")


@pytest.mark.xfail(reason="R1: chưa có quyền partner Farefeed", strict=True)
def test_quote_turn_calls_farefeed():
    pytest.fail("chưa có Farefeed client")


@pytest.mark.xfail(reason="R5: chưa có services[]/deeplink từ Farefeed", strict=True)
def test_confirm_turn_makes_no_request():
    pytest.fail("confirm hiện chưa thể chọn serviceID/deeplink")


@pytest.mark.xfail(reason="R3: chưa có khoảng giá thật từ Farefeed", strict=True)
def test_reads_fare_range_not_single_number():
    pytest.fail("không dựng giá giả")


@pytest.mark.xfail(reason="R3: chưa có surgeNotice thật từ Farefeed", strict=True)
def test_high_surge_adds_warning():
    pytest.fail("không dựng surge giả")


@pytest.mark.xfail(reason="R2: chưa có services[] thật từ Farefeed", strict=True)
def test_reads_only_two_options():
    pytest.fail("không dựng danh sách dịch vụ giả")


@pytest.mark.xfail(reason="R2: chưa có services[] thật trong pending", strict=True)
def test_more_options_no_api_call():
    pytest.fail("không có bảng dịch vụ để đọc tiếp")


@pytest.mark.xfail(reason="R5: provider đến từ Farefeed service", strict=True)
def test_provider_is_a_parameter():
    pytest.fail("chưa có service/provider thật")
