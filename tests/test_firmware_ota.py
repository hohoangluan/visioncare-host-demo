"""T25 — OTA kéo qua internet, sổ thiết bị, đổi Wi-Fi từ xa.

Ba nhóm ca, mỗi nhóm khoá lại một cách hỏng đã lường trước:

1. **Fail-closed.** Thư mục firmware không có `latest.json` thì KHÔNG phát
   hành gì, kể cả khi có file `.bin` nằm sẵn trong đó.
2. **Toàn vẹn.** `sha256` trong manifest phải là băm của đúng file được phục
   vụ ở `/firmware/bin` — kính đối chiếu digest TRƯỚC `Update.end()`, nên hai
   con số lệch nhau ở server là kính từ chối nạp và không ai biết vì sao.
3. **Không rơi nhầm thiết bị.** `/firmware/*` và `/internal/device/wifi` KHÔNG
   được rơi về `config.VISIONCARE_DEVICE_ID` khi thiếu `X-Device-Id` — rơi
   nhầm ở đây là đẩy firmware hoặc Wi-Fi của kính này xuống kính khác.
"""

from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from app import app
import config
from services.device_registry import DeviceRegistry, devices
from services.events_channel import events
from services.firmware import FirmwareRegistry, firmware


BIN = b"\xe9" + b"firmware-image-bytes" * 64


@pytest.fixture(autouse=True)
def _clean_state():
    devices.clear()
    events.clear()
    yield
    devices.clear()
    events.clear()


@pytest.fixture()
def firmware_dir(tmp_path, monkeypatch):
    """Kho firmware rỗng, tách hẳn khỏi thư mục thật của máy."""
    root = tmp_path / "firmware"
    root.mkdir()
    monkeypatch.setattr(firmware, "_root", root)
    monkeypatch.setattr(firmware, "_digest_cache", {})
    return root


def _release(root, version: str, payload: bytes = BIN) -> str:
    (root / f"{version}.bin").write_bytes(payload)
    (root / "latest.json").write_text(
        json.dumps({"version": version, "file": f"{version}.bin"}), encoding="utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _client() -> TestClient:
    return TestClient(app)


def _loopback_client() -> TestClient:
    """`/internal/*` chỉ nhận lời gọi từ loopback (`_require_internal_callback`).

    `TestClient(app)` khai địa chỉ là "testclient", không phải một IP, nên bị
    chặn ở 403 trước cả khi tới bước kiểm token. Cùng cách làm với
    `tests/test_incoming_call.py`.
    """
    return TestClient(app, client=("127.0.0.1", 12345))


def _board_headers(version: str = "2026.08.24-ota1", **extra) -> dict[str, str]:
    headers = {"X-Device-Id": "glasses-01", "X-Fw-Version": version}
    headers.update(extra)
    return headers


def _internal_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.VISIONCARE_CALLBACK_TOKEN}"}


# ─── 1. fail-closed ────────────────────────────────────────────────────────


def test_no_release_means_no_update(firmware_dir) -> None:
    response = _client().get("/firmware/manifest", headers=_board_headers())
    assert response.status_code == 200
    assert response.json() == {"update": False, "reason": "NO_RELEASE"}


def test_stray_bin_is_not_a_release(firmware_dir) -> None:
    """Một file .bin lạc vào thư mục KHÔNG tự trở thành bản phát hành."""
    (firmware_dir / "2026.09.01-wip.bin").write_bytes(BIN)
    body = _client().get("/firmware/manifest", headers=_board_headers()).json()
    assert body["update"] is False


def test_pointer_to_missing_file_is_no_release(firmware_dir) -> None:
    (firmware_dir / "latest.json").write_text(
        json.dumps({"version": "ghost", "file": "ghost.bin"}), encoding="utf-8"
    )
    assert _client().get("/firmware/manifest", headers=_board_headers()).json()["update"] is False


# ─── 2. manifest & toàn vẹn ────────────────────────────────────────────────


def test_manifest_offers_update_when_versions_differ(firmware_dir) -> None:
    digest = _release(firmware_dir, "2026.08.24-ota2")
    body = _client().get("/firmware/manifest", headers=_board_headers("2026.08.24-ota1")).json()
    assert body["update"] is True
    assert body["version"] == "2026.08.24-ota2"
    assert body["size"] == len(BIN)
    assert body["sha256"] == digest
    assert body["url"].startswith("/firmware/bin?version=")


def test_manifest_says_up_to_date_on_same_version(firmware_dir) -> None:
    _release(firmware_dir, "2026.08.24-ota2")
    body = _client().get("/firmware/manifest", headers=_board_headers("2026.08.24-ota2")).json()
    assert body["update"] is False
    assert body["reason"] == "UP_TO_DATE"


def test_downgrade_is_offered(firmware_dir) -> None:
    """Rollback phải chạy: so sánh bằng `!=`, không phải `>`.

    `FW_VERSION` là chuỗi ngày-tháng người viết đặt, không phải semver — mọi
    phép "lớn hơn" đều là đoán, và cái ta cần nhất là hạ cấp khi một bản phát
    hành hỏng.
    """
    _release(firmware_dir, "2026.08.24-ota1")
    body = _client().get("/firmware/manifest", headers=_board_headers("2026.08.24-ota9")).json()
    assert body["update"] is True
    assert body["version"] == "2026.08.24-ota1"


def test_binary_matches_manifest_digest(firmware_dir) -> None:
    digest = _release(firmware_dir, "2026.08.24-ota2")
    response = _client().get(
        "/firmware/bin", params={"version": "2026.08.24-ota2"}, headers=_board_headers()
    )
    assert response.status_code == 200
    assert response.content == BIN
    assert hashlib.sha256(response.content).hexdigest() == digest
    assert response.headers["x-firmware-sha256"] == digest


def test_unknown_version_is_404(firmware_dir) -> None:
    _release(firmware_dir, "2026.08.24-ota2")
    response = _client().get(
        "/firmware/bin", params={"version": "khong-co"}, headers=_board_headers()
    )
    assert response.status_code == 404


def test_registry_rehashes_after_file_changes(firmware_dir) -> None:
    """Băm có nhớ, nhưng khoá gồm mtime — sửa file là băm lại."""
    registry = FirmwareRegistry(firmware_dir)
    _release(firmware_dir, "v1", b"first")
    assert registry.latest().sha256 == hashlib.sha256(b"first").hexdigest()

    import os
    import time

    path = firmware_dir / "v1.bin"
    path.write_bytes(b"second-and-longer")
    os.utime(path, (time.time() + 1, time.time() + 1))
    assert registry.latest().sha256 == hashlib.sha256(b"second-and-longer").hexdigest()


# ─── 3. không rơi nhầm thiết bị ────────────────────────────────────────────


def test_manifest_requires_device_id(firmware_dir) -> None:
    assert _client().get("/firmware/manifest").status_code == 400


def test_binary_requires_device_id(firmware_dir) -> None:
    _release(firmware_dir, "2026.08.24-ota2")
    assert _client().get("/firmware/bin").status_code == 400


# ─── sổ thiết bị ───────────────────────────────────────────────────────────


def test_manifest_request_records_device(firmware_dir) -> None:
    _client().get(
        "/firmware/manifest",
        headers=_board_headers("2026.08.24-ota1", **{"X-Wifi-Ssid": "Redmi Note 14"}),
    )
    record = devices.get("glasses-01")
    assert record is not None
    assert record.serial == "01"
    assert record.fw_version == "2026.08.24-ota1"
    assert record.wifi_ssid == "Redmi Note 14"


def test_devices_endpoint_exposes_wifi_ssid(firmware_dir) -> None:
    """Người dùng phải thấy kính đang đăng ký mạng nào để còn cấp đúng mạng."""
    client = _client()
    client.get(
        "/firmware/manifest",
        headers=_board_headers(**{"X-Wifi-Ssid": "Redmi Note 14"}),
    )
    listed = client.get("/devices").json()["data"]["devices"]
    assert listed[0]["wifi_ssid"] == "Redmi Note 14"
    assert listed[0]["serial"] == "01"
    assert listed[0]["online"] is True


def test_serial_strips_glasses_prefix() -> None:
    registry = DeviceRegistry()
    assert registry.seen("glasses-01").serial == "01"
    assert registry.seen("laptop-test").serial == "laptop-test"


def test_pair_by_serial_before_glasses_ever_connects() -> None:
    """Gõ số in trên vỏ kính TRƯỚC khi bật kính là thứ tự tự nhiên nhất."""
    registry = DeviceRegistry()
    record = registry.pair("glasses-07", "+84900000000")
    assert record.paired_to == "+84900000000"
    assert registry.resolve_by_serial("07") is record


def test_reported_version_change_clears_pushed_marker() -> None:
    registry = DeviceRegistry()
    registry.seen("glasses-01", fw_version="v1")
    registry.mark_update_pushed("glasses-01", "v2")
    assert registry.get("glasses-01").update_pushed_for == "v2"
    registry.seen("glasses-01", fw_version="v2")
    assert registry.get("glasses-01").update_pushed_for is None


# ─── đẩy lệnh xuống kính ───────────────────────────────────────────────────


def test_firmware_push_sends_event_to_subscriber(firmware_dir) -> None:
    _release(firmware_dir, "2026.08.24-ota2")
    stream = events.subscribe("glasses-01")
    try:
        response = _loopback_client().post(
            "/internal/firmware/push",
            json={"device_id": "glasses-01"},
            headers=_internal_headers(),
        )
        assert response.status_code == 200
        payload = json.loads(next(stream)[6:-2])
        assert payload == {"type": "firmware_update", "version": "2026.08.24-ota2"}
    finally:
        stream.close()


def test_firmware_push_carries_no_binary(firmware_dir) -> None:
    """🔴 Khoá kiến trúc: 1.35 MB đi qua kênh SSE sẽ chặn `call_incoming`."""
    _release(firmware_dir, "2026.08.24-ota2")
    stream = events.subscribe("glasses-01")
    try:
        _loopback_client().post("/internal/firmware/push", json={}, headers=_internal_headers())
        events.firmware_update("glasses-01", "2026.08.24-ota2")
        chunk = next(stream)
        assert len(chunk) < 200
        assert "sha256" not in chunk and "url" not in chunk
    finally:
        stream.close()


def test_firmware_push_without_release_is_409(firmware_dir) -> None:
    response = _loopback_client().post("/internal/firmware/push", json={}, headers=_internal_headers())
    assert response.status_code == 409


def test_wifi_config_reaches_the_glasses() -> None:
    stream = events.subscribe("glasses-01")
    try:
        response = _loopback_client().post(
            "/internal/device/wifi",
            json={"device_id": "glasses-01", "ssid": "Nha Moi", "password": "12345678"},
            headers=_internal_headers(),
        )
        assert response.status_code == 200
        payload = json.loads(next(stream)[6:-2])
        assert payload["type"] == "wifi_config"
        assert payload["ssid"] == "Nha Moi"
    finally:
        stream.close()


def test_wifi_config_without_open_channel_is_409() -> None:
    """Kính đã mất mạng thì lối duy nhất là SoftAP trên chính kính.

    Trả 200 ở đây là nói dối: sự kiện rơi vào hư không, người dùng ngồi đợi
    một chiếc kính không bao giờ đổi mạng.
    """
    response = _loopback_client().post(
        "/internal/device/wifi",
        json={"device_id": "glasses-01", "ssid": "Nha Moi"},
        headers=_internal_headers(),
    )
    assert response.status_code == 409


def test_wifi_config_requires_ssid() -> None:
    response = _loopback_client().post(
        "/internal/device/wifi",
        json={"device_id": "glasses-01"},
        headers=_internal_headers(),
    )
    assert response.status_code == 422


def test_internal_endpoints_reject_missing_token() -> None:
    assert _loopback_client().post("/internal/firmware/push", json={}).status_code == 401
    assert _loopback_client().post("/internal/device/wifi", json={}).status_code == 401


def test_events_channel_rejects_unknown_event_type() -> None:
    with pytest.raises(ValueError):
        events.publish("glasses-01", {"type": "nap-firmware-luon-di"})
