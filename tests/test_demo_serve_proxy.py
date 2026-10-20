"""`demo-web/serve.py` chỉ chuyển tiếp danh sách trắng: `/internal/*` không bao giờ tới server kính (I-3)."""

import importlib.util
import os
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
    ("/api/v2/image", "/v2/image"),
])
def test_allowed_paths_are_forwarded(proxy, path, upstream):
    base, seen = proxy
    resp = httpx.post(base + path, content=b"{}")
    assert resp.status_code == 200 and resp.text == "ok"
    assert seen == [upstream]
