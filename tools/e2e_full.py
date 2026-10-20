# ruff: noqa
"""E2E trọn luồng: kính giả lập (WS /v2/session) -> VH voice server -> app server (webhook) -> điện thoại giả.

Dựng cả stack (postgres test + AB uvicorn DELIVERY_TRANSPORT=webhook + phone_sim + VH), chạy các kịch bản
bằng giọng nói tổng hợp (VieNeu -> ADPCM, phát đúng nhịp thời gian thực như người giữ nút), rồi in bảng
PASS/FAIL cùng ba mốc thời gian mỗi kịch bản:

  nhả nút -> tiếng đầu       (khung 0x02 đầu tiên sau turn_end)
  nhả nút -> lệnh tới ĐT      (dòng `command` trong phone_sim_log.jsonl, đồng hồ cùng máy)
  lệnh -> kết quả được đọc    (từ lúc ĐT báo `report` tới khối audio đầu tiên sau đó)

Làn D đọc lại ngay, lệnh chạy sau `readback_delay`; Gemma chưa đủ ACTION_MIN_CONFIDENCE thì server hỏi
"...phải không?" — kịch bản phát hiện qua log VH rồi trả lời "Đúng." và ghi cột `hỏi lại`.

    python tools/e2e_full.py                      # dựng toàn bộ stack riêng (cổng 18893/18001/18002)
    python tools/e2e_full.py --only call_mom chat # chỉ vài kịch bản
    python tools/e2e_full.py --app-url https://app-server-that --no-phone-sim   # app server + điện thoại THẬT
    python tools/e2e_full.py --keep               # không tắt stack khi xong (để soi log)

KHÔNG dùng app server :8001 của người dùng. Mọi tiến trình/DB do công cụ này dựng đều bị tắt khi xong.
Token đọc từ .env, không in ra.
"""

import argparse
import asyncio
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEEVIA = ROOT.parent  # SeeVia_system (worktree và checkout chính cùng nằm dưới đây)
AB = SEEVIA / "app-demo-backend" / "server"
PY = os.environ.get("E2E_PY", str(Path.home() / ".venvs" / "seevia" / "bin" / "python"))
GLASSES = "e2e-glasses"
BYTE_RATE = 8110.9
SILENCE = "<bấm nút, không nói>"
CHUNK = 512
ASK_MARK = "hỏi lại"  # log VH: "làn D <intent>: hỏi lại (backend=...)"
REQ_RE = re.compile(r"Calling VisionCare API: POST \S+/api/v1/service/(\w+)/(\w+) ")


# ───────────────────────────── env / tiến trình ─────────────────────────────

def read_env(path: Path) -> dict:
    """Như python-dotenv (cắt chú thích cuối dòng) để biến truyền cho tiến trình con giống hệt khi server tự nạp .env."""
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None} if path and path.exists() else {}


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def http_ok(url: str, timeout=2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def wait_http(url: str, secs: float, what: str, proc=None):
    end = time.time() + secs
    while time.time() < end:
        if http_ok(url):
            return
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"{what} thoát sớm (mã {proc.returncode}); xem log trong workdir")
        time.sleep(1.0)
    raise SystemExit(f"{what} không lên sau {secs:.0f}s ({url})")


class Stack:
    """Dựng/tắt stack riêng. Mọi thứ do mình bật đều tắt ở `stop()`."""

    def __init__(self, a):
        self.a = a
        self.procs: list[subprocess.Popen] = []
        self.work = Path(a.workdir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.phone_log = self.work / "phone_sim_log.jsonl"
        self.vh_log = self.work / "vh.log"
        self.compose = ["docker", "compose", "-p", a.compose_project, "-f", str(AB / "compose.test.yaml")]
        self.db_up = False
        self.ports = []

    def start(self):
        a = self.a
        vh_env = read_env(Path(a.vh_env))
        ab_env = read_env(Path(a.ab_env))
        public_token = os.environ.get("VISIONCARE_CLIENT_TOKEN") or ab_env.get("VISIONCARE_CLIENT_TOKEN", "")
        cb_token = ab_env.get("VISIONCARE_CALLBACK_TOKEN") or vh_env.get("VISIONCARE_CALLBACK_TOKEN", "")
        self.device_token = os.environ.get("VISIONCARE_DEVICE_CLIENT_TOKEN") or vh_env.get("VISIONCARE_DEVICE_CLIENT_TOKEN") or "e2e-" + "%032x" % random.getrandbits(128)
        app_url = a.app_url
        if not app_url:
            app_url = f"http://127.0.0.1:{a.ab_port}"
            self._start_ab(ab_env, app_url, cb_token)
            if not a.no_phone_sim:
                self._start_phone(app_url)
        self.app_url = app_url
        if not a.vh_url:
            self._start_vh(vh_env, app_url, public_token, cb_token)
        self.vh_url = a.vh_url or f"http://127.0.0.1:{a.vh_port}"

    def _spawn(self, cmd, env, cwd, log: Path, port=None):
        fh = open(log, "ab")
        p = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        if port:
            self.ports.append(port)
        return p

    def _start_ab(self, ab_env, app_url, cb_token):
        a = self.a
        env = {**os.environ, **ab_env}
        sh(self.compose + ["up", "-d", "--wait"], env={**os.environ, "TEST_POSTGRES_PORT": str(a.pg_port)},
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.db_up = True
        env.update(
            DATABASE_URL=f"postgresql+asyncpg://app_demo_test:app_demo_test@127.0.0.1:{a.pg_port}/app_demo_test",
            APP_ENV="test", HTTP_PORT=str(a.ab_port), PUBLIC_API_CLIENT_ID="e2e",
            PUBLIC_API_SCOPES="service:execute,requests:read", DELIVERY_TRANSPORT="webhook",
            DELIVERY_WEBHOOK_URL=f"http://127.0.0.1:{a.phone_port}/push",
        )
        env.pop("CALLBACK_URL", None)
        if cb_token and not a.no_callback:
            env.update(CALLBACK_URL=f"http://127.0.0.1:{a.vh_port}/internal/action-results",
                       CALLBACK_TOKEN=cb_token, CALLBACK_ALLOWED_HOSTS="127.0.0.1")
        else:
            env.pop("CALLBACK_TOKEN", None)
            env.pop("CALLBACK_ALLOWED_HOSTS", None)
        sh([str(AB / ".venv/bin/alembic"), "upgrade", "head"], env=env, cwd=AB, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL)
        self._spawn([str(AB / ".venv/bin/uvicorn"), "app.main:app", "--app-dir", "src", "--host", "127.0.0.1",
                     "--port", str(a.ab_port)], env, AB, self.work / "ab.log", a.ab_port)
        wait_http(f"{app_url}/health/live", 60, "AB")

    def _start_phone(self, app_url):
        a = self.a
        self.phone_log.unlink(missing_ok=True)
        cmd = [str(AB / ".venv/bin/python"), str(AB / "scripts/phone_sim.py"), "--app-url", app_url,
               "--port", str(a.phone_port), "--user-id", "e2e-user", "--glasses-id", a.glasses_id,
               "--log", str(self.phone_log)]
        if a.scenario:
            cmd += ["--scenario", a.scenario]
        self._spawn(cmd, {**os.environ}, AB, self.work / "phone_sim.out", a.phone_port)
        wait_http(f"http://127.0.0.1:{a.phone_port}/health", 60, "phone_sim")
        end = time.time() + 30  # chờ dòng `ready` (đã đăng ký thiết bị + ghép kính)
        while time.time() < end:
            if self.phone_log.exists() and '"ready"' in self.phone_log.read_text(encoding="utf-8"):
                return
            time.sleep(0.3)
        raise SystemExit("phone_sim không ready (đăng ký/ghép kính hỏng?) - xem phone_sim.out")

    def _start_vh(self, vh_env, app_url, public_token, cb_token):
        a = self.a
        env = {**os.environ, **vh_env}
        env.update(CUDA_VISIBLE_DEVICES=str(a.gpu), VISIONCARE_HOST_URL=app_url,
                   VISIONCARE_CLIENT_TOKEN=public_token, VISIONCARE_DEVICE_ID="e2e-wrong-default",  # khác id kính: lệnh mất device_ctx sẽ rơi vào id này và hỏng
                   VISIONCARE_DEVICE_CLIENT_TOKEN=self.device_token, VISIONCARE_CALLBACK_TOKEN=cb_token)
        self.vh_log.unlink(missing_ok=True)
        p = self._spawn([PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(a.vh_port),
                         "--ws-max-size", "2100000"],
                        env, ROOT, self.vh_log, a.vh_port)
        wait_http(f"http://127.0.0.1:{a.vh_port}/health", 420, "VH", p)

    def stop(self):
        for p in reversed(self.procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception:
                pass
        time.sleep(1.5)
        for port in self.ports:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.db_up:
            subprocess.run(self.compose + ["down", "-v"], env={**os.environ, "TEST_POSTGRES_PORT": str(self.a.pg_port)},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ───────────────────────────── log điện thoại / VH ─────────────────────────────

class PhoneLog:
    """Điện thoại giả (đọc JSONL) hoặc, khi --no-phone-sim, suy từ log VH ("<op> requested")."""

    def __init__(self, phone_path: Path | None, vh_path: Path):
        self.phone_path, self.vh_path = phone_path, vh_path

    def mark(self):
        return (len(self._phone()), len(self._vh_lines()))

    def _phone(self):
        if not self.phone_path or not self.phone_path.exists():
            return []
        out = []
        for line in self.phone_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rec["wall"] = datetime.fromisoformat(rec["ts"]).timestamp() if "ts" in rec else 0.0
            out.append(rec)
        return out

    def _vh_lines(self):
        return self.vh_path.read_text(encoding="utf-8", errors="replace").splitlines() if self.vh_path.exists() else []

    def commands(self, mark):
        if self.phone_path:
            return [r for r in self._phone()[mark[0]:] if r.get("event") == "command" and not r.get("duplicate")]
        now = time.time()
        return [{"action": f"{m.group(1)}_{m.group(2)}", "params": {}, "wall": now, "request_id": ""}
                for line in self._vh_lines()[mark[1]:] if (m := REQ_RE.search(line))]

    def reports(self, mark):
        return [r for r in self._phone()[mark[0]:] if r.get("event") == "report"]

    def asked_back(self, mark) -> int:
        return sum(1 for line in self._vh_lines()[mark[1]:] if ASK_MARK in line)

    def vh_count(self, mark, needle) -> int:
        return sum(1 for line in self._vh_lines()[mark[1]:] if needle in line)


# ───────────────────────────── kính giả lập ─────────────────────────────

class Turn:
    def __init__(self, text):
        self.text = text
        self.release_wall = self.release = self.reply_at = self.first_audio = self.end_at = None
        self.cues, self.live, self.has_audio, self.audio_bytes = [], None, False, 0
        self.error = None

    def ms(self, mark):
        v = getattr(self, mark)
        return None if v is None or self.release is None else round((v - self.release) * 1000)


class Glasses:
    def __init__(self, url, token, audio_fn, device=GLASSES):  # device = id kính (--glasses-id)
        self.url, self.token, self.audio_fn, self.device = url, token, audio_fn, device
        self.ws = None
        self.events: list[dict] = []  # {k: kind, perf, wall, ...}
        self._reader = None
        self._wake = asyncio.Event()
        self._n = 0

    async def connect(self):
        import websockets
        from pipeline.cues import CUE_VERSION

        self.ws = await websockets.connect(self.url.replace("http", "ws", 1) + "/v2/session", max_size=None)
        await self.ws.send(json.dumps({"t": "hello", "device": self.device, "token": self.token,
                                       "cue_version": CUE_VERSION, "fw": "e2e", "accept": "ima_adpcm",
                                       "debug": True}))  # khung debug (say/trace) để kiểm câu nói
        first = json.loads(await asyncio.wait_for(self.ws.recv(), 15))
        assert first["t"] == "hello_ok", first
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for msg in self.ws:
                ev = {"perf": time.perf_counter(), "wall": time.time()}
                if isinstance(msg, bytes):
                    ev.update(k="audio", n=len(msg) - 1)
                else:
                    ev.update(k="json", f=json.loads(msg))
                self.events.append(ev)
                self._wake.set()
        except Exception as exc:  # noqa: BLE001
            self.events.append({"perf": time.perf_counter(), "wall": time.time(), "k": "closed", "why": repr(exc)})
            self._wake.set()

    async def close(self):
        if self._reader:
            self._reader.cancel()
        if self.ws:
            await self.ws.close()

    def frames(self, t, since=0):
        return [e["f"] for e in self.events[since:] if e["k"] == "json" and e["f"].get("t") == t]

    async def wait_for(self, pred, timeout, since=0):
        end = time.perf_counter() + timeout
        while True:
            for e in self.events[since:]:
                if pred(e):
                    return e
            left = end - time.perf_counter()
            if left <= 0:
                return None
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), min(left, 0.25))
            except asyncio.TimeoutError:
                pass

    async def say(self, text, image: bytes | None = None, timeout=60, wait_end=True) -> Turn:
        audio = self.audio_fn(text)
        t = Turn(text)
        self._n += 1
        t.base = len(self.events)
        tid = f"t{self._n}-{int(time.time()) % 100000}"
        base = len(self.events)
        await self.ws.send(json.dumps({"t": "turn_start", "turn": tid, "t_press_ms": 0}))
        if image:
            await self.ws.send(b"\x01" + image)
        start = time.perf_counter()
        for i in range(0, len(audio), CHUNK):
            await asyncio.sleep(max(0.0, start + i / BYTE_RATE - time.perf_counter()))
            await self.ws.send(b"\x03" + audio[i:i + CHUNK])
        t.release, t.release_wall = time.perf_counter(), time.time()
        await self.ws.send(json.dumps({"t": "turn_end", "turn": tid, "t_release_ms": 0}))
        ev = await self.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply" and e["f"].get("turn") == tid,
                                 timeout, base)
        if ev is None:
            t.error = "không có khung reply"
            return t
        t.reply_at = ev["perf"]
        t.cues, t.live, t.has_audio = ev["f"].get("cues", []), ev["f"].get("live"), bool(ev["f"].get("audio"))
        if wait_end:
            end = await self.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end" and e["f"].get("turn") == tid,
                                      timeout, base)
            if end is None:
                t.error = "không có reply_end"
                return t
            t.end_at = end["perf"]
        aud = [e for e in self.events[base:] if e["k"] == "audio" and e["perf"] >= t.release]
        if aud:
            t.first_audio = aud[0]["perf"]
            t.audio_bytes = sum(e["n"] for e in aud)
        t.tid = tid
        return t

    def audio_after_wall(self, wall):
        return next((e for e in self.events if e["k"] == "audio" and e["wall"] > wall), None)

    async def cancel(self):
        await self.ws.send(json.dumps({"t": "cancel"}))


# ───────────────────────────── âm thanh / ảnh ─────────────────────────────

_tts_ready = False


def make_audio_fn(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)

    def fn(text: str, tail_s=0.3) -> bytes:
        if text == SILENCE:  # chỉ bấm nút rồi nhả: không có lời
            from pipeline import adpcm

            return adpcm.encode_blocks(b"\x00\x00" * 12000)
        key = re.sub(r"\W+", "_", text.lower()).strip("_")[:60] or "x"
        path = cache / f"{key}.adpcm"
        if path.exists() and path.stat().st_size > 0:
            return path.read_bytes()
        from pipeline import adpcm, tts

        pcm = b"".join(tts.synthesize_stream(text))
        data = adpcm.encode_blocks(b"\x00\x00" * 4000 + pcm + b"\x00\x00" * int(16000 * tail_s))
        path.write_bytes(data)
        return data

    return fn


def text_image(blur=0, w=1600, h=1200) -> bytes:
    import cv2
    import numpy as np

    img = np.full((h, w, 3), 245, np.uint8)
    lines = ["CHUONG 1. HANH TRINH", "Sang hom ay troi trong xanh, gio nhe thoi qua",
             "con duong dat do dan ve phia ngoi lang nho.", "Moi nguoi deu da thuc day tu rat som."]
    for i, line in enumerate(lines):
        cv2.putText(img, line, (160, 420 + i * 110), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 4)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def qvga(jpeg: bytes) -> bytes:
    import cv2
    import numpy as np

    img = cv2.resize(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), (320, 240))
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


# ───────────────────────────── kịch bản ─────────────────────────────

class Ctx:
    def __init__(self, g, plog, args, street):
        self.g, self.plog, self.args, self.street = g, plog, args, street


def result(name, ok, notes="", **kw):
    return {"name": name, "pass": bool(ok), "notes": notes, "first_audio_ms": None, "cmd_ms": None,
            "result_ms": None, "asked_back": False, **kw}


async def fire(c: Ctx, text, image=None, yes_words=("Đúng.", "Có.")):
    """Nói `text`; nếu server hỏi lại thì trả lời có. Trả (turn đầu, turn kích hoạt, đã hỏi lại)."""
    mark = c.plog.mark()
    t1 = await c.g.say(text, image)
    await asyncio.sleep(0.15)  # log VH ghi ngay trước khi reply, nhưng chờ file flush
    asked = c.plog.asked_back(mark) > 0
    t2 = t1
    if asked:
        t2 = await c.g.say(yes_words[0])
    return mark, t1, t2, asked


async def wait_cmd(c: Ctx, mark, action, timeout):
    end = time.time() + timeout
    while time.time() < end:
        for cmd in c.plog.commands(mark):
            if action is None or cmd["action"] == action:
                return cmd
        await asyncio.sleep(0.05)
    return None


async def result_spoken(c: Ctx, mark, cmd, timeout=8.0):
    """ms từ lúc ĐT báo kết quả tới khối audio đầu tiên sau đó (None = không nghe thấy gì)."""
    rep_wall = None
    end = time.time() + timeout
    while time.time() < end and rep_wall is None:
        for r in c.plog.reports(mark):
            if r["request_id"] == cmd["request_id"]:
                rep_wall = r["wall"]
        if rep_wall is None:
            await asyncio.sleep(0.1)
    if rep_wall is None:
        return None, None
    while time.time() < end:
        e = c.g.audio_after_wall(rep_wall)
        if e:
            return round((e["wall"] - cmd["wall"]) * 1000), rep_wall
        await asyncio.sleep(0.1)
    return None, rep_wall


async def command_scenario(c: Ctx, name, text, action, check=None, image=None, expect_report=None):
    mark, t1, t2, asked = await fire(c, text, image)
    cmd = await wait_cmd(c, mark, action, 9.0)
    r = result(name, False, asked_back=asked, first_audio_ms=t1.ms("first_audio"))
    if t1.error:
        r["notes"] = f"lượt 1: {t1.error}"
        return r
    got = [x["action"] for x in c.plog.commands(mark)]
    if cmd is None:
        r["notes"] = f"không có lệnh '{action}' tới ĐT (nhận: {got or 'không gì'})"
        return r
    r["cmd_ms"] = round((cmd["wall"] - t2.release_wall) * 1000)
    ok, why = True, ""
    if not c.plog.phone_path and c.plog.vh_count(mark, "VisionCare API HTTPError"):
        ok, why = False, "app server từ chối lệnh (HTTPError trong log VH)"
    if c.plog.phone_path:
        if check:
            ok, why = check(cmd)
        reps = c.plog.reports(mark)
        rep = next((x for x in reps if x["request_id"] == cmd["request_id"]), None)
        end = time.time() + 5
        while rep is None and time.time() < end:
            await asyncio.sleep(0.1)
            rep = next((x for x in c.plog.reports(mark) if x["request_id"] == cmd["request_id"]), None)
        if rep is None:
            ok, why = False, "ĐT không báo kết quả"
        elif expect_report and (rep.get("code") if expect_report != "ok" else rep["state"]) != (
                "succeeded" if expect_report == "ok" else expect_report):
            ok, why = False, f"report {rep['state']}/{rep.get('code')} != {expect_report}"
        r["report"] = f"{rep['state']}/{rep.get('code')}" if rep else None
    r["result_ms"], _ = await result_spoken(c, mark, cmd) if c.plog.phone_path else (None, None)
    if r["result_ms"] is None and c.plog.phone_path:
        r["flag"] = "kết quả KHÔNG được đọc cho người dùng"
    if len(got) != 1 and action not in ("ride_confirm",):
        extra = [a for a in got if a != action]
        if extra:
            ok, why = False, f"lệnh ngoài ý muốn: {extra}"
    if r.get("flag"):  # người dùng không nghe được kết quả = luồng chưa đúng, dù lệnh tới ĐT đúng
        ok, why = False, (why + "; " if why else "") + r["flag"]
    r["pass"], r["notes"] = ok, why or "ok"
    return r


def prm(key, contains):
    return lambda cmd: ((contains.lower() in str(cmd["params"].get(key, "")).lower()),
                        f"{key}={cmd['params'].get(key)!r}")


NAMES = {"single": "mẹ", "multi": "Nam"}  # --contact-single / --contact-multi (điện thoại thật dùng tên trong danh bạ của bạn)


async def sc_call_mom(c):
    n = NAMES["single"]
    return await command_scenario(c, "call_mom", f"Gọi cho {n}.", "contact_call", prm("name", n), expect_report="ok")


async def sc_call_nam(c):
    n = NAMES["multi"]
    return await command_scenario(c, "call_nam", f"Gọi cho {n}.", "contact_call", prm("name", n),
                                  expect_report="MULTIPLE_CONTACTS_FOUND")


async def _cancel_run(c, name, how):
    mark, t1, t2, asked = await fire(c, f"Gọi cho {NAMES['single']}.")
    r = result(name, False, asked_back=asked, first_audio_ms=t1.ms("first_audio"))
    if t2.error:
        r["notes"] = t2.error
        return r
    # cửa sổ huỷ: lệnh chờ cho tới khi đọc xong (>= 1,5 s); huỷ ngay sau reply_end
    if how == "cancel_frame":
        await c.g.cancel()
    elif how == "new_turn":
        await c.g.say("Kể cho tôi một câu chuyện cười ngắn.", wait_end=False)
    elif how == "disconnect":
        await c.g.close()
    await asyncio.sleep(7.0)
    got = [x["action"] for x in c.plog.commands(mark)]
    r["pass"] = not got
    r["notes"] = "ĐT không nhận lệnh nào" if not got else f"ĐT vẫn nhận: {got}"
    if how == "disconnect":
        await c.g.connect()
    return r


async def sc_cancel_frame(c):
    return await _cancel_run(c, "call_cancel", "cancel_frame")


async def sc_cancel_newturn(c):
    return await _cancel_run(c, "call_cancel_newturn", "new_turn")


async def sc_cancel_disconnect(c):
    return await _cancel_run(c, "call_cancel_disconnect", "disconnect")


async def sc_ride(c):
    """Lượt "đặt xe" gửi `ride_quote` ngay; lượt "xác nhận" gửi `ride_confirm {quote_id, confirm:true}`."""
    r1 = await command_scenario(c, "ride_quote", "Đặt xe đến chợ Bến Thành.", "ride_quote", prm("destination", "bến thành"),
                                expect_report="ok")
    if r1["cmd_ms"] is None:
        r1["name"] = "ride"
        return r1
    await asyncio.sleep(1.0)  # quote_id về VH qua callback
    r2 = await command_scenario(
        c, "ride_confirm", "Đồng ý, xác nhận đặt xe.", "ride_confirm",
        lambda cmd: (str(cmd["params"].get("quote_id", "")).startswith("quote-") and cmd["params"].get("confirm") is True,
                     f"params={cmd['params']}"), expect_report="ok")
    out = result("ride", r1["pass"] and r2["pass"], f"quote: {r1['notes']}; confirm: {r2['notes']}",
                 first_audio_ms=r1["first_audio_ms"], cmd_ms=r1["cmd_ms"], result_ms=r1["result_ms"],
                 asked_back=r1["asked_back"] or r2["asked_back"])
    out["confirm_cmd_ms"], out["confirm_result_ms"] = r2["cmd_ms"], r2["result_ms"]
    out["flag"] = r1.get("flag") or r2.get("flag")
    return out


async def sc_ride_cancel(c):
    """Hủy sau báo giá: `ride_confirm {quote_id, confirm:false}` (hợp đồng: huỷ = confirm false)."""
    r1 = await command_scenario(c, "ride_quote", "Đặt xe đến chợ Bến Thành.", "ride_quote", expect_report="ok")
    if r1["cmd_ms"] is None:
        r1["name"] = "ride_cancel"
        return r1
    await asyncio.sleep(1.0)
    r2 = await command_scenario(
        c, "ride_cancel", "Hủy chuyến xe.", "ride_confirm",
        lambda cmd: (str(cmd["params"].get("quote_id", "")).startswith("quote-") and cmd["params"].get("confirm") is False,
                     f"params={cmd['params']}"), expect_report="ok")
    r2["notes"] = f"quote: {r1['notes']}; cancel: {r2['notes']}"
    r2["pass"] = r2["pass"] and r1["pass"]
    return r2


async def sc_music(c):
    """phát -> "tăng âm lượng" LÚC ĐANG PHÁT (có lời: music_volume, không phải dừng) -> chỉ bấm nút = dừng."""
    steps = [await command_scenario(c, "music_play", "Mở bài Lạc trôi của Sơn Tùng.", "music_play", expect_report="ok")]
    if steps[0]["cmd_ms"] is not None:
        steps.append(await command_scenario(c, "music_volume(đang phát)", "Tăng âm lượng lên.", "music_volume", expect_report="ok"))
        steps.append(await command_scenario(c, "music_stop(bấm nút)", SILENCE, "music_stop", expect_report="ok"))
    out = result("music_play>volume>stop", all(s["pass"] for s in steps) and len(steps) == 3,
                 "; ".join(f"{s['name']}={'ok' if s['pass'] else s['notes']}" for s in steps),
                 first_audio_ms=steps[0]["first_audio_ms"], cmd_ms=steps[0]["cmd_ms"], result_ms=steps[0]["result_ms"],
                 asked_back=any(s["asked_back"] for s in steps))
    out["sub"] = steps
    out["flag"] = next((s["flag"] for s in steps if s.get("flag")), None)
    return out


async def sc_emergency(c):
    """ĐƯỜNG DỰ PHÒNG khẩn cấp (SIM): kính chưa có token riêng/phiên thì `emergency_call` đi `emergency/call` tới điện thoại
    chủ kính (SMS [SOS] + gọi). Đường chính qua internet (AB gọi người thân) được kiểm ở tools/e2e_calls.py."""
    return await command_scenario(c, "emergency", "Cấp cứu, gọi người thân giúp tôi.", "emergency_call", expect_report="ok")


async def sc_chat(c):
    mark = c.plog.mark()
    t = await c.g.say("Kể cho tôi một câu chuyện cười ngắn.")
    await asyncio.sleep(5.0)
    got = [x["action"] for x in c.plog.commands(mark)]
    ok = not got and t.first_audio is not None and not t.error
    return result("chat_no_command", ok, "không lệnh nào" if ok else f"{t.error or ''} lệnh={got} audio={t.first_audio is not None}",
                  first_audio_ms=t.ms("first_audio"))


async def _feed_street(g, src, stop):
    """Gửi khung 0x04 8 fps; `src["f"]` đổi được giữa chừng (đường phố / khung trống để reset chống-làm-phiền)."""
    while not stop.is_set() and src["f"]:
        await g.ws.send(b"\x04" + src["f"])
        await asyncio.sleep(0.125)


def blank_frame() -> bytes:
    import cv2
    import numpy as np

    return cv2.imencode(".jpg", np.full((240, 320, 3), 128, np.uint8))[1].tobytes()


async def sc_nav(c):
    """Dẫn đường = chỉ gửi lộ trình về ĐT (không live): lệnh navigation_start + maps_url, câu kết quả, chat giữa chừng, bấm nút = navigation_stop.

    Hazard/live nav nằm ở kịch bản `alert`."""
    g = c.g
    mark, t1, t2, asked = await fire(c, "Dẫn tôi đến chợ Bến Thành.")
    r = result("nav_send_stop", False, asked_back=asked, first_audio_ms=t1.ms("first_audio"))
    problems = []
    if t2.live is not None:
        problems.append(f"reply.live={t2.live!r} (dẫn đường không còn mở live)")
    cmd = await wait_cmd(c, mark, "navigation_start", 9.0)
    if cmd is None:
        r["notes"] = "; ".join(problems + ["không có lệnh navigation_start tới ĐT"])
        return r
    r["cmd_ms"] = round((cmd["wall"] - t2.release_wall) * 1000)
    if c.plog.phone_path:
        url = cmd.get("maps_url") or ""
        if "google.com/maps/dir" not in url or "destination=" not in url:
            problems.append(f"payload thiếu maps_url Google Maps (maps_url={url!r})")
        r["result_ms"], _ = await result_spoken(c, mark, cmd, 10.0)
        if r["result_ms"] is None:
            problems.append("kết quả gửi chỉ đường KHÔNG được đọc")
    # câu kết quả (khung `say` của result-*): phải nói "đã gửi về điện thoại, mở thông báo", không nói ĐT tự mở bản đồ
    end = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end"
                           and str(e["f"].get("turn", "")).startswith("result-"), 10, t2.base)
    if end is None:
        problems.append("không có lượt result-* (kết quả chưa được đọc)")
    else:
        txt = " ".join(f["text"] for f in g.frames("say", t2.base) if f["turn"] == end["f"]["turn"])
        r["result_text"] = txt
        if not (txt.startswith("Đã gửi chỉ đường tới") and "về điện thoại" in txt
                and "Mở thông báo để đi bằng Google Maps" in txt):
            problems.append(f"câu kết quả lạ: {txt!r}")
    if g.frames("cam", t2.base):
        problems.append("có khung `cam` sau nav_start (dẫn đường không được mở live)")
    # hỏi thường lúc đang dẫn đường: không sinh lệnh nào thêm
    chat = await g.say("Kể cho tôi một câu chuyện cười ngắn.")
    if chat.first_audio is None:
        problems.append("câu chat giữa chừng không có tiếng")
    extra = [x["action"] for x in c.plog.commands(mark) if x["action"] != "navigation_start"]
    if extra:
        problems.append(f"câu chat giữa chừng sinh lệnh {extra}")
    stop_t = await g.say(SILENCE)  # chỉ bấm nút = dừng chỉ đường
    stop_cmd = await wait_cmd(c, mark, "navigation_stop", 9.0)
    if stop_cmd is None:
        problems.append("không có lệnh navigation_stop tới ĐT")
    else:
        r["stop_ms"] = round((stop_cmd["wall"] - stop_t.release_wall) * 1000)
        if c.plog.phone_path and not stop_cmd["params"].get("navigation_id"):
            problems.append("navigation_stop thiếu navigation_id")
    r["pass"] = not problems
    r["notes"] = "; ".join(problems) or "nav_start -> navigation_start + maps_url + câu kết quả (không live) -> chat -> bấm nút -> navigation_stop"
    return r


async def sc_alert(c):
    """Chỉ bật cảnh báo vật cản (không có chỉ đường trên ĐT): lượt chat giữa chừng KHÔNG được tắt live, không sinh lệnh.

    Ảnh đường phố phải có vật cản đạt mức >= HAZARD_MIN_LEVEL (2) thì mới có khung hazard (box mức 0-1 không kêu)."""
    g = c.g
    street = qvga(Path(c.street).read_bytes()) if c.street else None
    mark = c.plog.mark()
    t = await g.say("Bật cảnh báo vật cản.")
    r = result("alert_live_survives_chat", False, first_audio_ms=t.ms("first_audio"))
    if street is None:
        r["notes"] = "thiếu ảnh vật cản mức >= 2 (--street / E2E_STREET_IMAGE): không kiểm được live nav"
        return r
    if t.live != "nav":
        r["notes"] = f"reply.live={t.live!r} cues={t.cues} (mong 'nav')"
        return r
    cam = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "cam", 8, t.base)
    stop, src = asyncio.Event(), {"f": street}
    feeder = asyncio.create_task(_feed_street(g, src, stop))
    problems = []
    try:
        haz = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "hazard", 10, t.base)
        if cam is None:
            problems.append("không có khung cam")
        if haz is None:
            problems.append("không có hazard: ảnh --street không đạt mức vật cản >= 2 (hoặc live nav không chạy)")
        n = len(g.events)
        n_t = time.perf_counter() - 1.0
        chat = await g.say("Kể cho tôi một câu chuyện cười ngắn.")
        ended = g.frames("end", n)
        if ended:
            problems.append("lượt chat làm live nav kết thúc (end)")
        if chat.first_audio is None:
            problems.append("lượt chat không có tiếng")
        # live còn SỐNG thật: reset chống-làm-phiền bằng khung trống rồi cho đường phố lại -> phải có hazard mới
        src["f"] = blank_frame()
        await asyncio.sleep(1.0)
        await asyncio.sleep(max(0.0, 5.5 - (time.perf_counter() - n_t)))
        n4 = len(g.events)
        src["f"] = street
        again = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "hazard", 6, n4)
        if again is None:
            problems.append("sau lượt chat live nav không còn phát hazard (đã chết?)")
        cmds = [x["action"] for x in c.plog.commands(mark)]
        if cmds:
            problems.append(f"sinh lệnh {cmds}")
        r["alive_hazards_after_chat"] = len(g.frames("hazard", n))
    finally:
        stop.set()
        await feeder
    await g.cancel()
    r["pass"] = not problems
    r["notes"] = "; ".join(problems) or f"live sống sau lượt chat (hazard sau chat: {r.get('alive_hazards_after_chat')})"
    return r


async def _ocr_run(c, name, image, want_live):
    g = c.g
    t = await g.say("Đọc giúp tôi trang sách này.", image)
    r = result(name, False)
    if not want_live:
        aud = next((e for e in g.events[t.base:] if e["k"] == "audio" and e["perf"] >= t.release), None)
        r["first_audio_ms"] = round((aud["perf"] - t.release) * 1000) if aud else None
        r["pass"] = t.live is None and aud is not None and not t.error
        r["notes"] = f"đọc thẳng ảnh buffer (live={t.live}, audio {sum(e['n'] for e in g.events[t.base:] if e['k']=='audio')} B)"
        return r
    if t.live != "ocr":
        r["notes"] = f"live={t.live!r}, cues={t.cues}: không vào OCR live (mong 'ocr')"
        return r
    cam = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "cam", 8, t.base)
    good = text_image()
    cap_sent, n0 = [], len(g.events)

    async def feed():
        while True:
            await g.ws.send(b"\x04" + qvga(good))
            await asyncio.sleep(0.2)

    async def serve_capture():
        seen = n0
        while True:
            await asyncio.sleep(0.1)
            for e in g.events[seen:]:
                if e["k"] == "json" and e["f"].get("t") == "capture":
                    await g.ws.send(b"\x04" + good)
                    cap_sent.append(time.time())
            seen = len(g.events)

    feeder, server = asyncio.create_task(feed()), asyncio.create_task(serve_capture())
    try:
        end = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "end", 45, n0)
    finally:
        feeder.cancel()
        server.cancel()
    aud = [e for e in g.events[n0:] if e["k"] == "audio"]
    r["first_audio_ms"] = round((aud[0]["perf"] - t.release) * 1000) if aud else None
    r["pass"] = cam is not None and end is not None and bool(aud)
    r["notes"] = (f"cam={'có' if cam else 'KHÔNG'}, capture gửi {len(cap_sent)} lần, đọc {sum(e['n'] for e in aud)} B, "
                  f"end={'có' if end else 'KHÔNG'}")
    return r


async def sc_ocr_direct(c):
    return await _ocr_run(c, "ocr_direct", text_image(), False)


async def sc_ocr_live(c):
    return await _ocr_run(c, "ocr_live", text_image(blur=14), True)


SCENARIOS = {
    # Gọi điện đã chuyển sang AB + WS /v2/call (không còn lệnh `contact_call` tới điện thoại): kịch bản gọi/huỷ gọi nằm ở
    # tools/e2e_calls.py. sc_call_mom/sc_call_nam/sc_cancel_* giữ lại bên dưới chỉ để tham khảo, KHÔNG nằm trong SCENARIOS.
    "ride": sc_ride, "ride_cancel": sc_ride_cancel, "music": sc_music, "nav": sc_nav, "alert": sc_alert, "emergency": sc_emergency, "chat": sc_chat,
    "ocr_direct": sc_ocr_direct, "ocr_live": sc_ocr_live,
}


# ───────────────────────────── main ─────────────────────────────

def fmt(v):
    return "-" if v is None else str(v)


def table(results):
    lines = ["| Kịch bản | PASS | hỏi lại | nhả nút→tiếng đầu (ms) | nhả nút→lệnh ĐT (ms) | lệnh→kết quả đọc (ms) | ghi chú |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        note = r["notes"] + (f" **[{r['flag']}]**" if r.get("flag") else "")
        lines.append(f"| {r['name']} | {'PASS' if r['pass'] else 'FAIL'} | {'có' if r['asked_back'] else 'không'} | "
                     f"{fmt(r['first_audio_ms'])} | {fmt(r['cmd_ms'])} | {fmt(r['result_ms'])} | {note} |")
    return "\n".join(lines)


async def run(args, stack: Stack):
    audio_fn = make_audio_fn(Path(args.cache))
    names = args.only or list(SCENARIOS)
    # sinh sẵn mọi câu nói để việc dựng TTS không lọt vào thời gian đo
    for text in [f"Gọi cho {NAMES['single']}.", f"Gọi cho {NAMES['multi']}.", "Đúng.", "Có.", "Đặt xe đến chợ Bến Thành.", "Đồng ý, xác nhận đặt xe.",
                 "Mở bài Lạc trôi của Sơn Tùng.", "Tăng âm lượng lên.", "Dừng nhạc lại.", "Dẫn tôi đến chợ Bến Thành.",
                 "Dừng chỉ đường.", "Cấp cứu, gọi người thân giúp tôi.", "Kể cho tôi một câu chuyện cười ngắn.",
                 "Đọc giúp tôi trang sách này.", "Bật cảnh báo vật cản.", "Hủy chuyến xe.", SILENCE]:
        audio_fn(text)
    plog = PhoneLog(stack.phone_log if not args.no_phone_sim else None, stack.vh_log)
    results = []
    for name in names:
        g = Glasses(stack.vh_url, stack.device_token, audio_fn, args.glasses_id)
        await g.connect()
        c = Ctx(g, plog, args, args.street)
        await g.ws.send(json.dumps({"t": "cancel"}))
        await asyncio.sleep(0.5)
        t0 = time.time()
        try:
            r = await asyncio.wait_for(SCENARIOS[name](c), 180)
        except Exception as exc:  # noqa: BLE001
            r = result(name, False, f"ngoại lệ: {exc!r}")
        r["secs"] = round(time.time() - t0, 1)
        results.append(r)
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['notes']}  asked={r['asked_back']} "
              f"audio={r['first_audio_ms']} cmd={r['cmd_ms']} result={r['result_ms']}", flush=True)
        try:
            await g.close()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1.0)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--app-url", help="app server có sẵn (không dựng AB/postgres); vd. app server thật của người dùng")
    ap.add_argument("--vh-url", help="VH voice server có sẵn (không tự dựng)")
    ap.add_argument("--no-phone-sim", action="store_true", help="điện thoại THẬT: lệnh suy từ log VH, không kiểm tham số/report")
    ap.add_argument("--glasses-id", default=GLASSES, help="id kính trong hello; với điện thoại thật = device_id kính đã ghép trong app")
    ap.add_argument("--contact-single", default="mẹ", help="tên có đúng 1 số trong danh bạ (call_mom, call_cancel*)")
    ap.add_argument("--contact-multi", default="Nam", help="tên có >= 2 số khác nhau (call_nam: MULTIPLE_CONTACTS_FOUND)")
    ap.add_argument("--only", nargs="*", choices=list(SCENARIOS))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--gpu", default=os.environ.get("CUDA_VISIBLE_DEVICES", "2"))
    ap.add_argument("--vh-port", type=int, default=18893)
    ap.add_argument("--ab-port", type=int, default=18001)
    ap.add_argument("--phone-port", type=int, default=18002)
    ap.add_argument("--pg-port", type=int, default=55435)
    ap.add_argument("--compose-project", default="vh-e2e-full")
    ap.add_argument("--scenario", help="JSON kịch bản cho phone_sim (danh bạ, độ trễ...)")
    ap.add_argument("--no-callback", action="store_true", help="AB không gọi callback VH (VH chỉ poll)")
    ap.add_argument("--street", default=os.environ.get("E2E_STREET_IMAGE", str(ROOT / "tools" / "assets" / "hazard_level2.jpg")),
                    help="ảnh có vật cản mức >= HAZARD_MIN_LEVEL (2) cho kịch bản alert; mặc định ảnh nhỏ nằm trong repo")
    ap.add_argument("--vh-env", dest="vh_env", default=str(next((p for p in (ROOT / ".env", SEEVIA / "visioncare-host-demo" / ".env") if p.exists()), ROOT / ".env")))
    ap.add_argument("--ab-env", dest="ab_env", default=str(SEEVIA / ".env"))
    ap.add_argument("--workdir", default=str(ROOT / "results" / "e2e_full"))
    ap.add_argument("--cache", default=str(ROOT / "tools" / "board_audio" / "e2e"))
    ap.add_argument("--json-out")
    args = ap.parse_args()
    NAMES["single"], NAMES["multi"] = args.contact_single, args.contact_multi
    if args.app_url:
        args.no_phone_sim = True  # app server ngoài: không có phone_sim của mình, điện thoại là máy thật
    if args.street and not Path(args.street).exists():
        args.street = None
    stack = Stack(args)
    code = 1
    try:
        stack.start()
        results = asyncio.run(run(args, stack))
        print("\n" + table(results))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        code = 0 if all(r["pass"] for r in results) else 1
    finally:
        if not args.keep:
            stack.stop()
    sys.exit(code)


if __name__ == "__main__":
    main()
