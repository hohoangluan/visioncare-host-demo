"""Final Router (§8): intent cuối -> 4 làn A–D.

`pipeline/router.py` vẫn phục vụ `/process` (firmware cũ, đường Gemini); router
này chỉ phục vụ `/v2/turn`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

import config
from lanes import general, ocr_live, phone
from live.session import sessions
from models import search
from pipeline import image_quality, speech
from pipeline.image_buffer import image_buffer
from pipeline.intent_early import Decision
from pipeline.reply import Reply

logger = logging.getLogger("blind_assist")


class Speculation:
    """Một async generator chạy TRƯỚC khi biết có dùng nó hay không.

    Mảnh sinh ra được giữ lại; `replay()` trả lại từ đầu rồi nối tiếp phần đang
    sinh. Không dùng tới thì `cancel()` — chưa mảnh nào rời server.
    """

    def __init__(self, key: tuple, agen: AsyncIterator[str]) -> None:
        self.key = key
        self._items: list = []
        self._event = asyncio.Event()
        self._done = False
        self._error: BaseException | None = None
        self._task = asyncio.get_running_loop().create_task(self._pump(agen))

    async def _pump(self, agen: AsyncIterator[str]) -> None:
        try:
            async for item in agen:
                self._items.append(item)
                self._event.set()
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
        finally:
            self._done = True
            self._event.set()

    async def replay(self) -> AsyncIterator[str]:
        i = 0
        while True:
            if i < len(self._items):
                yield self._items[i]
                i += 1
                continue
            if self._done:
                if self._error is not None and not isinstance(self._error, asyncio.CancelledError):
                    raise self._error
                return
            self._event.clear()
            if i < len(self._items) or self._done:
                continue
            await self._event.wait()

    def cancel(self) -> None:
        self._task.cancel()


class TurnContext:
    def __init__(self, device: str, turn_id: str, prewarmer, loop) -> None:
        self.device, self.turn_id = device, turn_id
        self.prewarmer = prewarmer
        self.loop = loop
        self.spec_answer: Speculation | None = None
        # (intent, text) -> task trích tham số chạy song song với Clef.
        self.spec_params: tuple[tuple, asyncio.Task] | None = None

    async def image(self):
        return await asyncio.to_thread(
            image_buffer.wait, self.device, self.turn_id, config.IMAGE_WAIT_S,
        )

    def cancel_speculation(self, keep_answer: bool = False, keep_params: bool = False) -> None:
        if self.spec_answer is not None and not keep_answer:
            self.spec_answer.cancel()
        if self.spec_params is not None and not keep_params:
            self.spec_params[1].cancel()


def _sync(ctx: TurnContext, agen: AsyncIterator[str]):
    return speech.sync_iter(agen, ctx.loop)


async def _lane_a(ctx: TurnContext, d: Decision, text: str) -> Reply:
    if d.intent == "ocr":  # reread
        last = ocr_live.last_text(ctx.device)
        if not last:
            return Reply(cues=["ocr_nothing_to_reread"], intent="ocr", lane="A")
        return Reply(speech=[last], intent="ocr", lane="A")

    image = None
    if d.intent in general.VISION_INTENTS:
        entry = await ctx.image()
        if entry is None:
            return Reply(cues=["no_image"], intent=d.intent, lane="A")
        reason = await asyncio.to_thread(image_quality.reject_reason, d.intent, entry.jpeg)
        if reason is not None:
            return Reply(speech=[reason], intent=d.intent, lane="A")
        image = await asyncio.to_thread(entry.llm_jpeg)

    results = None
    if d.intent == "chat" and d.needs_web and search.available():
        results = await search.search(text)

    spec = ctx.spec_answer
    if spec is not None and spec.key == (d.intent, text) and results is None:
        ctx.spec_answer = None
        logger.info("làn A: dùng câu trả lời đã sinh song song với Clef")
        return Reply(speech=_sync(ctx, spec.replay()), intent=d.intent, lane="A")
    if spec is not None:
        spec.cancel()
        ctx.spec_answer = None
    return Reply(speech=_sync(ctx, general.answer(d.intent, text, image, results)), intent=d.intent, lane="A")


async def _lane_b(ctx: TurnContext, d: Decision, text: str) -> Reply:
    entry = await ctx.image()
    if d.intent == "find":
        # Chưa có object detector: một lần, Gemma đọc ảnh buffer.
        return await _lane_a(ctx, d, text)
    if entry is None:
        return Reply(cues=["no_image"], intent=d.intent, lane="B")
    if d.intent == "money":
        # Tờ tiền ít chữ, bộ dò chữ không căn khung tốt -> đọc luôn ảnh buffer UXGA.
        return Reply(speech=_sync(ctx, ocr_live.spoken(entry.jpeg, "money", ctx.device)),
                     intent="money", lane="B")

    mode = "summarize" if d.ocr_mode == "summarize" else "read"
    if config.OCR_ACCEPT_BUFFER:
        task = ctx.prewarmer.assess_buffer()
        problem, boxes = await task if task is not None else ("look_around", [])
        logger.info("làn B: ảnh buffer %s (%d hộp chữ)", problem or "ĐẠT -> đọc ngay", len(boxes))
        if problem is None:
            return Reply(speech=_sync(ctx, ocr_live.spoken(entry.jpeg, mode, ctx.device)),
                         intent="ocr", lane="B")
    session = ctx.prewarmer.session("ocr", {"mode": mode, "fallback_jpeg": entry.jpeg})
    return Reply(cues=["ocr_start"], live="ocr", live_token=session.token, intent="ocr", lane="B")


async def _params(ctx: TurnContext, intent: str, text: str) -> dict:
    spec = ctx.spec_params
    if spec is not None and spec[0] == (intent, text) and not spec[1].cancelled():
        ctx.spec_params = None
        try:
            return await spec[1]
        except Exception:  # noqa: BLE001
            pass
    return await phone.extract(intent, text)


async def _lane_c(ctx: TurnContext, d: Decision, text: str, params: dict | None = None) -> Reply:
    if d.intent == "alert_off":
        sessions.close_device(ctx.device, "nav")
        return Reply(cues=["nav_alert_off"], intent=d.intent, lane="C")
    if d.intent == "nav_stop":
        sessions.close_device(ctx.device, "nav")
        return Reply(speech=phone.speech("nav_stop", text, {}), intent=d.intent, lane="C+D")

    if d.intent == "nav_start":
        params = params if params is not None else await _params(ctx, "nav_start", text)
        if not params.get("destination"):
            phone.set_pending(ctx.device, "nav_start")
            return Reply(cues=["ask_destination"], intent=d.intent, lane="D")
        session = ctx.prewarmer.session("nav")
        # Làn D ở nền: kết quả mở lộ trình đọc qua WS của làn C, không chặn cảnh báo.
        phone.run_background("nav_start", text, params, deliver=session.outbox.put)
        return Reply(cues=["nav_alert_on"], live="nav", live_token=session.token,
                     intent=d.intent, lane="C+D")

    session = ctx.prewarmer.session("nav")  # alert_on
    return Reply(cues=["nav_alert_on"], live="nav", live_token=session.token, intent=d.intent, lane="C")


async def _lane_d(ctx: TurnContext, d: Decision, text: str, params: dict | None = None) -> Reply:
    intent = d.intent
    if params is None:
        params = await _params(ctx, intent, text)
    slot = phone.SLOT.get(intent)
    if slot and not params.get(slot) and intent != "music_play":
        # music_play tự hỏi bằng câu riêng (gợi ý ca sĩ), giữ nguyên hành vi cũ.
        phone.set_pending(ctx.device, intent)
        return Reply(cues=[phone.ASK_CUE[intent]], intent=intent, lane="D")
    if intent == "emergency_call":
        phone.run_background(intent, text, params)
        return Reply(cues=["emergency_started"], intent=intent, lane="D")
    return Reply(speech=phone.speech(intent, text, params), intent=intent, lane="D")


async def route(ctx: TurnContext, d: Decision, text: str) -> Reply:
    if d.source == "no_speech":
        return Reply(cues=["no_speech"])
    if not d.intent:
        return Reply(cues=["system_busy"])

    # Lượt trước hỏi "Bạn muốn đi đâu?": câu này chính là câu trả lời.
    pending = phone.take_pending(ctx.device)
    if pending is not None and (d.intent == pending[0] or d.lane == "A"):
        intent, slot = pending
        params = await _params(ctx, intent, text) if d.intent == intent else {}
        params.setdefault(slot, phone._clean(text))
        if not params.get(slot):
            params[slot] = phone._clean(text)
        d = Decision(intent, source=d.source)
        ctx.cancel_speculation(keep_params=True)
        return await (_lane_c if intent == "nav_start" else _lane_d)(ctx, d, text, params)

    lane = d.lane
    ctx.cancel_speculation(keep_answer=lane == "A", keep_params=lane in ("C", "D"))
    if lane == "A":
        return await _lane_a(ctx, d, text)
    if lane == "B":
        return await _lane_b(ctx, d, text)
    if lane == "C":
        return await _lane_c(ctx, d, text)
    return await _lane_d(ctx, d, text)
