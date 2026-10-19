"""`WS /v2/session`: một WebSocket mỗi kính, ghép kênh lượt + audio trả lời + live OCR/nav.

Vì sao một socket: qua Cloudflare tunnel mỗi HTTP request là một lần bắt tay + proxy
gom body, còn WS giữ kết nối nóng nên audio tới server theo từng mảnh đúng lúc nói
(đoán sớm/prewarm có tác dụng) và câu trả lời đi ngược lại không chờ header.

Giao thức (JSON text; binary có byte đầu là loại):
    kính -> server  hello | turn_start | 0x01 JPEG lượt | 0x03 ADPCM lượt | turn_end
                    | 0x04 JPEG khung live | cancel | played | ping
    server -> kính  hello_ok | reply | 0x02 khối audio | reply_end | cam/capture/cue/hazard/end
                    (live, giữ nguyên `live/protocol.py`) | pong | error

Ngữ nghĩa huỷ (an toàn làn D): `turn_start` mới, `cancel`, đóng socket và phiên mới
của cùng kính đều: huỷ task `turn.run` + stream audio, huỷ live, rồi `begin_turn`
(tăng thế hệ + huỷ lệnh chờ làn D) — lệnh "gọi mẹ" đang chờ đọc xong không được chạy
khi kính đã rớt mạng hay bấm lại.
"""

import asyncio
import json
import logging
import secrets
import threading
import time
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket, WebSocketDisconnect

import config
from live import protocol
from live.session import sessions
from live.ws_adapter import LiveSocket
from pipeline import adpcm, cues, device_ctx, guard, pending_action
from pipeline import turn as turn_v2
from pipeline.image_buffer import image_buffer
from pipeline.reply import Reply

logger = logging.getLogger("blind_assist")

T_TURN_IMAGE = 0x01
T_TURN_AUDIO = 0x03
T_LIVE_FRAME = 0x04
PING_S = 25
IDLE_TIMEOUT_S = PING_S * 3 + 15  # Cloudflare cắt idle ~100 s; kính ping mỗi PING_S
HELLO_TIMEOUT_S = 10.0
AUDIO_CONTENT_TYPE = "audio/x-adpcm-ima; rate=16000; channels=1; block=256"
RESPONSE_FORMAT = "adpcm_stream"  # khối 256 byte trần: không header RIFF qua WS
_MAX_DEVICE_LEN = 64

ReplyAudio = Callable[..., Awaitable[tuple[dict, object]]]

# device -> phiên đang mở (phiên mới thay phiên cũ)
_registry: dict[str, "DeviceSession"] = {}


def _audio_expected(reply: Reply, cue_ok: bool) -> bool:
    """Có audio sau `reply` không (cùng điều kiện với `app._reply_audio`)."""
    speech = reply.speech
    if speech is not None and not (isinstance(speech, (list, tuple)) and not speech):
        return True
    return not cue_ok and any(cues.fallback_text(c) for c in reply.cues)


class _Turn:
    def __init__(self, turn_id: str) -> None:
        self.id = turn_id
        self.audio_q: asyncio.Queue = asyncio.Queue()  # bytes | None (None = nhả nút)
        self.audio_bytes = 0
        self.task: asyncio.Task | None = None
        self.cancelled_in_run = False

    async def body(self):
        while True:
            chunk = await self.audio_q.get()
            if chunk is None:
                return
            yield chunk


class DeviceSession:
    def __init__(self, ws: WebSocket, reply_audio: ReplyAudio) -> None:
        self.ws = ws
        self._reply_audio = reply_audio
        self.device = ""
        self.cue_version = 0
        self.session_id = secrets.token_hex(6)
        self._send_lock = asyncio.Lock()
        self._turn: _Turn | None = None
        self._live_task: asyncio.Task | None = None
        self._live_session = None
        self._live_sock: LiveSocket | None = None
        self._shut = False
        self._replaced = False
        self._evloop = asyncio.get_running_loop()
        self._unclaimed: str | None = None

    # ---------- gửi ----------
    async def send_json(self, obj: dict) -> None:
        await self.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_text(self, text: str) -> None:
        async with self._send_lock:
            await self.ws.send_text(text)

    async def send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def error(self, code: str) -> None:
        try:
            await self.send_json({"t": "error", "code": code})
        except (WebSocketDisconnect, RuntimeError):
            pass

    # ---------- vòng đời ----------
    async def run(self) -> None:
        if not await self._hello():
            return
        old = _registry.get(self.device)
        _registry[self.device] = self
        if old is not None and old is not self:
            await old.replace()
        device_ctx.current.set(self.device)  # task con thừa kế
        try:
            await self.send_json(
                {"t": "hello_ok", "session": self.session_id, "cue_version": cues.CUE_VERSION, "ping_s": PING_S}
            )
            await self._loop()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self.shutdown("socket đóng")
            if _registry.get(self.device) is self:
                del _registry[self.device]

    async def _hello(self) -> bool:
        try:
            msg = await asyncio.wait_for(self.ws.receive(), HELLO_TIMEOUT_S)
        except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
            await self._close(4400)
            return False
        if msg["type"] == "websocket.disconnect":
            return False
        hello = None
        if msg.get("text"):
            try:
                hello = json.loads(msg["text"])
            except ValueError:
                hello = None
        if not isinstance(hello, dict) or hello.get("t") != "hello":
            await self.error("bad_frame")
            await self._close(4400)
            return False
        token = hello.get("token")
        if not guard.token_ok(token if isinstance(token, str) and token else self.ws.headers):
            await self._close(4401)
            return False
        device = str(hello.get("device") or config.VISIONCARE_DEVICE_ID)[:_MAX_DEVICE_LEN]
        self.device = device
        try:
            self.cue_version = int(hello.get("cue_version") or 0)
        except (TypeError, ValueError):
            self.cue_version = 0
        logger.info("v2 session %s: hello device=%s fw=%s accept=%s", self.session_id, device,
                    str(hello.get("fw", ""))[:32], str(hello.get("accept", ""))[:80])
        return True

    async def _close(self, code: int) -> None:
        try:
            await self.ws.close(code=code)
        except RuntimeError:
            pass

    async def replace(self) -> None:
        """Phiên mới của cùng kính: huỷ sạch việc dở của phiên này rồi đóng 4000."""
        if asyncio.get_running_loop() is not self._evloop:
            # Chỉ xảy ra khi mỗi socket một event loop (TestClient); server thật dùng một loop.
            future = asyncio.run_coroutine_threadsafe(self._replace_here(), self._evloop)
            await asyncio.wrap_future(future)
            return
        await self._replace_here()

    async def _replace_here(self) -> None:
        self._replaced = True
        await self.shutdown("phiên mới thay thế")
        await self._close(4000)

    async def shutdown(self, reason: str) -> None:
        """Idempotent. Phải xong TRƯỚC khi phiên thay thế làm gì tiếp (nếu không
        begin_turn của phiên cũ sẽ huỷ nhầm lệnh chờ của phiên mới)."""
        if self._shut:
            return
        self._shut = True
        await self._cancel_work(reason)

    # ---------- huỷ ----------
    async def _cancel_work(self, reason: str, keep_nav: bool = False) -> None:
        """Huỷ lượt + live đang chạy, rồi tăng thế hệ & huỷ lệnh chờ làn D.

        `keep_nav`: lượt mới/`cancel` của nút bấm KHÔNG được tắt cảnh báo vật cản — người
        khiếm thị hỏi gì đó giữa lúc dẫn đường vẫn phải được cảnh báo. Nav chỉ dừng khi
        nav_stop, đóng socket hoặc phiên bị thay. OCR live thì vẫn bị lượt mới huỷ.
        """
        tasks = []
        turn, self._turn = self._turn, None
        if turn is not None and turn.task is not None:
            turn.task.cancel()
            tasks.append(turn.task)
        if not (keep_nav and self._live_session is not None and self._live_session.mode == "nav"):
            tasks.extend(self._stop_live())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        pending_action.begin_turn(self.device)
        logger.info("v2 session %s: huỷ (%s)", self.session_id, reason)

    def _stop_live(self) -> list[asyncio.Task]:
        tasks = []
        if self._live_sock is not None:
            self._live_sock.feed_disconnect()
        if self._live_session is not None:
            self._live_session.closed.set()
        if self._live_task is not None:
            self._live_task.cancel()
            tasks.append(self._live_task)
        self._live_task = self._live_session = self._live_sock = None
        return tasks

    # ---------- vòng nhận ----------
    async def _loop(self) -> None:
        while True:
            try:
                msg = await asyncio.wait_for(self.ws.receive(), IDLE_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.info("v2 session %s: idle quá %ds, đóng", self.session_id, IDLE_TIMEOUT_S)
                await self._close(1001)
                return
            if msg["type"] == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                await self._on_binary(data)
            elif msg.get("text") is not None:
                await self._on_text(msg["text"])

    async def _on_text(self, text: str) -> None:
        try:
            frame = json.loads(text)
            kind = frame["t"]
        except (ValueError, KeyError, TypeError):
            await self.error("bad_frame")
            return
        if kind == "ping":
            await self.send_json({"t": "pong"})
        elif kind == "turn_start":
            await self._turn_start(frame)
        elif kind == "turn_end":
            turn = self._turn
            if turn is not None and str(frame.get("turn", turn.id)) == turn.id:
                turn.audio_q.put_nowait(None)
        elif kind == "cancel":
            if not self._shut:  # socket cũ đã bị thay không được huỷ lệnh chờ của phiên mới
                await self._cancel_work("kính huỷ", keep_nav=True)
        elif kind == "played":
            logger.info("v2 played: %s", {k: frame.get(k) for k in ("turn", "first_byte_ms", "first_audio_ms")})
        elif kind == "hello":
            pass  # hello lặp: bỏ qua
        else:
            await self.error("bad_frame")

    async def _on_binary(self, data: bytes) -> None:
        if not data:
            await self.error("bad_frame")
            return
        kind, payload = data[0], data[1:]
        turn = self._turn
        if kind == T_LIVE_FRAME:
            # Khung live vượt trần/fps do runner bỏ (ocr_live.receive_frames); ngoài live thì bỏ ở đây.
            if self._live_sock is not None and len(payload) <= config.LIVE_MAX_FRAME_BYTES:
                self._live_sock.feed_frame(payload)
        elif kind == T_TURN_IMAGE:
            if turn is None:
                return  # lượt bị từ chối/huỷ: khung đang bay bỏ lặng lẽ, không dội lỗi
            if len(payload) > config.DEVICE_MAX_IMAGE_BYTES:
                await self.error("too_large")
            elif payload:
                image_buffer.put(self.device, turn.id, payload)
        elif kind == T_TURN_AUDIO:
            if turn is None:
                return
            turn.audio_bytes += len(payload)
            if turn.audio_bytes > config.DEVICE_MAX_AUDIO_S * adpcm.BYTE_RATE:
                if turn.audio_bytes - len(payload) <= config.DEVICE_MAX_AUDIO_S * adpcm.BYTE_RATE:
                    await self.error("too_large")  # báo một lần, các khối sau bỏ lặng lẽ
                return
            turn.audio_q.put_nowait(payload)
        else:
            await self.error("bad_frame")

    # ---------- lượt ----------
    async def _turn_start(self, frame: dict) -> None:
        from handlers.action_flow import device_state

        if self._shut:
            return
        await self._cancel_work("lượt mới", keep_nav=True)
        if self._shut:
            return
        # Sau huỷ: chỉ còn nav (OCR live đã dừng) nên `alerting` đúng nghĩa cảnh báo vật cản.
        state = {**device_state(), "alerting": sessions.active(self.device) is not None}
        if not guard.limiters()[0].allow(self.device):
            await self.error("rate_limited")
            return
        turn = _Turn(str(frame.get("turn", "")))
        self._turn = turn
        gen = pending_action.generation(self.device)
        turn.task = asyncio.create_task(self._run_turn(turn, state, gen))

    async def _run_turn(self, turn: _Turn, state: dict, gen: int) -> None:
        try:
            try:
                result = await turn_v2.run(
                    self.device, turn.id, AUDIO_CONTENT_TYPE, turn.body(), state, gen=gen,
                    on_cancel=lambda: setattr(turn, "cancelled_in_run", True),
                )
                reply, released = result.reply, result.released_at
            except Exception:  # noqa: BLE001 - kính luôn phải nghe được gì đó
                logger.exception("v2 session turn %s thất bại", turn.id)
                reply, released = Reply(cues=["system_busy"]), time.monotonic()
            await self._send_reply(turn, reply, released)
        except (WebSocketDisconnect, RuntimeError) as exc:
            logger.info("v2 session turn %s: socket đứt (%r)", turn.id, exc)
        except asyncio.CancelledError:
            logger.info("v2 session turn %s: bị huỷ (trong run=%s)", turn.id, turn.cancelled_in_run)
            raise

    async def _send_reply(self, turn: _Turn, reply: Reply, released: float) -> None:
        cue_ok = self.cue_version >= cues.CUE_VERSION
        has_audio = _audio_expected(reply, cue_ok)
        # `reply` đi NGAY (cue phát từ flash trong lúc TTS dựng mảnh đầu).
        await self.send_json({
            "t": "reply", "turn": turn.id, "cues": reply.cues if cue_ok else [],
            "live": reply.live,
            "audio": {"format": "ima_adpcm;rate=16000;channels=1;block=%d" % adpcm.BLOCK_ALIGN,
                      "sample_rate": adpcm.SAMPLE_RATE, "preroll_s": config.V2_AUDIO_PREROLL_SECONDS}
            if has_audio else None,
        })
        try:
            self._unclaimed = reply.live_token if reply.live else None
            _, body = await self._reply_audio(reply, cue_ok, RESPONSE_FORMAT, released)
            if body is not None:
                async for chunk in _iter_in_thread(body):
                    await self.send_bytes(protocol.audio(chunk))
            await self.send_json({"t": "reply_end", "turn": turn.id})
            if reply.live:
                await self._start_live(reply)
        finally:
            sessions.discard(self._unclaimed)  # bị huỷ trước khi nhận token live: bỏ luôn
            self._unclaimed = None

    async def _start_live(self, reply: Reply) -> None:
        from lanes import nav_live, ocr_live

        old = self._stop_live()  # live mới thay live cũ (vd. nav còn chạy từ lượt trước)
        if old:
            await asyncio.gather(*old, return_exceptions=True)
        live = sessions.claim(reply.live_token or "")
        self._unclaimed = None
        if live is None:
            logger.warning("v2 session %s: token live hết hạn", self.session_id)
            return
        sock = LiveSocket(self.send_text, self.send_bytes)
        runner = ocr_live.run if live.mode == "ocr" else nav_live.run
        self._live_session, self._live_sock = live, sock
        # Chạy ở task riêng để vòng nhận (và turn_start/cancel) không bị chặn; task
        # `_run_turn` kết thúc ngay sau đây nên không tự huỷ chính live của mình.
        self._live_task = asyncio.create_task(runner(sock, live))


async def _iter_in_thread(body):
    """Iterator đồng bộ (TTS+ADPCM) -> async iterator; thread tự đóng generator khi bị huỷ.

    Đóng generator từ thread khác khi nó đang chạy sẽ ném ValueError, nên chỉ chính
    thread đọc mới được đóng nó (trong `finally`).
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()
    done = object()

    def worker() -> None:
        try:
            for chunk in body:
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except BaseException as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
            loop.call_soon_threadsafe(queue.put_nowait, done)

    device_ctx.run_in_thread(worker, name="ws-reply")
    try:
        while True:
            item = await queue.get()
            if item is done:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()


async def serve(ws: WebSocket, reply_audio: ReplyAudio) -> None:
    await DeviceSession(ws, reply_audio).run()
