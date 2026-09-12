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
    """T16/E6: `hazard` là chức năng AN TOÀN — prompt CỐ ĐỊNH, `focus` bị bỏ qua.

    Thu hẹp khung nhìn theo đúng thứ người dùng vừa hỏi làm model giảm báo cáo
    thứ họ KHÔNG hỏi — có thể chính là vật sắp làm họ vấp.

    🔴 Đã đảo hai lần, ghi cả hai chiều để lần sau đọc không tưởng là lỗi:
      2026-08-25  hazard -> bật chế độ canh, test này khoá "describe_hazard
                  KHÔNG bị gọi"
      2026-08-26  hazard -> quay về LLM, test này khoá lại điều ban đầu
    """
    calls = _capture(monkeypatch, describe_hazard)
    with (
        patch("pipeline.stt.transcribe", return_value="bên trái có nguy hiểm không"),
        patch("pipeline.intent.detect_with_params", return_value=("hazard", {"focus": "left"})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
    ):
        out = "".join(router.resolve_speech(IMG, b"audio"))

    assert len(calls) == 1, f"hazard không tới describe_hazard: {calls!r}"
    assert calls[0]["prompt"] == describe_hazard._PROMPT
    assert "BÊN TRÁI" not in calls[0]["prompt"], "slot focus đã lọt vào prompt an toàn"
    assert (
        hashlib.sha256(calls[0]["prompt"].encode()).hexdigest() == _HAZARD_BASELINE_SHA256
    ), "prompt hazard đã đổi — nếu cố ý thì cập nhật _HAZARD_BASELINE_SHA256"
    assert out == "mô tả"


def test_hazard_reaches_the_llm_through_the_router(monkeypatch):
    """Bản thân việc định tuyến, tách khỏi chuyện `focus`.

    Có test riêng vì hai thứ hỏng độc lập nhau: bảng `_HANDLERS` trỏ sai thì
    test này đỏ, còn prompt bị chèn slot thì test trên đỏ. Gộp lại thì một lần
    đỏ không nói được là cái nào.
    """
    calls = _capture(monkeypatch, describe_hazard)
    with (
        patch("pipeline.stt.transcribe", return_value="phía trước có an toàn không"),
        patch("pipeline.intent.detect_with_params", return_value=("hazard", {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
    ):
        out = "".join(router.resolve_speech(IMG, b"audio"))

    assert len(calls) == 1
    assert calls[0]["image"] == IMG, "hazard phải nhận ĐÚNG ảnh của lượt đó"
    assert out == "mô tả"


def test_hazard_no_longer_starts_the_watch_mode(monkeypatch):
    """Chiều ngược lại của quyết định 2026-08-26: KHÔNG được bật chế độ canh.

    Khoá riêng vì đây là thứ một lần đảo quyết định nữa sẽ phá âm thầm: nếu
    `_HANDLERS[Intent.HAZARD]` bị trỏ lại về `hazard_watch.start`, test trên
    đỏ ngay, nhưng nếu ai đó gọi CẢ HAI thì chỉ test này bắt được.
    """
    _capture(monkeypatch, describe_hazard)
    with (
        patch("pipeline.stt.transcribe", return_value="phía trước có an toàn không"),
        patch("pipeline.intent.detect_with_params", return_value=("hazard", {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
    ):
        list(router.resolve_speech(IMG, b"audio"))

    assert not action_flow.device_state(None).get("hazard_watching"), (
        "hazard đã bật chế độ canh — quyết định 2026-08-26 nói nó phải gọi LLM"
    )


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
