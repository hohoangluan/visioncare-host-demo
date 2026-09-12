# E2E — tốc độ từng chặng và độ chính xác, theo chức năng

Đo 2026-08-26 09:36 · thiết bị `glasses-01` · qua `api.visioncare-host.uk:443` (tunnel + TLS)

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
| `ocr` | 200 | 235 | **257** | 4611 | 62 | 10 | 2999 | · | 3.82s | 0.87× | chờ hết! | ✅ |
| `find` | 200 | 178 | **179** | 4115 | 51 | 14 | 1550 | · | 4.82s | 1.22× | 1500ms | ✅ |
| `money` | 200 | 148 | **157** | 2111 | 54 | 12 | 1183 | · | 2.75s | 1.40× | 400ms | ✅ |
| `space` | 200 | 163 | **173** | 4318 | 60 | 11 | 1026 | · | 7.01s | 1.69× | 400ms | ✅ |
| `hazard` | 200 | 245 | **245** | 1171 | 62 | 10 | 0 | · | 2.57s | 2.77× | 400ms | ✅ |
| `chat` | 200 | 243 | **250** | 5250 | 70 | 14 | 1222 | · | 11.08s | 2.21× | 400ms | ✅ |
| `nav_start` | 200 | 211 | **220** | 4003 | 65 | 1512 | 76 | 1228 | 8.95s | 2.36× | 400ms | ✅ |
| `nav_stop` | 200 | 147 | **158** | 3613 | 44 | — | — | 2001 🔴hết giờ | 5.05s | 1.46× | 400ms | — |
| `contact_call` | 200 | 183 | **199** | 4693 | 55 | 1177 | 39 | 2006 🔴hết giờ | 6.37s | 1.41× | 400ms | ✅ |
| `ride_quote` | 200 | 207 | **216** | 2755 | 61 | 1269 | 0 | — | 6.54s | 2.57× | 400ms | ✅ |
| `ride_confirm` | 200 | 181 | **183** | 295 | 45 | — | — | — | 7.02s | 61.49× | 400ms | — |
| `music_play` | 200 | 209 | **219** | 1375 | 51 | 1015 | 0 | — | 5.46s | 4.68× | 400ms | ✅ |
| `music_stop` | 200 | 233 | **248** | 4749 | 51 | 16 | 40 | 2002 🔴hết giờ | 4.40s | 0.97× | chờ hết! | ✅ |
| `music_volume` | 200 | 242 | **247** | 5257 | 48 | 1487 | 25 | 2019 🔴hết giờ | 5.82s | 1.16× | 1500ms | ✅ |
| `unknown` | 200 | 193 | **193** | 3367 | 62 | 18 | 1936 | · | 3.50s | 1.10× | chờ hết! | ✅ |
| `emergency_call` | 200 | 231 | **262** | 3758 | 66 | — | — | 2009 🔴hết giờ | 5.71s | 1.62× | 400ms | ✅ cổng từ khoá |

### Đọc bảng trên

**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. `—` = có bàn giao nhưng chặng đó không chạy tới nơi.

🔴 **`X 🔴hết giờ` nghĩa là app Android nhận `202 Accepted` rồi KHÔNG trả `ActionResult` nào trong `VISIONCARE_FAST_ACTION_SECONDS`.** Con số đó là ĐỘ DÀI CỬA SỔ CHỜ, không phải tốc độ điện thoại. Đọc nhầm nó thành 'điện thoại phản hồi trong 2 giây' là kết luận ngược hẳn với sự thật — thực tế là **không phản hồi**.

🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` — `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'.

Muốn đo thật cột này thì phải ghép đôi trước (`POST /internal/device/pair`) và có app Android chạy để trả `ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi động lại server** — xem câu hỏi còn mở #7.

**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ tuyệt đối đó đã bị gỡ mất.

## Bảng 2 — tổng hợp

| | |
|---|---|
| Tiếng đầu, trung vị | **0.22s** |
| Tiếng đầu, chậm nhất | 0.26s |
| Dưới 1 giây | 16/16 |
| Tỉ lệ nhả, thấp nhất | 0.87× |
| Số ca board phải chờ hết mới phát | 3/16 |
| **Độ chính xác ý định** | **13/13** (100%) |
| Số ca lỗi | 0/16 |

🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` bắt được vật cản hay không: những thứ đó đo ở `measurements/T24.md` và `measurements/H4.md`, không đo được bằng một vòng bench.
