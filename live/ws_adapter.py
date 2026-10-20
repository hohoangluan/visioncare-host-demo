"""Giả `WebSocket` cho `ocr_live.run` / `nav_live.run` chạy trên socket phiên `/v2/session`.

Hai runner live viết cho `WS /v2/live` riêng và chỉ gọi đúng 3 method trên socket
(đọc từ `lanes/ocr_live.py::receive_frames`, `speak_ws`, `run` và
`lanes/nav_live.py::run`, `_speak_outbox`):

    await ws.receive()      -> dict kiểu starlette ("websocket.receive" / "websocket.disconnect")
    await ws.send_text(s)
    await ws.send_bytes(b)

Chỉ cài đúng ba method đó. Vòng nhận của phiên là nơi DUY NHẤT đọc socket thật;
nó đẩy khung live vào đây bằng `feed_frame` (khung 0x04 của kính đổi về 0x01 + JPEG
là định dạng `protocol.parse_frame` mong đợi) và báo ngắt bằng `feed_disconnect`.
"""

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable

from live import protocol
from pipeline import cues, speech

_QUEUE_MAX = 8  # runner chỉ giữ khung mới nhất (_Mailbox); đầy thì bỏ khung cũ nhất


class LiveSocket:
    def __init__(
        self,
        send_text: Callable[[str], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
        speak_cues: bool = False,
        audio_lock: asyncio.Lock | None = None,
        debug: Callable[[dict], None] | None = None,
    ) -> None:
        # Khoá kênh audio 0x02 của phiên: mỗi câu nói (outbox nav, OCR, cue đọc thay clip) giữ nó trọn câu
        # để không xen với câu trả lời của lượt / kết quả hành động. Khung JSON không cần khoá.
        self.audio_lock = audio_lock
        # Chỉ phiên bật `hello.debug` (trang demo) mới có: runner gửi khung det/ocr bằng móc này,
        # không chờ và không bao giờ ném lỗi (xem `DeviceSession.emit_debug`).
        self.debug = debug
        # Kính có `cue_version` cũ hơn server (không có clip trong flash): khung
        # {"t":"cue"} đổi thành câu nói TTS, giống `_send_reply` làm với cue của lượt.
        self._speak_cues = speak_cues
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._inbox: asyncio.Queue = asyncio.Queue(_QUEUE_MAX)
        self._closed = False

    # --- phía vòng nhận của phiên ---
    def feed_frame(self, jpeg: bytes) -> None:
        if self._closed:
            return
        if self._inbox.full():
            self._inbox.get_nowait()
        self._inbox.put_nowait({"type": "websocket.receive", "bytes": bytes([protocol.FRAME_JPEG]) + jpeg})

    def feed_disconnect(self) -> None:
        if self._closed:
            return
        self._closed = True
        while self._inbox.full():
            self._inbox.get_nowait()
        self._inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})

    # --- phía runner ---
    async def receive(self) -> dict:
        return await self._inbox.get()

    async def send_text(self, data: str) -> None:
        if self._speak_cues and '"cue"' in data:
            try:
                frame = json.loads(data)
            except ValueError:
                frame = None
            if isinstance(frame, dict) and frame.get("t") == "cue":
                text = cues.fallback_text(str(frame.get("id", "")))
                if text:
                    async with self.audio_lock or contextlib.nullcontext():
                        async with contextlib.aclosing(speech.adpcm_stream([text])) as chunks:
                            async for chunk in chunks:
                                await self._send_bytes(protocol.audio(chunk))
                return
        await self._send_text(data)

    async def send_bytes(self, data: bytes) -> None:
        await self._send_bytes(data)
