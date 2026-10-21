"""Một lượt `/v2/turn`: audio chunked -> partial -> đoán sớm/prewarm -> final -> router.

Đường chờ sau khi nhả nút chỉ còn:
    giải lại phần đuôi (0 ms nếu partial cuối đã thấy hết audio)
  + Clef cuối (0 ms nếu đã chạy trên partial trùng bản ghi cuối)
  + phần của làn (đã được prewarm / chạy song song với Clef).

VAD (Task 2b, pipeline/vad.py): khi VAD báo hết câu mà nút còn giữ thì "chốt sớm" —
giải đoạn có tiếng + intent + chạy trước làn A/D ngay lúc đó; nhả nút mà không có
tiếng mới thì dùng thẳng kết quả (bỏ final_stt + intent khỏi đường chờ). Cả lượt
không có tiếng -> `no_speech` ngay, không giải, không gọi Gemma.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import config
from lanes import general, phone
from pipeline import device_ctx, final_router, metrics, pending_action, vad
from pipeline.final_router import Speculation, TurnContext
from pipeline.intent_early import Decision
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
    source: str = ""  # nguồn quyết định ý định (khung debug `trace`)
    confidence: float | None = None  # None: không có bộ phân loại chấm (luật từ khoá / không tiếng)


def _button_stop(device_state: dict) -> bool:
    """Nhạc đang phát / ĐT đang dẫn đường: một lần bấm nút KHÔNG kèm lời nói nghĩa là "dừng"."""
    return bool(device_state.get("music_playing") or device_state.get("navigating"))


def _bypass(device: str, device_state: dict) -> Reply | None:
    """Bấm nút không nói gì khi đang phát nhạc / dẫn đường -> dừng (giữ hành vi cũ cho nút bấm).

    Chỉ áp cho lượt KHÔNG có lời (no_speech). Lượt có lời đi qua bộ phân loại như thường — nó đã biết
    `music_playing`/`navigating` — nên "tăng âm lượng" lúc đang nghe nhạc là music_volume chứ không phải
    dừng nhạc, và câu hỏi chat lúc đang dẫn đường không tắt chỉ đường. Dẫn đường (điện thoại) và cảnh báo
    vật cản (live nav) là hai chế độ độc lập: dừng chỉ đường KHÔNG đóng live nav, muốn tắt thì nói "tắt cảnh báo".
    """
    from lanes.phone import speech

    if device_state.get("music_playing"):
        return Reply(speech=speech("music_stop", "", {}), intent="music_stop", lane="D")
    if device_state.get("navigating"):
        return Reply(speech=speech("nav_stop", "", {}), intent="nav_stop", lane="D")
    return None


@dataclass
class _EarlyFinal:
    """Kết quả chốt sớm trên đoạn có tiếng `key` (xem transcriber.span_key())."""
    task: asyncio.Task | None = None
    key: object = None
    text: str = ""
    decision: Decision | None = None


async def _early_final(ctx: TurnContext, transcriber: StreamingTranscriber, early: EarlyIntent,
                       ef: _EarlyFinal) -> None:
    text = await asyncio.to_thread(transcriber.final)
    key = transcriber.decoded_key
    ef.key, ef.text, ef.decision = None, text, None
    if not text.strip():
        return
    _speculate(ctx, early, text)
    decision = await early.decide(text)
    if transcriber.span_key() != key:  # tiếng mới chen vào lúc đang chốt: bỏ
        _discard_speculation(ctx)
        return
    ef.key, ef.decision = key, decision


def _discard_speculation(ctx: TurnContext) -> None:
    ctx.cancel_speculation()
    ctx.spec_answer = ctx.spec_params = None


async def _partial_loop(transcriber: StreamingTranscriber, early: EarlyIntent, stop: asyncio.Event,
                        ctx: TurnContext | None = None, ef: _EarlyFinal | None = None) -> None:
    text = ""
    loop = asyncio.get_running_loop()
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
        if (ef is not None and ctx is not None and transcriber.speech_ended
                and (ef.task is None or ef.task.done()) and ef.key != transcriber.span_key()):
            ef.task = loop.create_task(_early_final(ctx, transcriber, early, ef))


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
    device_state: dict, gen: int | None = None, on_cancel: Callable[[], None] | None = None,
    transport: str = "post", glasses: dict | None = None,
    single_shot: bool = False,
) -> TurnResult:
    """`glasses`: dict mốc kính (t_press_ms/t_release_ms) do phiên điền; đọc lúc ghi metrics."""
    device_ctx.turn.set(turn_id)  # mọi log của lượt (kể cả thread nền copy context) mang turn id
    started = time.monotonic()
    loop = asyncio.get_running_loop()

    button_stop = _button_stop(device_state)

    prewarmer = Prewarmer(device, turn_id)
    segmenter = vad.Segmenter() if vad.available() else None
    transcriber = StreamingTranscriber(content_type, segmenter)
    early = EarlyIntent(device_state, on_guess=prewarmer.on_guess)
    stop = asyncio.Event()
    ctx = TurnContext(device, turn_id, prewarmer, loop)
    # `/process` (firmware cũ): toàn bộ lượt trong một request HTTP, không mở live.
    ctx.single_shot = single_shot
    ctx.device_state = device_state or {}
    prewarmer.live_ok = not single_shot
    ctx.gen = pending_action.generation(device) if gen is None else gen
    ef = _EarlyFinal() if segmenter is not None and config.VAD_EARLY_FINAL else None
    partials = loop.create_task(_partial_loop(transcriber, early, stop, ctx, ef))

    try:
        async for chunk in body:
            transcriber.feed(chunk)
        released = time.monotonic()
        stop.set()
        await partials

        if ef is not None and ef.task is not None:
            try:
                await ef.task  # chốt sớm đang dở thì chờ nốt, rẻ hơn làm lại
            except Exception:
                logger.exception("v2 turn %s: chốt sớm lỗi, làm lại", turn_id)
                ef.key = None

        if not transcriber.has_speech:
            text, decision = "", Decision("", source="no_speech")  # không tiếng: khỏi giải, khỏi Gemma
            t_final = t_intent = time.monotonic()
        elif ef is not None and ef.decision is not None and ef.key == transcriber.span_key():
            text, decision = ef.text, ef.decision  # không có tiếng mới từ lúc chốt sớm
            t_final = t_intent = time.monotonic()
            logger.info("v2 turn %s: dùng bản chốt sớm", turn_id)
        else:
            if ef is not None:
                _discard_speculation(ctx)
            text = await asyncio.to_thread(transcriber.final)
            t_final = time.monotonic()
            _speculate(ctx, early, text)
            decision = await early.decide(text)
            t_intent = time.monotonic()

        reply = None
        if button_stop and (decision.source == "no_speech" or not text.strip()):
            reply = _bypass(device, device_state)  # chỉ bấm nút, không nói: dừng nhạc/chỉ đường
            if reply is not None:
                decision = Decision(reply.intent, source="bypass")
                logger.info("v2 turn %s: bấm nút không lời -> %s", turn_id, reply.intent)
        if reply is None:
            reply = await final_router.route(ctx, decision, text)
        t_route = time.monotonic()
        ctx.cancel_speculation()  # phần chạy trước mà router không dùng tới
    except BaseException as exc:
        if on_cancel is not None and isinstance(exc, asyncio.CancelledError):
            on_cancel()  # phiên WS biết lượt này bị huỷ giữa chừng (lượt mới/cancel/ngắt)
        stop.set()
        partials.cancel()
        if ef is not None and ef.task is not None:
            ef.task.cancel()
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
    metrics.record_turn({
        "device": device, "turn": turn_id, "transport": transport, "intent": reply.intent,
        "lane": reply.lane, "source": decision.source, "confidence": decision.confidence,
        **{k: round(v, 4) for k, v in timings.items()}, "glasses": glasses,
    })
    confidence = decision.confidence if decision.backend and decision.confidence_known else None
    return TurnResult(reply, text, released, timings, decision.source, confidence)
