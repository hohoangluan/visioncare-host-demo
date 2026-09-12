"""T14 — câu hỏi OCR, cache transcript và follow-up text-only."""

import time
from unittest.mock import patch

import pytest

import config
from handlers import action_flow, ocr as ocr_handler
from models import ocr
from pipeline import image_quality, intent as intent_mod, router


IMG_A = b"image-a"
IMG_B = b"image-b-khac-khung"


@pytest.fixture(autouse=True)
def _clean_ocr_state():
    action_flow.reset_state()
    image_quality.reset_no_text_count()
    yield
    action_flow.reset_state()
    image_quality.reset_no_text_count()


def _fake_stream(monkeypatch, pieces):
    calls = []

    def generate(prompt, image=None, **kwargs):
        calls.append({"prompt": prompt, "image": image, **kwargs})
        for piece in pieces:
            if isinstance(piece, BaseException):
                raise piece
            yield piece

    monkeypatch.setattr(ocr.vlm, "generate_stream", generate)
    return calls


def test_command_text_reaches_prompt(monkeypatch):
    calls = _fake_stream(monkeypatch, ["Dòng hai"])
    list(ocr.read_stream(IMG_A, ocr.Mode.NORMAL, "đọc dòng thứ hai"))
    assert 'Người dùng hỏi: "đọc dòng thứ hai"' in calls[0]["prompt"]


def test_prompt_has_both_clauses():
    prompt = ocr.prompts.build(ocr.Mode.NORMAL, "đọc phần giá tiền")
    lowered = prompt.lower()
    assert "chỉ đọc đúng phần đó" in lowered
    assert "không chỉ định thì đọc toàn bộ" in lowered


@pytest.mark.parametrize(
    "command,expected",
    [
        ("đọc nguyên văn", ocr.Mode.RAW),
        ("đọc tài liệu chuyên ngành", ocr.Mode.SPECIALIZED),
        ("đọc chữ này", ocr.Mode.NORMAL),
    ],
)
def test_mode_detection_unchanged(monkeypatch, command, expected):
    seen = {}

    def fake_read(image, mode, command_text, **kwargs):
        seen.update(image=image, mode=mode, command_text=command_text)
        yield "ok"

    monkeypatch.setattr(ocr_handler.ocr, "read_stream", fake_read)
    list(ocr_handler.handle(IMG_A, command, {}))
    assert seen == {"image": IMG_A, "mode": expected, "command_text": command}


def test_transcript_cached_after_stream(monkeypatch):
    _fake_stream(monkeypatch, ["Dòng một.\n", "Dòng hai."])
    assert "".join(ocr_handler.handle(IMG_A, "đọc chữ", {})) == "Dòng một.\nDòng hai."
    cached = action_flow.get_last_ocr()
    assert cached is not None
    assert cached["text"] == "Dòng một.\nDòng hai."


def test_no_cache_on_sentinel(monkeypatch):
    _fake_stream(monkeypatch, [ocr.NO_TEXT_SENTINEL])
    out = "".join(ocr_handler.handle(IMG_A, "đọc chữ", {}))
    assert action_flow.get_last_ocr() is None
    assert ocr.NO_TEXT_SENTINEL not in out
    assert image_quality.no_text_count() == 1


def test_no_cache_on_partial_stream(monkeypatch):
    _fake_stream(monkeypatch, ["Đây là phần đầu đủ dài để stream.", RuntimeError("mất mạng")])
    with pytest.raises(RuntimeError, match="mất mạng"):
        list(ocr_handler.handle(IMG_A, "đọc chữ", {}))
    assert action_flow.get_last_ocr() is None


def test_followup_uses_text_only(monkeypatch):
    action_flow.remember_ocr("Dòng một\nDòng hai là 250 nghìn đồng")
    calls = _fake_stream(monkeypatch, ["250 nghìn đồng"])
    out = "".join(
        ocr_handler.handle(IMG_B, "dòng hai nói gì", {"ocr_followup": True})
    )
    assert out == "250 nghìn đồng"
    assert calls[0]["image"] is None
    assert "Dòng hai là 250 nghìn đồng" in calls[0]["prompt"]


def test_followup_router_skips_image_gate_and_new_image(monkeypatch):
    action_flow.remember_ocr("Dòng một\nDòng hai")
    calls = _fake_stream(monkeypatch, ["Dòng hai"])
    with (
        patch("pipeline.stt.transcribe", return_value="dòng hai nói gì"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=("ocr", {"ocr_followup": True}),
        ),
        patch("pipeline.image_quality.reject_reason") as gate,
    ):
        out = "".join(router.resolve_speech(None, b"audio"))
    assert out == "Dòng hai"
    gate.assert_not_called()
    assert calls[0]["image"] is None


def test_followup_faster_than_full_ocr(monkeypatch):
    action_flow.remember_ocr("A\nB")
    calls = _fake_stream(monkeypatch, ["B"])
    list(ocr_handler.handle(IMG_B, "đọc dòng hai", {"ocr_followup": True}))
    assert len(calls) == 1
    assert calls[0]["image"] is None


def test_expired_cache_falls_back_to_image(monkeypatch):
    action_flow.remember_ocr(
        "transcript cũ", taken_at=time.monotonic() - ocr_handler.OCR_CACHE_TTL_SECONDS - 1
    )
    calls = _fake_stream(monkeypatch, ["Nội dung ảnh mới"])
    list(ocr_handler.handle(IMG_B, "đọc dòng hai", {"ocr_followup": True}))
    assert calls[0]["image"] == IMG_B


def test_unrelated_question_does_not_use_cache():
    action_flow.remember_ocr("Nội dung hóa đơn")
    with (
        patch("pipeline.stt.transcribe", return_value="phía trước có gì"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=("hazard", {"focus": "front"}),
        ),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        # `hazard` quay về LLM 2026-08-26, nên patch được `handle` như cũ:
        # `router._HANDLERS[Intent.HAZARD]` là MODULE `describe_hazard`, và
        # dispatch đọc `handler_mod.handle` mỗi lượt.
        patch(
            "handlers.describe_hazard.handle",
            return_value=iter(["Lối đi phía trước thoáng."]),
        ) as hazard_call,
        patch("handlers.ocr.handle") as ocr_call,
    ):
        out = "".join(router.resolve_speech(IMG_B, b"audio"))
    hazard_call.assert_called_once()
    assert "hóa đơn" not in out, "câu không liên quan lại lôi cache OCR ra dùng"
    ocr_call.assert_not_called()


def test_line_number_stable_across_turns(monkeypatch):
    transcript_a = "A1\nA2 đúng\nA3\nA4\nA5"
    action_flow.remember_ocr(transcript_a)
    calls = _fake_stream(monkeypatch, ["A2 đúng"])
    out = "".join(
        ocr_handler.handle(IMG_B, "đọc dòng thứ 2", {"ocr_followup": True})
    )
    assert out == "A2 đúng"
    assert calls[0]["image"] is None
    assert transcript_a in calls[0]["prompt"]


def test_followup_signal_is_in_intent_schema():
    props = intent_mod._SCHEMA["properties"]["params"]["properties"]
    assert props["ocr_followup"]["type"] == "boolean"


def test_no_text_guidance_escalates_through_pending(monkeypatch):
    calls = _fake_stream(monkeypatch, [ocr.NO_TEXT_SENTINEL])
    first = "".join(ocr_handler.handle(IMG_A, "đọc chữ", {}))
    pending = action_flow.get_pending()
    assert pending is not None and pending.slot == "ocr_retry"
    assert pending.attempt == 1
    assert first == ocr.prompts.guidance_for_attempt(1)
    assert calls[0]["model"] == config.GEMINI_OCR_MODEL

    # Mô phỏng router chuyển attempt của pending cũ vào lượt retry kế tiếp.
    monkeypatch.setattr(
        ocr.vlm,
        "generate_stream",
        lambda *args, **kwargs: iter([ocr.NO_TEXT_SENTINEL]),
    )
    action_flow.clear_pending()
    second = "".join(ocr_handler.handle(IMG_A, "đọc lại", {"_ocr_attempt": 1}))
    assert second == ocr.prompts.guidance_for_attempt(2)
    assert action_flow.get_pending().attempt == 2
