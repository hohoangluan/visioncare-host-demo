import pytest
from pipeline import intent
from schemas import Intent
from models import vlm


@pytest.mark.parametrize("label,expected", [
    ("ocr", Intent.OCR),
    ("find", Intent.FIND),
    ("money", Intent.MONEY),
    ("space", Intent.SPACE),
    ("hazard", Intent.HAZARD),
    ("chat", Intent.CHAT),
    ("nav_start", Intent.NAV_START),
    ("nav_stop", Intent.NAV_STOP),
    ("contact_call", Intent.CONTACT_CALL),
    ("emergency_call", Intent.EMERGENCY_CALL),
    ("ride_quote", Intent.RIDE_QUOTE),
    ("ride_confirm", Intent.RIDE_CONFIRM),
    ("music_play", Intent.MUSIC_PLAY),
    ("music_stop", Intent.MUSIC_STOP),
    ("music_volume", Intent.MUSIC_VOLUME),
])
def test_detect_maps_llm_label_to_intent(monkeypatch, label, expected):
    monkeypatch.setattr(vlm, "generate_json", lambda prompt, **kw: {"intent": label})
    assert intent.detect(label) == expected


def test_detect_with_params(monkeypatch):
    monkeypatch.setattr(
        vlm,
        "generate_json",
        lambda prompt, **kw: {"intent": "nav_start", "params": {"destination": "Bưu điện"}},
    )
    intent_val, params = intent.detect_with_params("chỉ đường tới Bưu điện")
    assert intent_val == Intent.NAV_START
    assert params == {"destination": "Bưu điện"}


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_detect_blank_is_unknown_without_calling_llm(monkeypatch, text):
    """STT không nghe ra chữ nào: không có gì để phân loại, không tốn quota gọi Gemini."""
    def fail_if_called(prompt, **kw):
        raise AssertionError("không được gọi Gemini khi câu rỗng")

    monkeypatch.setattr(vlm, "generate_json", fail_if_called)
    assert intent.detect(text) == Intent.UNKNOWN


def test_detect_unknown_on_vlm_error(monkeypatch):
    def raise_error(prompt, **kw):
        raise vlm.VLMError("Gemini lỗi mạng")

    monkeypatch.setattr(vlm, "generate_json", raise_error)
    assert intent.detect("mô tả xung quanh tôi") == Intent.UNKNOWN


@pytest.mark.parametrize("reply", [
    {"intent": "không phải nhãn hợp lệ"},
    {},
    {"khong_dung_field": "ocr"},
])
def test_detect_unknown_on_invalid_llm_reply(monkeypatch, reply):
    monkeypatch.setattr(vlm, "generate_json", lambda prompt, **kw: reply)
    assert intent.detect("câu lệnh bất kỳ") == Intent.UNKNOWN


def test_detect_passes_command_text_into_prompt(monkeypatch):
    captured = {}

    def fake_generate_json(prompt, **kw):
        captured["prompt"] = prompt
        return {"intent": "chat"}

    monkeypatch.setattr(vlm, "generate_json", fake_generate_json)
    intent.detect("hôm nay bạn khỏe không")

    assert "hôm nay bạn khỏe không" in captured["prompt"]
