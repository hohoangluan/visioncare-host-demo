"""T09/21.5 — hợp đồng cửa sổ huỷ sau khi đã gửi emergency action."""

from unittest.mock import patch

import pytest

from handlers import phone


def test_action_already_sent_before_window(monkeypatch):
    """Luồng hiện tại gửi action trước khi phát bất kỳ lời nào cho người dùng."""
    events: list[str] = []

    def sent_first(*_args, ack, **_kwargs):
        events.append("action_sent")
        yield ack

    monkeypatch.setattr(phone.action_flow, "run_action", sent_first)
    stream = phone.handle_emergency(b"", "cấp cứu", {})
    first = next(stream)
    events.append("speech_yielded")

    assert events == ["action_sent", "speech_yielded"]
    assert first == phone._EMERGENCY_ACK


@pytest.mark.xfail(
    reason="T09/21.5: chưa có cửa sổ huỷ sau action nên chưa có câu earcon/hướng dẫn",
    strict=True,
)
def test_cancel_window_is_not_a_question():
    with patch.object(phone.action_flow, "run_action", return_value=iter([phone._EMERGENCY_ACK])):
        speech = list(phone.handle_emergency(b"", "cấp cứu", {}))

    cancel_instruction = next(piece for piece in speech if "huỷ" in piece.lower())
    assert "?" not in cancel_instruction


@pytest.mark.xfail(
    reason="T09/21.5: endpoint abort cuộc gọi khẩn cấp chưa có trong endpoint.md",
    strict=True,
)
def test_say_cancel_within_window_sends_abort():
    assert hasattr(phone.action_flow, "abort_emergency_call")


@pytest.mark.xfail(
    reason="T09/21.5: chưa có cửa sổ huỷ để quan sát timeout khi người dùng im lặng",
    strict=True,
)
def test_silence_within_window_does_nothing():
    assert hasattr(phone.action_flow, "emergency_cancel_window")
