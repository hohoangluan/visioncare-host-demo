"""Đọc tiền v2 (2026-10-21): đọc chặt 1 khung, không chắc thì nói hướng dẫn + đọc lại 1 lần từ khung live."""

import asyncio
import io
import json
import math
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import config
from handlers import read_money
from lanes import ocr_live
from live import protocol
from live.session import LiveSession
from live.ws_adapter import LiveSocket
from models import llm
from pipeline import final_router
from pipeline.intent_early import Decision

STILL, BACK, CLOSER = "Giữ yên tay.", "Lùi ra xa một chút, để cả tờ tiền nằm giữa.", "Đưa tờ tiền lại gần hơn một chút."
SHARP, BLURRY = 5000.0, 10.0  # quanh MONEY_BLUR_HINT


def _jpeg(sharp: bool, w=192, h=144) -> bytes:
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (h, w), dtype=np.uint8) if sharp else np.full((h, w), 128, np.uint8)
    out = io.BytesIO()
    Image.fromarray(arr).convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


# ── câu hướng dẫn: 3 nhóm + thứ tự ưu tiên ────────────────────────────────────────────────────
@pytest.mark.parametrize("top,sharp,expected", [
    ([("50 nghìn đồng", 0.9)], BLURRY, STILL),                                   # mờ
    ([("50 nghìn đồng", 0.9)], None, CLOSER),                                    # không đo được độ nét: không đoán là mờ
    ([("50 nghìn đồng", 0.9)], SHARP, CLOSER),                                   # còn lại
    ([("không rõ", 0.8), ("50 nghìn đồng", 0.1)], SHARP, BACK),                  # "không rõ"
    ([("không rõ", 0.8)], SHARP, BACK),                                          # chỉ có top-1
    ([("50 nghìn đồng", 0.6), ("500 nghìn đồng", 0.4)], SHARP, BACK),            # lệch x10
    ([("500 nghìn đồng", 0.6), ("50 nghìn đồng", 0.4)], SHARP, BACK),
    ([("10 nghìn đồng", 0.6), ("100 nghìn đồng", 0.4)], SHARP, BACK),
    ([("200 đồng", 0.6), ("2 nghìn đồng", 0.4)], SHARP, BACK),
    ([("2 nghìn đồng", 0.6), ("200 đồng", 0.4)], SHARP, BACK),
    ([("50 nghìn đồng", 0.6), ("20 nghìn đồng", 0.4)], SHARP, CLOSER),           # hai mệnh giá khác, không x10
    ([("50 nghìn đồng", 0.6), ("5 nghìn đồng", 0.4)], SHARP, BACK),              # 5 nghìn <-> 50 nghìn cũng x10
    ([("50 nghìn đồng", 0.9)], BLURRY, STILL),
    ([("không rõ", 0.8)], BLURRY, STILL),                                        # mờ thắng "không rõ"
    ([("50 nghìn đồng", 0.6), ("500 nghìn đồng", 0.4)], BLURRY, STILL),          # mờ thắng x10
    ([], SHARP, CLOSER),
])
def test_hint(top, sharp, expected):
    assert read_money.hint(top, sharp) == expected


def test_hint_blur_threshold_is_config(monkeypatch):
    monkeypatch.setattr(config, "MONEY_BLUR_HINT", 100.0)
    assert read_money.hint([("50 nghìn đồng", 0.9)], 99.0) == STILL
    assert read_money.hint([("50 nghìn đồng", 0.9)], 100.0) == CLOSER


# ── top-2 từ logprobs ────────────────────────────────────────────────────────────────────────
def _choice(text: str, steps: list[tuple[str, float, list[tuple[str, float]]]]) -> dict:
    """steps: (token, logprob, [(token thay thế, logprob)]) — token ghép lại phải bằng `text` (+ token kết)."""
    return {"message": {"content": text}, "logprobs": {"content": [
        {"token": t, "logprob": lp, "top_logprobs": [{"token": t, "logprob": lp}, *({"token": a, "logprob": b} for a, b in alts)]}
        for t, lp, alts in steps]}}


def test_top_labels_finds_x10_runner_up_at_the_zero_digit():
    ch = _choice("50 nghìn đồng", [("5", 0.0, []), ("0", math.log(0.7), [("0", math.log(0.7))]), (" ngh", math.log(0.9), [("0", math.log(0.2))]),
                                    ("ìn", 0.0, []), (" đồng", 0.0, [])])
    # Nhánh khác ở token thứ 3: "5","0","0" -> tiền tố "500" khớp "500 đồng"/"500 nghìn đồng"; ưu tiên nhãn lệch x10 với top-1.
    top = read_money.top_labels(ch, "50 nghìn đồng")
    assert top[0][0] == "50 nghìn đồng" and abs(top[0][1] - 0.7 * 0.9) < 1e-9
    assert top[1][0] == "500 nghìn đồng" and abs(top[1][1] - 0.7 * 0.2) < 1e-9


def test_top_labels_runner_up_unsure_label():
    ch = _choice("2 nghìn đồng", [("2", math.log(0.6), [("không", math.log(0.35))]), (" ngh", 0.0, []), ("ìn", 0.0, []), (" đồng", 0.0, [])])
    top = read_money.top_labels(ch, "2 nghìn đồng")
    assert [t[0] for t in top] == ["2 nghìn đồng", "không rõ"]


def test_top_labels_without_alternatives_or_logprobs_is_top1_only():
    ch = _choice("không rõ", [("không", 0.0, []), (" rõ", 0.0, [])])
    assert read_money.top_labels(ch, "không rõ") == [("không rõ", 1.0)]
    # thiếu logprobs: vẫn giữ nhãn top-1 để hint() không mất "không rõ" (xác suất không biết = None)
    assert read_money.top_labels({"message": {"content": "không rõ"}}, "không rõ") == [("không rõ", None)]


def test_unsure_without_logprobs_still_says_step_back():
    top = read_money.top_labels({"message": {"content": "không rõ"}}, "không rõ")
    assert read_money.hint(top, 500.0) == BACK


# ── ngưỡng ───────────────────────────────────────────────────────────────────────────────────
def test_default_min_prob_is_0_999():
    assert config.MONEY_MIN_PROB == 0.999 and config.MONEY_RETRY_PROB == 0.999
    assert read_money.say("50 nghìn đồng", 0.998, config.MONEY_MIN_PROB) == read_money.UNSURE
    assert read_money.say("50 nghìn đồng", 0.9995, config.MONEY_MIN_PROB) == "50 nghìn đồng"


def test_retry_defaults():
    assert config.MONEY_RETRY is True
    assert config.MONEY_RETRY_SETTLE_S == 1.0 and config.MONEY_RETRY_TIMEOUT_S == 3.0
    assert config.MONEY_BLUR_HINT > 0


# ── bộ định tuyến làn B ──────────────────────────────────────────────────────────────────────
class _Warmer:
    def __init__(self):
        self.calls = []

    def session(self, mode, params=None):
        self.calls.append((mode, params))
        return SimpleNamespace(token="tok-1")


def _ctx(single_shot=False):
    async def image():
        return SimpleNamespace(jpeg=_jpeg(sharp=True))

    return SimpleNamespace(device="dev-money", single_shot=single_shot, prewarmer=_Warmer(), image=image)


def _fake_choose(label, prob, top=None):
    calls = []

    async def fake(messages):
        calls.append(messages)
        return label, prob, top if top is not None else [(label, prob)]

    return fake, calls


def _route(ctx, monkeypatch, label, prob, top=None):
    fake, calls = _fake_choose(label, prob, top)
    monkeypatch.setattr(read_money, "choose_ranked", fake)
    reply = asyncio.run(final_router._lane_b(ctx, Decision("money"), "đọc tiền"))
    return reply, calls


def test_sure_read_speaks_denomination_without_live(monkeypatch):
    ctx = _ctx()
    reply, calls = _route(ctx, monkeypatch, "50 nghìn đồng", 0.9995)
    assert list(reply.speech) == ["50 nghìn đồng"] and reply.live is None and ctx.prewarmer.calls == []
    assert len(calls) == 1  # đúng 1 lượt Gemma


def test_unsure_read_speaks_hint_and_opens_money_retry_live(monkeypatch):
    ctx = _ctx()
    reply, calls = _route(ctx, monkeypatch, "50 nghìn đồng", 0.998, [("50 nghìn đồng", 0.998), ("500 nghìn đồng", 0.001)])
    assert list(reply.speech) == [BACK]
    assert reply.live == "ocr" and reply.live_token == "tok-1" and reply.intent == "money" and reply.lane == "B"
    assert ctx.prewarmer.calls == [("ocr", {"mode": "money_retry"})]  # phiên mode "ocr" để nav tạm nhường chỗ như OCR live
    assert len(calls) == 1


def test_unsure_blurry_frame_says_hold_still(monkeypatch):
    ctx = _ctx()

    async def blurry():
        return SimpleNamespace(jpeg=_jpeg(sharp=False))

    ctx.image = blurry
    reply, _ = _route(ctx, monkeypatch, "50 nghìn đồng", 0.5)
    assert list(reply.speech) == [STILL] and reply.live == "ocr"


def test_unsure_single_shot_speaks_hint_without_live(monkeypatch):
    ctx = _ctx(single_shot=True)
    reply, _ = _route(ctx, monkeypatch, "không rõ", 0.9)
    assert list(reply.speech) == [BACK] and reply.live is None and ctx.prewarmer.calls == []


def test_retry_off_keeps_old_behaviour_and_never_opens_live(monkeypatch):
    monkeypatch.setattr(config, "MONEY_RETRY", False)
    ctx = _ctx()
    old = []

    def spoken(jpeg, mode, device):  # đường cũ: ocr_live.spoken(entry.jpeg, "money", ...)
        old.append(mode)
        return ["ĐƯỜNG CŨ"]

    async def boom(messages):
        raise AssertionError("MONEY_RETRY=0 không được đi đường mới")

    monkeypatch.setattr(ocr_live, "spoken", spoken)
    monkeypatch.setattr(read_money, "choose_ranked", boom)
    monkeypatch.setattr(final_router, "_sync", lambda ctx, agen: agen)  # SyncIter cần loop của lượt thật
    reply = asyncio.run(final_router._lane_b(ctx, Decision("money"), "đọc tiền"))
    assert reply.live is None and ctx.prewarmer.calls == [] and reply.speech == ["ĐƯỜNG CŨ"] and old == ["money"]


def test_no_money_and_network_error_do_not_retry(monkeypatch):
    ctx = _ctx()
    reply, _ = _route(ctx, monkeypatch, "không có tiền", 0.9)
    assert list(reply.speech) == [read_money.NO_MONEY] and reply.live is None

    async def broken(messages):
        raise llm.LLMError("mất mạng")

    monkeypatch.setattr(read_money, "choose_ranked", broken)
    reply = asyncio.run(final_router._lane_b(ctx, Decision("money"), "đọc tiền"))
    assert list(reply.speech) == [read_money.UNSURE] and reply.live is None


def test_hint_sentences_are_prerendered():
    for line in (STILL, BACK, CLOSER, read_money.RETRY_FAILED):
        assert line in final_router.STATIC_SPEECH


# ── phiên live money_retry ───────────────────────────────────────────────────────────────────
class _Box:
    """Socket giả: ghi lại khung văn bản và câu nói; khung ảnh đẩy vào qua feed_frame."""

    def __init__(self, monkeypatch):
        self.texts, self.said, self.exits = [], [], []

        async def send_text(s):
            self.texts.append(json.loads(s))

        async def send_bytes(b):
            pass

        async def speak(ws, text):
            line = "".join(text)
            # Lời báo thoát chế độ ("Thoát đọc tiền.") kiểm riêng ở tests/test_che_do_vao_ra.py: ở đây chỉ câu nội dung.
            (self.exits if line == ocr_live.EXIT_MONEY else self.said).append(line)

        monkeypatch.setattr(ocr_live, "speak_ws", speak)
        self.ws = LiveSocket(send_text, send_bytes)
        self.session = LiveSession("tok", "dev-money", "ocr", {"mode": "money_retry"})

    def types(self):
        return [t["t"] for t in self.texts]


def _fast(monkeypatch, settle=0.3, timeout=1.5):
    monkeypatch.setattr(config, "MONEY_RETRY_SETTLE_S", settle)
    monkeypatch.setattr(config, "MONEY_RETRY_TIMEOUT_S", timeout)
    monkeypatch.setattr(config, "MONEY_BLUR_HINT", 100.0)
    monkeypatch.setattr(config, "LIVE_MAX_FPS", 0)


def _patch_read(monkeypatch, label="50 nghìn đồng", prob=0.9999, seen=None):
    async def fake(messages):
        if seen is not None:
            seen.append(messages)
        return label, prob, [(label, prob)]

    monkeypatch.setattr(read_money, "choose_ranked", fake)


async def _drive(box, script):
    """script: [(giây chờ, jpeg)] — đẩy khung vào socket rồi chạy runner tới hết."""
    task = asyncio.create_task(ocr_live.run(box.ws, box.session))

    async def feed():
        for wait, jpeg in script:
            await asyncio.sleep(wait)
            box.ws.feed_frame(jpeg)

    await asyncio.gather(task, feed())


def test_money_retry_drops_settle_frames_reads_first_sharp_one_and_ends(monkeypatch):
    _fast(monkeypatch)
    box, seen = _Box(monkeypatch), []
    _patch_read(monkeypatch, seen=seen)
    sharp_early = _jpeg(True, 64, 48)   # trong 0,3 s đầu: phải bị bỏ dù nét
    sharp_late = _jpeg(True, 192, 144)
    asyncio.run(_drive(box, [(0.05, sharp_early), (0.4, _jpeg(False)), (0.1, sharp_late)]))
    assert box.texts[0] == json.loads(protocol.cam("vga", 5))
    assert box.types() == ["cam", "end"] and box.said == ["50 nghìn đồng"]
    assert len(seen) == 1  # đúng 1 lượt Gemma (chỉ đọc 1 lần)


def test_money_retry_clocks_start_after_cam_is_sent(monkeypatch):
    """Gửi `cam` mất 0,6 s: vẫn phải chờ trọn SETTLE (0,3 s) SAU cam và còn trọn TIMEOUT (1,0 s) sau cam."""
    _fast(monkeypatch, settle=0.3, timeout=1.0)
    box = _Box(monkeypatch)
    cam_sent = asyncio.Event()

    async def slow_send(s):
        box.texts.append(json.loads(s))
        if json.loads(s)["t"] == "cam":
            await asyncio.sleep(0.6)
            cam_sent.set()

    async def send_bytes(b):
        pass

    box.ws = LiveSocket(slow_send, send_bytes)
    used = []

    async def fake_frame(jpeg, min_prob):
        used.append(jpeg)
        return "50 nghìn đồng", [("50 nghìn đồng", 1.0)]

    monkeypatch.setattr(ocr_live, "read_money_frame", fake_frame)
    early, late = _jpeg(True, 64, 48), _jpeg(True, 192, 144)

    async def main():
        task = asyncio.create_task(ocr_live.run(box.ws, box.session))
        await cam_sent.wait()
        await asyncio.sleep(0.05)
        box.ws.feed_frame(early)   # 0,05 s sau cam: còn trong thời gian chỉnh tay -> bỏ
        await asyncio.sleep(0.65)
        box.ws.feed_frame(late)    # 0,7 s sau cam: quá hạn nếu đồng hồ tính từ trước cam (0,6 + 0,7 > 1,0)
        await task

    asyncio.run(main())
    assert used == [late] and box.said == ["50 nghìn đồng"]


def test_money_retry_settle_uses_receive_time_not_processing_time(monkeypatch):
    """Khung NHẬN lúc 0,3 s sau cam (settle 0,6 s) nhưng vòng lặp chỉ xử lý lúc 1,0 s: vẫn phải bỏ."""
    _fast(monkeypatch, settle=0.6, timeout=2.0)
    box = _Box(monkeypatch)
    orig_take, calls = ocr_live._Mailbox.take, []

    async def late_take(self, timeout):
        if not calls:
            calls.append(1)
            await asyncio.sleep(1.0)  # vòng lặp bận: khung nằm trong hộp thư lâu
        return await orig_take(self, timeout)

    monkeypatch.setattr(ocr_live._Mailbox, "take", late_take)

    async def boom(jpeg, min_prob):
        raise AssertionError("khung nhận trong thời gian chỉnh tay không được đọc")

    monkeypatch.setattr(ocr_live, "read_money_frame", boom)
    asyncio.run(_drive(box, [(0.3, _jpeg(True))]))
    assert box.said == [read_money.RETRY_FAILED] and box.types() == ["cam", "end"]


def test_money_retry_frame_used_is_the_first_sharp_after_settle(monkeypatch):
    _fast(monkeypatch)
    box = _Box(monkeypatch)
    used = []

    async def fake_frame(jpeg, min_prob):
        used.append((len(jpeg), min_prob))
        return "50 nghìn đồng", [("50 nghìn đồng", 1.0)]

    monkeypatch.setattr(ocr_live, "read_money_frame", fake_frame)
    early, late = _jpeg(True, 64, 48), _jpeg(True, 192, 144)
    asyncio.run(_drive(box, [(0.05, early), (0.4, _jpeg(False)), (0.1, late)]))
    assert used == [(len(late), config.MONEY_RETRY_PROB)]  # bỏ khung sớm + khung mờ, đọc khung nét đầu tiên, ngưỡng MONEY_RETRY_PROB
    assert box.said == ["50 nghìn đồng"] and box.types() == ["cam", "end"]


def test_money_retry_timeout_takes_sharpest_seen(monkeypatch):
    _fast(monkeypatch, settle=0.1, timeout=0.8)
    monkeypatch.setattr(config, "MONEY_BLUR_HINT", 10 ** 9)  # không khung nào đạt -> hết hạn lấy khung nét nhất
    box, used = _Box(monkeypatch), []

    async def fake_frame(jpeg, min_prob):
        used.append(jpeg)
        return "không rõ", [("không rõ", 1.0)]

    monkeypatch.setattr(ocr_live, "read_money_frame", fake_frame)
    flat, noisy = _jpeg(False), _jpeg(True)
    t = time.monotonic()
    asyncio.run(_drive(box, [(0.2, noisy), (0.1, flat)]))
    assert used == [noisy] and time.monotonic() - t < 2.0
    assert box.said == [read_money.RETRY_FAILED] and box.types() == ["cam", "end"]


def test_money_retry_no_frame_in_time_says_still_unsure(monkeypatch):
    _fast(monkeypatch, settle=0.1, timeout=0.4)
    box = _Box(monkeypatch)

    async def boom(jpeg, min_prob):
        raise AssertionError("không có khung thì không đọc")

    monkeypatch.setattr(ocr_live, "read_money_frame", boom)
    asyncio.run(_drive(box, []))
    assert box.said == [read_money.RETRY_FAILED] and box.types() == ["cam", "end"]


def test_money_retry_unsure_again_says_still_unsure_and_never_loops(monkeypatch):
    _fast(monkeypatch)
    box, seen = _Box(monkeypatch), []
    _patch_read(monkeypatch, prob=0.5, seen=seen)  # dưới ngưỡng
    asyncio.run(_drive(box, [(0.4, _jpeg(True)), (0.1, _jpeg(True)), (0.1, _jpeg(True))]))
    assert box.said == [read_money.RETRY_FAILED] and len(seen) == 1 and box.types().count("cam") == 1


def test_money_retry_turn_start_cancels_without_speaking(monkeypatch):
    _fast(monkeypatch)
    box = _Box(monkeypatch)
    _patch_read(monkeypatch)

    async def go():
        task = asyncio.create_task(ocr_live.run(box.ws, box.session))
        await asyncio.sleep(0.1)
        box.session.closed.set()        # DeviceSession._stop_live: huỷ khi turn_start mới
        box.ws.feed_disconnect()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    assert box.said == [] and "end" not in box.types()


def test_money_retry_socket_close_or_closed_session_before_speaking_does_not_speak(monkeypatch):
    _fast(monkeypatch)
    box = _Box(monkeypatch)

    async def fake_frame(jpeg, min_prob):
        box.session.closed.set()  # huỷ đúng lúc Gemma đang đọc
        return "50 nghìn đồng", [("50 nghìn đồng", 1.0)]

    monkeypatch.setattr(ocr_live, "read_money_frame", fake_frame)
    asyncio.run(_drive(box, [(0.4, _jpeg(True))]))
    assert box.said == []


def test_blur_score_orders_sharp_above_blurry_and_uses_reference_width():
    assert read_money.blur_score(_jpeg(True)) > config.MONEY_BLUR_HINT > read_money.blur_score(_jpeg(False))
    big = _jpeg(True, 1600, 1200)
    assert read_money.blur_score(big) is not None
    assert read_money.blur_score(b"khong phai anh") is None
