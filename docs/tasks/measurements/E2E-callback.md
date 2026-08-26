# E2E — tốc độ từng chặng và độ chính xác, theo chức năng

Đo 2026-08-26 09:42 · thiết bị `glasses-01` · qua `api.visioncare-host.uk:443` (tunnel + TLS)

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
| `nav_stop` | 200 | 266 | **266** | 376 | 70 | 16 | 0 | — | 2.65s | 24.01× | 400ms | ✅ |
| `music_stop` | 200 | 181 | **187** | 3717 | 45 | 13 | 28 | 2009 🔴hết giờ | 4.89s | 1.38× | 400ms | ✅ |
| `music_volume` | 200 | 161 | **169** | 3131 | 40 | 1198 | 34 | 895 | 4.37s | 1.47× | 400ms | ✅ |

### Đọc bảng trên

**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. `—` = có bàn giao nhưng chặng đó không chạy tới nơi.

🔴 **`X 🔴hết giờ` nghĩa là app Android nhận `202 Accepted` rồi KHÔNG trả `ActionResult` nào trong `VISIONCARE_FAST_ACTION_SECONDS`.** Con số đó là ĐỘ DÀI CỬA SỔ CHỜ, không phải tốc độ điện thoại. Đọc nhầm nó thành 'điện thoại phản hồi trong 2 giây' là kết luận ngược hẳn với sự thật — thực tế là **không phản hồi**.

🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` — `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'.

Muốn đo thật cột này thì phải ghép đôi trước (`POST /internal/device/pair`) và có app Android chạy để trả `ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi động lại server** — xem câu hỏi còn mở #7.

**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ tuyệt đối đó đã bị gỡ mất.

## Bảng 2 — tổng hợp

| | |
|---|---|
| Tiếng đầu, trung vị | **0.19s** |
| Tiếng đầu, chậm nhất | 0.27s |
| Dưới 1 giây | 3/3 |
| Tỉ lệ nhả, thấp nhất | 1.38× |
| Số ca board phải chờ hết mới phát | 0/3 |
| **Độ chính xác ý định** | **3/3** (100%) |
| Số ca lỗi | 0/3 |

🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` bắt được vật cản hay không: những thứ đó đo ở `measurements/T24.md` và `measurements/H4.md`, không đo được bằng một vòng bench.
