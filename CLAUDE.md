# CLAUDE.md — Server kính (Your Eyes / VisionCare)

Thiết bị hỗ trợ người khiếm thị. Giữ nút → kính chụp ảnh + thu tiếng → server
xử lý → phát câu trả lời ra loa.

## Topology: 3 repo tách rời

Một luồng end-to-end thường phải sửa cả ba — đừng kết luận "không làm được"
khi mới đọc repo này.

| Vai trò | Đường dẫn | Cổng |
|---|---|---|
| **Server kính** (repo này) | `D:\Study\innostar\Sever_test` | `localhost:8000`, ra ngoài qua **Cloudflare tunnel** `api.visioncare-host.uk` |
| **Server app** | `D:\Study\innostar\app_demo_backend\apps\backend` | `localhost:8001` |
| **App Android** | `D:\Study\innostar\app_demo_backend\apps\android` | Kotlin + Compose |
| **Firmware ESP32** | `D:\Study\innostar\your-eyes-esp32-firmware` | COM10 · có `CLAUDE.md`/`AGENTS.md` riêng |

⚠️ Có ba thư mục cùng tên "app". Chỉ `app_demo_backend\apps\android` là app
thật.

## Luồng một lượt

```
kính giữ nút
  POST /frame     ảnh, fire-and-forget, socket riêng   (T17)
  POST /process   audio ADPCM thô, chunked, keep-alive (T01)
     └─ STT Zipformer → intent (SetFit ONNX 8ms, lui về Gemini)
        → router 6 bước → handler → TTS stream → audio về kính
GET /events       SSE giữ mở: server nói trước, không đợi nút (T18)
```

Mọi request từ kính mang `X-Device-Id: glasses-<số máy>` (số trong NVS, bản
đầu là `01`), `X-Turn-Id`, `X-Fw-Version`, `X-Wifi-Ssid`.

## Thư mục

| | |
|---|---|
| `app.py` | endpoint + stream audio + idempotency |
| `pipeline/` | `router.py` (6 bước ưu tiên) · `stt` `tts` `intent` `adpcm` `image_quality` `phrases` |
| `handlers/` | mỗi intent một file · `action_flow.py` giữ session/pending/generation |
| `services/` | `events_channel` (SSE) · `frame_buffer` · `turn_trace` (đo độ trễ) · `firmware` + `device_registry` (OTA) · `hazard_risk` + `hazard_detector` |
| `models/` | STT, VLM, intent encoder, `od/` (YOLO) — **không commit**, dựng lại bằng tool |
| `tools/` | `bench_e2e.py` (đo end-to-end) · `measure_budget.py` · `publish_firmware.py` · `fetch_hazard_model.py` |
| `docs/tasks/` | **nguồn sự thật của kế hoạch** — xem dưới |

## Tài liệu — đọc theo thứ tự này

1. [`docs/tasks/reports/PHIEN-2026-08-24.md`](docs/tasks/reports/PHIEN-2026-08-24.md) — phiên gần nhất đã đổi gì
2. [`docs/tasks/CONTRACTS.md`](docs/tasks/CONTRACTS.md) — **hợp đồng liên repo, nguồn sự thật**
3. [`docs/tasks/PROGRESS.md`](docs/tasks/PROGRESS.md) — trạng thái 25 task
4. [`docs/tasks/RUNBOOK.md`](docs/tasks/RUNBOOK.md) — thứ tự thi công + **mục 7: việc KHÔNG được làm**
5. [`docs/tasks/AGENT_RULES.md`](docs/tasks/AGENT_RULES.md) — luật cho subagent

## Quy tắc làm việc

1. **Có bảng số thì mới được chốt.** Ngưỡng chưa đo thì ghi "chưa đo", đừng
   chép số của cấu hình khác.
2. **Không báo xong khi chưa chạy lệnh DoD và nhìn thấy output xanh.** Dán
   output thật, không tóm tắt.
3. **Phụ thuộc repo khác chưa xong → PARTIAL**, ghi rõ ca nào còn hỏng, dùng
   `@pytest.mark.xfail(reason=...)`. Không xoá test, không báo xanh giả.
4. **Khi trong code đã có ghi chú cấm một việc, ghi chú đó thắng lập luận
   mới** — kể cả lập luận có số đo. Đã sai một lần vì tự đổi
   `AUDIO_PREROLL_MODE` dù chính `config.py` ghi là không được.
5. **Tối ưu trải nghiệm, không tối ưu đồng hồ.** Thiết bị này người dùng đeo
   cả ngày; "nhanh hơn 0.7 s" không thắng "nghe lần thứ hai mươi thì thế nào".
6. `find_object` và `read_money` **không đụng** (spec mục 7).
   ~~`describe_hazard.py` chỉ được thêm comment.~~ **Khoá này đã được người
   dùng gỡ tường minh 2026-08-25**: intent `hazard` giờ BẬT CHẾ ĐỘ CANH thay
   vì gọi Gemini, nên `describe_hazard.py` không còn ai gọi tới.
7. Test: `.venv/Scripts/python.exe -m pytest <đường dẫn cụ thể> -q`.
   Cả suite thì thêm `-m "not llm"` — nhóm `llm` gọi Gemini thật, đỏ ngẫu
   nhiên vì hạn mức chứ không phải vì code (`833 passed, 19 deselected`).

## Đo độ trễ — cách ĐÚNG

```powershell
python tools/bench_e2e.py --host api.visioncare-host.uk --port 443 --repeat 2
```

Đo qua `127.0.0.1:8000` là **đo một đường không tồn tại với board thật** (thiếu
TLS + tunnel). ⚠️ Không chạy `--repeat` lớn khi không có app điện thoại:
`contact_call`/`music_*`/`nav_*`/`ride_*` chờ trọn timeout 25-40 s mỗi lượt.

Số hiện tại (2026-08-25, qua tunnel, board chạy `API_USE_TLS 1`): trung vị
tiếng đầu **0.33 s**, **16/16** chức năng dưới 1 s, phân loại ý định **15/15**.
Bảng từng chặng: [`measurements/E2E.md`](docs/tasks/measurements/E2E.md)
(`python tools/report_e2e.py --host api.visioncare-host.uk --port 443`).
Bảng ngân sách cũ: [`measurements/G1.md`](docs/tasks/measurements/G1.md).

## Nạp firmware — biên dịch và nạp được trọn gói, không mở IDE

`arduino-cli` nằm lọt trong thư mục resources của Arduino IDE, nên
`where arduino-cli` không thấy:

```bash
CLI="/d/AppDownload/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe"
FQBN="esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=min_spiffs,FlashSize=16M,CDCOnBoot=cdc"

"$CLI" compile --fqbn "$FQBN" /d/Study/innostar/your-eyes-esp32-firmware
```

🔴 **`PartitionScheme=min_spiffs`, KHÔNG phải `huge_app`.** File cache
`D:\arduino-build\VisionCare\build.options.json` ghi `huge_app` — đó là bản
dựng 15/08, trước khi có OTA. Board từng chạy đúng bảng đó và **mọi lượt OTA
đều chết** ở `Update.begin that bai: Partition Could Not be Found`, im lặng với
server. Bảng phân vùng **chỉ ghi được qua USB**.

Rồi phát hành + nạp (đọc log board qua mạng chứ đừng mở COM):

```bash
python tools/publish_firmware.py --bin <bin> --version <FW_VERSION>
"$ESPOTA" -i 192.168.2.88 -p 3232 -a "visioncare-ota" -f <bin> -r
curl.exe -s http://192.168.2.88/wifi/status    # board chạy bản nào
curl.exe -s http://192.168.2.88/diag/log       # serial monitor qua mạng
```

---

# 🔴 VIỆC CÒN GÁC — đọc trước khi lập kế hoạch

*Cập nhật 2026-08-26 (phiên tối). Board `glasses-01` chạy `2026.08.26-ota25`
trên mạng **`Redmi Note 14`** (`172.20.51.254`). Board đã **lên PCB, không cắm
COM thường xuyên** — mọi việc đi qua mạng.*

## 🔴 Ba điều phải biết trước khi chạm vào board

1. **Laptop và kính phải CÙNG một Wi-Fi.** `espota` và `GET /diag/log` đều là
   LAN. Khác mạng thì mọi lệnh dò đều trả về rỗng, nhìn y hệt "board chết".
   Mất một tiếng của phiên 2026-08-26 vì đúng chuyện này.
2. **Mở COM bằng pyserial là RESET board** — pyserial bật DTR khi `open()`.
   Ba lần quét BLE liên tiếp không thấy kính chỉ vì chính lệnh đọc serial vừa
   đẩy nó về đầu vòng thử Wi-Fi. Muốn nghe mà không reset: đặt
   `dtr=False`/`rts=False` **trước** `open()`.
3. **Nạp USB xong PHẢI `publish_firmware.py` cùng version.** Board hội tụ về
   bản server đang phát hành, và `services/firmware.py` nguyên tắc 3 so bằng
   `!=` (cố ý, để rollback được). Nạp `ota25` qua USB mà server còn `ota24`
   thì board kéo `ota24` về đè — **đúng thiết kế, không phải lỗi.**

## ✅ Đã đóng trong phiên 2026-08-26 (tối) — bỏ SSE, một chế độ ảnh, hazard về LLM

| Việc | Bằng chứng |
|---|---|
| **Bỏ `GET /events` (SSE) → `GET /downlink` (poll 2 s khi rảnh)** | `[DOWN] <- firmware_update` trên board thật, rồi `[OTA-PULL] Dang chay ota23, server khong co ban moi`. Server: `downlink_open: true`, `downlink_last_poll_seconds: 1.6` |
| **Một chế độ ảnh XGA 1024×768, luôn gửi. F5 xoá sạch** | `tests/test_frame_single_mode.py` 17 test; `router` không còn import `events` |
| **`hazard` quay về LLM** (`describe_hazard`) | `_HANDLERS[Intent.HAZARD] is describe_hazard`; hazard trở lại cả hai cổng ảnh |
| **Test full pipeline + xác nhận nhiều vòng** | `tests/test_pipeline_e2e.py` 70 test — `confirm`/`fill`/`select`, thứ tự 6 bước, một-pending-mỗi-thiết-bị |
| **Toàn bộ suite server** | `969 passed, 1 skipped, 19 deselected, 17 xfailed` |
| **`POST /ota/pull` trên board** | Cửa kích nạp thủ công qua LAN, không cần inbound. `{"ok":true,"queued":true}` |
| **BLE cấp Wi-Fi** | Đổi kính từ `Thanh_Cuong_FI` → `Redmi Note 14` bằng `tools/ble_provision.py`, kính nhận và vào mạng mới |
| **BLE trong app Android** | `GlassesBleProvisioner.kt` + quyền manifest + nối vào `sendWifi()` thành **ba** đường. Gradle `BUILD SUCCESSFUL`. 🔴 **chưa chạy trên máy thật lần nào** |
| **`downlinkWaitIdle()`** | Bug do chính thiết kế poll đẻ ra: `downlinkPause()` chỉ đặt cờ, không đóng được socket của lượt poll đang chạy. Log board: `mbedtls -32512 Memory allocation failed` → `Nhuong RAM ... → TCP/TLS OK (2353 ms)` |
| **`TLS_KEEPALIVE_MS` 60 s → 20 s** | Phiên ấm bỏ đói kênh poll: đo được `downlink_last_poll_seconds: 57.5` — khớp đúng 60 s. Quyết định của người dùng 2026-08-26 |
| **`BLEDevice::setMTU(247)`** | Bug tiềm tàng chưa nổ: `onWrite()` không ghép mảnh, MTU mặc định 23 → 20 byte thân, mà JSON cấu hình là 46 byte. `bleak` tự nâng MTU nên laptop không dính; Android thì không |

## ✅ Đã đóng trong phiên 2026-08-26 (sáng)

| Việc | Bằng chứng |
|---|---|
| **Loa** | Đo bằng mic của chính board: đỉnh ở **đúng 440 Hz** ở cả sáu mức, biên độ 87→2060 gần tuyến tính. Trước đó câm vì dây `SD` của **mic** bị nối đất |
| **Xem serial qua mạng** | `GET /diag/log` — vòng đệm 32 KB trong PSRAM. Đọc được log board **không cắm dây, không reset nó** |
| **Biên dịch + nạp tự động** | `arduino-cli` có sẵn trong Arduino IDE; nạp OTA bằng `espota` báo `100% Done` |
| **T26 — cấp Wi-Fi qua BLE** | `VisionCare-01` quảng bá Nordic UART, laptop ghi cấu hình, board nhận và vào mạng mới. Lái bằng `tools/ble_provision.py` |
| **Đổi mạng từ app** | `Thanh_Cuong_FI` → `Ngoc Phat` → về, qua cả `/wifi/config` trên LAN lẫn sự kiện SSE |
| **Nút khẩn cấp 3 nhịp** | `Nhip bam 1/3, 2/3, 3/3` → `PANIC: gui /process` → server 200 sau 988 ms → **điện thoại đổ chuông thật** |
| **`otaSetBusyProbe()`** | Đã nối dây. Chặn OTA khi vừa bấm nút trong 60 s hoặc đang canh vật cản |
| **Callback server app** | Thêm `CALLBACK_URL`/`TOKEN`/`ALLOWED_HOSTS` vào `apps/backend/.env`. Đo: `music_volume` **2019 ms hết giờ → 895 ms** |
| **Ba migration DB thiếu** | `alembic upgrade head` — trước đó không đăng ký được tài khoản nào, và `capabilities_get`/`call_answer`/`call_reject` bị CHECK constraint chặn |

## 🔴 Nút thắt số một: RAM liền — mọi thứ khác đều vướng ở đây

Đo trực tiếp trên board (`memWatchLargest()`, `/diag/log`):

```
trước mọi thứ                khối liền  114 676 B
sau MỘT phiên TLS                        69 620 B   (−45 056)
sau khi cấp phát audio                   34 804 B
```

| thứ cần khối liền | tốn |
|---|---|
| một phiên TLS (mbedtls) | **45 056 B** |
| `/events` (SSE) | **37 888 B** |
| NimBLE | 40 000–60 000 B |

Board **không giữ nổi TLS và `/events` cùng lúc**, nên mỗi lần khởi động nó hy
sinh `/events`. Hệ quả đã đo: `firmware_update` đẩy đi trả `pushed: 0`, và
lệnh đổi Wi-Fi qua SSE rơi vào hộp thư chết dù server đếm `subscribers: 1`.

⟹ **T19 cuộc gọi đến, `wifi_config`, `firmware_update`, `hazard_watch` đều
không đáng tin** — tất cả đi chung `/events`.

Đường ra đã khảo sát: `CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC=y` đẩy mbedtls sang
PSRAM (còn 6.16 MB liền). Nằm trong sdkconfig của thư viện Arduino dựng sẵn,
**không sửa được từ sketch** — phải dựng bằng ESP-IDF, tức rời Arduino IDE.
Chưa quyết.

BLE không vướng: nó chỉ bật khi **chưa** có mạng, lúc đó khối liền còn 114 KB,
và board khởi động lại ngay sau khi ghi NVS nên hai bên không bao giờ gặp nhau.

## Chưa chạy trên phần cứng lần nào

| Việc | Cần gì để mở khoá |
|---|---|
| T24: fps thật, pin, tông có đè TTS không | bật chế độ canh rồi **nghe** trên board — `hazardWatchFps()` vẫn trả `0.00` |
| T19 cuộc gọi đến — kính có phát câu thông báo không | gọi vào máy đã ghép; **chặn bởi `/events` không đáng tin** |
| Bảng độ phân giải ảnh (F5) | `tools/bench_resolution.py` đã dựng và chạy được; cần bạn chĩa kính vào cảnh thử thật |

## Quyết định chờ người dùng

| # | Câu hỏi | Chặn |
|---|---|---|
| 2 | **Đẩy mbedtls sang PSRAM** — được 45 056 B mỗi phiên, giá là rời Arduino IDE | nút thắt RAM |
| 3 | Cột "nhả": còn **3/16** ca board phải chờ hết mới phát. **Phải nghe trên board** | T21 |
| 4 | Ngân sách riêng cho `ocr`, và F5 cộng thêm một vòng xin ảnh tầng cao | T15 |
| 5 | `OTA_PASSWORD`/`WIFI_SETUP_AP_PASSWORD` viết cứng ⟹ mọi kính chung một mật khẩu | phát hành |
| 6 | Số máy khi sản xuất nhiều chiếc — mọi bản dựng đều `"01"` ⟹ **trùng `device_id`** | phát hành |
| 9 | `setInsecure()` ⟹ kính **không kiểm chứng chỉ** TLS. Phải ghim CA trước khi phát hành | phát hành |
| 8 | ⛔ Farefeed (T11) · geocode ai làm · P1 `contact_list` (T08) · nguồn mã lỗi P7 (T20) | 4 task cũ |

## Chưa viết

- **Kết quả action về muộn không ai nói ra.** `run_action()` kết thúc ngay sau
  câu báo hết giờ; `reconcile_late()` chỉ cập nhật trạng thái phiên. Đường giữ
  lời hứa là đẩy xuống `/events` — chặn bởi nút thắt RAM ở trên. Tạm thời câu
  hết giờ đã đổi thành `"Điện thoại chưa báo lại."`, không hứa gì nữa.
- **Thu trước / chụp sau khi bấm đã là giữ thật.** Chỉ làm được nửa rẻ (bỏ
  chụp ở nhịp 2 và 3 của một chuỗi). Nửa còn lại — thu ngay từ 0 ms — đòi chụp
  từ task khác, mà `photoCaptureTier()` bảo vệ camera bằng cách *tạm dừng* vòng
  canh chứ không có mutex. Đưa concurrency thật vào đó là việc riêng, và phải
  có người bấm nút + nghe mới nghiệm thu được.
- **Ngưỡng blur theo TỪNG TẦNG** (F5). `image_quality.py` dùng một bộ ngưỡng
  cho mọi tầng, mà điểm Laplacian phụ thuộc mạnh vào độ phân giải — đo được
  trên cùng một cảnh: VGA **156.0**, XGA **80.8**, UXGA **55.2**. Ảnh tầng cao
  vì thế luôn nằm gần ngưỡng từ chối hơn dù nét như nhau.
- **`X-Audio-Format` cho `adpcm_stream`** đã đúng; nhánh `adpcm_wav` đã bỏ
  header đó. Không còn nợ ở đây.

## 🔴 Bẫy đã dính, đừng dính lại

- **Bảng phân vùng phải là `min_spiffs`.** Board từng chạy `huge_app` và mọi
  lượt OTA đều chết ở `Update.begin that bai: Partition Could Not be Found` —
  im lặng với server, chỉ thấy được khi đọc serial. Bảng phân vùng **chỉ ghi
  được qua USB**, không ghi được qua OTA. FQBN đúng:
  `esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=min_spiffs,FlashSize=16M,CDCOnBoot=cdc`
- **Mở COM10 là RESET board** (`rst:0x15 USB_UART_CHIP_RESET`) — nhưng từ
  `ota18` đã có `GET /diag/log`, nên **đừng mở cổng nữa**, đọc log qua mạng.
- **Wi-Fi và BLE dùng chung một radio.** Mỗi `wifiConnect()` quét sóng là cắt
  BLE: laptop nối vào được rồi ghi thì Windows trả
  `WinError -2147023673 operation was canceled`. Đang cấp mạng qua BLE thì
  `loop()` phải thoát sớm, đừng thử nối lại Wi-Fi.
- **Đừng gọi `BLEDevice::deinit()` trong `onWrite()`.** Ngăn xếp gửi
  write-response SAU khi callback trả về; giết nó trong callback nghĩa là việc
  THÀNH CÔNG mà bên kia thấy LỖI — app sẽ báo thất bại rồi người dùng bấm lại
  trong khi kính đã khởi động lại.
- **`bleak` trên Windows trả `device.name = None`** cho thiết bị chưa ghép đôi.
  Lọc theo tên là bỏ sót kính đang quảng bá ngay bên cạnh. Lọc theo **UUID dịch
  vụ** với `return_adv=True`.
- **`enum framesize_t` lệch hai bậc** so với mọi ví dụ trên mạng: bản
  esp32-camera của core 3.3.10 chèn thêm `FRAMESIZE_128X128` và
  `FRAMESIZE_320X320`. `VGA = 10`, không phải 8. Luôn đọc lại kích thước thật
  từ JPEG nhận được.
- **`apps/backend/.env` phải có đủ ba biến `CALLBACK_*`.** Thiếu thì **mọi**
  chức năng qua điện thoại báo "chưa phản hồi" sau 2 giây dù điện thoại đã xong
  việc từ giây 0.55 — và validator cho phép để trống cả ba nên không ai kêu.
- **Mọi tool trong `tools/` phải `reconfigure(encoding="utf-8")`** — stdout
  Windows là cp1252, và tool sẽ chạy XONG việc rồi chết ở lệnh `print` cuối,
  nhìn từ ngoài giống hệt "tool hỏng".
