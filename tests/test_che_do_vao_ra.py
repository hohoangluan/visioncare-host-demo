"""Báo vào/ra chế độ cho người chỉ nghe: lời báo cực ngắn, KHÔNG làm trễ đường đi chính.

- DeviceSession: OCR live thay nav live -> "Tạm tắt cảnh báo."; dựng lại nav -> "Bật lại cảnh báo."
  (kể cả sau cúp máy); "tắt cảnh báo" lúc đang tạm dừng thì không bao giờ tự bật lại.
- ocr_live.run: đọc xong / không thấy chữ / hết trần không ảnh -> "Thoát đọc chữ." SAU nội dung;
  đọc tiền lại xong -> "Thoát đọc tiền."; huỷ hoặc ngắt kết nối -> im.
"""

import asyncio
import io
import json
from types import SimpleNamespace

from PIL import Image

import config
from lanes import nav_live, ocr_live
from live import call_bridge, device_session
from live.device_session import DeviceSession
from live.session import LiveSession, sessions
from live.ws_adapter import LiveSocket
from pipeline import final_router, phrases, speech
from pipeline.intent_early import Decision
from pipeline.reply import Reply

DEV = "dev-mode"
PAUSED, RESUMED = "Tạm tắt cảnh báo.", "Bật lại cảnh báo."
EXIT_READ, EXIT_MONEY = "Thoát đọc chữ.", "Thoát đọc tiền."


# ── DeviceSession: tạm dừng / dựng lại cảnh báo ──────────────────────────────────────────────
class _World:
    """Phiên thiết bị giả: runner nav/ocr giả sống tới khi bị đóng, `said` ghi mọi câu nói của phiên."""

    def __init__(self, monkeypatch):
        self.said: list[str] = []
        self.ran: list[str] = []
        self.ocr_done = asyncio.Event()
        self.calls = SimpleNamespace(call=None, by_device=lambda device: self.calls.call)

        async def adpcm_stream(text):
            self.said.append("".join(text))
            yield b"\x00"

        async def nav_run(sock, live):
            self.ran.append("nav")
            try:
                while not live.closed.is_set():
                    await asyncio.sleep(0.005)
            finally:
                sessions.release(live)

        async def ocr_run(sock, live):
            self.ran.append("ocr")
            try:
                while not live.closed.is_set() and not self.ocr_done.is_set():
                    await asyncio.sleep(0.005)
            finally:
                sessions.release(live)

        class Ws:
            async def send_text(self, data):
                pass

            async def send_bytes(self, data):
                pass

        monkeypatch.setattr(speech, "adpcm_stream", adpcm_stream)
        monkeypatch.setattr(nav_live, "run", nav_run)
        monkeypatch.setattr(ocr_live, "run", ocr_run)
        monkeypatch.setattr(device_session, "calls", self.calls)
        self.session = DeviceSession(Ws(), None)
        self.session.device = DEV
        monkeypatch.setitem(device_session._registry, DEV, self.session)

    def start_nav(self):
        self.session._launch_live(sessions.claim(sessions.create(DEV, "nav").token))

    async def start_ocr(self):
        token = sessions.create(DEV, "ocr", {"mode": "read"}).token
        await self.session._start_live(Reply(live="ocr", live_token=token))

    async def settle(self, seconds=0.15):
        await asyncio.sleep(seconds)

    async def finish_ocr(self):
        self.ocr_done.set()
        await self.settle()

    async def close(self):
        await self.session._cancel_work("test")
        await self.settle(0.02)


def _run(monkeypatch, scenario):
    async def go():
        world = _World(monkeypatch)
        try:
            await scenario(world)
        finally:
            await world.close()
            sessions.clear()

    asyncio.run(go())


def test_ocr_replacing_nav_says_pause_once_then_resume(monkeypatch):
    async def scenario(w):
        w.start_nav()
        await w.settle()
        assert w.said == []  # bật nav bằng cue của lượt, lời báo mới không nói gì thêm
        await w.start_ocr()
        await w.settle()
        assert w.said == [PAUSED] and w.session._nav_suspended
        await w.finish_ocr()
        assert w.said == [PAUSED, RESUMED]
        assert w.ran == ["nav", "ocr", "nav"] and not w.session._nav_suspended

    _run(monkeypatch, scenario)


def test_resume_after_hangup_says_resume(monkeypatch):
    async def scenario(w):
        w.start_nav()
        await w.settle()
        call = SimpleNamespace(state=call_bridge.ACTIVE, session=w.session, emergency=False)
        w.calls.call = call
        await w.session._on_call_state(call)  # đang gọi: nav tạm dừng, KHÔNG nói gì (đang trong cuộc gọi)
        await w.settle()
        assert w.said == [] and w.session._nav_suspended
        call.state = call_bridge.ENDED
        await w.session._on_call_state(call)
        await w.settle()
        assert w.said == [RESUMED] and w.ran == ["nav", "nav"]

    _run(monkeypatch, scenario)


def test_ocr_cut_by_call_defers_resume_to_hangup(monkeypatch):
    async def scenario(w):
        w.start_nav()
        await w.settle()
        await w.start_ocr()
        await w.settle()
        call = SimpleNamespace(state=call_bridge.ACTIVE, session=w.session, emergency=False)
        w.calls.call = call
        await w.session._on_call_state(call)  # cuộc gọi nhấc máy: huỷ OCR live; `_in_call()` chặn dựng lại
        await w.settle()
        assert w.said == [PAUSED]  # đang gọi: chưa dựng lại, chưa báo
        call.state = call_bridge.ENDED
        await w.session._on_call_state(call)
        await w.settle()
        assert w.said == [PAUSED, RESUMED]

    _run(monkeypatch, scenario)


def test_alert_off_while_paused_never_turns_alert_back_on(monkeypatch):
    async def scenario(w):
        w.start_nav()
        await w.settle()
        await w.start_ocr()
        await w.settle()
        assert w.session._nav_suspended
        ctx = SimpleNamespace(device=DEV, single_shot=False)
        reply = await final_router._lane_c(ctx, Decision("alert_off"), "tắt cảnh báo")
        assert reply.cues == ["nav_alert_off"]
        assert not w.session._nav_suspended
        await w.finish_ocr()
        assert w.said == [PAUSED]  # không "Bật lại cảnh báo."
        assert w.ran == ["nav", "ocr"] and sessions.active(DEV) is None

    _run(monkeypatch, scenario)


def test_alert_off_with_no_session_is_harmless(monkeypatch):
    monkeypatch.setattr(device_session, "_registry", {})
    ctx = SimpleNamespace(device="khong-co-phien", single_shot=False)
    reply = asyncio.run(final_router._lane_c(ctx, Decision("alert_off"), "tắt cảnh báo"))
    assert reply.cues == ["nav_alert_off"]


def test_ocr_without_prior_nav_says_nothing_about_alert(monkeypatch):
    async def scenario(w):
        await w.start_ocr()
        await w.settle()
        await w.finish_ocr()
        assert w.said == [] and w.ran == ["ocr"]

    _run(monkeypatch, scenario)


def test_cancel_by_new_turn_still_resumes_with_one_announcement(monkeypatch):
    """Lượt mới huỷ OCR giữa chừng: nav vẫn dựng lại (hành vi cũ) và đúng MỘT lời báo mỗi chiều."""
    async def scenario(w):
        w.start_nav()
        await w.settle()
        await w.start_ocr()
        await w.settle()
        await w.session._cancel_work("lượt mới", keep_nav=True)
        await w.settle()
        assert w.said == [PAUSED, RESUMED] and w.ran == ["nav", "ocr", "nav"]

    _run(monkeypatch, scenario)


def test_status_phrases_do_not_delay_main_path(monkeypatch):
    """`_start_live` trả về ngay dù TTS lời báo chậm: lời báo chạy ở task riêng."""
    async def scenario(w):
        gate = asyncio.Event()

        async def slow(text):
            await gate.wait()
            yield b"\x00"

        monkeypatch.setattr(speech, "adpcm_stream", slow)
        w.start_nav()
        await w.settle()
        await asyncio.wait_for(w.start_ocr(), 0.5)
        assert w.session._live_session is not None and w.session._live_session.mode == "ocr"
        gate.set()

    _run(monkeypatch, scenario)


# ── ocr_live.run: báo thoát ──────────────────────────────────────────────────────────────────
def _wide_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1000, 40), (200, 200, 200)).save(out, format="JPEG")
    return out.getvalue()


class _Box:
    def __init__(self, monkeypatch, mode="read", content=("Nội dung."), fallback=None):
        self.events: list[str] = []
        self.texts: list[dict] = []
        self.hold: asyncio.Event | None = None
        self.on_speak = None

        async def send_text(s):
            self.texts.append(json.loads(s))
            if self.texts[-1]["t"] == "end":
                self.events.append("end")

        async def send_bytes(b):
            pass

        async def speak(ws, text):
            said = "".join(text)
            if self.hold is not None:
                await self.hold.wait()
            self.events.append(said)
            if self.on_speak is not None:
                self.on_speak()

        monkeypatch.setattr(ocr_live, "speak_ws", speak)
        monkeypatch.setattr(ocr_live.speech, "sync_iter", lambda agen, loop: agen)
        monkeypatch.setattr(ocr_live, "spoken", lambda jpeg, mode, device: list(content))
        monkeypatch.setattr(config, "LIVE_MAX_FPS", 0)
        params = {"mode": mode}
        if fallback is not None:
            params["fallback_jpeg"] = fallback
        self.ws = LiveSocket(send_text, send_bytes)
        self.session = LiveSession("tok", "dev-ocr", "ocr", params)


def _frames(box, *frames):
    for frame in frames:
        box.ws.feed_frame(frame)


def test_exit_phrase_comes_after_content(monkeypatch):
    box = _Box(monkeypatch)
    _frames(box, _wide_jpeg())
    asyncio.run(ocr_live.run(box.ws, box.session))
    assert box.events == ["Nội dung.", EXIT_READ, "end"]


def test_no_text_found_still_announces_exit(monkeypatch):
    box = _Box(monkeypatch, content=[ocr_live._NO_TEXT])
    _frames(box, _wide_jpeg())
    asyncio.run(ocr_live.run(box.ws, box.session))
    assert box.events == [ocr_live._NO_TEXT, EXIT_READ, "end"]


def test_alignment_ceiling_with_no_image_announces_exit(monkeypatch):
    """Hết trần căn khung, không có ảnh nào đọc được -> trước đây im lặng; giờ báo thoát."""
    box = _Box(monkeypatch)
    monkeypatch.setattr(ocr_live, "pick_image", lambda *a: None)
    _frames(box, _wide_jpeg())
    asyncio.run(ocr_live.run(box.ws, box.session))
    assert box.events == [EXIT_READ]


def test_cancel_during_content_is_silent(monkeypatch):
    box = _Box(monkeypatch)
    box.hold = asyncio.Event()
    _frames(box, _wide_jpeg())

    async def go():
        task = asyncio.create_task(ocr_live.run(box.ws, box.session))
        await asyncio.sleep(0.2)
        task.cancel()  # lượt mới / _stop_live huỷ task live
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    assert box.events == []


def test_session_closed_after_content_skips_exit(monkeypatch):
    box = _Box(monkeypatch)
    box.on_speak = box.session.closed.set  # bị đóng đúng lúc nội dung vừa nói xong
    _frames(box, _wide_jpeg())
    asyncio.run(ocr_live.run(box.ws, box.session))
    assert box.events == ["Nội dung."]


def test_disconnect_before_reading_is_silent(monkeypatch):
    box = _Box(monkeypatch)
    box.ws.feed_disconnect()
    asyncio.run(ocr_live.run(box.ws, box.session))
    assert box.events == []


def test_money_retry_announces_exit_money_after_sentence(monkeypatch):
    from tests.test_money_retry import _drive, _fast, _jpeg, _patch_read

    _fast(monkeypatch)
    box = _Box(monkeypatch, mode="money_retry")
    _patch_read(monkeypatch)
    asyncio.run(_drive(box, [(0.4, _jpeg(True, 192, 144))]))
    assert box.events == ["50 nghìn đồng", EXIT_MONEY, "end"]


def test_money_retry_cancelled_is_silent(monkeypatch):
    from tests.test_money_retry import _fast

    _fast(monkeypatch)
    box = _Box(monkeypatch, mode="money_retry")

    async def go():
        task = asyncio.create_task(ocr_live.run(box.ws, box.session))
        await asyncio.sleep(0.1)
        box.session.closed.set()
        await task

    asyncio.run(go())
    assert box.events == []


# ── câu dựng sẵn ─────────────────────────────────────────────────────────────────────────────
def test_new_phrases_are_prerendered():
    keys = set(phrases.collect())
    from pipeline import tts

    for line in (PAUSED, RESUMED, EXIT_READ, EXIT_MONEY):
        assert tts.phrase_key(line) in keys, line


def test_constants_match_spec():
    assert device_session.NAV_PAUSED == PAUSED and device_session.NAV_RESUMED == RESUMED
    assert ocr_live.EXIT_READ == EXIT_READ and ocr_live.EXIT_MONEY == EXIT_MONEY
