# ruff: noqa
"""E2E gọi điện / nhắn tin / khẩn cấp: kính giả lập <-> VH <-> AB <-> người thân giả lập (relative_sim).

Dựng cả stack riêng (postgres test + AB uvicorn DELIVERY_TRANSPORT=webhook + phone_sim của chủ kính +
relative_sim cho 3 người thân + VH), mỗi người thân là một tài khoản thật trên AB (đăng ký, OTP, lời mời care_links).
Kính giả lập dùng TOKEN RIÊNG của kính (file `device_tokens.json` trong workdir) vì gọi điện/nhắn tin chỉ chạy với token riêng.
Lời nói của kính = giọng tổng hợp (VieNeu -> ADPCM, phát đúng nhịp thời gian thực) qua STT/Gemma thật như `e2e_full.py`;
âm thanh cuộc gọi = nguồn im lặng + tiếng "tách" 5 ms mỗi giây ở CẢ HAI đầu (kính gửi 0x05 ADPCM, người thân gửi PCM16
qua `WS /v2/call`), dò tách ở đầu kia bằng tương quan chéo.

Cách đo trễ một chiều: mẫu n của nguồn được "thu" lúc `t0 + n/16000`; khung chứa nó gửi đi khi khung đầy; trễ = (giờ khối/khung
đầu tiên chứa HẾT tiếng tách tới đầu kia) - (giờ thu xong tiếng tách). Gồm gói khung 20 ms (người thân) hoặc khối ADPCM 31,6 ms (kính),
cầu VH, đệm chống giật 60 ms (hướng app -> kính), socket loopback. Cùng một máy nên cùng đồng hồ. KHÔNG gồm mạng thật/Cloudflare,
mic/loa/AEC của kính.

    python tools/e2e_calls.py --gpu 0                     # dựng stack riêng (cổng 18895/18011/18012/18013/55436), chạy hết
    python tools/e2e_calls.py --gpu 0 --only call_mom call_nam
    python tools/e2e_calls.py --gpu 0 --keep              # giữ stack (workdir/stack.json) để chạy lại nhanh
    python tools/e2e_calls.py --attach                    # dùng stack đã --keep
    python tools/e2e_calls.py --stop                      # tắt stack đã --keep

KHÔNG dùng cổng 18888/8001 của người dùng. Chuông rút ngắn bằng cấu hình `--ring-s` (CALL_RING_TIMEOUT_S ở cả AB và VH);
hằng số mặc định không bị sửa. Token đọc từ .env, không in ra.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_full as base  # noqa: E402
from e2e_full import AB, PY, ROOT, SEEVIA, read_env, sh, wait_http  # noqa: E402
from pipeline import adpcm  # noqa: E402

SR = 16000
CLICK_N = 80
AMP = 12000
FRAME = 320  # 20 ms
GLASSES = "e2e-glasses"
OWNER_PHONE, OWNER_NAME = "0911000000", "Cô Sáu"
MOM, NAMANH, NAMBINH = "0911000001", "0911000002", "0911000003"
RELATIVES = {  # phone -> (display_name, aliases, emergency, priority)
    MOM: ("Mẹ", ["mẹ", "má"], True, 0),
    NAMANH: ("Nam Anh", ["nam"], False, 0),
    NAMBINH: ("Nam Bình", ["nam"], True, 1),
}
NAME_OF = {p: v[0] for p, v in RELATIVES.items()}


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# ───────────────────────────── nguồn tách + dò tương quan chéo ─────────────────────────────

def click_template() -> np.ndarray:
    """Giống `relative_sim.click_template` (LCG xác định)."""
    state, out = 20_261_020, []
    for _ in range(CLICK_N):
        state = (state * 1_103_515_245 + 12_345) & 0x7FFFFFFF
        out.append((state % (2 * AMP + 1)) - AMP)
    return np.array(out, dtype=np.int16)


CLICK = click_template()


def signal_frame(i: int, first: int, period: int) -> bytes:
    start = i * FRAME
    buf = np.zeros(FRAME, dtype=np.int16)
    k = max(0, (start - first - CLICK_N) // period)
    while True:
        c0 = first + k * period
        if c0 >= start + FRAME:
            break
        lo, hi = max(c0, start), min(c0 + CLICK_N, start + FRAME)
        if hi > lo:
            buf[lo - start:hi - start] = CLICK[lo - c0:hi - c0]
        k += 1
    return buf.tobytes()


def find_clicks(pcm: np.ndarray) -> list[int]:
    """Vị trí mẫu bắt đầu mỗi tiếng tách trong `pcm` (tương quan chéo với mẫu tách; gộp đỉnh gần nhau)."""
    if len(pcm) < CLICK_N:
        return []
    x, h = pcm.astype(np.float64), CLICK.astype(np.float64)
    n = 1 << (len(x) + len(h)).bit_length()
    corr = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(h, n)), n)[: len(x) - len(h) + 1]
    thr = 0.35 * float(np.dot(h, h))
    idx = np.where(corr > thr)[0]
    peaks: list[int] = []
    group: list[int] = []
    for i in idx:
        if group and i - group[-1] > SR // 4:
            peaks.append(group[int(np.argmax(corr[group]))])
            group = []
        group.append(int(i))
    if group:
        peaks.append(group[int(np.argmax(corr[group]))])
    return peaks


def one_way_delays(pcm: np.ndarray, arrivals: list[tuple[float, int]], tx_t0: float, first_s: float,
                   period_s: float) -> list[float]:
    """Trễ (ms) của từng tiếng tách dò được. `arrivals` = [(giờ tới, số MẪU của gói)] theo thứ tự tới."""
    cum = np.cumsum([n for _, n in arrivals])
    out = []
    for p in find_clicks(pcm):
        j = int(np.searchsorted(cum, p + CLICK_N - 1, side="right"))
        if j >= len(arrivals):
            continue
        arrive = arrivals[j][0]
        k = int(np.floor(((arrive - tx_t0) - first_s - CLICK_N / SR) / period_s))
        if k < 0:
            continue
        done = tx_t0 + first_s + k * period_s + CLICK_N / SR
        d = (arrive - done) * 1000.0
        if 0 <= d < period_s * 900:
            out.append(d)
    return out


def stat(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    a = np.array(xs)
    return {"n": len(xs), "p50": round(float(np.percentile(a, 50))), "p90": round(float(np.percentile(a, 90))),
            "min": round(float(a.min())), "max": round(float(a.max()))}


def fmt_stat(s: dict | None) -> str:
    return "-" if not s or not s.get("n") else f"{s['p50']}/{s['p90']} (n={s['n']})"


# ───────────────────────────── stack ─────────────────────────────

class CallStack(base.Stack):
    def __init__(self, a):
        super().__init__(a)
        self.info: dict = {}

    @property
    def state_file(self) -> Path:
        return self.work / "stack.json"

    def start(self):
        a = self.a
        vh_env, ab_env = read_env(Path(a.vh_env)), read_env(Path(a.ab_env))
        public_token = os.environ.get("VISIONCARE_CLIENT_TOKEN") or ab_env.get("VISIONCARE_CLIENT_TOKEN", "")
        cb_token = ab_env.get("VISIONCARE_CALLBACK_TOKEN") or vh_env.get("VISIONCARE_CALLBACK_TOKEN", "")
        self.ab_url = f"http://127.0.0.1:{a.ab_port}"
        self.vh_url = f"http://127.0.0.1:{a.vh_port}"
        self.rel_url = f"http://127.0.0.1:{a.rel_port}"
        self.ab_log = self.work / "ab.log"
        self.rel_log = self.work / "relative_sim_log.jsonl"
        self.rel_log.unlink(missing_ok=True)
        self.ab_log.unlink(missing_ok=True)
        self._start_ab(ab_env, cb_token)
        owner = self._account(OWNER_PHONE, OWNER_NAME)
        self._start_phone(owner["public_user_id"])
        self._start_rel()
        self._invite(owner)
        self.device_token = "e2e-" + hashlib.sha256(os.urandom(16)).hexdigest()
        tokens = self.work / "device_tokens.json"
        tokens.write_text(json.dumps({a.glasses_id: hashlib.sha256(self.device_token.encode()).hexdigest()}), encoding="utf-8")
        os.chmod(tokens, 0o600)
        self._start_vh2(vh_env, public_token, cb_token, owner["public_user_id"], tokens)
        self.info = {"vh_url": self.vh_url, "ab_url": self.ab_url, "rel_url": self.rel_url, "owner": owner,
                     "device_token": self.device_token, "ring_s": a.ring_s, "ports": self.ports,
                     "pids": [p.pid for p in self.procs], "compose_project": a.compose_project, "pg_port": a.pg_port}
        self.state_file.write_text(json.dumps(self.info), encoding="utf-8")
        os.chmod(self.state_file, 0o600)

    def _start_ab(self, ab_env, cb_token):
        a = self.a
        env = {**os.environ, **ab_env}
        sh(self.compose + ["up", "-d", "--wait"], env={**os.environ, "TEST_POSTGRES_PORT": str(a.pg_port)},
           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.db_up = True
        env.update(
            DATABASE_URL=f"postgresql+asyncpg://app_demo_test:app_demo_test@127.0.0.1:{a.pg_port}/app_demo_test",
            APP_ENV="test", HTTP_PORT=str(a.ab_port), PUBLIC_API_CLIENT_ID="e2e",
            PUBLIC_API_SCOPES="service:execute,requests:read,calls:manage", DELIVERY_TRANSPORT="webhook",
            DELIVERY_WEBHOOK_URL=f"http://127.0.0.1:{a.rel_port}/push",
            CALLBACK_URL=f"http://127.0.0.1:{a.vh_port}/internal/action-results", CALLBACK_TOKEN=cb_token,
            CALLBACK_ALLOWED_HOSTS="127.0.0.1", CALL_MEDIA_URL=f"ws://127.0.0.1:{a.vh_port}/v2/call",
            CALL_RING_TIMEOUT_S=str(a.ring_s), LOG_LEVEL="info",
        )
        sh([str(AB / ".venv/bin/alembic"), "upgrade", "head"], env=env, cwd=AB, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL)
        self._spawn([str(AB / ".venv/bin/uvicorn"), "app.main:app", "--app-dir", "src", "--host", "127.0.0.1",
                     "--port", str(a.ab_port)], env, AB, self.ab_log, a.ab_port)
        wait_http(f"{self.ab_url}/health/live", 60, "AB")

    def _account(self, phone, name) -> dict:
        offset = self.ab_log.stat().st_size if self.ab_log.exists() else 0
        with httpx.Client(base_url=self.ab_url, timeout=15) as c:
            r = c.post("/api/v1/auth/register", json={"phone_number": phone, "password": "owner-pass-1", "display_name": name})
            if r.status_code == 409:
                r = c.post("/api/v1/auth/login", json={"phone_number": phone, "password": "owner-pass-1"})
            else:
                r.raise_for_status()
                end, code = time.time() + 15, None
                while time.time() < end and code is None:
                    txt = self.ab_log.read_bytes()[offset:].decode("utf-8", "replace")
                    m = re.findall(r"Demo OTP for (\S+): (\d+)", txt)
                    code = next((cd for p, cd in m if p.endswith(phone[-9:])), None)
                    time.sleep(0.2)
                if code is None:
                    raise SystemExit("không thấy OTP trong ab.log")
                r = c.post("/api/v1/auth/otp/verify", json={"phone_number": phone, "otp_code": code})
            r.raise_for_status()
            d = r.json()["data"]
        return {"public_user_id": d["public_user_id"], "access_token": d["access_token"], "phone": phone}

    def _start_phone(self, owner_pub):
        a = self.a
        self.phone_log.unlink(missing_ok=True)
        cmd = [str(AB / ".venv/bin/python"), str(AB / "scripts/phone_sim.py"), "--app-url", self.ab_url,
               "--port", str(a.phone_port), "--user-id", owner_pub, "--glasses-id", a.glasses_id,
               "--log", str(self.phone_log)]
        self._spawn(cmd, {**os.environ}, AB, self.work / "phone_sim.out", a.phone_port)
        wait_http(f"http://127.0.0.1:{a.phone_port}/health", 60, "phone_sim")
        end = time.time() + 30
        while time.time() < end:
            if self.phone_log.exists() and '"ready"' in self.phone_log.read_text(encoding="utf-8"):
                return
            time.sleep(0.3)
        raise SystemExit("phone_sim không ready")

    def _start_rel(self):
        a = self.a
        scenario = self.work / "relative_scenario.json"
        scenario.write_text(json.dumps({
            "names": {p: n for p, n in NAME_OF.items()},
            "defaults": {"incoming": "ignore", "answer_delay_s": 1.0, "hangup_after_s": None, "media": True},
        }, ensure_ascii=False), encoding="utf-8")
        cmd = [str(AB / ".venv/bin/python"), str(AB / "scripts/relative_sim.py"), "--app-url", self.ab_url,
               "--port", str(a.rel_port), "--scenario", str(scenario), "--log", str(self.rel_log),
               "--audio-dir", str(self.work / "relative_audio"), "--ab-log", str(self.ab_log),
               "--forward-sim", f"http://127.0.0.1:{a.phone_port}/push"]
        for p in RELATIVES:
            cmd += ["--user", p]
        self._spawn(cmd, {**os.environ}, AB, self.work / "relative_sim.out", a.rel_port)
        wait_http(f"{self.rel_url}/health", 60, "relative_sim")
        end = time.time() + 90
        while time.time() < end:
            if self.rel_log.exists() and '"ready"' in self.rel_log.read_text(encoding="utf-8"):
                return
            time.sleep(0.3)
        raise SystemExit("relative_sim không ready - xem relative_sim.out")

    def _invite(self, owner):
        hdr = {"Authorization": f"Bearer {owner['access_token']}"}
        with httpx.Client(base_url=self.ab_url, timeout=15, headers=hdr) as c:
            for phone, (name, aliases, emergency, priority) in RELATIVES.items():
                r = c.post("/api/v1/care/invite", json={"phone_number": phone, "display_name": name, "aliases": aliases,
                                                        "emergency": emergency, "priority": priority})
                r.raise_for_status()
            end = time.time() + 30
            while time.time() < end:
                links = c.get("/api/v1/care/links").json()["data"]["links"]
                if len(links) == len(RELATIVES) and all(l["status"] == "active" for l in links):
                    return
                time.sleep(0.3)
        raise SystemExit("người thân chưa chấp nhận lời mời (relative_sim)")

    def _start_vh2(self, vh_env, public_token, cb_token, owner_pub, tokens):
        a = self.a
        env = {**os.environ, **vh_env}
        env.update(CUDA_VISIBLE_DEVICES=str(a.gpu), VISIONCARE_HOST_URL=self.ab_url,
                   VISIONCARE_CLIENT_TOKEN=public_token, VISIONCARE_DEVICE_ID="e2e-wrong-default",
                   VISIONCARE_CALLBACK_TOKEN=cb_token,  # không đặt VISIONCARE_USER_ID: AB suy chủ từ glasses_device_id
                   VISIONCARE_DEVICE_TOKENS=str(tokens), CALL_RING_TIMEOUT_S=str(a.ring_s))
        self.vh_log.unlink(missing_ok=True)
        p = self._spawn([PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(a.vh_port),
                         "--ws-max-size", "2100000"], env, ROOT, self.vh_log, a.vh_port)
        wait_http(f"{self.vh_url}/health", 420, "VH", p)

    def attach(self):
        self.info = json.loads(self.state_file.read_text(encoding="utf-8"))
        i = self.info
        self.vh_url, self.ab_url, self.rel_url = i["vh_url"], i["ab_url"], i["rel_url"]
        self.device_token = i["device_token"]
        self.rel_log = self.work / "relative_sim_log.jsonl"
        self.ab_log = self.work / "ab.log"
        for url, what in ((self.vh_url + "/health", "VH"), (self.rel_url + "/health", "relative_sim"),
                          (self.ab_url + "/health/live", "AB")):
            wait_http(url, 10, what)

    def kill_saved(self):
        i = json.loads(self.state_file.read_text(encoding="utf-8"))
        for pid in reversed(i["pids"]):
            try:
                os.killpg(pid, signal.SIGTERM)
            except Exception:
                pass
        time.sleep(1.5)
        for port in i["ports"]:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "compose", "-p", i["compose_project"], "-f", str(AB / "compose.test.yaml"), "down", "-v"],
                       env={**os.environ, "TEST_POSTGRES_PORT": str(i["pg_port"])},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state_file.unlink(missing_ok=True)


# ───────────────────────────── người thân (điều khiển relative_sim) ─────────────────────────────

class Rel:
    def __init__(self, url: str, log: Path):
        self.url, self.log = url, log

    def ctl(self, path: str, body: dict | None = None) -> dict:
        r = httpx.post(self.url + path, json=body or {}, timeout=20)
        r.raise_for_status()
        return r.json()

    def lines(self) -> list[dict]:
        if not self.log.exists():
            return []
        out = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def mark(self) -> int:
        return len(self.lines())

    def events(self, mark: int, event: str | None = None, **match) -> list[dict]:
        return [e for e in self.lines()[mark:] if (event is None or e["event"] == event)
                and all(e.get(k) == v for k, v in match.items())]

    async def wait(self, mark: int, timeout: float, event: str, count: int = 1, **match) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            found = self.events(mark, event, **match)
            if len(found) >= count:
                return found[count - 1]
            await asyncio.sleep(0.05)
        return None

    def behave(self, per_user: dict[str, dict]) -> None:
        for phone, beh in per_user.items():
            self.ctl("/ctl/behavior", {"user": phone, **beh})


IGNORE = {"incoming": "ignore", "hangup_after_s": None}


def answer(delay=1.0, hangup_after=None) -> dict:
    return {"incoming": "answer", "answer_delay_s": delay, "hangup_after_s": hangup_after, "media": True}


# ───────────────────────────── kính giả lập cho cuộc gọi ─────────────────────────────

class CallGlasses(base.Glasses):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._mic_task = None
        self.mic_t0 = None

    async def _read(self):  # như base nhưng giữ cả nội dung audio để dò tách
        try:
            async for msg in self.ws:
                ev = {"perf": time.perf_counter(), "wall": time.time()}
                if isinstance(msg, bytes):
                    ev.update(k="audio", n=len(msg) - 1, b=msg[1:] if msg[:1] == b"\x02" else b"")
                else:
                    ev.update(k="json", f=json.loads(msg))
                self.events.append(ev)
                self._wake.set()
        except Exception as exc:  # noqa: BLE001
            self.events.append({"perf": time.perf_counter(), "wall": time.time(), "k": "closed", "why": repr(exc)})
            self._wake.set()

    def call_states(self, since=0) -> list[dict]:
        return [{"wall": e["wall"], **e["f"]} for e in self.events[since:]
                if e["k"] == "json" and e["f"].get("t") == "call_state"]

    async def wait_state(self, state: str, timeout: float, since=0):
        return await self.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "call_state"
                                   and e["f"].get("state") == state, timeout, since)

    async def wait_say(self, needle: str, timeout: float, since=0):
        needle = strip_accents(needle)
        return await self.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "say"
                                   and needle in strip_accents(e["f"].get("text", "")), timeout, since)

    def says(self, since=0) -> list[str]:
        return [e["f"].get("text", "") for e in self.events[since:] if e["k"] == "json" and e["f"].get("t") == "say"]

    async def press_hangup(self, call_id=""):
        await self.ws.send(json.dumps({"t": "call_hangup", "call": call_id}))

    async def press_answer(self, call_id=""):
        await self.ws.send(json.dumps({"t": "call_answer", "call": call_id}))

    def start_mic(self, first_s=0.3, period_s=1.0) -> float:
        """Mic giả: nguồn tách, ADPCM, khung 0x05 gửi khi khối đầy (đồng hồ thu như relative_sim)."""
        wall0 = time.time()
        self.mic_t0, self.mic_first, self.mic_period = wall0, first_s, period_s

        async def run():
            enc = adpcm.Encoder()
            t0, i = time.perf_counter(), 0
            first, period = int(first_s * SR), int(period_s * SR)
            while True:
                await asyncio.sleep(max(0.0, t0 + (i + 1) * FRAME / SR - time.perf_counter()))
                out = enc.encode(signal_frame(i, first, period))
                if out:
                    await self.ws.send(b"\x05" + out)
                i += 1

        self._mic_task = asyncio.create_task(run())
        return wall0

    def stop_mic(self):
        if self._mic_task:
            self._mic_task.cancel()
            self._mic_task = None

    def rx_call_audio(self, t_from: float, t_to: float):
        """Âm thanh 0x02 tới kính trong [t_from, t_to]: (pcm int16, [(giờ tới, số mẫu)])."""
        pcm, arr = [], []
        for e in self.events:
            if e["k"] == "audio" and t_from <= e["wall"] <= t_to and e.get("b"):
                s = adpcm.decode_blocks(e["b"])
                pcm.append(s)
                arr.append((e["wall"], len(s)))
        return (np.concatenate(pcm) if pcm else np.zeros(0, dtype=np.int16)), arr


# ───────────────────────────── kịch bản ─────────────────────────────

class Ctx:
    def __init__(self, g, rel, plog, args, owner_pub, cs):
        self.g, self.rel, self.plog, self.args, self.owner_pub, self.cs = g, rel, plog, args, owner_pub, cs


def R(name, ok, notes="", **kw):
    return {"name": name, "pass": bool(ok), "notes": notes, **kw}


def ms(x):
    return None if x is None else round(x * 1000)


async def utter(c: Ctx, text: str):
    """Nói `text`; nếu server hỏi lại "...phải không?" thì trả lời "Đúng.". Trả lượt cuối."""
    mark = c.plog.mark()
    t = await c.g.say(text)
    await asyncio.sleep(0.15)
    if c.plog.asked_back(mark) > 0:
        t = await c.g.say("Đúng.")
    return t


def reply_end_wall(g, turn_id, since=0):
    for e in g.events[since:]:
        if e["k"] == "json" and e["f"].get("t") == "reply_end" and e["f"].get("turn") == turn_id:
            return e["wall"]
    return None


async def stream_phase(c: Ctx, base_idx: int, user: str, call_id: str, hang_by: str, tx_wait: float = 4.6) -> tuple[dict, list]:
    """Đang `active`: mic kính + nguồn người thân chạy `tx_wait` s, rồi cúp (glasses|app|auto), dò trễ hai chiều."""
    g, rel = c.g, c.rel
    problems, m = [], {}
    rmark = rel.mark() - 0
    mic_wall = g.start_mic()
    if hang_by == "auto":
        ended = await g.wait_state("ended", tx_wait + 8, base_idx)
    else:
        await asyncio.sleep(tx_wait)
        if hang_by == "glasses":
            await g.press_hangup(call_id)
        else:
            rel.ctl("/ctl/hangup", {"user": user})
        ended = await g.wait_state("ended", 8, base_idx)
    g.stop_mic()
    if ended is None:
        problems.append("kính không nhận call_state ended")
        return m, problems
    m["ended_reason"] = ended["f"].get("reason")
    active = next((s for s in g.call_states(base_idx) if s["state"] == "active"), None)
    closed = await rel.wait(0, 10, "media_closed", user=user, call_id=call_id)
    if closed is None:
        problems.append("người thân không đóng media WS")
        return m, problems
    # kính -> app
    tx = next((e for e in rel.events(0, "tx_start", user=user, call_id=call_id)), None)
    stem = Path(closed["wav"]).with_suffix(".json")
    meta = json.loads(stem.read_text(encoding="utf-8"))
    with wave.open(closed["wav"], "rb") as w:
        rx_pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    arrivals = [(t, n // 2) for t, n in meta["arrivals"]]
    d_g2a = one_way_delays(rx_pcm, arrivals, g.mic_t0, g.mic_first, g.mic_period)
    m["g2a"] = stat(d_g2a)
    first_rx = next(iter(rel.events(0, "rx_first_audio", user=user, call_id=call_id)), None)
    if first_rx:
        m["mic_to_app_first_ms"] = ms(first_rx["wall"] - mic_wall)
    # app -> kính
    pcm, arr = g.rx_call_audio(active["wall"] if active else 0, ended["wall"])
    if tx:
        d_a2g = one_way_delays(pcm, arr, tx["tx_t0"], tx["click_first_s"], tx["click_period_s"])
        m["a2g"] = stat(d_a2g)
    if not m["g2a"]["n"]:
        problems.append("app không nhận được tiếng tách nào từ kính")
    if not m.get("a2g", {}).get("n"):
        problems.append("kính không nhận được tiếng tách nào từ app")
    return m, problems


async def check_ab_state(c: Ctx, user: str, call_id: str, want: str, problems: list):
    st = c.rel.ctl("/ctl/get_call", {"user": user, "call_id": call_id})
    if st.get("state") != want:
        problems.append(f"AB state={st.get('state')!r} (mong {want!r})")
    return st


async def sc_call_mom(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: answer(1.0), NAMANH: IGNORE, NAMBINH: IGNORE})
    m0, base_idx = rel.mark(), len(g.events)
    t = await utter(c, "Gọi cho mẹ.")
    r = R("call_mom", False)
    ring = await rel.wait(m0, 20, "push", user=MOM, type="call_incoming")
    if ring is None:
        r["notes"] = "người thân không nhận call_incoming"
        return r
    r["ring_ms"] = ms(ring["wall"] - t.release_wall)
    end = reply_end_wall(g, t.tid, base_idx)
    r["ring_after_readback_ms"] = ms(ring["wall"] - end) if end else None
    problems = []
    others = rel.events(m0, "push", type="call_incoming")
    if any(e["user"] != MOM for e in others):
        problems.append("người khác cũng nhận chuông")
    out = next(iter(g.call_states(base_idx)), None)
    if not out or out["state"] != "ringing_out":
        problems.append(f"kính không nhận ringing_out ({out})")
    ans = await rel.wait(m0, 10, "answer_http", user=MOM)
    act = await g.wait_state("active", 10, base_idx)
    if ans is None or act is None:
        r["notes"] = "; ".join(problems + ["không nghe máy/không active"])
        return r
    call_id = ans["call_id"]
    r["answer_to_active_ms"] = ms(act["wall"] - ans["t_send"])
    first_audio = None
    sm, p2 = await stream_phase(c, base_idx, MOM, call_id, "glasses")
    problems += p2
    aud = next((e for e in g.events[base_idx:] if e["k"] == "audio" and e["wall"] >= act["wall"]), None)
    if aud:
        r["answer_to_first_audio_ms"] = ms(aud["wall"] - ans["t_send"])
    else:
        problems.append("kính không nhận khối audio nào từ app")
    r.update(sm)
    if sm.get("ended_reason") not in ("glasses_hangup", None):
        problems.append(f"ended reason={sm.get('ended_reason')}")
    if not rel.events(m0, "push", user=MOM, type="call_ended"):
        problems.append("người thân không nhận FCM call_ended")
    await asyncio.sleep(0.5)
    await check_ab_state(c, MOM, call_id, "ended", problems)
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "gọi -> chuông -> nghe -> tiếng hai chiều -> kính cúp -> AB ended"
    return r


async def sc_call_nam(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE, NAMANH: IGNORE, NAMBINH: answer(0.5, hangup_after=4.0)})
    m0, base_idx = rel.mark(), len(g.events)
    await g.say("Gọi cho Nam.")
    ask = await g.wait_say("Bạn muốn gọi ai", 25, base_idx)
    r = R("call_nam", False)
    if ask is None:
        r["notes"] = f"kính không nghe câu hỏi chọn người (say: {g.says(base_idx)})"
        return r
    txt = [x for x in g.says(base_idx) if "muốn gọi ai" in x][0]
    problems = []
    if "Nam Anh" not in txt or "Nam Bình" not in txt:
        problems.append(f"câu hỏi thiếu ứng viên: {txt!r}")
    if rel.events(m0, "push", type="call_incoming"):
        problems.append("chuông đổ trước khi chọn người")
    await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end"
                     and str(e["f"].get("turn", "")).startswith("result-") and e["wall"] >= ask["wall"], 15, base_idx)
    m1, b2 = rel.mark(), len(g.events)
    t = await utter(c, "Nam Bình.")
    ring = await rel.wait(m1, 25, "push", user=NAMBINH, type="call_incoming")
    if ring is None:
        r["notes"] = "; ".join(problems + [f"Nam Bình không nhận chuông (say: {g.says(b2)})"])
        return r
    r["ring_ms"] = ms(ring["wall"] - t.release_wall)
    if rel.events(m0, "push", user=NAMANH, type="call_incoming"):
        problems.append("Nam Anh nhận chuông nhầm")
    ans = await rel.wait(m1, 10, "answer_http", user=NAMBINH)
    act = await g.wait_state("active", 10, b2)
    if ans is None or act is None:
        r["notes"] = "; ".join(problems + ["không nghe máy/không active"])
        return r
    r["answer_to_active_ms"] = ms(act["wall"] - ans["t_send"])
    sm, p2 = await stream_phase(c, b2, NAMBINH, ans["call_id"], "auto")
    problems += p2
    r.update(sm)
    if sm.get("ended_reason") != "app_hangup":
        problems.append(f"ended reason={sm.get('ended_reason')!r} (mong app_hangup)")
    await asyncio.sleep(0.5)
    await check_ab_state(c, NAMBINH, ans["call_id"], "ended", problems)
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "trùng tên -> hỏi -> chọn Nam Bình -> gọi -> app cúp -> AB ended"
    return r


async def sc_call_cancel_readback(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: answer(0.2), NAMANH: IGNORE, NAMBINH: IGNORE})
    m0, base_idx = rel.mark(), len(g.events)
    t = await g.say("Gọi cho mẹ.")
    await g.cancel()  # bấm huỷ trong cửa sổ đọc lại
    await asyncio.sleep(7.0)
    got = rel.events(m0, "push", type="call_incoming")
    states = g.call_states(base_idx)
    ok = not got and not states and not t.error
    return R("call_cancel_readback", ok, "AB không có call: người thân không nhận chuông, kính không nhận call_state" if ok
             else f"chuông={len(got)} call_state={len(states)} err={t.error}", first_audio_ms=t.ms("first_audio"))


async def sc_missed_then_message(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE, NAMANH: IGNORE, NAMBINH: IGNORE})
    m0, base_idx = rel.mark(), len(g.events)
    t = await utter(c, "Gọi cho mẹ.")
    r = R("missed_then_message", False)
    ring = await rel.wait(m0, 20, "push", user=MOM, type="call_incoming")
    if ring is None:
        r["notes"] = "không có chuông"
        return r
    r["ring_ms"] = ms(ring["wall"] - t.release_wall)
    miss = await g.wait_say("chưa nghe máy", c.args.ring_s + 20, base_idx)
    if miss is None:
        r["notes"] = f"kính không nghe 'chưa nghe máy' (say: {g.says(base_idx)})"
        return r
    r["ring_to_missed_say_ms"] = ms(miss["wall"] - ring["wall"])
    problems = []
    if "Bạn muốn nhắn tin không" not in " ".join(g.says(base_idx)):
        problems.append("thiếu lời mời nhắn tin")
    ended = [s for s in g.call_states(base_idx) if s["state"] == "ended"]
    if not ended or ended[0].get("reason") != "missed":
        problems.append(f"call_state ended reason={ended[0].get('reason') if ended else None}")
    await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end"
                     and str(e["f"].get("turn", "")).startswith("result-") and e["wall"] >= miss["wall"], 15, base_idx)
    m1, b2 = rel.mark(), len(g.events)
    await utter(c, "Có.")
    if await g.wait_say("muốn nhắn gì", 15, b2) is None:
        r["notes"] = "; ".join(problems + [f"kính không hỏi lời nhắn (say: {g.says(b2)})"])
        return r
    await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end" and e["wall"] >= g.events[b2]["wall"], 15, b2)
    await asyncio.sleep(1.0)
    t = await utter(c, "Con sẽ về muộn.")
    msg = await rel.wait(m1, 25, "push", user=MOM, type="message_in")
    if msg is None:
        r["notes"] = "; ".join(problems + [f"người thân không nhận tin (say: {g.says(b2)})"])
        return r
    r["message_ms"] = ms(msg["wall"] - t.release_wall)
    text = msg.get("text") or ""
    if "muon" not in strip_accents(text):
        problems.append(f"nội dung tin lạ: {text!r}")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or f"nhỡ -> 'Có' -> lời nhắn -> tin tới Mẹ: {text!r}"
    return r


async def sc_message_send(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE})
    m0, base_idx = rel.mark(), len(g.events)
    t = await utter(c, "Nhắn tin cho mẹ là con đi ăn cơm nhé.")
    msg = await rel.wait(m0, 25, "push", user=MOM, type="message_in")
    r = R("message_send_idle", False, first_audio_ms=t.ms("first_audio"))
    if msg is None:
        r["notes"] = f"người thân không nhận tin (say: {g.says(base_idx)})"
        return r
    r["message_ms"] = ms(msg["wall"] - t.release_wall)
    text = msg.get("text") or ""
    ok = "com" in strip_accents(text)
    r["pass"], r["notes"] = ok, f"tin tới Mẹ: {text!r}" + ("" if ok else " (thiếu 'cơm')")
    return r


async def _history_item(c: Ctx, text_part: str):
    h = c.rel.ctl("/ctl/history", {"user": MOM, "owner_user_id": c.owner_pub})
    return next((m for m in h.get("messages", []) if text_part in m["text"]), None)


async def sc_message_in_idle(c: Ctx):
    g, rel = c.g, c.rel
    base_idx = len(g.events)
    sent = rel.ctl("/ctl/message", {"user": MOM, "owner_user_id": c.owner_pub, "text": "Mẹ nấu cơm rồi, con về ăn nhé."})
    r = R("message_in_idle", False)
    if sent.get("http") != 200:
        r["notes"] = f"gửi tin lỗi {sent}"
        return r
    say = await g.wait_say("Mẹ nhắn:", 20, base_idx)
    if say is None:
        r["notes"] = f"kính không đọc tin (say: {g.says(base_idx)})"
        return r
    aud = await g.wait_for(lambda e: e["k"] == "audio" and e["wall"] >= sent["t_send"], 10, base_idx)
    r["message_to_first_audio_ms"] = ms(aud["wall"] - sent["t_send"]) if aud else None
    r["message_to_say_ms"] = ms(say["wall"] - sent["t_send"])
    text = [x for x in g.says(base_idx) if "Mẹ nhắn:" in x][0]
    read_at = None
    end = time.time() + 12
    while time.time() < end:
        item = await _history_item(c, "nấu cơm")
        read_at = item and item.get("read_at")
        if read_at:
            break
        await asyncio.sleep(0.4)
    problems = []
    if "nấu cơm" not in text:
        problems.append(f"nội dung đọc lạ: {text!r}")
    if not read_at:
        problems.append("AB không ghi read_at")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or f"kính rảnh đọc ngay: {text!r}; AB read_at có"
    return r


async def sc_message_in_busy(c: Ctx):
    g, rel = c.g, c.rel
    base_idx = len(g.events)
    t = await g.say("Kể cho tôi một câu chuyện cười ngắn.", wait_end=False)
    sent = rel.ctl("/ctl/message", {"user": MOM, "owner_user_id": c.owner_pub, "text": "Mẹ gọi con lúc chiều nhé."})
    r = R("message_in_busy", False)
    if t.error or sent.get("http") != 200:
        r["notes"] = f"lượt chat lỗi {t.error} / gửi tin {sent.get('http')}"
        return r
    end_ev = await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end" and e["f"].get("turn") == t.tid, 40, base_idx)
    say = await g.wait_say("Mẹ nhắn:", 40, base_idx)
    if end_ev is None or say is None:
        r["notes"] = f"thiếu reply_end({end_ev is not None}) hoặc tin không được đọc (say: {g.says(base_idx)})"
        return r
    problems = []
    if say["wall"] < end_ev["wall"] - 0.05:
        tl = [(round(e["wall"] - end_ev["wall"], 2), e["f"].get("turn"), e["f"].get("text", "")[:40]) for e in g.events[base_idx:]
              if e["k"] == "json" and e["f"].get("t") == "say"]
        problems.append(f"tin chen ngang câu trả lời đang đọc (so với reply_end: {tl})")
    r["message_after_reply_end_ms"] = ms(say["wall"] - end_ev["wall"])
    item = None
    end = time.time() + 12
    while time.time() < end:
        item = await _history_item(c, "gọi con lúc chiều")
        if item and item.get("read_at"):
            break
        await asyncio.sleep(0.4)
    if not (item and item.get("read_at")):
        problems.append("AB không ghi read_at")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "tin tới giữa lượt chat: xếp hàng, đọc sau reply_end, không mất"
    return r


async def sc_glasses_called(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: {"incoming": "ignore", "media": True, "hangup_after_s": None}})
    m0, base_idx = rel.mark(), len(g.events)
    sent = rel.ctl("/ctl/call_glasses", {"user": MOM, "owner_user_id": c.owner_pub})
    r = R("glasses_called_by_relative", False)
    if sent.get("http") != 200:
        r["notes"] = f"POST /calls lỗi {sent}"
        return r
    ringing = await g.wait_state("ringing_in", 10, base_idx)
    if ringing is None:
        r["notes"] = f"kính không nhận ringing_in (say: {g.says(base_idx)})"
        return r
    r["app_to_ring_ms"] = ms(ringing["wall"] - sent["t_send"])
    problems = []
    say = await g.wait_say("đang gọi", 10, base_idx)
    if say is None:
        problems.append("kính không đọc 'đang gọi'")
    else:
        await g.wait_for(lambda e: e["k"] == "json" and e["f"].get("t") == "reply_end" and e["wall"] >= say["wall"], 12, base_idx)
    t_press = time.time()
    await g.press_answer(sent["call_id"])
    act = await g.wait_state("active", 10, base_idx)
    if act is None:
        r["notes"] = "; ".join(problems + ["kính không active sau khi bấm nghe"])
        return r
    r["answer_to_active_ms"] = ms(act["wall"] - t_press)
    if await rel.wait(m0, 10, "push", user=MOM, type="call_answered") is None:
        problems.append("người thân không nhận FCM call_answered")
    if await rel.wait(m0, 10, "media_open", user=MOM, call_id=sent["call_id"]) is None:
        problems.append("người thân không mở media WS")
    sm, p2 = await stream_phase(c, base_idx, MOM, sent["call_id"], "app")
    problems += p2
    aud = next((e for e in g.events[base_idx:] if e["k"] == "audio" and e["wall"] >= act["wall"]), None)
    r["answer_to_first_audio_ms"] = ms(aud["wall"] - t_press) if aud else None
    r.update(sm)
    if sm.get("ended_reason") != "app_hangup":
        problems.append(f"ended reason={sm.get('ended_reason')!r} (mong app_hangup)")
    await asyncio.sleep(0.5)
    await check_ab_state(c, MOM, sent["call_id"], "ended", problems)
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "app gọi -> kính đọc 'đang gọi' -> bấm nghe -> tiếng hai chiều -> app cúp -> AB ended"
    return r


async def _emergency_start(c: Ctx, text="Cấp cứu, gọi người thân giúp tôi."):
    m0, base_idx = c.rel.mark(), len(c.g.events)
    t = await utter(c, text)
    return m0, base_idx, t


async def sc_emergency_second(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE, NAMANH: IGNORE, NAMBINH: answer(0.5)})
    m0, base_idx, t = await _emergency_start(c)
    r = R("emergency_second_answers", False)
    first = await rel.wait(m0, 25, "push", user=MOM, type="call_incoming")
    if first is None:
        r["notes"] = f"người 1 không nhận chuông (say: {g.says(base_idx)})"
        return r
    r["ring_ms"] = ms(first["wall"] - t.release_wall)
    problems = []
    if first.get("emergency") != "true":
        problems.append("call_incoming không có emergency=true")
    second = await rel.wait(m0, c.args.ring_s + 20, "push", user=NAMBINH, type="call_incoming")
    if second is None:
        r["notes"] = "; ".join(problems + ["người 2 không nhận chuông"])
        return r
    r["chain_gap_ms"] = ms(second["wall"] - first["wall"])
    ans = await rel.wait(m0, 10, "answer_http", user=NAMBINH)
    act = await g.wait_state("active", 10, base_idx)
    if ans is None or act is None:
        r["notes"] = "; ".join(problems + ["người 2 không nghe/không active"])
        return r
    r["answer_to_active_ms"] = ms(act["wall"] - ans["t_send"])
    for phone in (MOM, NAMBINH):  # tin khẩn cấp tới mọi người thân khẩn cấp
        msg = await rel.wait(m0, 15, "push", user=phone, type="message_in")
        if msg is None or not (msg.get("text") or "").startswith("KHẨN CẤP"):
            problems.append(f"{NAME_OF[phone]} không nhận tin KHẨN CẤP ({msg and msg.get('text')!r})")
        else:
            r.setdefault("alert_text", msg["text"])
    if rel.events(m0, "push", user=NAMANH):
        problems.append("Nam Anh (không khẩn cấp) nhận push")
    sm, p2 = await stream_phase(c, base_idx, NAMBINH, ans["call_id"], "glasses")
    problems += p2
    r.update(sm)
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "người 1 không nghe -> người 2 nghe -> tiếng hai chiều; tin KHẨN CẤP tới cả hai"
    return r


async def sc_emergency_exhausted(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE, NAMANH: IGNORE, NAMBINH: IGNORE})
    m0, base_idx, t = await _emergency_start(c)
    r = R("emergency_exhausted", False)
    first = await rel.wait(m0, 25, "push", user=MOM, type="call_incoming")
    if first is None:
        r["notes"] = f"không có chuông khẩn cấp (say: {g.says(base_idx)})"
        return r
    done = await g.wait_say("Chưa liên lạc được người thân nào", c.args.ring_s * 6 + 60, base_idx)
    if done is None:
        r["notes"] = f"kính không được báo hết vòng (say: {g.says(base_idx)})"
        return r
    r["total_s"] = round(done["wall"] - first["wall"], 1)
    problems = []
    n = {p: len(rel.events(m0, "push", user=p, type="call_incoming")) for p in (MOM, NAMBINH)}
    if n != {MOM: 3, NAMBINH: 3}:
        problems.append(f"số lần đổ chuông {n} (mong 3 vòng x mỗi người)")
    if rel.events(m0, "push", user=NAMANH, type="call_incoming"):
        problems.append("Nam Anh nhận chuông")
    ended = await g.wait_state("ended", 5, base_idx)
    if ended is None or ended["f"].get("reason") != "emergency_exhausted":
        problems.append(f"call_state ended={ended and ended['f'].get('reason')!r}")
    await asyncio.sleep(c.args.ring_s + 2)
    if len(rel.events(m0, "push", type="call_incoming")) != 6:
        problems.append("chuỗi vẫn gọi tiếp sau khi hết vòng")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or f"6 lượt chuông (3 vòng x 2 người) trong {r['total_s']} s rồi dừng, kính được báo"
    return r


async def sc_emergency_stop(c: Ctx):
    g, rel = c.g, c.rel
    rel.behave({MOM: IGNORE, NAMANH: IGNORE, NAMBINH: IGNORE})
    m0, base_idx, t = await _emergency_start(c)
    r = R("emergency_stop_by_button", False)
    first = await rel.wait(m0, 25, "push", user=MOM, type="call_incoming")
    if first is None:
        r["notes"] = f"không có chuông khẩn cấp (say: {g.says(base_idx)})"
        return r
    await g.press_hangup()
    ended = await g.wait_state("ended", 8, base_idx)
    problems = []
    if ended is None:
        problems.append("kính không nhận ended")
    if await rel.wait(m0, 8, "push", user=MOM, type="call_ended") is None:
        problems.append("Mẹ không nhận call_ended (huỷ chuông)")
    await asyncio.sleep(c.args.ring_s * 2 + 3)
    n = len(rel.events(m0, "push", type="call_incoming"))
    if n != 1:
        problems.append(f"chuỗi vẫn gọi tiếp: {n} lượt chuông")
    r["pass"], r["notes"] = not problems, "; ".join(problems) or "bấm nút khi đang chuông: chuỗi dừng, Mẹ nhận call_ended, không ai khác bị gọi"
    return r


SCENARIOS = {
    "call_mom": sc_call_mom, "call_nam": sc_call_nam, "call_cancel_readback": sc_call_cancel_readback,
    "missed_then_message": sc_missed_then_message, "message_send": sc_message_send,
    "message_in_idle": sc_message_in_idle, "message_in_busy": sc_message_in_busy,
    "glasses_called": sc_glasses_called, "emergency_second": sc_emergency_second,
    "emergency_exhausted": sc_emergency_exhausted, "emergency_stop": sc_emergency_stop,
}
LONG = {"emergency_exhausted": 240}

PHRASES = ["Gọi cho mẹ.", "Gọi cho Nam.", "Nam Bình.", "Có.", "Đúng.", "Con sẽ về muộn.", "Nhắn tin cho mẹ là con đi ăn cơm nhé.",
           "Kể cho tôi một câu chuyện cười ngắn.", "Cấp cứu, gọi người thân giúp tôi."]


def table(results):
    lines = ["| Kịch bản | PASS | nhả nút→chuông app (ms) | nghe→active (ms) | nghe→khối audio đầu tới kính (ms) | trễ kính→app p50/p90 (ms) | trễ app→kính p50/p90 (ms) | ghi chú |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        extra = []
        for k, label in (("ring_after_readback_ms", "đọc lại xong→chuông"), ("chain_gap_ms", "người1→người2"),
                         ("message_ms", "nhả nút→tin tới app"), ("message_to_first_audio_ms", "tin tới→tiếng đầu"),
                         ("message_after_reply_end_ms", "tin sau reply_end"), ("app_to_ring_ms", "app gọi→kính chuông"),
                         ("ring_to_missed_say_ms", "chuông→'chưa nghe máy'"), ("total_s", "tổng s"),
                         ("mic_to_app_first_ms", "mic→app khung đầu")):
            if r.get(k) is not None:
                extra.append(f"{label} {r[k]}")
        note = (r["notes"] + (" [" + "; ".join(extra) + "]" if extra else "")).replace("|", "/")
        lines.append(f"| {r['name']} | {'PASS' if r['pass'] else 'FAIL'} | {r.get('ring_ms', r.get('app_to_ring_ms', '-'))} | "
                     f"{r.get('answer_to_active_ms', '-')} | {r.get('answer_to_first_audio_ms', '-')} | "
                     f"{fmt_stat(r.get('g2a'))} | {fmt_stat(r.get('a2g'))} | {note} |")
    return "\n".join(lines)


async def run(args, cs: CallStack):
    audio_fn = base.make_audio_fn(Path(args.cache))
    for text in PHRASES:
        audio_fn(text)
    rel = Rel(cs.rel_url, cs.rel_log)
    plog = base.PhoneLog(None, cs.vh_log)
    owner_pub = cs.info["owner"]["public_user_id"]
    results = []
    for name in args.only or list(SCENARIOS):
        g = CallGlasses(cs.vh_url, cs.device_token, audio_fn, args.glasses_id)
        await g.connect()
        c = Ctx(g, rel, plog, args, owner_pub, cs)
        await g.ws.send(json.dumps({"t": "cancel"}))
        await asyncio.sleep(0.8)
        t0 = time.time()
        try:
            r = await asyncio.wait_for(SCENARIOS[name](c), LONG.get(name, 150))
        except Exception as exc:  # noqa: BLE001
            r = R(name, False, f"ngoại lệ: {exc!r}")
        r["secs"] = round(time.time() - t0, 1)
        results.append(r)
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: {r['notes']}  ({r['secs']} s)", flush=True)
        g.stop_mic()
        try:
            await g.close()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2.0)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=list(SCENARIOS))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--attach", action="store_true", help="dùng stack đã --keep (đọc workdir/stack.json)")
    ap.add_argument("--stop", action="store_true", help="tắt stack đã --keep rồi thoát")
    ap.add_argument("--ring-s", type=float, default=5.0, help="CALL_RING_TIMEOUT_S rút ngắn cho test (AB và VH)")
    ap.add_argument("--gpu", default=os.environ.get("CUDA_VISIBLE_DEVICES", "0"))
    ap.add_argument("--glasses-id", default=GLASSES)
    ap.add_argument("--vh-port", type=int, default=18895)
    ap.add_argument("--ab-port", type=int, default=18011)
    ap.add_argument("--phone-port", type=int, default=18012)
    ap.add_argument("--rel-port", type=int, default=18013)
    ap.add_argument("--pg-port", type=int, default=55436)
    ap.add_argument("--compose-project", default="vh-e2e-calls")
    ap.add_argument("--vh-env", dest="vh_env", default=str(next((p for p in (ROOT / ".env", SEEVIA / "visioncare-host-demo" / ".env") if p.exists()), ROOT / ".env")))
    ap.add_argument("--ab-env", dest="ab_env", default=str(SEEVIA / ".env"))
    ap.add_argument("--workdir", default=str(ROOT / "results" / "e2e_calls"))
    ap.add_argument("--cache", default=str(ROOT / "tools" / "board_audio" / "e2e"))
    ap.add_argument("--json-out")
    args = ap.parse_args()
    args.no_phone_sim = False
    args.vh_url = args.app_url = args.scenario = None
    cs = CallStack(args)
    if args.stop:
        cs.kill_saved()
        return
    code = 1
    try:
        if args.attach:
            cs.attach()
        else:
            cs.start()
        results = asyncio.run(run(args, cs))
        print("\n" + table(results))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        code = 0 if all(r["pass"] for r in results) else 1
    finally:
        if not (args.keep or args.attach):
            cs.stop()
            cs.state_file.unlink(missing_ok=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
