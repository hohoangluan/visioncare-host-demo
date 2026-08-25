"""Sổ ghi các kính đã từng gọi tới — khoá bằng `device_id` của T01.

Vì sao có file này
------------------
Trước đây server chỉ biết `device_id` trong đúng lúc xử lý một request rồi
quên. Ba việc mới đòi hỏi phải nhớ giữa các request:

1. **Định tuyến sang điện thoại.** Mỗi yêu cầu từ kính mang `X-Device-Id`;
   app ghép đôi bằng chính chuỗi đó. Không có sổ này thì server không trả lời
   được câu "kính số 01 ứng với điện thoại nào" mà không đi hỏi server app.
2. **OTA.** Kính gửi kèm `X-Fw-Version` mỗi lượt (`api_client.cpp`). Nhờ vậy
   server biết cả đàn kính đang chạy bản nào **mà không tốn thêm một vòng
   hỏi nào** — và biết kính nào cần đẩy sự kiện `firmware_update`.
3. **Đổi mạng từ xa.** App gửi Wi-Fi mới xuống kính qua kênh `/events`; muốn
   biết có nên gửi hay không thì phải biết kính có đang mở kênh không.

Không phải cơ sở dữ liệu
------------------------
Sổ này nằm trong RAM và **mất khi server khởi động lại** — hoàn toàn đúng ý
định. Mọi trường ở đây đều tự phục hồi trong một lượt bấm nút (kính gọi lại
là ghi lại). Đưa nó xuống đĩa sẽ tạo ra ca "sổ nói kính đang chạy bản X" cho
một chiếc kính đã tắt từ hôm qua — tệ hơn là không nhớ gì.

Ghép đôi (`pair`) thì NGƯỢC LẠI, và từ 2026-08-25 nó **có xuống đĩa**
------------------------------------------------------------------------
Ghép đôi là thứ người dùng cấu hình một lần và mong nó còn đó. Giữ trong RAM
nghĩa là mỗi lần khởi động lại server, mọi chiếc kính lại `paired_to: null` —
và hậu quả không phải "hơi bất tiện": `emergency_call`, `contact_call`,
`nav_*`, `music_*`, `ride_*` đều trả `404 GLASSES_DEVICE_NOT_LINKED`. Tức là
**gọi cấp cứu không hoạt động** cho tới khi có người ghép lại bằng tay, và
không ai được báo là phải làm thế.

Đo được 2026-08-25: một phiên đo end-to-end mất trắng cột `action` của 9 chức
năng vì server vừa khởi động lại giữa chừng.

🔴 Chỉ `paired_to` xuống đĩa. `fw_version`/`wifi_ssid`/`last_seen` **vẫn ở
RAM và vẫn mất khi restart** — đúng ý định gốc: ghi chúng xuống đĩa sẽ tạo ra
ca "sổ nói kính đang chạy bản X" cho một chiếc kính đã tắt từ hôm qua, tệ hơn
là không nhớ gì. Ba trường đó tự phục hồi trong đúng một lượt bấm nút.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import tempfile
import threading
import time

import config

logger = logging.getLogger("blind_assist.devices")


@dataclass
class DeviceRecord:
    device_id: str
    fw_version: str | None = None
    # Tên mạng kính ĐANG dùng, lấy từ header `X-Wifi-Ssid` mỗi request. App
    # hiện lại cho người dùng: không thấy dòng này thì họ chỉ biết "kính không
    # nối được" mà không biết nó đang chờ mạng nào, và đoán mò là cách hỏng
    # lâu nhất. Kính chưa gọi tới lần nào thì None — đúng, vì lúc đó ta THẬT SỰ
    # không biết, và bịa ra một cái tên còn tệ hơn để trống.
    wifi_ssid: str | None = None
    last_seen: float = field(default_factory=time.monotonic)
    # Số điện thoại / user id mà app đã ghép với kính này. None = chưa ghép.
    paired_to: str | None = None
    # Bản firmware server ĐÃ bảo kính này cập nhật, để không đẩy lặp lại một
    # sự kiện `firmware_update` mỗi lần kính gọi. None = chưa bảo lần nào.
    update_pushed_for: str | None = None

    @property
    def serial(self) -> str:
        """Phần số người dùng đọc ra: `glasses-01` -> `01`.

        Firmware dựng `device_id` là `"glasses-" + số máy`
        (`src/net/device_identity.h`). Cắt tiền tố ở đây chứ không bắt app tự
        cắt: quy ước tên nằm ở một chỗ thì đổi nó chỉ phải sửa một chỗ.
        """
        prefix = "glasses-"
        if self.device_id.startswith(prefix):
            return self.device_id[len(prefix) :]
        return self.device_id


class DeviceRegistry:
    def __init__(self, *, online_window_seconds: float | None = None) -> None:
        self._online_window = (
            config.DEVICE_ONLINE_WINDOW_SECONDS
            if online_window_seconds is None
            else online_window_seconds
        )
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceRecord] = {}

    def seen(
        self,
        device_id: str,
        *,
        fw_version: str | None = None,
        wifi_ssid: str | None = None,
    ) -> DeviceRecord:
        """Ghi nhận một request từ kính. Gọi từ mọi endpoint kính chạm tới."""
        if not device_id:
            raise ValueError("device_id is required")
        now = time.monotonic()
        with self._lock:
            record = self._devices.get(device_id)
            if record is None:
                record = DeviceRecord(device_id=device_id)
                self._devices[device_id] = record
            record.last_seen = now
            if wifi_ssid:
                record.wifi_ssid = wifi_ssid
            if fw_version:
                # Kính vừa báo bản nó ĐANG chạy. Nếu khác bản ta từng bảo nó
                # cập nhật thì xoá dấu đã-đẩy: hoặc nó đã nạp xong (bản mới),
                # hoặc nó nạp trượt (bản cũ) — cả hai đều cần đánh giá lại.
                if record.fw_version != fw_version:
                    record.update_pushed_for = None
                record.fw_version = fw_version
            return record

    def get(self, device_id: str) -> DeviceRecord | None:
        with self._lock:
            return self._devices.get(device_id)

    def is_online(self, device_id: str) -> bool:
        record = self.get(device_id)
        if record is None:
            return False
        return (time.monotonic() - record.last_seen) <= self._online_window

    def pair(self, device_id: str, phone: str) -> DeviceRecord:
        """Ghép kính với một điện thoại. Kính chưa từng gọi tới cũng ghép được.

        Cho phép ghép trước là chủ ý: người dùng mở app và gõ số máy in trên
        vỏ kính TRƯỚC khi bật kính lên là thứ tự tự nhiên nhất.
        """
        if not device_id or not phone:
            raise ValueError("device_id and phone are required")
        with self._lock:
            record = self._devices.get(device_id)
            if record is None:
                record = DeviceRecord(device_id=device_id)
                self._devices[device_id] = record
            record.paired_to = phone
            self._save_pairings_locked()
            return record

    # ── sổ ghép đôi trên đĩa ──────────────────────────────────────────────
    def _pairings_path(self) -> str:
        return os.path.join(config.STORAGE_DIR, "pairings.json")

    def _save_pairings_locked(self) -> None:
        """Ghi `{device_id: phone}` xuống đĩa. PHẢI đang giữ `self._lock`.

        Ghi qua file tạm rồi `os.replace` — thao tác đó là nguyên tử trên cả
        Windows lẫn POSIX. Ghi thẳng vào file đích thì mất điện đúng lúc ghi
        dở sẽ để lại một file JSON cụt, và lần khởi động sau **không đọc được
        sổ ghép đôi nào cả** — tức mất `emergency_call` mà không ai biết vì
        sao.
        """
        data = {
            device_id: record.paired_to
            for device_id, record in self._devices.items()
            if record.paired_to
        }
        try:
            os.makedirs(config.STORAGE_DIR, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=config.STORAGE_DIR, prefix="pairings-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self._pairings_path())
        except OSError:
            # KHÔNG ném ra ngoài: ghép đôi vừa thành công trong RAM, và làm
            # hỏng request vì không ghi được đĩa là đổi một lỗi nhỏ lấy một
            # lỗi to. Nhưng phải kêu, vì lần restart sau sẽ mất.
            logger.exception(
                "Không ghi được sổ ghép đôi xuống %s — ghép đôi sẽ MẤT khi "
                "khởi động lại server",
                self._pairings_path(),
            )

    def load_pairings(self) -> int:
        """Đọc sổ ghép đôi từ đĩa. Gọi MỘT lần lúc khởi động.

        Trả về số cặp đọc được. File không tồn tại là chuyện bình thường (máy
        mới), không phải lỗi.
        """
        path = self._pairings_path()
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return 0
        except (OSError, ValueError):
            logger.exception("Sổ ghép đôi %s hỏng — bỏ qua, coi như chưa ghép", path)
            return 0

        if not isinstance(data, dict):
            logger.warning("Sổ ghép đôi %s không phải object — bỏ qua", path)
            return 0

        with self._lock:
            for device_id, phone in data.items():
                if not device_id or not phone:
                    continue
                record = self._devices.get(device_id)
                if record is None:
                    record = DeviceRecord(device_id=str(device_id))
                    self._devices[str(device_id)] = record
                record.paired_to = str(phone)
        return len(data)

    def resolve_by_serial(self, serial: str) -> DeviceRecord | None:
        """Tra kính theo số máy ngắn người dùng gõ vào app ("01")."""
        if not serial:
            return None
        wanted = serial.strip().lstrip("#")
        with self._lock:
            for record in self._devices.values():
                if record.serial == wanted:
                    return record
        return None

    def snapshot(self) -> list[dict[str, object]]:
        now = time.monotonic()
        with self._lock:
            records = list(self._devices.values())
        return [
            {
                "device_id": record.device_id,
                "serial": record.serial,
                "fw_version": record.fw_version,
                "wifi_ssid": record.wifi_ssid,
                "paired_to": record.paired_to,
                "online": (now - record.last_seen) <= self._online_window,
                "seconds_since_seen": round(now - record.last_seen, 1),
            }
            for record in records
        ]

    def mark_update_pushed(self, device_id: str, version: str) -> None:
        with self._lock:
            record = self._devices.get(device_id)
            if record is not None:
                record.update_pushed_for = version

    def clear(self) -> None:
        with self._lock:
            self._devices.clear()


devices = DeviceRegistry()
