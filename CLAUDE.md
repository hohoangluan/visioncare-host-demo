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

## Nạp firmware

Từ 2026-08-24: **OTA, không cắm dây**. Partition **`min_spiffs`** (bắt buộc —
`huge_app` không có slot OTA). Chi tiết ở `CLAUDE.md` của repo firmware.

```powershell
curl.exe -s http://<ip-board>/wifi/status      # board đang ở đâu, chạy bản nào
& $espota -i <ip-board> -p 3232 -a "visioncare-ota" -f <bin> -r
```

---

# 🔴 VIỆC CÒN GÁC — đọc trước khi lập kế hoạch

*Cập nhật 2026-08-25. Board `glasses-01` chạy `2026.08.25-ota12` trên mạng
`UIT Public`, loa đã cắm, điện thoại đã ghép đôi.*

## ✅ Đã đóng trong phiên 2026-08-25 — đừng lập kế hoạch lại

| Việc | Bằng chứng |
|---|---|
| OTA kéo qua internet | ota7/8/9/**10**/**11**/**12** — mỗi lần `0%→100%`, sha256 khớp |
| SSE `/events` phía firmware | `[SSE] Duong xuong /events da mo`, tự nối lại sau restart server trong **2.3 s** |
| **RAM khi nhiều phiên TLS** | Đo xong → [`docs/tasks/measurements/F6-ram.md`](docs/tasks/measurements/F6-ram.md). 🔴 Khối liền lớn nhất là **36 852 B**, KHÔNG phải 77 812 B như ghi cũ. Trần cứng **2 phiên**; phiên thứ ba luôn chết ở `malloc` |
| T24 worker vòng lặp | Đã viết + nối dây. Mức nguy hiểm về trong **thân response** `POST /frame`, không qua SSE |
| `call_incoming` / `call_ended` / `frame_request` phía firmware | Đã nối vào `onDeviceEvent()` |
| **F5 ảnh phân tầng** | Thi công xong: VGA mặc định, HD chỉ cho `ocr` qua `frame_request` |
| Sổ ghép đôi | Xuống đĩa (`storage/pairings.json`), sống sót qua restart |
| Đo độ trễ từ đường thật | [`measurements/E2E.md`](docs/tasks/measurements/E2E.md) — tiếng đầu trung vị **0.33 s**, **16/16 dưới 1 s**, ý định 15/15 |

## Chưa chạy trên phần cứng lần nào

| Việc | Cần gì để mở khoá |
|---|---|
| T24: fps thật, pin, tông có đè TTS không | bật chế độ canh rồi **nghe** trên board |
| Nút khẩn cấp 3 nhịp — request có tới server không | bấm nút thật ba nhịp |
| T19 cuộc gọi đến — kính có phát câu thông báo không | gọi vào điện thoại đã ghép |
| T23 quyền/cấu hình trên điện thoại thật | nạp app lên máy thật |

## Quyết định chờ người dùng

| # | Câu hỏi | Chặn |
|---|---|---|
| 3 | Cột "nhả": còn **3/16** ca board phải chờ hết mới phát (`ocr` 0.68×, `money` 1.02×, `unknown` 1.06×). **Phải nghe trên board** mới biết là "cà giật" hay chấp nhận được | T21 |
| 4 | Ngân sách riêng cho `ocr` (T15/H1 cố ý làm chậm hơn) — và giờ F5 cộng thêm một vòng xin ảnh tầng cao | T15 |
| 5 | `OTA_PASSWORD`/`WIFI_SETUP_AP_PASSWORD` viết cứng ⟹ mọi kính chung một mật khẩu | phát hành |
| 6 | Số máy khi sản xuất nhiều chiếc — mọi bản dựng đều `"01"` ⟹ **trùng `device_id`** | phát hành |
| 9 | `setInsecure()` ⟹ kính **không kiểm chứng chỉ** TLS. Phải ghim CA trước khi phát hành | phát hành |
| 8 | ⛔ Farefeed (T11) · geocode ai làm · P1 `contact_list` (T08) · nguồn mã lỗi P7 (T20) | 4 task cũ |

## Chưa viết

- **T26 — cấp Wi-Fi qua BLE** (chốt 2026-08-25). BLE **chỉ** thay khâu cấp
  mạng; mọi đường dữ liệu giữ trên Wi-Fi/TLS. Phải
  `esp_bt_controller_deinit()` ngay sau khi ghi NVS — NimBLE tốn 40-60 KB mà
  khối liền chỉ còn 36 852 B. Xem `docs/tasks/T25-ota-provisioning.md`.
- **`otaSetBusyProbe()` chưa nối dây** — OTA có thể nạp giữa lúc người dùng
  đang bấm nút.
- **Ngưỡng blur theo TỪNG TẦNG** (F5). `image_quality.py` đang dùng một bộ
  ngưỡng đo trên 1280×720 cho cả VGA lẫn HD. Nợ duy nhất còn lại của T17.

## 🔴 Bẫy đã dính, đừng dính lại

- **Mở COM10 là RESET board** (`rst:0x15 USB_UART_CHIP_RESET`), kể cả khi đã
  đặt `DtrEnable=$false`/`RtsEnable=$false` TRƯỚC `Open()`. Đọc serial trong
  lúc đang chờ board nối lại SSE = tự tay làm nó không bao giờ nối được. Theo
  dõi bằng `GET /devices` chứ đừng mở cổng.
- **`UIT Public` cách ly client** ⟹ không `curl` được vào IP LAN của board, và
  `espota` (đẩy qua LAN) **không dùng được**. Chỉ còn đường OTA kéo qua tunnel.
- **Mọi tool trong `tools/` phải `reconfigure(encoding="utf-8")`** — stdout
  Windows là cp1252, và tool sẽ chạy XONG việc rồi chết ở lệnh `print` cuối,
  nhìn từ ngoài giống hệt "tool hỏng".
