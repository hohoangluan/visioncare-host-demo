"""Phục vụ trang demo và chuyển tiếp `/api/*` tới server kính.

Cấu hình sẵn: mở trang là chạy, không phải nhập token hay mã kính. Proxy đọc `VISIONCARE_DEVICE_CLIENT_TOKEN` và
`VISIONCARE_DEVICE_ID` (biến môi trường, hoặc `.env` của repo, hoặc `--token`/`--device`) rồi tự gắn `Authorization:
Bearer <token>` vào kết nối WebSocket `/api/v2/observe` và `/api/v2/session` của trang CÙNG NGUỒN GỐC; token không bao
giờ xuống trình duyệt. Mã kính (không bí mật) trang lấy ở `/config.json`. Hệ quả: ai mở được trang này (`--lan` là cả
mạng) là được vào luôn với quyền kính, nên chỉ bật trong mạng demo.

Cần có file này vì hai lý do:

- `app.py` không bật CORS. Trang mở từ nguồn khác (file://, cổng khác) gọi
  thẳng `/process` là bị trình duyệt chặn. Chuyển tiếp qua cùng một nguồn thì
  trang không cần server sửa gì.
- `getUserMedia` (camera/micro của `client.html`) chỉ chạy trên https hoặc localhost. Phục vụ
  trang ở đây rồi mở bằng http://localhost:8080 là đủ điều kiện.

Ngoài HTTP còn chuyển tiếp WebSocket: `/api/v2/observe` (bảng giám sát `index.html`, chỉ xem) và
`/api/v2/session` (kính giả lập `client.html`) tới server kính. Proxy không đọc khung,
chỉ chuyển byte hai chiều sau cái bắt tay `Upgrade: websocket`.

Chỉ dùng thư viện chuẩn: máy trình bày không cần cài thêm gì.

    python demo-web/serve.py                       # server kính ở 127.0.0.1:8000
    python demo-web/serve.py --upstream http://192.168.1.20:8000

Client là máy khác (laptop BGK) thì chạy trên máy đặt server:

    python demo-web/serve.py --lan

`--lan` mở cổng cho cả mạng và bật https với chứng chỉ tự ký, vì camera/micro của
`client.html` bị trình duyệt từ chối chạy qua http://<địa-chỉ-IP> (bảng giám sát thì không cần).

`--phone-mirror` (tuỳ chọn, mặc định tắt): ô "Điện thoại" của bảng giám sát hiện màn hình điện thoại THẬT qua
`/phone/stream.mjpg` (multipart MJPEG). Nguồn: `adb exec-out screenrecord` (h264) -> ffmpeg -> MJPEG. Chỉ chạy khi có
người xem và dừng khi không còn ai; screenrecord tự hết sau 180 s thì chạy lại. adb chỉ được gọi khi cổng adb server
(mặc định 127.0.0.1:5037, vd. SSH RemoteForward từ máy cắm điện thoại) đang LISTEN: không bao giờ để adb tự khởi động
daemon cục bộ. Biến môi trường: `SEEVIA_ADB` (mặc định ~/android-sdk/platform-tools/adb), `SEEVIA_FFMPEG`,
`SEEVIA_ADB_PORT`, `SEEVIA_ADB_SERIAL`. Ai mở được trang đều xem được màn hình điện thoại: chỉ bật trong mạng demo.
"""
import argparse
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
API_PREFIX = "/api/"

# Danh sách trắng đường dẫn được chuyển tiếp (so khớp CHÍNH XÁC, sau khi bỏ query). `/internal/*` (callback AB ->
# VH) tuyệt đối không qua đây: proxy chạy cùng máy với VH nên IP nguồn luôn là 127.0.0.1 và vòng chặn IP của
# callback sẽ bị vượt khi chạy `--lan`; chỉ còn `VISIONCARE_CALLBACK_TOKEN` thì quá yếu.
ENV_FILE = os.path.join(ROOT, "..", ".env")
WS_AUTH_PATHS = frozenset({"/v2/observe", "/v2/session"})  # đường WS được tự gắn token (xem docstring đầu file)

ALLOWED_API_PATHS = frozenset({
    "/process", "/v2/turn", "/v2/image", "/v2/session", "/v2/observe", "/v2/live", "/v2/call", "/health",
})


# ---------------------------------------------------------------------------
# Màn hình điện thoại thật (tuỳ chọn --phone-mirror)
# ---------------------------------------------------------------------------

PHONE_STREAM_PATH = "/phone/stream.mjpg"
ADB_DEFAULT = os.path.expanduser("~/android-sdk/platform-tools/adb")
MIRROR_BOUNDARY = "seeviaframe"
_SOI, _EOI = b"\xff\xd8", b"\xff\xd9"


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """True nếu có tiến trình đang nghe ở host:port (chỉ thử kết nối, không gửi gì)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class PhoneMirror:
    """Luồng màn hình điện thoại: `adb exec-out screenrecord` (h264) | ffmpeg -> các khung JPEG.

    Một đường ống dùng chung cho mọi người xem; chạy khi có >= 1 người xem, dừng khi không còn ai. screenrecord tự
    kết thúc sau 180 s nên vòng lặp chạy lại. Chỉ gọi adb khi cổng adb server đang LISTEN (xem docstring đầu file).
    """

    FAILS_BEFORE_GIVING_UP = 3

    def __init__(self, adb: str | None = None, ffmpeg: str | None = None, port: int | None = None, serial: str | None = None):
        self.adb = adb or os.environ.get("SEEVIA_ADB") or ADB_DEFAULT
        self.ffmpeg = ffmpeg or os.environ.get("SEEVIA_FFMPEG") or shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        self.port = int(port or os.environ.get("SEEVIA_ADB_PORT") or 5037)
        self.serial = serial or os.environ.get("SEEVIA_ADB_SERIAL", "")
        self._cond = threading.Condition()
        self._viewers = 0
        self._frame: bytes | None = None
        self._seq = 0
        self._alive = False
        self._thread: threading.Thread | None = None
        self._procs: list[subprocess.Popen] = []
        self.runs = 0  # số lần screenrecord đã khởi chạy (để kiểm thử)

    # --- điều kiện có điện thoại ---
    def available(self) -> bool:
        return os.access(self.adb, os.X_OK) and shutil.which(self.ffmpeg) is not None and port_listening(self.port)

    def adb_cmd(self) -> list[str]:
        cmd = [self.adb, "-H", "127.0.0.1", "-P", str(self.port)]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd + ["exec-out", "screenrecord", "--output-format=h264", "--size", "540x1170", "--bit-rate", "2000000", "-"]

    def ffmpeg_cmd(self) -> list[str]:
        return [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-probesize", "32768", "-analyzeduration", "0", "-flags", "low_delay",
                "-f", "h264", "-i", "-", "-f", "mjpeg", "-q:v", "6", "-r", "10", "-"]

    # --- người xem ---
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def acquire(self) -> bool:
        """Đăng ký một người xem; False nếu không có điện thoại (không đụng tới adb)."""
        if not self.available():
            return False
        with self._cond:
            self._viewers += 1
            if not (self.running and self._alive):
                self._frame, self._seq, self._alive = None, 0, True
                self._thread = threading.Thread(target=self._run, name="phone-mirror", daemon=True)
                self._thread.start()
        return True

    def release(self) -> None:
        with self._cond:
            self._viewers = max(0, self._viewers - 1)
            if self._viewers == 0:
                self._kill()
                self._cond.notify_all()

    def wait_frame(self, last_seq: int, timeout: float) -> tuple[int, bytes] | None:
        """Khung mới hơn `last_seq`; hết `timeout` mà chưa có (màn hình đứng yên) thì trả lại khung cũ để giữ kết nối.
        None = luồng đã chết (adb mất, hết thử lại)."""
        with self._cond:
            self._cond.wait_for(lambda: (self._seq != last_seq and self._frame is not None) or not self._alive, timeout)
            if self._frame is not None and (self._seq != last_seq or self._alive):
                return self._seq, self._frame
            return None

    # --- đường ống ---
    def _kill(self) -> None:
        for proc in self._procs:
            try:
                proc.kill()
            except OSError:
                pass
        self._procs = []

    def _run(self) -> None:
        fails = 0
        me = threading.current_thread()
        try:
            while True:
                with self._cond:
                    if self._viewers == 0:
                        self._alive = False  # cùng khoá với kiểm tra: người xem tới sau sẽ dựng luồng mới
                        break
                if not port_listening(self.port):
                    break  # tunnel adb rớt: KHÔNG gọi adb (nó sẽ tự dựng daemon cục bộ)
                got = self._pump_once()
                fails = 0 if got else fails + 1
                if fails >= self.FAILS_BEFORE_GIVING_UP:
                    break
                time.sleep(0.2)
        finally:
            with self._cond:
                if self._thread is me:
                    self._alive = False
                self._cond.notify_all()

    def _pump_once(self) -> int:
        """Một lần screenrecord (tối đa 180 s). Trả số khung đã nhận."""
        env = dict(os.environ, ANDROID_ADB_SERVER_PORT=str(self.port))
        frames = 0
        with self._cond:
            if self._viewers == 0:
                return 0
            try:
                adb = subprocess.Popen(self.adb_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
                ff = subprocess.Popen(self.ffmpeg_cmd(), stdin=adb.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                return 0
            adb.stdout.close()  # ffmpeg giữ đầu đọc; adb nhận SIGPIPE khi ffmpeg thoát
            self._procs = [adb, ff]
            self.runs += 1
        mine = (adb, ff)
        buf = bytearray()
        try:
            while True:
                chunk = os.read(ff.stdout.fileno(), 65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start = buf.find(_SOI)
                    if start < 0:
                        buf.clear()
                        break
                    end = buf.find(_EOI, start + 2)
                    if end < 0:
                        del buf[:start]
                        break
                    jpeg = bytes(buf[start:end + 2])
                    del buf[:end + 2]
                    frames += 1
                    with self._cond:
                        self._frame, self._seq = jpeg, self._seq + 1
                        self._cond.notify_all()
        except OSError:
            pass
        finally:
            for proc in mine:
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.wait()
            ff.stdout.close()
            with self._cond:
                self._procs = [pr for pr in self._procs if pr not in mine]
        return frames


def read_env_file(path: str = ENV_FILE) -> dict[str, str]:
    """`KEY=VALUE` từng dòng của `.env` (bỏ dòng trống, `#`, dấu nháy bao quanh). Thiếu file thì trả {}."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                out[key.strip()] = value
    except OSError:
        pass
    return out


def read_token_file(path: str) -> str:
    """Dòng đầu (bỏ khoảng trắng) của file token; file không đọc được thì thoát với thông báo (không in token)."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readline().strip()
    except OSError as exc:
        sys.exit(f"--token-file không đọc được ({path}): {exc.strerror}")


def demo_credentials(token: str = "", device: str = "", env_file: str = ENV_FILE,
                     token_file: str = "") -> tuple[str, str]:
    """(token, mã kính) cho trang: `--token` > `--token-file` > biến môi trường > `.env`; mã kính mặc định như `config.py`.

    `--token-file` dành cho token RIÊNG của kính (`~/.config/seevia/<kính>.token`, quyền 600): không phải đưa token qua
    dòng lệnh (lộ trong `ps`) hay `.env`."""
    env = read_env_file(env_file)
    token = token or (read_token_file(token_file) if token_file else "")

    def pick(arg: str, key: str, default: str = "") -> str:
        return arg or os.environ.get(key) or env.get(key) or default

    return pick(token, "VISIONCARE_DEVICE_CLIENT_TOKEN"), pick(device, "VISIONCARE_DEVICE_ID", "glasses-123")


def api_path_allowed(request_path: str) -> bool:
    """`request_path` dạng `/api/<đường dẫn>[?query]`: True nếu đường dẫn đích nằm trong danh sách trắng."""
    return urlsplit(request_path[len(API_PREFIX) - 1:]).path in ALLOWED_API_PATHS

# Header theo từng chặng (RFC 9110 §7.6.1): không được chuyển tiếp nguyên.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


class Handler(SimpleHTTPRequestHandler):
    upstream = None  # urlsplit(...) của server kính, gán trong main()
    device_token = ""  # token tự gắn vào WS của trang (không bao giờ gửi xuống trình duyệt)
    device_id = ""  # mã kính hiện tại: trang lấy ở /config.json
    mirror = None  # PhoneMirror khi bật --phone-mirror

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/config.json":
            return self._send_config()
        if route == PHONE_STREAM_PATH:
            return self._send_phone_stream()
        if self.path.startswith(API_PREFIX):
            if not api_path_allowed(self.path):
                return self.send_error(404)
            if self.headers.get("Upgrade", "").lower() == "websocket":
                return self._proxy_ws()
            return self._proxy()
        super().do_GET()

    def do_POST(self):
        if self.path.startswith(API_PREFIX):
            if not api_path_allowed(self.path):
                return self.send_error(404)
            return self._proxy()
        self.send_error(405)

    def _send_config(self):
        body = json.dumps({"device": self.device_id, "phone_mirror": bool(self.mirror and self.mirror.available())}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_phone_stream(self):
        """MJPEG nhiều phần của màn hình điện thoại. 404 khi không bật --phone-mirror, 503 khi không có điện thoại."""
        mirror = self.mirror
        if mirror is None:
            return self.send_error(404)
        if not mirror.acquire():
            return self.send_error(503, "No phone (adb not connected)")
        try:
            first = mirror.wait_frame(0, 10.0)
            if first is None:
                return self.send_error(503, "Phone sent no video")
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={MIRROR_BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            seq, frame = first
            while True:
                self.wfile.write(
                    f"--{MIRROR_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n".encode()
                    + frame + b"\r\n")
                self.wfile.flush()
                nxt = mirror.wait_frame(seq, 3.0)
                if nxt is None:
                    break
                seq, frame = nxt
        except OSError:
            pass  # người xem đóng tab
        finally:
            mirror.release()

    def _ws_auth_header(self, path: str) -> str | None:
        """Dòng `Authorization` tự gắn cho WS của trang, hoặc None (không có token / đường khác / client tự mang token /
        trang nguồn gốc khác: trang web lạ không được mượn token của server)."""
        token = self.device_token
        if not token or "\r" in token or "\n" in token or urlsplit(path).path not in WS_AUTH_PATHS:
            return None
        if any(k.lower() in ("authorization", "x-device-token") for k in self.headers):
            return None
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return None
        return f"Authorization: Bearer {token}"

    def end_headers(self):
        # Trang dùng module ES: trình duyệt cache cứng thì sửa file xong vẫn
        # chạy bản cũ, và đó là thứ rất khó nhận ra giữa buổi demo.
        if not self.path.startswith(API_PREFIX) and urlsplit(self.path).path != "/config.json":  # config.json tự đặt no-store
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _proxy(self):
        up = self.upstream
        path = self.path[len(API_PREFIX) - 1:]  # "/api/process" -> "/process"
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}

        conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
        # Không đặt timeout: STT + Gemini + TTS có thể mất vài chục giây, và
        # luồng SSE trace mở suốt lượt.
        conn = conn_cls(up.hostname, up.port or (443 if up.scheme == "https" else 80))
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as exc:
            self.send_error(502, f"Không nối được server kính: {exc}")
            conn.close()
            return

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in _HOP_BY_HOP:
                self.send_header(k, v)
        # Không biết độ dài trước (audio đang được tổng hợp) nên đóng kết nối
        # để báo hết thân, thay vì dựng lại chunked encoding.
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                # read1 trả về ngay khi có byte, không đợi đủ cỡ khối: nếu
                # dùng read(n) thì gói audio đầu bị giữ lại chờ gói sau.
                chunk = resp.read1(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # trình duyệt đóng tab giữa chừng
        finally:
            conn.close()

    def _proxy_ws(self):
        """Nối WebSocket của trình duyệt tới server kính bằng cách bơm byte hai chiều.

        Không làm lại bắt tay: chuyển nguyên dòng request và header (chỉ đổi `Host`) để
        server tự trả `101 Switching Protocols`; sau đó mọi byte đi qua như ống dẫn.
        """
        up = self.upstream
        path = self.path[len(API_PREFIX) - 1:]
        try:
            raw = socket.create_connection((up.hostname, up.port or (443 if up.scheme == "https" else 80)), timeout=10)
            if up.scheme == "https":
                raw = ssl.create_default_context().wrap_socket(raw, server_hostname=up.hostname)
            raw.settimeout(None)  # kết nối WS sống lâu: ping của trang giữ nhịp, không đặt hạn đọc
        except OSError as exc:
            self.send_error(502, f"Không nối được server kính: {exc}")
            return

        host = up.hostname + (f":{up.port}" if up.port else "")
        head = [f"GET {path} HTTP/1.1", f"Host: {host}"]
        head += [f"{k}: {v}" for k, v in self.headers.items() if k.lower() != "host"]
        auth = self._ws_auth_header(path)
        if auth:
            head.append(auth)
        raw.sendall(("\r\n".join(head) + "\r\n\r\n").encode("latin-1"))

        client = self.connection

        def pump(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass  # một đầu đóng đột ngột
            finally:
                # Đóng nửa còn lại để thread bên kia thoát khỏi recv().
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        back = threading.Thread(target=pump, args=(raw, client), daemon=True)
        back.start()
        pump(client, raw)
        back.join(timeout=2)
        raw.close()
        self.close_connection = True

    def log_message(self, fmt, *args):
        if not self.path.startswith(API_PREFIX + "health"):  # poll 10 giây/lần, bớt ồn
            super().log_message(fmt, *args)


def lan_ip():
    """IP của máy này trong mạng LAN, để in ra địa chỉ cho máy client mở."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # UDP: không gửi gói nào, chỉ để hệ điều hành chọn card mạng
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def self_signed_cert(ip):
    """Tạo (một lần) chứng chỉ tự ký có SAN cho IP LAN; trả về (cert, key).

    Phải có SAN đúng IP: trình duyệt bỏ qua CN, nên thiếu SAN thì bấm "tiếp
    tục" xong vẫn bị coi là chứng chỉ sai tên. Đổi mạng (IP khác) thì xoá thư
    mục certs/ để dựng lại.
    """
    folder = os.path.join(ROOT, "certs")
    cert, key = os.path.join(folder, "demo.pem"), os.path.join(folder, "demo.key")
    if os.path.exists(cert) and os.path.exists(key):
        with open(os.path.join(folder, "demo.ip")) as f:
            if f.read().strip() == ip:
                return cert, key
    os.makedirs(folder, exist_ok=True)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
             "-keyout", key, "-out", cert, "-subj", "/CN=seevia-demo",
             "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Không tạo được chứng chỉ (cần lệnh openssl): {exc}\n"
                 "Tự cấp bằng --cert/--key, hoặc cài openssl rồi chạy lại.")
    with open(os.path.join(folder, "demo.ip"), "w") as f:
        f.write(ip)
    return cert, key


class TLSThreadingHTTPServer(ThreadingHTTPServer):
    """https mà bắt tay TLS nằm trong luồng của từng kết nối.

    Bọc luôn ổ cắm đang nghe thì bắt tay chạy ngay trong accept() của luồng chính: một client
    nói HTTP thường vào cổng https (gõ nhầm http://) hay kết nối rồi im làm treo cả server.
    """
    tls_context = None
    handshake_timeout = 10

    def finish_request(self, request, client_address):
        request.settimeout(self.handshake_timeout)
        try:
            request = self.tls_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # không phải TLS / treo bắt tay: bỏ kết nối này, server vẫn sống
        request.settimeout(None)
        super().finish_request(request, client_address)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--upstream", default=os.environ.get("GLASSES_SERVER_URL", "http://127.0.0.1:8000"))
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 để máy khác trong mạng truy cập được")
    p.add_argument("--port", type=int, default=None, help="mặc định 8080 (http) hoặc 8443 (https)")
    p.add_argument("--lan", action="store_true", help="cho máy khác trong mạng truy cập: nghe 0.0.0.0 và bật https tự ký")
    p.add_argument("--cert", help="file chứng chỉ PEM, bật https")
    p.add_argument("--key", help="file khoá PEM đi kèm --cert")
    p.add_argument("--token", default="", help="token thiết bị tự gắn vào WS (mặc định: VISIONCARE_DEVICE_CLIENT_TOKEN / .env)")
    p.add_argument("--token-file", default="", help="file chứa token RIÊNG của kính (dòng đầu); thắng biến môi trường/.env, thua --token")
    p.add_argument("--device", default="", help="mã kính hiện tại (mặc định: VISIONCARE_DEVICE_ID / .env)")
    p.add_argument("--phone-mirror", action="store_true",
                   help="ô Điện thoại hiện màn hình thật qua adb (cần cổng adb 127.0.0.1:5037 đang nghe và ffmpeg)")
    args = p.parse_args()

    Handler.device_token, Handler.device_id = demo_credentials(args.token, args.device, token_file=args.token_file)
    if args.phone_mirror:
        Handler.mirror = PhoneMirror()
    Handler.upstream = urlsplit(args.upstream)
    if not Handler.upstream.hostname:
        sys.exit(f"--upstream không hợp lệ: {args.upstream}")

    shown_host = "localhost"
    if args.lan:
        args.host = "0.0.0.0"
        shown_host = lan_ip()
        if not args.cert:
            args.cert, args.key = self_signed_cert(shown_host)
    elif args.host not in ("127.0.0.1", "0.0.0.0"):
        shown_host = args.host
    port = args.port or (8443 if args.cert else 8080)

    scheme = "http"
    if args.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        httpd = TLSThreadingHTTPServer((args.host, port), Handler)
        httpd.tls_context = ctx
        scheme = "https"
    else:
        httpd = ThreadingHTTPServer((args.host, port), Handler)
    print(f"Trang demo : {scheme}://{shown_host}:{port}")
    print(f"Server kính: {args.upstream}  (qua /api/*)")
    print(f"Mã kính    : {Handler.device_id}")
    if Handler.mirror:
        print("Điện thoại : " + (f"gương màn hình qua adb :{Handler.mirror.port} (chỉ chạy khi có người xem)"
                                 if Handler.mirror.available() else f"--phone-mirror bật nhưng chưa thấy adb ở :{Handler.mirror.port}; "
                                 "ô Điện thoại dùng khung mô phỏng, tự thử lại sau"))
    print("Token      : đã đọc sẵn, proxy tự gắn vào WS (không gửi xuống trình duyệt)" if Handler.device_token
          else "Token      : CHƯA có (không thấy VISIONCARE_DEVICE_CLIENT_TOKEN), nhập ở Cài đặt của từng trang")
    if args.lan:
        print("\nTrên máy client: mở địa chỉ trên, trình duyệt sẽ cảnh báo chứng chỉ tự ký —")
        print("bấm 'Nâng cao' rồi 'Tiếp tục truy cập', sau đó cho phép camera/micro.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
