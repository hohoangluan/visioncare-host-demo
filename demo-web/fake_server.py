"""Server kính GIẢ cho trang demo: phát kịch bản khung đúng hợp đồng `WS /v2/session`.

Dùng để xem trang demo khi chưa có GPU/server thật (demo offline), và để tự kiểm
trang mà không phụ thuộc VH. Không có STT/LLM/TTS thật: lời thoại, ý định và
box vật cản đều là kịch bản soạn sẵn, giọng nói là tiếng "bi bô" tổng hợp. Khung
debug (`trace`/`say`/`det`/`ocr`/`mode`) theo bảng của task D1; chỉ gửi khi `hello`
có `debug:true`.

    ~/.venvs/seevia/bin/python demo-web/fake_server.py --port 18777
    python demo-web/serve.py --upstream http://127.0.0.1:18777

Mỗi lượt bấm nút lấy một bước kế tiếp trong vòng kịch bản (hỏi cảnh, đọc chữ,
chỉ đường, gọi điện hai lượt có xác nhận, nhạc...). Lượt nào cũng đọc ảnh/audio
client gửi lên (đếm byte) nên có thể thấy luồng thật chạy qua proxy.
"""
import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time

import numpy as np
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pipeline import adpcm  # noqa: E402  (cùng bộ mã hoá ADPCM với server thật)

RATE = 16000

# Một vòng kịch bản. `live` / `after` là hành vi đặc biệt, phần còn lại chỉ là dữ liệu cho `trace`.
SCRIPT = [
    dict(transcript="phía trước có gì", intent="describe_scene", lane="B", source="gemma", confidence=0.97,
         say=["Phía trước là một căn phòng rộng, có bàn gỗ ở giữa và cửa ra vào bên trái."]),
    dict(transcript="đọc chữ giúp tôi", intent="ocr_start", lane="C", source="rule", confidence=1.0,
         live="ocr", cues=["ocr_start"], say=["Đang bật đọc chữ. Hãy đưa chữ vào giữa khung."]),
    dict(transcript="bật cảnh báo vật cản", intent="alert_on", lane="C", source="rule", confidence=1.0,
         live="nav", cues=["nav_alert_on"], say=["Đã bật cảnh báo vật cản."]),
    dict(transcript="gọi cho mẹ", intent="call", lane="D", source="gemma", confidence=0.93,
         params={"contact": "mẹ"}, pending="Gọi cho mẹ phải không?", say=["Gọi cho mẹ phải không?"]),
    dict(transcript="đúng", intent="confirm", lane="D", source="rule", confidence=1.0,
         params={"contact": "mẹ"}, say=["Đang gọi cho mẹ."], after="call"),
    dict(transcript="phát nhạc", intent="music_play", lane="D", source="gemma", confidence=0.91,
         pending="Bạn muốn nghe bài gì?", say=["Bạn muốn nghe bài gì?"]),
    dict(transcript="nhạc không lời thư giãn", intent="music_play", lane="D", source="gemma", confidence=0.88,
         params={"query": "nhạc không lời thư giãn"}, say=["Đang mở nhạc không lời thư giãn."], after="music"),
    dict(transcript="tắt cảnh báo vật cản", intent="alert_off", lane="C", source="rule", confidence=1.0,
         cues=["nav_alert_off"], say=["Đã tắt cảnh báo vật cản."], after="stop_nav"),
]


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(rộng, cao) đọc từ marker SOF của JPEG; (0, 0) nếu không đọc được."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return 0, 0


def babble(text: str) -> bytes:
    """Giọng "bi bô" tổng hợp cho câu `text`: không phải giọng thật, chỉ để có âm thanh theo nhịp chữ."""
    out = []
    for i, ch in enumerate(text):
        if ch == " ":
            out.append(np.zeros(int(RATE * 0.05)))
            continue
        n = int(RATE * 0.06)
        f = 180 + (ord(ch) * 7) % 140 + 30 * math.sin(i / 3)
        t = np.arange(n) / RATE
        env = np.minimum(1, np.minimum(t / 0.01, (t[-1] - t) / 0.015))
        out.append(0.28 * env * (np.sin(2 * math.pi * f * t) + 0.4 * np.sin(2 * math.pi * 2 * f * t)))
    pcm = (np.concatenate(out) * 32767).astype("<i2").tobytes()
    return adpcm.encode_blocks(pcm)


class Session:
    def __init__(self, ws, token: str):
        self.ws = ws
        self.token = token
        self.debug = False
        self.audio_lock = asyncio.Lock()
        self.live = None  # "ocr" | "nav" | None
        self.flags = dict(obstacle=False, ocr=False, navigating=False, music=False, call=None)
        self.step = 0
        self.turn = None
        self.audio_bytes = 0
        self.image_bytes = 0
        self.frames = 0
        self.last_sent = -99
        self.ocr_state = "scan"
        self.tasks: set[asyncio.Task] = set()

    # --- gửi ---
    async def text(self, obj):
        try:
            await self.ws.send(json.dumps(obj, ensure_ascii=False))
        except ConnectionClosed:
            pass

    async def dbg(self, obj):
        if self.debug:
            await self.text(obj)

    async def mode(self):
        await self.dbg({"t": "mode", **self.flags})

    async def speak(self, turn, text):
        """Một câu: khung `say` rồi audio, giữ khoá để hai câu không xen nhau (như hàng đợi thật)."""
        async with self.audio_lock:
            await self.dbg({"t": "say", "turn": turn, "text": text})
            data = babble(text)
            try:
                for i in range(0, len(data), 256 * 8):
                    await self.ws.send(b"\x02" + data[i:i + 256 * 8])
                    await asyncio.sleep(0.05)  # nhanh hơn thời gian thực ~ 2,5 lần, như TTS thật
            except ConnectionClosed:
                pass

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # --- một lượt ---
    async def run_turn(self, turn, t_release):
        s = SCRIPT[self.step % len(SCRIPT)]
        self.step += 1
        await asyncio.sleep(0.25)  # "STT + intent"
        timings = dict(audio_s=1.6, upload_s=0.12, final_stt_s=0.21, intent_s=0.34, route_s=0.02,
                       release_to_reply_s=round(time.monotonic() - t_release + 0.05, 3))
        await self.dbg({
            "t": "trace", "turn": turn, "transcript": s["transcript"], "intent": s["intent"], "lane": s["lane"],
            "source": s["source"], "confidence": s["confidence"], "params": s.get("params", {}),
            "cues": s.get("cues", []), "live": s.get("live"), "timings": timings, "pending": s.get("pending"),
        })
        await self.text({"t": "reply", "turn": turn, "cues": [], "live": s.get("live"),
                         "audio": {"format": "ima_adpcm;rate=16000;channels=1;block=256", "sample_rate": RATE, "preroll_s": 0.2}})
        for line in s["say"]:
            await self.speak(turn, line)
        await self.text({"t": "reply_end", "turn": turn})

        if s.get("live") == "ocr":
            self.live, self.ocr_state, self.frames = "ocr", "scan", 0
            self.flags["ocr"] = True
            await self.text({"t": "cam", "size": "vga", "fps": 5, "quality": 12})
        elif s.get("live") == "nav":
            self.live, self.frames, self.last_sent = "nav", 0, -99
            self.flags["obstacle"] = True
            await self.text({"t": "cam", "size": "qvga", "fps": 8, "quality": 15})
        after = s.get("after")
        if after == "call":
            self.flags["call"] = "Mẹ"
            self.spawn(self.result_later("result-9f1c", "Cuộc gọi đã kết nối với mẹ.", 2.5))
        elif after == "music":
            self.flags["music"] = True
        elif after == "stop_nav":
            await self.end_live()
            self.flags["music"] = False
        await self.mode()

    async def result_later(self, rid, text, delay):
        await asyncio.sleep(delay)
        await self.text({"t": "reply", "turn": rid, "cues": [], "live": None,
                         "audio": {"format": "ima_adpcm;rate=16000;channels=1;block=256", "sample_rate": RATE, "preroll_s": 0.2}})
        await self.speak(rid, text)
        await self.text({"t": "reply_end", "turn": rid})

    async def end_live(self):
        if self.live:
            await self.text({"t": "end"})
        self.live = None
        self.flags.update(obstacle=False, ocr=False, navigating=False)
        await self.mode()

    # --- khung live ---
    async def on_live_frame(self, jpeg):
        w, h = jpeg_size(jpeg)
        if not w:
            return
        self.frames += 1
        n = self.frames
        if self.live == "nav":
            await self.nav_frame(n, w, h)
        elif self.live == "ocr":
            await self.ocr_frame(n, w, h)

    async def nav_frame(self, n, w, h):
        k = (n % 64) / 64  # xe chạy vào từ bên trái rồi lớn dần
        size = 0.12 + 0.34 * k
        cx = 0.2 + 0.35 * k
        car = [max(0, cx - size / 2), 0.35, min(1, cx + size / 2), min(0.98, 0.35 + size * 0.9)]
        area = (car[2] - car[0]) * (car[3] - car[1])
        level = 3 if area > 0.14 else 2 if area > 0.06 else 1 if area > 0.03 else 0
        person = [0.72, 0.38, 0.84, 0.82]
        direction = "left" if cx < 0.4 else "right" if cx > 0.6 else "center"
        sent = level >= 2 and n - self.last_sent >= 8
        if sent:
            self.last_sent = n
        hazard = {"level": level, "dir": direction, "kind": "car"} if level else None
        await self.dbg({"t": "det", "w": w, "h": h, "sent": bool(sent), "hazard": hazard, "boxes": [
            {"kind": "car", "score": round(0.74 + 0.2 * k, 2), "box": [round(v, 3) for v in car], "level": level},
            {"kind": "person", "score": 0.61, "box": person, "level": 1},
        ]})
        if sent:
            await self.text({"t": "hazard", **hazard})

    async def ocr_frame(self, n, w, h):
        if w >= 1000:  # ảnh nét theo lệnh `capture`
            boxes = [[int(w * a), int(h * b), int(w * c), int(h * d)] for a, b, c, d in
                     [(.18, .30, .82, .38), (.18, .44, .74, .52), (.18, .58, .80, .66)]]
            await self.dbg({"t": "ocr", "w": w, "h": h, "boxes": boxes, "cue": None, "capture": True})
            self.ocr_state = "done"
            self.spawn(self.read_out("Trên tấm biển ghi: Cà phê, mở cửa từ sáu giờ sáng đến mười giờ tối."))
            return
        if self.ocr_state != "scan":
            return
        cue = {6: "look_left", 12: "move_closer", 18: "hold_still"}.get(n)
        shift = 0.22 if n < 6 else 0.1 if n < 12 else 0.0
        boxes = [[int(w * (.12 + shift)), int(h * .32), int(w * (.62 + shift)), int(h * .4)],
                 [int(w * (.12 + shift)), int(h * .46), int(w * (.5 + shift)), int(h * .54)]]
        await self.dbg({"t": "ocr", "w": w, "h": h, "boxes": boxes, "cue": cue, "capture": False})
        if cue:  # server thật đọc cue thành lời cho client không có clip (cue_version 0)
            self.spawn(self.speak("live", {"look_left": "Quay trái một chút.", "move_closer": "Lại gần hơn.",
                                           "hold_still": "Giữ yên."}[cue]))
        if cue == "hold_still":
            await self.text({"t": "capture", "size": "uxga"})  # các khung nhỏ đến trong lúc chờ vẫn được trả box

    async def read_out(self, text):
        await self.speak("live", text)
        await self.end_live()

    # --- vòng nhận ---
    async def run(self):
        first = await asyncio.wait_for(self.ws.recv(), 10)
        hello = json.loads(first) if isinstance(first, str) else {}
        if hello.get("t") != "hello":
            await self.ws.close(4400)
            return
        if self.token and hello.get("token") != self.token:
            await self.ws.close(4401)
            return
        self.debug = bool(hello.get("debug"))
        await self.text({"t": "hello_ok", "session": f"fake{int(time.time()) % 10000:04d}", "cue_version": 2,
                         "ping_s": 25, **({"debug": True} if self.debug else {})})
        await self.mode()
        t_release = time.monotonic()
        try:
            async for msg in self.ws:
                if isinstance(msg, bytes):
                    kind, body = msg[0], msg[1:]
                    if kind == 0x01:
                        self.image_bytes += len(body)
                    elif kind == 0x03:
                        self.audio_bytes += len(body)
                    elif kind == 0x04:
                        await self.on_live_frame(body)
                    continue
                f = json.loads(msg)
                t = f.get("t")
                if t == "ping":
                    await self.text({"t": "pong"})
                elif t == "turn_start":
                    self.turn, self.audio_bytes, self.image_bytes = f.get("turn"), 0, 0
                    # Bấm = huỷ OCR live (nav sống tiếp), như server thật.
                    if self.live == "ocr":
                        await self.end_live()
                elif t == "turn_end" and f.get("turn") == self.turn:
                    t_release = time.monotonic()
                    print(f"[fake] turn {self.turn}: ảnh {self.image_bytes} B, audio {self.audio_bytes} B", flush=True)
                    self.spawn(self.run_turn(self.turn, t_release))
                elif t == "cancel" and self.live == "ocr":
                    await self.end_live()
        except ConnectionClosed:
            pass
        finally:
            for task in list(self.tasks):
                task.cancel()


async def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18777)
    p.add_argument("--token", default="", help="đòi token này trong hello (rỗng = không kiểm)")
    args = p.parse_args()

    async def handler(ws):
        if ws.request.path.split("?")[0] != "/v2/session":
            await ws.close(1008)
            return
        await Session(ws, args.token).run()

    async with serve(handler, args.host, args.port, max_size=2_100_000):
        print(f"Server kính giả: ws://{args.host}:{args.port}/v2/session", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
