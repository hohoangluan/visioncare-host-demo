"""Kênh xuống: hộp thư + `GET /downlink`.

🔴 VIẾT LẠI 2026-08-26. File này TRƯỚC ĐÂY khoá kênh SSE `GET /events`:
`subscribe()` trả generator, `_payload()` bóc khung `data: ...\\n\\n`, và ba
test riêng cho "kênh ma" (`_prune_dead_locked`). Toàn bộ đã xoá cùng SSE.

Vì sao xoá — đo trên `glasses-01`: một phiên TLS ngốn 45 056 B RAM liền,
`/events` ngốn thêm 37 888 B, board chỉ có ~114 KB. Nó không giữ nổi cả hai
nên hy sinh `/events`, và `firmware_update` trả `pushed: 0` còn `wifi_config`
rơi vào hộp thư chết dù server đếm `subscribers: 1`.

Ba thứ file này khoá, theo thứ tự quan trọng:
  1. hộp thư KHÔNG đánh rơi sự kiện khi board đang bận (SSE thì có)
  2. `drain()` rút cạn và chỉ trả một lần
  3. `downlink_open` phản ánh lượt poll thật, không phản ánh việc có socket
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app import app
import config
from services.events_channel import EventHub, events


@pytest.fixture(autouse=True)
def _clear_events() -> None:
    events.clear()
    yield
    events.clear()


def _get(device_id: str | None) -> object:
    headers = {} if device_id is None else {"X-Device-Id": device_id}
    return TestClient(app).get("/downlink", headers=headers)


# ─── endpoint ──────────────────────────────────────────────────────────────


def test_downlink_requires_device_id() -> None:
    assert _get(None).status_code == 400


def test_downlink_rejects_blank_device_id() -> None:
    """Khoảng trắng không phải một `device_id`.

    Header rỗng đi qua Cloudflare thành chuỗi trắng chứ không biến mất, và một
    hộp thư mang khoá `"   "` sẽ nuốt sự kiện của mọi kính gửi thiếu header.
    """
    assert TestClient(app).get("/downlink", headers={"X-Device-Id": "   "}).status_code == 400


def test_downlink_empty_mailbox_returns_empty_list() -> None:
    """Hộp thư rỗng là 200 + danh sách rỗng, KHÔNG phải 204 và KHÔNG phải lỗi.

    Board poll 43 200 lượt mỗi ngày và tuyệt đại đa số là rỗng. Trả mã lạ ở
    ca thường gặp nhất nghĩa là firmware phải có nhánh riêng cho nó.
    """
    response = _get("glasses-01")
    assert response.status_code == 200
    assert response.json()["data"]["events"] == []


def test_downlink_returns_queued_events() -> None:
    events.firmware_update("glasses-01", "2026.08.26-ota23")
    response = _get("glasses-01")
    assert response.status_code == 200
    (event,) = response.json()["data"]["events"]
    assert event == {"type": "firmware_update", "version": "2026.08.26-ota23"}


def test_downlink_drains_so_a_second_poll_is_empty() -> None:
    """Không có ack: rút ra là xoá. Hai lượt poll không được nhận trùng.

    Nhận trùng nghĩa là kính phát lại câu "có cuộc gọi từ Mẹ" mỗi 2 giây.
    """
    events.call_incoming("glasses-01", {"display_name": "Mẹ"})
    assert len(_get("glasses-01").json()["data"]["events"]) == 1
    assert _get("glasses-01").json()["data"]["events"] == []


def test_downlink_returns_every_queued_event_in_one_poll() -> None:
    """Rút CẠN, không nhỏ giọt.

    Trả một sự kiện mỗi lượt thì bốn sự kiện xếp hàng mất 8 giây mới đi hết —
    và trong đó có thể có `call_incoming`.
    """
    events.call_incoming("glasses-01", {"display_name": "Mẹ"})
    events.call_ended("glasses-01")
    events.firmware_update("glasses-01", "v2")
    got = _get("glasses-01").json()["data"]["events"]
    assert [e["type"] for e in got] == ["call_incoming", "call_ended", "firmware_update"]


def test_downlink_preserves_order() -> None:
    """FIFO. `call_incoming` rồi `call_ended` đảo thứ tự nghĩa là kính báo có
    cuộc gọi SAU khi cuộc gọi đã tắt."""
    for version in ("v1", "v2", "v3"):
        events.firmware_update("glasses-01", version)
    got = _get("glasses-01").json()["data"]["events"]
    assert [e["version"] for e in got] == ["v1", "v2", "v3"]


def test_downlink_is_per_device_not_broadcast() -> None:
    events.call_incoming("glasses-01", {"display_name": "A"})
    events.call_incoming("glasses-02", {"display_name": "B"})
    got_1 = _get("glasses-01").json()["data"]["events"]
    got_2 = _get("glasses-02").json()["data"]["events"]
    assert [e["caller"]["display_name"] for e in got_1] == ["A"]
    assert [e["caller"]["display_name"] for e in got_2] == ["B"]


def test_downlink_is_not_cacheable() -> None:
    """🔴 Kênh này đi qua Cloudflare tunnel.

    Một lượt poll được cache nghĩa là board đọc mãi một hộp thư cũ — và triệu
    chứng nhìn từ ngoài là "lệnh không tới", giống hệt board mất mạng.
    """
    assert _get("glasses-01").headers["cache-control"] == "no-store"


def test_downlink_records_the_device_as_seen() -> None:
    """Lượt poll phải tính là "kính còn sống" cho `/devices`.

    Không tính thì một kính chỉ poll (chưa ai bấm nút) sẽ hiện là offline suốt.
    """
    from services.device_registry import devices as registry

    TestClient(app).get(
        "/downlink",
        headers={
            "X-Device-Id": "glasses-01",
            "X-Fw-Version": "2026.08.26-ota23",
            "X-Wifi-Ssid": "Thanh_Cuong_FI",
        },
    )
    record = registry.get("glasses-01")
    assert record is not None
    assert record.fw_version == "2026.08.26-ota23"
    assert record.wifi_ssid == "Thanh_Cuong_FI"
    assert registry.is_online("glasses-01") is True


def test_events_endpoint_is_gone() -> None:
    """SSE đã xoá — khoá tường minh để không ai thêm lại mà không đọc spec."""
    assert TestClient(app).get(
        "/events", headers={"X-Device-Id": "glasses-01"}
    ).status_code == 404


# ─── hộp thư ───────────────────────────────────────────────────────────────


def test_events_survive_while_the_board_is_busy() -> None:
    """🔴 ĐÂY LÀ LÝ DO THIẾT KẾ NÀY TỒN TẠI.

    Board CỐ Ý ngừng poll khi bận (đang `/process`, đang phát tiếng, đang
    OTA). Kênh SSE cũ mất sạch sự kiện trong khoảng đó — `eventStreamPause()`
    là một khoảng mù thật sự, ghi thẳng trong `event_stream.h` như một đánh
    đổi đã biết. Hộp thư thì không: nó không cần ai đang nối.
    """
    hub = EventHub()
    assert hub.queued_count("glasses-01") == 0
    hub.call_incoming("glasses-01", {"display_name": "Mẹ"})
    hub.firmware_update("glasses-01", "v9")
    assert hub.queued_count("glasses-01") == 2
    assert len(hub.drain("glasses-01")) == 2


def test_publish_returns_queue_depth_not_subscriber_count() -> None:
    """Giá trị trả về của `publish()` ĐỔI NGHĨA 2026-08-26.

    Trước: "số subscriber đã nhận" — 0 nghĩa là mất sự kiện.
    Sau:   "số sự kiện đang chờ" — luôn ≥ 1, không bao giờ nghĩa là mất.

    Khoá tường minh vì một chỗ gọi cũ còn kiểm `== 0` sẽ ÂM THẦM đúng mãi mãi.
    """
    hub = EventHub()
    assert hub.call_incoming("glasses-01", {"display_name": "A"}) == 1
    assert hub.call_ended("glasses-01") == 2


def test_mailbox_drops_oldest_when_full() -> None:
    """Board rớt mạng cả ngày không được làm RAM server phình vô hạn.

    Bỏ cái CŨ NHẤT, giữ cái mới: với `call_incoming` đó là lựa chọn đúng —
    chuông đang đổ bây giờ quan trọng hơn chuông đã tắt từ lâu.
    """
    hub = EventHub(queue_size=3)
    for index in range(6):
        hub.firmware_update("glasses-01", f"v{index}")
    assert hub.queued_count("glasses-01") == 3
    assert [e["version"] for e in hub.drain("glasses-01")] == ["v3", "v4", "v5"]


def test_drain_on_unknown_device_is_empty_not_an_error() -> None:
    """Một kính chưa từng gửi gì vẫn phải poll được — đó là lượt poll ĐẦU TIÊN
    của mọi kính vừa khởi động."""
    assert EventHub().drain("chua-tung-thay") == []


def test_drain_requires_device_id() -> None:
    with pytest.raises(ValueError):
        EventHub().drain("")


def test_publish_requires_device_id() -> None:
    with pytest.raises(ValueError):
        EventHub().publish("", {"type": "call_ended"})


def test_unknown_event_type_is_rejected_at_the_call_site() -> None:
    """Danh sách đóng, không phải gợi ý.

    Một loại gõ sai sẽ đi tới board rồi rơi vào im lặng — `onDeviceEvent()`
    không có nhánh cho nó. Bắt ở đây thì lỗi lộ ra ngay tại chỗ gọi sai.
    """
    with pytest.raises(ValueError):
        EventHub().publish("glasses-01", {"type": "khong-co-loai-nay"})


def test_frame_request_is_no_longer_a_valid_event_type() -> None:
    """F5 đã xoá 2026-08-26 — kèm theo cả loại sự kiện của nó.

    Khoá tường minh: thêm lại `frame_request` mà không đọc spec nghĩa là dựng
    lại vòng hỏi-đáp hai tầng ảnh mà quyết định #2 vừa gỡ.
    """
    with pytest.raises(ValueError):
        EventHub().publish("glasses-01", {"type": "frame_request", "turn_id": "t1"})
    assert not hasattr(EventHub(), "request_frame")


def test_ping_is_no_longer_a_valid_event_type() -> None:
    """`ping` là nhịp tim của SSE. Kênh poll không giữ kết nối nào để mà giữ."""
    with pytest.raises(ValueError):
        EventHub().publish("glasses-01", {"type": "ping"})


def test_two_devices_do_not_share_a_mailbox() -> None:
    hub = EventHub()
    hub.call_incoming("device-a", {"display_name": "A"})
    hub.call_incoming("device-b", {"display_name": "B"})
    assert hub.queued_count("device-a") == 1
    assert hub.queued_count("device-b") == 1
    hub.drain("device-a")
    assert hub.queued_count("device-b") == 1, "rút hộp thư A đã dọn cả hộp thư B"


def test_clear_wipes_mailboxes_and_poll_history() -> None:
    hub = EventHub()
    hub.call_ended("glasses-01")
    hub.drain("glasses-01")
    assert hub.downlink_open("glasses-01") is True
    hub.clear()
    assert hub.queued_count("glasses-01") == 0
    assert hub.downlink_open("glasses-01") is False


# ─── downlink_open ─────────────────────────────────────────────────────────


def test_downlink_open_is_false_before_the_first_poll() -> None:
    hub = EventHub()
    assert hub.downlink_open("glasses-01") is False
    assert hub.last_poll_age_seconds("glasses-01") is None


def test_downlink_open_is_true_right_after_a_poll() -> None:
    hub = EventHub()
    hub.drain("glasses-01")
    assert hub.downlink_open("glasses-01") is True
    assert hub.last_poll_age_seconds("glasses-01") < 1.0


def test_downlink_open_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quá `DOWNLINK_STALE_SECONDS` thì coi như kính không giữ kênh nữa."""
    import services.events_channel as module

    hub = EventHub(stale_seconds=10.0)
    at = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: at[0])

    hub.drain("glasses-01")
    at[0] = 1009.9
    assert hub.downlink_open("glasses-01") is True, "9.9 s < 10 s mà đã bị coi là chết"
    at[0] = 1010.1
    assert hub.downlink_open("glasses-01") is False


def test_downlink_open_is_per_device() -> None:
    hub = EventHub()
    hub.drain("glasses-01")
    assert hub.downlink_open("glasses-01") is True
    assert hub.downlink_open("glasses-02") is False


def test_downlink_open_on_blank_device_is_false_not_an_error() -> None:
    """`/devices` gọi hàm này với bất cứ chuỗi nào người dùng gõ vào app."""
    assert EventHub().downlink_open("") is False


def test_stale_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EventHub(stale_seconds=0)


def test_queue_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EventHub(queue_size=0)


def test_config_default_stale_window_covers_several_polls() -> None:
    """🔴 Bất biến số học, không phải sở thích.

    Board CỐ Ý ngừng poll khi bận, và một lượt hỏi-đáp dài chiếm 5-6 giây. Đặt
    cửa sổ sát nhịp poll nghĩa là mỗi lần người dùng bấm nút, kính bị đọc
    thành "mất tích" trong đúng lượt đó — và `/wifi/remote-config` trả 409.
    """
    assert config.DOWNLINK_STALE_SECONDS >= 4 * (config.DOWNLINK_POLL_HINT_MS / 1000.0)


def test_downlink_tells_the_board_the_expected_poll_interval() -> None:
    data = _get("glasses-01").json()["data"]
    assert data["poll_after_ms"] == config.DOWNLINK_POLL_HINT_MS


# ─── hình dạng từng loại sự kiện ───────────────────────────────────────────


def test_call_incoming_event_shape() -> None:
    hub = EventHub()
    caller = {"display_name": "Mẹ", "last_digits": "1234"}
    hub.call_incoming("device-a", caller)
    assert hub.drain("device-a") == [{"type": "call_incoming", "caller": caller}]


def test_call_incoming_copies_the_caller_dict() -> None:
    """Bên gọi sửa dict của nó sau đó không được sửa cả sự kiện đã xếp hàng."""
    hub = EventHub()
    caller = {"display_name": "Mẹ"}
    hub.call_incoming("device-a", caller)
    caller["display_name"] = "Bố"
    assert hub.drain("device-a")[0]["caller"] == {"display_name": "Mẹ"}


def test_firmware_update_carries_no_binary() -> None:
    """🔴 KHOÁ KIẾN TRÚC: sự kiện chỉ mang TÊN phiên bản.

    `url`/`size`/`sha256` nằm ở `GET /firmware/manifest`, nguồn sự thật duy
    nhất. Nhét chúng vào đây nghĩa là có hai nguồn, và chúng sẽ lệch nhau đúng
    vào lúc phát hành lại một bản đã sửa.
    """
    hub = EventHub()
    hub.firmware_update("device-a", "2026.08.26-ota23")
    (event,) = hub.drain("device-a")
    assert set(event) == {"type", "version"}


def test_firmware_update_requires_a_version() -> None:
    with pytest.raises(ValueError):
        EventHub().firmware_update("device-a", "")


def test_wifi_config_requires_an_ssid() -> None:
    with pytest.raises(ValueError):
        EventHub().wifi_config("device-a", "")


def test_wifi_config_allows_an_open_network() -> None:
    """Mạng không mật khẩu là hợp lệ — quán cà phê, sân bay."""
    hub = EventHub()
    hub.wifi_config("device-a", "Free_Wifi")
    assert hub.drain("device-a") == [
        {"type": "wifi_config", "ssid": "Free_Wifi", "password": ""}
    ]


# ─── không đụng vào lượt hỏi-đáp ───────────────────────────────────────────


def test_mailbox_survives_a_process_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Một lượt `/process` không được làm mất sự kiện đang chờ.

    Đây đúng là ca kênh SSE cũ hỏng: board `eventStreamPause()` trước khi bấm
    nút để nhường 45 KB RAM cho phiên TLS của `/process`, và mọi sự kiện tới
    trong khoảng đó biến mất.
    """
    events.call_incoming("device-a", {"display_name": "Mẹ"})
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "pcm_stream")
    with patch("pipeline.router.resolve_speech", return_value=iter(("ok",))), patch(
        "pipeline.tts.synthesize_text_stream",
        return_value=iter((b"\x00\x00" * 100,)),
    ):
        response = TestClient(app).post(
            "/process",
            files={"audio": ("a.wav", b"audio", "audio/wav")},
            headers={"X-Device-Id": "device-a", "X-Turn-Id": "turn-process"},
        )
    assert response.status_code == 200
    got = _get("device-a").json()["data"]["events"]
    assert [e["type"] for e in got] == ["call_incoming"]
