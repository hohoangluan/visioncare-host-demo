"""Final Router (§8): intent cuối -> 4 làn A–D.

Phục vụ cả `/v2/turn` lẫn `WS /v2/session` và `/process` (firmware cũ, Task 12).
Với `/process` thì `ctx.single_shot = True`: không có WebSocket nào để mở nên làn B
đọc thẳng ảnh buffer và làn C chỉ gửi lệnh điện thoại + câu xác nhận.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

import config
from lanes import general, ocr_live, phone
from live.session import sessions
from models import search
from pipeline import image_quality, pending_action, speech
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
        # `/process` (firmware cũ): một lần HTTP, không WS -> làn B/C không mở live.
        self.single_shot = False
        self.gen: int | None = None  # thế hệ lượt (pending_action.begin_turn)
        self.spec_answer: Speculation | None = None
        # (intent, text) -> task trích tham số chạy song song với Clef.
        self.spec_params: tuple[tuple, asyncio.Task] | None = None

    async def image(self):
        if self.single_shot:  # ảnh đi cùng request, tới rồi hoặc không bao giờ tới: khỏi chờ
            return image_buffer.get(self.device, self.turn_id)
        return await asyncio.to_thread(
            image_buffer.wait, self.device, self.turn_id, config.IMAGE_WAIT_S,
        )

    def cancel_speculation(self, keep_answer: bool = False, keep_params: bool = False) -> None:
        if self.spec_answer is not None and not keep_answer:
            self.spec_answer.cancel()
        if self.spec_params is not None and not keep_params:
            self.spec_params[1].cancel()

FILLER_SEARCHING = "Để tôi tra cứu."

# Chỉ gặp ở `/process` (firmware cũ, không có WS): bật cảnh báo vật cản liên tục
# cần kênh realtime nên nói thẳng là chưa làm được, thay vì nói "đã bật" rồi im.
NO_LIVE_MESSAGE = "Kính bản này chưa hỗ trợ cảnh báo liên tục."
STATIC_SPEECH: tuple[str, ...] = (NO_LIVE_MESSAGE,)


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

    if d.intent == "chat" and d.needs_web:
        # Câu chạy trước (speculation) sinh khi chưa có kết quả tra -> không dùng.
        if ctx.spec_answer is not None:
            ctx.spec_answer.cancel()
            ctx.spec_answer = None
        return Reply(speech=_sync(ctx, _web_answer(d, text)), intent=d.intent, lane="A")

    spec = ctx.spec_answer
    if spec is not None and spec.key == (d.intent, text):
        ctx.spec_answer = None
        logger.info("làn A: dùng câu trả lời đã sinh song song với Clef")
        return Reply(speech=_sync(ctx, spec.replay()), intent=d.intent, lane="A")
    if spec is not None:
        spec.cancel()
        ctx.spec_answer = None
    return Reply(speech=_sync(ctx, general.answer(d.intent, text, image)), intent=d.intent, lane="A")


async def _web_answer(d: Decision, text: str) -> AsyncIterator[str]:
    """Câu cần tra web: câu đệm phát NGAY, tra (trần `SEARCH_TIMEOUT_S`) chạy dưới câu đệm.

    Không khoá hoặc tra hỏng -> `search_failed`: Gemma nói thẳng là chưa tra được.
    """
    if not search.available():
        results = None
    else:
        task = asyncio.ensure_future(search.search(text))
        try:
            if config.SEARCH_FILLER:
                yield FILLER_SEARCHING + "\n"
            results = await task
        finally:
            task.cancel()
    async for piece in general.answer(d.intent, text, None, results, search_failed=results is None):
        yield piece


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

    mode = d.ocr_mode if d.ocr_mode in ("summarize", "raw", "specialized") else "read"
    if ctx.single_shot:  # không có WS để hướng dẫn căn khung: đọc thẳng ảnh đã có
        return Reply(speech=_sync(ctx, ocr_live.spoken(entry.jpeg, mode, ctx.device)),
                     intent="ocr", lane="B")
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


def _trusted(d: Decision) -> bool:
    """Chỉ nhãn Gemma đủ tin cậy mới được chạy hành động có tác dụng phụ.

    Clef/không rõ nguồn/luật từ khoá -> hỏi lại. `backend` lạ KHÔNG mặc định là gemma.
    """
    return d.backend == "gemma" and d.confidence >= config.ACTION_MIN_CONFIDENCE


def _ask_back(ctx: TurnContext, d: Decision, params: dict, lane: str) -> Reply:
    phone.set_pending_confirm(ctx.device, d.intent, params)
    logger.info("làn D %s: hỏi lại (backend=%r conf=%.2f)", d.intent, d.backend, d.confidence)
    return Reply(speech=[phone.ask_confirm(d.intent, params)], intent=d.intent, lane=lane)


def _fire_after_readback(ctx: TurnContext, intent: str, text: str, params: dict,
                         deliver=None) -> str | None:
    """Đọc lại xong mới chạy; lượt mới / kính ngắt trong lúc đó sẽ huỷ (pending_action)."""
    line = phone.readback(intent, params)
    delay = pending_action.readback_delay(line) + config.ACTION_TTS_LEAD_S
    action = pending_action.schedule(
        ctx.device, delay,
        lambda: phone.run_background(intent, text, params, deliver=deliver), label=intent,
        gen=ctx.gen,
    )
    return line if action is not None else None  # None: lượt đã bị lượt mới thay


async def _lane_c(ctx: TurnContext, d: Decision, text: str, params: dict | None = None) -> Reply:
    if ctx.single_shot and d.intent == "alert_on":
        return Reply(speech=[NO_LIVE_MESSAGE], intent=d.intent, lane="C")
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
        if not _trusted(d):
            return _ask_back(ctx, d, params, "C+D")
        if ctx.single_shot:
            # Không WS: chỉ gửi lệnh mở chỉ đường tới điện thoại (kết quả không đọc
            # lại được), nói câu xác nhận.
            line = _fire_after_readback(ctx, "nav_start", text, params)
            return Reply(speech=[line] if line else [], intent=d.intent, lane="C+D")
        session = ctx.prewarmer.session("nav")
        # Cảnh báo làn C bật ngay; mở lộ trình (làn D) chờ đọc lại điểm đến xong,
        # kết quả đọc qua WS của làn C.
        line = _fire_after_readback(ctx, "nav_start", text, params, deliver=session.outbox.put)
        if line is None:
            return Reply(intent=d.intent, lane="C+D")
        return Reply(cues=["nav_alert_on"], speech=[line], live="nav", live_token=session.token,
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
    if intent not in phone.CONFIRM_INTENTS:
        # music_stop / music_volume: không nguy hiểm, chạy ngay như cũ.
        return Reply(speech=phone.speech(intent, text, params), intent=intent, lane="D")
    if not _trusted(d):
        return _ask_back(ctx, d, params, "D")
    line = _fire_after_readback(ctx, intent, text, params)
    if line is None:
        return Reply(intent=intent, lane="D")
    return Reply(speech=[line], intent=intent, lane="D")


async def route(ctx: TurnContext, d: Decision, text: str) -> Reply:
    if d.source == "no_speech":
        return Reply(cues=["no_speech"])

    # Lượt trước hỏi "... phải không?": câu này là có/không.
    confirm = phone.take_pending_confirm(ctx.device)
    if confirm is not None:
        intent, params = confirm
        if phone.is_yes(text):
            ctx.cancel_speculation()
            d = Decision(intent, source="confirmed", backend="gemma", confidence=1.0)
            return await (_lane_c if intent == "nav_start" else _lane_d)(ctx, d, text, params)
        if phone.is_no(text):
            ctx.cancel_speculation()
            return Reply(speech=["Đã huỷ."], intent=intent, lane="D")
        # Câu khác: bỏ lệnh chờ, xử lý như lượt mới.

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
        # Điền chỗ trống bằng câu nói tự do -> không tin cậy, ép hỏi xác nhận.
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
