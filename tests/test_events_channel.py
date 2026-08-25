from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app import app
import config
from services.events_channel import EventHub, events


def _payload(chunk: str) -> dict[str, object]:
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    return json.loads(chunk[6:-2])


@pytest.fixture(autouse=True)
def _clear_events() -> None:
    events.clear()
    yield
    events.clear()


def test_events_requires_device_id() -> None:
    assert TestClient(app).get("/events").status_code == 400


def test_events_per_device_not_broadcast() -> None:
    hub = EventHub(heartbeat_seconds=1)
    stream_a = hub.subscribe("device-a")
    stream_b = hub.subscribe("device-b")
    assert hub.request_frame("device-a", "turn-a") == 1
    assert _payload(next(stream_a))["turn_id"] == "turn-a"
    assert hub.queued_count("device-b") == 0
    stream_a.close()
    stream_b.close()


def test_heartbeat_sent() -> None:
    hub = EventHub(heartbeat_seconds=0.001)
    stream = hub.subscribe("device-a")
    assert _payload(next(stream)) == {"type": "ping"}
    stream.close()


def test_client_disconnect_detected() -> None:
    hub = EventHub(heartbeat_seconds=0.001)
    stream = hub.subscribe("device-a")
    assert hub.subscriber_count("device-a") == 1
    next(stream)  # start the streaming generator as a real connected client does
    stream.close()
    assert hub.subscriber_count("device-a") == 0


def test_events_do_not_queue_forever() -> None:
    hub = EventHub(queue_size=2)
    assert hub.request_frame("offline", "turn-1") == 0
    assert hub.queued_count("offline") == 0

    stream = hub.subscribe("device-a")
    for index in range(5):
        hub.request_frame("device-a", f"turn-{index}")
    assert hub.queued_count("device-a") == 2
    assert _payload(next(stream))["turn_id"] == "turn-3"
    assert _payload(next(stream))["turn_id"] == "turn-4"
    stream.close()


def test_frame_request_carries_turn_id() -> None:
    hub = EventHub()
    stream = hub.subscribe("device-a")
    hub.request_frame("device-a", "turn-1", tier="high")
    assert _payload(next(stream)) == {
        "type": "frame_request",
        "turn_id": "turn-1",
        "tier": "high",
    }
    stream.close()


def test_call_incoming_event_shape() -> None:
    hub = EventHub()
    stream = hub.subscribe("device-a")
    caller = {"display_name": "Mẹ", "last_digits": "1234"}
    hub.call_incoming("device-a", caller)
    assert _payload(next(stream)) == {"type": "call_incoming", "caller": caller}
    stream.close()


def test_reconnect_after_server_restart() -> None:
    first = EventHub()
    old_stream = first.subscribe("device-a")
    old_stream.close()

    restarted = EventHub()
    new_stream = restarted.subscribe("device-a")
    restarted.request_frame("device-a", "turn-after-restart")
    assert _payload(next(new_stream))["turn_id"] == "turn-after-restart"
    new_stream.close()


def test_two_devices_two_channels() -> None:
    hub = EventHub()
    stream_a = hub.subscribe("device-a")
    stream_b = hub.subscribe("device-b")
    assert hub.subscriber_count() == 2
    hub.call_incoming("device-a", {"display_name": "A"})
    hub.call_incoming("device-b", {"display_name": "B"})
    assert _payload(next(stream_a))["caller"] == {"display_name": "A"}
    assert _payload(next(stream_b))["caller"] == {"display_name": "B"}
    stream_a.close()
    stream_b.close()


def test_channel_survives_process_request(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = events.subscribe("device-a")
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
    events.request_frame("device-a", "turn-after-request")
    assert _payload(next(stream))["turn_id"] == "turn-after-request"
    stream.close()


# ─── kênh ma (2026-08-25) ──────────────────────────────────────────────────
def test_a_stalled_generator_is_pruned_so_events_reach_the_live_board():
    """🔴 Đo được trên board: `sse_subscribers` của một kính lên 3 và còn tăng.

    `subscribe()` chỉ gỡ đăng ký trong `finally:` của generator, mà generator
    đó là ĐỒNG BỘ và Starlette chạy nó trong threadpool — nó không phải lúc nào
    cũng đóng generator khi client biến mất. Mỗi lần kính rớt để lại một kênh
    ma, và `publish()` ghi sự kiện vào cả những cái ma đó.
    """
    import time as _time
    from services.events_channel import EventHub

    hub = EventHub(heartbeat_seconds=0.05, queue_size=4)

    ghost = hub.subscribe("glasses-01")
    next(ghost)                      # chạy tới `yield` đầu rồi NGHẼN ở đó
    assert hub.subscriber_count("glasses-01") == 1

    # Không ai tiêu thụ `ghost` nữa -> `_alive_at` của nó đứng yên.
    _time.sleep(0.05 * 3 + 0.05)

    live = hub.subscribe("glasses-01")
    next(live)
    assert hub.subscriber_count("glasses-01") == 2

    # Lần publish kế tiếp phải dọn con ma đi, và CHỈ còn kênh sống nhận.
    delivered = hub.publish("glasses-01", {"type": "hazard_watch", "action": "start"})
    assert delivered == 1, "sự kiện vẫn đi vào kênh ma"
    assert hub.subscriber_count("glasses-01") == 1
    assert "hazard_watch" in next(live)


def test_a_slow_but_live_board_is_not_pruned():
    """Một nhịp mạng xấu KHÔNG được bị coi là chết — hạn là 3 nhịp tim."""
    import time as _time
    from services.events_channel import EventHub

    hub = EventHub(heartbeat_seconds=0.2, queue_size=4)
    live = hub.subscribe("glasses-01")
    next(live)
    _time.sleep(0.2)                 # chậm hơn một nhịp, nhưng chưa tới ba

    assert hub.publish("glasses-01", {"type": "call_ended"}) == 1
    assert hub.subscriber_count("glasses-01") == 1
