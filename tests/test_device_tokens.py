"""C0: token riêng từng kính ràng buộc device_id; token chung vẫn chạy nhưng không phải per_device."""

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
from app import app
from live import device_session
from pipeline import device_ctx, guard
from pipeline.image_buffer import image_buffer
from tests.conftest import TEST_DEVICE_TOKEN
from tests.test_v2_api import world  # noqa: F401 (fixture)
from tests.test_v2_session import _hello

client = TestClient(app)

TOK_A, TOK_B = "tok-kinh-a-" + "a" * 20, "tok-kinh-b-" + "b" * 20


@pytest.fixture
def per_device_tokens(tmp_path, monkeypatch):
    path = tmp_path / "device_tokens.json"
    path.write_text(json.dumps({"dev-a": hashlib.sha256(TOK_A.encode()).hexdigest(),
                                "dev-b": hashlib.sha256(TOK_B.encode()).hexdigest()}))
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_TOKENS", str(path))
    guard.reset()
    return path


def _post_image(token, device=None):
    headers = {"x-device-token": token}
    if device:
        headers["x-device-id"] = device
    return client.post("/v2/image", content=b"\xff\xd8", headers=headers)


def test_per_device_token_ok(per_device_tokens, world):  # noqa: F811
    assert guard.authenticate(TOK_A, "dev-a") == guard.Auth("dev-a", True)
    assert guard.authenticate(TOK_A) == guard.Auth("dev-a", True)  # không khai id: lấy kính chủ token
    # WS: phiên mang id đã xác thực + per_device, kể cả khi hello không khai device.
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="dev-a", token=TOK_A)
        assert json.loads(ws.receive_text())["t"] == "hello_ok"
        session = device_session._registry["dev-a"]
        assert session.device == "dev-a" and session.per_device is True
    with client.websocket_connect("/v2/session") as ws:
        ws.send_text(json.dumps({"t": "hello", "token": TOK_B}))
        assert json.loads(ws.receive_text())["t"] == "hello_ok"
        assert device_session._registry["dev-b"].per_device is True
    # HTTP: ảnh vào buffer của kính chủ token, kể cả khi client khai X-Device-Id khác đi (bị từ chối, xem test sau).
    image_buffer.clear()
    assert _post_image(TOK_A, "dev-a").status_code == 204
    assert _post_image(TOK_A).status_code == 204  # không khai: vẫn là dev-a
    assert image_buffer.get("dev-a", "") is not None


def test_token_of_other_device_rejected(per_device_tokens, world):  # noqa: F811
    assert guard.authenticate(TOK_B, "dev-a") is None
    assert guard.authenticate("không-phải-token", "dev-a") is None
    assert _post_image(TOK_B, "dev-a").status_code == 401
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="dev-a", token=TOK_B)
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401
    assert "dev-a" not in device_session._registry
    # /v2/live cũng ràng buộc: token của B không mở được phiên live của A.
    from live.session import sessions

    live = sessions.create("dev-a", "nav")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/v2/live?token={live.token}",
                                      headers={"x-device-token": TOK_B, "x-device-id": "dev-a"}):
            pass
    assert exc.value.code == 4401


def test_shared_token_off_rejects_shared(per_device_tokens, monkeypatch):
    monkeypatch.setattr(config, "VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN", False)
    assert guard.authenticate(TEST_DEVICE_TOKEN, "dev-a") is None
    assert _post_image(TEST_DEVICE_TOKEN, "dev-a").status_code == 401
    assert _post_image(TOK_A, "dev-a").status_code == 204  # token riêng vẫn chạy


def test_shared_token_cannot_call(per_device_tokens, world):  # noqa: F811
    """Token chung vẫn vào được (demo-web) nhưng per_device=False ở cả auth, phiên WS lẫn ContextVar."""
    assert guard.authenticate(TEST_DEVICE_TOKEN, "demo-web") == guard.Auth("demo-web", False)
    assert guard.authenticate(TEST_DEVICE_TOKEN) == guard.Auth(config.VISIONCARE_DEVICE_ID, False)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="demo-web", token=TEST_DEVICE_TOKEN, debug=True)
        assert json.loads(ws.receive_text())["t"] == "hello_ok"
        session = device_session._registry["demo-web"]
        assert session.device == "demo-web" and session.per_device is False
    assert device_ctx.per_device.get() is False  # mặc định an toàn
    assert _post_image(TEST_DEVICE_TOKEN, "demo-web").status_code == 204


def test_shared_token_works_without_tokens_file(monkeypatch):
    """Tương thích: không cấu hình file token riêng thì mọi thứ y như trước."""
    monkeypatch.setattr(config, "VISIONCARE_DEVICE_TOKENS", "")
    guard.reset()
    assert guard.authenticate(TEST_DEVICE_TOKEN, "x") == guard.Auth("x", False)
    assert _post_image(TEST_DEVICE_TOKEN).status_code == 204


def test_authenticate_overhead_under_100us(per_device_tokens):
    guard.authenticate(TOK_A)  # nạp file
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        guard.authenticate(TOK_B, "dev-b")
    per_call = (time.perf_counter() - t0) / n
    assert per_call < 1e-4, per_call


def test_device_token_tool_roundtrip(tmp_path):
    from tools import device_token

    path = str(tmp_path / "t.json")
    token = device_token.add("kinh-1", path)
    data = json.loads(open(path).read())
    assert data == {"kinh-1": hashlib.sha256(token.encode()).hexdigest()} and token not in open(path).read()
    with pytest.raises(SystemExit):
        device_token.add("kinh-1", path)  # không ghi đè âm thầm
    assert device_token.add("kinh-1", path, force=True) != token
