"""Giả lập kính gọi server v2 thật, in từng mốc thời gian (§14).

Mỗi câu lệnh: POST /v2/image lúc "bấm nút", rồi POST /v2/turn đẩy ADPCM theo
nhịp thời gian thực (như kính đang thu), đo từ lúc "nhả nút" (gửi xong khối
cuối) tới header, tới byte audio đầu. Câu `nav` còn mở WS và đo khung -> hazard.

Audio câu lệnh đọc bằng chính VieNeu-TTS rồi nén ADPCM (cache ở --cache).

    python tools/bench_live.py --base http://127.0.0.1:8000
    python tools/bench_live.py --base https://app.visioncare-host.uk --runs 3
    python tools/bench_live.py --base http://127.0.0.1:8000 --ws   # cùng luồng, qua WS /v2/session
"""

import argparse
import asyncio
import io
import json
import os
import statistics
import sys
import time

import httpx
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

COMMANDS = {
    "chat": "Kể cho tôi một câu chuyện cười ngắn.",
    "space": "Trước mặt tôi có gì vậy?",
    "ocr": "Đọc giúp tôi trang sách này.",
    "money": "Tờ tiền này là bao nhiêu?",
    "alert": "Bật cảnh báo vật cản.",
    "contact": "Gọi cho mẹ.",
}
BYTE_RATE = 8110.9  # ADPCM 16 kHz
CHUNK = 512
WAV_HEADER = 60


def _command_audio(name: str, text: str, cache: str, tail_s: float = 0.25) -> bytes:
    path = os.path.join(cache, f"{name}.adpcm" if tail_s == 0.25 else f"{name}_t{tail_s}.adpcm")
    if os.path.exists(path):
        return open(path, "rb").read()
    from pipeline import adpcm, tts

    pcm = b"".join(tts.synthesize_stream(text))
    silence = b"\x00\x00" * 4000  # 0,25 s im lặng hai đầu như người bấm nút
    tail = b"\x00\x00" * int(16000 * tail_s)  # --tail-s: giữ nút lâu sau khi nói xong (đo chốt sớm VAD)
    data = adpcm.encode_blocks(silence + pcm + tail)
    os.makedirs(cache, exist_ok=True)
    open(path, "wb").write(data)
    return data


def _text_image(w=1600, h=1200) -> bytes:
    import cv2

    img = np.full((h, w, 3), 245, np.uint8)
    lines = ["CHUONG 1. HANH TRINH", "Sang hom ay troi trong xanh, gio nhe thoi qua",
             "con duong dat do dan ve phia ngoi lang nho.", "Moi nguoi deu da thuc day tu rat som."]
    for i, line in enumerate(lines):
        cv2.putText(img, line, (160, 420 + i * 110), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 4)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _auth() -> dict:
    """Token kính lấy từ biến môi trường (không bao giờ ghi vào code/log)."""
    token = os.environ.get("VISIONCARE_DEVICE_CLIENT_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def one_turn(http: httpx.AsyncClient, base: str, name: str, audio: bytes, image: bytes) -> dict:
    turn = str(int(time.time() * 1000) % 10_000_000)
    headers = {"X-Device-Id": "bench-glasses", **_auth(), "X-Turn-Id": turn, "X-Cue-Version": "2",
               "Accept": "audio/wav;codec=ima_adpcm"}
    marks: dict[str, float] = {}

    async def body():
        start = time.perf_counter()
        for i in range(0, len(audio), CHUNK):
            target = start + i / BYTE_RATE
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            yield audio[i:i + CHUNK]
        marks["release"] = time.perf_counter()

    pressed = time.perf_counter()
    image_task = asyncio.create_task(http.post(f"{base}/v2/image", content=image,
                                               headers={**headers, "Content-Type": "image/jpeg"}))
    async with http.stream("POST", f"{base}/v2/turn", content=body(), headers={
        **headers, "Content-Type": "audio/x-adpcm-ima; rate=16000; channels=1; block=256",
    }) as resp:
        marks["headers"] = time.perf_counter()
        got = 0
        arrivals: list[tuple[float, int]] = []  # (lúc tới, số byte audio luỹ kế)
        async for chunk in resp.aiter_raw():
            got += len(chunk)
            if got > WAV_HEADER:
                arrivals.append((time.perf_counter(), got - WAV_HEADER))
            if got > WAV_HEADER and "first_audio" not in marks:
                marks["first_audio"] = time.perf_counter()
        marks["done"] = time.perf_counter()
        info = {k: resp.headers.get(k) for k in ("x-cue", "x-live", "x-live-token")}
    image_ms = (await image_task).elapsed.total_seconds() * 1000
    rel = marks["release"]
    return {
        "name": name, "audio_s": len(audio) / BYTE_RATE, "image_ms": image_ms,
        "headers_ms": (marks["headers"] - rel) * 1000,
        "first_audio_ms": (marks["first_audio"] - rel) * 1000 if "first_audio" in marks else None,
        "total_ms": (marks["done"] - rel) * 1000, "bytes": got, "pressed_to_release_s": rel - pressed,
        "starve_ms": _starvation_ms(arrivals),
        **info,
    }


async def one_turn_ws(ws, name: str, audio: bytes, image: bytes) -> dict:
    """Cùng một lượt như `one_turn`, nhưng trên socket phiên: cột kết quả giống hệt.

    `headers_ms` ở đây là lúc khung `reply` (cue/live) tới; `first_audio_ms` là khối 0x02 đầu.
    """
    turn = str(int(time.time() * 1000) % 10_000_000)
    marks: dict[str, float] = {}
    pressed = time.perf_counter()
    await ws.send(json.dumps({"t": "turn_start", "turn": turn, "t_press_ms": 0}))
    await ws.send(b"\x01" + image)

    async def sender():
        start = time.perf_counter()
        for i in range(0, len(audio), CHUNK):
            target = start + i / BYTE_RATE
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            await ws.send(b"\x03" + audio[i:i + CHUNK])
        marks["release"] = time.perf_counter()
        await ws.send(json.dumps({"t": "turn_end", "turn": turn, "t_release_ms": 0}))

    send_task = asyncio.create_task(sender())
    got, arrivals, info = 0, [], {"x-cue": None, "x-live": None, "x-live-token": None}
    while True:
        msg = await ws.recv()
        now = time.perf_counter()
        if isinstance(msg, bytes):
            got += len(msg) - 1
            arrivals.append((now, got))
            marks.setdefault("first_audio", now)
            continue
        frame = json.loads(msg)
        if frame["t"] == "reply" and frame["turn"] == turn:
            marks["headers"] = now
            info["x-cue"] = ",".join(frame["cues"]) or None
            info["x-live"] = frame["live"]
        elif frame["t"] == "reply_end" and frame["turn"] == turn:
            marks["done"] = now
            break
    await send_task
    rel = marks["release"]
    return {
        "name": name, "audio_s": len(audio) / BYTE_RATE, "image_ms": 0.0,
        "headers_ms": (marks["headers"] - rel) * 1000,
        "first_audio_ms": (marks["first_audio"] - rel) * 1000 if "first_audio" in marks else None,
        "total_ms": (marks["done"] - rel) * 1000, "bytes": got, "pressed_to_release_s": rel - pressed,
        "starve_ms": _starvation_ms(arrivals), **info,
    }


def _starvation_ms(arrivals: list[tuple[float, int]]) -> float:
    """Loa phát ngay khi có byte đầu: tổng số ms bị đứt tiếng vì dữ liệu tới trễ.

    Đây chính là phần đệm phía server còn THIẾU: 0 nghĩa là đệm preroll hiện tại
    đã đủ, > 0 nghĩa là cần đệm thêm ngần ấy để không bị ngắt giữa câu.
    """
    if not arrivals:
        return 0.0
    start = arrivals[0][0]
    worst, previous = 0.0, arrivals[0][1]
    for at, cumulative in arrivals[1:]:
        # Mảnh này phải tới trước lúc loa phát hết mọi byte đã có trước nó.
        needed_at = start + previous / BYTE_RATE
        worst = max(worst, at - needed_at)
        previous = cumulative
    return worst * 1000


async def nav_rtt(base: str, token: str, frame: bytes, frames: int = 40) -> dict:
    import websockets

    url = base.replace("http", "ws", 1) + f"/v2/live?token={token}"
    rtts, sent_at = [], {}
    async with websockets.connect(url, max_size=None, additional_headers=_auth()) as ws:
        await ws.send(json.dumps({"t": "hello", "device": "bench-glasses", "cue_version": 2}))
        print("  WS:", await ws.recv())

        async def reader():
            async for msg in ws:
                if isinstance(msg, str) and '"hazard"' in msg and sent_at:
                    rtts.append((time.perf_counter() - sent_at["t"]) * 1000)

        task = asyncio.create_task(reader())
        for i in range(frames):
            sent_at["t"] = time.perf_counter()
            await ws.send(b"\x01" + frame)
            await asyncio.sleep(0.125)  # 8 fps
        await asyncio.sleep(0.5)
        task.cancel()
    return {"hazard_msgs": len(rtts), "frame_to_hazard_ms": rtts}


def _qvga(jpeg: bytes) -> bytes:
    import cv2

    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    img = cv2.resize(img, (320, 240))
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def _pin_dns(host: str, ip: str) -> None:
    """Ép `host` về `ip` cho httpx và websockets (cùng đi qua socket.getaddrinfo); SNI/Host giữ nguyên."""
    import socket

    real = socket.getaddrinfo

    def patched(name, *a, **k):
        # anyio/httpcore truyền hostname dạng bytes (đã mã hoá idna), websockets thì str.
        text = name.decode("ascii", "ignore") if isinstance(name, bytes) else name
        return real(ip if text == host else name, *a, **k)

    socket.getaddrinfo = patched


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--tail-s", type=float, default=0.25, help="im lặng cuối trước khi nhả nút")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--cache", default=os.path.join(ROOT, "tools", "board_audio", "v2"))
    parser.add_argument("--street", help="ảnh đường phố có xe cho đo làn C")
    parser.add_argument("--ws", action="store_true", help="đo qua WS /v2/session thay vì POST")
    parser.add_argument("--resolve", help="host=ip: bỏ qua DNS (như curl --resolve), khi resolver còn cache NXDOMAIN")
    args = parser.parse_args()
    if args.resolve:
        _pin_dns(*args.resolve.split("=", 1))

    text_image = _text_image()
    # `space`/`money` cần ảnh cảnh vật: trang giấy trắng bị chặn vì "ảnh quá sáng".
    scene = open(args.street, "rb").read() if args.street else text_image
    ws = None
    if args.ws:
        import websockets

        ws = await websockets.connect(args.base.replace("http", "ws", 1) + "/v2/session", max_size=None)
        await ws.send(json.dumps({"t": "hello", "device": "bench-glasses", "cue_version": 2, "fw": "bench",
                                  "accept": "audio/wav;codec=ima_adpcm",
                                  "token": os.environ.get("VISIONCARE_DEVICE_CLIENT_TOKEN", "")}))
        print("  WS:", await ws.recv())
    async with httpx.AsyncClient(timeout=60, http2=False) as http:
        results = []
        for name, text in COMMANDS.items():
            if args.only and name not in args.only:
                continue
            audio = _command_audio(name, text, args.cache, args.tail_s)
            for run in range(args.runs):
                image = text_image if name == "ocr" else scene
                r = await (one_turn_ws(ws, name, audio, image) if ws else one_turn(http, args.base, name, audio, image))
                results.append(r)
                fa = f"{r['first_audio_ms']:.0f}" if r["first_audio_ms"] is not None else "-"
                print(f"{name:8s} run{run} headers={r['headers_ms']:.0f}ms first_audio={fa}ms "
                      f"total={r['total_ms']:.0f}ms image={r['image_ms']:.0f}ms starve={r['starve_ms']:.0f}ms "
                      f"cue={r['x-cue']} live={r['x-live']}")
                if name == "alert" and ws and r["x-live"] == "nav" and args.street:
                    street = _qvga(open(args.street, "rb").read())
                    sent, rtts = {}, []
                    for _ in range(40):
                        sent["t"] = time.perf_counter()
                        await ws.send(b"\x04" + street)
                        try:
                            while True:
                                m = await asyncio.wait_for(ws.recv(), 0.125)
                                if isinstance(m, str) and '"hazard"' in m:
                                    rtts.append((time.perf_counter() - sent["t"]) * 1000)
                        except asyncio.TimeoutError:
                            pass
                    print(f"  nav(ws): {len(rtts)} hazard, median "
                          f"{statistics.median(rtts) if rtts else 0:.0f}ms")
                elif name == "alert" and r["x-live-token"] and args.street:
                    street = _qvga(open(args.street, "rb").read())
                    rtt = await nav_rtt(args.base, r["x-live-token"], street)
                    vals = rtt["frame_to_hazard_ms"]
                    if vals:
                        print(f"  nav: {len(vals)} hazard, frame->hazard median "
                              f"{statistics.median(vals):.0f}ms max {max(vals):.0f}ms")
                    else:
                        print("  nav: không có hazard nào (anti-annoy / ảnh không có vật)")
                await asyncio.sleep(0.5)
    if ws:
        await ws.close()
    print(json.dumps(results, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    asyncio.run(main())
