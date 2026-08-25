"""T25 — sổ ghép đôi phải sống sót qua một lần khởi động lại server.

🔴 Vì sao đây không phải một tiện nghi nhỏ.

Ghép đôi nằm trong RAM cho tới 2026-08-25. Mỗi lần khởi động lại server, mọi
chiếc kính về `paired_to: null`, và server app trả `404
GLASSES_DEVICE_NOT_LINKED` cho **emergency_call, contact_call, nav_*, music_*,
ride_***. Tức là **gọi cấp cứu không hoạt động** — im lặng, không cảnh báo, cho
tới khi có người ghép lại bằng tay.

Đo được cùng ngày: một phiên đo end-to-end mất trắng cột `action` của 9 chức
năng vì server vừa khởi động lại giữa chừng.
"""

from __future__ import annotations

import json

import config
from services.device_registry import DeviceRegistry


def test_pairing_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    first = DeviceRegistry()
    first.pair("glasses-01", "+84900000001")

    # "Khởi động lại": một registry hoàn toàn mới, không chia sẻ gì với cái cũ.
    second = DeviceRegistry()
    assert second.get("glasses-01") is None, "registry mới lại có sẵn dữ liệu?"
    assert second.load_pairings() == 1

    record = second.get("glasses-01")
    assert record is not None and record.paired_to == "+84900000001"


def test_only_the_pairing_is_persisted_not_the_volatile_fields(tmp_path, monkeypatch):
    """🔴 `fw_version`/`wifi_ssid` KHÔNG được xuống đĩa.

    Ghi chúng lại tạo ra ca "sổ nói kính đang chạy bản X" cho một chiếc kính
    đã tắt từ hôm qua — tệ hơn là không nhớ gì, vì OTA sẽ quyết định dựa trên
    một sự thật đã hết hạn. Cả ba trường đó tự phục hồi trong ĐÚNG một lượt
    bấm nút.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    first = DeviceRegistry()
    first.seen("glasses-01", fw_version="2026.08.25-ota12", wifi_ssid="UIT Public")
    first.pair("glasses-01", "+84900000001")

    on_disk = json.loads((tmp_path / "pairings.json").read_text(encoding="utf-8"))
    assert on_disk == {"glasses-01": "+84900000001"}

    second = DeviceRegistry()
    second.load_pairings()
    record = second.get("glasses-01")
    assert record.paired_to == "+84900000001"
    assert record.fw_version is None, "bản firmware cũ bị ghi xuống đĩa"
    assert record.wifi_ssid is None, "tên mạng cũ bị ghi xuống đĩa"


def test_a_corrupt_book_does_not_stop_the_server(tmp_path, monkeypatch):
    """File JSON cụt (mất điện lúc ghi dở) không được làm server chết lúc lên.

    Mất sổ ghép đôi đã đủ tệ; không khởi động được thì còn tệ hơn.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "pairings.json").write_text('{"glasses-01": "+849', encoding="utf-8")

    registry = DeviceRegistry()
    assert registry.load_pairings() == 0


def test_missing_book_is_normal_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path / "chua-ton-tai"))
    assert DeviceRegistry().load_pairings() == 0
