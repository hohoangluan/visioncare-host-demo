# E2E — tốc độ từng chặng và độ chính xác, theo chức năng

Đo 2026-08-25 11:03 · thiết bị `glasses-01` · qua `api.visioncare-host.uk:443` (tunnel + TLS)

## Cấu hình lúc đo

| | |
|---|---|
| `RESPONSE_FORMAT` | `auto` |
| `AUDIO_PREROLL_MODE` | `warm_melodic` |
| `AUDIO_PREROLL_SECONDS` | 0.0 |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_INTENT_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_OCR_MODEL` | `gemini-3.5-flash` |

## Bảng 1 — một lượt, từng chặng (mili giây)

`headers` là lúc server trả dòng trạng thái; `tiếng đầu` là byte AUDIO đầu tiên (thứ người dùng thật sự nghe thấy); `tổng` là lúc byte cuối tới. `stt`/`intent`/`handler`/`action` đọc từ `turn_trace` của chính lượt đó, ghép bằng `turn_id`.

| Chức năng | mã | headers | **tiếng đầu** | tổng | stt | intent | handler | action | audio | nhả | đệm board | ý định |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ocr` | 200 | 468 | **491** | 10921 | 592 | 320 | 3965 | · | 4.51s | 0.43× | chờ hết! | ✅ |
| `find` | 200 | 246 | **256** | 30861 | 54 | 25 | — | · | 2.26s | 0.07× | chờ hết! | — |
| `money` | 200 | 221 | **235** | 11461 | 151 | 41 | 8660 | · | 3.14s | 0.28× | chờ hết! | ✅ |
| `space` | 200 | 596 | **596** | 4912 | 142 | 35 | 1834 | · | 4.30s | 1.00× | chờ hết! | ✅ |
| `hazard` | 200 | 646 | **646** | 1920 | 90 | 36 | 1 | · | 2.89s | 2.27× | 400ms | ✅ |
| `chat` | 200 | 391 | **425** | 21006 | 141 | 42 | 16058 | · | 7.45s | 0.36× | chờ hết! | ✅ |
| `nav_start` | 200 | 412 | **412** | 7234 | 93 | 1521 | 94 | 2012 | 6.61s | 0.97× | chờ hết! | ✅ |
| `nav_stop` | 200 | 258 | **269** | 6483 | 164 | — | — | 2003 | 6.17s | 0.99× | chờ hết! | — |
| `contact_call` | 200 | 309 | **309** | 5513 | 159 | 1618 | 19 | 2006 | 5.27s | 1.01× | chờ hết! | ✅ |
| `ride_quote` | 200 | 325 | **338** | 1897 | 56 | 1319 | 1 | — | 5.06s | 3.22× | 400ms | ✅ |
| `ride_confirm` | 200 | 401 | **413** | 1845 | 60 | 1315 | 1 | — | 2.79s | 1.93× | 400ms | ✅ |
| `music_play` | 200 | 205 | **205** | 1391 | 52 | 1039 | 1 | — | 5.46s | 4.60× | 400ms | ✅ |
| `music_stop` | 200 | 314 | **314** | 4886 | 45 | 14 | 35 | 2004 | 5.01s | 1.10× | chờ hết! | ✅ |
| `music_volume` | 200 | 707 | **707** | 5499 | 41 | 1172 | 31 | 2001 | 5.37s | 1.12× | 1500ms | ✅ |
| `unknown` | 200 | 179 | **193** | 2874 | 51 | 20 | 1337 | · | 3.27s | 1.21× | 1500ms | ✅ |
| `emergency_call` | 200 | 172 | **172** | 3667 | 46 | — | — | 2003 | 5.96s | 1.70× | 400ms | ✅ cổng từ khoá |

### Đọc bảng trên

**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. `—` = có bàn giao nhưng chặng đó không chạy tới nơi.

🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` — `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'.

Muốn đo thật cột này thì phải ghép đôi trước (`POST /internal/device/pair`) và có app Android chạy để trả `ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi động lại server** — xem câu hỏi còn mở #7.

**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ tuyệt đối đó đã bị gỡ mất.

## Bảng 2 — tổng hợp

| | |
|---|---|
| Tiếng đầu, trung vị | **0.33s** |
| Tiếng đầu, chậm nhất | 0.71s |
| Dưới 1 giây | 16/16 |
| Tỉ lệ nhả, thấp nhất | 0.07× |
| Số ca board phải chờ hết mới phát | 9/16 |
| **Độ chính xác ý định** | **13/13** (100%) |
| Số ca lỗi | 0/16 |

🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` bắt được vật cản hay không: những thứ đó đo ở `measurements/T24.md` và `measurements/H4.md`, không đo được bằng một vòng bench.
