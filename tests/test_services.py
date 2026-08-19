import json
import pytest
from unittest.mock import patch, MagicMock

import config
from services import visioncare_client
from handlers import action_flow, navigation, phone, ride, music


def test_call_service_api_success(monkeypatch):
    """Chặn ở tầng vận chuyển của httpx, không phải ở `_client()`.

    Bản trước stub `urllib.request.urlopen`. Khi client đổi sang httpx thì cái
    stub đó thành vô hại theo kiểu tệ nhất: test không lỗi vì thiếu stub, nó
    lặng lẽ GỌI THẬT ra host production và chỉ hỏng khi API trả 400. Chặn ở
    `MockTransport` thì không đường nào ra được mạng.
    """
    import httpx

    captured_req = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_req["url"] = str(request.url)
        captured_req["headers"] = dict(request.headers)
        captured_req["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(202, json={
            "status": "ok",
            "data": {
                "request_id": "req-123",
                "operation": "ride_quote",
                "request_state": "processing",
            },
        })

    monkeypatch.setattr(
        visioncare_client, "_CLIENT",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    res = visioncare_client.call_service_api(
        "api/v1/service/ride/quote", {"destination": {"address": "Bách Khoa"}}
    )

    assert res["status"] == "ok"
    assert captured_req["url"] == f"{config.VISIONCARE_HOST_URL}/api/v1/service/ride/quote"
    assert captured_req["headers"]["authorization"] == f"Bearer {config.VISIONCARE_CLIENT_TOKEN}"
    assert captured_req["body"]["device_id"] == config.VISIONCARE_DEVICE_ID
    assert "request_id" in captured_req["body"]
    assert captured_req["body"]["destination"]["address"] == "Bách Khoa"


def _stub_flow(monkeypatch, final_result=None, state="succeeded", error=None):
    """Replace the two network calls run_action makes, and record what was sent.

    Both are patched on handlers.action_flow, the single module every handler
    now routes through. The status stub answers terminal on the first poll, so
    no test waits on the progress timer.
    """
    calls = []

    def fake_call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"status": "ok", "data": {"request_id": f"req-{len(calls)}"}}

    def fake_status(request_id):
        return {"request_state": state, "result": final_result or {}, "error": error}

    monkeypatch.setattr(action_flow, "call_service_api", fake_call)
    monkeypatch.setattr(action_flow, "get_request_status", fake_status)
    return calls


def test_navigation_start_speaks_the_destination_the_phone_confirmed(monkeypatch):
    calls = _stub_flow(monkeypatch, {"navigation_id": "nav-9", "destination": {"address": "Chợ Bến Thành"}})

    out = "".join(navigation.handle_start(b"", "", {"destination": "Chợ Bến Thành"}))

    assert calls[0][0] == "api/v1/service/navigation/start"
    assert "Chợ Bến Thành" in out
    assert "Đã mở chỉ đường" in out
    # Maps opens through the launcher notification, which Android only
    # auto-opens with the screen off, so the reply has to say so.
    assert "nhấn vào thông báo" in out


def test_navigation_start_refuses_without_a_destination(monkeypatch):
    calls = _stub_flow(monkeypatch)

    out = "".join(navigation.handle_start(b"", "", {}))

    # Previously fell back to the literal string "điểm đến yêu cầu" and sent the
    # command anyway, so a misheard phrase started navigation to nowhere.
    assert calls == []
    assert "Bạn muốn đi đâu" in out


def test_navigation_stop_reuses_the_id_from_the_last_start(monkeypatch):
    calls = _stub_flow(monkeypatch, {"navigation_id": "nav-9", "destination": {"address": "Chợ Bến Thành"}})
    "".join(navigation.handle_start(b"", "", {"destination": "Chợ Bến Thành"}))

    out = "".join(navigation.handle_stop(b"", "", {}))

    assert calls[1][0] == "api/v1/service/navigation/stop"
    assert calls[1][1]["navigation_id"] == "nav-9"
    assert "dừng chỉ đường" in out.lower()


def test_navigation_stop_refuses_when_nothing_is_running(monkeypatch):
    action_flow.forget("navigation_id")
    calls = _stub_flow(monkeypatch)

    out = "".join(navigation.handle_stop(b"", "", {}))

    # The old code hardcoded "nav-123", which the host always rejected.
    assert calls == []
    assert "không có lộ trình" in out.lower()


def test_contact_call_speaks_the_name_the_phone_resolved(monkeypatch):
    calls = _stub_flow(monkeypatch, {"call_state": "calling", "contact_name": "Nguyễn Văn A"})

    out = "".join(phone.handle_contact(b"", "", {"contact_name": "Nguyễn Văn A"}))

    assert calls[0][0] == "api/v1/service/contact/call"
    assert "Đang gọi cho Nguyễn Văn A" in out


def test_contact_call_reports_a_failed_call_as_failed(monkeypatch):
    calls = _stub_flow(monkeypatch, state="failed")
    monkeypatch.setattr(
        action_flow,
        "get_request_status",
        lambda request_id: {
            "request_state": "failed",
            "result": None,
            "error": {"code": "CONTACT_NOT_FOUND"},
        },
    )

    out = "".join(phone.handle_contact(b"", "", {"contact_name": "Ai Đó"}))

    assert calls[0][0] == "api/v1/service/contact/call"
    assert "Không tìm thấy" in out


def test_contact_call_refuses_without_a_name(monkeypatch):
    calls = _stub_flow(monkeypatch)

    out = "".join(phone.handle_contact(b"", "", {}))

    assert calls == []
    assert "gọi cho ai" in out.lower()


def test_emergency_call_speaks_whether_the_sms_went_out(monkeypatch):
    calls = _stub_flow(monkeypatch, {"contact": "***768", "sms_sent": True})

    out = "".join(phone.handle_emergency(b"", "", {}))

    assert calls[0][0] == "api/v1/service/emergency/call"
    assert "khẩn cấp" in out
    assert "đã gửi tin nhắn vị trí" in out


def test_ride_quote_reads_the_destination_back_and_books_nothing_yet(monkeypatch):
    calls = _stub_flow(monkeypatch)

    out = "".join(ride.handle_quote(b"", "", {"destination": "Sân bay"}))

    # Speech-to-text mishears place names, and a wrong one sends a blind person
    # to the wrong address, so the first turn only confirms what was heard.
    assert calls == []
    assert "Sân bay" in out
    assert "đúng không" in out


def test_ride_confirm_books_the_destination_that_was_read_back(monkeypatch):
    calls = _stub_flow(
        monkeypatch,
        {
            "quote_id": "quote-9",
            "product_type": "GrabCar",
            "price_estimate": {"currency": "VND", "amount": 85000},
            "eta_minutes": 6,
        },
    )
    "".join(ride.handle_quote(b"", "", {"destination": "Sân bay"}))

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert calls[0][0] == "api/v1/service/ride/quote"
    assert calls[0][1]["destination"]["address"] == "Sân bay"
    # No price, product type or ETA: Grab only quotes after the rider confirms
    # the pickup point, which this flow cannot reach, so any number here would
    # be the backend's guess presented as a fare.
    assert "85" not in out
    assert "nghìn" not in out
    assert "phút" not in out
    assert "điểm đón" in out and "xác nhận" in out


def test_ride_confirm_cancels_without_calling_anything(monkeypatch):
    calls = _stub_flow(monkeypatch)
    "".join(ride.handle_quote(b"", "", {"destination": "Sân bay"}))

    out = "".join(ride.handle_confirm(b"", "", {"confirm": False}))

    assert calls == []
    assert "hủy" in out.lower()


def test_ride_confirm_refuses_when_nothing_was_asked_for(monkeypatch):
    action_flow.forget("quote_id")
    action_flow.forget("pending_ride_destination")
    calls = _stub_flow(monkeypatch)

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert calls == []
    assert "chưa có chuyến nào" in out.lower()


def test_ride_destination_not_found_is_reported_not_guessed(monkeypatch):
    _stub_flow(monkeypatch)
    monkeypatch.setattr(
        action_flow,
        "get_request_status",
        lambda request_id: {
            "request_state": "failed",
            "result": None,
            "error": {"code": "INVALID_DESTINATION"},
        },
    )
    "".join(ride.handle_quote(b"", "", {"destination": "Chỗ Không Có Thật"}))

    out = "".join(ride.handle_confirm(b"", "", {"confirm": True}))

    assert "Không tìm thấy địa điểm" in out
    assert "nói lại tên địa điểm" in out


def test_music_play_asks_which_artist_when_only_a_title_was_given(monkeypatch):
    action_flow.forget("pending_song_title")
    calls = _stub_flow(monkeypatch)

    out = "".join(music.handle_play(b"", "", {"song": "Nơi này có anh"}))

    # A bare title matches covers, remixes and karaoke versions; picking one is
    # a guess, and a blind listener cannot see they got the wrong track.
    assert calls == []
    assert "nhiều bài trùng tên" in out
    assert "ca sĩ nào" in out


@pytest.mark.parametrize(
    "command,params",
    [
        ("mở nhạc đi", {"song": "nhạc"}),   # đo thật từ bộ phân loại
        ("bật nhạc lên", {}),               # đo thật: không tách được gì
        ("nghe nhạc", {"song": "nghe nhạc"}),
    ],
)
def test_music_play_asks_which_song_when_none_was_named(command, params, monkeypatch):
    """"Bật nhạc lên" là ý muốn nghe nhạc, chưa phải một bài cụ thể.

    Trước đây câu lệnh tự trở thành tên bài, nên ứng dụng nhạc đi tìm một bài
    hát tên đúng bằng câu người dùng vừa nói.
    """
    action_flow.forget("pending_song_title")
    calls = _stub_flow(monkeypatch)

    out = "".join(music.handle_play(b"", command, params))

    assert calls == []
    assert out == music._ASK_SONG


def test_music_volume_asks_instead_of_guessing_a_direction(monkeypatch):
    """Trước đây mặc định tăng. Người khiếm thị không nhìn được thanh âm lượng
    để chỉnh lại một tiếng to họ không hề yêu cầu."""
    calls = _stub_flow(monkeypatch)

    out = "".join(music.handle_volume(b"", "âm lượng", {}))

    assert calls == []
    assert out == music._ASK_VOLUME


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"direction": "up"}, {"direction": "up"}),
        ({"direction": "down"}, {"direction": "down"}),
        ({"volume": 70}, {"level": 70}),
    ],
)
def test_music_volume_still_acts_when_the_command_was_clear(params, expected, monkeypatch):
    calls = _stub_flow(monkeypatch, {"level": 70})

    "".join(music.handle_volume(b"", "chỉnh âm lượng", params))

    assert {key: calls[0][1][key] for key in expected} == expected
    assert calls[0][1]["request_id"]


def test_music_play_combines_the_artist_answer_with_the_pending_title(monkeypatch):
    action_flow.forget("pending_song_title")
    calls = _stub_flow(monkeypatch, {"title": "Nơi này có anh", "artist": "Sơn Tùng M-TP"})
    "".join(music.handle_play(b"", "", {"song": "Nơi này có anh"}))

    "".join(music.handle_play(b"", "", {"song": "Sơn Tùng M-TP"}))

    assert calls[0][1]["song"] == "Nơi này có anh - Sơn Tùng M-TP"


def test_music_play_honours_cu_phat_as_any_artist(monkeypatch):
    action_flow.forget("pending_song_title")
    calls = _stub_flow(monkeypatch, {"title": "Nơi này có anh", "artist": "Unknown"})
    "".join(music.handle_play(b"", "", {"song": "Nơi này có anh"}))

    "".join(music.handle_play(b"", "", {"song": "cứ phát"}))

    assert calls[0][1]["song"] == "Nơi này có anh"


def test_music_play_speaks_the_track_the_phone_actually_started(monkeypatch):
    action_flow.forget("pending_song_title")
    calls = _stub_flow(monkeypatch, {"title": "Nơi này có anh", "artist": "Sơn Tùng M-TP"})

    out = "".join(music.handle_play(b"", "", {"song": "Nơi này có anh - Sơn Tùng M-TP"}))

    assert calls[0][0] == "api/v1/service/music/play"
    assert "Đã tìm được bài Nơi này có anh của Sơn Tùng M-TP" in out


def test_music_play_reports_silence_as_a_failure(monkeypatch):
    _stub_flow(monkeypatch)
    monkeypatch.setattr(
        action_flow,
        "get_request_status",
        lambda request_id: {
            "request_state": "failed",
            "result": None,
            "error": {"code": "PLAYBACK_FAILED"},
        },
    )

    out = "".join(music.handle_play(b"", "", {"song": "Nơi này có anh - Sơn Tùng M-TP"}))

    # The whole point of polling: "sent the request" used to be the only thing
    # the user ever heard, whether or not a single note came out.
    assert "chưa phát được" in out
    assert "nhấn vào thông báo" in out


def test_music_stop_and_volume_speak_the_confirmed_state(monkeypatch):
    calls = _stub_flow(monkeypatch, {"playback_state": "stopped", "level": 66})

    out_stop = "".join(music.handle_stop(b"", "", {}))
    out_vol = "".join(music.handle_volume(b"", "", {"direction": "up"}))

    assert calls[0][0] == "api/v1/service/music/stop"
    assert "Đã dừng phát nhạc" in out_stop
    assert calls[1][0] == "api/v1/service/music/volume"
    assert "66 phần trăm" in out_vol


def test_no_result_at_slo_keeps_phone_action_running(monkeypatch):
    _stub_flow(monkeypatch)
    # Never leaves processing, so run_action must fall through its budget.
    monkeypatch.setattr(action_flow, "get_request_status", lambda request_id: {"request_state": "processing"})
    monkeypatch.setattr(config, "VISIONCARE_RESULT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(config, "VISIONCARE_RESULT_POLL_SECONDS", 0.01)

    out = "".join(music.handle_stop(b"", "", {}))

    assert "vẫn đang thực hiện" in out.lower()
