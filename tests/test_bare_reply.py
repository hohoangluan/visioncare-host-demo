"""V1: "Đúng"/"Không" đứng một mình khi không có câu hỏi chờ thì KHÔNG chạy lệnh nào."""

import asyncio

import pytest

from lanes import phone
from pipeline import final_router, pending_action
from pipeline.intent_early import Decision

DEV = "dev-bare-reply"
WORDS = ["Đúng", "Có", "Ừ", "Vâng", "Ok", "Được", "Không", "Thôi", "Vâng ạ", "Đúng rồi", "Ừ, được"]
# Nhãn mà bộ phân loại hay đoán bừa cho lời đáp trống không (đã thấy ở e2e 2026-10-21).
WRONG_GUESSES = ["nav_stop", "ride_confirm", "music_stop", "emergency_call", "contact_call", "alert_off"]


@pytest.fixture(autouse=True)
def _clean():
    for table in (phone._CONFIRM, phone._PENDING, phone._CHOICE, phone._OFFER, phone._BODY):
        table.clear()
    pending_action.cancel(DEV, "test")
    pending_action._cancelled_by_turn.clear()
    yield
    for table in (phone._CONFIRM, phone._PENDING, phone._CHOICE, phone._OFFER, phone._BODY):
        table.clear()


def _route(text, intent="nav_stop", state=None):
    ctx = final_router.TurnContext(DEV, "t", None, None)
    ctx.device_state = state or {}
    d = Decision(intent, source="model", backend="gemma", confidence=0.99)
    return asyncio.run(final_router.route(ctx, d, text))


@pytest.mark.parametrize("word", WORDS)
@pytest.mark.parametrize("guess", WRONG_GUESSES)
def test_bare_reply_without_pending_runs_nothing(word, guess):
    reply = _route(word, guess)
    assert list(reply.speech) == [final_router.NO_QUESTION_MESSAGE]
    assert reply.lane == "A" and reply.live is None and not reply.cues and reply.on_audio_start is None


@pytest.mark.parametrize("word", WORDS)
def test_bare_reply_with_state_still_runs_nothing(word):
    """Đang phát nhạc / chỉ đường: "Thôi" vẫn không tự dừng gì (nút bấm không lời mới là cách dừng)."""
    reply = _route(word, "music_stop", {"music_playing": True, "navigating": True})
    assert list(reply.speech) == [final_router.NO_QUESTION_MESSAGE]


@pytest.mark.parametrize("word", ["Đúng", "Có", "Ừ", "Vâng", "Ok", "Được"])
def test_yes_with_pending_confirm_still_confirms(word):
    phone.set_pending_confirm(DEV, "nav_start", {"destination": "sở thú"})
    reply = _route(word, "nav_stop")
    assert reply.intent == "nav_start"
    assert reply.on_audio_start is not None  # đã xếp lệnh chờ sau khi đọc lại
    pending_action.cancel(DEV, "test")


@pytest.mark.parametrize("word", ["Không", "Thôi"])
def test_no_with_pending_confirm_cancels(word):
    phone.set_pending_confirm(DEV, "nav_start", {"destination": "sở thú"})
    reply = _route(word, "nav_stop")
    assert list(reply.speech) == [final_router.CANCELLED_MESSAGE]


def test_offer_and_choice_and_body_count_as_pending():
    phone.set_pending_offer(DEV, "message_send", {"contact_name": "mẹ"})
    assert phone.has_pending(DEV)
    assert list(_route("Không", "nav_stop").speech) == [final_router.CANCELLED_MESSAGE]
    phone.set_pending_choice(DEV, "contact_call", ["Mẹ Lan", "Mẹ Hoa"])
    assert phone.has_pending(DEV)
    phone.take_pending_choice(DEV)
    phone.set_pending_body(DEV, "mẹ")
    assert phone.has_pending(DEV)


def test_pending_expires():
    phone.set_pending_confirm(DEV, "nav_start", {"destination": "x"})
    phone._CONFIRM[DEV] = (*phone._CONFIRM[DEV][:2], phone._CONFIRM[DEV][2] - 999)
    assert not phone.has_pending(DEV)
    assert list(_route("Đúng").speech) == [final_router.NO_QUESTION_MESSAGE]


def test_ride_quote_pending_state_keeps_old_behaviour():
    """Chuyến xe đang chờ xác nhận là một câu hỏi đang chờ: "Đúng" vẫn đi bộ phân loại như trước."""
    reply = _route("Đúng", "ride_confirm", {"ride_quote_pending": True})
    assert list(reply.speech) == ["Xác nhận chuyến xe phải không?"]


@pytest.mark.parametrize("text", ["có gì trước mặt", "đúng rồi đọc chữ giúp tôi", "không phải, gọi cho mẹ"])
def test_real_commands_are_not_bare_replies(text):
    assert not phone.is_bare_reply(text)


def test_no_right_after_window_cancel_says_cancelled():
    """Lệnh đang đọc lại bị lượt "Không" huỷ (begin_turn): nói "Đã huỷ", không nói "chưa hỏi gì"."""
    fired = []
    action = pending_action.schedule(DEV, None, lambda: fired.append(1), label="contact_call")
    assert action is not None
    pending_action.begin_turn(DEV)
    assert action.cancelled.is_set()
    assert list(_route("Không").speech) == [final_router.CANCELLED_MESSAGE]
    assert list(_route("Không").speech) == [final_router.NO_QUESTION_MESSAGE]  # dùng một lần
    assert not fired
