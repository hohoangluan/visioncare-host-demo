"""Kiểm thử end-to-end bằng TRÌNH DUYỆT THẬT cho bảng giám sát (index.html) và kính giả lập (client.html).

Chromium (Playwright) mở cả hai trang như người dùng: bật camera/micro, giữ nút nói, nhìn bảng giám sát. Camera là file
ảnh thật, micro là các câu lệnh tiếng Việt thật (xem README.md). Mỗi kịch bản một trình duyệt mới, kết thúc bằng một bảng
PASS/FAIL, ảnh chụp màn hình và `report.json` (số đo UX) để so giữa các lần sửa giao diện.

    # server thật (đã `./run.sh`): trang mở bằng https://localhost:18443
    ~/.venvs/seevia/bin/python demo-web/e2e/browser_e2e.py --mode real

    # không cần GPU: dựng fake_server + serve.py ở cổng tạm
    ~/.venvs/seevia/bin/python demo-web/e2e/browser_e2e.py --mode fake

Thoát 0 nếu mọi kiểm tra đạt. Cài đặt, kịch bản và cách đọc kết quả: demo-web/e2e/README.md.
"""
import argparse
import asyncio
import base64
import collections
import json
import math
import os
import ssl
import struct
import subprocess
import sys
import time

import websockets
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SEEVIA = os.path.abspath(os.path.join(REPO, ".."))
DEMO = os.path.join(REPO, "demo-web")
STORAGE = os.path.join(REPO, "storage", "e2e-demo-web")  # storage/* đã nằm trong .gitignore

# Dữ liệu thật dùng làm camera/micro (ngoài repo, có sẵn trong workspace SeeVia).
BENCH = os.path.join(SEEVIA, "stt-bench-cache")
OBSTACLE = os.path.join(SEEVIA, "evaluations", "datas", "obstacle_dataset", "train", "img-train")
SIGN = os.path.join(SEEVIA, "evaluations", "datas", "vintext", "vietnamese", "unseen_test_images", "im1808.jpg")
CLIPS = {  # tên -> (file trong stt-bench-cache, câu nói)
    "describe": ("cmd/06e5b050_v0_clean.wav", "Mô tả không gian xung quanh"),
    "alert_on": ("cmd/5348806a_v0_clean.wav", "Bật cảnh báo vật cản"),
    "alert_off": ("cmd/51ab9699_v0_clean.wav", "Tắt cảnh báo vật cản"),
    "ocr": ("cmd/1f64b2ab_v0_clean.wav", "Đọc lá thư tôi đang cầm"),
}
TRUCKS = os.path.join(OBSTACLE, "000000016466.jpg")  # xe tải, không có chữ
CYCLE = [os.path.join(OBSTACLE, n) for n in ("000000020460.jpg", "000000060678.jpg", "000000029656.jpg", "000000016466.jpg")]

# Giây từ lúc bấm nút tới lúc câu lệnh bắt đầu phát. Mặc định 0,2 s (người dùng nói ngay). Server có lỗi STT đã biết: tiếng
# nói bắt đầu quanh 0,6 s thì rớt chữ đầu ("Tắt cảnh báo" -> "Cảnh báo"), xem README.md; `--say-lead 0.6` để tái hiện.
SAY_LEAD = 0.2

MODES_JS = "[...document.querySelectorAll('#modes .mode[data-on=\"1\"]')].map(e=>e.dataset.mode)"
# Chỉ trong bài test: micro = MediaStream do bài test phát file câu lệnh đúng lúc. Micro giả của Chromium
# (--use-file-for-fake-audio-capture) trôi giờ khi máy bận nên lượt nghe sai. Từ MediaStream trở đi là đường thu âm
# thật của client.html (worklet, hạ mẫu, WebSocket). Camera vẫn là camera giả của Chromium phát file MJPEG.
INIT_SCRIPT = """
const ac = new AudioContext(); const dest = ac.createMediaStreamDestination(); window.__clips = {};
window.__load = async (n, b64) => { const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0)); window.__clips[n] = await ac.decodeAudioData(bin.buffer); };
window.__say = (n) => { ac.resume(); const s = ac.createBufferSource(); s.buffer = window.__clips[n]; s.connect(dest); s.start(); };
const g = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = (c) => (c && c.audio) ? (ac.resume(), Promise.resolve(dest.stream)) : g(c);
"""


# ---------------------------------------------------------------------------
# Kết quả kiểm tra + số đo
# ---------------------------------------------------------------------------

class Report:
    def __init__(self, out):
        self.out, self.checks, self.metrics, self.scenario = out, [], collections.OrderedDict(), ""

    def check(self, name, ok, detail=""):
        self.checks.append({"scenario": self.scenario, "name": name, "ok": bool(ok), "detail": str(detail)})
        print(f"  [{'ĐẠT' if ok else 'HỎNG'}] {name}" + (f"  ({detail})" if detail != "" else ""), flush=True)

    def metric(self, key, value):
        self.metrics.setdefault(self.scenario, {})[key] = value
        print(f"  [số đo] {key} = {value}", flush=True)

    def shot(self, page, tag):
        path = os.path.join(self.out, f"{self.scenario}_{tag}.png")
        return page.screenshot(path=path)


# ---------------------------------------------------------------------------
# Dữ liệu thật -> camera/micro giả
# ---------------------------------------------------------------------------

def ffmpeg_mjpeg(images, secs_each, out):
    """Ghép ảnh thành MJPEG 640x480 30 fps, mỗi ảnh `secs_each` giây. Chromium phát lặp file nên 1 vòng ngắn là đủ."""
    if os.path.exists(out):
        return out
    parts = []
    for i, img in enumerate(images):
        part = f"{out}.{i}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-t", str(secs_each), "-i", img,
                        "-vf", "scale=640:480:force_original_aspect_ratio=decrease,pad=640:480:(ow-iw)/2:(oh-ih)/2,format=yuvj420p",
                        "-c:v", "mjpeg", "-q:v", "6", "-f", "mjpeg", part], check=True)
        parts.append(part)
    with open(out, "wb") as fh:
        for p in parts:
            fh.write(open(p, "rb").read())
            os.remove(p)
    return out


def need(path, what):
    if not os.path.exists(path):
        sys.exit(f"Thiếu {what}: {path}\n(kiểm thử thật cần bộ dữ liệu của workspace SeeVia, xem demo-web/e2e/README.md)")
    return path


def cam_file(kind):
    os.makedirs(os.path.join(STORAGE, "assets"), exist_ok=True)
    out = os.path.join(STORAGE, "assets", f"cam_{kind}.mjpeg")
    if kind == "nav":      # xe tải, phố có người và xe, trụ nước: để YOLO có vật cản thật
        return ffmpeg_mjpeg([need(p, "ảnh vật cản") for p in CYCLE], 3, out)
    if kind == "trucks":   # không có chữ: OCR phải căn khung live
        return ffmpeg_mjpeg([need(TRUCKS, "ảnh vật cản")], 4, out)
    if kind == "sign":     # biển "CÔNG TRƯỜNG ĐANG THI CÔNG": server đọc thẳng
        return ffmpeg_mjpeg([need(SIGN, "ảnh biển chữ")], 4, out)
    raise ValueError(kind)


def clip_b64(name):
    return base64.b64encode(open(need(os.path.join(BENCH, CLIPS[name][0]), "file câu lệnh"), "rb").read()).decode()


# ---------------------------------------------------------------------------
# Người xem Python: kiểm giao thức độc lập với trình duyệt (không token: proxy tự gắn)
# ---------------------------------------------------------------------------

class PyObserver:
    def __init__(self, url):
        self.url, self.log, self.task = url, [], None

    async def _run(self):
        try:
            insecure = None
            if self.url.startswith("wss"):  # https tự ký của serve.py --lan
                insecure = ssl.create_default_context()
                insecure.check_hostname, insecure.verify_mode = False, ssl.CERT_NONE
            async with websockets.connect(self.url, max_size=4_000_000, ssl=insecure) as ws:
                await ws.send(json.dumps({"t": "hello", "token": ""}))

                async def ping():
                    while True:
                        await asyncio.sleep(20)  # giao thức: ping định kỳ, im 90 s là bị ngắt
                        await ws.send(json.dumps({"t": "ping"}))

                pinger = asyncio.create_task(ping())
                try:
                    async for m in ws:
                        self.log.append(("bin", m[0], len(m)) if isinstance(m, bytes) else ("json", json.loads(m)["t"], json.loads(m)))
                finally:
                    pinger.cancel()
        except Exception as exc:  # noqa: BLE001
            self.log.append(("error", repr(exc), None))

    def start(self):
        self.task = asyncio.create_task(self._run())

    def stop(self):
        self.task.cancel()

    def errors(self):
        return [v for k, v, _ in self.log if k == "error"]

    def count(self, t):
        return sum(1 for k, v, _ in self.log if k == "json" and v == t)

    def frames_follow_jpeg(self, kind):
        """Mọi khung det/ocr phải đi NGAY sau một khung nhị phân 0x04 (ảnh server vừa tính). -> (đúng, sai)"""
        ok = bad = 0
        for i, (k, v, _) in enumerate(self.log):
            if k == "json" and v == kind:
                prev = self.log[i - 1] if i else None
                if prev and prev[0] == "bin" and prev[1] == 0x04:
                    ok += 1
                else:
                    bad += 1
        return ok, bad

    def traces(self):
        return [x for k, v, x in self.log if k == "json" and v == "trace"]


# ---------------------------------------------------------------------------
# Một phiên trình duyệt: bảng giám sát + kính giả lập
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, base, report, cam, viewport=None, clips=()):
        self.base, self.r, self.cam, self.viewport, self.clips = base, report, cam, viewport or {"width": 1440, "height": 900}, clips
        self.errors, self.sent, self.t0 = [], [], 0.0

    async def __aenter__(self):
        self.pw = await async_playwright().start()
        args = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
        if self.cam:
            args.append(f"--use-file-for-fake-video-capture={self.cam}")
        self.browser = await self.pw.chromium.launch(args=args)
        self.ctx = await self.browser.new_context(permissions=["camera", "microphone"], ignore_https_errors=True, viewport=self.viewport)
        await self.ctx.add_init_script(INIT_SCRIPT)
        self.view, self.client = await self.ctx.new_page(), await self.ctx.new_page()
        for pg, name in ((self.view, "viewer"), (self.client, "client")):
            pg.on("pageerror", lambda e, n=name: self.errors.append(f"{n}: {e}"))
        self.client.on("websocket", lambda ws: "/v2/session" in ws.url and ws.on("framesent", lambda p: self.sent.append((time.monotonic(), p))))
        await self.view.goto(f"{self.base}/index.html")
        await self.client.goto(f"{self.base}/client.html")
        await asyncio.sleep(1.5)
        for n in self.clips:
            await self.client.evaluate("([n,b])=>window.__load(n,b)", [n, clip_b64(n)])
        return self

    async def __aexit__(self, *exc):
        await self.browser.close()
        await self.pw.stop()

    async def start_devices(self):
        await self.client.click("#btn-cam")
        await self.client.click("#btn-mic")
        self.t0 = time.monotonic()
        await asyncio.sleep(1.0)

    async def say(self, clip, tail=2.5, silent=0.0):
        """Giữ nút nói, phát câu `clip` sau SAY_LEAD giây, thả sau câu + `tail` giây."""
        box = await self.client.locator("#ptt").bounding_box()
        await self.client.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await self.client.mouse.down()
        await asyncio.sleep(SAY_LEAD)
        dur = silent
        if clip:
            await self.client.evaluate("n=>window.__say(n)", clip)
            dur = len(base64.b64decode(clip_b64(clip))) / 32000
        await asyncio.sleep(dur + tail)
        await self.client.mouse.up()

    async def reply_done(self, timeout=45):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if await self.view.get_attribute('.step[data-step="reply"]', "data-state") == "done":
                return True
            await asyncio.sleep(0.3)
        return False

    async def heard(self):
        """Câu server nghe được + ý định của lượt hiện tại (đọc từ timeline), để biết lỗi do STT/ý định hay do giao diện."""
        stt = await self.view.inner_text('.step[data-step="stt"] .step-detail')
        intent = await self.view.inner_text('.step[data-step="intent"] .step-detail')
        return f"{stt.strip()} -> {intent.strip().replace(chr(10), ' ')}"

    async def modes(self):
        return await self.view.evaluate(MODES_JS)

    async def text(self, sel):
        return await self.view.inner_text(sel)

    def turn_pcms(self):
        """PCM16 16 kHz mà client.html đã gửi lên theo từng lượt (đúng thứ server nhận)."""
        turns, cur = [], None
        for _, p in self.sent:
            if isinstance(p, str):
                f = json.loads(p)
                if f["t"] == "turn_start":
                    cur = bytearray()
                elif f["t"] == "turn_end" and cur is not None:
                    turns.append(cur)
                    cur = None
            elif cur is not None and p[0] == 0x03:
                body = bytes(p[1:])
                cur.extend(body[44:] if body[:4] == b"RIFF" else body)
        return turns

    def dump_wavs(self, outdir, prefix):
        """Lưu âm thanh client đã gửi thành WAV để nghe lại / đưa qua realcheck.py khi nghi đường thu âm."""
        import wave

        for i, pcm in enumerate(self.turn_pcms()):
            with wave.open(os.path.join(outdir, f"{prefix}_turn{i + 1}_sent.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(bytes(pcm))

    def audio_onsets(self):
        """Mỗi lượt: tiếng nói của câu lệnh bắt đầu sau bao nhiêu giây (chẩn đoán đường thu âm của client.html)."""
        out = []
        for pcm in self.turn_pcms():
            n = len(pcm) // 2
            s = struct.unpack("<%dh" % n, bytes(pcm[: n * 2]))
            env = [math.sqrt(sum(x * x for x in s[i:i + 1600]) / 1600) for i in range(0, n - 1600, 1600)]
            loud = [i / 10 for i, e in enumerate(env) if e > 500]
            out.append({"sent_s": round(n / 16000, 2), "speech_from_s": loud[0] if loud else None})
        return out


def observe_url(base):
    return base.replace("https", "wss", 1).replace("http", "ws", 1) + "/api/v2/observe"


def parse_ms(text):
    """'tiếng đầu sau 327 ms' hoặc '1,2 s' -> mili giây."""
    import re

    m = re.search(r"tiếng đầu sau ([\d,]+) (ms|s)", text)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return round(v * (1000 if m.group(2) == "s" else 1))


async def ready_checks(s, r, expect_device=None):
    r.check("bảng giám sát nối server", "Đã nối server" in await s.text("#conn-text"), await s.text("#conn-text"))
    gl = await s.text("#glasses-text")
    r.check("kính giả lập hiện là đã kết nối", "Kính đã kết nối" in gl and (not expect_device or expect_device in gl), gl)
    r.check("kính giả lập nối không cần nhập token", "Đã kết nối" in await s.client.inner_text("#conn-text"))
    r.metric("empty_state", await s.text("#stage-empty-msg"))


# ---------------------------------------------------------------------------
# Kịch bản
# ---------------------------------------------------------------------------

async def sc_describe(base, r, **_):
    async with Session(base, r, cam_file("trucks"), clips=["describe"]) as s:
        await ready_checks(s, r)
        await r.shot(s.view, "0_ready")
        await s.start_devices()
        await s.say("describe")
        done = await s.reply_done()
        r.check("server trả lời xong lượt", done)
        timeline = await s.text("#timeline")
        hist = await s.text("#history")
        r.check("POV hiện ảnh kính gửi lúc bấm nút", await s.view.get_attribute("#stage", "data-frame") == "1" and "Ảnh kính gửi" in await s.text("#stat-src"))
        r.check("timeline có transcript và ý định", "Mô tả không gian" in timeline and "space" in timeline)
        r.check("lịch sử có câu hỏi và câu trả lời", "Mô tả không gian" in hist and "KÍNH TRẢ LỜI" in hist.upper())
        ttfa = parse_ms(timeline)
        r.metric("ttfa_ms", ttfa)
        r.check("tiếng đầu < 1,5 s", ttfa is not None and ttfa < 1500, ttfa)
        r.metric("audio_onsets", s.audio_onsets())
        s.dump_wavs(r.out, "describe")
        await r.shot(s.view, "1_after")
        r.check("không có lỗi JS", not s.errors, s.errors)


async def sc_nav(base, r, **_):
    obs = PyObserver(observe_url(base))
    async with Session(base, r, cam_file("nav"), clips=["alert_on", "alert_off"]) as s:
        await ready_checks(s, r)
        await s.start_devices()
        # người xem Python nối sau khi trang đã chạy: kiểm proxy gắn token cho client không phải trình duyệt
        obs.start()
        await s.say("alert_on")
        await s.reply_done(25)
        r.metric("alert_on_heard", await s.heard())
        await asyncio.sleep(9)
        modes = await s.modes()
        r.check("chế độ Tránh vật cản sáng", modes == ["obstacle"], modes)
        fps = await s.text("#stat-fps")
        r.metric("fps_text", fps)
        r.check("server xử lý khung live", "server xử lý" in fps and "0,0 fps" not in fps, fps)
        r.check("nhãn nguồn: khung live server vừa xử lý", "Khung live" in await s.text("#stat-src"))
        hlog = await s.text("#hlog")
        r.check("có cảnh báo vật cản trong log", "Chưa có cảnh báo" not in hlog, hlog.replace("\n", " ¦ ")[:120])
        r.check("kính giả lập hiện đang gửi live", await s.client.is_visible("#live-badge"), await s.client.inner_text("#live-badge"))
        await r.shot(s.view, "1_nav_viewer")
        await r.shot(s.client, "1_nav_client")
        await s.say("alert_off")
        await s.reply_done(20)
        await asyncio.sleep(2)
        r.metric("alert_off_heard", await s.heard())
        r.check("tắt cảnh báo: chế độ về trống", await s.modes() == [], f"{await s.modes()} | server nghe: {await s.heard()}")
        await r.shot(s.view, "2_stopped")
        s.dump_wavs(r.out, "nav")
        r.check("người xem Python nối được qua proxy (không token)", not obs.errors() and obs.count("hello_ok") == 1, obs.errors())
        dets, bad = obs.count("det"), obs.frames_follow_jpeg("det")
        r.metric("det_frames", dets)
        r.metric("det_with_prior_jpeg", {"đúng": bad[0], "sai": bad[1]})
        r.check("có khung det", dets > 20, dets)
        r.check("mọi det đi sau đúng khung JPEG của nó", bad[1] == 0 and bad[0] == dets, bad)
        r.check("người xem Python (không token) nhận cảnh báo", obs.count("hazard") > 0, obs.count("hazard"))
        await s.client.close()
        await asyncio.sleep(4)
        r.check("kính ngắt: bảng báo chưa kết nối", "chưa kết nối" in await s.text("#glasses-text"), await s.text("#glasses-text"))
        await r.shot(s.view, "3_offline")
        obs.stop()
        r.check("không có lỗi JS", not s.errors, s.errors)


async def ocr_start(s, obs):
    await ready_checks(s, s.r)
    await s.start_devices()
    obs.start()
    await s.say("ocr")


async def sc_ocr_direct(base, r, **_):
    obs = PyObserver(observe_url(base))
    async with Session(base, r, cam_file("sign"), clips=["ocr"]) as s:
        await ocr_start(s, obs)
        await s.reply_done(40)
        await asyncio.sleep(2)
        hist = await s.text("#history")
        r.check("đọc đúng chữ trên biển", "CÔNG TRƯỜNG ĐANG THI CÔNG" in hist.upper(), hist.replace("\n", " ¦ ")[-120:])
        r.check("không mở OCR live (ảnh rõ, đọc thẳng)", await s.modes() == [], await s.modes())
        await r.shot(s.view, "1_after")
        r.check("không có lỗi JS", not s.errors, s.errors)
    obs.stop()


async def sc_ocr_live(base, r, **_):
    obs = PyObserver(observe_url(base))
    async with Session(base, r, cam_file("trucks"), clips=["ocr"]) as s:
        await ocr_start(s, obs)
        await asyncio.sleep(10)
        r.check("chế độ Đọc chữ trực tiếp sáng", await s.modes() == ["ocr"], await s.modes())
        chip = (await s.text("#ocr-text")) if await s.view.is_visible("#ocr-chip") else ""
        r.metric("ocr_chip", chip)
        r.check("hiện chip hướng dẫn căn khung", chip != "", chip)
        await asyncio.sleep(5)
        await r.shot(s.view, "1_live")
        hist = await s.text("#history")
        r.check("lịch sử có bong bóng 'SeeVia · trực tiếp' gộp câu lặp", "TRỰC TIẾP" in hist.upper() and "×" in hist, hist.replace("\n", " ¦ ")[-100:])
        r.check("người xem Python nối được qua proxy (không token)", not obs.errors() and obs.count("hello_ok") == 1, obs.errors())
        n, bad = obs.count("ocr"), obs.frames_follow_jpeg("ocr")
        r.metric("ocr_frames", n)
        r.check("mọi ocr đi sau đúng khung JPEG của nó", n > 20 and bad[1] == 0 and bad[0] == n, bad)
        r.check("không có lỗi JS", not s.errors, s.errors)
    obs.stop()


async def sc_fake_flow(base, r, **_):
    """Server giả (kịch bản soạn sẵn): hỏi cảnh -> đọc chữ live -> tránh vật cản. Không cần GPU, dùng để chỉnh UX nhanh."""
    obs = PyObserver(observe_url(base))
    async with Session(base, r, cam_file("nav")) as s:
        await ready_checks(s, r, expect_device="kinh-hien-tai")
        await s.start_devices()
        obs.start()
        for tag, wait in (("1_describe", 4), ("2_ocr_live", 9), ("3_nav", 11)):
            await s.say(None, tail=0.8, silent=1.0)
            await asyncio.sleep(wait)
            r.metric(f"{tag}_modes", await s.modes())
            r.metric(f"{tag}_fps", await s.text("#stat-fps"))
            await r.shot(s.view, tag)
        r.check("kết thúc ở chế độ Tránh vật cản", await s.modes() == ["obstacle"], await s.modes())
        r.check("log có cảnh báo vật cản", "Chưa có cảnh báo" not in await s.text("#hlog"))
        n, bad = obs.count("det"), obs.frames_follow_jpeg("det")
        r.check("mọi det đi sau đúng khung JPEG của nó", n > 10 and bad[1] == 0, (n, bad))
        r.check("không có lỗi JS", not s.errors, s.errors)
    obs.stop()


OVERFLOW_JS = """() => {
  const sel = '.row-body, .row-label, .task-name, .task-arg, .chip, .mode, .step-head b, .turn-no, .glasses, .conn, .sec-title, .btn, .modes-title, .pill, .hlog .what, .ph-status';
  return [...document.querySelectorAll(sel)].filter(e => e.offsetParent && e.getClientRects().length &&
    e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible').map(e => (e.className || e.tagName) + ':' + e.textContent.trim().slice(0, 30));
}"""


async def sc_fake_tour(base, r, **_):
    """(chỉ --mode fake) Cả kịch bản 8 lượt ở 1920x1080: thẻ hội thoại, lệnh điện thoại, ảnh thu nhỏ, ô Điện thoại, không chữ bị cắt."""
    async with Session(base, r, cam_file("nav"), viewport={"width": 1920, "height": 1080}) as s:
        await ready_checks(s, r, expect_device="kinh-hien-tai")
        r.check("chưa có lượt: câu rỗng rõ ràng", "Bấm nút trên kính" in await s.text("#history-empty-msg"), await s.text("#history-empty-msg"))
        r.check("ô Điện thoại rỗng có hướng dẫn", "Chưa có lệnh nào" in await s.text("#ph-tasks"))
        await r.shot(s.view, "0_empty")
        await s.start_devices()
        for i, wait in enumerate((4, 9, 9, 4, 6, 4, 6, 4)):
            await s.say(None, tail=0.8, silent=1.0)
            await asyncio.sleep(wait)
            if i == 3:  # lượt "gọi cho mẹ": đang chờ xác nhận
                r.check("lệnh gọi điện chờ xác nhận", "CHỜ BẠN TRẢ LỜI" in (await s.text("#ph-tasks")).upper(), (await s.text("#ph-tasks"))[:80])
        await asyncio.sleep(3)
        turns = await s.view.locator("#history .turn").count()
        r.metric("turn_cards", turns)
        r.check("mọi lượt đều có thẻ (>= 8 thẻ người dùng)", await s.view.locator("#history .turn .row-user").count() >= 8, turns)
        hist = await s.text("#history")
        r.check("thẻ có 'Người dùng nói' + 'Kính trả lời' + ý định + độ trễ", all(k in hist.upper() for k in ("NGƯỜI DÙNG NÓI", "KÍNH TRẢ LỜI", "Ý ĐỊNH", "TIẾNG ĐẦU")), hist[:80])
        r.check("thẻ lệnh điện thoại có trạng thái xong + kết quả", "XONG" in hist.upper() and "CUỘC GỌI ĐÃ KẾT NỐI" in hist.upper())
        tasks = (await s.text("#ph-tasks")).upper()
        r.metric("phone_tasks", tasks.replace("\n", " ¦ ")[:200])
        r.check("ô Điện thoại: gọi điện + phát nhạc đã xong", "GỌI ĐIỆN" in tasks and "PHÁT NHẠC" in tasks and tasks.count("XONG") >= 2, tasks[:120])
        r.check("ô Điện thoại có cuộc gọi đang diễn ra", "ĐANG TRONG CUỘC GỌI" in tasks)
        r.check("log cảnh báo có ảnh thu nhỏ đúng khung", await s.view.locator("#hlog img.hthumb").count() >= 1)
        r.check("thẻ trực tiếp gắn ảnh thu nhỏ", await s.view.locator("#history .thumb img").count() >= 1)
        over = await s.view.evaluate(OVERFLOW_JS)
        r.check("không chữ bị cắt ở 1920x1080", not over, over)
        sw = await s.view.evaluate("document.documentElement.scrollWidth")
        r.check("1920x1080 không cuộn ngang", sw <= 1920, sw)
        await r.shot(s.view, "1_final")
        await s.view.evaluate("document.getElementById('history').scrollTop = 0")
        await asyncio.sleep(0.4)
        await r.shot(s.view, "2_history_top")
        r.check("không có lỗi JS", not s.errors, s.errors)


async def sc_fake_client(base, r, **_):
    """(chỉ --mode fake) client.html: giữ phím Space để nói, chỉ báo mức âm micro, trạng thái đọc được bằng trình đọc màn hình."""
    async with Session(base, r, cam_file("nav"), clips=["alert_on"]) as s:
        await ready_checks(s, r, expect_device="kinh-hien-tai")
        attrs = await s.client.evaluate("""() => ({
          meter: document.getElementById('meter').getAttribute('role'),
          status: document.getElementById('status').getAttribute('role'),
          shortcut: document.getElementById('ptt').getAttribute('aria-keyshortcuts'),
          banner: !!document.getElementById('banner') })""")
        r.check("client: có role=meter, vùng trạng thái aria-live, aria-keyshortcuts", attrs["meter"] == "meter" and attrs["status"] == "status" and attrs["shortcut"] == "Space" and attrs["banner"], attrs)
        await s.start_devices()
        r.check("client: micro bật, chưa nghe thì chỉ báo nghỉ", await s.client.get_attribute("#meter-box", "data-active") == "0")
        n0 = len([1 for _, p in s.sent if isinstance(p, str) and '"turn_start"' in p])
        await s.client.keyboard.down("Space")  # tiêu điểm không ở ô nhập nên Space = giữ để nói
        await asyncio.sleep(0.15)
        await s.client.evaluate("n=>window.__say(n)", "alert_on")
        await asyncio.sleep(0.8)
        r.check("client: giữ Space = nút Nói đang bấm", await s.client.get_attribute("#ptt", "aria-pressed") == "true")
        status = await s.client.inner_text("#status")
        r.check("client: trạng thái đọc được ('Đang nghe bạn…')", "Đang nghe" in status, status)
        now = int(await s.client.get_attribute("#meter", "aria-valuenow"))
        r.metric("meter_valuenow", now)
        r.check("client: chỉ báo mức âm micro nhích lên khi có tiếng", now > 0 and await s.client.get_attribute("#meter-box", "data-active") == "1", now)
        await r.shot(s.client, "1_listening")
        await s.client.keyboard.up("Space")
        await asyncio.sleep(0.6)
        n1 = len([1 for _, p in s.sent if isinstance(p, str) and '"turn_start"' in p])
        r.check("client: thả Space = gửi lượt", n1 == n0 + 1 and any(isinstance(p, str) and '"turn_end"' in p for _, p in s.sent))
        r.check("client: thả phím thì chỉ báo về nghỉ", await s.client.get_attribute("#meter-box", "data-active") == "0" and await s.client.get_attribute("#ptt", "aria-pressed") == "false")
        await asyncio.sleep(3)
        await s.client.keyboard.press("Space")  # nhấn nhanh cũng phải là một lượt hợp lệ, không làm hỏng trạng thái
        await asyncio.sleep(1.5)
        r.check("client: sau lượt vẫn dùng được (không kẹt)", await s.client.get_attribute("#ptt", "aria-pressed") == "false")
        r.check("client: không có lỗi JS", not s.errors, s.errors)


async def sc_phone_mirror(base, r, upstream="", **_):
    """(chỉ --mode fake) serve.py --phone-mirror với adb GIẢ (ffmpeg testsrc, KHÔNG gọi adb thật): ô Điện thoại hiện ảnh thật + thẻ tác vụ dưới."""
    import socket
    import threading

    fake_adb = os.path.join(r.out, "fake_adb.sh")
    with open(fake_adb, "w") as fh:
        fh.write("#!/bin/sh\nexec ffmpeg -v error -f lavfi -i testsrc=size=540x1170:rate=10 -t 20 -f h264 -\n")
    os.chmod(fake_adb, 0o755)
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(8)
    ls.settimeout(0.2)
    stop = threading.Event()

    def accept():
        while not stop.is_set():
            try:
                ls.accept()[0].close()
            except OSError:
                pass

    threading.Thread(target=accept, daemon=True).start()
    web = 18781
    env = dict(os.environ, SEEVIA_ADB=fake_adb, SEEVIA_ADB_PORT=str(ls.getsockname()[1]))
    proc = subprocess.Popen([sys.executable, os.path.join(DEMO, "serve.py"), "--port", str(web), "--upstream", upstream, "--token", "tok-chi-nam-o-server",
                             "--device", "kinh-hien-tai", "--phone-mirror"], cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await asyncio.sleep(1.5)
        async with Session(f"http://localhost:{web}", r, cam_file("nav"), viewport={"width": 1920, "height": 1080}) as s:
            for _ in range(30):
                if await s.view.get_attribute("#phone", "data-mirror") == "on":
                    break
                await asyncio.sleep(0.5)
            r.check("ô Điện thoại: có luồng thật thì hiện ảnh", await s.view.get_attribute("#phone", "data-mirror") == "on")
            await asyncio.sleep(1.5)
            w = await s.view.evaluate("document.getElementById('phone-img').naturalWidth")
            r.metric("phone_img_naturalWidth", w)
            r.check("ảnh điện thoại đã giải mã (540 px rộng)", w == 540, w)
            await s.start_devices()
            await s.say(None, tail=0.8, silent=1.0)
            await asyncio.sleep(3)
            await s.say(None, tail=0.8, silent=1.0)
            await asyncio.sleep(3)
            r.check("thẻ tác vụ nằm dưới khung ảnh", await s.view.evaluate("(() => { const a = document.getElementById('phone-frame'), b = document.getElementById('ph-tasks'); return !!(a.nextElementSibling === b); })()"))
            await r.shot(s.view, "1_mirror")
            r.check("không có lỗi JS", not s.errors, s.errors)
    finally:
        stop.set()
        proc.terminate()
        proc.wait(5)
        ls.close()


async def sc_layout(base, r, **_):
    """Bố cục: máy tính và điện thoại, hộp Cài đặt, không cuộn ngang."""
    for name, vp in (("desktop", {"width": 1440, "height": 900}), ("phone", {"width": 390, "height": 800})):
        async with Session(base, r, None, viewport=vp) as s:
            sw = await s.view.evaluate("document.documentElement.scrollWidth")
            r.metric(f"viewer_{name}_scrollWidth", sw)
            r.check(f"bảng giám sát {name} không cuộn ngang", sw <= vp["width"], f"{sw} <= {vp['width']}")
            await s.view.screenshot(path=os.path.join(r.out, f"layout_viewer_{name}.png"))
            await s.client.screenshot(path=os.path.join(r.out, f"layout_client_{name}.png"))
            await s.view.click("#btn-settings")
            await asyncio.sleep(0.3)
            await s.view.screenshot(path=os.path.join(r.out, f"layout_settings_{name}.png"))
            r.check(f"{name}: hộp Cài đặt không còn ô camera/chế độ mô phỏng", await s.view.locator("#set-facing, input[name=mode]").count() == 0)
            r.check(f"{name}: không có lỗi JS", not s.errors, s.errors)


async def sc_bad_token(base, r, upstream=None, **_):
    """Đối chứng âm: proxy cấu hình token SAI thì trang phải báo 'Token sai', không được nối nhầm."""
    port = 18793
    proc = subprocess.Popen([sys.executable, os.path.join(DEMO, "serve.py"), "--port", str(port), "--upstream", upstream, "--token", "token-sai-co-chu-dich"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await asyncio.sleep(1.5)
        async with Session(f"http://localhost:{port}", r, None) as s:
            conn = await s.text("#conn-text")
            r.check("token sai: bảng báo 'Token sai'", "Token sai" in conn, conn)
            r.check("token sai: không hiện kính đã kết nối", "chưa kết nối" in await s.text("#glasses-text"))
            await r.shot(s.view, "1_bad_token")
    finally:
        proc.terminate()
        proc.wait(5)


SCENARIOS = {"describe": sc_describe, "nav": sc_nav, "ocr-direct": sc_ocr_direct, "ocr-live": sc_ocr_live,
             "fake-flow": sc_fake_flow, "fake-tour": sc_fake_tour, "fake-client": sc_fake_client, "phone-mirror": sc_phone_mirror, "layout": sc_layout, "bad-token": sc_bad_token}
DEFAULT = {"real": ["describe", "nav", "ocr-direct", "ocr-live", "layout", "bad-token"],
           "fake": ["fake-flow", "fake-tour", "fake-client", "phone-mirror", "layout", "bad-token"]}


# ---------------------------------------------------------------------------

async def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["real", "fake"], default="real")
    ap.add_argument("--url", help="địa chỉ trang demo (mặc định real: https://localhost:18443, fake: http://localhost:18780)")
    ap.add_argument("--upstream", default="http://127.0.0.1:18888", help="server kính (chỉ dùng cho kịch bản bad-token ở chế độ real)")
    ap.add_argument("--scenarios", nargs="+", choices=sorted(SCENARIOS), help="mặc định theo --mode")
    ap.add_argument("--say-lead", type=float, default=SAY_LEAD, help="giây từ lúc bấm nút tới lúc câu lệnh bắt đầu (mặc định 0,2)")
    ap.add_argument("--out", default=os.path.join(STORAGE, time.strftime("run-%Y%m%d-%H%M%S")), help="thư mục ảnh + report.json")
    args = ap.parse_args()
    globals()["SAY_LEAD"] = args.say_lead
    os.makedirs(args.out, exist_ok=True)
    report = Report(args.out)
    procs, base, upstream = [], args.url, args.upstream
    if args.mode == "fake":
        fake, web = 18777, 18780
        secret = "tok-chi-nam-o-server"
        procs = [subprocess.Popen([sys.executable, os.path.join(DEMO, "fake_server.py"), "--port", str(fake), "--token", secret], cwd=REPO, stdout=subprocess.DEVNULL),
                 subprocess.Popen([sys.executable, os.path.join(DEMO, "serve.py"), "--port", str(web), "--upstream", f"http://127.0.0.1:{fake}",
                                   "--token", secret, "--device", "kinh-hien-tai"], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        base, upstream = base or f"http://localhost:{web}", f"http://127.0.0.1:{fake}"
        await asyncio.sleep(1.5)
    base = base or "https://localhost:18443"
    try:
        for name in args.scenarios or DEFAULT[args.mode]:
            report.scenario = name
            print(f"\n== {name}", flush=True)
            try:
                await SCENARIOS[name](base, report, upstream=upstream)
            except Exception as exc:  # noqa: BLE001 - một kịch bản hỏng không được che các kịch bản khác
                report.check("kịch bản chạy hết", False, repr(exc))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(5)
    failed = [c for c in report.checks if not c["ok"]]
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"mode": args.mode, "base": base, "checks": report.checks, "metrics": report.metrics}, fh, ensure_ascii=False, indent=2)
    print(f"\n{len(report.checks) - len(failed)}/{len(report.checks)} kiểm tra đạt. Ảnh + report.json: {args.out}")
    for c in failed:
        print(f"  HỎNG [{c['scenario']}] {c['name']}  ({c['detail']})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
