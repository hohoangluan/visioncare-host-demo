from __future__ import annotations

import pytest

from handlers import action_flow, phone
from services import capabilities


def _snapshot(**changes: bool | str) -> dict:
    values: dict[str, bool | str] = {
        "notification_listener": True,
        "system_alert_window": True,
        "battery_optimization_off": True,
        "background_location": "always",
        "fine_location": True,
        "read_contacts": True,
        "read_phone_state": False,
        "call_phone": True,
        "send_sms": True,
        "emergency_contact_set": True,
    }
    values.update(changes)
    return {"capabilities": values}


@pytest.fixture(autouse=True)
def _reset_capabilities() -> None:
    capabilities.reset_for_test()
    yield
    capabilities.reset_for_test()


def _install_snapshot(monkeypatch: pytest.MonkeyPatch, **changes: bool | str) -> None:
    monkeypatch.setattr(
        capabilities.visioncare_client,
        "get_device_capabilities",
        lambda **_kwargs: _snapshot(**changes),
    )
    assert capabilities.cache_at_pairing("device-1") is not None


def test_capabilities_cached_at_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, fine_location=False)
    assert capabilities.get_cached("device-1") == _snapshot(
        fine_location=False
    )["capabilities"]


def test_missing_emergency_contact_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, emergency_contact_set=False)
    first = capabilities.consume_pairing_warning("device-1")
    assert first is not None and "chưa cài số liên hệ khẩn cấp" in first
    assert capabilities.consume_pairing_warning("device-1") is None


def test_missing_minor_permission_stays_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, notification_listener=False)
    assert capabilities.consume_pairing_warning("device-1") is None


def test_error_speech_mentions_missing_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, notification_listener=False)
    speech = capabilities.permission_failure_speech(
        "music_play",
        {"request_state": "failed", "error": {"code": "PLAYBACK_FAILED"}},
        "device-1",
    )
    assert speech is not None
    assert "quyền đọc thông báo" in speech
    assert "chưa phát nhạc được" in speech


def test_capabilities_refreshed_on_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = iter((_snapshot(read_contacts=True), _snapshot(read_contacts=False)))
    calls: list[str] = []

    def fetch(**kwargs: object) -> dict:
        calls.append(str(kwargs.get("device_id")))
        return next(replies)

    monkeypatch.setattr(capabilities.visioncare_client, "get_device_capabilities", fetch)
    assert capabilities.cache_at_pairing("device-1") is not None
    speech = capabilities.permission_failure_speech(
        "contact_call",
        {"request_state": "failed", "error": {"code": "CONTACT_PERMISSION_DENIED"}},
        "device-1",
    )
    assert calls == ["device-1", "device-1"]
    assert speech == "Ứng dụng chưa được cấp quyền đọc danh bạ."


def test_missing_capability_does_not_block_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, notification_listener=False)
    calls: list[str] = []

    def accept(endpoint: str, payload: dict) -> dict:
        calls.append(endpoint)
        return {"data": {}}

    monkeypatch.setattr(action_flow, "call_service_api", accept)
    pieces = list(
        action_flow.run_action(
            "music_play",
            "api/v1/service/music/play",
            {"song": "test"},
            ack="Đang mở nhạc.",
            failure="Không mở được nhạc.",
        )
    )
    assert calls == ["api/v1/service/music/play"]
    assert len(pieces) == 1 and pieces[0].startswith("Đang mở nhạc.")


def test_emergency_checked_before_use(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_snapshot(monkeypatch, emergency_contact_set=False)
    monkeypatch.setattr(capabilities, "current_device_key", lambda: "device-1")

    def forbidden(*_args: object, **_kwargs: object):
        raise AssertionError("emergency action must not be attempted")

    monkeypatch.setattr(action_flow, "run_action", forbidden)
    pieces = list(phone.handle_emergency(b"", "cứu tôi"))
    assert pieces == ["Chưa cài số liên hệ khẩn cấp trên điện thoại."]


def test_no_capabilities_endpoint_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capabilities.visioncare_client,
        "get_device_capabilities",
        lambda **_kwargs: None,
    )
    assert capabilities.refresh("old-device") is None
    assert capabilities.emergency_blocking_speech("old-device") is None
    assert capabilities.permission_failure_speech(
        "music_play",
        {"request_state": "failed", "error": {"code": "PLAYBACK_FAILED"}},
        "old-device",
    ) is None


def test_capability_shape_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _snapshot()
    raw["capabilities"]["camera"] = True
    monkeypatch.setattr(
        capabilities.visioncare_client,
        "get_device_capabilities",
        lambda **_kwargs: raw,
    )
    assert capabilities.refresh("device-1") is None
