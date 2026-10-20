"""Tự kiểm proxy WebSocket của serve.py và hợp đồng khung debug, không cần trình duyệt.

Dựng `fake_server.py` + `serve.py` ở cổng tạm, nối như trang demo (`/api/v2/session`,
hello có `debug:true`) rồi chạy hết vòng kịch bản; kiểm từng loại khung tới đúng
dạng và audio 0x02 giải mã được. Thoát 0 nếu đạt.

    ~/.venvs/seevia/bin/python demo-web/selftest.py
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from websockets.asyncio.client import connect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from pipeline import adpcm  # noqa: E402

FAKE_PORT, WEB_PORT = 18777, 18780


def jpeg(w, h):
    buf = io.BytesIO()
    Image.fromarray((np.random.RandomState(1).rand(h, w, 3) * 255).astype("uint8")).save(buf, "JPEG", quality=60)
    return buf.getvalue()


async def drain(ws, seconds, got, send_live=None):
    """Đọc khung trong `seconds`; `send_live` = (jpeg, fps) để gửi 0x04 như kính khi live bật."""
    end = time.monotonic() + seconds
    next_tx = 0.0
    while time.monotonic() < end:
        if send_live and time.monotonic() >= next_tx:
            await ws.send(b"\x04" + send_live[0])
            next_tx = time.monotonic() + 1 / send_live[1]
        try:
            msg = await asyncio.wait_for(ws.recv(), 0.05)
        except asyncio.TimeoutError:
            continue
        if isinstance(msg, bytes):
            got.setdefault("audio", bytearray()).extend(msg[1:])
        else:
            f = json.loads(msg)
            got.setdefault(f["t"], []).append(f)
            if f["t"] == "capture":  # kính gửi ảnh nét
                await ws.send(b"\x04" + jpeg(1600, 1200))


async def turn(ws, tid, secs=1.5, live=None):
    got = {}
    await ws.send(json.dumps({"t": "turn_start", "turn": tid, "t_press_ms": 1}))
    await ws.send(b"\x01" + jpeg(320, 240))
    await ws.send(b"\x03RIFF" + b"\xff\xff\xff\xff" + b"WAVE" + b"\x00" * 100)
    await ws.send(json.dumps({"t": "turn_end", "turn": tid, "t_release_ms": 2}))
    await drain(ws, secs, got, live)
    return got


async def main():
    py = sys.executable
    procs = [
        subprocess.Popen([py, os.path.join(HERE, "fake_server.py"), "--port", str(FAKE_PORT)]),
        subprocess.Popen([py, os.path.join(HERE, "serve.py"), "--port", str(WEB_PORT),
                          "--upstream", f"http://127.0.0.1:{FAKE_PORT}"]),
    ]
    try:
        await asyncio.sleep(1.5)
        async with connect(f"ws://127.0.0.1:{WEB_PORT}/api/v2/session", max_size=2_100_000) as ws:
            await ws.send(json.dumps({"t": "hello", "device": "demo-web", "token": "", "debug": True,
                                      "cue_version": 0, "accept": "ima_adpcm"}))
            ok = json.loads(await ws.recv())
            assert ok["t"] == "hello_ok" and ok["debug"] is True, ok
            mode0 = json.loads(await ws.recv())
            assert mode0["t"] == "mode" and mode0["call"] is None, mode0

            # lượt 1: hỏi cảnh -> trace + reply + say + audio
            g = await turn(ws, "t1")
            tr = g["trace"][0]
            assert tr["turn"] == "t1" and tr["intent"] == "describe_scene" and tr["pending"] is None, tr
            assert {"audio_s", "final_stt_s", "intent_s", "route_s", "release_to_reply_s"} <= set(tr["timings"])
            assert g["say"][0]["turn"] == "t1" and g["reply"][0]["live"] is None and g["reply_end"]
            pcm = adpcm.decode_blocks(bytes(g["audio"]))
            assert len(pcm) > 8000 and np.abs(pcm).max() > 1000, "audio 0x02 giải mã không ra tiếng"

            # lượt 2: đọc chữ -> live ocr: cam vga, ocr frame có cue, capture, kết thúc bằng end
            g = await turn(ws, "t2", secs=3)
            assert g["reply"][0]["live"] == "ocr" and g["cam"][0]["size"] == "vga"
            g = await turn_free(ws, secs=7, live=(jpeg(640, 480), 5))
            ocr = g["ocr"]
            assert any(f["cue"] == "look_left" for f in ocr), "thiếu cue look_left"
            assert any(f["capture"] and f["w"] >= 1000 for f in ocr), "thiếu khung capture >= 1000 px"
            assert g["capture"] and g["end"], "thiếu capture/end"
            assert all(isinstance(b, list) and len(b) == 4 for f in ocr for b in f["boxes"])

            # lượt 3: nav live -> det có box + level, một khung sent kèm hazard
            await turn(ws, "t3", secs=3)
            g = await turn_free(ws, secs=9, live=(jpeg(320, 240), 8))
            dets = g["det"]
            assert any(f["boxes"] and 0 <= f["boxes"][0]["box"][0] <= 1 for f in dets)
            sent = [f for f in dets if f["sent"]]
            assert sent and sent[0]["hazard"]["kind"] == "car" and sent[0]["hazard"]["level"] >= 2, "không có det sent"
            assert g["hazard"], "không có khung hazard"

            # lượt 4-5: gọi điện có xác nhận (pending) rồi kết quả result-*
            g = await turn(ws, "t4")
            assert g["trace"][0]["pending"] == "Gọi cho mẹ phải không?"
            g = await turn(ws, "t5", secs=4.5)
            assert g["trace"][0]["pending"] is None
            assert g["mode"][-1]["call"] == "Mẹ"
            assert any(s["turn"].startswith("result-") for s in g["say"]), "thiếu say result-*"
        print("selftest: ĐẠT (proxy WS + trace/say/det/ocr/mode + ADPCM)")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(5)


async def turn_free(ws, secs, live):
    got = {}
    await drain(ws, secs, got, live)
    return got


if __name__ == "__main__":
    asyncio.run(main())
