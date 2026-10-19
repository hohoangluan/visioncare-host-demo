"""Làn C — Navigation Realtime (§11): khung QVGA -> hazard model -> luật mức -> JSON.

Đường nóng nhất của hệ thống (mục tiêu khung -> bíp <= 300 ms), nên:
- chỉ xử lý khung MỚI NHẤT (`_Mailbox`), khung cũ bị đè chứ không xếp hàng;
- server chỉ gửi mã mức + hướng; kính phát âm từ flash, không qua TTS.

Câu nói của làn D (kết quả mở lộ trình trên điện thoại) đẩy vào
`session.outbox` và được đọc qua cùng WebSocket, không chặn vòng cảnh báo.
"""

import asyncio
import logging
import queue
import time

import cv2
import numpy as np
from starlette.websockets import WebSocket, WebSocketDisconnect

from lanes.ocr_live import _Mailbox, receive_frames, speak_ws
from live import hazard, protocol
from live.session import LiveSession, sessions

logger = logging.getLogger("blind_assist")


def _decode(jpeg: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def process_frame(det, tracker: hazard.HazardTracker, jpeg: bytes) -> hazard.Hazard:
    bgr = _decode(jpeg)
    if bgr is None:
        return hazard.Hazard(0)
    return tracker.assess(det.detect(bgr))


async def _speak_outbox(ws: WebSocket, session: LiveSession) -> None:
    while not session.closed.is_set():
        try:
            text = session.outbox.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.1)
            continue
        await speak_ws(ws, [text])


async def run(ws: WebSocket, session: LiveSession) -> None:
    box = _Mailbox()
    receiver = asyncio.create_task(receive_frames(ws, box, session))
    talker = asyncio.create_task(_speak_outbox(ws, session))
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
