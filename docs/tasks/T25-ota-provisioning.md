# T25 — Nạp OTA, cấu hình mạng từ app, số máy kính

| | |
|---|---|
| **Mã spec** | O1–O7 (mới, không có trong SPEC gốc — yêu cầu người dùng 2026-08-24) |
| **SPEC gốc** | — |
| **Repo đụng** | 🔵 Server kính · 🔴 Firmware · 🟡 App Android |
| **Trạng thái** | 🟠 PARTIAL — OTA LAN đã kiểm chứng trên board thật; OTA qua internet chờ mạng mở cổng 443 |
| **Chặn bởi** | — |
| **Chặn** | mọi task cần nạp lại firmware (T17/F5, T18, T19, T24) |

> Task này **mở khoá** cho các task đang treo vì "không nạp lại được board".
> Ghi chú cũ `board-firmware-lags-repo-head` đã hết hiệu lực.

---

## 0. Vì sao có task này

Ba yêu cầu người dùng đưa ra ngày 2026-08-24, theo thứ tự:

1. *"nạp code từ giờ chuyển từ nạp trực tiếp sang nạp OTA, cho phép app config mạng cho thiết bị"*
2. *"thêm cho board gọi là device id (là số nạp lần đầu), bản này để là 01, nó sẽ dựa vào số đó để link với điện thoại"*
3. *"cho sửa code thông qua không cùng mạng luôn, board không cùng mạng với server, server yêu cầu board cập nhật code mới nếu cần"*
4. *"mỗi yêu cầu từ kính gửi kèm device id để định tuyến sang điện thoại tốt hơn"*
5. *"thêm chỗ xem wifi đang đăng ký là gì để người dùng biết phải cấp mạng cho board"*

Yêu cầu 3 là yêu cầu quyết định kiến trúc: nó loại bỏ `ArduinoOTA` khỏi vị trí
đường phát hành chính.

---

## 1. Hiện trạng trước task

| Tầng | Trạng thái cũ |
|---|---|
| Nạp firmware | chỉ USB/UART, phải tháo dây RX/TX |
| Wi-Fi | hai dòng `const char*` biên dịch cứng trong `.ino` |
| `device_id` | `"glasses-" + MAC` — câu hỏi mở #2 của T01 mục 6 |
| Server | không biết kính nào đang chạy bản nào |

---

## 2. Việc đã làm

### O1 — Partition phải đổi (🔴 blocker của cả task)

`huge_app` là **"3MB No OTA/1MB SPIFFS"** — không có slot OTA.
`ArduinoOTA.begin()` vẫn chạy nhưng mọi phiên nạp chết ở `OTA_BEGIN_ERROR`.

```
min_spiffs:  1966080 byte/slot
bản dựng  :  1367015 byte (69%)     ← vừa, còn 599 KB bù
```

🔴 **Đây là lần nạp USB CUỐI CÙNG.** Đổi partition không OTA qua được — slot
đích chưa tồn tại. Đã nạp COM10 lúc 2026-08-24, `Hash of data verified`.

### O2 — Hai đường OTA, hai hoàn cảnh khác nhau

| | ArduinoOTA (đẩy) | HTTP pull (kéo) |
|---|---|---|
| File | `src/net/ota_manager.cpp` — `otaBegin()` | cùng file — `otaPullIfAvailable()` |
| Ai bắt đầu | máy nạp | **chính kính** |
| Mạng | phải **cùng LAN** (mDNS) | khác mạng vẫn chạy |
| Dùng khi | đang ngồi trong phòng lab | phát hành thật |
| Kích hoạt | `espota.exe -i <ip> -a <pass>` | sự kiện SSE `firmware_update`, hoặc vòng hỏi 6 giờ |

Cả hai dùng chung slot OTA nên **không bao giờ chạy cùng lúc** — vì vậy cùng
nằm trong một task (`otaTask`, core 0, ưu tiên 1).

### O3 — Hợp đồng OTA kéo

```
GET /firmware/manifest      X-Device-Id (bắt buộc) · X-Fw-Version
  -> {"update":true,"version":"...","url":"/firmware/bin?version=...",
      "size":1367015,"sha256":"<64 hex>"}
  -> {"update":false,"reason":"NO_RELEASE"|"UP_TO_DATE"}

GET /firmware/bin?version=  X-Device-Id (bắt buộc)
  -> thân nhị phân + X-Firmware-Sha256, X-Firmware-Version

POST /internal/firmware/push   loopback + Bearer
  {"device_id":"glasses-01"}   thiếu device_id -> đẩy cho MỌI kính lệch bản
```

Ba quyết định, mỗi cái trả giá cho một cách hỏng:

1. **Fail-closed** — không có `latest.json` thì không phát hành gì. File `.bin`
   lạc vào thư mục KHÔNG tự thành bản phát hành.
2. **`sha256` bắt buộc, kính đối chiếu TRƯỚC `Update.end()`** — ảnh đứt giữa
   chừng vẫn "ghi thành công", chỉ chết lúc khởi động lại, mà lúc đó kính đã ở
   trong túi người dùng.
3. **So phiên bản bằng `!=` chứ không `>`** — `FW_VERSION` là chuỗi ngày-tháng,
   không phải semver. `!=` cho phép **rollback**, thứ cần nhất khi một bản phát
   hành hỏng.

🔴 **Sự kiện SSE không mang byte firmware nào**, chỉ mang tên phiên bản. Đẩy
1.35 MB qua kênh `/events` sẽ chặn hàng đợi của `call_incoming` hàng chục giây.

### O4 — Số máy kính (trả lời câu hỏi mở #2 của T01 mục 6)

`X-Device-Id` = `"glasses-" + số máy`; số máy nằm trong **NVS**
(`src/net/device_identity.h`, namespace `vc_id`), mặc định
`DEVICE_SERIAL_DEFAULT = "01"` ghi vào lần khởi động đầu sau khi nạp.

Vì sao không lấy MAC: người dùng phải **đọc số đó ra miệng** để ghép đôi, và
thay board hỏng là mất sạch lịch sử ghép đôi. Số trong NVS chép sang board mới
được.

Kiểm chứng trên board thật:
```
Firmware 2026.08.24-ota1
So may 01  (X-Device-Id: glasses-01)
```

### O5 — Cấu hình mạng từ app, hai đường

| Kính còn mạng | Kính mất mạng |
|---|---|
| `POST /internal/device/wifi` → sự kiện SSE `wifi_config` → NVS → khởi động lại | kính tự bật SoftAP **`VisionCare-Setup`**, điện thoại nối vào, mở `http://192.168.4.1/` |

Kính mất mạng trả **409** ở đường thứ nhất, không phải 200 — trả 200 là nói dối:
sự kiện rơi vào hư không, người dùng ngồi đợi một chiếc kính không bao giờ đổi.

Ba endpoint trên chính kính (cổng 80, có ở cả SoftAP lẫn lúc online):

```
GET  /wifi/status  -> serial, device_id, fw_version, ssid, from_nvs,
                      ap_mode, connected, ip, rssi, ota_hostname, ota_protected
GET  /wifi/scan    -> danh sách AP 2.4 GHz (app hiện picker)
POST /wifi/config  -> ssid + password (query HOẶC thân JSON) -> NVS -> reboot
```

### O6 — Mọi request mang `device_id` (định tuyến sang điện thoại)

`X-Device-Id` đã có trên `/process` và `/frame` từ T01/F1. Task này thêm nó
vào `/events`, `/firmware/manifest`, `/firmware/bin`, và thêm hai header nữa:

| Header | Ai dùng |
|---|---|
| `X-Fw-Version` | server biết cả đàn kính đang chạy bản gì, **không tốn vòng hỏi nào** |
| `X-Wifi-Ssid` | app hiện "kính đang ở mạng «Redmi Note 14»" (yêu cầu 5) |

Cả hai đi kèm **mỗi lượt bấm nút**, ghi vào `services/device_registry.py`.

🔴 `/firmware/*` và `/internal/device/wifi` **KHÔNG** rơi về
`config.VISIONCARE_DEVICE_ID` khi thiếu header — RUNBOOK mục 7 cấm đúng chuyện
đó, và ở đây còn tệ hơn: rơi nhầm là đẩy firmware của kính này xuống kính khác.

### O7 — Ghép đôi kính ↔ điện thoại

```
GET  /devices                 danh sách kính: serial, fw_version, wifi_ssid,
                              paired_to, online, seconds_since_seen
POST /internal/device/pair    {"phone":"...","serial":"01"}  hoặc device_id
```

Ghép trước khi kính từng gọi tới **được phép** — người dùng mở app và gõ số in
trên vỏ kính trước khi bật kính là thứ tự tự nhiên nhất.

---

## 3. Hợp đồng đổi

Ghi vào `CONTRACTS.md`:

```
mọi request từ kính  + X-Fw-Version, X-Wifi-Ssid (mới, "nên có")
X-Device-Id          = "glasses-" + số máy NVS  (CHỐT, thay MAC)
GET  /firmware/manifest        (mới)
GET  /firmware/bin             (mới)
GET  /devices                  (mới)
POST /internal/firmware/push   (mới, loopback+Bearer)
POST /internal/device/wifi     (mới, loopback+Bearer)
POST /internal/device/pair     (mới, loopback+Bearer)
GET  /events   + firmware_update, wifi_config  (loại sự kiện mới)
```

---

## 4. Test

`tests/test_firmware_ota.py` — 24 ca, **24 pass**:

```
$ .venv/Scripts/python.exe -m pytest tests/test_firmware_ota.py -q
........................                                                 [100%]
24 passed, 3 warnings in 1.04s
```

Nhóm ca:
- fail-closed (3): không `latest.json`, `.bin` lạc, con trỏ tới file thiếu
- manifest & toàn vẹn (5): offer/up-to-date/**rollback**/digest khớp/404
- không rơi nhầm thiết bị (2): thiếu `X-Device-Id` → 400
- sổ thiết bị (5): serial cắt tiền tố, `wifi_ssid` lộ ra `/devices`, ghép trước
- đẩy lệnh (9): sự kiện tới đúng kính, **không mang byte firmware**, 409/401/422

---

## 5. Đã kiểm chứng những gì — và KHÔNG kiểm chứng những gì

🔴 Đọc kỹ cột "trên board thật?". Ba dòng cuối bảng dưới **chưa từng chạy
trên phần cứng** — chúng được nghiệm thu bằng `curl` từ máy tính tự đặt header
đóng giả kính. Đó là phép thử nửa phía server, **không phải** phép thử của
đường OTA kéo.

### 5.1 Thật, trên board (2026-08-24)

| Kiểm | Kết quả |
|---|---|
| Nạp USB COM10, partition `min_spiffs` | ✅ `Wrote 1367168 bytes ... Hash of data verified` |
| Số máy ghi NVS lần đầu | ✅ Serial in `So may 01  (X-Device-Id: glasses-01)` |
| `GET /wifi/status` qua LAN | ✅ `{"serial":"01","fw_version":"2026.08.24-ota1","ssid":"Redmi Note 14","ota_protected":true}` |
| `GET /wifi/scan` | ✅ 11 AP, đúng danh sách kính THẤY (không phải điện thoại thấy) |
| **OTA ĐẨY qua Wi-Fi LAN** (`espota -i 172.20.51.254 -a visioncare-ota`) | ✅ `100% Done`, board tự khởi động lại, `/wifi/status` báo `fw_version: 2026.08.24-ota2` |
| Số máy sống sót qua OTA | ✅ vẫn `01` |

### 5.2 Chỉ nửa phía server — board KHÔNG tham gia

Chạy bằng `curl` từ máy tính qua **Cloudflare tunnel thật**, tự đặt
`X-Device-Id: glasses-01` và `X-Fw-Version: 2026.08.24-ota2`:

| Kiểm | Kết quả | Board có tham gia? |
|---|---|---|
| `GET /firmware/manifest` | ✅ chào đúng `2026.08.24-ota3` kèm `size` + `sha256` | ❌ không |
| `GET /firmware/bin?version=…` | ✅ 1369568 byte, `X-Firmware-Sha256` khớp header | ❌ không |
| sha256 file tải về vs manifest | ✅ khớp tuyệt đối `d69b50e7…f6707` | ❌ không |

**`otaPullIfAvailable()` chưa chạy trên phần cứng lần nào.** Muốn nghiệm thu
thật: cắm board, cho nó vào mạng cho ra 443, rồi xem Serial in
`[OTA-PULL] Co ban moi ... dang keo ve`.

### 5.3 Thất bại thật, ghi lại để không đoán nhầm

Bản `ota3` (có T24) **không lên được board**: `espota` báo
`No response from the ESP`. Nguyên nhân **không phải code** — giữa chừng board
rời USB *và* máy tính đổi sang Wi-Fi khác (`172.20.51.177` → `10.108.84.200`).
Board nằm ở mạng cũ, máy nạp ở mạng mới, mà `espota` đi qua mDNS **cùng LAN**.

Đó chính là lý do phải có đường thứ hai: `espota` chỉ dùng được trong phòng lab.

---

## 6. Chưa làm & vì sao — GAP

### 6.1 🔴 OTA **kéo qua internet** chưa chạy thật trên board lần nào

Hai chặng chặn khác nhau, xảy ra nối tiếp trong cùng một phiên:

**a) Mạng đầu (`172.20.51.x`) chặn TCP 443 ra Cloudflare.** Đo xen kẽ đúng
theo phép thử bắt buộc ở firmware `CLAUDE.md` mục 4b:

```
board 172.20.51.254 : TCP/TLS toi 104.21.67.134 HONG sau 18309 ms
                      mbedtls -1 (-0x0001) ERROR - Generic error
PC    172.20.51.177 : code=000 tcp=0.000000 tong=21.35   (curl)
DNS                 : xanh, 172.67.176.233 + 104.21.67.134
server local :8000  : 200 · cloudflared đang chạy
```

**PC cùng AP cũng hỏng y hệt** ⟹ mạng, không phải board, không phải code.

**b) Mạng sau (`10.108.84.200`) CHO RA 443** — `tcp=0.18s tls=0.28s tổng=0.97s`.
Nhưng lúc đó board đã rời USB và còn nằm ở mạng cũ, nên nó chưa bao giờ được
thử trên mạng tốt.

Chưa xác minh được, phải làm khi board lên lại mạng cho ra 443:
- `otaPullIfAvailable()` end-to-end **từ chính board**
- SSE `/events` giữ mở qua Cloudflare (client firmware đã viết, chưa chạy thật)
- 🔴 **RAM khi hai phiên TLS cùng mở** (`/events` + `/process`): mbedtls cần
  ~45 KB LIÊN mỗi phiên; khối liền lớn nhất đo được sau khi audio cấp phát là
  **77812 B**. Hai phiên = ~90 KB ⟹ **có khả năng không đủ**. Đã có sẵn
  `eventStreamPause()`/`Resume()` làm đường lui, chưa nối dây vì chưa đo.
- Ngân sách độ trễ T21 đo từ board trên bản TLS=1

### 6.2 Chưa nối dây

- `otaSetBusyProbe()` chưa được sketch cài — hiện OTA có thể nạp giữa lúc
  người dùng đang bấm nút. Cần một hàm "đang bận" từ `audio_service`, mà quy
  ước project cấm khối gọi ngang hàng (`CLAUDE.md` mục 8) → phải đi qua
  `audio_service` hoặc qua hook cài từ `.ino`.
- `onDeviceEvent()` mới xử `firmware_update` + `wifi_config`. `call_incoming`
  (T19), `frame_request` (T17/F5), `hazard_*` (T24) còn rơi vào nhánh
  "chưa có người nhận".

---

## 7. Câu hỏi phải chốt

1. `OTA_PASSWORD` hiện là `"visioncare-ota"` và `WIFI_SETUP_AP_PASSWORD` là
   `"visioncare"` — cả hai viết cứng trong `app_config.h`, tức **mọi kính xuất
   xưởng dùng chung một mật khẩu**. Có nên sinh theo số máy không?
2. Số máy do ai cấp khi sản xuất nhiều chiếc? Hiện mọi bản dựng đều mang
   `DEVICE_SERIAL_DEFAULT = "01"`, nên kính thứ hai nạp cùng bản firmware sẽ
   **trùng `device_id`** cho tới khi ai đó gọi `deviceSerialSet()`.
3. Sổ ghép đôi (`paired_to`) hiện nằm trong RAM, mất khi server khởi động lại.
   Cần kho bền — Postgres của server app, hay file JSON bên server kính?

---

## Quyết định UI — chốt 2026-08-25 (người dùng)

App CHỈ phơi ra hai việc, không hơn:

1. **Đổi mạng Wi-Fi cho kính**
2. **Cập nhật firmware**

Mọi thứ còn lại giấu ở backend: `device_id`/số máy, `fw_version`, token, ngưỡng
hazard, `wifi_ssid` hiện tại, trạng thái ghép đôi... Người dùng không phải biết
và không phải chọn.

> *"phần ui thay đổi mạng, và cập nhật chỉ cần cung cấp cho ng dùng cái đó
> phần còn lại giấu ở backend đi ng dùng k cần bt config nhiều vậy"*

Hệ quả cụ thể:

- `GET /device/status` vẫn trả đủ trường (server app + chẩn đoán cần), nhưng
  màn hình kính trong app chỉ vẽ hai nút. Không có màn "thông số kỹ thuật".
- Cập nhật firmware: **một nút**, không chọn phiên bản. Server tự biết bản mới
  nhất (`GET /firmware/manifest`), app chỉ hỏi "có bản mới không" và bấm.
- Đổi Wi-Fi: chọn mạng + gõ mật khẩu. Không phơi `X-Device-Id` hay token.

## T26 — cấp Wi-Fi qua BLE (chốt 2026-08-25, chưa thi công)

BLE **chỉ** thay khâu cấp/đổi Wi-Fi. Toàn bộ đường dữ liệu (POST /process,
/frame, SSE /events, OTA kéo) **giữ nguyên trên Wi-Fi/TLS** — BLE không có
đường IP tới `api.visioncare-host.uk:443`, và băng thông không gánh nổi:

| | Wi-Fi hiện tại | BLE5 2M PHY, ~8-11 KB/s thực |
|---|---|---|
| một câu trả lời | 35.1 KB, tiếng đầu 0.22 s, stream | ~4 s, không stream được |
| khung hazard 2 fps | JPEG mỗi 500 ms | không đủ băng thông |
| một bản OTA | 1 369 568 B, ~30 s | ~2-3 phút |

🔴 Ràng buộc RAM là thứ quyết định thiết kế: NimBLE tốn ~40-60 KB, mà mbedtls
cần **~45 KB LIỀN** mỗi phiên TLS và khối liền lớn nhất còn **77 812 B**. Nên
BLE **không được sống cùng lúc** với đường TLS: bật lúc cấp mạng, gọi
`esp_bt_controller_deinit()` ngay sau khi ghi NVS xong, rồi mới nối Wi-Fi.

Thay cho SoftAP `VisionCare-Setup` + `http://192.168.4.1` hiện tại (người
khiếm thị không tự vào được trang đó).
