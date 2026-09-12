"""Luồng chọn bài hát — hỏi để LÀM RÕ, không hỏi để xác nhận.

Người dùng chốt 2026-08-27, sau khi đảo một lần trong cùng ngày. Ghi cả hai
chiều vì đây là quyết định đã đổi ý một lần:

    sáng 2026-08-27  nói đủ bài + ca sĩ -> đọc lại "đúng không?" rồi mới phát
    chiều 2026-08-27 nói đủ bài + ca sĩ -> PHÁT LUÔN

Lý do bỏ bước chốt: câu "phát cho tôi bài Nơi này có anh của Sơn Tùng MTP" đã
không còn gì để hiểu nhầm. Hỏi lại chỉ cộng thêm một lượt bấm nút và vài giây
cho một việc đã rõ — và với người khiếm thị, mỗi lượt bấm là một lần phải giơ
tay lên gọng kính.

Ba ngả còn lại, và mỗi ngả PHẢI khác nhau:

    1. nói đủ bài + ca sĩ        -> phát ngay, không hỏi gì
    2. chỉ nói tên bài           -> hỏi ca sĩ MỘT lần (đây là làm rõ thật:
                                    thiếu thông tin, không phải nghi ngờ)
    3. "cứ phát" / không nhớ     -> phát ngay với dữ liệu đang có

Ngả 3 là chỗ dễ làm sai nhất: hỏi thêm một câu ở đó là đi ngược đúng thứ người
dùng vừa từ chối làm.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from handlers import action_flow, music
from pipeline import router
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


@pytest.fixture
def played(monkeypatch):
    """Danh sách payload đã thật sự gửi xuống điện thoại."""
    calls = []

    def fake_run(operation, endpoint, payload, *, ack, failure, progress, **kw):
        calls.append(payload)
        yield ack

    monkeypatch.setattr(music.action_flow, "run_action", fake_run)
    return calls


def _play(**params):
    params.setdefault("song_is_specific", True)
    return list(music.handle_play(b"", "", params))


def _answer(text: str):
    """Một lượt nói tiếp theo, đi qua router như lượt bấm nút thật."""
    with patch("pipeline.stt.transcribe", return_value=text), patch(
        "pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})
    ):
        return list(router.resolve_speech(b"\xff\xd8anh", b"RIFF"))


# ══════════════════════════════════════════════════════════════════════════
# Ngả 1 — nói đủ ngay câu đầu: PHÁT LUÔN
# ══════════════════════════════════════════════════════════════════════════


def test_full_request_plays_immediately(played):
    """🔴 Đây là bất biến vừa ĐẢO NGƯỢC. Nói đủ bài + ca sĩ thì không còn câu
    "đúng không?" nào nữa — bài chạy ngay."""
    spoken = _play(song_title="Nơi này có anh", artist="Sơn Tùng MTP")

    assert len(played) == 1
    assert played[0]["song"] == "Nơi này có anh - Sơn Tùng MTP"
    assert action_flow.get_pending() is None
    assert "đúng không" not in " ".join(spoken).lower()


def test_full_request_leaves_no_pending_to_answer(played):
    """Không pending nghĩa là lượt nói kế tiếp là một câu HOÀN TOÀN MỚI, không
    bị nuốt làm câu trả lời cho một câu hỏi không còn tồn tại."""
    _play(song_title="Chạy ngay đi", artist="Sơn Tùng")
    assert action_flow.get_pending() is None
    assert len(played) == 1


def test_volume_rides_along_when_given(played):
    _play(song_title="Nơi này có anh", artist="Sơn Tùng", volume=40)
    assert played[0]["volume"] == 40


# ══════════════════════════════════════════════════════════════════════════
# Ngả 2 — thiếu ca sĩ: hỏi MỘT lần, rồi tôn trọng câu trả lời
# ══════════════════════════════════════════════════════════════════════════


def test_song_only_asks_for_the_artist_once(played):
    spoken = _play(song_title="Chạy ngay đi")
    assert played == []
    pending = action_flow.get_pending()
    assert pending is not None and pending.slot == "artist"
    assert "ca sĩ" in " ".join(spoken).lower()


def test_answering_the_artist_plays_without_another_question(played):
    """Người dùng vừa TỰ nói ra tên ca sĩ để trả lời đúng câu hỏi đó. Hỏi thêm
    một câu nữa là bắt họ trả lời hai lần cho một lần chọn."""
    _play(song_title="Chạy ngay đi")
    pending = action_flow.get_pending()
    known = dict(pending.known)
    known["artist"] = "Sơn Tùng"
    action_flow.clear_pending()
    _play(**known)

    assert len(played) == 1
    assert played[0]["song"] == "Chạy ngay đi - Sơn Tùng"
    assert action_flow.get_pending() is None


def test_nothing_specific_asks_which_song(played):
    spoken = _play(song_title="", song_is_specific=False)
    assert played == []
    assert action_flow.get_pending().slot == "song_title"
    assert "bài" in " ".join(spoken).lower()


# ══════════════════════════════════════════════════════════════════════════
# Ngả 3 — "cứ phát": người dùng BỎ QUA việc chọn, đừng hỏi nữa
# ══════════════════════════════════════════════════════════════════════════


def test_skipping_the_artist_plays_with_what_we_already_have(played):
    _play(song_title="Chạy ngay đi")
    spoken = _answer("cứ phát")

    assert len(played) == 1, f"không phát mà lại nói: {spoken!r}"
    assert played[0]["song"] == "Chạy ngay đi"
    assert action_flow.get_pending() is None


# ══════════════════════════════════════════════════════════════════════════
# Bỏ bước chốt của NHẠC không được đụng tới confirm của việc khác
# ══════════════════════════════════════════════════════════════════════════


def test_other_confirmations_still_ask_and_still_cancel():
    """Đặt xe / gọi điện vẫn phải chốt: ở đó đoán sai là tốn tiền hoặc gọi
    nhầm một người thật, nên một lượt xác nhận là đáng."""
    action_flow.set_pending(
        slot="destination",
        intent=Intent.RIDE_CONFIRM,
        known={"destination": "Bách Khoa"},
        question="Đặt xe đi Bách Khoa, đúng không?",
        kind="confirm",
    )
    spoken = " ".join(_answer("không phải"))
    assert "Đã huỷ" in spoken
    assert action_flow.get_pending() is None
