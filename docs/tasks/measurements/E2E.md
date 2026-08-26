# E2E — tốc độ từng chặng và độ chính xác, theo chức năng

Đo 2026-08-26 09:33 · thiết bị `bench-report` · qua `api.visioncare-host.uk:443` (tunnel + TLS)

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
| `ocr` | 200 | 226 | **235** | 6899 | 64 | 11 | 5401 | · | 4.51s | 0.68× | chờ hết! | ✅ |
| `find` | 200 | 182 | **192** | 4509 | 64 | 13 | 1766 | · | 5.93s | 1.37× | 400ms | ✅ |
| `money` | 200 | 195 | **201** | 3229 | 82 | 14 | 2111 | · | 3.07s | 1.01× | chờ hết! | ✅ |
| `space` | 200 | 177 | **181** | 4815 | 46 | 12 | 2013 | · | 5.94s | 1.28× | 1500ms | ✅ |
| `hazard` | 200 | 183 | **190** | 1099 | 62 | 13 | 0 | · | 2.81s | 3.07× | 400ms | ✅ |
| `chat` | 200 | 248 | **249** | 6273 | 74 | 14 | 1202 | · | 11.91s | 1.98× | 400ms | ✅ |
| `nav_start` | 200 | 211 | **217** | 2596 | 58 | 1050 | 27 | — | 4.00s | 1.68× | 400ms | ✅ |
| `nav_stop` | 200 | 216 | **225** | 318 | 52 | 13 | 0 | — | 2.99s | 29.35× | 400ms | ✅ |
| `contact_call` | 200 | 257 | **257** | 2994 | 59 | 1226 | 47 | — | 3.92s | 1.43× | 400ms | ✅ |
| `ride_quote` | 200 | 234 | **255** | 2736 | 63 | 1292 | 0 | — | 5.94s | 2.38× | 400ms | ✅ |
| `ride_confirm` | 200 | 187 | **197** | 326 | 58 | — | — | — | 7.19s | 51.70× | 400ms | — |
| `music_play` | 200 | 229 | **237** | 1633 | 62 | 1251 | 0 | — | 5.80s | 4.13× | 400ms | ✅ |
| `music_stop` | 200 | 240 | **259** | 1258 | 68 | 12 | 34 | — | 2.47s | 2.43× | 400ms | ✅ |
| `music_volume` | 200 | 193 | **200** | 1391 | 50 | 1075 | 21 | — | 2.39s | 1.99× | 400ms | ✅ |
| `unknown` | 200 | 163 | **177** | 3192 | 58 | 15 | 1784 | · | 3.53s | 1.16× | 1500ms | ✅ |
| `emergency_call` | 200 | 170 | **177** | 300 | 50 | — | — | — | 3.68s | 28.37× | 400ms | ✅ cổng từ khoá |

### Đọc bảng trên

**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. `—` = có bàn giao nhưng chặng đó không chạy tới nơi.

🔴 **`X 🔴hết giờ` nghĩa là app Android nhận `202 Accepted` rồi KHÔNG trả `ActionResult` nào trong `VISIONCARE_FAST_ACTION_SECONDS`.** Con số đó là ĐỘ DÀI CỬA SỔ CHỜ, không phải tốc độ điện thoại. Đọc nhầm nó thành 'điện thoại phản hồi trong 2 giây' là kết luận ngược hẳn với sự thật — thực tế là **không phản hồi**.

🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` — `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'.

Muốn đo thật cột này thì phải ghép đôi trước (`POST /internal/device/pair`) và có app Android chạy để trả `ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi động lại server** — xem câu hỏi còn mở #7.

**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ tuyệt đối đó đã bị gỡ mất.

## Bảng 2 — tổng hợp

| | |
|---|---|
| Tiếng đầu, trung vị | **0.21s** |
| Tiếng đầu, chậm nhất | 0.26s |
| Dưới 1 giây | 16/16 |
| Tỉ lệ nhả, thấp nhất | 0.68× |
| Số ca board phải chờ hết mới phát | 2/16 |
| **Độ chính xác ý định** | **14/14** (100%) |
| Số ca lỗi | 0/16 |

🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` bắt được vật cản hay không: những thứ đó đo ở `measurements/T24.md` và `measurements/H4.md`, không đo được bằng một vòng bench.
