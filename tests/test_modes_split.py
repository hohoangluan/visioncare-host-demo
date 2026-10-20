"""Tách dẫn đường (điện thoại, Google Maps) khỏi cảnh báo vật cản (live nav qua WS)."""

import json
import time

from fastapi.testclient import TestClient

import config
from app import app
from live import hazard
from live.session import sessions
from models import clef
from pipeline import intent_early
from tests.test_v2_api import _gemma, _jpeg, _turn, world  # noqa: F401 (fixture)

client = TestClient(app)
DEV = "aa:bb"  # X-Device-Id của tests.test_v2_api.TOKEN_HEADERS


def _wait_actions(calls, n=1, timeout=8.0):
    """Câu đọc lại của nav_start dài hơn nên cửa sổ huỷ cũng dài hơn (~3,5 s)."""
    end = time.monotonic() + timeout
    while len(calls["actions"]) < n and time.monotonic() < end:
        time.sleep(0.02)


def test_lane_table_splits_navigation_from_obstacle_alert():
    assert intent_early.LANE["nav_start"] == "D" and intent_early.LANE["nav_stop"] == "D"
    assert intent_early.LANE["alert_on"] == "C" and intent_early.LANE["alert_off"] == "C"


def test_nav_start_does_not_start_live(world):  # noqa: F811
    rec, labels, calls = world
    rec.text = "DẪN TÔI TỚI CHỢ BẾN THÀNH"
    labels["dẫn tôi tới chợ bến thành"] = _gemma("nav_start")
    r = _turn("n1")
    assert "x-live" not in r.headers and "x-live-token" not in r.headers
    assert r.headers.get("x-cue") != "nav_alert_on"
    assert sessions.active(DEV) is None
    _wait_actions(calls)
    assert calls["actions"] == [("nav_start", {"destination": "chợ Bến Thành"})]


def test_nav_start_without_destination_asks_then_confirms_without_live(world):  # noqa: F811
    from models import llm

    rec, labels, calls = world
    rec.text = "DẪN ĐƯỜNG"
    labels["dẫn đường"] = _gemma("nav_start")

    async def empty(prompt, schema, max_tokens=120):
        return {"destination": ""}

    saved = llm.generate_json
    llm.generate_json = empty
    try:
        r = _turn("n2")
    finally:
        llm.generate_json = saved
    assert r.headers["x-cue"] == "ask_destination" and calls["actions"] == []
    rec.text = "CHỢ BẾN THÀNH"
    labels["chợ bến thành"] = clef.ClefResult("chat", 0.6)
    r = _turn("n2b")  # câu điền chỗ trống không đủ tin -> hỏi lại
    assert "x-live" not in r.headers and calls["actions"] == []
    rec.text = "ĐÚNG"
    labels["đúng"] = clef.ClefResult("chat", 0.9)
    r = _turn("n2c")
    assert "x-live" not in r.headers
    _wait_actions(calls)
    assert calls["actions"] == [("nav_start", {"destination": "Chợ bến thành"})]


def test_nav_stop_keeps_obstacle_mode(world):  # noqa: F811
    rec, labels, calls = world
    session = sessions.claim(sessions.create(DEV, "nav").token)  # live nav đang chạy
    rec.text = "DỪNG CHỈ ĐƯỜNG"
    labels["dừng chỉ đường"] = clef.ClefResult("nav_stop", 0.9)
    _turn("n3")
    _wait_actions(calls)
    assert [n for n, _ in calls["actions"]] == ["nav_stop"]
    assert sessions.active(DEV) is session  # live nav còn nguyên


def test_alert_on_off_still_drive_live_nav(world):  # noqa: F811
    rec, labels, _ = world
    rec.text = "BẬT CẢNH BÁO"
    labels["bật cảnh báo"] = clef.ClefResult("alert_on", 0.9)
    r = _turn("n4")
    assert r.headers["x-cue"] == "nav_alert_on" and r.headers["x-live"] == "nav"
    assert sessions.claim(r.headers["x-live-token"]) is not None
    assert sessions.active(DEV) is not None
    rec.text = "TẮT CẢNH BÁO"
    labels["tắt cảnh báo"] = clef.ClefResult("alert_off", 0.9)
    r = _turn("n5")
    assert r.headers["x-cue"] == "nav_alert_off"
    assert sessions.active(DEV) is None


def test_nav_phrases():
    from handlers import navigation, result_speech

    assert navigation._START_ACK == "Đang gửi chỉ đường về điện thoại."
    ok = {"destination": {"address": "chợ Bến Thành"}}
    assert result_speech._success_speech("navigation_start", ok) == (
        "Đã gửi chỉ đường tới chợ Bến Thành về điện thoại. Mở thông báo để đi bằng Google Maps."
    )
    assert result_speech._success_speech("navigation_start", {}) == (
        "Đã gửi chỉ đường về điện thoại. Mở thông báo để đi bằng Google Maps."
    )


def test_navigation_speech_never_says_phone_opens_the_map():
    """Dẫn đường chỉ GỬI lộ trình về điện thoại (người dùng tự chạm thông báo): không câu cố định nào nói ĐT tự mở bản đồ."""
    from handlers import navigation

    assert all("mở bản đồ" not in s for s in navigation.STATIC_SPEECH)
    assert navigation._STILL_SENDING in navigation.STATIC_SPEECH
    assert "gửi chỉ đường về điện thoại" in navigation._STILL_SENDING


def _live_hazards(monkeypatch, boxes):
    """Chạy một khung qua live nav với detector giả; trả các khung hazard nhận được."""
    class FakeYolo:
        def detect(self, bgr):
            return boxes

    monkeypatch.setattr(hazard, "detector", lambda: FakeYolo())
    session = sessions.create("aa:bb", "nav")
    frame = bytes([1]) + _jpeg(320, 240)
    got = []
    with client.websocket_connect(f"/v2/live?token={session.token}") as ws:
        ws.send_text(json.dumps({"t": "hello", "device": "aa:bb", "cue_version": 2}))
        assert json.loads(ws.receive_text())["t"] == "cam"
        for _ in range(4):  # level 1 cần giữ 2 khung liên tiếp mới qua AntiAnnoy
            ws.send_bytes(frame)
            time.sleep(0.15)
        session.closed.set()
        end = time.monotonic() + 3
        while time.monotonic() < end:
            msg = json.loads(ws.receive_text())
            if msg["t"] == "end":
                break
            if msg["t"] == "hazard":
                got.append(msg)
    return got


# Hộp ngoài lối đi (cx 0.15), diện tích ~0.03 -> mức 1
_LEVEL1 = [hazard.Detection("chair", "static", 0.9, (0.05, 0.4, 0.25, 0.55))]
# Xe máy giữa lối đi, to -> mức 3
_LEVEL3 = [hazard.Detection("motorbike", "vehicle", 0.9, (0.35, 0.2, 0.75, 0.95))]


def test_level1_not_sent_by_default(world, monkeypatch):  # noqa: F811
    assert config.HAZARD_MIN_LEVEL == 2
    assert hazard.level_of(_LEVEL1[0], False) == 1
    assert _live_hazards(monkeypatch, _LEVEL1) == []


def test_level1_sent_when_min_level_lowered(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "HAZARD_MIN_LEVEL", 1)
    got = _live_hazards(monkeypatch, _LEVEL1)
    assert got and got[0]["level"] == 1


def test_level3_still_sent_by_default(world, monkeypatch):  # noqa: F811
    got = _live_hazards(monkeypatch, _LEVEL3)
    assert got and got[0]["level"] == 3
