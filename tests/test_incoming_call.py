from __future__ import annotations

import json
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

import app as app_module
import config
from handlers import action_flow
from handlers import incoming_call as incoming_call_handler
from pipeline import router
from services.events_channel import events
from services.incoming_calls import (
    IncomingCallRegistry,
    announcement_for,
    incoming_calls,
    sanitize_caller,
)


@pytest.fixture(autouse=True)
def _clean_call_state() -> None:
    incoming_calls.clear()
    events.clear()
    yield
    incoming_calls.clear()
    events.clear()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.VISIONCARE_CALLBACK_TOKEN}"}


def _post(payload: dict[str, object]):
    return TestClient(app_module.app, client=("127.0.0.1", 12345)).post(
        "/internal/device-events", json=payload, headers=_headers()
    )


def _open_payload(caller: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "device_id": "glasses-a",
        "type": "call_incoming",
        "caller": caller or {"contact_id": "contact-1", "name": "Mẹ", "number_tail": "456"},
    }


def test_cuts_tts_within_200ms() -> None:
    before = action_flow.current_generation("glasses-a")
    started = time.monotonic()
    response = _post(_open_payload())
    elapsed_ms = (time.monotonic() - started) * 1000

    assert response.status_code == 200
    assert action_flow.current_generation("glasses-a") == before + 1
    assert response.json()["data"]["interruption_ms"] < 200
    assert elapsed_ms < 200


def test_pending_survives_incoming_call() -> None:
    token = app_module.DEVICE_ID_CTX.set("glasses-a")
    try:
        pending = action_flow.set_pending(
            "contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?"
        )
        response = _post(_open_payload())
        assert response.status_code == 200
        assert action_flow.get_pending() is pending
    finally:
        action_flow.clear_pending()
        app_module.DEVICE_ID_CTX.reset(token)


def test_emergency_beats_incoming_call(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming_calls.open("glasses-a", {"name": "Mẹ"})
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "gọi cấp cứu")
    with patch("handlers.emergency_call.handle", return_value=iter(("emergency",))) as emergency:
        assert list(router._resolve(None, b"audio", "glasses-a")) == ["emergency"]
    emergency.assert_called_once()
    assert incoming_calls.current("glasses-a") is not None


@pytest.mark.parametrize(
    ("spoken", "intent"),
    [("nghe máy", "call_answer"), ("nghe", "call_answer"), ("trả lời", "call_answer"),
     ("từ chối", "call_reject"), ("không nghe", "call_reject"), ("bỏ", "call_reject")],
)
def test_intent_window_15s(monkeypatch: pytest.MonkeyPatch, spoken: str, intent: str) -> None:
    registry = IncomingCallRegistry(window_seconds=15)
    registry.open("glasses-a", {}, now=100)
    assert registry.command("glasses-a", spoken, now=114.999) == intent
    assert registry.command("glasses-a", spoken, now=115) is None


def test_call_control_beats_pending_and_preserves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    token = app_module.DEVICE_ID_CTX.set("glasses-a")
    try:
        pending = action_flow.set_pending(
            "contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?"
        )
        incoming_calls.open("glasses-a", {"name": "Mẹ"})
        monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "nghe máy")
        with patch(
            "handlers.incoming_call.handle_answer", return_value=iter(("Đang nghe máy.",))
        ) as answer:
            assert list(router._resolve(None, b"audio", "glasses-a")) == ["Đang nghe máy."]
        answer.assert_called_once()
        assert action_flow.get_pending() is pending
        assert incoming_calls.current("glasses-a") is None
    finally:
        action_flow.clear_pending()
        app_module.DEVICE_ID_CTX.reset(token)


def test_window_closes_when_ringing_stops() -> None:
    assert _post(_open_payload()).status_code == 200
    response = _post({"device_id": "glasses-a", "type": "call_ended"})
    assert response.status_code == 200
    assert incoming_calls.current("glasses-a") is None


def test_call_ended_says_nothing() -> None:
    stream = events.subscribe("glasses-a")
    incoming_calls.open("glasses-a", {"name": "Mẹ"})
    response = _post({"device_id": "glasses-a", "type": "call_ended"})
    event = json.loads(next(stream)[6:-2])
    stream.close()

    assert response.status_code == 200
    assert response.json()["data"].get("announcement") is None
    assert event == {"type": "call_ended"}


def test_known_contact_reads_name() -> None:
    assert announcement_for({"contact_id": "1", "name": "Mẹ", "number_tail": "456"}) == (
        "Có cuộc gọi từ Mẹ đang gọi."
    )


def test_unknown_number_reads_digits() -> None:
    assert announcement_for({"number_tail": "456"}) == "Số lạ, đuôi bốn năm sáu."


def test_duplicate_name_adds_tail() -> None:
    assert announcement_for(
        {"contact_id": "1", "name": "Mẹ", "number_tail": "789", "duplicate_name": True}
    ) == "Có cuộc gọi từ Mẹ, đuôi bảy tám chín, đang gọi."


@pytest.mark.parametrize(
    "caller",
    [
        {"number": "0901234567"},
        {"full_number": "0901234567"},
        {"number_tail": "12345"},
        {"name": "090 123 4567"},
    ],
)
def test_never_accepts_full_number(caller: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        sanitize_caller(caller)


def test_announce_caller_number_only() -> None:
    assert announcement_for({"contact_id": "1", "number_tail": "456"}) == (
        "Số gọi đến, đuôi bốn năm sáu."
    )


def test_announce_caller_ring_only() -> None:
    assert announcement_for({}) is None


def test_device_event_does_not_require_request_id() -> None:
    response = _post(_open_payload())
    assert response.status_code == 200
    assert response.json()["data"]["type"] == "call_incoming"


def test_device_event_rejects_full_number() -> None:
    response = _post(_open_payload({"number": "0901234567"}))
    assert response.status_code == 422
    assert "0901234567" not in response.text


def test_device_event_requires_internal_auth() -> None:
    response = TestClient(app_module.app, client=("127.0.0.1", 12345)).post(
        "/internal/device-events", json=_open_payload()
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("handler", "endpoint", "ack"),
    [
        (incoming_call_handler.handle_answer, "api/v1/service/call/answer", "Đang nghe máy."),
        (incoming_call_handler.handle_reject, "api/v1/service/call/reject", "Đã từ chối cuộc gọi."),
    ],
)
def test_call_control_uses_host_action_pipeline(
    monkeypatch: pytest.MonkeyPatch, handler, endpoint: str, ack: str
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def accept(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((path, payload))
        return {"data": {"request_id": payload["request_id"]}}

    monkeypatch.setattr(action_flow, "call_service_api", accept)
    stream = handler(None, "", {})
    assert next(stream) == ack + "\n"
    stream.close()

    assert calls[0][0] == endpoint
    assert set(calls[0][1]) == {"request_id"}
