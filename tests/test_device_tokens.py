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


def test_shared_token_cannot_claim_enrolled_device(per_device_tokens, world):  # noqa: F811
    """Id đã có token riêng chỉ dùng được với token riêng của nó (không bị đá phiên / điều khiển điện thoại)."""
    assert guard.authenticate(TEST_DEVICE_TOKEN, "dev-a") is None
    assert guard.authenticate(TEST_DEVICE_TOKEN, "demo-web") == guard.Auth("demo-web", False)  # id lạ vẫn vào
    assert _post_image(TEST_DEVICE_TOKEN, "dev-a").status_code == 401
    with client.websocket_connect("/v2/session") as real:  # kính thật đang online
        _hello(real, device="dev-a", token=TOK_A)
        assert json.loads(real.receive_text())["t"] == "hello_ok"
        real_session = device_session._registry["dev-a"]
        with client.websocket_connect("/v2/session") as fake:
            _hello(fake, device="dev-a", token=TEST_DEVICE_TOKEN)
            msg = fake.receive()
            assert msg["type"] == "websocket.close" and msg["code"] == 4401
        assert device_session._registry["dev-a"] is real_session and not real_session._replaced


def test_per_device_reaches_request_and_session_context(per_device_tokens, world, monkeypatch):  # noqa: F811
    """`device_ctx.per_device`/`current` đúng bên TRONG request HTTP và task của phiên WS (không phải thread test)."""
    seen = []
    monkeypatch.setattr(image_buffer, "put", lambda device, turn, jpeg: seen.append(
        ("http", device, device_ctx.current.get(), device_ctx.per_device.get())))
    assert _post_image(TOK_A, "dev-a").status_code == 204
    assert _post_image(TEST_DEVICE_TOKEN, "demo-web").status_code == 204
    monkeypatch.setattr(device_session.DeviceSession, "emit_mode", lambda self: seen.append(
        ("ws", self.device, device_ctx.current.get(), device_ctx.per_device.get())))
    for device, token in (("dev-a", TOK_A), ("demo-web", TEST_DEVICE_TOKEN)):
        with client.websocket_connect("/v2/session") as ws:
            _hello(ws, device=device, token=token)
            assert json.loads(ws.receive_text())["t"] == "hello_ok"
            deadline = time.time() + 2
            while not any(k == "ws" and d == device for k, d, _, _ in seen) and time.time() < deadline:
                time.sleep(0.01)
    assert seen == [("http", "dev-a", "dev-a", True), ("http", "demo-web", "demo-web", False),
                    ("ws", "dev-a", "dev-a", True), ("ws", "demo-web", "demo-web", False)]


def test_use_resets_per_device_on_device_switch():
    token = device_ctx.per_device.set(True)
    try:
        with device_ctx.use("other"):
            assert device_ctx.per_device.get() is False  # kính khác không thừa kế quyền
        assert device_ctx.per_device.get() is True  # thoát khối thì khôi phục
        with device_ctx.use("dev-a", True):
            assert device_ctx.per_device.get() is True
    finally:
        device_ctx.per_device.reset(token)
    assert device_ctx.per_device.get() is False


def _run_pending(per_device, device="dev-a"):
    import threading

    from pipeline import pending_action

    got, done = [], threading.Event()
    pd = device_ctx.per_device.set(per_device)
    cur = device_ctx.current.set("dev-a")
    try:
        pending_action.schedule(device, 0, lambda: (got.append((device_ctx.current.get(), device_ctx.per_device.get())),
                                                     done.set()), "test-c0")
    finally:
        device_ctx.current.reset(cur)
        device_ctx.per_device.reset(pd)
    assert done.wait(2)
    return got[0]


def test_per_device_survives_pending_action_timer():
    assert _run_pending(True) == ("dev-a", True)
    assert _run_pending(False) == ("dev-a", False)
    assert _run_pending(True, device="dev-other") == ("dev-other", False)  # lệnh đặt cho kính khác: không mang quyền


def test_per_device_survives_action_callback_thread(monkeypatch):
    import threading

    from handlers import action_flow
    from services.action_callbacks import action_callbacks

    rids = []
    monkeypatch.setattr(action_flow, "call_service_api", lambda endpoint, payload: (
        rids.append(payload["request_id"]), {"data": {"request_id": payload["request_id"]}})[1])
    monkeypatch.setattr(action_flow, "get_request_status", lambda rid: {"request_state": "processing"})
    seen, done = [], threading.Event()
    monkeypatch.setattr(action_flow, "note_result", lambda op, data: (
        seen.append((device_ctx.current.get(), device_ctx.per_device.get())), done.set()))
    pd = device_ctx.per_device.set(True)
    cur = device_ctx.current.set("dev-a")
    try:
        gen = action_flow.run_action("op", "ep", {}, "ack", "fail")
        next(gen)  # đã đăng ký callback + gửi lệnh
    finally:
        device_ctx.current.reset(cur)
        device_ctx.per_device.reset(pd)
    threading.Thread(target=action_callbacks.resolve, args=(rids[0], {"request_state": "success"})).start()
    assert done.wait(2)
    assert seen == [("dev-a", True)]
    gen.close()


def test_startup_logs_token_status(per_device_tokens, monkeypatch, caplog):
    """`preload_models` (startup của app) phải gọi `guard.log_startup()` trước khi nạp model."""
    import logging

    import app as app_module

    def stop(*_a, **_k):
        raise RuntimeError("dừng sau log_startup")

    monkeypatch.setattr(app_module.stt, "_load_asr", stop)
    with caplog.at_level(logging.INFO, logger="blind_assist"), pytest.raises(RuntimeError):
        app_module.preload_models()
    text = caplog.text
    assert "token riêng từng kính: 2 kính" in text and "VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN=1" in text
    assert TOK_A not in text and TEST_DEVICE_TOKEN not in text
