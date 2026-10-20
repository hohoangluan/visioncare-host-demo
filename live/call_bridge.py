"""Cầu âm thanh cuộc gọi kính <-> app người thân (spec 2026-10-19-glasses-calls-messages §5.3, §6).

Tín hiệu đi qua AB (HTTP + callback `/internal/calls`), âm thanh KHÔNG qua AB:

    kính  --0x05 ADPCM-->  Call.from_glasses  --PCM16 640 B-->  WS /v2/call (app)
    kính  <--0x02 ADPCM--  Call (JitterBuffer)  <--PCM16 640 B--  WS /v2/call (app)

Độ trễ là ưu tiên số 1, nên:
- Đường kính -> app KHÔNG có khoá/đệm: giải mã ADPCM (bộ giải vô hướng ~0,2 ms/khối; `adpcm.decode_blocks`
  vector hoá theo khối nên một khối lẻ tốn ~22 ms, chặn event loop quá lâu), cắt khung 640 B, đẩy vào hàng
  đợi có trần, một task gửi riêng — vòng nhận của kính không bao giờ chờ socket chậm của app.
- Đường app -> kính KHÔNG dùng `_audio_lock` của phiên (khoá trọn câu TTS): chỉ `_send_lock` từng khung nên chờ
  tối đa MỘT khung đang gửi. Lúc cuộc gọi `active`, phiên đã huỷ lượt/kết quả đang đọc và giữ hàng đợi câu nói,
  nên không có tiếng nào khác chen vào kênh 0x02 (xem `DeviceSession._on_call_state`).
- Đệm chống giật `CALL_JITTER_MS` (mặc định 60, theo spec); `0` = phát ngay khi khung tới.

Mọi phương thức async của `Call` chạy trên event loop; `calls.create` và `Call.hangup_threadsafe` gọi được từ
thread nền (handler làn D chạy trong thread).
"""

import asyncio
import collections
import contextlib
import hashlib
import json
import logging
import math
import secrets
import threading
import time
from array import array
from collections.abc import Awaitable, Callable

import numpy as np
from starlette.websockets import WebSocketDisconnect

import config
from live.jitter import JitterBuffer
from pipeline import adpcm, device_ctx

logger = logging.getLogger("blind_assist")

# Câu cố định (đưa vào `pipeline/phrases.py` để dựng sẵn audio). Câu có tên người thì tổng hợp lúc chạy.
NEED_OWN_TOKEN = "Kính cần token riêng để gọi điện."
EMERGENCY_UNANSWERED = "Chưa ai nghe máy cuộc gọi khẩn cấp."
STATIC_SPEECH: tuple[str, ...] = (NEED_OWN_TOKEN, EMERGENCY_UNANSWERED)


def incoming_speech(name: str) -> str:
    return f"{name} đang gọi. Bấm nút để nghe."


def missed_speech(name: str) -> str:
    return f"{name} chưa nghe máy. Bạn muốn nhắn tin không?"


def rejected_speech(name: str) -> str:
    return f"{name} từ chối cuộc gọi."


RINGING_OUT, RINGING_IN, ACTIVE, ENDED = "ringing_out", "ringing_in", "active", "ended"
TO_RELATIVE, TO_GLASSES = "to_relative", "to_glasses"

FRAME_BYTES = 640  # 20 ms PCM16 16 kHz mono
_BLOCK = adpcm.BLOCK_ALIGN
_STEP, _INDEX, _MAX_INDEX = adpcm._STEP_TABLE, adpcm._INDEX_TABLE, adpcm._MAX_INDEX
_QUEUE_MAX = 10  # 200 ms: đầy thì bỏ khung CŨ nhất (giữ độ trễ thấp hơn là giữ đủ tiếng)

AudioSender = Callable[[bytes], Awaitable[None]]
StateSender = Callable[[dict], Awaitable[None]]
StateHook = Callable[["Call"], Awaitable[None]]


_bg: set[asyncio.Task] = set()  # giữ tham chiếu task nền (asyncio chỉ giữ yếu)


class GlassesBusy(Exception):
    """Kính đã có một cuộc gọi chưa kết thúc."""


def decode_block(block: bytes) -> bytes:
    """MỘT khối IMA ADPCM 256 B -> PCM16LE (505 mẫu), bit-exact với `adpcm.decode_blocks`, ~0,2 ms."""
    pred = int.from_bytes(block[0:2], "little", signed=True)
    index = min(block[2], _MAX_INDEX)
    out = array("h", [pred])
    append = out.append
    step_t, idx_t = _STEP, _INDEX
    for byte in block[4:]:
        for code in (byte & 15, byte >> 4):
            step = step_t[index]
            diff = step >> 3
            if code & 1:
                diff += step >> 2
            if code & 2:
                diff += step >> 1
            if code & 4:
                diff += step
            pred = pred - diff if code & 8 else pred + diff
            if pred > 32767:
                pred = 32767
            elif pred < -32768:
                pred = -32768
            index += idx_t[code]
            if index < 0:
                index = 0
            elif index > _MAX_INDEX:
                index = _MAX_INDEX
            append(pred)
    return out.tobytes()


def rms_dbfs(frame: bytes) -> float:
    x = np.frombuffer(frame, dtype="<i2").astype(np.float32)
    if x.size == 0:
        return -120.0
    rms = math.sqrt(float(np.mean(x * x))) / 32768.0
    return 20.0 * math.log10(max(rms, 1e-6))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Call:
    def __init__(self, call_id: str, device: str, peer: str, direction: str) -> None:
        self.call_id = call_id
        self.device = device
        self.peer = peer
        self.direction = direction
        self.state = RINGING_IN if direction == TO_GLASSES else RINGING_OUT
        self.end_reason = ""
        self.emergency = False
        self.media_token = secrets.token_urlsafe(16)  # một lần; AB chỉ chuyển, VH kiểm khi app mở WS
        self.expires_at = time.monotonic() + config.CALL_RING_TIMEOUT_S + config.CALL_TOKEN_GRACE_S
        self.session = None  # DeviceSession đang giữ đầu kính
        self.ab_task: asyncio.Task | None = None  # báo AB hangup/answer (nền) — test chờ được
        self.loop: asyncio.AbstractEventLoop | None = None
        self._send_audio: AudioSender | None = None
        self._send_state: StateSender | None = None
        self._on_state: StateHook | None = None
        self._app_ws = None
        self._ended: asyncio.Event | None = None  # tạo lười trên loop (xem _ended_event)
        self._tasks: set[asyncio.Task] = set()
        self._timers: list[tuple[str, asyncio.TimerHandle]] = []
        self._answering = False
        # kính -> app
        self._g_rem = b""  # byte ADPCM lẻ chưa đủ một khối
        self._g_pcm = b""  # PCM chưa đủ một khung 640 B
        self._to_app: asyncio.Queue | None = None
        self._app_loud_until = 0.0
        # app -> kính
        self._jb = (JitterBuffer(config.CALL_JITTER_MS, config.CALL_JITTER_MAX_LATE_MS)
                    if config.CALL_JITTER_MS > 0 else None)
        self._app_ts = 0.0
        self._to_glasses: asyncio.Queue | None = None  # chỉ khi không đệm
        self._wake: asyncio.Event | None = None
        self._enc = adpcm.Encoder()
        # đo trễ cộng thêm của cầu (ms), giữ 500 mẫu cuối
        self.lat_g2a = collections.deque(maxlen=500)
        self.lat_a2g = collections.deque(maxlen=500)
        self.stats = {"g2a_frames": 0, "a2g_frames": 0, "drop_g2a": 0}

    # ---------- gắn hai đầu ----------
    def attach_glasses(self, send_audio: AudioSender, send_state: StateSender, on_state: StateHook | None = None,
                       session=None) -> None:
        """Gọi trên event loop của phiên kính. `send_audio` nhận ADPCM TRẦN (phiên tự thêm byte 0x02)."""
        self.loop = asyncio.get_running_loop()
        self._send_audio, self._send_state, self._on_state, self.session = send_audio, send_state, on_state, session
        if self.state != ENDED:
            self._timer(config.CALL_RING_TIMEOUT_S + config.CALL_TOKEN_GRACE_S, self._ring_expired)

    async def announce(self) -> None:
        """Báo kính trạng thái đầu tiên (`ringing_out|ringing_in`) và cho phiên cập nhật khung mode."""
        await self._notify_glasses(self.end_reason if self.state == ENDED else None)
        await self._call_hook()

    async def attach_app(self, ws) -> None:
        """App mở `WS /v2/call` (token đã `claim`): chạy vòng nhận tới khi cúp / app rớt mạng."""
        self.loop = self.loop or asyncio.get_running_loop()
        self._app_ws = ws
        self._cancel_timers("media_wait")
        self._to_app = asyncio.Queue(_QUEUE_MAX)
        self._spawn(self._app_sender(ws))
        if self.state == ACTIVE:
            self._start_media()
        await self._send_app_state()
        # MỘT waiter `ended` cho cả cuộc gọi (không tạo mới mỗi khung: rò task theo 50 khung/s)
        ended_task = asyncio.ensure_future(self._ended_event().wait())
        recv = asyncio.ensure_future(ws.receive())
        try:
            while self.state != ENDED:
                done, _ = await asyncio.wait({recv, ended_task}, return_when=asyncio.FIRST_COMPLETED)
                if recv not in done:
                    break
                msg = recv.result()
                if msg["type"] == "websocket.disconnect":
                    break
                recv = asyncio.ensure_future(ws.receive())
                data = msg.get("bytes")
                if data is not None:
                    self._on_app_frame(data)
                elif msg.get("text"):
                    await self._on_app_text(msg["text"])
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            recv.cancel()
            ended_task.cancel()
            if self.state != ENDED:
                self.end_soon("peer_disconnect", by="app")

    async def _on_app_text(self, text: str) -> None:
        try:
            frame = json.loads(text)
            kind = frame["t"]
        except (ValueError, KeyError, TypeError):
            return
        if kind == "hangup":
            await self.hangup("app_hangup", by="app")
        elif kind == "mute":
            pass  # app tự ngắt mic của nó: không cần làm gì (khung PCM ngừng tới, đệm tự cạn rồi neo lại)

    # ---------- chuyển trạng thái ----------
    async def activate(self) -> None:
        """`ringing_* -> active` (idempotent): AB báo người thân nghe / kính nghe thành công."""
        if self.state in (ACTIVE, ENDED):
            return
        self.state = ACTIVE
        self._cancel_timers("ring")
        if self._app_ws is None:
            self._timer(config.CALL_MEDIA_WAIT_S, self._media_expired, tag="media_wait")
        else:
            self._start_media()
        await self._notify_glasses()
        await self._send_app_state()
        await self._call_hook()

    async def glasses_answer(self) -> None:
        """Kính bấm nghe cuộc gọi tới: báo AB kèm `media_token`, xong mới `active`."""
        if self.direction != TO_GLASSES or self.state != RINGING_IN or self._answering:
            return
        self._answering = True
        try:
            await _ab_post(self.device, f"api/v1/service/call/{self.call_id}/answer", {"media_token": self.media_token})
        except Exception as exc:  # noqa: BLE001 - AB từ chối (đã kết thúc) / lỗi mạng
            logger.warning("call %s: AB answer lỗi (%r)", self.call_id, exc)
            await self.hangup("answer_failed", by="ab")
            return
        finally:
            self._answering = False
        await self.activate()

    async def hangup(self, reason: str, by: str = "server") -> None:
        """Kết thúc cuộc gọi (idempotent). `by`: glasses|app|server|ab. Báo AB trừ khi chính AB báo."""
        if self.state == ENDED:
            return
        self.state, self.end_reason = ENDED, reason
        self._cancel_timers()
        calls._remove(self)
        for task in list(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()
        if by != "ab" and not self.call_id.startswith("local-"):
            self.ab_task = self._spawn(self._ab_hangup(reason))
        if self._ended is not None:
            self._ended.set()
        await self._notify_glasses(reason)  # kính trước (đường nhạy trễ), rồi phiên, cuối cùng mới đóng đầu app
        await self._call_hook()
        await self._close_app(reason)
        self._log_latency()

    def end_soon(self, reason: str, by: str) -> None:
        """Cúp ở task RIÊNG: nơi gọi (endpoint WS bị server huỷ khi socket đóng, task gửi audio bị `hangup`
        huỷ) không được cắt ngang việc dọn dẹp giữa chừng."""
        task = asyncio.get_running_loop().create_task(self.hangup(reason, by))
        _bg.add(task)
        task.add_done_callback(_bg.discard)

    def hangup_threadsafe(self, reason: str, by: str = "server") -> None:
        loop = self.loop
        if loop is None:
            self.state, self.end_reason = ENDED, reason
            calls._remove(self)
            return
        asyncio.run_coroutine_threadsafe(self.hangup(reason, by), loop)

    # ---------- âm thanh ----------
    def from_glasses(self, adpcm_bytes: bytes) -> None:
        """Khung `0x05` của kính (ADPCM 256 B/khối, có thể tới lẻ) -> PCM16 640 B cho app. Đồng bộ, không chờ."""
        if self.state != ACTIVE or self._to_app is None:
            return
        t0 = time.monotonic()
        buf = self._g_rem + adpcm_bytes if self._g_rem else adpcm_bytes
        usable = len(buf) // _BLOCK * _BLOCK
        self._g_rem = buf[usable:]
        if not usable:
            return
        pcm = self._g_pcm + b"".join(decode_block(buf[i:i + _BLOCK]) for i in range(0, usable, _BLOCK))
        cut = len(pcm) // FRAME_BYTES * FRAME_BYTES
        self._g_pcm = pcm[cut:]
        duck = config.CALL_HALF_DUPLEX and t0 < self._app_loud_until
        for i in range(0, cut, FRAME_BYTES):
            frame = pcm[i:i + FRAME_BYTES]
            if duck:  # dự phòng khi kính không khử vọng: đầu app đang nói thì mic kính nhỏ đi
                gain = 10.0 ** (-config.CALL_HALF_DUPLEX_DUCK_DB / 20.0)
                frame = (np.frombuffer(frame, dtype="<i2").astype(np.float32) * gain).astype("<i2").tobytes()
            if self._to_app.full():
                self._to_app.get_nowait()
                self.stats["drop_g2a"] += 1
            self._to_app.put_nowait((t0, frame))

    def _on_app_frame(self, data: bytes) -> None:
        """Khung PCM16 từ app. Trước `active` hoặc sai cỡ thì bỏ."""
        if self.state != ACTIVE or not data or len(data) & 1 or len(data) > config.CALL_MAX_FRAME_BYTES:
            return
        now = time.monotonic()
        if config.CALL_HALF_DUPLEX and rms_dbfs(data) > config.CALL_HALF_DUPLEX_THRESHOLD_DBFS:
            self._app_loud_until = now + config.CALL_HALF_DUPLEX_HOLD_MS / 1000.0
        if self._jb is None:
            if self._to_glasses is not None:
                self._to_glasses.put_nowait((now, data))
            return
        self._jb.push(data, int(self._app_ts))  # seq_ts chỉ để sắp thứ tự; độ trễ do độ sâu đệm quyết định
        self._app_ts += len(data) / 32.0
        if self._jb.playing and self._wake is not None:
            self._wake.set()

    def _start_media(self) -> None:
        if self._jb is not None:
            self._wake = asyncio.Event()
            if self._jb.playing:
                self._wake.set()
        else:
            self._to_glasses = asyncio.Queue(_QUEUE_MAX)
        self._spawn(self._glasses_pump())

    async def _glasses_pump(self) -> None:
        try:
            if self._jb is None:
                while True:
                    t0, frame = await self._to_glasses.get()
                    await self._to_glasses_frame(frame, t0)
            nxt = time.monotonic()
            while True:
                if not self._jb.playing:
                    await self._wake.wait()
                    self._wake.clear()
                    nxt = time.monotonic()
                frame = self._jb.pop()
                if frame is not None:
                    await self._to_glasses_frame(frame, time.monotonic())
                nxt += 0.02
                delay = nxt - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                elif delay < -0.1:
                    nxt = time.monotonic()  # chậm quá 100 ms: đừng phát bù một chuỗi
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - socket kính đứt
            logger.info("call %s: gửi audio tới kính lỗi (%r)", self.call_id, exc)
            self.end_soon("glasses_disconnect", by="glasses")

    async def _to_glasses_frame(self, pcm: bytes, t0: float) -> None:
        out = self._enc.encode(pcm)
        if out and self._send_audio is not None:
            await self._send_audio(out)
            self.lat_a2g.append((time.monotonic() - t0) * 1000.0)
            self.stats["a2g_frames"] += 1

    async def _app_sender(self, ws) -> None:
        try:
            while True:
                t0, frame = await self._to_app.get()
                await ws.send_bytes(frame)
                self.lat_g2a.append((time.monotonic() - t0) * 1000.0)
                self.stats["g2a_frames"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - app rớt mạng giữa chừng
            logger.info("call %s: gửi audio tới app lỗi (%r)", self.call_id, exc)
            self.end_soon("peer_disconnect", by="app")

    # ---------- báo ra ngoài ----------
    async def _notify_glasses(self, reason: str | None = None) -> None:
        if self._send_state is None:
            return
        frame = {"t": "call_state", "call": self.call_id, "state": self.state, "peer": self.peer}
        if reason:
            frame["reason"] = reason
        with contextlib.suppress(Exception):  # kính rớt thì thôi: cuộc gọi đã kết thúc ở phía này
            await self._send_state(frame)

    async def _call_hook(self) -> None:
        if self._on_state is not None:
            try:
                await self._on_state(self)
            except Exception:  # noqa: BLE001
                logger.exception("call %s: móc trạng thái phiên lỗi", self.call_id)

    async def _send_app_state(self) -> None:
        ws = self._app_ws
        if ws is None:
            return
        state = "ringing" if self.state in (RINGING_OUT, RINGING_IN) else self.state
        frame = {"t": "state", "state": state}
        if self.end_reason:
            frame["reason"] = self.end_reason
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps(frame))

    async def _close_app(self, reason: str) -> None:
        ws, self._app_ws = self._app_ws, None
        if ws is None:
            return
        self.end_reason = reason
        frame = json.dumps({"t": "state", "state": "ended", "reason": reason})
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.send_text(frame), 1.0)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.close(1000), 1.0)

    async def _ab_hangup(self, reason: str) -> None:
        try:
            await _ab_post(self.device, f"api/v1/service/call/{self.call_id}/hangup", {"reason": reason})
        except Exception as exc:  # noqa: BLE001 - AB tự đánh `ended`/`missed` theo hạn chuông
            logger.warning("call %s: báo AB hangup lỗi (%r)", self.call_id, exc)

    def _log_latency(self) -> None:
        def pct(xs: collections.deque, q: float) -> float:
            s = sorted(xs)
            return round(s[min(len(s) - 1, int(len(s) * q))], 2) if s else 0.0

        logger.info("call %s: kết thúc (%s) kính->app p50=%s p90=%s ms (%d khung, bỏ %d), app->kính p50=%s p90=%s ms (%d)",
                    self.call_id, self.end_reason, pct(self.lat_g2a, .5), pct(self.lat_g2a, .9),
                    self.stats["g2a_frames"], self.stats["drop_g2a"],
                    pct(self.lat_a2g, .5), pct(self.lat_a2g, .9), self.stats["a2g_frames"])

    # ---------- phụ trợ ----------
    def _ended_event(self) -> asyncio.Event:
        if self._ended is None:
            self._ended = asyncio.Event()
            if self.state == ENDED:
                self._ended.set()
        return self._ended

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _timer(self, delay: float, fn: Callable[[], Awaitable[None]], tag: str = "ring") -> None:
        loop = self.loop or asyncio.get_running_loop()
        def fire() -> None:
            task = loop.create_task(fn())
            _bg.add(task)
            task.add_done_callback(_bg.discard)

        handle = loop.call_later(delay, fire)
        self._timers.append((tag, handle))

    def _cancel_timers(self, tag: str | None = None) -> None:
        keep = []
        for name, handle in self._timers:
            if tag is None or name == tag:
                handle.cancel()
            else:
                keep.append((name, handle))
        self._timers = keep

    async def _ring_expired(self) -> None:
        if self.state in (RINGING_OUT, RINGING_IN):
            await self.hangup("timeout", by="server")

    async def _media_expired(self) -> None:
        if self.state == ACTIVE and self._app_ws is None:
            await self.hangup("media_timeout", by="server")


async def _ab_post(device: str, path: str, payload: dict) -> dict:
    """POST tới AB (client httpx đồng bộ dùng chung) trong thread, mang `device` đã xác thực."""
    from services import visioncare_client

    def run() -> dict:
        with device_ctx.use(device, per_device=True):
            return visioncare_client.call_service_api(path, payload)

    return await asyncio.to_thread(run)


class CallRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, Call] = {}
        self._by_device: dict[str, Call] = {}
        self._by_token: dict[str, Call] = {}
        # `device_session` đặt: tìm phiên của `call.device` rồi gắn đầu kính (an toàn từ thread nền).
        self.attach_hook: Callable[[Call], None] | None = None

    def create(self, call_id: str | None, device: str, peer: str, direction: str, emergency: bool = False) -> Call:
        """Tạo cuộc gọi (gọi được từ thread nền). `call_id=None` = chưa có id của AB (kính gọi đi cần
        `media_token` TRƯỚC khi AB sinh id): dùng `call.media_token` gọi AB rồi `bind(call, id)`.
        Kính đang có cuộc gọi khác -> `GlassesBusy` (AB không chặn hai cuộc gọi trên một kính)."""
        if direction not in (TO_RELATIVE, TO_GLASSES):
            raise ValueError(direction)
        call = Call(call_id or "local-" + secrets.token_hex(6), device, peer, direction)
        call.emergency = emergency
        with self._lock:
            if device in self._by_device:
                raise GlassesBusy(device)
            self._by_device[device] = call
            self._by_id[call.call_id] = call
            self._by_token[_token_hash(call.media_token)] = call
        if self.attach_hook is not None:
            self.attach_hook(call)
        if call.loop is None:
            # Không có phiên kính để gắn (không có timer chuông trên loop): hạn dự phòng để kính không "bận" mãi.
            timer = threading.Timer(config.CALL_RING_TIMEOUT_S + config.CALL_TOKEN_GRACE_S, self._expire_unattached, (call,))
            timer.daemon = True
            timer.start()
        return call

    def _expire_unattached(self, call: Call) -> None:
        if call.session is None and call.state in (RINGING_OUT, RINGING_IN):
            call.end_reason = "timeout"
            call.state = ENDED
            self._remove(call)

    def bind(self, call: Call, call_id: str, peer: str | None = None) -> None:
        with self._lock:
            self._by_id.pop(call.call_id, None)
            call.call_id = call_id
            self._by_id[call_id] = call
        if peer:
            call.peer = peer

    def discard(self, call: Call, reason: str = "start_failed") -> None:
        """Bỏ cuộc gọi chưa thành (AB từ chối lúc `start`). Gọi được từ thread nền: đi qua `hangup_threadsafe`
        (by="ab": không dội AB) nên kính nhận `call_state ended` kèm lý do + phát `mode`, timer/task dọn trên loop."""
        call.hangup_threadsafe(reason, by="ab")

    def _remove(self, call: Call) -> None:
        with self._lock:
            if self._by_id.get(call.call_id) is call:
                del self._by_id[call.call_id]
            if self._by_device.get(call.device) is call:
                del self._by_device[call.device]
            self._by_token.pop(_token_hash(call.media_token), None)

    def by_device(self, device: str) -> "Call | None":
        return self._by_device.get(device)

    def get(self, call_id: str) -> "Call | None":
        return self._by_id.get(call_id)

    def claim_token(self, token: str) -> "Call | None":
        """Token media dùng MỘT lần: lấy ra là xoá. Sai / hết hạn / cuộc gọi đã kết thúc -> None."""
        if not token:
            return None
        with self._lock:
            call = self._by_token.pop(_token_hash(token), None)
        if call is None or call.state == ENDED or time.monotonic() > call.expires_at:
            return None
        return call


calls = CallRegistry()

# Dedupe callback của AB theo Idempotency-Key (AB thử lại 1/2/5/10 s)
_seen_events: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
_SEEN_MAX = 512


async def handle_event(body: dict, idempotency_key: str = "") -> tuple[int, dict]:
    """`POST /internal/calls` (đã qua xác thực): cập nhật `Call` + báo kính. -> (http_status, body)."""
    if idempotency_key and idempotency_key in _seen_events:
        return 200, _seen_events[idempotency_key]
    status, out = await _handle_event(body)
    if idempotency_key and status < 400:
        _seen_events[idempotency_key] = out
        while len(_seen_events) > _SEEN_MAX:
            _seen_events.popitem(last=False)
    return status, out


async def _handle_event(body: dict) -> tuple[int, dict]:
    from live import device_session

    event = str(body.get("event") or "")
    call_id = str(body.get("call_id") or "")
    device = str(body.get("glasses_device_id") or "")
    peer = str(body.get("peer_display_name") or "")
    reason = body.get("reason") or None

    def ok(matched: bool = True) -> tuple[int, dict]:
        return 200, {"status": "ok", "data": {"call_id": call_id, "matched": matched}}

    if event == "emergency_exhausted":
        call = calls.by_device(device)
        if call is not None and call.state == RINGING_OUT:
            await call.hangup("emergency_exhausted", by="ab")
        device_session.push_result(device, EMERGENCY_UNANSWERED)
        return ok(False)
    if not call_id or not event:
        return 422, {"detail": "event/call_id bắt buộc"}

    if event == "call_incoming":
        if calls.get(call_id) is not None:
            return ok()  # AB gửi lại
        session = device_session.session_for(device)
        # Không nhận được: trả 2xx (AB thử lại với mọi mã lỗi) rồi báo AB kết thúc bằng hangup ở nền.
        if session is None:
            _refuse(device, call_id, "glasses_offline")
            return ok(False)
        if not session.per_device:
            device_session.push_result(device, NEED_OWN_TOKEN)
            _refuse(device, call_id, "glasses_offline")
            return ok(False)
        try:
            calls.create(call_id, device, peer, TO_GLASSES, emergency=bool(body.get("emergency")))
        except GlassesBusy:  # AB không chặn hai cuộc gọi trên một kính
            _refuse(device, call_id, "busy")
            return ok(False)
        device_session.push_result(device, incoming_speech(peer or "Người thân"), f"call-{call_id}")
        return ok()

    call = calls.get(call_id)
    if call is None:
        return ok(False)  # đã kết thúc ở phía này / không phải của kính này: bỏ, trả 2xx để AB khỏi thử lại
    if event == "call_answered":
        await call.activate()
    elif event in ("call_rejected", "call_missed", "call_ended"):
        outgoing = call.direction == TO_RELATIVE and call.state == RINGING_OUT
        emergency = call.emergency or bool(body.get("emergency"))  # lời riêng của khẩn cấp do C6 lo
        name = call.peer or "Người thân"
        end = {"call_rejected": "rejected", "call_missed": "missed"}.get(event) or str(reason or "ended")
        await call.hangup(end, by="ab")
        if emergency:
            pass
        elif outgoing and event == "call_missed":
            device_session.push_result(device, missed_speech(name), f"call-{call_id}")
        elif outgoing and event == "call_rejected":
            device_session.push_result(device, rejected_speech(name), f"call-{call_id}")
    else:
        return 422, {"detail": "event không hỗ trợ"}
    return ok()


def _refuse(device: str, call_id: str, reason: str) -> asyncio.Task:
    """Không nhận được cuộc gọi tới: báo AB hangup ở nền (không giữ callback chờ HTTP tới AB)."""
    async def run() -> None:
        try:
            await _ab_post(device, f"api/v1/service/call/{call_id}/hangup", {"reason": reason})
        except Exception as exc:  # noqa: BLE001
            logger.warning("call %s: báo AB %s lỗi (%r)", call_id, reason, exc)

    task = asyncio.get_running_loop().create_task(run())
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return task

