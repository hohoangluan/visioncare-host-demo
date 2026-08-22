"""T12 — nhạc dùng slot có cấu trúc, không ghép/đoán bằng chuỗi tự do."""

import inspect
import time
from unittest.mock import patch

import pytest

import config
from handlers import action_flow, music
from pipeline import router


@pytest.fixture(autouse=True)
def _clean_music_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def _capture_actions(monkeypatch):
    calls = []

    def fake_run(operation, endpoint, payload, *, ack, failure, progress, **kwargs):
        calls.append((operation, endpoint, payload, ack, kwargs))
        yield ack

    monkeypatch.setattr(music.action_flow, "run_action", fake_run)
    return calls


def test_no_string_heuristics_left():
    source = inspect.getsource(music)
    for obsolete in (
        "_ARTIST_MARKERS",
        "_GENERIC_SONG_WORDS",
        "_names_an_artist",
        "_names_a_song",
        "_PENDING_SONG",
    ):
        assert obsolete not in source


def test_song_title_and_artist_joined_only_when_both(monkeypatch):
    calls = _capture_actions(monkeypatch)
    list(
        music.handle_play(
            b"", "", {"song_title": "Nơi này có anh", "song_is_specific": True}
        )
    )
    assert calls == []

    action_flow.clear_pending()
    list(
        music.handle_play(
            b"",
            "",
            {
                "song_title": "Nơi này có anh",
                "artist": "Sơn Tùng M-TP",
                "song_is_specific": True,
            },
        )
    )
    assert calls[0][2]["song"] == "Nơi này có anh - Sơn Tùng M-TP"


@pytest.mark.parametrize(
    "command",
    ["mở nhạc nào đó đi", "cho nghe cái gì đó", "nhạc gì cũng được"],
)
def test_generic_request_asks_for_song(command, monkeypatch):
    calls = _capture_actions(monkeypatch)
    out = "".join(
        music.handle_play(
            b"", command, {"song_title": command, "song_is_specific": False}
        )
    )
    pending = action_flow.get_pending()
    assert calls == []
    assert out == "Bạn muốn nghe bài hát nào?"
    assert pending is not None and pending.slot == "song_title"


def test_artist_swallowed_cua_still_detected(monkeypatch):
    calls = _capture_actions(monkeypatch)
    list(
        music.handle_play(
            b"",
            "",
            {
                "song_title": "Nơi này có anh",
                "artist": "Sơn Tùng",
                "song_is_specific": True,
            },
        )
    )
    assert calls[0][2]["song"] == "Nơi này có anh - Sơn Tùng"


def test_song_title_containing_cua_not_split(monkeypatch):
    calls = _capture_actions(monkeypatch)
    list(
        music.handle_play(
            b"",
            "",
            {"song_title": "Chuyện của mùa đông", "song_is_specific": True},
        )
    )
    pending = action_flow.get_pending()
    assert calls == []
    assert pending is not None and pending.slot == "artist"
    assert pending.known["song_title"] == "Chuyện của mùa đông"


def test_music_missing_song_two_turns(monkeypatch):
    _capture_actions(monkeypatch)
    first = "".join(music.handle_play(b"", "mở nhạc đi", {"song_is_specific": False}))
    assert first == "Bạn muốn nghe bài hát nào?"

    with (
        patch("pipeline.stt.transcribe", return_value="Nơi này có anh"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(
                "music_play",
                {"song_title": "Nơi này có anh", "song_is_specific": True},
            ),
        ),
    ):
        second = "".join(router.resolve_speech(None, b"audio"))

    assert "ca sĩ nào" in second
    pending = action_flow.get_pending()
    assert pending is not None and pending.slot == "artist"


def test_music_missing_artist_two_turns(monkeypatch):
    calls = _capture_actions(monkeypatch)
    list(
        music.handle_play(
            b"", "", {"song_title": "Nơi này có anh", "song_is_specific": True}
        )
    )

    with (
        patch("pipeline.stt.transcribe", return_value="Sơn Tùng"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=("music_play", {"artist": "Sơn Tùng"}),
        ),
    ):
        list(router.resolve_speech(None, b"audio"))

    assert calls[0][2]["song"] == "Nơi này có anh - Sơn Tùng"
    assert action_flow.get_pending() is None


def test_any_artist_answer(monkeypatch):
    calls = _capture_actions(monkeypatch)
    list(
        music.handle_play(
            b"", "", {"song_title": "Nơi này có anh", "song_is_specific": True}
        )
    )
    with (
        patch("pipeline.stt.transcribe", return_value="cứ phát"),
        patch("pipeline.intent.detect_with_params") as detect,
    ):
        list(router.resolve_speech(None, b"audio"))

    assert calls[0][2]["song"] == "Nơi này có anh"
    detect.assert_not_called()


def test_volume_missing_direction_two_turns(monkeypatch):
    calls = _capture_actions(monkeypatch)
    first = "".join(music.handle_volume(b"", "chỉnh âm lượng", {}))
    assert first == "Bạn muốn tăng hay giảm âm lượng?"

    with (
        patch("pipeline.stt.transcribe", return_value="tăng"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=("music_volume", {"direction": "up"}),
        ),
    ):
        list(router.resolve_speech(None, b"audio"))

    assert calls[0][0] == "music_volume"
    assert calls[0][2] == {"direction": "up"}


def test_volume_validator_rejects_non_direction():
    assert router._validate_slot("volume_direction", "Sơn Tùng") is False
    assert router._validate_slot("volume_direction", "tăng") is True


def test_music_pending_ttl_expired(monkeypatch):
    calls = _capture_actions(monkeypatch)
    pending = action_flow.set_pending(
        "artist",
        "music_play",
        {"song_title": "Bài cũ"},
        "Bạn muốn nghe của ca sĩ nào?",
    )
    pending.asked_at = time.monotonic() - config.PENDING_TTL_FILL_SECONDS - 1
    assert action_flow.get_pending() is None

    list(
        music.handle_play(
            b"",
            "",
            {
                "song_title": "Bài mới",
                "artist": "Đen Vâu",
                "song_is_specific": True,
            },
        )
    )
    assert calls[0][2]["song"] == "Bài mới - Đen Vâu"


def test_song_not_found_sets_pending(monkeypatch):
    monkeypatch.setattr(
        music.action_flow,
        "call_service_api",
        lambda *_args, **_kwargs: {"data": {"request_id": "song-missing"}},
    )
    monkeypatch.setattr(
        music.action_flow,
        "get_request_status",
        lambda _request_id: {
            "request_state": "failed",
            "result": {},
            "error": {"code": "SONG_NOT_FOUND"},
        },
    )
    list(
        music.handle_play(
            b"",
            "",
            {"song_title": "Bài lạ", "artist": "Ca sĩ lạ", "song_is_specific": True},
        )
    )
    pending = action_flow.get_pending()
    assert pending is not None
    assert (pending.slot, pending.intent) == ("song_title", "music_play")


def test_music_playing_stays_true_after_song_ends():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    # Host không có callback "bài đã hết"; không tự đặt TTL đoán mò.
    assert action_flow.device_state()["music_playing"] is True


def test_music_play_does_not_stop_navigation():
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    state = action_flow.device_state()
    assert state["navigating"] is True
    assert state["music_playing"] is True
