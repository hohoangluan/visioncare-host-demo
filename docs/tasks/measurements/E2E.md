# E2E — tốc độ từng chặng và độ chính xác, theo chức năng

Đo 2026-08-27 01:41 · thiết bị `glasses-01` · qua `api.visioncare-host.uk:443` (tunnel + TLS)

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
| `ocr` | 200 | 303 | **314** | 2121 | 82 | 25 | — | · | 2.09s | 1.15× | 1500ms | — |
| `find` | 200 | 186 | **189** | 4194 | 56 | 21 | 1239 | · | 5.52s | 1.38× | 400ms | ✅ |
| `money` | 200 | 191 | **195** | 2731 | 57 | 19 | 1576 | · | 2.90s | 1.14× | 1500ms | ✅ |
| `space` | 200 | 296 | **308** | 2969 | 52 | 19 | 1124 | · | 4.08s | 1.53× | 400ms | ✅ |
| `hazard` | 200 | 193 | **196** | 4931 | 57 | 30 | 1443 | · | 8.35s | 1.76× | 400ms | ✅ |
| `chat` | 200 | 236 | **244** | 4933 | 54 | 24 | 757 | · | 10.05s | 2.14× | 400ms | ✅ |
| `nav_start` | 200 | 243 | **251** | 4695 | 58 | 1317 | 40 | 1976 | 9.05s | 2.03× | 400ms | ✅ |
| `nav_stop` | 200 | 243 | **255** | 2019 | 56 | — | — | 1436 | 3.16s | 1.78× | 400ms | — |
| `contact_call` | 200 | 868 | **881** | 3451 | 52 | 1237 | 35 | 1264 | 4.60s | 1.78× | 400ms | ✅ |
| `ride_quote` | 200 | 254 | **259** | 3533 | 55 | 1141 | 1 | — | 6.05s | 1.84× | 400ms | ✅ |
| `ride_confirm` | 200 | 181 | **187** | 313 | 48 | — | — | — | 6.68s | 50.86× | 400ms | — |
| `music_play` | 200 | 443 | **443** | 1838 | 53 | 1319 | 0 | — | 5.12s | 3.67× | 400ms | ✅ |
| `music_stop` | 200 | 175 | **180** | 2314 | 44 | 16 | 28 | 1262 | 3.01s | 1.41× | 400ms | ✅ |
| `music_volume` | 200 | 204 | **206** | 3336 | 44 | 900 | 37 | 1301 | 4.54s | 1.45× | 400ms | ✅ |
| `unknown` | 200 | 247 | **253** | 3284 | 53 | 19 | 1711 | · | 3.82s | 1.26× | 1500ms | ✅ |
| `emergency_call` | 200 | 202 | **202** | 3373 | 46 | — | — | 2540 🔴hết giờ | 4.31s | 1.36× | 400ms | ✅ cổng từ khoá |

### Đọc bảng trên

**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. `—` = có bàn giao nhưng chặng đó không chạy tới nơi.

🔴 **`X 🔴hết giờ` nghĩa là app Android nhận `202 Accepted` rồi KHÔNG trả `ActionResult` nào trong `VISIONCARE_FAST_ACTION_SECONDS`.** Con số đó là ĐỘ DÀI CỬA SỔ CHỜ, không phải tốc độ điện thoại. Đọc nhầm nó thành 'điện thoại phản hồi trong 2 giây' là kết luận ngược hẳn với sự thật — thực tế là **không phản hồi**.

🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` — `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'.

Muốn đo thật cột này thì phải ghép đôi trước (`POST /internal/device/pair`) và có app Android chạy để trả `ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi động lại server** — xem câu hỏi còn mở #7.

**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ tuyệt đối đó đã bị gỡ mất.

## Bảng 2 — tổng hợp

| | |
|---|---|
| Tiếng đầu, trung vị | **0.25s** |
| Tiếng đầu, chậm nhất | 0.88s |
| Dưới 1 giây | 16/16 |
| Tỉ lệ nhả, thấp nhất | 1.14× |
| Số ca board phải chờ hết mới phát | 0/16 |
| **Độ chính xác ý định** | **12/12** (100%) |
| Số ca lỗi | 0/16 |

🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` bắt được vật cản hay không: những thứ đó đo ở `measurements/T24.md` và `measurements/H4.md`, không đo được bằng một vòng bench.
