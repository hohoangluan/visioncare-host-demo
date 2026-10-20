"""Làn B — OCR Realtime (§10): căn khung qua WS -> chụp UXGA -> Gemma -> TTS.

Đường nhanh: ảnh buffer UXGA chụp lúc bấm nút đã đạt chuẩn căn khung (chạy
detector lúc prewarm) thì đọc luôn ngay trong response `/v2/turn`, không mở
WebSocket — bỏ hẳn vòng căn khung lẫn một lần chụp nữa.
"""

import asyncio
import contextlib
import io
import logging
import threading
import time
from collections.abc import AsyncIterator

from PIL import Image
from starlette.websockets import WebSocket, WebSocketDisconnect

import config
from handlers import read_money
from lanes import general
from live import protocol, text_align
from live.session import LiveSession, sessions
from models import llm
from models.ocr import prompts
from pipeline import speech
from pipeline.image_buffer import resize_jpeg

logger = logging.getLogger("blind_assist")

_SUMMARIZE = prompts._COMMON + (
    "Tóm tắt nội dung chính của văn bản trong ảnh bằng tiếng Việt, 2 đến 4 câu "
    "ngắn, dễ nghe. Giữ đúng mọi con số, tên riêng, ngày tháng quan trọng."
)
_NO_TEXT = "Không thấy chữ nào đọc được."

# device -> (text, lúc lưu); "đọc lại" dùng trong 5 phút.
_LAST_TEXT: dict[str, tuple[str, float]] = {}
_LAST_LOCK = threading.Lock()


def last_text(device: str) -> str | None:
    with _LAST_LOCK:
        item = _LAST_TEXT.get(device)
    if item is None or time.monotonic() - item[1] > config.LAST_TEXT_TTL_S:
        return None
    return item[0]


def _remember(device: str, text: str) -> None:
    with _LAST_LOCK:
        _LAST_TEXT[device] = (text, time.monotonic())


def _prompt(mode: str) -> str:
    if mode == "summarize":
        return _SUMMARIZE
    if mode == "money":
        return read_money._PROMPT
    if mode in ("raw", "specialized"):  # dùng lại đúng văn bản prompt của models/ocr/prompts.py
        return prompts.build(mode)
    return prompts.build("normal")


def pick_image(hi_res: bytes | None, fallback_jpeg: bytes | None, best_vga: bytes | None) -> bytes | None:
    """Hết trần căn khung mà chưa có ảnh UXGA mới: ưu tiên UXGA buffer (đọc chữ rõ hơn
    hẳn VGA), VGA căn khung tốt nhất chỉ là phương án cuối."""
    return hi_res or fallback_jpeg or best_vga


async def read_image(jpeg: bytes, mode: str, device: str) -> AsyncIterator[str]:
    """Ảnh high-res -> từng mảnh text đọc lên. Lưu `last_text` khi xong."""
    image = await asyncio.to_thread(resize_jpeg, jpeg, config.LLM_OCR_IMAGE_MAX_SIDE, 90)
    stream = llm.stream_chat([llm.user_message(_prompt(mode), image)], max_tokens=1024, temperature=0.0)
    head, released, reply = "", False, []
    peek = len(prompts.NO_TEXT_SENTINEL) + 4
    async for piece in stream:
        if released:
            reply.append(piece)
            yield piece
            continue
        head += piece
        if len(head.strip()) > peek:
            released = True
            reply.append(head)
            yield head
    if not released:
        if head.strip().strip(".").strip() == prompts.NO_TEXT_SENTINEL or not head.strip():
            yield _NO_TEXT
            return
        reply.append(head)
        yield head
    text = "".join(reply).strip()
    if text and mode != "money":
        _remember(device, text)


def spoken(jpeg: bytes, mode: str, device: str) -> AsyncIterator[str]:
    """`read_image` với câu đầu cắt ngắn (<= 8 từ) để TTS đọc ngay, như làn chat.

    Gemma ra token đầu sau ~0,2 s nhưng câu đầu của một trang sách thường dài; TTS chỉ
    bắt đầu khi gặp dấu hết câu nên phải chờ cả câu dài sinh xong.
    """
    return general.short_first_sentence(read_image(jpeg, mode, device))


def _width(jpeg: bytes) -> int:
    try:
        return Image.open(io.BytesIO(jpeg)).size[0]
    except Exception:  # noqa: BLE001
        return 0


class _Mailbox:
    """Chỉ giữ khung MỚI NHẤT: xử lý chậm thì bỏ khung cũ, không xếp hàng trễ dần."""

    def __init__(self) -> None:
        self.frame: bytes | None = None
        self.event = asyncio.Event()
        self.closed = False

    def put(self, frame: bytes) -> None:
        self.frame = frame
        self.event.set()

    async def take(self, timeout: float) -> bytes | None:
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        self.event.clear()
        frame, self.frame = self.frame, None
        return frame


async def receive_frames(ws: WebSocket, box: _Mailbox, session: LiveSession) -> None:
    min_gap = 1.0 / config.LIVE_MAX_FPS if config.LIVE_MAX_FPS > 0 else 0.0
    last = 0.0
    try:
        while not session.closed.is_set():
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                # Khung quá trần/quá fps: bỏ khung, KHÔNG đóng phiên (Task 9).
                now = time.monotonic()
                if len(data) > config.LIVE_MAX_FRAME_BYTES or now - last < min_gap:
                    continue
                last = now
                frame = protocol.parse_frame(data)
                if frame is not None:
                    box.put(frame)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        box.closed = True
        box.event.set()


async def speak_ws(ws: WebSocket, text) -> None:
    """Text (iterable đồng bộ) -> TTS -> khung 0x02 ADPCM qua WS.

    Trên `/v2/session` giữ khoá audio của phiên (`ws.audio_lock`) trọn câu: kết quả hành động / câu trả lời
    lượt khác xếp hàng sau, không xen vào audio đọc chữ.
    """
    async with getattr(ws, "audio_lock", None) or contextlib.nullcontext():
        async with contextlib.aclosing(speech.adpcm_stream(text)) as chunks:
            async for chunk in chunks:
                await ws.send_bytes(protocol.audio(chunk))


async def run(ws: WebSocket, session: LiveSession) -> None:
    mode = session.params.get("mode", "read")
    box = _Mailbox()
    receiver = asyncio.create_task(receive_frames(ws, box, session))
    aligner = text_align.Aligner()
    det = text_align.detector()
    started = time.monotonic()
    deadline = started + config.OCR_ALIGN_TIMEOUT_S
    best_vga: bytes | None = None
    debug = getattr(ws, "debug", None)  # chỉ có trên LiveSocket của phiên bật debug (demo)
    try:
        await ws.send_text(protocol.cam("vga", 5))
        capture_sent = False
        capture_deadline = 0.0
        hi_res: bytes | None = None
        while not box.closed and not session.closed.is_set():
            now = time.monotonic()
            if not capture_sent and now >= deadline:
                logger.info("OCR live: hết trần %.0fs, chụp luôn", config.OCR_ALIGN_TIMEOUT_S)
                capture_sent, capture_deadline = True, now + 3.0
                await ws.send_text(protocol.capture("uxga"))
            if capture_sent and now >= capture_deadline:
                break
            frame = await box.take(0.5)
            if frame is None:
                continue
            if _width(frame) >= 1000:
                hi_res = frame
                break
            if capture_sent:
                continue
            best_vga = frame
            decoded = await asyncio.to_thread(text_align.decode_gray, frame)
            if decoded is None:
                continue
            gray, _ = decoded
            boxes = await asyncio.to_thread(det.detect, gray)
            action = aligner.step_gray(gray, boxes)
            if debug is not None:
                debug({"t": "ocr", "w": gray.shape[1], "h": gray.shape[0],
                       "boxes": [[int(v) for v in b] for b in boxes],
                       "cue": action.cue if action is not None and action.kind == "cue" else None,
                       "capture": action is not None and action.kind == "capture"})
            if action is None:
                continue
            if action.kind == "cue":
                await ws.send_text(protocol.cue(action.cue))
            else:
                logger.info("OCR live: khung đạt sau %.1fs, chụp UXGA", time.monotonic() - started)
                capture_sent, capture_deadline = True, time.monotonic() + 3.0
                await ws.send_text(protocol.capture("uxga"))

        image = pick_image(hi_res, session.params.get("fallback_jpeg"), best_vga)
        if image is None or box.closed or session.closed.is_set():
            return
        loop = asyncio.get_running_loop()
        await speak_ws(ws, speech.sync_iter(spoken(image, mode, session.device), loop))
        await ws.send_text(protocol.end())
    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("OCR live: kính ngắt kết nối (%r), huỷ", exc)
    finally:
        receiver.cancel()
        sessions.release(session)
