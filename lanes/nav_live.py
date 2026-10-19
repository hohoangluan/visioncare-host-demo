"""Làn C — Navigation Realtime (§11): khung QVGA -> hazard model -> luật mức -> JSON.

Đường nóng nhất của hệ thống (mục tiêu khung -> bíp <= 300 ms), nên:
- chỉ xử lý khung MỚI NHẤT (`_Mailbox`), khung cũ bị đè chứ không xếp hàng;
- server chỉ gửi mã mức + hướng; kính phát âm từ flash, không qua TTS.

Câu nói của làn D (kết quả mở lộ trình trên điện thoại) đẩy vào
`session.outbox` và được đọc qua cùng WebSocket, không chặn vòng cảnh báo.
"""

import asyncio
import contextlib
import logging
import queue
import time

import cv2
import numpy as np
from starlette.websockets import WebSocket, WebSocketDisconnect

from lanes.ocr_live import _Mailbox, receive_frames
from live import hazard, protocol
from live.session import LiveSession, sessions
from pipeline import speech

logger = logging.getLogger("blind_assist")


def _decode(jpeg: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def process_frame(det, tracker: hazard.HazardTracker, jpeg: bytes) -> hazard.Hazard:
    bgr = _decode(jpeg)
    if bgr is None:
        return hazard.Hazard(0)
    return tracker.assess(det.detect(bgr))


HAZARD_QUIET_S = 1.5  # sau hazard mức >= 2, chừng này giây im lặng mới được nói tiếp
_HIGH_LEVEL = 2


class _HazardClock:
    """Lần cuối thấy hazard mức >= 2. Dùng chung vòng cảnh báo và người đọc `outbox`."""

    def __init__(self) -> None:
        self._last_high = -1e9

    def mark(self) -> None:
        self._last_high = time.monotonic()

    def quiet(self) -> bool:
        return time.monotonic() - self._last_high >= HAZARD_QUIET_S


async def _speak_outbox(ws: WebSocket, session: LiveSession, clock: _HazardClock | None = None) -> None:
    """Đọc `session.outbox` qua socket nhưng nhường đường cho cảnh báo vật cản.

    Trên `WS /v2/session` khung hazard và audio trả lời dùng chung một socket (khoá gửi
    chỉ giữ từng khung nên hazard chen được giữa hai khối 0x02). Người khiếm thị đang
    nghe đọc lệnh thì tiếng đó không được che mất "xe máy phía trước": có hazard mức >= 2
    trong HAZARD_QUIET_S thì chưa nói, và đang nói thì dừng ngay, đưa câu về đầu hàng
    (đọc lại cả câu khi yên — thà nghe lại còn hơn nghe cụt).
    """
    clock = clock or _HazardClock()
    retry: str | None = None
    while not session.closed.is_set():
        text = retry
        retry = None
        if text is None:
            try:
                text = session.outbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
        if not clock.quiet():
            retry = text
            await asyncio.sleep(0.05)
            continue
        # Trên `/v2/session`: một kênh audio có thứ tự — chờ câu trả lời/kết quả đang phát xong (khoá FIFO),
        # rồi nói trọn câu. Khung JSON hazard không qua khoá nên vẫn tới ngay.
        async with getattr(ws, "audio_lock", None) or contextlib.nullcontext():
            if not clock.quiet():  # trong lúc chờ khoá có hazard mức >= 2
                retry = text
                continue
            async with contextlib.aclosing(speech.adpcm_stream([text])) as stream:
                async for chunk in stream:
                    if not clock.quiet():
                        retry = text
                        break
                    await ws.send_bytes(protocol.audio(chunk))


async def run(ws: WebSocket, session: LiveSession) -> None:
    box = _Mailbox()
    receiver = asyncio.create_task(receive_frames(ws, box, session))
    clock = _HazardClock()
    talker = asyncio.create_task(_speak_outbox(ws, session, clock))
    det = hazard.detector()
    tracker, anti = hazard.HazardTracker(), hazard.AntiAnnoy()
    frames, total_ms = 0, 0.0
    try:
        await ws.send_text(protocol.cam("qvga", 8, quality=15))
        while not box.closed and not session.closed.is_set():
            frame = await box.take(0.5)
            if frame is None or det is None:
                continue
            started = time.perf_counter()
            result = await asyncio.to_thread(process_frame, det, tracker, frame)
            if result.level >= _HIGH_LEVEL:
                clock.mark()  # TRƯỚC khi gửi: audio outbox phải dừng ngay, hazard đi trước
            if anti.step(result.level):
                await ws.send_text(protocol.hazard(result.level, result.dir, result.kind))
                logger.info("hazard level=%d dir=%s kind=%s", result.level, result.dir, result.kind)
            frames += 1
            total_ms += (time.perf_counter() - started) * 1000
        if session.closed.is_set() and not box.closed:
            await ws.send_text(protocol.end())
    except (WebSocketDisconnect, RuntimeError) as exc:
        logger.info("Nav live: kính ngắt kết nối (%r)", exc)
    finally:
        receiver.cancel()
        talker.cancel()
        sessions.release(session)
        if frames:
            logger.info("Nav live: %d khung, xử lý trung bình %.1f ms", frames, total_ms / frames)
