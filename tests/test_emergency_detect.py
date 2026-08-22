"""T09 — khóa đường gọi khẩn cấp nhanh và tuyệt đối.

Các ca ``xfail`` là hợp đồng chưa có thật, không phải test bị làm yếu. Đặc biệt
không hạ ngưỡng nhận diện trước khi có đường abort, vì như vậy sẽ tăng cuộc gọi
nhầm mà người dùng không thể dừng.
"""

import statistics
import time
from unittest.mock import patch

import pytest

from handlers import action_flow, phone
from pipeline import router


@pytest.fixture(autouse=True)
def _clean_emergency_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


@pytest.mark.parametrize(
    "spoken",
    [
        "cấp cứu",
        "cứu tôi",
        pytest.param(
            "gọi cứu thương",
            marks=pytest.mark.xfail(
                reason="T09/21.5b: cổng từ khoá router chưa nhận 'gọi cứu thương'",
                strict=True,
            ),
        ),
        pytest.param(
            "một một bốn",
            marks=pytest.mark.xfail(
                reason="T09/21.5b: cổng từ khoá router chưa nhận cách đọc số 114",
                strict=True,
            ),
        ),
        "khẩn cấp",
    ],
)
def test_keyword_gate_hits(spoken):
    """Từ khoá khẩn cấp phải đi thẳng vào handler, không gọi classifier."""
    with (
        patch("pipeline.stt.transcribe", return_value=spoken),
        patch("pipeline.intent.detect_with_params", return_value=("chat", {})) as detect,
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
    ):
        out = "".join(router.resolve_speech(None, b"audio"))

    assert "khẩn cấp" in out
    emergency.assert_called_once()
    detect.assert_not_called()


@pytest.mark.xfail(
    reason=(
        "T09/21.5b: chưa có ngưỡng emergency riêng thấp hơn ngưỡng SetFit thường; "
        "chỉ được bật cùng cửa sổ abort"
    ),
    strict=True,
)
def test_low_threshold_classifier(monkeypatch):
    """Một dự đoán emergency yếu vẫn phải thắng đường Gemini thông thường."""
    monkeypatch.setattr(
        "pipeline.intent_local.classify",
        lambda _text: None,  # mô phỏng điểm dưới ngưỡng chung nên bị loại
    )
    with (
        patch("pipeline.stt.transcribe", return_value="tôi cần người giúp ngay"),
        patch("pipeline.intent._ask_gemini", return_value=("chat", {})),
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
        patch("handlers.chat.handle", return_value=iter(["Bạn cần tôi giúp gì?"])),
    ):
        list(router.resolve_speech(None, b"audio"))

    emergency.assert_called_once()


@pytest.mark.xfail(
    reason="T09/21.5: endpoint abort và cửa sổ huỷ 3–5 giây chưa tồn tại",
    strict=True,
)
def test_false_positive_has_cancel_window():
    """Sau khi action đã gửi, một báo nhầm phải còn đường dừng cuộc gọi."""
    assert hasattr(action_flow, "abort_emergency_call")


def test_emergency_while_music_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    with (
        patch("pipeline.stt.transcribe", return_value="cứu tôi"),
        patch("handlers.music_stop.handle") as stop,
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
    ):
        list(router.resolve_speech(None, b"audio"))

    emergency.assert_called_once()
    stop.assert_not_called()


def test_emergency_while_pending_open():
    action_flow.set_pending(
        slot="contact_name",
        intent="contact_call",
        known={},
        question="Bạn muốn gọi cho ai?",
    )
    with (
        patch("pipeline.stt.transcribe", return_value="cứu tôi"),
        patch("handlers.contact_call.handle") as contact,
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
    ):
        list(router.resolve_speech(None, b"audio"))

    emergency.assert_called_once()
    contact.assert_not_called()


def test_emergency_skips_image_gate():
    with (
        patch("pipeline.stt.transcribe", return_value="khẩn cấp"),
        patch("pipeline.image_quality.reject_reason") as image_gate,
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
    ):
        list(router.resolve_speech(b"anh-mo", b"audio"))

    emergency.assert_called_once()
    image_gate.assert_not_called()


def test_emergency_does_not_wait_for_image():
    """Không có ảnh vẫn dispatch ngay; bảng F4 không cho emergency cần ảnh."""
    with (
        patch("pipeline.stt.transcribe", return_value="cấp cứu"),
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as emergency,
    ):
        list(router.resolve_speech(None, b"audio"))

    assert emergency.call_args.args[0] is None


def test_emergency_ack_under_300ms(monkeypatch):
    """Đo p50 thời gian dispatch tới mảnh ack đầu, không gồm STT hay phần cứng."""
    sent_at: list[float] = []

    def immediate_action(*_args, ack, **_kwargs):
        sent_at.append(time.perf_counter())
        yield ack

    monkeypatch.setattr(phone.action_flow, "run_action", immediate_action)
    samples = []
    for _ in range(21):
        started = time.perf_counter()
        first = next(phone.handle_emergency(b"", "cấp cứu", {}))
        samples.append(time.perf_counter() - started)
        assert first == phone._EMERGENCY_ACK

    assert len(sent_at) == 21
    assert statistics.median(samples) < 0.300
    assert phone._EMERGENCY_ACK in phone.STATIC_SPEECH
