"""T26 — cấp Wi-Fi cho kính qua BLE, lái từ laptop.

Vì sao có tool này thay vì chờ app điện thoại
---------------------------------------------
Đường BLE là đường CỨU HỘ: nó chỉ bật khi kính **không vào được mạng**, tức
đúng lúc mọi cách chẩn đoán khác đã tắt — không SSH, không `/diag/log`, không
`GET /devices`. Nếu bản thân đường cứu hộ chưa từng được thử thì nó không phải
đường cứu hộ, nó là một giả định.

Thử bằng laptop chạy được ngay hôm nay; app điện thoại thì phải chờ giao diện.
Firmware cố ý dùng **Nordic UART Service** chính vì lý do đó — mọi công cụ BLE
phổ thông (nRF Connect, `bleak`) nói chuyện được ngay, không cần profile riêng.

    service   6E400001-B5A3-F393-E0A9-E50E24DCCA9E
    RX write  6E400002-...   <- {"ssid":"...","password":"..."}
    TX notify 6E400003-...   -> câu trạng thái đọc được bằng mắt thường

Cách chạy
---------
    python tools/ble_provision.py --scan
    python tools/ble_provision.py --ssid "Thanh_Cuong_FI" --password "123456789"

🔴 Kính chỉ quảng bá BLE khi ĐANG KHÔNG có mạng. Đang online mà quét thì không
thấy gì — đó là hành vi ĐÚNG, không phải hỏng: NimBLE tốn 40-60 KB còn khối
liền sau khi TLS mở chỉ còn 34 804 B (đo 2026-08-26), nên hai bên không bao
giờ được sống cùng lúc.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from types import SimpleNamespace

# stdout Windows là cp1252; thiếu dòng này thì tool chạy xong việc rồi chết ở
# lệnh print cuối, nhìn từ ngoài giống hệt "tool hỏng".
sys.stdout.reconfigure(encoding="utf-8")

from bleak import BleakClient, BleakScanner  # noqa: E402

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

NAME_PREFIX = "VisionCare-"


async def find_glasses(timeout: float):
    """Chiếc kính đang quảng bá, hoặc None.

    🔴 Lọc theo UUID DỊCH VỤ, không theo tên. Bản đầu lọc theo tên và nó hỏng
    im lặng trên Windows: `BleakScanner.discover()` trả `device.name = None`
    cho mọi thiết bị chưa ghép đôi, nên kính đang quảng bá ngay bên cạnh vẫn
    bị bỏ qua — nhìn từ ngoài giống hệt "kính không bật BLE". Tên vẫn đọc
    được, nhưng phải lấy từ `advertisement.local_name` với `return_adv=True`.
    """
    print(f"Đang quét {timeout:.0f}s...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)

    hits = [
        (addr, adv)
        for addr, (_dev, adv) in found.items()
        if NUS_SERVICE in [u.lower() for u in adv.service_uuids]
    ]

    for addr, (_dev, adv) in found.items():
        mark = "  <-- kính" if any(a == addr for a, _ in hits) else ""
        print(f"  {addr}  {adv.local_name or '(không tên)'}{mark}")

    if not hits:
        print(
            "\nKhông thấy thiết bị nào quảng bá Nordic UART.\n"
            "Kính chỉ bật BLE khi KHÔNG vào được mạng — đang online thì đây là "
            "kết quả đúng."
        )
        return None

    addr, adv = hits[0]
    return SimpleNamespace(address=addr, name=adv.local_name or f"{NAME_PREFIX}?")


async def send_credentials(address: str, ssid: str, password: str) -> bool:
    replies: list[str] = []

    def on_notify(_sender, data: bytearray) -> None:
        text = data.decode("utf-8", "replace")
        replies.append(text)
        print(f"  kính nói: {text}")

    async with BleakClient(address) as client:
        print(f"Đã nối {address}")
        await client.start_notify(NUS_TX, on_notify)

        payload = json.dumps({"ssid": ssid, "password": password}).encode("utf-8")
        print(f"Gửi {len(payload)} byte: ssid={ssid!r}, mật khẩu {len(password)} ký tự")

        # response=True: đợi bên kia xác nhận từng gói. Với write-no-response
        # thì một gói rơi là im lặng — mà đây là đường cứu hộ, im lặng là thứ
        # tệ nhất có thể xảy ra.
        await client.write_gatt_char(NUS_RX, payload, response=True)

        # Kính trả lời rồi mới tự khởi động lại; chờ đủ để câu đó ra khỏi hàng.
        await asyncio.sleep(3.0)

    ok = any("Da luu" in r for r in replies)
    print("\n✅ Kính đã nhận và lưu — nó đang khởi động lại vào mạng mới."
          if ok else
          "\n⚠️ Không thấy câu xác nhận. Xem lại phần kính nói ở trên.")
    return ok


async def amain() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", action="store_true", help="chỉ quét, không gửi gì")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--ssid")
    parser.add_argument("--password", default="")
    parser.add_argument("--address", help="bỏ qua bước quét, nối thẳng địa chỉ này")
    args = parser.parse_args()

    address = args.address
    if not address:
        found = await find_glasses(args.timeout)
        if found is None:
            return 1
        print(f"\nThấy kính: {found.name} ({found.address})")
        address = found.address

    if args.scan or not args.ssid:
        if not args.scan:
            print("\nThiếu --ssid nên dừng ở bước quét.")
        return 0

    return 0 if await send_credentials(address, args.ssid, args.password) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
