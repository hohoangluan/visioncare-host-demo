"""`WS /v2/session`: hello/token, một lượt đầu-cuối, huỷ khi có lượt mới, phiên mới thay phiên cũ."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
from app import app
from models import clef
from pipeline import cues, pending_action
from tests.conftest import TEST_DEVICE_TOKEN
from tests.test_v2_api import _adpcm_chunks, _gemma, world  # noqa: F401 (fixture)

client = TestClient(app)


def _hello(ws, device="ws-dev", token=TEST_DEVICE_TOKEN, **extra):
    ws.send_text(json.dumps({"t": "hello", "device": device, "token": token,
                             "cue_version": cues.CUE_VERSION, "fw": "t", "accept": "audio/wav;codec=ima_adpcm",
                             **extra}))


def _hello_debug(ws, device="ws-dev"):
    _hello(ws, device, debug=True)  # khung debug chỉ dành cho trang demo


def _send_turn(ws, turn, end=True):
    ws.send_text(json.dumps({"t": "turn_start", "turn": turn, "t_press_ms": 0}))
    for chunk in _adpcm_chunks():
        ws.send_bytes(b"\x03" + chunk)
    if end:
        ws.send_text(json.dumps({"t": "turn_end", "turn": turn, "t_release_ms": 0}))


def _recv_until_end(ws, turn):
    """-> (khung reply, số byte audio 0x02, thứ tự 'reply' < audio < 'reply_end')."""
    reply, audio, order = None, 0, []
    while True:
        msg = ws.receive()
        assert msg["type"] == "websocket.send", msg
        if msg.get("bytes") is not None:
            assert msg["bytes"][0] == 0x02
            audio += len(msg["bytes"]) - 1
            order.append("audio")
            continue
        frame = json.loads(msg["text"])
        if frame["t"] == "reply":
            reply = frame
            order.append("reply")
        elif frame["t"] == "end":
            raise AssertionError("live bị kết thúc ngoài ý muốn")
        elif frame["t"] == "reply_end":
            assert frame["turn"] == turn
            order.append("end")
            return reply, audio, order


def _chat(world):  # noqa: F811
    rec, labels, _ = world
    rec.text = "KỂ CHUYỆN CƯỜI ĐI"
    labels["kể chuyện cười đi"] = clef.ClefResult("chat", 0.9)


def test_bad_token_closes_4401(world):  # noqa: F811
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, token="sai-token")
        msg = ws.receive()
        assert msg["type"] == "websocket.close" and msg["code"] == 4401


def test_turn_roundtrip_chat(world):  # noqa: F811
    _chat(world)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws)
        ok = json.loads(ws.receive_text())
        assert ok["t"] == "hello_ok" and ok["ping_s"] == 25 and ok["session"]
        _send_turn(ws, "t1")
        reply, audio, order = _recv_until_end(ws, "t1")
        assert reply["turn"] == "t1" and reply["audio"]["sample_rate"] == 16000
        assert audio > 1000 and order[0] == "reply" and order[-1] == "end"
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}


def _sync(ws):
    """ping/pong: mọi khung gửi trước đó đã được server xử lý xong."""
    ws.send_text('{"t":"ping"}')
    while True:
        msg = ws.receive()
        if msg.get("text") and json.loads(msg["text"]) == {"t": "pong"}:
            return


@pytest.fixture
def cancelled_turns(monkeypatch):
    """Ghi lại các lượt bị huỷ giữa chừng trong turn.run (CancelledError)."""
    import asyncio

    from live import device_session

    seen = []
    original = device_session.turn_v2.run

    async def spy(device, turn_id, *args, **kwargs):
        try:
            return await original(device, turn_id, *args, **kwargs)
        except asyncio.CancelledError:
            seen.append(turn_id)
            raise

    monkeypatch.setattr(device_session.turn_v2, "run", spy)
    return seen


def test_new_turn_cancels_previous(world, cancelled_turns):  # noqa: F811
    _chat(world)
    fired = []
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-cancel")
        ws.receive_text()
        _send_turn(ws, "A", end=False)  # lượt A còn dở, chưa nhả nút
        _sync(ws)  # A đã begin_turn xong
        pending_action.schedule("ws-cancel", 30, lambda: fired.append(1), "gọi mẹ",
                                gen=pending_action.generation("ws-cancel"))
        _send_turn(ws, "B")  # chỉ lượt B mới được huỷ lệnh chờ
        reply, audio, _ = _recv_until_end(ws, "B")
        assert reply["turn"] == "B" and audio > 1000
        assert cancelled_turns == ["A"]
        assert not pending_action.cancel("ws-cancel", "kiểm")  # đã bị huỷ từ trước
    assert fired == []


def test_new_session_replaces_old(world, cancelled_turns):  # noqa: F811
    _chat(world)
    fired = []
    with client.websocket_connect("/v2/session") as old:
        _hello(old, device="ws-replace")
        old.receive_text()
        _send_turn(old, "A", end=False)
        _sync(old)
        pending_action.schedule("ws-replace", 30, lambda: fired.append(1), "gọi mẹ",
                                gen=pending_action.generation("ws-replace"))
        gen_before = pending_action.generation("ws-replace")
        with client.websocket_connect("/v2/session") as new:
            _hello(new, device="ws-replace")
            assert json.loads(new.receive_text())["t"] == "hello_ok"
            # Phiên mới chưa gửi lượt nào: chính việc thay phiên phải huỷ lệnh chờ + lượt A.
            assert pending_action.generation("ws-replace") > gen_before
            assert fired == [] and not pending_action.cancel("ws-replace", "kiểm")
            assert cancelled_turns == ["A"]
            msg = old.receive()
            assert msg["type"] == "websocket.close" and msg["code"] == 4000
            _send_turn(new, "B")
            reply, _, _ = _recv_until_end(new, "B")
            assert reply["turn"] == "B"
    assert fired == []


def test_nav_live_survives_new_chat_turn(world):  # noqa: F811
    from live.session import sessions

    rec, labels, _ = world
    rec.text = "BẬT CẢNH BÁO"
    labels["bật cảnh báo"] = clef.ClefResult("alert_on", 0.9)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-nav")
        ws.receive_text()
        _send_turn(ws, "N")
        reply, _, _ = _recv_until_end(ws, "N")
        assert reply["live"] == "nav"
        assert json.loads(ws.receive_text())["t"] == "cam"
        assert sessions.active("ws-nav") is not None
        _chat(world)
        _send_turn(ws, "C")
        reply, audio, _ = _recv_until_end(ws, "C")  # `end` của nav mà chen vào sẽ làm vỡ assert này
        assert reply["turn"] == "C" and audio > 1000
        assert sessions.active("ws-nav") is not None  # nav vẫn chạy sau lượt chat


def _recv_result_reply(ws):
    """Đọc tới khi gặp một lượt `result-*` hoàn chỉnh -> (khung reply, số byte audio, thứ tự khung)."""
    reply, audio, order = None, 0, []
    while True:
        msg = ws.receive()
        if msg.get("bytes") is not None:
            audio += len(msg["bytes"]) - 1
            order.append("audio")
            continue
        frame = json.loads(msg["text"])
        if frame["t"] == "reply":
            reply = frame
            order.append("reply")
        elif frame["t"] == "reply_end":
            order.append("end")
            if str(frame["turn"]).startswith("result-"):
                return reply, audio, order


def test_lane_d_result_is_pushed_as_server_reply(world, monkeypatch):  # noqa: F811
    """Kết quả điện thoại (vd. MULTIPLE_CONTACTS_FOUND) được đọc cho kính qua khung reply `result-<id>`."""
    from lanes import phone
    from pipeline import device_ctx

    rec, labels, _ = world
    rec.text = "GỌI CHO NAM"
    labels["gọi cho nam"] = _gemma("contact_call")

    def handler(image, text, params=None):
        device_ctx.action_request.set("req-42")
        yield "Đang gọi cho Nam.\n"  # câu xác nhận: làn D đã đọc lại rồi, không đọc lần nữa
        yield "Có nhiều người trùng tên trong danh bạ, vui lòng nói rõ hơn."

    monkeypatch.setitem(phone.HANDLERS, "contact_call", handler)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-result")
        ws.receive_text()
        _send_turn(ws, "D1")
        reply, _, _ = _recv_until_end(ws, "D1")  # câu đọc lại
        assert reply["turn"] == "D1"
        res, audio, order = _recv_result_reply(ws)  # lệnh chạy sau cửa sổ đọc lại, kết quả đẩy xuống
        assert res["turn"] == "result-req-42" and res["audio"]["sample_rate"] == 16000
        assert audio > 500 and order[0] == "reply" and order[-1] == "end"
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}  # không còn khung result nào kèm theo


def _silent_turn(world):  # noqa: F811
    world[0].text = ""


def test_button_press_without_speech_stops_music_but_speech_is_classified(world):  # noqa: F811
    from handlers import action_flow
    from pipeline import device_ctx

    rec, labels, calls = world
    with device_ctx.use("ws-btn"):
        action_flow.mark_active("music_playing")
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-btn")
        ws.receive_text()
        # Có lời: "tăng âm lượng" lúc nhạc đang phát là music_volume, KHÔNG phải dừng nhạc.
        rec.text = "TĂNG ÂM LƯỢNG LÊN"
        labels["tăng âm lượng lên"] = _gemma("music_volume")
        _send_turn(ws, "V")
        _recv_until_end(ws, "V")
        assert [n for n, _ in calls["actions"]] == ["music_volume"]
        # Chỉ bấm nút (không lời): dừng nhạc như cũ.
        _silent_turn(world)
        _send_turn(ws, "S")
        _recv_until_end(ws, "S")
        assert [n for n, _ in calls["actions"]] == ["music_volume", "music_stop"]


def test_button_stop_navigation_keeps_obstacle_live(world):  # noqa: F811
    from handlers import action_flow
    from live.session import sessions
    from pipeline import device_ctx

    rec, labels, calls = world
    rec.text = "BẬT CẢNH BÁO"
    labels["bật cảnh báo"] = clef.ClefResult("alert_on", 0.9)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-navbtn")
        ws.receive_text()
        _send_turn(ws, "N")
        reply, _, _ = _recv_until_end(ws, "N")
        assert reply["live"] == "nav" and json.loads(ws.receive_text())["t"] == "cam"
        assert sessions.active("ws-navbtn") is not None
        with device_ctx.use("ws-navbtn"):
            action_flow.mark_active("navigating")  # ĐT đang dẫn đường
        _silent_turn(world)
        ws.send_text(json.dumps({"t": "turn_start", "turn": "B", "t_press_ms": 0}))
        ws.send_text(json.dumps({"t": "turn_end", "turn": "B", "t_release_ms": 0}))
        _recv_until_end(ws, "B")  # khung `end` của live nav mà tới thì hàm này ném lỗi
        assert sessions.active("ws-navbtn") is not None  # dừng chỉ đường không tắt cảnh báo vật cản
        assert ("navigation_stop" in [n for n, _ in calls["actions"]]) or ("nav_stop" in [n for n, _ in calls["actions"]])


# ── Đợt sửa cuối plan 1 ───────────────────────────────────────────────────────

def test_lane_d_command_waits_for_readback_audio_to_reach_the_glasses(world, monkeypatch):  # noqa: F811
    """C1/I1: cửa sổ huỷ đếm từ khối audio đọc lại ĐẦU TIÊN gửi tới kính, không phải từ `route()`.

    TTS chậm 0,8 s: nếu đồng hồ chạy từ route() (delay 0,4 s) lệnh nổ TRƯỚC khi kính nghe được gì."""
    from lanes import phone
    from pipeline import tts

    rec, labels, _ = world
    rec.text = "GỌI CHO NAM"
    labels["gọi cho nam"] = _gemma("contact_call")
    monkeypatch.setattr(pending_action, "readback_delay", lambda text: 0.0)
    monkeypatch.setattr(config, "ACTION_TTS_LEAD_S", 0.4)
    fired = []
    monkeypatch.setattr(phone, "run_background",
                        lambda *a, **k: fired.append(time.monotonic()))

    def slow_pcm(text):
        time.sleep(0.8)  # TTS dựng mảnh đầu chậm (GPU dùng chung, Task 16: 3-5 s)
        yield b"\x10\x00" * 8000

    monkeypatch.setattr(tts, "synthesize_stream", slow_pcm)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-c1")
        ws.receive_text()
        _send_turn(ws, "R")
        first_audio = None
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None and first_audio is None:
                first_audio = time.monotonic()
                assert fired == []  # audio đọc lại vừa tới kính, lệnh chưa nổ
            elif msg.get("text") and json.loads(msg["text"])["t"] == "reply_end":
                break
        end = time.monotonic() + 3
        while not fired and time.monotonic() < end:
            time.sleep(0.02)
    assert fired, "lệnh phải chạy sau cửa sổ huỷ"
    assert fired[0] - first_audio >= 0.3  # >= lead 0,4 s trừ độ lệch đồng hồ nhận


def test_nav_outbox_and_turn_reply_never_interleave_on_the_audio_channel(world, monkeypatch):  # noqa: F811
    """I4: câu của outbox nav live và audio lượt trả lời đi tuần tự (một kênh 0x02 có thứ tự)."""
    from live.session import sessions

    rec, labels, _ = world
    rec.text = "BẬT CẢNH BÁO"
    labels["bật cảnh báo"] = clef.ClefResult("alert_on", 0.9)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-i4")
        ws.receive_text()
        _send_turn(ws, "N")
        assert _recv_until_end(ws, "N")[0]["live"] == "nav"
        assert json.loads(ws.receive_text())["t"] == "cam"
        _chat(world)
        _send_turn(ws, "C0")  # đo số khối audio của MỘT lượt chat đứng một mình
        _, alone, _ = _recv_until_end(ws, "C0")
        # câu nav đang xếp hàng ngay trước lượt chat tiếp theo
        sessions.active("ws-i4").outbox.put("Đã mở lộ trình trên điện thoại.")
        _send_turn(ws, "C1")
        frames, in_window, outside = [], 0, 0
        inside = False
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                if inside:
                    in_window += len(msg["bytes"]) - 1
                else:
                    outside += 1
                continue
            frame = json.loads(msg["text"])
            if frame["t"] == "reply" and frame["turn"] == "C1":
                inside = True
            elif frame["t"] == "reply_end" and frame["turn"] == "C1":
                break
        # Trong khung reply..reply_end chỉ có audio của lượt C1 (không lẫn câu nav).
        assert in_window == alone
        time.sleep(1.0)  # câu nav (nếu chưa đọc) đọc xong sau, trọn câu
        ws.send_text('{"t":"ping"}')
        while True:
            msg = ws.receive()
            if msg.get("bytes") is not None:
                outside += 1
            elif json.loads(msg["text"]) == {"t": "pong"}:
                break
        assert outside >= 1  # câu nav có được đọc, không bị nuốt


def test_ocr_live_does_not_kill_nav_alerts_for_good(world):  # noqa: F811
    """I5: OCR live giữa lúc chỉ đường thay nav live tạm thời; OCR xong thì nav live được dựng lại."""
    from live.session import sessions
    from tests.test_v2_api import _jpeg

    rec, labels, _ = world
    rec.text = "BẬT CẢNH BÁO"
    labels["bật cảnh báo"] = clef.ClefResult("alert_on", 0.9)
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-i5")
        ws.receive_text()
        _send_turn(ws, "N")
        assert _recv_until_end(ws, "N")[0]["live"] == "nav"
        assert json.loads(ws.receive_text())["t"] == "cam"
        assert sessions.active("ws-i5").mode == "nav"

        rec.text = "ĐỌC GIÚP TÔI TRANG SÁCH NÀY"
        labels["đọc giúp tôi trang sách này"] = clef.ClefResult("ocr", 0.9, "read")
        ws.send_text(json.dumps({"t": "turn_start", "turn": "O", "t_press_ms": 0}))
        ws.send_bytes(b"\x01" + _jpeg(1600, 1200))  # trắng trơn: ảnh buffer không đạt -> OCR live
        for chunk in _adpcm_chunks():
            ws.send_bytes(b"\x03" + chunk)
        ws.send_text(json.dumps({"t": "turn_end", "turn": "O", "t_release_ms": 0}))
        reply, _, _ = _recv_until_end(ws, "O")
        assert reply["live"] == "ocr"
        end = time.monotonic() + 3
        while time.monotonic() < end and (sessions.active("ws-i5") or object()).__dict__.get("mode") != "ocr":
            time.sleep(0.02)
        assert sessions.active("ws-i5").mode == "ocr"  # nav đã nhường chỗ

        _chat(world)  # lượt mới huỷ OCR live -> nav phải sống lại
        _send_turn(ws, "C")
        seen_cam = False
        for _ in range(400):
            msg = ws.receive()
            if msg.get("text"):
                frame = json.loads(msg["text"])
                seen_cam = seen_cam or (frame["t"] == "cam" and frame.get("size") == "qvga")
                if frame["t"] == "reply_end" and frame["turn"] == "C":
                    break
        end = time.monotonic() + 3
        while time.monotonic() < end and not (sessions.active("ws-i5") and sessions.active("ws-i5").mode == "nav"):
            time.sleep(0.02)
        assert sessions.active("ws-i5") is not None and sessions.active("ws-i5").mode == "nav"
        if not seen_cam:  # cam của nav có thể tới sau reply_end
            _sync(ws)


def test_oversized_ws_frame_is_rejected_not_buffered(world):  # noqa: F811
    with client.websocket_connect("/v2/session") as ws:
        _hello(ws, device="ws-big")
        ws.receive_text()
        ws.send_bytes(b"\x04" + b"\x00" * (config.WS_MAX_FRAME_BYTES + 10))
        assert json.loads(ws.receive_text()) == {"t": "error", "code": "too_large"}
        ws.send_text('{"t":"ping"}')
        assert json.loads(ws.receive_text()) == {"t": "pong"}
