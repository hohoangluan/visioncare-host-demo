"""Cảnh báo "chưa chắc" khi chữ số đọc ra có xác suất token thấp (lanes/ocr_live.read_image, 2026-10-21)."""

import asyncio
import io
import math

import pytest
from PIL import Image

import config
from lanes import ocr_live
from models import llm


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _fake_stream(pieces: list[tuple[str, float]], seen: dict):
    async def fake(messages, max_tokens=None, on_logprobs=None, **extra):
        seen["on_logprobs"] = on_logprobs
        for text, prob in pieces:
            if on_logprobs is not None:
                on_logprobs([{"token": text, "logprob": math.log(prob)}])
            yield text
    return fake


def _read(monkeypatch, pieces, tau=0.9, mode="normal"):
    seen = {}
    monkeypatch.setattr(llm, "stream_chat", _fake_stream(pieces, seen))
    monkeypatch.setattr(config, "OCR_DIGIT_HEDGE_PROB", tau)

    async def run():
        return "".join([p async for p in ocr_live.read_image(_jpeg(), mode, "test-hedge")])

    return asyncio.run(run()), seen


@pytest.mark.parametrize("digit_prob,hedged", [(0.99, False), (0.6, True)])
def test_hedge_only_when_a_digit_is_unsure(monkeypatch, digit_prob, hedged):
    text, _ = _read(monkeypatch, [("Tổng tiền là ", 0.2), ("8", digit_prob), (".20 đồng.", 0.99)])
    assert text.startswith("Tổng tiền là 8.20 đồng.")  # con số vẫn được đọc
    assert (ocr_live.DIGIT_HEDGE in text) is hedged


def test_low_prob_words_without_digits_never_hedge(monkeypatch):
    text, _ = _read(monkeypatch, [("Cửa hàng ", 0.3), ("Phúc Long, mở cửa buổi sáng.", 0.4)])
    assert ocr_live.DIGIT_HEDGE not in text


def test_hedge_off_does_not_request_logprobs(monkeypatch):
    text, seen = _read(monkeypatch, [("Số ", 0.9), ("7", 0.1), (" ạ, rất rõ ràng.", 0.9)], tau=0.0)
    assert seen["on_logprobs"] is None and ocr_live.DIGIT_HEDGE not in text


def test_hedge_not_saved_for_reread(monkeypatch):
    _read(monkeypatch, [("Mã số ", 0.9), ("12", 0.5), ("34 ở cuối trang.", 0.9)])
    assert ocr_live.DIGIT_HEDGE not in (ocr_live.last_text("test-hedge") or "")
