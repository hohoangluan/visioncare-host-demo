"""Đo tốc độ end-to-end của /process, mô phỏng đúng cách board ESP32 gọi lên.

Dựng gói multipart y như firmware (`HUONG_DAN_SERVER.md` §1), gửi qua socket
trần rồi đóng dấu thời gian từng mảnh nhận về. Đo qua `requests`/`httpx` không
được: chúng gom body nên che mất chính thứ cần đo.

Bốn mốc, theo đúng đồng hồ board đếm:

    headers   HTTP/1.1 200 OK + headers  (trần 90 s, Cloudflare cắt ở 100 s)
    byte đầu  byte đầu tiên của thân     (trần 180 s tính từ lúc gửi xong)
    tiếng đầu byte AUDIO đầu tiên        — bỏ 60 byte header WAV ra
    tổng      mảnh cuối

Và con số quyết định người dùng nghe sớm hay muộn:

    tỉ lệ nhả = số giây tiếng nhận được / số giây đồng hồ tính từ byte đầu

Board đệm 400 ms rồi phát ngay nếu ≥ 1.30x; dưới 1.12x mà không biết tổng độ
dài thì nó đợi nhận xong hết mới phát.

Chạy:  python tools/bench_e2e.py [--host 127.0.0.1] [--port 8000] [--only ocr,chat]
"""

import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import adpcm  # noqa: E402
from tools.make_board_audio import COMMANDS, OUT_DIR  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

# Ảnh hợp cảnh cho từng intent. Board luôn kèm ảnh nên intent không dùng ảnh
# cũng gửi một tấm — giữ nguyên như vậy để đo đúng chi phí truyền/đọc file.
#
# `ocr_screenshot.png` KHÔNG dùng được: nó là ảnh chụp màn hình nền trắng nên
# `pipeline/image_quality.py` chặn ở mức "Ảnh quá sáng" trước khi handler chạy —
# đo ra 0.2s mà tưởng là tốc độ OCR. Bao bì gói bánh có chữ thật nên hợp hơn.
IMAGES = {
    "ocr": "find_snack.jpg",
    "find": "find_snack.jpg",
    "money": "money_notes.jpg",
}
_DEFAULT_IMAGE = "space_room.jpg"

BOUNDARY = "----ESP32VisionCareBoundary7d91"
BOARD_ACCEPT = "audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav"


def _multipart(image: bytes, image_name: str, audio: bytes) -> bytes:
    sep = f"--{BOUNDARY}\r\n".encode()
    image_type = "image/png" if image_name.endswith(".png") else "image/jpeg"
    return b"".join((
        sep,
        f'Content-Disposition: form-data; name="image"; filename="capture.jpg"\r\n'
        f"Content-Type: {image_type}\r\n\r\n".encode(),
        image, b"\r\n",
        sep,
        b'Content-Disposition: form-data; name="audio"; filename="record.wav"\r\n'
        b"Content-Type: audio/wav\r\n\r\n",
        audio, b"\r\n",
        f"--{BOUNDARY}--\r\n".encode(),
    ))


class Result:
    __slots__ = (
        "name", "t_headers", "t_first_byte", "t_first_audio", "t_total",
        "body_bytes", "audio_seconds", "status", "encoding", "error",
    )


def _byte_rate(encoding: str) -> float:
    if encoding == "ima_adpcm":
        return adpcm.BYTE_RATE
    if encoding == "mp3":
        return 32 * 1000 / 8
    return 16000 * 2


def run_one(
    host: str, port: int, name: str, timeout: float = 200.0, accept: str = BOARD_ACCEPT
) -> Result:
    audio = open(os.path.join(OUT_DIR, f"{name}.wav"), "rb").read()
    image_name = IMAGES.get(name, _DEFAULT_IMAGE)
    image = open(os.path.join(FIXTURES, image_name), "rb").read()
    body = _multipart(image, image_name, audio)

    request = (
        f"POST /process HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"User-Agent: ESP32S3-VisionCare/1.0\r\n"
        f"Accept: {accept}\r\n"
        f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()

    res = Result()
    res.name = name
    res.error = None
    res.t_headers = res.t_first_byte = res.t_first_audio = res.t_total = 0.0
    res.body_bytes = 0
    res.audio_seconds = 0.0
    res.status = 0
    res.encoding = "?"

    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        # Đồng hồ bắt đầu khi gửi xong, giống board: nó đo từ lúc đẩy hết gói.
        sock.sendall(request + body)
        started = time.monotonic()

        buf = b""
        while b"\r\n\r\n" not in buf:
            part = sock.recv(65536)
            if not part:
                res.error = "đóng kết nối trước khi trả headers"
                return res
            buf += part
        res.t_headers = time.monotonic() - started

        head, rest = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        res.status = int(lines[0].split()[1])
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        res.encoding = headers.get("x-audio-encoding", "?")
        chunked = headers.get("transfer-encoding", "").lower() == "chunked"

        received = bytearray(_dechunk(rest) if chunked else rest)
        now = time.monotonic()
        # (số byte đã nhận, thời điểm) — để tìm lại lúc byte AUDIO đầu tiên tới,
        # sau khi đọc header mới biết phải bỏ qua bao nhiêu byte đầu.
        marks: list[tuple[int, float]] = []
        if received:
            res.t_first_byte = now - started
            marks.append((len(received), res.t_first_byte))

        while True:
            part = sock.recv(65536)
            if not part:
                break
            now = time.monotonic() - started
            if not res.t_first_byte:
                res.t_first_byte = now
            received += _dechunk(part) if chunked else part
            marks.append((len(received), now))
            res.t_total = now

        rate = _byte_rate(res.encoding)
        payload = bytes(received)
        # 60 byte header WAV không phải audio. Board nhận header xong vẫn chưa
        # có gì để phát, nên tách riêng hai mốc: header ra sớm là đúng hợp đồng,
        # nhưng thứ người dùng nghe được lại đếm từ byte audio đầu tiên.
        offset = adpcm.WAV_HEADER_BYTES if payload[:4] == b"RIFF" else 0
        res.t_first_audio = next(
            (t for total, t in marks if total > offset), res.t_first_byte
        )
        res.body_bytes = len(payload)
        res.audio_seconds = max(len(payload) - offset, 0) / rate
    finally:
        sock.close()
    return res


def _dechunk(data: bytes) -> bytes:
    """Bóc khung chunked. Đủ dùng cho đo đạc: server không gửi trailer."""
    out = bytearray()
    while data:
        end = data.find(b"\r\n")
        if end == -1:
            break
        try:
            size = int(data[:end].split(b";")[0], 16)
        except ValueError:
            # Mảnh cắt giữa chừng khung: gom nguyên xi, sai lệch vài byte không
            # đổi kết luận về thời gian.
            return bytes(data)
        if size == 0:
            break
        out += data[end + 2: end + 2 + size]
        data = data[end + 2 + size + 2:]
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--only", default="")
    ap.add_argument("--repeat", type=int, default=1,
                    help="số lượt mỗi chức năng; >1 thì lấy lượt có `tổng` trung vị")
    # Gemini free tier chặn theo số request MỖI PHÚT. Bắn liên tục là từ lượt
    # thứ ~40 trở đi mọi câu trả về 429, bước phân loại rơi xuống `unknown` và
    # bảng đo ghi 0.2s cho mọi chức năng — nhìn như server nhanh lên, thực ra là
    # nó không còn làm gì nữa. Giãn ra thì đo đúng đường chạy thật.
    ap.add_argument("--gap", type=float, default=6.0,
                    help="số giây nghỉ giữa hai lượt, tránh 429 của Gemini")
    ap.add_argument("--accept", default=BOARD_ACCEPT,
                    help="header Accept gửi lên; đổi để đo định dạng khác "
                         "(vd. 'audio/mpeg' ra MP3, 'audio/wav' ra WAV PCM)")
    args = ap.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(COMMANDS)

    results = []
    for name in names:
        print(f"... {name}", flush=True)
        runs = []
        for attempt in range(args.repeat):
            if results or attempt:
                time.sleep(args.gap)
            try:
                runs.append(run_one(args.host, args.port, name, accept=args.accept))
            except Exception as exc:  # noqa: BLE001
                res = Result()
                res.name = name
                res.error = f"{type(exc).__name__}: {exc}"
                res.t_headers = res.t_first_byte = res.t_first_audio = res.t_total = 0.0
                res.body_bytes = 0
                res.audio_seconds = 0.0
                res.status = 0
                res.encoding = "?"
                runs.append(res)
        # Lấy lượt TRUNG VỊ chứ không phải nhanh nhất: Gemini dao động 2.7s tới
        # 12.3s trong cùng một buổi, nên lượt nhanh nhất là con số không lặp lại
        # được. Trung vị mới là thứ người dùng gặp.
        runs.sort(key=lambda r: r.t_total)
        results.append(runs[len(runs) // 2])

    print()
    header = (
        f"{'chức năng':<16} {'mã':>4} {'headers':>8} {'tiếng đầu':>10} "
        f"{'tổng':>7} {'audio':>7} {'KB':>7} {'nhả':>7} {'đệm board':>10} {'mã hoá':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        if r.error:
            print(f"{r.name:<16} {'LỖI':>4}  {r.error}")
            continue
        print(
            f"{r.name:<16} {r.status:>4} {r.t_headers:>7.2f}s {r.t_first_audio:>9.2f}s "
            f"{r.t_total:>6.2f}s {r.audio_seconds:>6.2f}s {r.body_bytes/1024:>7.1f} "
            f"{_ratio(r):>6.2f}x {_board_wait(_ratio(r)):>10} {r.encoding:>10}"
        )

    ok = [r for r in results if not r.error and r.status == 200]
    if ok:
        print()
        for label, values in (
            ("headers", [r.t_headers for r in ok]),
            ("tiếng đầu", [r.t_first_audio for r in ok]),
            ("tổng", [r.t_total for r in ok]),
        ):
            print(f"{label:>10}: trung vị {_median(values):5.2f}s   "
                  f"chậm nhất {max(values):5.2f}s")
        worst = min(ok, key=_ratio)
        print(f"{'nhả':>10}: thấp nhất {_ratio(worst):.2f}x ({worst.name})")


def _ratio(r: Result) -> float:
    """Tỉ lệ nhả, đúng phép chia board làm.

    Giây tiếng nhận được / giây đồng hồ kể từ BYTE ĐẦU TIÊN — kể cả byte đó là
    header chứ chưa phải tiếng. Board bắt đầu đếm từ đó (`HUONG_DAN_SERVER.md`
    §3), nên đo từ byte audio đầu tiên là tự cho mình điểm cao hơn thực tế.
    """
    window = max(r.t_total - r.t_first_byte, 1e-6)
    return r.audio_seconds / window


def _board_wait(ratio: float) -> str:
    """Board sẽ đệm bao lâu trước khi phát, ứng với tỉ lệ đó."""
    if ratio >= 1.30:
        return "400ms"
    if ratio >= 1.12:
        return "1500ms"
    return "chờ hết!"


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


if __name__ == "__main__":
    main()
