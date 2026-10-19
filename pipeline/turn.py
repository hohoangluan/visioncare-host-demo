"""Một lượt `/v2/turn`: audio chunked -> partial -> đoán sớm/prewarm -> final -> router.

Đường chờ sau khi nhả nút chỉ còn:
    giải lại phần đuôi (0 ms nếu partial cuối đã thấy hết audio)
  + Clef cuối (0 ms nếu đã chạy trên partial trùng bản ghi cuối)
  + phần của làn (đã được prewarm / chạy song song với Clef).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import config
from lanes import general, phone
from pipeline import final_router
from pipeline.final_router import Speculation, TurnContext
from pipeline.image_buffer import image_buffer
from pipeline.intent_early import EarlyIntent, LANE, keyword_rule
from pipeline.prewarm import Prewarmer
from pipeline.reply import Reply
from pipeline.stt_stream import StreamingTranscriber

logger = logging.getLogger("blind_assist")


@dataclass
class TurnResult:
    reply: Reply
    transcript: str = ""
    released_at: float = 0.0  # mốc nhả nút (body đóng)
    timings: dict = field(default_factory=dict)


def _bypass(device_state: dict) -> Reply | None:
    """Đang phát nhạc / đang chỉ đường mà bấm nút -> dừng (giữ hành vi cũ)."""
    from lanes.phone import speech

    if device_state.get("music_playing"):
        return Reply(speech=speech("music_stop", "", {}), intent="music_stop", lane="D")
    if device_state.get("navigating"):
        return Reply(speech=speech("nav_stop", "", {}), intent="nav_stop", lane="C+D")
    return None


async def _partial_loop(transcriber: StreamingTranscriber, early: EarlyIntent, stop: asyncio.Event) -> None:
    text = ""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), config.STT_PARTIAL_INTERVAL_S)
            return
        except asyncio.TimeoutError:
            pass
        if transcriber.has_new_audio():
            text = await asyncio.to_thread(transcriber.partial)
        if text:
            early.on_partial(text)


def _speculate(ctx: TurnContext, early: EarlyIntent, text: str) -> None:
    """Sau bản ghi cuối, trong lúc chờ Clef: chạy trước phần KHÔNG có tác dụng phụ."""
    guess = early.guess or keyword_rule(text)
    if not config.SPECULATIVE_FINAL or guess is None:
        return
    intent, mode = guess
    loop = asyncio.get_running_loop()
    if LANE.get(intent) == "A" and not (intent == "ocr" and mode == "reread"):
        image = None
        if intent in general.VISION_INTENTS:
            entry = image_buffer.get(ctx.device, ctx.turn_id)
            if entry is None or not entry.prepared():
                return
            image = entry.llm_jpeg()  # đã thu nhỏ sẵn lúc ảnh vào, không chặn loop
        ctx.spec_answer = Speculation((intent, text), general.answer(intent, text, image))
    elif intent in phone.SLOT:
        ctx.spec_params = ((intent, text), loop.create_task(phone.extract(intent, text)))


async def run(
    device: str, turn_id: str, content_type: str | None, body: AsyncIterator[bytes],
    device_state: dict,
) -> TurnResult:
    started = time.monotonic()
    loop = asyncio.get_running_loop()

    bypass = _bypass(device_state)
    if bypass is not None:
        async for _ in body:  # đọc hết body kính đang gửi rồi mới trả lời
            pass
        logger.info("v2 turn %s: bypass %s", turn_id, bypass.intent)
        return TurnResult(bypass, released_at=time.monotonic())

    prewarmer = Prewarmer(device, turn_id)
    transcriber = StreamingTranscriber(content_type)
    early = EarlyIntent(device_state, on_guess=prewarmer.on_guess)
    stop = asyncio.Event()
    partials = loop.create_task(_partial_loop(transcriber, early, stop))
    ctx = TurnContext(device, turn_id, prewarmer, loop)

    try:
        async for chunk in body:
            transcriber.feed(chunk)
        released = time.monotonic()
        stop.set()
        await partials

        text = await asyncio.to_thread(transcriber.final)
        t_final = time.monotonic()

        _speculate(ctx, early, text)
        decision = await early.decide(text)
        t_intent = time.monotonic()

        reply = await final_router.route(ctx, decision, text)
        t_route = time.monotonic()
        ctx.cancel_speculation()  # phần chạy trước mà router không dùng tới
    except BaseException:
        stop.set()
        partials.cancel()
        ctx.cancel_speculation()
        prewarmer.discard()
        raise
    finally:
        early.cancel()

    prewarmer.discard(keep=reply.live_token)
    reply.intent = reply.intent or decision.intent
    timings = {
        "audio_s": transcriber.seconds,
        "upload_s": released - started,
        "final_stt_s": t_final - released,
        "intent_s": t_intent - t_final,
        "route_s": t_route - t_intent,
        "release_to_reply_s": t_route - released,
    }
    logger.info(
        "v2 turn %s | nghe='%s' -> %s/%s (%s) | audio=%.2fs upload=%.2fs final_stt=%.3fs "
        "intent=%.3fs route=%.3fs nhả->quyết=%.3fs cues=%s live=%s",
        turn_id, text, reply.intent, reply.lane, decision.source, timings["audio_s"],
        # upload ~ audio: body tới theo từng mảnh (đoán sớm/prewarm có tác dụng);
        # upload ~ 0 với audio dài: proxy (Cloudflare) gom đủ body mới chuyển.
        timings["upload_s"], timings["final_stt_s"], timings["intent_s"], timings["route_s"],
        timings["release_to_reply_s"], reply.cues, reply.live,
    )
    return TurnResult(reply, text, released, timings)
