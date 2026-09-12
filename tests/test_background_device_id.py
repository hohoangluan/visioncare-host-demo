"""Luồng nền gọi app server bằng device_id NÀO.

Bối cảnh (đo được 2026-08-26, server app chạy thật trên 8001):

    POST /api/v1/service/location/get  ->  404
    GLASSES_DEVICE_NOT_LINKED  details: {"device_id": "glasses-123"}

`services/visioncare_client.call_service_api()` lấy `device_id` theo thứ tự:
`app.DEVICE_ID_CTX` của request hiện tại, rồi rơi về `config.VISIONCARE_DEVICE_ID`.
Luồng nền lấy vị trí (`handlers/chat._location_refresh_loop`) chạy NGOÀI mọi
request nên ContextVar rỗng, và nó rơi về hằng số giữ chỗ `"glasses-123"` —
một chuỗi chưa từng ứng với chiếc kính nào đang chạy. Hậu quả: vòng làm mới vị
trí ở nền **không bao giờ** lấy được toạ độ, trong khi cùng lúc đó
`glasses-01` hỏi thẳng thì app trả về toạ độ trong dưới 2 giây.

Chữa bằng cách chèn một bậc NỮA giữa hai bậc cũ: sổ `device_registry` biết
chiếc kính nào vừa gọi tới. Hằng số vẫn còn, nhưng lùi xuống bậc cuối.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

import config
from services import visioncare_client
from services.device_registry import DeviceRegistry, devices


@pytest.fixture(autouse=True)
def _clean_registry():
    devices.clear()
    yield
    devices.clear()


# ─── sổ thiết bị: ai là kính "đang dùng" ──────────────────────────────────


def test_registry_has_no_current_device_when_nothing_called_yet():
    """Server vừa khởi động, chưa kính nào gọi tới: không được bịa ra một cái."""
    assert DeviceRegistry().current_device_id() is None


def test_registry_picks_the_glasses_that_called_most_recently():
    registry = DeviceRegistry()
    registry.seen("glasses-01")
    registry.seen("glasses-02")
    assert registry.current_device_id() == "glasses-02"


def test_registry_ignores_glasses_that_went_quiet():
    """Kính tắt từ hôm qua không được kéo vòng nền đi hỏi vị trí hộ nó.

    Cửa sổ online là `DEVICE_ONLINE_WINDOW_SECONDS`; quá hạn thì coi như
    không có ai, và người gọi rơi tiếp xuống bậc dưới.
    """
    registry = DeviceRegistry(online_window_seconds=30.0)
    registry.seen("glasses-01")
    record = registry.get("glasses-01")
    assert record is not None
    record.last_seen = time.monotonic() - 3600.0
    assert registry.current_device_id() is None


def test_registry_prefers_an_online_device_over_a_stale_one():
    registry = DeviceRegistry(online_window_seconds=30.0)
    registry.seen("glasses-cu")
    registry.seen("glasses-moi")
    stale = registry.get("glasses-moi")
    assert stale is not None
    stale.last_seen = time.monotonic() - 3600.0
    assert registry.current_device_id() == "glasses-cu"


# ─── client: bậc rơi khi không có request nào đang chạy ───────────────────


def _mock_client(monkeypatch, captured: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(202, json={
            "status": "ok",
            "data": {
                "request_id": "req-nen",
                "operation": "location_get",
                "request_state": "processing",
            },
        })

    monkeypatch.setattr(
        visioncare_client, "_CLIENT",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_background_call_uses_the_glasses_that_is_actually_running(monkeypatch):
    """🔴 Ca sinh ra file này. Không có request nào đang chạy, nhưng kính vừa
    bấm nút xong — hỏi app bằng ĐÚNG chiếc kính đó, không phải hằng số."""
    captured: dict = {}
    _mock_client(monkeypatch, captured)
    devices.seen("glasses-01")

    visioncare_client.call_service_api("api/v1/service/location/get", {})

    assert captured["body"]["device_id"] == "glasses-01"
    assert captured["body"]["device_id"] != config.VISIONCARE_DEVICE_ID


def test_background_call_falls_back_to_the_constant_when_no_glasses_seen(monkeypatch):
    """Sổ rỗng (server vừa restart) thì hằng số vẫn là bậc cuối, không phải lỗi."""
    captured: dict = {}
    _mock_client(monkeypatch, captured)

    visioncare_client.call_service_api("api/v1/service/location/get", {})

    assert captured["body"]["device_id"] == config.VISIONCARE_DEVICE_ID


def test_explicit_device_id_in_payload_still_wins(monkeypatch):
    """Người gọi đã nói rõ hỏi hộ kính nào thì sổ không được ghi đè."""
    captured: dict = {}
    _mock_client(monkeypatch, captured)
    devices.seen("glasses-01")

    visioncare_client.call_service_api(
        "api/v1/service/location/get", {"device_id": "glasses-09"}
    )

    assert captured["body"]["device_id"] == "glasses-09"


def test_request_context_still_wins_over_the_registry(monkeypatch):
    """Bậc cũ không được đổi thứ tự: đang phục vụ kính A thì hỏi hộ kính A,
    kể cả khi kính B vừa gọi tới sau đó một mili giây."""
    import app as app_module

    captured: dict = {}
    _mock_client(monkeypatch, captured)
    devices.seen("glasses-02")

    token = app_module.DEVICE_ID_CTX.set("glasses-01")
    try:
        visioncare_client.call_service_api("api/v1/service/location/get", {})
    finally:
        app_module.DEVICE_ID_CTX.reset(token)

    assert captured["body"]["device_id"] == "glasses-01"
