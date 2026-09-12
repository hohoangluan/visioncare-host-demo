# Bỏ SSE, chuyển kênh xuống sang poll — thiết kế

Ngày 2026-08-26. Đụng cả ba repo.

## Vì sao

Board không giữ nổi TLS và `/events` cùng lúc — đo trực tiếp trên
`glasses-01`: một phiên TLS ngốn 45 056 B RAM liền, `/events` ngốn 37 888 B,
mà khối liền lớn nhất sau khi httpd + audio lấy phần của chúng chỉ còn
~114 676 B. Hệ quả đã đo: `firmware_update` trả `pushed: 0`, lệnh đổi Wi-Fi
qua SSE rơi vào hộp thư chết dù server đếm `subscribers: 1`.

Đường ra đã khảo sát trước đây (`CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC=y`) đòi rời
Arduino IDE. Thiết kế này giải cùng bài toán mà **không** phải rời: bỏ kết nối
thường trực đi thì không còn hai phiên TLS cùng lúc để mà tranh RAM.

## Quyết định

| # | Quyết định | Người quyết |
|---|---|---|
| 1 | Kênh xuống: SSE thường trực → `GET /downlink` poll 2 s khi rảnh | người dùng, 2026-08-26 |
| 2 | Một chế độ ảnh duy nhất, **XGA 1024×768**, luôn gửi mỗi lượt | người dùng, 2026-08-26 |
| 3 | Wi-Fi qua app: giữ **cả hai** đường — BLE (kính chưa có mạng) và server→poll (đổi mạng A→B) | người dùng, 2026-08-26 |
| 4 | Vật cản **quay về bản gốc dùng LLM** (`describe_hazard`), bỏ chế độ canh khỏi luồng | người dùng, 2026-08-26 |

Quyết định #4 đảo ngược quyết định 2026-08-25 (`hazard` → bật chế độ canh).
Ghi lại ở đây để lần sau đọc code không tưởng là lỗi.

## Phần 1 — `GET /downlink` thay `GET /events`

```
GET /downlink        X-Device-Id (bắt buộc) · X-Fw-Version · X-Wifi-Ssid
200 {"status":"ok","data":{"events":[ {...}, ... ]}}
400  thiếu X-Device-Id
```

Rút cạn hàng đợi của đúng thiết bị đó, trả ngay, đóng socket. Không giữ kết
nối, không heartbeat, không `ping`.

Board gọi mỗi 2 s và **chỉ khi rảnh** — không đang `/process`, không đang phát
tiếng, không đang OTA, không đang chụp. Đó là điều kiện làm nên toàn bộ giá
trị của thiết kế: **không bao giờ hai phiên TLS cùng lúc**.

`EventHub` giữ nguyên hàng đợi 8 chỗ/thiết bị và chính sách đẩy-văng-cái-cũ khi
đầy. Đổi:

- `subscribe()` (generator SSE) → `drain(device_id)` trả `list[dict]`
- xoá `_alive_at`, `_prune_dead_locked()`, `_unsubscribe()`, `_encode()` —
  không còn subscriber thì không còn subscriber ma
- `subscriber_count()` → `downlink_open(device_id)`: **thiết bị đã poll trong
  `DOWNLINK_STALE_SECONDS` (10 s) gần đây** hay chưa
- hàng đợi giờ sống độc lập với việc có ai đang nối hay không: sự kiện đẩy vào
  lúc board đang bận vẫn nằm đó chờ lượt poll kế tiếp. Đây là điểm SSE thua —
  SSE mất sự kiện khi board `eventStreamPause()`.

Loại sự kiện: bỏ `frame_request` và `ping`. Giữ `call_incoming`, `call_ended`,
`wifi_config`, `firmware_update`, `hazard_watch`, `hazard_level` (hai cái cuối
không còn ai phát trong luồng — xem Phần 4).

`/wifi/remote-config` và `/firmware/push` đổi điều kiện 503 từ "không có
subscriber" sang "thiết bị chưa poll trong 10 s".

**Đánh đổi đã biết:** cuộc gọi đến báo trễ thêm ≤2 s. Chuông đổ 30 s nên dư.

## Phần 2 — Một chế độ ảnh, XGA, luôn gửi

Bỏ hẳn F5 (hai tầng ảnh + vòng hỏi-đáp xin tầng cao cho `ocr`).

Board: `photoCaptureHigh()` xoá, `FRAME_TIER_LOW`/`FRAME_TIER_HIGH` → một hằng
`FRAME_SIZE_DEFAULT = FRAMESIZE_XGA`. Header `X-Frame-Tier` bỏ.

Server: `FrameBuffer` bỏ field `tier`, `/frame` bỏ đọc `X-Frame-Tier`,
`router.py` xoá khối xin ảnh tầng cao, `config.FRAME_HIGH_TIER_WAIT_MS` xoá.

Số đo, từ `docs/tasks/measurements/F5-resolution.md`:

| | VGA (cũ) | XGA (mới) |
|---|---|---|
| JPEG | 21 153 B | 43 020 B |
| đẩy @24.3 KB/s | 850 ms | 1 729 ms |
| chụp | 946 ms | 524 ms |
| độ nét (Laplacian) | 156.0 | 80.8 |

Ngưỡng blur **không phải hiệu chỉnh lại**: `IMAGE_MIN_SHARPNESS = 5`, và nó
chỉ áp cho `money`. 80.8 dư 16 lần.

🔴 **Chưa đo:** `/frame` là fire-and-forget trên socket riêng, chạy song song
với lúc người dùng đang giữ nút và nói. Nếu người ta nói ≥1.7 s thì +879 ms
này miễn phí; nói cụt ("đọc đi") thì nó lộ ra. Phải bấm nút trên board và đo,
không chốt bằng suy luận.

Bù lại `ocr` mất hẳn vòng hỏi-đáp — trước đây tốn một vòng SSE cộng chờ
`FRAME_HIGH_TIER_WAIT_MS`.

## Phần 3 — Wi-Fi qua app, hai đường

| đường | dùng khi | trạng thái |
|---|---|---|
| App → BLE → kính | kính **chưa** vào được mạng nào | board sẵn sàng; **app Android chưa có gì** — làm mới |
| App → server → poll → kính | kính đang có mạng, đổi sang mạng khác | có sẵn, chỉ đổi transport SSE→poll |
| App → LAN `/wifi/config` | cùng LAN | có sẵn, không đụng |

Hai đường đầu **không thay thế nhau**: BLE trên board chỉ bật khi chưa có
mạng, nên nó không dùng được để đổi mạng A→B; và đường server không dùng được
khi kính chưa online. Đó là lý do giữ cả hai.

Phía Android cần: quét theo **UUID dịch vụ** (không theo tên — `bleak` và
Android đều trả tên rỗng cho thiết bị chưa ghép đôi), GATT connect, ghi
Nordic UART, xin quyền `BLUETOOTH_SCAN`/`BLUETOOTH_CONNECT` (Android 12+), màn
hình chọn kính + nhập SSID/mật khẩu.

🔴 Board **không** được `BLEDevice::deinit()` trong `onWrite()` — ngăn xếp gửi
write-response sau khi callback trả về. App sẽ thấy LỖI cho một việc THÀNH
CÔNG.

## Phần 4 — Vật cản quay về LLM

`Intent.HAZARD` → `handlers/describe_hazard.py` (Gemini/VLM, một câu trả lời
cho một khung hình), đúng như trước 2026-08-25.

`Intent.HAZARD` quay lại `router._IMAGE_REQUIRED_INTENTS` và
`image_quality._READS_IMAGE` — nó lại là một câu hỏi về một khung hình, nên
lại cần ảnh và lại chịu cổng chất lượng ảnh.

Chế độ canh (T24): **gỡ khỏi luồng, không xoá file.** `hazard_watch.py`,
`hazard_worker.py`, `hazard_risk.py`, `hazard_detector.py` và test của chúng
giữ nguyên và vẫn xanh; chỉ router thôi trỏ vào. `Intent.HAZARD_WATCH_START/
STOP` không nằm trong prompt phân loại ý định nên không đường nào tới được
chúng nữa. Giữ lại vì quyết định này đã đảo một lần và có thể đảo lại.

## Phần 5 — Kiểm thử

Ba tầng. Tầng 3 người dùng phải làm, không thay thế được.

### Tầng 1 — unit + contract (tôi chạy)

`.venv/Scripts/python.exe -m pytest -q -m "not llm"`, mốc hiện tại `833 passed`.

Mới:
- `/downlink`: rút cạn hàng đợi · hai lần poll liên tiếp không nhận trùng ·
  thiếu `X-Device-Id` → 400 · sự kiện đẩy lúc không ai poll vẫn còn ở lượt sau ·
  hàng đầy thì đẩy văng cái cũ nhất · `downlink_open` hết hạn sau 10 s
- `/events` đã biến mất → 404
- `/frame` không còn `tier`

Sửa: `test_frame_tier.py` (F5 bị xoá), `test_events_channel.py`,
`test_router.py` phần hazard.

### Tầng 2 — full pipeline, phủ hết case (tôi chạy)

Một file `tests/test_pipeline_e2e.py`, mỗi chức năng một lớp, đi **qua router**
chứ không gọi thẳng handler — đó là chỗ ba lần bug im lặng đã lọt.

| chức năng | case phải có |
|---|---|
| mô tả (`space`) | thường · ảnh mờ · ảnh tối · không có ảnh |
| đọc chữ (`ocr`) | có chữ · không có chữ · chỉ-text không cần ảnh |
| vật cản (`hazard`) | thường · **không có ảnh → từ chối** · ảnh tối (quay lại LLM nên lại chịu cổng ảnh) |
| nghe nhạc | play · stop · volume · app không phản hồi → câu hết giờ |
| khẩn cấp | đúng 3 nhịp · cổng từ khoá cục bộ bước 1/6 · phải thắng mọi pending |
| cuộc gọi đến | `call_incoming` vào hàng đợi · `call_answer`/`call_reject` · ngắt lượt đang chạy |

### Tầng 2b — luồng xác nhận nhiều vòng (trọng tâm)

Ba `kind` pending, mỗi cái một TTL, mỗi cái một luật khớp. Đây là chỗ dễ sai
nhất và đã sai một lần.

| kind | ví dụ | case phải có |
|---|---|---|
| `confirm` | `ride_quote` → "đặt xe này nhé?" | ừ → chạy · không → huỷ · **câu lạc → không được coi là "ừ"** · hết TTL 25 s · nói lại lượt mới trong lúc chờ · hỏi lại hai vòng liên tiếp |
| `fill` | `nav_start` thiếu điểm đến | điền đủ · điền sai/thiếu → hỏi lại · đổi ý giữa chừng · hết TTL |
| `select` | `contact_call` trùng nhiều tên | chọn theo số · chọn theo tên · chọn ngoài danh sách · "không phải" → huỷ |

Bất biến phải có assert riêng, không suy ra từ case khác:
- **MỘT pending mỗi thiết bị** — pending mới THAY, không xếp chồng
  (CONTRACTS quyết định #9)
- thứ tự 6 bước của router: khẩn cấp (1) thắng pending tất định (2) thắng
  STOP (3) thắng pending điền slot (4) thắng huỷ/lặp toàn cục (5) thắng phân
  loại ý định (6)
- `bump_generation` không được xoá `Session.pending`
- pending của thiết bị A không rò sang thiết bị B

### Tầng 3 — trên phần cứng thật (🔴 người dùng)

| việc | cách nghiệm thu |
|---|---|
| nút khẩn cấp 3 nhấn | bấm thật trên gọng kính → điện thoại phải đổ chuông |
| cuộc gọi đến qua poll | gọi vào máy đã ghép → **nghe** kính có báo không, đo trễ |
| XGA có làm chậm lượt nói cụt không | bấm nút, nói đúng một từ, đọc `X-Turn-Id` trong `/diag/log` |
| đổi Wi-Fi qua app, đường BLE | kính chưa có mạng → app ghi → kính vào mạng |
| đổi Wi-Fi qua app, đường server | kính đang ở mạng A → app đổi sang B |
| OTA qua poll | `publish_firmware.py` rồi đợi ≤2 s, board tự kéo |

### Tầng 4 — end-to-end qua tunnel (tôi chạy, cần server sống)

```
python tools/bench_e2e.py --host api.visioncare-host.uk --port 443 --repeat 2
```

Mốc hiện tại: trung vị tiếng đầu 0.33 s, 16/16 dưới 1 s, phân loại 15/15.

## Việc KHÔNG làm trong đợt này

- Không đụng `find_object`, `read_money` (spec mục 7)
- Không xoá file chế độ canh vật cản — chỉ gỡ khỏi luồng
- Không đổi `AUDIO_PREROLL_MODE`
- Không ghim CA cho TLS (`setInsecure()` vẫn nguyên) — việc riêng, quyết định #9
