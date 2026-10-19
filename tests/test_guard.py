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


def _asgi_post(path, headers, total, chunk=64 * 1024):
    """POST multipart thật qua ASGI; trả (status, số byte body đã bị đọc)."""
    import asyncio

    read = {"bytes": 0}
    sent: list[dict] = []
    scope = {
        "type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
        "query_string": b"", "http_version": "1.1", "scheme": "http", "server": ("t", 80),
        "client": ("1.2.3.4", 1), "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }

    async def receive():
        if read["bytes"] >= total:
            return {"type": "http.request", "body": b"", "more_body": False}
        body = b"\0" * chunk
        if read["bytes"] == 0:  # phần mở đầu multipart hợp lệ, phần file kéo dài vô tận
            body = (b'--xyz\r\ncontent-disposition: form-data; name="audio"; filename="a.wav"\r\n'
                    b"content-type: audio/wav\r\n\r\n") + body
        read["bytes"] += chunk
        return {"type": "http.request", "body": body, "more_body": True}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], read["bytes"]


_MULTIPART = {"content-type": "multipart/form-data; boundary=xyz"}


def test_process_multipart_no_token_401_without_parsing(no_auto_token):
    status, read = _asgi_post("/process", _MULTIPART, 50_000_000)
    assert status == 401
    assert read == 0


def test_process_multipart_over_cap_413():
    headers = {**_MULTIPART, "x-device-token": TEST_DEVICE_TOKEN}
    status, read = _asgi_post("/process", headers, 50_000_000)  # không khai content-length
    assert status == 413
    assert read <= config.DEVICE_MAX_PROCESS_BYTES + 2 * 64 * 1024
    status, read = _asgi_post("/process", {**headers, "content-length": "50000000"}, 50_000_000)
    assert (status, read) == (413, 0)


def test_audio_header_never_completes_is_capped(monkeypatch):
    from pipeline.stt_stream import StreamingTranscriber

    monkeypatch.setattr(config, "DEVICE_MAX_AUDIO_S", 1)
    t = StreamingTranscriber("audio/wav")
    t.feed(b"RIFF")  # header không bao giờ xong
    for _ in range(100):
        t.feed(b"\0" * 8192)
    assert t.capped and len(t._pending) < 1 * 16000 * 2 + 65536 + 8192


def test_rate_limiter_state_bounded():
    limiter = guard.RateLimiter(60, 1)
    for i in range(10_000):
        limiter.allow(f"dev{i}")
    assert len(limiter._state) <= 4096
