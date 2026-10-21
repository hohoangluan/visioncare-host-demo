"""`demo-web/serve.py` chỉ chuyển tiếp danh sách trắng: `/internal/*` không bao giờ tới server kính (I-3)."""

import importlib.util
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest

_SERVE = os.path.join(os.path.dirname(__file__), "..", "demo-web", "serve.py")


@pytest.fixture
def proxy():
    spec = importlib.util.spec_from_file_location("demo_serve", _SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    seen: list[str] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        do_POST = do_GET

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    serve.Handler.upstream = urlsplit(f"http://127.0.0.1:{up.server_port}")
    front = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    for srv in (up, front):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{front.server_port}", seen
    for srv in (up, front):
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("path", [
    "/api/internal/calls", "/api/internal/messages", "/api/internal/action-results",
    "/api/v2/session/../internal/calls", "/api/%2e%2e/internal/calls", "/api//internal/calls",
    "/api/v2/debug/stats", "/api/",
])
def test_internal_and_unknown_paths_are_not_forwarded(proxy, path):
    base, seen = proxy
    for method in ("GET", "POST"):
        resp = httpx.request(method, base + path, headers={"Authorization": "Bearer x"}, content=b"{}")
        assert resp.status_code == 404
    assert seen == []


@pytest.mark.parametrize("path, upstream", [
    ("/api/health", "/health"), ("/api/process?x=1", "/process?x=1"), ("/api/v2/turn", "/v2/turn"),
    ("/api/v2/image", "/v2/image"), ("/api/v2/observe", "/v2/observe"),
])
def test_allowed_paths_are_forwarded(proxy, path, upstream):
    base, seen = proxy
    resp = httpx.post(base + path, content=b"{}")
    assert resp.status_code == 200 and resp.text == "ok"
    assert seen == [upstream]


# --- cấu hình sẵn: proxy tự gắn token vào WS của trang, token không bao giờ xuống trình duyệt ---

TOKEN = "tok-bi-mat-cua-server"


@pytest.fixture
def ws_proxy():
    """Proxy + upstream TCP thô ghi lại nguyên request bắt tay WS mà proxy chuyển lên."""
    spec = importlib.util.spec_from_file_location("demo_serve_ws", _SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    captured: list[str] = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def accept_loop():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            captured.append(data.decode("latin-1"))
            conn.close()

    threading.Thread(target=accept_loop, daemon=True).start()
    serve.Handler.upstream = urlsplit(f"http://127.0.0.1:{listener.getsockname()[1]}")
    serve.Handler.device_token = TOKEN
    serve.Handler.device_id = "kinh-hien-tai"
    front = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=front.serve_forever, daemon=True).start()
    yield serve, front.server_port, captured
    front.shutdown()
    front.server_close()
    listener.close()


def _upgrade(port, path, **headers):
    """Gửi yêu cầu nâng cấp WS thô tới proxy, trả request upstream nhận được (chuỗi header)."""
    host = headers.pop("Host", f"127.0.0.1:{port}")
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
             "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==", "Sec-WebSocket-Version: 13"]
    lines += [f"{k.replace('_', '-')}: {v}" for k, v in headers.items()]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        sock.settimeout(5)
        try:
            while sock.recv(4096):
                pass
        except (socket.timeout, OSError):
            pass


def _wait_captured(captured, n=1):
    import time

    deadline = time.monotonic() + 3
    while len(captured) < n and time.monotonic() < deadline:
        time.sleep(0.02)
    return captured


def test_config_json_gives_device_and_never_the_token(ws_proxy):
    _, port, _ = ws_proxy
    resp = httpx.get(f"http://127.0.0.1:{port}/config.json")
    assert resp.status_code == 200 and resp.json() == {"device": "kinh-hien-tai", "phone_mirror": False}
    assert TOKEN not in resp.text and resp.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/api/v2/observe", "/api/v2/session"])
def test_proxy_injects_token_into_same_origin_ws(ws_proxy, path):
    _, port, captured = ws_proxy
    _upgrade(port, path, Origin=f"http://127.0.0.1:{port}")
    assert f"Authorization: Bearer {TOKEN}" in _wait_captured(captured)[0]


def test_proxy_injects_token_when_no_origin_header(ws_proxy):
    _, port, captured = ws_proxy
    _upgrade(port, "/api/v2/observe")  # client không phải trình duyệt (realcheck...) không có Origin
    assert f"Authorization: Bearer {TOKEN}" in _wait_captured(captured)[0]


def test_proxy_does_not_lend_token_to_foreign_origin(ws_proxy):
    _, port, captured = ws_proxy
    _upgrade(port, "/api/v2/observe", Origin="https://trang-la.example")
    assert TOKEN not in _wait_captured(captured)[0]


def test_proxy_keeps_token_the_client_brought(ws_proxy):
    _, port, captured = ws_proxy
    _upgrade(port, "/api/v2/observe", Authorization="Bearer cua-client")
    sent = _wait_captured(captured)[0]
    assert "Bearer cua-client" in sent and TOKEN not in sent


def test_proxy_injects_only_on_observe_and_session(ws_proxy):
    _, port, captured = ws_proxy
    _upgrade(port, "/api/v2/live")
    assert TOKEN not in _wait_captured(captured)[0]


def test_no_token_configured_injects_nothing(ws_proxy):
    serve, port, captured = ws_proxy
    serve.Handler.device_token = ""
    _upgrade(port, "/api/v2/observe")
    assert "Authorization" not in _wait_captured(captured)[0]


def test_demo_credentials_read_env_file_and_cli_wins(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("demo_serve_env", _SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    env = tmp_path / ".env"
    env.write_text("# ghi chú\nOTHER=1\nVISIONCARE_DEVICE_CLIENT_TOKEN='tok-env'\nVISIONCARE_DEVICE_ID=glasses-env\n")
    for key in ("VISIONCARE_DEVICE_CLIENT_TOKEN", "VISIONCARE_DEVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    assert serve.demo_credentials(env_file=str(env)) == ("tok-env", "glasses-env")
    assert serve.demo_credentials("tok-cli", "kinh-cli", env_file=str(env)) == ("tok-cli", "kinh-cli")
    monkeypatch.setenv("VISIONCARE_DEVICE_ID", "glasses-shell")  # biến môi trường thắng .env
    assert serve.demo_credentials(env_file=str(env)) == ("tok-env", "glasses-shell")
    assert serve.demo_credentials(env_file=str(tmp_path / "khong-co")) == ("", "glasses-shell")
    monkeypatch.delenv("VISIONCARE_DEVICE_ID")
    assert serve.demo_credentials(env_file=str(tmp_path / "khong-co")) == ("", "glasses-123")  # như config.py


def test_demo_credentials_token_file(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("demo_serve_tokfile", _SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    env = tmp_path / ".env"
    env.write_text("VISIONCARE_DEVICE_CLIENT_TOKEN=tok-env\nVISIONCARE_DEVICE_ID=glasses-env\n")
    tf = tmp_path / "kinh.token"
    tf.write_text("tok-file\n")
    for key in ("VISIONCARE_DEVICE_CLIENT_TOKEN", "VISIONCARE_DEVICE_ID"):
        monkeypatch.delenv(key, raising=False)
    assert serve.demo_credentials(env_file=str(env), token_file=str(tf)) == ("tok-file", "glasses-env")  # thắng .env
    assert serve.demo_credentials("tok-cli", env_file=str(env), token_file=str(tf))[0] == "tok-cli"  # --token thắng
    with pytest.raises(SystemExit):
        serve.demo_credentials(env_file=str(env), token_file=str(tmp_path / "khong-co"))


# ---------------------------------------------------------------------------
# --phone-mirror: màn hình điện thoại qua adb (giả lập bằng script phát h264 từ ffmpeg testsrc)
# ---------------------------------------------------------------------------

import shutil  # noqa: E402
import time  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")


def _load_serve():
    spec = importlib.util.spec_from_file_location("demo_serve", _SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    return serve


class _FakeAdbPort:
    """Cổng adb server giả (127.0.0.1:<tạm>): `close()` thật sự ngừng LISTEN (đóng socket đang accept trên Linux thì không)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.sock.accept()[0].close()
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._thread.join(2)
        self.sock.close()


@pytest.fixture
def mirror_world(tmp_path, monkeypatch):
    """(serve, port của trang, log lệnh adb, đóng/mở 'cổng adb 5037'). adb giả = script phát testsrc dạng h264."""
    log = tmp_path / "adb.log"
    adb = tmp_path / "adb"
    adb.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexec ffmpeg -v error -f lavfi -i testsrc=size=540x1170:rate=10 -t 2 -f h264 -\n')
    adb.chmod(0o755)
    listener = _FakeAdbPort()
    adb_port = listener.port

    serve = _load_serve()
    serve.Handler.mirror = serve.PhoneMirror(adb=str(adb), port=adb_port)
    serve.Handler.upstream = urlsplit("http://127.0.0.1:1")
    front = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=front.serve_forever, daemon=True).start()
    yield serve, front.server_port, log, listener
    front.shutdown()
    front.server_close()
    serve.Handler.mirror.release()
    listener.close()


def _read_frames(url, want, timeout=15):
    """Đọc MJPEG nhiều phần tới khi đủ `want` khung JPEG; trả (header content-type, số khung, số byte khung đầu)."""
    frames, buf, first = 0, b"", None
    deadline = time.monotonic() + timeout
    with httpx.stream("GET", url, timeout=timeout) as resp:
        ctype = resp.headers.get("content-type", "")
        for chunk in resp.iter_bytes():
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                if e < 0:
                    break
                frames += 1
                first = first or (e + 2 - s)
                buf = buf[e + 2:]
            if frames >= want or time.monotonic() > deadline:
                break
    return ctype, frames, first


def test_phone_stream_404_when_not_enabled(proxy):
    base, _ = proxy
    assert httpx.get(base + "/phone/stream.mjpg").status_code == 404


def test_config_says_phone_mirror_only_when_adb_listening(mirror_world):
    serve, port, log, listener = mirror_world
    assert httpx.get(f"http://127.0.0.1:{port}/config.json").json()["phone_mirror"] is True
    listener.close()
    assert httpx.get(f"http://127.0.0.1:{port}/config.json").json()["phone_mirror"] is False


def test_phone_stream_503_and_never_calls_adb_when_port_closed(mirror_world):
    serve, port, log, listener = mirror_world
    listener.close()
    resp = httpx.get(f"http://127.0.0.1:{port}/phone/stream.mjpg")
    assert resp.status_code == 503
    assert not log.exists()  # adb không được gọi (nó sẽ tự dựng daemon cục bộ)
    assert not serve.Handler.mirror.running


@needs_ffmpeg
def test_phone_stream_serves_multipart_jpeg_and_uses_exact_adb_command(mirror_world):
    serve, port, log, _ = mirror_world
    ctype, frames, first = _read_frames(f"http://127.0.0.1:{port}/phone/stream.mjpg", want=5)
    assert ctype.startswith("multipart/x-mixed-replace") and "boundary=" in ctype
    assert frames >= 5 and first > 500
    args = log.read_text().splitlines()[0].split()
    assert args[-8:] == ["exec-out", "screenrecord", "--output-format=h264", "--size", "540x1170", "--bit-rate", "2000000", "-"]
    assert "-P" in args and str(serve.Handler.mirror.port) in args


@needs_ffmpeg
def test_phone_stream_restarts_after_screenrecord_ends_and_stops_with_no_viewer(mirror_world):
    serve, port, log, _ = mirror_world
    m = serve.Handler.mirror
    _, frames, _ = _read_frames(f"http://127.0.0.1:{port}/phone/stream.mjpg", want=30, timeout=20)
    assert frames >= 30  # adb giả chỉ phát 2 s (~20 khung): phải chạy lại mới đủ 30
    assert m.runs >= 2
    deadline = time.monotonic() + 5
    while m.running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not m.running and not m._procs  # không còn ai xem: dừng hẳn, không còn tiến trình con
    runs = len(log.read_text().splitlines())
    time.sleep(1.0)
    assert len(log.read_text().splitlines()) == runs  # và không tự chạy lại


@needs_ffmpeg
def test_phone_stream_is_shared_between_viewers(mirror_world):
    serve, port, log, _ = mirror_world
    results = []
    ts = [threading.Thread(target=lambda: results.append(_read_frames(f"http://127.0.0.1:{port}/phone/stream.mjpg", want=8))) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert len(results) == 2 and all(r[1] >= 8 for r in results)
    assert serve.Handler.mirror.runs <= 2  # một đường ống chung, không phải mỗi người một screenrecord
