from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

import app as server_app
import config
from services.action_callbacks import ActionCallbackRegistry, action_callbacks


def test_registry_wakes_immediately_and_marks_slo() -> None:
    registry = ActionCallbackRegistry()
    observed: list[dict] = []
    registry.register("req-fast", "music_play", observed.append)

    threading.Thread(
        target=lambda: registry.resolve(
            "req-fast", {"request_id": "req-fast", "request_state": "succeeded"}
        ),
        daemon=True,
    ).start()

    result = registry.wait("req-fast", 1.0)
    assert result is not None
    assert result["slo_missed"] is False
    assert observed == [result]


def test_registry_accepts_duplicate_and_reconciles_late_result() -> None:
    registry = ActionCallbackRegistry()
    observed: list[dict] = []
    registry.register(
        "req-late", "navigation_start", observed.append, registered_at=time.monotonic() - 1.1
    )
    payload = {"request_id": "req-late", "request_state": "succeeded"}

    assert registry.resolve("req-late", payload) is True
    assert registry.resolve("req-late", payload) is True
    assert len(observed) == 1
    assert observed[0]["slo_missed"] is True


def test_callback_endpoint_requires_loopback_bearer_and_idempotency(monkeypatch) -> None:
    monkeypatch.setattr(config, "VISIONCARE_CALLBACK_TOKEN", "test-callback-token")
    action_callbacks.reset()
    action_callbacks.register("req-1", "music_play", lambda _data: None)
    client = TestClient(server_app.app, client=("127.0.0.1", 12345))
    payload = {
        "status": "ok",
        "data": {"request_id": "req-1", "request_state": "succeeded", "result": {}},
    }

    unauthorized = client.post("/internal/action-results", json=payload)
    assert unauthorized.status_code == 401

    accepted = client.post(
        "/internal/action-results",
        json=payload,
        headers={
            "Authorization": "Bearer test-callback-token",
            "Idempotency-Key": "req-1",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"] == {"request_id": "req-1", "matched": True}


def test_callback_endpoint_rejects_caller_outside_allowed_networks(monkeypatch) -> None:
    monkeypatch.setattr(config, "VISIONCARE_CALLBACK_TOKEN", "test-callback-token")
    payload = {"status": "ok", "data": {"request_id": "req-2"}}
    headers = {"Authorization": "Bearer test-callback-token", "Idempotency-Key": "req-2"}

    outsider = TestClient(server_app.app, client=("172.28.0.5", 12345))
    assert outsider.post("/internal/action-results", json=payload, headers=headers).status_code == 403

    monkeypatch.setattr(config, "CALLBACK_ALLOWED_NETWORKS", ("172.28.0.0/16",))
    assert outsider.post("/internal/action-results", json=payload, headers=headers).status_code == 200
