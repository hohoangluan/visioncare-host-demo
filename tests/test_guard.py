"""Task 9: xác thực thiết bị, trần kích thước, rate limit."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
from app import app
from pipeline import guard
from tests.conftest import TEST_DEVICE_TOKEN

client = TestClient(app)

HTTP_ENDPOINTS = ["/process", "/v2/image", "/v2/turn"]


@pytest.mark.parametrize("path", HTTP_ENDPOINTS + ["/v2/live"])
def test_missing_token_401(no_auto_token, path):
    if path == "/v2/live":
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/v2/live?token=whatever"):
                pass
        assert exc.value.code == 4401
        return
    response = client.post(path, content=b"x")
    assert response.status_code == 401


def test_token_not_configured_503(no_auto_token, monkeypatch):
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_CLIENT_TOKEN", "")
    for path in HTTP_ENDPOINTS:
        # Kể cả khi kính gửi "token rỗng": không được lọt qua.
        response = client.post(path, content=b"x", headers={"X-Device-Token": ""})
        assert response.status_code == 503
        assert response.json() == {"error": "device token not configured"}


def test_image_over_cap_413_without_reading_all(monkeypatch):
    """Dựng ASGI thẳng: TestClient gom cả body trước khi gọi app nên che mất việc đếm."""
    import asyncio

    monkeypatch.setattr(config, "DEVICE_MAX_IMAGE_BYTES", 2_000_000)
    chunk = 64 * 1024
    read = {"bytes": 0}
    sent: list[dict] = []
    scope = {
        "type": "http", "method": "POST", "path": "/v2/image", "raw_path": b"/v2/image",
        "query_string": b"", "http_version": "1.1", "scheme": "http", "server": ("t", 80),
        "client": ("1.2.3.4", 1), "root_path": "",
        "headers": [(b"x-device-token", TEST_DEVICE_TOKEN.encode())],  # không khai content-length
    }

    async def receive():
        if read["bytes"] >= 3_000_000:
            return {"type": "http.request", "body": b"", "more_body": False}
        read["bytes"] += chunk
        return {"type": "http.request", "body": b"\0" * chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 413
    assert read["bytes"] <= 2_000_000 + 2 * chunk


def test_rate_limit_429(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_IMAGES_PER_MIN", 3)
    guard.reset()
    codes = [client.post("/v2/image", content=b"\xff\xd8").status_code for _ in range(5)]
    assert codes[:3] == [204, 204, 204]
    assert codes[3:] == [429, 429]
