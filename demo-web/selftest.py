"""Tự kiểm proxy WebSocket của serve.py và hợp đồng khung debug/xem, không cần trình duyệt.

Dựng `fake_server.py` + `serve.py` ở cổng tạm. Một client Python đóng vai kính (`/api/v2/session`, hello có
`debug:true`) chạy hết vòng kịch bản; kiểm từng loại khung tới đúng dạng và audio 0x02 giải mã được. Song song một
client khác đóng vai trang giám sát (`/api/v2/observe`): kiểm nó thấy kính nối/ngắt, ảnh lượt đúng từng byte,
trace/say/audio, và khung JPEG ngay trước mỗi `det`/`ocr`. Thoát 0 nếu đạt.

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


async def watch(url, got, ready):
    """Trang giám sát giả: ghi lại theo thứ tự mọi khung nhận được ("bin", bytes) / ("json", dict)."""
    async with connect(url, max_size=2_100_000) as ws:
        await ws.send(json.dumps({"t": "hello", "token": ""}))
        ready.set()
        try:
            async for msg in ws:
                got.append(("bin", msg) if isinstance(msg, bytes) else ("json", json.loads(msg)))
        except Exception:  # noqa: BLE001 - đóng khi selftest xong
            pass


def check_observer(got):
    kinds = [k if k == "bin" else v["t"] for k, v in got]
    ok = next(v for k, v in got if k == "json" and v["t"] == "hello_ok")
    assert ok["role"] == "observer" and ok["glasses"] is False, ok
    on = next(v for k, v in got if k == "json" and v["t"] == "glasses" and v["online"])
    assert on["device"] == "demo-web", on
    assert kinds.index("glasses") < kinds.index("turn_start")
    # ảnh lượt: đúng byte kính gửi
    assert ("bin", b"\x01" + jpeg(320, 240)) in got, "người xem không nhận đúng ảnh lượt 0x01"
    t1 = [i for i, (k, v) in enumerate(got) if k == "json" and v.get("turn") == "t1"]
    seq = [got[i][1]["t"] for i in t1]
    assert seq.index("turn_start") < seq.index("turn_end") < seq.index("trace") < seq.index("reply") < seq.index("reply_end"), seq
    assert any(k == "bin" and v[0] == 0x02 for k, v in got), "người xem không nhận audio 0x02"
    # det/ocr: khung JPEG server vừa xử lý đi NGAY trước JSON của nó
    for t, size in (("det", (320, 240)), ("ocr", (640, 480))):
        idx = [i for i, (k, v) in enumerate(got) if k == "json" and v["t"] == t]
        assert idx, f"người xem không nhận {t}"
        want = ("bin", b"\x04" + jpeg(*size))
        assert any(got[i - 1] == want for i in idx if i), f"{t} không đi sau đúng khung JPEG đã tính"
    assert kinds.count("glasses") >= 2 and got[-1][1].get("online") is False, "thiếu khung kính ngắt"


async def main():
    py = sys.executable
    procs = [
        subprocess.Popen([py, os.path.join(HERE, "fake_server.py"), "--port", str(FAKE_PORT)]),
        subprocess.Popen([py, os.path.join(HERE, "serve.py"), "--port", str(WEB_PORT),
                          "--upstream", f"http://127.0.0.1:{FAKE_PORT}"]),
    ]
    try:
        await asyncio.sleep(1.5)
        seen, ready = [], asyncio.Event()
        watcher = asyncio.create_task(watch(f"ws://127.0.0.1:{WEB_PORT}/api/v2/observe", seen, ready))
        await asyncio.wait_for(ready.wait(), 5)
        await asyncio.sleep(0.3)
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
        await asyncio.sleep(0.5)  # kính đã ngắt: người xem nhận khung glasses offline
        watcher.cancel()
        check_observer(seen)
        print("selftest: ĐẠT (proxy WS + trace/say/det/ocr/mode + ADPCM + trang xem /v2/observe)")
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
