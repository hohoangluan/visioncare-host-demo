"""T16 — focus ràng buộc cho space và khóa không-context cho hazard."""

import hashlib
from unittest.mock import patch

import pytest

from handlers import (
    action_flow,
    describe_hazard,
    describe_space,
    find_object,
    read_money,
)
from pipeline import router


IMG = b"image"
_SPACE_BASELINE_SHA256 = "17d4cb1ff254d8dd41255817df07192155e3725a19fe0face1fd1aa30623a6b1"
_HAZARD_BASELINE_SHA256 = "50aaca1d114ed5b7cf747d9b27ba89790f06f281701a46e01f86a7926a9eb52b"


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def _capture(monkeypatch, module):
    calls = []

    def generate(prompt, image=None, **kwargs):
        calls.append({"prompt": prompt, "image": image, **kwargs})
        yield "mô tả"

    monkeypatch.setattr(module.vlm, "generate_stream", generate)
    return calls


def test_focus_left_changes_prompt(monkeypatch):
    calls = _capture(monkeypatch, describe_space)
    list(describe_space.handle(IMG, "bên trái có gì", {"focus": "left"}))
    assert "Chỉ mô tả phía BÊN TRÁI khung hình." in calls[0]["prompt"]


def test_focus_null_prompt_unchanged(monkeypatch):
    calls = _capture(monkeypatch, describe_space)
    list(describe_space.handle(IMG, "trước mặt có gì", {"focus": None}))
    assert calls[0]["prompt"] == describe_space._PROMPT
    assert hashlib.sha256(calls[0]["prompt"].encode()).hexdigest() == _SPACE_BASELINE_SHA256


def test_left_and_front_give_different_answers(monkeypatch):
    calls = _capture(monkeypatch, describe_space)
    list(describe_space.handle(IMG, "", {"focus": "left"}))
    list(describe_space.handle(IMG, "", {"focus": "front"}))
    assert calls[0]["prompt"] != calls[1]["prompt"]
    assert "BÊN TRÁI" in calls[0]["prompt"]
    assert "TRƯỚC MẶT" in calls[1]["prompt"]


def test_prompt_rules_intact():
    prompt = describe_space._prompt_for_focus("right")
    for required in (
        "25 đến 40 từ",
        "1. Loại không gian",
        "2. Bố cục",
        "3. Biển báo hoặc bảng hiệu",
        "KHÔNG được:",
        "Mở đầu bằng",
        "Kể thứ không có",
        "Tả quần áo",
        "Đọc hết một trang",
        "Đọc mệnh giá",
        "Nhắc lại thứ câu trước",
    ):
        assert required in prompt
    assert describe_space._PROMPT.count("- ") == 6


def test_command_text_still_not_injected(monkeypatch):
    calls = _capture(monkeypatch, describe_space)
    secret = "NOI_NGUYEN_VAN_BI_CAM_8291"
    list(describe_space.handle(IMG, secret, {"focus": "left"}))
    assert secret not in calls[0]["prompt"]


def test_behind_answers_without_vlm(monkeypatch):
    generate = patch.object(describe_space.vlm, "generate_stream")
    with generate as vlm_call:
        out = "".join(describe_space.handle(IMG, "phía sau có gì", {"focus": "behind"}))
    assert out == "Tôi không quan sát được phía sau."
    assert out in describe_space.STATIC_SPEECH
    vlm_call.assert_not_called()


def test_no_history_in_space_prompt(monkeypatch):
    action_flow.record_history_turn("HISTORY_SECRET_551", "chiếc ghế cũ")
    calls = _capture(monkeypatch, describe_space)
    list(describe_space.handle(IMG, "", {"focus": "front"}))
    assert "HISTORY_SECRET_551" not in calls[0]["prompt"]
    assert "chiếc ghế cũ" not in calls[0]["prompt"]


def test_hazard_ignores_command_text(monkeypatch):
    calls = _capture(monkeypatch, describe_hazard)
    list(describe_hazard.handle(IMG, "chỉ nói cái ghế"))
    list(describe_hazard.handle(IMG, "có bậc thềm không"))
    assert calls[0]["prompt"] == calls[1]["prompt"] == describe_hazard._PROMPT


def test_hazard_ignores_focus(monkeypatch):
    """🔴 ĐỔI 2026-08-25: `hazard` không còn dựng prompt nào để mà bỏ qua slot.

    Test cũ khoá "hazard dùng đúng `_PROMPT`, không chèn `focus` vào". Giờ
    `hazard` bật chế độ canh liên tục, nên `focus` bị bỏ qua theo một cách
    mạnh hơn hẳn: không có prompt nào cả, và `describe_hazard` không còn ai
    gọi tới.

    Điều đáng khoá còn lại: slot `focus` KHÔNG được làm hỏng lượt đó.
    """
    calls = _capture(monkeypatch, describe_hazard)
    with (
        patch("pipeline.stt.transcribe", return_value="bên trái có nguy hiểm không"),
        patch("pipeline.intent.detect_with_params", return_value=("hazard", {"focus": "left"})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
    ):
        out = "".join(router.resolve_speech(IMG, b"audio"))

    assert calls == [], "describe_hazard vẫn bị gọi — định tuyến chưa đổi"
    assert "cảnh báo vật cản" in out, f"slot focus làm hỏng lượt: {out!r}"


def test_hazard_ignores_history(monkeypatch):
    action_flow.record_history_turn("HISTORY_HAZARD_771", "vật cản cũ")
    calls = _capture(monkeypatch, describe_hazard)
    list(describe_hazard.handle(IMG, "an toàn không"))
    assert "HISTORY_HAZARD_771" not in calls[0]["prompt"]


def test_hazard_ignores_ocr_transcript(monkeypatch):
    action_flow.remember_ocr("OCR_SECRET_990")
    calls = _capture(monkeypatch, describe_hazard)
    list(describe_hazard.handle(IMG, "an toàn không"))
    assert "OCR_SECRET_990" not in calls[0]["prompt"]


def test_hazard_ignores_location(monkeypatch):
    calls = _capture(monkeypatch, describe_hazard)
    list(describe_hazard.handle(IMG, "LOCATION_SECRET_440"))
    assert "LOCATION_SECRET_440" not in calls[0]["prompt"]


def test_hazard_prompt_unchanged_from_baseline():
    digest = hashlib.sha256(describe_hazard._PROMPT.encode()).hexdigest()
    assert digest == _HAZARD_BASELINE_SHA256


def test_find_object_still_uses_command_text(monkeypatch):
    calls = _capture(monkeypatch, find_object)
    list(find_object.handle(IMG, "tìm chìa khóa xanh"))
    assert "tìm chìa khóa xanh" in calls[0]["prompt"]


def test_read_money_still_ignores_command_text(monkeypatch):
    calls = _capture(monkeypatch, read_money)
    list(read_money.handle(IMG, "MONEY_SECRET_332"))
    assert "MONEY_SECRET_332" not in calls[0]["prompt"]
