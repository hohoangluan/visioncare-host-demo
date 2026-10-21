"""Làn B — OCR Realtime (§10): căn khung qua WS -> chụp UXGA -> Gemma -> TTS.

Đường nhanh: ảnh buffer UXGA chụp lúc bấm nút đã đạt chuẩn căn khung (chạy
detector lúc prewarm) thì đọc luôn ngay trong response `/v2/turn`, không mở
WebSocket — bỏ hẳn vòng căn khung lẫn một lần chụp nữa.
"""

import asyncio
import contextlib
import io
import logging
import math
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
# Nói SAU câu trả lời khi có chữ số model đọc kém chắc (xác suất token < OCR_DIGIT_HEDGE_PROB).
# Đo dev 2026-10-21 (SROIE + ViTextVQA, 424 câu có số): AUROC 0,82; τ 0,9 bắt ~1/3 số đọc sai, gắn
# cảnh báo cho ~5 % câu — vẫn đọc số (không mất câu đúng), chỉ báo người mù nên kiểm lại.
DIGIT_HEDGE = "Có con số tôi đọc chưa chắc, bạn đưa lại gần để tôi đọc lại."
# Báo thoát chế độ cho người chỉ nghe (2-3 từ; dựng sẵn qua STATIC_SPEECH). Nói SAU nội dung chính, chỉ khi OCR live
# tự kết thúc: huỷ bằng lượt mới, kính ngắt kết nối hay phiên bị thay thì im (đã có việc khác đang nói).
EXIT_READ = "Thoát đọc chữ."
EXIT_MONEY = "Thoát đọc tiền."
STATIC_SPEECH: tuple[str, ...] = (EXIT_READ, EXIT_MONEY)

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
    if mode == "money" and config.MONEY_MODE == "choice":
        async for piece in read_money.read_choice([image]):
            yield piece
        return
    message = llm.user_message(_prompt(mode), image)
    digit_probs: list[float] = []

    def seen(items: list[dict]) -> None:
        digit_probs.extend(math.exp(it["logprob"]) for it in items
                           if it.get("logprob") is not None and any(c.isdigit() for c in it.get("token", "")))

    hedge = config.OCR_DIGIT_HEDGE_PROB > 0
    stream = llm.stream_chat([message], max_tokens=1024, temperature=0.0, on_logprobs=seen if hedge else None)
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
    if hedge and digit_probs and min(digit_probs) < config.OCR_DIGIT_HEDGE_PROB:
        logger.info("đọc chữ: chữ số kém chắc (p min %.3f) -> cảnh báo", min(digit_probs))
        yield " " + DIGIT_HEDGE
    if text and mode != "money":
        _remember(device, text)


async def read_money_frame(jpeg: bytes, min_prob: float) -> tuple[str, list[tuple[str, float]] | None]:
    """Đọc tiền đúng MỘT khung (cỡ ảnh như `read_image`): (câu nói, top-2 nhãn; None khi lỗi mạng/model)."""
    image = await asyncio.to_thread(resize_jpeg, jpeg, config.LLM_OCR_IMAGE_MAX_SIDE, 90)
    return await read_money.read_ranked(image, min_prob)


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
        self.received_at = 0.0  # lúc `put` khung đang giữ
        self.taken_at = 0.0     # lúc NHẬN của khung `take` vừa trả (khác lúc xử lý khi vòng lặp bận)
        self.event = asyncio.Event()
        self.closed = False

    def put(self, frame: bytes) -> None:
        self.frame = frame
        self.received_at = time.monotonic()
        self.event.set()

    async def take(self, timeout: float) -> bytes | None:
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        self.event.clear()
        frame, self.frame = self.frame, None
        self.taken_at = self.received_at
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


async def _money_retry(ws: WebSocket, box: _Mailbox, session: LiveSession) -> None:
    """Đọc tiền lại MỘT lần sau câu hướng dẫn (final_router._money): bỏ khung trong MONEY_RETRY_SETTLE_S đầu cho người
    dùng chỉnh tay, lấy khung đầu tiên đủ nét (độ nét >= MONEY_BLUR_HINT); hết MONEY_RETRY_TIMEOUT_S thì khung nét nhất
    đã thấy; không có khung nào thì nói "vẫn chưa đọc chắc". Không bao giờ đọc lần thứ hai (người khiếm thị không kẹt vòng lặp)."""
    await ws.send_text(protocol.cam("vga", 5))
    # Đồng hồ tính từ SAU khi gửi `cam` (gửi chậm không được ăn vào thời gian chỉnh tay / hạn đọc).
    started = time.monotonic()
    settle_end, deadline = started + config.MONEY_RETRY_SETTLE_S, started + config.MONEY_RETRY_TIMEOUT_S
    best, best_score = None, -1.0
    while not box.closed and not session.closed.is_set():
        left = deadline - time.monotonic()
        if left <= 0:
            break
        frame = await box.take(min(0.5, left))
        if frame is None or box.taken_at < settle_end:
            continue  # chưa có khung, hoặc khung NHẬN lúc người dùng còn đang chỉnh tay (không tính lúc xử lý)
        score = await asyncio.to_thread(read_money.blur_score, frame)
        if score is None:
            continue
        if score > best_score:
            best, best_score = frame, score
        if score >= config.MONEY_BLUR_HINT:
            break
    if box.closed or session.closed.is_set():
        return
    sentence = read_money.RETRY_FAILED
    if best is not None:
        logger.info("đọc tiền đọc lại: dùng khung nét %.0f (ngưỡng %.0f) sau %.1fs", best_score,
                    config.MONEY_BLUR_HINT, time.monotonic() - started)
        said, _ = await read_money_frame(best, config.MONEY_RETRY_PROB)
        if said in read_money.LABELS:
            sentence = said
    else:
        logger.info("đọc tiền đọc lại: không có khung nào trong %.1fs", config.MONEY_RETRY_TIMEOUT_S)
    if box.closed or session.closed.is_set():
        return
    await speak_ws(ws, [sentence])
    if box.closed or session.closed.is_set():
        return
    await speak_ws(ws, [EXIT_MONEY])
    await ws.send_text(protocol.end())


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
        if mode == "money_retry":
            await _money_retry(ws, box, session)
            return
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
                       "capture": action is not None and action.kind == "capture",
                       protocol.DEBUG_JPEG: frame})
            if action is None:
                continue
            if action.kind == "cue":
                await ws.send_text(protocol.cue(action.cue))
            else:
                logger.info("OCR live: khung đạt sau %.1fs, chụp UXGA", time.monotonic() - started)
                capture_sent, capture_deadline = True, time.monotonic() + 3.0
                await ws.send_text(protocol.capture("uxga"))

        image = pick_image(hi_res, session.params.get("fallback_jpeg"), best_vga)
        if box.closed or session.closed.is_set():
            return
        if image is None:  # hết trần mà không có ảnh nào: đừng im lặng như bị treo
            await speak_ws(ws, [EXIT_READ])
            return
        loop = asyncio.get_running_loop()
        await speak_ws(ws, speech.sync_iter(spoken(image, mode, session.device), loop))
        if box.closed or session.closed.is_set():
            return
        await speak_ws(ws, [EXIT_READ])
        await ws.send_text(protocol.end())
    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("OCR live: kính ngắt kết nối (%r), huỷ", exc)
    finally:
        receiver.cancel()
        sessions.release(session)
