"""Phục vụ trang demo và chuyển tiếp `/api/*` tới server kính.

Cần có file này vì hai lý do:

- `app.py` không bật CORS. Trang mở từ nguồn khác (file://, cổng khác) gọi
  thẳng `/process` là bị trình duyệt chặn. Chuyển tiếp qua cùng một nguồn thì
  trang không cần server sửa gì.
- `getUserMedia` (camera/micro) chỉ chạy trên https hoặc localhost. Phục vụ
  trang ở đây rồi mở bằng http://localhost:8080 là đủ điều kiện.

Chỉ dùng thư viện chuẩn: máy trình bày không cần cài thêm gì.

    python demo-web/serve.py                       # server kính ở 127.0.0.1:8000
    python demo-web/serve.py --upstream http://192.168.1.20:8000

Client là máy khác (laptop BGK, điện thoại) thì chạy trên máy đặt server:

    python demo-web/serve.py --lan

`--lan` mở cổng cho cả mạng và bật https với chứng chỉ tự ký, vì camera/micro
trên trình duyệt từ chối chạy qua http://<địa-chỉ-IP>.
"""
import argparse
import http.client
import os
import socket
import ssl
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
API_PREFIX = "/api/"

# Header theo từng chặng (RFC 9110 §7.6.1): không được chuyển tiếp nguyên.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


class Handler(SimpleHTTPRequestHandler):
    upstream = None  # urlsplit(...) của server kính, gán trong main()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path.startswith(API_PREFIX):
            return self._proxy()
        super().do_GET()

    def do_POST(self):
        if self.path.startswith(API_PREFIX):
            return self._proxy()
        self.send_error(405)

    def end_headers(self):
        # Trang dùng module ES: trình duyệt cache cứng thì sửa file xong vẫn
        # chạy bản cũ, và đó là thứ rất khó nhận ra giữa buổi demo.
        if not self.path.startswith(API_PREFIX):
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


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--upstream", default=os.environ.get("GLASSES_SERVER_URL", "http://127.0.0.1:8000"))
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 để máy khác trong mạng truy cập được")
    p.add_argument("--port", type=int, default=None, help="mặc định 8080 (http) hoặc 8443 (https)")
    p.add_argument("--lan", action="store_true", help="cho máy khác trong mạng truy cập: nghe 0.0.0.0 và bật https tự ký")
    p.add_argument("--cert", help="file chứng chỉ PEM, bật https")
    p.add_argument("--key", help="file khoá PEM đi kèm --cert")
    args = p.parse_args()

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

    httpd = ThreadingHTTPServer((args.host, port), Handler)
    scheme = "http"
    if args.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print(f"Trang demo : {scheme}://{shown_host}:{port}")
    print(f"Server kính: {args.upstream}  (qua /api/*)")
    if args.lan:
        print("\nTrên máy client: mở địa chỉ trên, trình duyệt sẽ cảnh báo chứng chỉ tự ký —")
        print("bấm 'Nâng cao' rồi 'Tiếp tục truy cập', sau đó cho phép camera/micro.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
