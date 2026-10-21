"""`WS /v2/observe`: phiên CHỈ XEM cho trang demo của ban giám khảo.

Trang demo không phải kính: không bật camera/micro, không gửi lượt. Nó nối vào đây để nhìn
cái kính gửi gì lên và server xử lý ra sao. Phiên xem không thay phiên của kính (khác `/v2/session`
bị `4000`), không gửi được gì vào lượt/live của kính, và kính thật không biết có người xem.

    trang -> server   hello {token, device?} | ping
    server -> trang   hello_ok | glasses {online} | pong
                      + mọi thứ kính gửi/nhận, đã lọc:
        từ kính       turn_start | turn_end (JSON) | 0x01 JPEG ảnh lượt
        từ server     reply | reply_end | cam | capture | cue | hazard | end | call_state (JSON)
                      0x02 ADPCM tiếng trả lời
        debug         trace | say | mode (JSON)
                      det | ocr: [0x04 JPEG khung server vừa xử lý] ngay trước JSON `det`/`ocr` của chính nó,
                      nên box luôn vẽ đúng lên đúng khung (không lệch do độ trễ).

Mọi khung gửi cho người xem đều không chờ: người xem chậm thì khung cũ bị bỏ (khung det/ocr chỉ giữ cái mới
nhất), không bao giờ làm chậm kính. Token như kính (`hello.token`); token riêng chỉ xem được đúng kính của nó,
token chung không khai `device` thì xem mọi kính.
"""

import asyncio
import collections
import contextlib
import json
import logging
from collections.abc import Iterable

from starlette.websockets import WebSocket, WebSocketDisconnect

from pipeline import guard

logger = logging.getLogger("blind_assist")

PING_S = 25
IDLE_TIMEOUT_S = PING_S * 3 + 15
HELLO_TIMEOUT_S = 10.0
_MAX_DEVICE_LEN = 64
_QUEUE_MAX = 400  # gói chờ gửi tối đa mỗi người xem; đầy thì bỏ gói cũ nhất
ANY_DEVICE = "*"

# Một "gói" = các khung gửi liền nhau theo thứ tự (bytes -> nhị phân, str -> text).
Bundle = tuple[bytes | str, ...]


class Observer:
    def __init__(self, ws: WebSocket, watch: str) -> None:
        self.ws = ws
        self.watch = watch
        self._loop = asyncio.get_running_loop()
        self._q: collections.deque[tuple[str | None, Bundle]] = collections.deque()
        self._wake = asyncio.Event()
        self._closed = False

    def offer(self, bundle: Bundle, key: str | None = None) -> None:
        """Gọi từ bất kỳ thread/event loop nào. `key` khác None: thay gói cùng key đang chờ (chỉ giữ cái mới nhất)."""
        if self._closed:
            return
        try:
            self._loop.call_soon_threadsafe(self._push, bundle, key)
        except RuntimeError:  # loop của người xem đã đóng
            self._closed = True

    def _push(self, bundle: Bundle, key: str | None) -> None:
        if self._closed:
            return
        if key is not None:
            for item in self._q:
                if item[0] == key:
                    self._q.remove(item)
                    break
        self._q.append((key, bundle))
        while len(self._q) > _QUEUE_MAX:
            self._q.popleft()
        self._wake.set()

    async def pump(self) -> None:
        """Gửi lần lượt từng gói tới trang; ném lỗi khi socket đứt (để `serve` dọn)."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._q:
                _, bundle = self._q.popleft()
                for frame in bundle:
                    if isinstance(frame, str):
                        await self.ws.send_text(frame)
                    else:
                        await self.ws.send_bytes(frame)

    def close(self) -> None:
        self._closed = True


class Observers:
    def __init__(self) -> None:
        self._by: dict[str, set[Observer]] = {}

    def add(self, obs: Observer) -> None:
        self._by.setdefault(obs.watch, set()).add(obs)

    def remove(self, obs: Observer) -> None:
        obs.close()
        group = self._by.get(obs.watch)
        if group is not None:
            group.discard(obs)
            if not group:
                del self._by[obs.watch]

    def _targets(self, device: str) -> list[Observer]:
        return [*self._by.get(device, ()), *self._by.get(ANY_DEVICE, ())]

    def any(self, device: str) -> bool:
        return bool(self._by.get(device) or self._by.get(ANY_DEVICE))

    def publish(self, device: str, frames: Iterable[bytes | str], key: str | None = None) -> None:
        bundle = tuple(frames)
        for obs in self._targets(device):
            obs.offer(bundle, key)

    def text(self, device: str, obj: dict | str, key: str | None = None) -> None:
        if self.any(device):
            self.publish(device, [obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)], key)

    def binary(self, device: str, data: bytes) -> None:
        if self.any(device):
            self.publish(device, [data])


observers = Observers()


async def _close(ws: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError):
        await ws.close(code=code)


async def _hello(ws: WebSocket) -> str | None:
    """-> khoá đang xem (id kính hoặc `*`), hoặc None nếu đã đóng socket."""
    try:
        msg = await asyncio.wait_for(ws.receive(), HELLO_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        await _close(ws, 4400)
        return None
    if msg["type"] == "websocket.disconnect":
        return None
    hello = None
    if msg.get("text"):
        try:
            hello = json.loads(msg["text"])
        except ValueError:
            hello = None
    if not isinstance(hello, dict) or hello.get("t") != "hello":
        await _close(ws, 4400)
        return None
    token = hello.get("token")
    claimed = str(hello.get("device") or "")[:_MAX_DEVICE_LEN]
    auth = guard.authenticate(token if isinstance(token, str) and token else ws.headers, claimed or None)
    if auth is None:
        await _close(ws, 4401)
        return None
    return auth.device_id[:_MAX_DEVICE_LEN] if auth.per_device else (claimed or ANY_DEVICE)


async def serve(ws: WebSocket) -> None:
    from live import device_session

    watch = await _hello(ws)
    if watch is None:
        return
    obs = Observer(ws, watch)
    observers.add(obs)
    writer: asyncio.Task | None = None
    try:
        glasses = device_session.sessions_watched(watch)
        await ws.send_text(json.dumps({
            "t": "hello_ok", "role": "observer", "watch": watch, "ping_s": PING_S,
            "glasses": bool(glasses),
        }))
        for session in glasses:  # vào giữa chừng: cho trang biết ngay kính nào đang nối + chế độ hiện tại
            session.announce_to_observers(obs)
        writer = asyncio.create_task(obs.pump())
        while True:
            reader = asyncio.ensure_future(asyncio.wait_for(ws.receive(), IDLE_TIMEOUT_S))
            await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
            if writer.done():
                reader.cancel()
                writer.result()  # ném lỗi gửi (socket đứt)
                return
            try:
                msg = reader.result()
            except asyncio.TimeoutError:
                await _close(ws, 1001)
                return
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("text") and '"ping"' in msg["text"]:
                obs.offer((json.dumps({"t": "pong"}),))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        observers.remove(obs)
        if writer is not None:
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await writer
