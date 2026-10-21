from handlers import read_money
from models import vlm

IMG = b"fake image"


def test_read_money_streams_vlm_response(monkeypatch):
    captured = {}

    def fake_generate_stream(prompt, image=None):
        captured["prompt"] = prompt
        captured["image"] = image
        yield "50 nghìn đồng."

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)

    speech = "".join(read_money.handle(IMG, "đọc tiền"))

    assert speech == "50 nghìn đồng."
    assert captured["image"] == IMG
    assert "trọng tâm" in captured["prompt"].lower()


def test_read_money_prompt_forbids_filler_words(monkeypatch):
    captured = {}

    def fake_generate_stream(prompt, image=None):
        captured["prompt"] = prompt
        yield "100 nghìn đồng."

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)

    list(read_money.handle(IMG, "đọc mệnh giá"))

    prompt = captured["prompt"].lower()
    assert "đây là" in prompt or "dẫn dắt" in prompt



# ── chọn nhãn có xác suất + gộp nhiều khung (2026-10-21) ──────────────────────
import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

import config  # noqa: E402
from models import llm  # noqa: E402


@pytest.mark.parametrize("reads,min_prob,expected", [
    ([("50 nghìn đồng", 0.999)], 0.995, "50 nghìn đồng"),
    ([("50 nghìn đồng", 0.99)], 0.995, read_money.UNSURE),          # dưới ngưỡng: không nói số
    ([("50 nghìn đồng", None)], 0.995, read_money.UNSURE),          # không có xác suất = không chắc
    ([("không có tiền", 0.6)], 0.995, read_money.NO_MONEY),
    ([("không rõ", 0.9), ("2 nghìn đồng", 1.0), ("2 nghìn đồng", 1.0)], 0.98, "2 nghìn đồng"),
    ([("50 nghìn đồng", 1.0), ("5 nghìn đồng", 1.0)], 0.98, read_money.UNSURE),  # hai khung chắc, mâu thuẫn
    ([("50 nghìn đồng", 1.0), ("5 nghìn đồng", 0.5)], 0.98, "50 nghìn đồng"),     # khung kia không chắc
    ([("không có tiền", 0.9), ("10 nghìn đồng", 0.99)], 0.98, "10 nghìn đồng"),
])
def test_combine(reads, min_prob, expected):
    assert read_money.combine(reads, min_prob) == expected


def test_read_choice_runs_frames_in_parallel_and_uses_multi_threshold(monkeypatch):
    calls = []

    async def fake_choose(messages):
        calls.append(messages)
        await asyncio.sleep(0.05)
        return ("200 nghìn đồng", 0.985)

    monkeypatch.setattr(read_money, "choose", fake_choose)
    monkeypatch.setattr(config, "MONEY_MIN_PROB", 0.995)
    monkeypatch.setattr(config, "MONEY_MULTI_MIN_PROB", 0.98)

    async def collect(images):
        return [p async for p in read_money.read_choice(images)]

    t = time.monotonic()
    multi = asyncio.run(collect([IMG, IMG, IMG]))
    assert time.monotonic() - t < 0.12  # song song, không phải 3 x 0,05 s
    single = asyncio.run(collect([IMG]))
    assert multi == ["200 nghìn đồng"] and single == [read_money.UNSURE]
    assert len(calls) == 4 and calls[0][0]["role"] == "system"


def test_read_choice_network_error_says_unsure(monkeypatch):
    async def broken(messages):
        raise llm.LLMError("mất mạng")

    monkeypatch.setattr(read_money, "choose", broken)

    async def collect():
        return [p async for p in read_money.read_choice([IMG])]

    assert asyncio.run(collect()) == [read_money.UNSURE]


def test_choices_cover_every_denomination_once():
    assert len(read_money.CHOICES) == len(set(read_money.CHOICES)) == len(read_money.DENOMS) + 2
    assert read_money.LABELS["500 nghìn đồng"] == 500000 and read_money.LABELS["200 đồng"] == 200
