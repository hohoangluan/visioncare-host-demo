"""Đo RIÊNG hai chức năng đem đi thi: nút khẩn cấp 3 nhịp, và mở nhạc.

Vì sao có tool riêng thay vì dùng `bench_e2e.py`
------------------------------------------------
`bench_e2e.py` chạy một bảng 16 câu dựng sẵn, mỗi câu một lượt độc lập. Hai
chức năng đem thi thì không vừa cái khuôn đó:

  * **nút 3 nhịp** không gửi audio và không gửi ảnh — thân multipart RỖNG, cả
    lượt nằm trong đúng một header `X-Trigger: emergency`. `run_one()` luôn
    đính kèm một file .wav nên nó đo một đường khác.
  * **mở nhạc** từ 2026-08-27 là một chuỗi HAI lượt: nói đủ tên bài + ca sĩ ->
    server đọc lại và hỏi "đúng không?" -> người dùng đáp "đúng rồi" -> mới
    phát. Đo một lượt lẻ thì ra một nửa con số.

Tool này đo trọn cả chuỗi, và ĐỌC NGƯỢC audio server trả về bằng chính bộ STT
của server — vì "200 OK trong 1.4 giây" không nói được câu đó có ĐÚNG không.
Ba lần trong dự án này một lượt xanh hoá ra là câu "Điện thoại chưa báo lại."

🔴 Chạy QUA TUNNEL, không qua 127.0.0.1 — `127.0.0.1:8000` thiếu TLS và thiếu
Cloudflare, tức là một đường không tồn tại với board thật.

    python tools/bench_demo_two.py --host api.visioncare-host.uk --port 443 \
        --device glasses-01

🔴 `--device` PHẢI là chiếc kính đã ghép đôi. Bỏ trống thì server rơi về hằng
số `VISIONCARE_DEVICE_ID` và host 8001 trả 404 GLASSES_DEVICE_NOT_LINKED —
bảng đo khi đó ghi ~0.3 s cho mọi thứ, nhìn như nhanh, thực ra chưa lần nào
chạm tới điện thoại.

🔴 Nút khẩn cấp GỌI THẬT tới liên hệ khẩn cấp trong app. Mặc định tool BỎ QUA
nó; thêm `--panic` khi bạn thực sự muốn bắn.
"""

from __future__ import annotations

import argparse
import glob
import os
import socket
import ssl
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# stdout Windows là cp1252 và mọi dòng in ở đây có tiếng Việt — thiếu ba dòng
# này thì tool chạy XONG việc rồi chết ở lệnh print cuối.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from pipeline import adpcm, stt, tts  # noqa: E402
from tools.bench_e2e import (  # noqa: E402
    BOARD_ACCEPT, BOUNDARY, FIXTURES, run_one,
)
from tools.make_board_audio import OUT_DIR  # noqa: E402

# Câu dùng cho phần nhạc. Nói ĐỦ tên bài + ca sĩ ngay câu đầu — đó là ca bắt
# server phải đọc lại để chốt, và cũng là ca STT dễ nghe nhầm nhất.
SAY_MUSIC = "Phát bài Nơi này có anh của Sơn Tùng MTP."
SAY_YES = "Đúng rồi."

STORAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage")


def _make_clip(name: str, text: str) -> str:
    """Dựng một file WAV IMA ADPCM y như board gửi lên, từ `text`."""
    path = os.path.join(OUT_DIR, f"{name}.wav")
    os.makedirs(OUT_DIR, exist_ok=True)
    pcm = b"".join(tts.synthesize_stream(text))
    blocks = adpcm.encode_blocks(pcm)
    wav = adpcm.wav_header(len(blocks), sample_count=len(pcm) // 2) + blocks
    with open(path, "wb") as f:
        f.write(wav)
    return path


def _newest_response() -> str | None:
    files = glob.glob(os.path.join(STORAGE, "response*.wav"))
    return max(files, key=os.path.getmtime) if files else None


def _heard(before: str | None) -> str:
    """Đọc ngược câu server vừa nói. `before` là file mới nhất TRƯỚC lượt này."""
    now = _newest_response()
    if not now or now == before:
        return "(server không ghi lại audio — bật STORAGE_DIR?)"
    try:
        with open(now, "rb") as f:
            return stt.transcribe(f.read())
    except Exception as exc:  # noqa: BLE001
        return f"(không đọc lại được: {type(exc).__name__}: {exc})"


def _panic_turn(host: str, port: int, device: str, timeout: float = 60.0) -> dict:
    """Đúng gói firmware gửi sau nhịp thứ ba: thân multipart RỖNG.

    Không dùng `run_one()` được vì nó luôn đính kèm ảnh + audio. Ở đây phải
    đóng gói đúng phép (boundary kết + `0\\r\\n\\r\\n`) — thiếu một trong hai
    thì uvicorn ngồi đợi tới timeout rồi trả 400, nhìn từ ngoài giống hệt
    "nút không ăn".
    """
    body = f"--{BOUNDARY}--\r\n".encode()
    head = (
        f"POST /process HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"User-Agent: ESP32S3-VisionCare/1.0\r\n"
        f"Accept: {BOARD_ACCEPT}\r\n"
        f"X-Device-Id: {device}\r\n"
        f"X-Turn-Id: {uuid.uuid4().hex}\r\n"
        f"X-Trigger: emergency\r\n"
        f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()

    t0 = time.perf_counter()
    sock = socket.create_connection((host, port), timeout=timeout)
    if port == 443:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    sock.sendall(head + body)

    buf = b""
    t_head = t_first_audio = None
    header_done = False
    audio_bytes = 0
    while True:
        try:
            chunk = sock.recv(65536)
        except (TimeoutError, socket.timeout):
            break
        if not chunk:
            break
        if t_head is None:
            t_head = time.perf_counter() - t0
        buf += chunk
        if not header_done and b"\r\n\r\n" in buf:
            header_done = True
            body_part = buf.split(b"\r\n\r\n", 1)[1]
            if body_part:
                audio_bytes += len(body_part)
                # Bỏ 60 byte header WAV ra — byte AUDIO đầu mới là thứ nghe được.
                if audio_bytes > adpcm.WAV_HEADER_BYTES and t_first_audio is None:
                    t_first_audio = time.perf_counter() - t0
        elif header_done:
            audio_bytes += len(chunk)
            if audio_bytes > adpcm.WAV_HEADER_BYTES and t_first_audio is None:
                t_first_audio = time.perf_counter() - t0
    sock.close()
    total = time.perf_counter() - t0
    status = 0
    if b" " in buf[:32]:
        try:
            status = int(buf.split(b" ", 2)[1])
        except (ValueError, IndexError):
            status = 0
    return {
        "status": status,
        "headers": t_head or 0.0,
        "first_audio": t_first_audio or 0.0,
        "total": total,
        "audio_seconds": max(0, audio_bytes - adpcm.WAV_HEADER_BYTES) / adpcm.BYTE_RATE,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="api.visioncare-host.uk")
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--device", default="glasses-01")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--gap", type=float, default=3.0)
    ap.add_argument("--panic", action="store_true",
                    help="BẮN THẬT nút khẩn cấp — điện thoại sẽ gọi liên hệ "
                         "khẩn cấp đã cài. Bỏ cờ này thì chỉ đo phần nhạc.")
    args = ap.parse_args()

    print("Đang dựng hai đoạn tiếng bằng chính bộ TTS của server...", flush=True)
    tts._load_tts()
    stt._load_asr()
    _make_clip("demo_music", SAY_MUSIC)
    _make_clip("demo_yes", SAY_YES)
    print(f"  demo_music : {SAY_MUSIC!r}")
    print(f"  demo_yes   : {SAY_YES!r}\n")

    rows = []

    # ── MỞ NHẠC: hai lượt nối nhau, cùng device nên pending đi theo ──────────
    for i in range(args.repeat):
        if i:
            time.sleep(args.gap)
        before = _newest_response()
        r1 = run_one(args.host, args.port, "demo_music",
                     device_id=args.device, turn_id=uuid.uuid4().hex)
        heard1 = _heard(before)
        rows.append(("mở nhạc · lượt 1 (nói đủ bài + ca sĩ)", r1, heard1))

        time.sleep(1.0)
        before = _newest_response()
        r2 = run_one(args.host, args.port, "demo_yes",
                     device_id=args.device, turn_id=uuid.uuid4().hex)
        heard2 = _heard(before)
        rows.append(("mở nhạc · lượt 2 (đáp \"đúng rồi\")", r2, heard2))

    # ── NÚT 3 NHỊP ───────────────────────────────────────────────────────────
    if args.panic:
        for i in range(args.repeat):
            time.sleep(args.gap)
            before = _newest_response()
            p = _panic_turn(args.host, args.port, args.device)
            heard = _heard(before)
            rows.append(("nút 3 nhịp (thân RỖNG)", p, heard))
    else:
        print("⚠ Bỏ qua nút khẩn cấp — thêm --panic để bắn thật "
              "(điện thoại sẽ gọi liên hệ khẩn cấp).\n")

    print(f"{'chức năng':<40} {'mã':>4} {'headers':>8} {'tiếng đầu':>10} "
          f"{'tổng':>8} {'audio':>7}")
    print("-" * 88)
    for name, r, _heard_text in rows:
        get = (lambda k: r[k]) if isinstance(r, dict) else (lambda k: getattr(r, _MAP[k]))
        print(f"{name:<40} {get('status'):>4} {get('headers'):>7.2f}s "
              f"{get('first_audio'):>9.2f}s {get('total'):>7.2f}s "
              f"{get('audio_seconds'):>6.2f}s")

    print("\nServer NÓI GÌ (đọc ngược bằng chính STT của server):")
    for name, _r, heard in rows:
        print(f"  {name:<40} {heard!r}")


# `run_one()` trả về object có __slots__, `_panic_turn()` trả dict — một bảng
# tên để in chung một bảng mà không phải viết hai nhánh in.
_MAP = {
    "status": "status",
    "headers": "t_headers",
    "first_audio": "t_first_audio",
    "total": "t_total",
    "audio_seconds": "audio_seconds",
}


if __name__ == "__main__":
    main()
