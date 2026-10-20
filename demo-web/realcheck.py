"""Chạy các WAV tiếng Việt qua proxy của serve.py tới server kính THẬT và in khung debug nhận được.

Như trang demo: nối `/api/v2/session` (hoặc thẳng `/v2/session` bằng --direct), hello có `debug:true`,
mỗi lượt gửi ảnh 0x01 + header WAV stream (size 0xFFFFFFFF) + khối PCM ~100 ms đúng nhịp thật, rồi `turn_end`.
Token đọc từ VISIONCARE_DEVICE_CLIENT_TOKEN hoặc --token (không in ra).

    ~/.venvs/seevia/bin/python demo-web/realcheck.py --url http://127.0.0.1:8080 \
        --wav qa.wav alert_on.wav --image street.jpg
"""
import argparse
import asyncio
import json
import os
import struct
import sys
import time
import wave

from websockets.asyncio.client import connect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

CHUNK_S = 0.1


def stream_header() -> bytes:
    """Header WAV PCM16 16 kHz mono, kích thước 0xFFFFFFFF như trang demo (`wav.js`)."""
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", 0xFFFFFFFF))


def read_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2), path
        return w.readframes(w.getnframes())


class Session:
    def __init__(self, ws):
        self.ws = ws
        self.frames: list[dict] = []   # khung JSON theo thứ tự tới, kèm "_at" (giây từ lúc mở)
        self.audio = bytearray()
        self.t0 = time.monotonic()
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for msg in self.ws:
                if isinstance(msg, bytes):
                    self.audio.extend(msg[1:])
                else:
                    f = json.loads(msg)
                    f["_at"] = round(time.monotonic() - self.t0, 2)
                    self.frames.append(f)
        except Exception:  # noqa: BLE001
            pass

    def of(self, t, since=0):
        return [f for f in self.frames[since:] if f["t"] == t]

    async def wait(self, pred, timeout, since=0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for f in self.frames[since:]:
                if pred(f):
                    return f
            await asyncio.sleep(0.05)
        return None

    async def turn(self, tid, wav, image=None, timeout=60, settle=0.3):
        since = len(self.frames)
        await self.ws.send(json.dumps({"t": "turn_start", "turn": tid, "t_press_ms": 0}))
        if image:
            await self.ws.send(b"\x01" + image)
        pcm = read_pcm(wav)
        step = int(CHUNK_S * 32000)
        first = True
        start = time.monotonic()
        for i in range(0, len(pcm), step):
            await asyncio.sleep(max(0.0, start + i / 32000 - time.monotonic()))
            await self.ws.send(b"\x03" + (stream_header() if first else b"") + pcm[i:i + step])
            first = False
        await self.ws.send(json.dumps({"t": "turn_end", "turn": tid, "t_release_ms": 0}))
        end = await self.wait(lambda f: f["t"] == "reply_end" and f.get("turn") == tid, timeout, since)
        await asyncio.sleep(settle)  # chờ thêm khung tới muộn (result-*, live)
        return since, end


async def open_session(url, token, device="demo-web"):
    ws = await connect(url, max_size=2_100_000)
    await ws.send(json.dumps({"t": "hello", "device": device, "token": token, "debug": True,
                              "cue_version": 0, "fw": "realcheck", "accept": "ima_adpcm"}))
    s = Session(ws)
    ok = await s.wait(lambda f: f["t"] == "hello_ok", 15)
    assert ok and ok.get("debug") is True, f"hello_ok: {ok}"
    return s


def show(s, since):
    for f in s.frames[since:]:
        g = {k: v for k, v in f.items() if k != "audio"}
        print("  ", json.dumps(g, ensure_ascii=False)[:420])


async def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080", help="serve.py (hoặc server kính nếu có --direct)")
    ap.add_argument("--direct", action="store_true", help="nối thẳng /v2/session, không qua proxy /api")
    ap.add_argument("--token", default=None)
    ap.add_argument("--device", default="demo-web", help="id thiết bị trong hello (trạng thái server tính theo id này)")
    ap.add_argument("--wav", nargs="+", required=True)
    ap.add_argument("--image", help="JPEG gửi kèm mỗi lượt (0x01)")
    ap.add_argument("--settle", type=float, default=0.3, help="giây chờ thêm sau reply_end mỗi lượt")
    args = ap.parse_args()
    token = args.token if args.token is not None else os.environ.get("VISIONCARE_DEVICE_CLIENT_TOKEN", "")
    if not token:
        sys.path.insert(0, os.path.join(HERE, ".."))
        import config  # noqa: PLC0415 - đọc .env như server, không in
        token = config.VISIONCARE_DEVICE_CLIENT_TOKEN
    ws_url = args.url.replace("http", "ws", 1) + ("/v2/session" if args.direct else "/api/v2/session")
    image = open(args.image, "rb").read() if args.image else None
    s = await open_session(ws_url, token, args.device)
    for n, wav in enumerate(args.wav, 1):
        print(f"== lượt {n}: {os.path.basename(wav)}")
        since, end = await s.turn(f"r{n}", wav, image, settle=args.settle)
        show(s, since)
        print(f"   audio 0x02: {len(s.audio)} B tích luỹ; reply_end={'có' if end else 'KHÔNG'}")
    await s.ws.close()


if __name__ == "__main__":
    asyncio.run(main())
