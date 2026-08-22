"""T10 — slot, readback và trạng thái cho chỉ đường."""

from unittest.mock import patch

import pytest

import config
from handlers import action_flow, navigation
from pipeline import router


@pytest.fixture(autouse=True)
def _clean_navigation_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def _capture_actions(monkeypatch):
    calls = []

    def fake_run(operation, endpoint, payload, *, ack, failure, progress, **_kwargs):
        calls.append(
            {
                "operation": operation,
                "endpoint": endpoint,
                "payload": payload,
                "ack": ack,
                "failure": failure,
                "progress": progress,
            }
        )
        yield ack

    monkeypatch.setattr(navigation.action_flow, "run_action", fake_run)
    return calls


def test_nav_missing_destination_two_turns(monkeypatch):
    calls = _capture_actions(monkeypatch)

    first = "".join(navigation.handle_start(b"", "chỉ đường đi", {}))
    pending = action_flow.get_pending()
    assert first == "Bạn muốn đi đâu?"
    assert pending is not None
    assert (pending.slot, pending.intent, pending.kind) == (
        "destination",
        "nav_start",
        "fill",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="Bưu điện Thành phố"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(
                "nav_start",
                {"destination": "Bưu điện Thành phố", "slot_confidence": "high"},
            ),
        ),
    ):
        second = "".join(router.resolve_speech(None, b"audio"))

    assert action_flow.get_pending() is None
    assert len(calls) == 1
    assert calls[0]["payload"] == {
        "destination": {"address": "Bưu điện Thành phố"}
    }
    assert "Bưu điện Thành phố" in second


def test_nav_pending_ttl_120s():
    "".join(navigation.handle_start(b"", "chỉ đường đi", {}))
    pending = action_flow.get_pending()
    assert pending is not None
    assert pending.kind == "fill"
    assert pending.ttl == config.PENDING_TTL_FILL_SECONDS == 120.0


def test_nav_pending_rejects_imperative():
    "".join(navigation.handle_start(b"", "chỉ đường đi", {}))
    action_flow.note_result("music_play", {"request_state": "succeeded"})

    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("handlers.music_stop.handle", return_value=iter(["Đang tắt nhạc."])) as stop,
        patch("handlers.nav_start.handle") as nav_start,
    ):
        list(router.resolve_speech(None, b"audio"))

    stop.assert_called_once()
    nav_start.assert_not_called()


def test_ack_reads_destination_name(monkeypatch):
    calls = _capture_actions(monkeypatch)
    out = "".join(
        navigation.handle_start(
            b"", "", {"destination": "Bách Khoa", "slot_confidence": "high"}
        )
    )

    assert len(calls) == 1
    assert calls[0]["ack"] == "Đang mở chỉ đường tới Bách Khoa."
    assert "Bách Khoa" in out


def test_low_confidence_reads_back_first(monkeypatch):
    calls = _capture_actions(monkeypatch)
    out = "".join(
        navigation.handle_start(
            b"", "", {"destination": "Bát Khoa", "slot_confidence": "low"}
        )
    )

    assert calls == []
    assert out == "Bạn muốn mở chỉ đường tới Bát Khoa, đúng không?"
    assert action_flow.get_pending() is not None


def test_high_confidence_sends_immediately(monkeypatch):
    calls = _capture_actions(monkeypatch)
    "".join(
        navigation.handle_start(
            b"", "", {"destination": "Bách Khoa", "slot_confidence": "high"}
        )
    )
    assert len(calls) == 1
    assert action_flow.get_pending() is None


def test_readback_pending_is_confirm_kind(monkeypatch):
    _capture_actions(monkeypatch)
    "".join(
        navigation.handle_start(
            b"", "", {"destination": "Bát Khoa", "slot_confidence": "low"}
        )
    )

    pending = action_flow.get_pending()
    assert pending is not None
    assert pending.kind == "confirm"
    assert pending.ttl == config.PENDING_TTL_CONFIRM_SECONDS == 25.0
    assert pending.known["destination_confirmed"] is True


@pytest.mark.xfail(
    reason="T20/P7: app NavigationStartHandler luôn trả Success, chưa phát INVALID_DESTINATION",
    strict=True,
)
def test_invalid_destination_sets_pending(monkeypatch):
    monkeypatch.setattr(
        navigation.action_flow,
        "call_service_api",
        lambda *_args, **_kwargs: {"data": {"request_id": "nav-invalid"}},
    )
    monkeypatch.setattr(
        navigation.action_flow,
        "get_request_status",
        lambda _request_id: {
            "request_state": "failed",
            "result": {},
            "error": {"code": "INVALID_DESTINATION"},
        },
    )
    list(
        navigation.handle_start(
            b"", "", {"destination": "Nơi Không Có", "slot_confidence": "high"}
        )
    )
    pending = action_flow.get_pending()
    assert pending is not None and pending.slot == "destination"


def test_stop_without_navigation_id_says_nothing_to_stop(monkeypatch):
    calls = _capture_actions(monkeypatch)
    out = "".join(navigation.handle_stop(b"", "", {}))
    assert calls == []
    assert "không có lộ trình" in out.lower()


def test_stop_marks_inactive(monkeypatch):
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )

    def successful_stop(*_args, ack, **_kwargs):
        action_flow.note_result("navigation_stop", {"request_state": "succeeded"})
        yield ack

    monkeypatch.setattr(navigation.action_flow, "run_action", successful_stop)
    list(navigation.handle_stop(b"", "", {}))
    assert action_flow.device_state()["navigating"] is False


def test_stop_while_music_playing_only_stops_navigation(monkeypatch):
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )

    def successful_stop(*_args, ack, **_kwargs):
        action_flow.note_result("navigation_stop", {"request_state": "succeeded"})
        yield ack

    monkeypatch.setattr(navigation.action_flow, "run_action", successful_stop)
    list(navigation.handle_stop(b"", "", {}))
    state = action_flow.device_state()
    assert state["navigating"] is False
    assert state["music_playing"] is True
