# Định dạng bắt buộc để demo đúng luồng chức năng

Tài liệu này là hợp đồng bắt buộc giữa **server kính** (repo `Sever_test`, External
API Client) và **App Communication Server** (repo `app_demo_backend`) cho buổi demo.
Mọi giá trị dưới đây là giá trị thật đang chạy, không phải ví dụ.

## 1. Sơ đồ hệ thống đang chạy

```
Kính (ESP32)
   │  HTTP
   ▼
Server kính  = Sever_test          uvicorn app:app  →  127.0.0.1:8000
   │  HTTPS  (External API Client)
   ▼
https://app.visioncare-host.uk     ← Cloudflare Tunnel (Windows service "Cloudflared")
   │
   ▼
App Communication Server = app_demo_backend   uvicorn app.main:app → 0.0.0.0:8001
   │  ├── PostgreSQL  docker container `app-demo-postgres-1`  → 127.0.0.1:5432
   │  └── FCM (DELIVERY_TRANSPORT=fcm, project `your-537d3`)
   ▼
App Android `com.youreyes.app` trên điện thoại thật
   │  POST /api/v1/device/report
   ▼
App Communication Server  → request_state = succeeded / failed
```

**Điểm dễ sai nhất:** tunnel `app.visioncare-host.uk` trỏ tới **localhost:8001**,
không phải 8000. Port 8000 là của server kính (`Sever_test`). Đã kiểm chứng bằng
probe: dựng HTTP server trên 8001 → tunnel trả đúng nội dung của 8001.

## 2. Giá trị bắt buộc — không được đổi giữa buổi demo

| Thành phần | Giá trị |
|---|---|
| Base URL công khai | `https://app.visioncare-host.uk` |
| Public client token (server kính dùng) | `f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY` |
| Device bearer token (app Android dùng) | `_W7kNZRwdQC9jawhJr7ji_TJ6JzUI5igkHQrE6oAQKE` |
| `user_id` demo | `user-100` |
| `device_id` Android | `device-100` |
| **`device_id` kính (đã pairing)** | **`glasses-123`** |
| Port backend cục bộ | `8001` (tunnel trỏ vào đây) |
| Port server kính cục bộ | `8000` |

Hai id-space khác nhau, không được lẫn:

- `device_id` **Android** (`device-100`) — dùng ở `/api/v1/device/register`, `/report`.
- `device_id` **kính** (`glasses-123`) — dùng ở mọi `/api/v1/service/*`.

`glasses-123` đã được ghép nối với `user-100` (xác nhận `{"linked": true}`).

## 3. Thứ tự bắt buộc để demo chạy đúng

Sai thứ tự → request bị `failed` với `DELIVERY_FAILED` hoặc `GLASSES_DEVICE_NOT_LINKED`.

### Cách nhanh — một lệnh

```powershell
D:\Study\innostar\Sever_test\start-demo.ps1
```

Script dựng Postgres → backend `8001` → kiểm tra tunnel → server kính `8000` →
khẳng định lại pairing `glasses-123 ↔ user-100`. Cái gì đang chạy rồi thì bỏ
qua, không dựng trùng. Log ra `Sever_test\logs\`. Thêm `-SkipGlasses` khi chỉ
cần backend.

Script **không** làm được phần trên điện thoại — vẫn phải mở app và bấm
**Đăng ký** để FCM token còn sống.

### Từng bước thủ công

1. **Postgres up**:
   ```powershell
   docker start app-demo-postgres-1
   # hoặc: docker compose -f D:\Study\innostar\app_demo_backend\infra\compose.yaml up -d postgres
   ```
2. **Backend up trên 8001** (không phải 8000 — 8000 là của server kính):
   ```powershell
   cd D:\Study\innostar\app_demo_backend\apps\backend
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8001
   ```
   Kiểm tra: `GET https://app.visioncare-host.uk/health/ready` → `{"status":"ok"}`.
   Trả `502` = backend chưa lên; trả `404` = tunnel đang trỏ nhầm port.
3. **Tunnel**: chạy sẵn dưới dạng Windows service `Cloudflared`.
   ```powershell
   Get-Service Cloudflared    # kỳ vọng Running
   Start-Service Cloudflared  # nếu Stopped
   ```
4. **Server kính up trên 8000** (đọc `models/.env`, đã có sẵn 3 biến VISIONCARE).
   Mất 60-90s để nạp STT + TTS trước khi `/health` trả `200`:
   ```powershell
   cd D:\Study\innostar\Sever_test
   .\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
   ```
5. **App Android**: mở app → tab **Đăng ký** → `Server URL = https://app.visioncare-host.uk`,
   `user_id = user-100`, `device_id = device-100` → bấm **Đăng ký**.
   Bước này bắt buộc: nó nạp FCM push token mới. Token cũ của lần cài trước đã
   chết, backend trả `DELIVERY_FAILED / NotRegistered`.
6. **Pairing kính**: trong app, tab ghép nối kính → nhập `glasses-123` → Lưu.
   Tương đương lệnh:
   ```bash
   curl -X POST https://app.visioncare-host.uk/api/v1/device/glasses/link \
     -H "Authorization: Bearer _W7kNZRwdQC9jawhJr7ji_TJ6JzUI5igkHQrE6oAQKE" \
     -H "Content-Type: application/json" \
     -H "User-Agent: VisionCare-Glasses/1.0" \
     -d '{"user_id":"user-100","device_id":"glasses-123"}'
   ```
7. **Giữ app Android ở foreground / không force-stop**. App bị force-stop thì FCM
   không đánh thức được → request treo `processing` tới `timed_out`.

### Gửi lệnh như kính thật

```bash
curl -X POST http://127.0.0.1:8000/process \
  -F "image=@storage/request1.jpg" \
  -F "audio=@command.wav" \
  --output response.mp3
```

## 4. Định dạng bắt buộc của mọi request từ server kính

```http
POST https://app.visioncare-host.uk/api/v1/service/<action>
Authorization: Bearer f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY
Content-Type: application/json
Accept: application/json
User-Agent: VisionCare-Glasses/1.0
```

**`User-Agent` là bắt buộc, không phải tùy chọn.** Cloudflare đứng trước tunnel
chặn user-agent mặc định của thư viện HTTP (`Python-urllib/3.x`) bằng
**error 1010 `browser_signature_banned`** — trả `403` kèm body HTML/JSON của
Cloudflare, request không bao giờ tới backend. Đã tái hiện: cùng một script,
thiếu `User-Agent` → `403` ở cả 5 action; thêm `User-Agent` → `202` hết.
`services/visioncare_client.py:38` đã set sẵn `VisionCare-Glasses/1.0` — bất kỳ
client nào khác (script test, curl trong CI, Postman collection) cũng phải set.

Body luôn có đúng 2 trường chung, cộng trường riêng của từng action:

```json
{
  "device_id": "glasses-123",
  "request_id": "<UUID4 sinh mới mỗi lệnh>"
}
```

Ràng buộc bắt buộc:

- `device_id` phải là `glasses-123`. Chưa pairing → `404 GLASSES_DEVICE_NOT_LINKED`.
- `request_id` phải là UUID hợp lệ, **duy nhất cho mỗi lệnh mới**. Gửi lại cùng
  `request_id` + cùng body = idempotent (không thực thi lại). Cùng `request_id`
  nhưng body khác = `409 REQUEST_ID_CONFLICT`.
- Schema là `extra="forbid"`: thêm bất kỳ trường lạ nào → `400 INVALID_REQUEST`.
- Không được gửi `user_id` trong `/api/v1/service/*`. Server tự resolve
  `glasses-123 → user-100`.

### Body từng action

| Endpoint | Trường riêng bắt buộc | Trường tùy chọn |
|---|---|---|
| `POST /api/v1/service/ride/quote` | `current_location{lat,lng}`, `destination{address}` hoặc `destination{lat,lng}` | — |
| `POST /api/v1/service/ride/confirm` | `quote_id`, `confirm` (bool) | — |
| `POST /api/v1/service/music/play` | `song` (non-empty) | `volume` 0–100 |
| `POST /api/v1/service/music/stop` | — | — |
| `POST /api/v1/service/music/volume` | đúng **một** trong `direction` (`up`/`down`) **hoặc** `level` (0–100) | — |
| `POST /api/v1/service/navigation/start` | `destination{address}` hoặc `destination{lat,lng}` | — |
| `POST /api/v1/service/navigation/stop` | `navigation_id` | — |
| `POST /api/v1/service/emergency/call` | — | `number` |
| `POST /api/v1/service/contact/call` | `name` (non-empty) | `contact_id` |

`destination`: gửi `address`, hoặc gửi `lat`+`lng` cùng nhau. Không được gửi mỗi `lat`.

## 5. Định dạng bắt buộc của response

### 5.1. Tiếp nhận — `HTTP 202`

```json
{
  "status": "ok",
  "data": {
    "request_id": "6ce98b3c-d005-4e59-9495-9650a5a87234",
    "operation": "music_volume",
    "request_state": "processing",
    "status_url": "/api/v1/requests/6ce98b3c-d005-4e59-9495-9650a5a87234",
    "accepted_at": "2026-08-03T18:35:00.257767Z"
  }
}
```

`202` **chỉ có nghĩa là đã nhận**, không có nghĩa là đã làm xong. Kết quả thật
nằm ở mục 5.2.

### 5.2. Kết quả cuối — `GET /api/v1/requests/{request_id}`

```http
GET https://app.visioncare-host.uk/api/v1/requests/<request_id>
Authorization: Bearer f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY
```

```json
{
  "status": "ok",
  "data": {
    "request_id": "...",
    "operation": "music_volume",
    "request_state": "processing | succeeded | failed | timed_out",
    "result": null,
    "error": null,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

`result` theo từng `operation`:

| `operation` | `result` khi `succeeded` |
|---|---|
| `ride_quote` | `{quote_id, product_type, price_estimate{currency,amount}, eta_minutes, expires_at}` |
| `ride_confirm` | `{quote_id, ride_id, ride_status}` |
| `music_play` | `{track_id, title, artist, playback_state, volume}` |
| `music_stop` | `{playback_state: "stopped"}` |
| `music_volume` | `{volume_state: "changed", level}` |
| `navigation_start` | `{navigation_id, navigation_state, travel_mode: "walking", destination}` |
| `navigation_stop` | `{navigation_id, navigation_state: "stopped"}` |
| `emergency_call` | `{emergency_state, attempt, answered, cycle, contact, sms_sent}` |
| `contact_call` | `{call_state, contact_name, phone_number}` |

### 5.3. Lỗi

Lỗi nghiệp vụ (envelope chuẩn):

```json
{ "status": "error", "error": { "code": "GLASSES_DEVICE_NOT_LINKED", "message": "...", "details": {} } }
```

Lỗi xác thực (`401`/`403`) **không** theo envelope trên: `{"detail": "UNAUTHORIZED"}`.

Mã lỗi hay gặp trong demo:

| Code | Nguyên nhân thực tế |
|---|---|
| `GLASSES_DEVICE_NOT_LINKED` | Quên bước 4 mục 3, hoặc gửi sai `device_id` |
| `DELIVERY_FAILED` + `NotRegistered` | App Android chưa cài / chưa bấm Đăng ký lại sau khi cài |
| `REQUEST_ID_CONFLICT` | Tái sử dụng `request_id` với body khác |
| `INVALID_REQUEST` | Gửi thừa trường, hoặc thiếu trường riêng của action |
| Cloudflare `1010` (`403`, không có `error.code`) | Quên header `User-Agent` |
| `QUOTE_NOT_FOUND` | `ride/confirm` dùng `quote_id` không lấy từ `ride/quote` |
| `NAVIGATION_NOT_FOUND` | `navigation/stop` dùng `navigation_id` không lấy từ `navigation/start` |

## 6. Server kính đọc kết quả thật, không dừng ở `202`

`202` chỉ nói host đã nhận lệnh. Mỗi handler giờ chạy qua
`handlers/action_flow.py::run_action`, trả **hai mảnh text**:

1. Câu xác nhận phát ngay — người dùng biết lệnh đã đi, và nghe lại được thứ
   STT hiểu ("Đang tìm bài hát Nơi này có anh") để bắt lỗi nghe nhầm sớm.
2. Câu kết quả thật, sau khi poll `GET /api/v1/requests/{request_id}` mỗi 1s
   tới khi `request_state != "processing"`.

Ngân sách chờ: `VISIONCARE_RESULT_TIMEOUT_SECONDS` (mặc định 25s, chỉnh qua
`models/.env`). Cố ý ngắn hơn deadline phía host (`contact_call` 60s,
`music_play` 45s) để câu trả lời không treo tới lúc host tự `timed_out`.

Câu nói cho từng trạng thái nằm ở `handlers/result_speech.py`. Ví dụ thật:

| Tình huống | Người dùng nghe |
|---|---|
| `music_volume` thành công | "Đang chỉnh âm lượng. **Âm lượng hiện ở mức 66 phần trăm.**" |
| `music_play` không ra tiếng | "Đang mở nhạc, tìm bài Nơi này có anh. Nếu màn hình đang bật, hãy nhấn vào thông báo trên điện thoại. **Đã mở ứng dụng nhạc nhưng chưa phát được. Vui lòng nhấn vào thông báo trên điện thoại rồi bấm nút phát.**" |
| `ride_quote` thành công | "Đang gọi xe. **Đã mở ứng dụng đặt xe. Vui lòng nhấn vào thông báo trên điện thoại, kiểm tra lại điểm đón và điểm đến trong ứng dụng rồi xác nhận để đặt xe.**" (cố ý **không** đọc giá — xem mục đặt xe) |
| `nav_stop` thành công | "Đang dừng chỉ đường. **Đã dừng chỉ đường.**" |
| `contact_call` không có trong danh bạ | "**Không tìm thấy người này trong danh bạ.**" |
| Host không trả lời trong 25s | "**Điện thoại chưa phản hồi, vui lòng kiểm tra thông báo trên điện thoại.**" |

### Không bao giờ để người dùng chờ trong im lặng

Người khiếm thị không nhìn được màn hình: một quãng im 30 giây không phân biệt
được với "máy hỏng rồi". Nên mọi quãng chờ đều có tiếng nói xen vào.

Ba loại câu, đừng lẫn:

| Loại | Khi nào | Ví dụ |
|---|---|---|
| **Câu chào** | Ngay khi gói tin vào server, trước cả STT | "Đã nhận yêu cầu của bạn, hệ thống đang xử lý." |
| **Báo tiến độ** | Ngay khi có thông tin mới | "Đã tìm được bài X, đang phát." |
| **Trấn an** | Chỉ khi chờ đã lâu | "Vẫn đang chờ điện thoại phản hồi." |

#### Câu chào: audio dựng sẵn, phát ở 0.0s

`app.py` ghép `_RECEIVED_MESSAGE` vào TRƯỚC `router.resolve_speech(...)`. Vì
`chain` lười, STT chỉ chạy sau khi TTS đã lấy xong câu chào — người dùng nghe
tiếng trong lúc STT còn đang chạy, thay vì im 2-3 giây đầu.

Chỉ làm được vì audio của nó **đã dựng sẵn** (xem mục dưới). Tổng hợp lúc chạy
thì chính nó lại là quãng chờ mới, đúng thứ nó sinh ra để xoá.

Câu chào dài **2.72s** audio, lớn hơn đệm `AUDIO_PREROLL_SECONDS` (2.0s), nên
byte đầu rời server ngay. Ngắn hơn đệm là mất sạch cái lợi — `preload_models()`
log cảnh báo nếu vậy.

#### Trấn an: giãn dần, không nhịp đều

| Tham số (`config.py`) | Mặc định |
|---|---|
| `SPEECH_FIRST_NOTICE_SECONDS` | 4.0 |
| `SPEECH_NOTICE_INTERVAL_SECONDS` | 9.0 |
| `SPEECH_NOTICE_BACKOFF` | 1.4 |
| `SPEECH_NOTICE_MAX_INTERVAL_SECONDS` | 18.0 |

Nhịp đều 4s trước đây nghe **dồn dập**: giãn cách tính từ lúc đẩy câu ra, mà mỗi
câu đọc lên mất 2-3 giây, nên chỉ còn ~1 giây im lặng giữa hai câu — nói nhiều
hơn cả nội dung thật. Giờ với `music_play` chờ 40s: **4 câu** (mốc 4s, 13s, 26s,
40s) thay vì 10 câu.

Cả hai chỗ biết chờ (`handlers/waiting.py` chờ Gemini, `handlers/action_flow.py`
chờ điện thoại) dùng chung `waiting.notice_delays()` — người dùng nghe chung một
cái loa, không quan tâm bên trong đang chờ ai.

Danh sách câu trấn an **quay vòng** và **không trùng câu chào**: nghe lại gần y
hệt thì tưởng máy phát lại chứ không phải đang chạy tiếp.

#### Dấu "câu này trọn vẹn" (`\n`)

`tts._sentences()` chỉ cắt ở dấu kết câu **kèm khoảng trắng theo sau**, nên câu
cuối của một mảnh text phải nằm chờ mảnh sau. Với Gemini thì mảnh sau tới ngay;
với handler thì mảnh sau là câu trấn an cả chục giây nữa.

Nên `action_flow._utterance()` và `waiting.with_progress_notice()` thêm `\n` vào
cuối mỗi câu, và `_sentences()` **không áp luật gộp câu ngắn** khi cắt ở `\n`.
Thiếu dấu này thì "Đang gọi xe." (12 ký tự) nằm im tới lúc câu trấn an xuất hiện
rồi hai câu bung ra một lượt — đúng triệu chứng "im rồi nói dồn" đo được lúc chạy
thật.

Không dùng luật "hễ hết mảnh mà có dấu chấm thì cắt": tiếng Việt dùng dấu chấm
phân cách hàng nghìn ("50.000 đồng") và Gemini đánh số đầu dòng ("1. ").

#### Số đo thật (server đang chạy, 04/08/2026)

| Lệnh | intent | ttfb | Quãng im dài nhất |
|---|---|---|---|
| "hôm nay là ngày mấy" | `chat` | 0.02s | 1.44s |
| "kể tôi nghe một câu chuyện cười ngắn" | `chat` | 0.02s | 1.43s |
| "dừng nhạc đi" | `music_stop` | 0.03s | 3.15s (dưới mốc 4s nên không chèn câu nào) |
| "dừng chỉ đường" | `nav_stop` | 0.04s | không có |

### Audio dựng sẵn cho câu nói cố định

Phần lớn thứ người dùng nghe **không phải do model viết ra**: câu chào, câu xác
nhận, câu trấn an, câu báo lỗi, câu nhắc bấm thông báo đều viết cứng trong code.
Trước đây chúng vẫn đi qua TTS như mọi câu khác, nên đúng những câu sinh ra để
lấp quãng chờ lại tự tạo thêm quãng chờ.

`pipeline/phrases.py` tổng hợp chúng **một lần** lúc khởi động rồi giữ PCM lại:
trong RAM cho lượt chạy này, trên đĩa (`models/.cache/tts_phrases`) cho các lần
sau. Lúc chạy, `tts._sentence_pcm()` chỉ còn cắt bytes ra gửi.

Đo thật (VieNeu-TTS v3 Turbo, ONNX/CPU):

| | Tổng hợp lúc chạy | Lấy sẵn |
|---|---|---|
| "Đã nhận yêu cầu của bạn, hệ thống đang xử lý." | 1.09s | 0.0000s |
| "Đang gọi xe." | 0.43s | 0.0000s |
| "Nếu màn hình đang bật, hãy nhấn vào thông báo trên điện thoại." | 1.23s | 0.0000s |
| **6 câu** | **5.01s** | **0.0002s** |

Khởi động: lần đầu **89.9s** cho 90 câu, các lần sau **1.3s** (đọc từ đĩa). Chạy
đồng bộ, cố ý — làm ở luồng nền thì có hai luồng cùng gọi vào một phiên ONNX.

**Nguồn chữ chỉ một chỗ.** Mỗi module khai `STATIC_SPEECH` trỏ vào đúng hằng số
của nó, `phrases.collect()` gom lại. Chép chữ sang chỗ khác thì sửa một chỗ là
chỗ kia trượt cache trong im lặng — triệu chứng đúng bằng thứ cache này sinh ra
để chữa.

**Khoá phải khớp chuỗi thật lúc chạy.** `collect()` cắt câu bằng đúng
`tts._sentences()` mà đường phát dùng, mỗi hằng số một lượt riêng. Nối chúng lại
rồi cắt một thể sẽ ra kết quả khác (luật gộp câu ngắn dính câu này vào câu kia)
và khoá dựng ra không bao giờ được tra tới. `tests/test_phrases.py` kiểm đúng
điểm này.

Câu có biến (tên bài, tên người, địa chỉ) vẫn tổng hợp lúc chạy, nhưng thường bị
tách thành nhiều câu nên nửa cố định vẫn trúng cache: "Đang mở nhạc, tìm bài X."
tổng hợp thật, còn "Nếu màn hình đang bật, hãy nhấn vào thông báo trên điện
thoại." lấy sẵn.

Hai cái bẫy đã dính thật:

1. **File cache cụt bị tin.** Bộ test ghi đè PCM 2 byte vào thư mục cache thật;
   vì "khác rỗng" nên lần chạy server sau nạp lại nguyên xi — server im lặng ở
   đúng những câu đáng lẽ phát ngay, không lỗi, không log. Giờ file ngắn hơn
   `_MIN_CACHED_SECONDS` (0.2s) bị coi là hỏng và dựng lại.
2. **Cache là biến toàn cục của tiến trình.** Một test gọi `preload_models()` là
   nạp đầy nó cho mọi test sau. `tests/conftest.py` dọn cache và trỏ
   `PHRASE_CACHE_DIR` sang `tmp_path` trước mỗi test.

Tắt bằng `TTS_PRERENDER=0` trong `models/.env` nếu chỉ cần server lên nhanh.

### Chat: chỉ làm đúng phần việc câu hỏi cần

Bộ phân loại intent (`pipeline/intent.py`) đã gọi model một lần trên câu lệnh,
nên hai cờ `needs_location` / `needs_web` được trả về trong **chính lần gọi đó**
— không tốn thêm lượt gọi nào để biết câu này cần gì.

| Câu hỏi | location | web | Đo thật |
|---|---|---|---|
| "kể chuyện cười đi" | ✗ | ✗ | 0.7s, không cần cả câu trấn an |
| "thủ đô Việt Nam là gì" | ✗ | ✗ | — |
| "2 cộng 2 bằng mấy" | ✗ | ✗ | — |
| "giá vàng hôm nay" | ✗ | ✓ | — |
| "tin tức hôm nay có gì" | ✗ | ✓ | — |
| "tôi đang ở đâu" | ✓ | ✗ | — |
| "chỗ này là chỗ nào" | ✓ | ✗ | — |
| "quán cà phê gần đây" | ✓ | ✓ | — |
| "hôm nay trời thế nào" | ✓ | ✓ | 2.4s |

**"Gần nhất" luôn là gần chỗ người dùng đứng.** Mọi cách nói mang nghĩa đó đều
bật `needs_location`, không cần người dùng đọc ra địa chỉ: "gần nhất", "gần
đây", "quanh đây", "gần chỗ tôi", "ở đây", "chỗ này", "lân cận", "xung quanh".
Bỏ cờ này thì model không có mốc nào để tính gần xa và trả lời theo một thành
phố nó tự chọn. Đo thật 8 câu, đúng 8:

| Câu | loc | web |
|---|---|---|
| "nhà thuốc gần nhất ở đâu" | ✓ | ✓ |
| "có quán ăn nào quanh đây không" | ✓ | ✓ |
| "trạm xe buýt gần nhất" | ✓ | ✓ |
| "tìm quán cà phê gần chỗ tôi" | ✓ | ✓ |
| "siêu thị lân cận có gì" | ✓ | ✓ |
| "chỗ này là chỗ nào" | ✓ | ✗ |
| "thủ đô nước Pháp là gì" | ✗ | ✗ |
| "kể chuyện cười đi" | ✗ | ✗ |

Bật cả hai cho mọi câu thì "kể chuyện cười đi" cũng phải chờ lấy vị trí và tra
Google. Tắt cả hai thì "hôm nay trời thế nào" nhận về thời tiết model tự bịa.

Vị trí lấy qua `POST /api/v1/service/location/get`, cache 5 phút. **Cache cả lần
hỏng** (thử lại sau 60s) — không cache thì điện thoại tắt định vị là mọi lượt
chat phải chờ hết timeout trước khi model nói được câu nào.

`LocationGetHandler` reverse-geocode toạ độ thành địa chỉ (`Geocoder`, timeout
5s, hỏng thì trả `address: null`). Tốn thêm ~1s nhưng cần thiết: chỉ đưa toạ độ
trần thì model quy về thành phố lớn gần nhất — đo thật, Tân Triều (Đồng Nai) bị
trả lời thành TP.HCM, lệch khoảng 20 km, mà người khiếm thị không có cách nào
nhận ra câu trả lời là của nơi khác. Sau khi có địa chỉ: "Hôm nay ở Đồng Nai có
mây, chiều tối và đêm có mưa rào và dông."

Địa chỉ bị cắt bỏ Google Plus Code ở đầu (`2R5J+X8M, Ấp 1 ĐT768, ...`) — đó là
toạ độ lưới, đọc lên thành rác.

Prompt phải nói thẳng **cấm hỏi lại người dùng đang ở đâu**. Chỉ đưa vị trí vào
prompt là chưa đủ: model vẫn hỏi ngược "bạn muốn xem dự báo thời tiết ở đâu?",
mà người khiếm thị không đọc bản đồ để trả lời.

### Gợi ý địa điểm: bắt tra trước khi được nêu tên

Câu hỏi kiểu "gần đây có quán ăn ngon không", "có hiệu thuốc nào gần đây không"
đi qua cùng đường `needs_location` + `needs_web`.

Cạm bẫy đã dính: prompt bảo model "nêu 2-3 chỗ, mỗi chỗ nói tên, loại hình và
cách bao xa" — đó là một công thức model **tự bịa ra được**, nên nó trả lời
trong 0.7s với những cái tên không tồn tại, trong khi lượt thời tiết có tra thật
mất 5.3s. Kiểm bằng `grounding_metadata.web_search_queries`: lượt bịa không có
truy vấn nào.

Cách sửa: bỏ công thức, thay bằng lệnh cấm —

> "TUYỆT ĐỐI không nêu tên địa điểm, quán, cửa hàng, thương hiệu, con số, giá
> hay khoảng cách nào không có trong kết quả tra cứu. Thà nói ít mà đúng."

Sau đó kết quả ra từ tra cứu thật: "Nhà hàng Lẩu Dê & Hải Sản Tân Triều, Tỉnh lộ
768, xã Tân Bình", "Nhà thuốc FPT Long Châu, 571 Tỉnh lộ 767, Ấp An Chu".

Kiểm tra nhanh xem một câu trả lời có thật sự tra hay không:

```python
r = client.models.generate_content(model=..., contents=[...], config=tool_cfg)
gm = r.candidates[0].grounding_metadata
print(gm.web_search_queries, len(gm.grounding_chunks or []))
```

Rỗng nghĩa là model trả lời bằng trí nhớ — mọi tên riêng trong câu đó đều đáng ngờ.

Câu `"Bạn tra được Google..."` chỉ dán vào prompt khi lượt đó thật sự bật tool.
Dán vào lượt không có tool là dạy model nói dối về thứ nó vừa làm.

### Grounding tính hạn mức RIÊNG THEO TỪNG MODEL

Đây là chỗ mất nhiều thời gian nhất để tìm ra. Cùng một API key, cùng câu hỏi,
chỉ khác model:

| Model | `google_search` |
|---|---|
| `gemini-3.1-flash-lite` | ❌ `429 RESOURCE_EXHAUSTED` |
| `gemini-2.0-flash` | ❌ `429` |
| `gemini-flash-latest` | ❌ `429` |
| `gemini-2.5-flash` | ✅ |
| `gemini-2.5-flash-lite` | ✅ |

Lượt gọi **không** grounding trên `gemini-3.1-flash-lite` vẫn trả `200` bình
thường — nên `429` ở đây không phải key hết hạn mức, mà là hạn mức grounding
của riêng model đó.

Vì vậy `config.GEMINI_SEARCH_MODEL` tách khỏi `config.GEMINI_MODEL`: lượt có tra
Google chạy trên `gemini-2.5-flash-lite`, mọi lượt khác vẫn dùng model nhanh
nhất. Đổi model chính mà quên đổi cái này là search chết im lặng (rơi vào nhánh
dự phòng, người dùng nghe "chưa tra cứu được" mà không ai biết vì sao).

Kết quả thật sau khi tách:

> "Hôm nay thứ ba ngày 4 tháng 8 năm 2026, ở Thành phố Hồ Chí Minh trời nhiều
> mây và có khả năng mưa rào vào buổi chiều tối. Nhiệt độ cao nhất khoảng 34 độ
> C và thấp nhất khoảng 25 độ C."

Mảnh đầu tới ở 5.2s (thời tiết) và 2.8s (giá vàng) — chậm hơn lượt không tra
(0.7s) đúng bằng một vòng grounding, nên câu trấn an ở 1.5s là bắt buộc.

### Nhánh dự phòng khi tra cứu hỏng

Tra hỏng thì `handlers/chat.py` gọi lại **không** tra cứu, kèm chỉ thị nói thẳng
là chưa tra được và cấm đoán. Kết quả thật:

> "Hiện tại tôi chưa tra cứu được thông tin thời tiết trực tiếp cho bạn lúc này.
> Bạn có thể cảm nhận nhiệt độ bên ngoài hoặc hỏi thăm những người xung quanh."

Không có nhánh này thì người dùng chỉ nghe "Có lỗi xảy ra, vui lòng thử lại" —
không biết hỏng mạng, hỏng máy hay câu hỏi sai.

Vì sao phải cấm đoán: trí nhớ model dừng ở thời điểm huấn luyện. Hỏi "hôm nay
ngày mấy" mà không tra, nó trả lời **"Thứ Năm, ngày 24 tháng 10 năm 2024"** —
lệch gần hai năm, nói bằng giọng chắc chắn.

Muốn search chạy thật thì cần key bật billing hoặc chưa cạn hạn mức grounding.

### Nhạc trùng tên thì hỏi, không đoán

Chỉ có tên bài, không có ca sĩ → hỏi lại, **không gửi lệnh**. Một cái tên trần
khớp cả cover, remix, karaoke; chọn đại là đoán, mà người khiếm thị không nhìn
được để biết đang nghe nhầm bản.

Nhận diện ca sĩ qua `" - "`, `" của "`, `" by "`. Trả lời tên ca sĩ → ghép
`"Nơi này có anh - Sơn Tùng M-TP"`. Trả lời "cứ phát" / "bất kỳ" → phát tên bài
trần. Hỏi **đúng một lần**, không lặp.

`pipeline/intent.py` có thêm dòng trong prompt: một câu chỉ gồm tên ca sĩ, hoặc
"cứ phát", cũng là `music_play`. Thiếu dòng này thì câu trả lời "Sơn Tùng M-TP"
bị phân loại thành `chat` và luồng gãy.

### Đặt xe: xác nhận điểm đến trước, không đọc giá

Lượt 1 (nói "đặt xe đi X") **không gọi API**, chỉ đọc lại: "Bạn muốn đặt xe đi
X, đúng không?" — vì STT nghe nhầm địa điểm là đưa người khiếm thị tới nhầm chỗ.

Lượt 2 (nói "xác nhận") mới gọi API, rồi nói: "Đã mở ứng dụng đặt xe. Vui lòng
nhấn vào thông báo trên điện thoại, kiểm tra lại điểm đón và điểm đến trong ứng
dụng rồi xác nhận để đặt xe."

**Không đọc giá, loại xe hay thời gian chờ.** Backend trả `85000 VND / GrabCar /
6 phút` nhưng đó là số server tự sinh — Grab thật chỉ báo giá sau khi người dùng
xác nhận điểm đón, mà app không qua được bước đó. Đọc lên là nói một cái giá
không ai cam kết. Có test chặn: `assert "85" not in out`.

Không tìm thấy địa điểm → "Không tìm thấy địa điểm này. Vui lòng nói lại tên
địa điểm." Không đoán chỗ gần đúng.

### Action nào cần người dùng bấm thông báo

| Action | Cần bấm? |
|---|---|
| `contact_call`, `emergency_call` | Không — đi qua `TelecomManager.placeCall`, không phải mở activity |
| `music_stop`, `music_volume`, `navigation_stop` | Không — không mở màn hình nào |
| `music_play`, `navigation_start`, `ride_quote` | **Có, khi màn hình đang bật** |

Nhóm cuối mở ứng dụng khác qua notification full-screen-intent. Màn hình tắt thì
Android tự mở; người dùng đang cầm máy thì hệ điều hành cố ý chỉ hiện heads-up để
không cắt ngang. Câu nói phải nhắc — và nhắc ngay ở **câu đầu**, không đợi hết
câu kết quả.

### Id nối giữa hai lệnh

`handlers/action_flow.py` nhớ `navigation_id` từ `navigation_start` và
`quote_id` từ `ride_quote`, rồi cấp lại cho `navigation_stop` / `ride_confirm`.
Trước đây hai lệnh này hardcode `nav-123` / `quote-123` nên host luôn trả
`NOT_FOUND`. Dict trong bộ nhớ tiến trình — đủ cho demo một kính; nhiều kính
thì phải khoá theo `device_id`.

### Không bịa tham số

Thiếu tham số thì hỏi lại, không gửi lệnh với giá trị mặc định:

- `navigation_start` không có `destination` → "Bạn muốn đi đâu?"
  (trước: fallback `"điểm đến yêu cầu"` rồi vẫn gửi lệnh)
- `contact_call` không có `contact_name` → "Bạn muốn gọi cho ai?"
  (trước: fallback `"người thân"`)
- `ride_quote` không có `destination` → "Bạn muốn đi đâu?"
- `navigation_stop` / `ride_confirm` không có id → nói rõ chưa có gì để dừng/xác nhận
- `music_play` không có tên bài → "Bạn muốn nghe bài hát nào?"
  (trước: lấy nguyên câu lệnh làm tên bài, nên "bật nhạc lên" đi tìm một bài hát
  tên đúng bằng câu đó; bộ phân loại trả `song: "nhạc"` cho "mở nhạc đi" và
  không trả gì cho "bật nhạc lên" — đo thật, cả hai đường đều với tới được)
- `music_volume` không có hướng lẫn mức → "Bạn muốn tăng hay giảm âm lượng?"
  (trước: mặc định `direction: "up"` — nghe không rõ mà tự tăng là bắt người
  khiếm thị hứng một tiếng to họ không yêu cầu, và họ không nhìn được thanh âm
  lượng để chỉnh lại)

Kiểm cả 7 đường một lượt:

```
nav_start   không địa điểm  api=False | Bạn muốn đi đâu? Vui lòng nói lại kèm tên địa điểm.
nav_stop    không id        api=False | Hiện không có lộ trình nào đang chạy để dừng.
ride_quote  không địa điểm  api=False | Bạn muốn đi đâu? Vui lòng nói lại kèm tên điểm đến.
ride_confirm không quote    api=False | Chưa có chuyến nào để xác nhận, bạn hãy nói điểm đến trước.
contact_call không tên      api=False | Bạn muốn gọi cho ai? Vui lòng nói lại kèm tên người cần gọi.
music_play  không bài       api=False | Bạn muốn nghe bài hát nào?
music_volume không hướng    api=False | Bạn muốn tăng hay giảm âm lượng?
```

### Ảnh: xét sau khi biết intent, không xét trước

Chất lượng ảnh chỉ có nghĩa khi đã biết người dùng hỏi gì. Cùng một tấm ảnh là
vô dụng với "đọc chữ giùm tôi" nhưng hoàn toàn không liên quan tới "gọi cho mẹ".

Cổng lọc từng chạy trong `app.py`, **trước** cả STT — nên một tấm ảnh xấu chặn
đứng cả những lệnh không hề mở ảnh ra xem. Giờ nó nằm ở `pipeline/router.py`,
sau bước nhận diện intent (`image_quality.reject_reason`).

| Intent | Cần ảnh | Chặn theo sáng/tối | Chặn theo độ nét |
|---|---|---|---|
| `ocr`, `find`, `space`, `hazard` | ✓ | ✓ | ✗ |
| `money` | ✓ | ✓ | ✓ |
| `chat` + 9 action điện thoại | ✗ | ✗ | ✗ |

Intent không đọc ảnh thì **không decode ảnh luôn** — tiết kiệm khoảng 0,1 giây
mỗi request cho phép đo mà kết quả không được dùng tới. Ảnh cũng thành không bắt
buộc: `POST /process` chỉ còn đòi `audio`. Câu hỏi thật sự cần ảnh mà thiếu ảnh
thì nói thẳng, vì chỉ ở bước này mới biết intent là gì.

**Vì sao bỏ chặn độ nét cho 4 intent kia.** request410 (ảnh bức tường trắng,
sharpness 0.92) bị từ chối bằng câu "giữ chắc tay" — chẩn đoán sai: ảnh nét bình
thường, chỉ là chủ thể phẳng nên Laplacian variance thấp. Thả cho đi tiếp thì cả
ba handler trả lời đúng và có ích hơn hẳn câu từ chối:

| Handler | Trả lời trên chính tấm ảnh đó |
|---|---|
| `space` | "một bề mặt phẳng, có thể là bức tường trắng hoặc cánh cửa trơn màu" |
| `ocr` | "Không thấy rõ chữ trong ảnh, vui lòng chụp lại." |
| `find` | "Tôi không thấy rõ cái ly, vui lòng chụp lại gần hơn." |

**Vì sao GIỮ chặn sáng/tối, cho mọi intent đọc ảnh.** Lấy ảnh tờ 5.000đ thật
(request1) rồi làm tối / làm sáng quá, đo 2 lần mỗi bên — kết quả giống hệt nhau
cả 2 lần:

| Ảnh | Độ sáng | `read_money` nói | Thật |
|---|---|---|---|
| gốc | 127.2 | "không đủ rõ để xác định mệnh giá" | 5.000đ |
| làm tối | 12.3 | **"Đây là tờ 2 nghìn đồng."** | 5.000đ |
| làm sáng | 246.9 | **"Đây là tờ 500 nghìn đồng."** | 5.000đ |

Làm ảnh xấu đi khiến model **tự tin hơn và sai**, không hề từ chối. Cơ chế từ
chối theo manh mối trong `read_money` chạy ngược trên ảnh hỏng, nên cổng lọc độ
sáng là thứ duy nhất chặn giữa người khiếm thị và một mệnh giá sai. Đây cũng là
lý do `money` vẫn giữ luật độ nét — ngưỡng phòng xa chứ chưa có ca đo được, giữ
vì đây là intent duy nhất mà trả lời sai đắt hơn hẳn câu "chụp lại".

### Nói bừa thì hỏi lại, không xếp vào `chat`

`unknown` giờ là nhãn model được phép **chọn**, không chỉ là giá trị dự phòng
khi gọi model hỏng. Thiếu nó thì mọi thứ STT nghe nhầm đều rơi vào `chat`, và
Gemini lịch sự trả lời một câu hỏi chưa từng ai hỏi.

Ba đường vào cùng nhãn `unknown`, ba câu khác nhau — vì người dùng phải sửa theo
ba cách khác nhau:

| Tình huống | Người dùng nghe |
|---|---|
| STT không ra chữ nào | "Xin lỗi, tôi không nghe rõ, vui lòng nói lại." |
| Nghe ra chữ mà vô nghĩa | "Xin chào, tôi chưa hiểu bạn muốn gì. Nếu cần hỗ trợ, bạn vui lòng gửi lại yêu cầu." |
| Gọi Gemini hỏng (`classify_failed`) | "Hệ thống đang bận, bạn vui lòng thử lại sau giây lát." |

Dòng cuối không được nhận là "tôi chưa hiểu": lúc đó hệ thống chưa hiểu được câu
nào cả, kể cả câu hoàn hảo — nói vậy là đổ lỗi cho người dùng về việc họ không
làm sai. Cờ `classify_failed` này lập tức có ích: khi đo 25 câu, 5 câu rõ ràng
("tắt nhạc", "cứu tôi với") ra `unknown`, và cờ chỉ đúng thủ phạm là **429 hết
quota** chứ không phải prompt hỏng. Không có cờ thì 5 ca đó trông y hệt phân
loại sai, và sẽ sửa nhầm vào prompt.

Đo thật 25 câu, đúng 25 (5 ca 429 đã thử lại có giãn cách):

| Nhóm | Ví dụ | Ra |
|---|---|---|
| Vô nghĩa | "ờ à ừm", "xe xe xe xe", "a bờ cờ dờ", "lô ca ta xi mà", "mà rồi thì là mà" | `unknown` |
| Ngắn/cụt nhưng có ý | "ê", "nóng quá", "buồn ngủ ghê", "mấy giờ rồi", "chào bạn" | `chat` |
| Có lệnh rõ | "tắt nhạc", "cứu tôi với", "đặt xe đi Bách Khoa", "cứ phát" | đúng action |

Ranh giới viết thẳng trong prompt: câu ngắn, cụt, sai ngữ pháp hay nói trống
không mà VẪN đoán ra ý thì **không** phải `unknown`. Chỉ chọn `unknown` khi thật
sự không nói được người dùng muốn gì.

### Mọi câu đều có chỗ thở trước câu sau

TTS chỉ tổng hợp trong phạm vi từng câu, nên nối thẳng lại là một tràng tiếng
liên tục. Người khiếm thị chỉ có kênh âm thanh để theo dõi: câu chào, câu trấn
an, câu báo kết quả và đoạn model viết dính liền nhau thì không nghe ra ranh
giới giữa chúng, và một câu trả lời dài thành khó bám.

`SPEECH_SENTENCE_PAUSE_SECONDS` (0,45s) chèn vào giữa **mọi** cặp câu liền nhau,
không riêng chỗ giáp ranh giữa hai loại câu — `tts._sentences()` cắt xong thì
không còn biết câu nào từ nguồn nào, và một đoạn model viết dài cũng cần ngắt
hơi y như vậy. Không chèn trước câu đầu: chèn thì mọi request đều chậm thêm đúng
ngần ấy mà chẳng ngăn cách được với câu nào.

Đo trên chuỗi thật (câu chào → câu trấn an → "Đang gọi cho Em iu."):

| | Tổng audio | Các quãng nghỉ ở ranh giới câu |
|---|---|---|
| Trước | 6,56s | 0,28s và một chỗ không có gì |
| Sau | 7,30s | **0,70s** và **0,66s** |

0,45s là chỗ đủ nghe rõ đã sang câu khác, còn dưới quãng nghỉ tự nhiên giữa hai
câu người nói (~0,6s) nên không lê thê. Cộng với đuôi tự nhiên của model thì ra
0,66–0,70s — sát nhịp nói người thật. Giá phải trả: câu trả lời 5 câu dài thêm
1,8 giây. Đặt `SPEECH_SENTENCE_PAUSE_SECONDS=0` trong `models/.env` để tắt.

### Câu vừa nói đẩy câu trấn an kế tiếp ra xa

Câu chào "Đã nhận yêu cầu của bạn, hệ thống đang xử lý." **cũng là câu trấn an
đầu tiên**. Mốc kế tiếp vì vậy đếm từ lúc nó đọc XONG, không phải từ lúc bắt đầu
đọc — nếu không thì câu chào dài 2,72 giây chỉ để lại 1,28 giây im lặng trước
câu kế, nghe thành nói dồn.

| | Câu chào xong | Trấn an #1 | Im lặng ở giữa |
|---|---|---|---|
| Trước | 2,72s | 4,00s | **1,28s** |
| Sau | 2,72s | 6,72s | **4,00s** |

Cùng luật cho mỗi action: câu xác nhận ("Đang gọi xe.") là câu trấn an đầu ở đó,
nên `_await_result` nhận `opening_seconds` bằng độ dài câu ack.

Độ dài câu lấy từ `tts.speaking_seconds()`: câu dựng sẵn thì đo thẳng trên PCM
sắp phát (chính xác tuyệt đối), câu động (tên bài, tên người, địa chỉ) thì ước
lượng theo độ dài — khớp tuyến tính trên 96 câu dựng sẵn:

```
giây = 0.0466 * số_ký_tự + 0.324     sai số trung bình 0.17s, tối đa 1.30s
```

**Trần 5 giây áp cho câu đầu, không áp cứng cho các câu sau:**

| | Im lặng trước đó |
|---|---|
| Trấn an #1 | 4,00s |
| Trấn an #2 | 6,60s |
| Trấn an #3 | 10,76s |

Quãng đầu — quãng gần như request nào cũng đi qua — nằm dưới 5 giây. Các quãng
sau nới ra vì càng chờ lâu thì càng ít cần nhắc lại, và vì chúng hiếm khi xảy ra
thật: phần lớn request xong trước cả trấn an #2. Ép cứng 5 giây cho mọi quãng
thì một lượt nhạc 40 giây phải nghe 8 câu trấn an — đúng cái "nói dồn dập" đã
sửa đi. Cần ép thì đặt `SPEECH_NOTICE_MAX_INTERVAL_SECONDS=5` và
`SPEECH_NOTICE_BACKOFF=1.0` trong `models/.env`.

### Luật ưu tiên: nội dung thật luôn thắng câu trấn an

Thứ tự ưu tiên, cài ở một chỗ duy nhất (`handlers/waiting.py`, `wait_for`):

1. **Kết quả model, trạng thái thật của action, câu báo lỗi thật** — có lúc nào
   phát lúc đó. Không đồng hồ nào giữ chúng lại.
2. **Câu trấn an** chỉ được nói khi tới mốc mà VẪN chưa có gì. Tới mốc mà nội
   dung thật đã sẵn sàng thì bỏ hẳn câu đó, không nói bù.
3. **Câu trấn an đã đẩy ra thì không rút lại được** — audio phát tuần tự nên mọi
   thứ sau nó phải xếp hàng chờ đọc xong. Đây là lý do phải cố hết sức để đừng
   nói hụt ở bước 2.

Trước đây luật này được cài hai lần ở hai chỗ, theo hai cách khác nhau — và bản
bên chờ điện thoại vi phạm chính nó: luồng chính `sleep` cố định một nhịp poll
sau mỗi lần hỏi host, nên kết quả vừa về vẫn nằm chờ tới một giây mới được nói
ra. Giờ vòng `sleep` nằm ở luồng nền, luồng chính chỉ chờ trên hàng đợi và bật
dậy ngay khi có kết quả.

Độ trễ còn lại là do nhịp poll, đo trên 6 mốc hoàn thành khác nhau:

| Nhịp poll | Trễ trung bình | Tối đa | Số lần gọi trong 25s |
|---|---|---|---|
| 1,00s | 0,66s | 0,95s | 25 |
| **0,50s** | **0,33s** | **0,46s** | **50** |
| 0,25s | 0,21s | 0,21s | 100 |

Chọn 0,50s: nửa độ trễ so với 1,0 mà chỉ thêm 25 lần gọi tới host chạy cùng
máy. Xuống 0,25 chỉ mua thêm 0,12 giây nữa mà gấp đôi số lần gọi.

### Câu trấn an phải nhường kết quả thật

Audio phát tuần tự, nên câu trấn an đã đẩy vào luồng là **không rút lại được**:
kết quả thật về ngay sau đó phải xếp hàng chờ đọc xong câu đã hết tác dụng —
người dùng ngồi nghe thêm khoảng 2,5 giây "vẫn đang chờ" trong khi máy đã xong.

Hai chỗ biết chờ đều nhường thêm một nhịp cuối trước khi cam kết nói:

- `handlers/waiting.py` (chờ Gemini): chờ thêm `SPEECH_NOTICE_GRACE_SECONDS`
  (0,5s) rồi mới nói.
- `handlers/action_flow.py` (chờ điện thoại): tra `get_request_status` thêm một
  lần ngay trước khi nói — một lần gọi HTTP rẻ hơn nhiều so với quãng 2,5 giây.

Giá phải trả khi thật sự còn chờ lâu đúng bằng 0,5 giây đó, và chỉ ở câu đầu.

Đây cũng là chỗ chặn hậu quả của lỗi STT ở mục "dừng chỉ đường" → "dân chỉ
đường": intent vẫn ra `nav_start`, nhưng không có `destination` nên handler hỏi
lại thay vì bắt đầu dẫn đường tới một nơi không ai nhắc tới. Đã kiểm chứng bằng
audio thật: `outbound call none`.

### Còn tồn tại

**`ride/quote` vẫn gửi vị trí giả** `{lat: 10.7769, lng: 106.7009}`
(`handlers/ride.py`). Kính chưa có GPS. Phải nêu rõ nếu bị hỏi khi demo.

## 7. Lệnh kiểm chứng nhanh trước khi demo

```bash
TOKEN=f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY

# 1. Backend sống qua tunnel
curl -s https://app.visioncare-host.uk/health/ready
# kỳ vọng: {"status":"ok"}

# 2. Pairing còn hiệu lực + round-trip đầy đủ
RID=$(python -c "import uuid;print(uuid.uuid4())")
curl -s -X POST https://app.visioncare-host.uk/api/v1/service/music/volume \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: VisionCare-Glasses/1.0" \
  -d "{\"device_id\":\"glasses-123\",\"request_id\":\"$RID\",\"direction\":\"up\"}"
sleep 5
curl -s "https://app.visioncare-host.uk/api/v1/requests/$RID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: VisionCare-Glasses/1.0"
# kỳ vọng: request_state = "succeeded"
# "failed" + DELIVERY_FAILED  → app Android chưa bấm Đăng ký lại
# 403 không có error.code     → thiếu header User-Agent
```

Kiểm tra app Android còn cài và còn sống:

```powershell
$adb = "D:\tmp\app-demo-android-toolchain\android-sdk\platform-tools\adb.exe"
& $adb shell pm list packages | Select-String youreyes
```

## 8. Tình trạng đã kiểm chứng (2026-08-04)

Round-trip thật, đi qua tunnel → backend → FCM → điện thoại → `/device/report`:

| Action | Kết quả | Thời gian | `result` |
|---|---|---|---|
| `music_play` | ✅ succeeded | 1.9s | `{title: "Nơi này có anh", artist: "Sơn Tùng M-TP", volume: 60, track_id: "yt-music-8a66295e", playback_state: "playing"}` |
| `music_volume` | ✅ succeeded | 2.0s | `{level: 66, volume_state: "changed"}` |
| `music_stop` | ✅ succeeded | 2.1s | `{playback_state: "stopped"}` |
| `navigation_start` | ✅ succeeded | 2.1s | `{navigation_id: "nav-ae92ecda", navigation_state: "navigating", travel_mode: "walking"}` |
| `navigation_stop` | ✅ succeeded | 1.8s | `{navigation_id: "nav-ae92ecda", navigation_state: "stopped"}` |
| `ride_quote` | ✅ succeeded | 1.9s | `{quote_id: "quote-eeb81162", product_type: "GrabCar", price_estimate: {amount: 85000, currency: "VND"}, eta_minutes: 6}` |
| `ride_confirm` | ✅ succeeded | 1.8s | `{quote_id: "quote-eeb81162", ride_id: null, ride_status: "cancelled"}` |
| `emergency_call` | ✅ succeeded | 2.4s | `{emergency_state: "completed", attempt: 1, answered: false, cycle: "stopped", contact: "***768", sms_sent: true}` — gọi thật + SMS thật |
| `contact_call` | ✅ succeeded | 1.9s | `{call_state: "calling", contact_name: "Em iu", phone_number: "***768"}` — quay số thật |

Hai action trên tác động ra thế giới thật (quay số, gửi SMS). Chỉ chạy khi thật
sự demo. Error path đã kiểm chứng riêng: `emergency_call` khi ô liên hệ khẩn cấp
trống → `EMERGENCY_CONTACT_NOT_CONFIGURED`; `contact_call` với tên không có
trong danh bạ → `CONTACT_NOT_FOUND`.

Chuỗi id đã kiểm chứng: `navigation_start.navigation_id` → `navigation_stop`,
`ride_quote.quote_id` → `ride_confirm`. Cả hai đều `succeeded` khi truyền id thật,
đúng như mục 6 yêu cầu.

Hạ tầng:

| Hạng mục | Trạng thái |
|---|---|
| PostgreSQL `app-demo-postgres-1` | ✅ Up (healthy), migration ở head `20260803_0004` |
| Backend trên `8001` | ✅ `/health/ready` = `ok` |
| Tunnel `app.visioncare-host.uk` → `8001` | ✅ `200` |
| Pairing `glasses-123` ↔ `user-100` | ✅ `{"linked": true}` |
| App Android `com.youreyes.app` v0.1.0 | ✅ đã cài, đã Đăng ký, FCM token sống |
| 9/9 endpoint nhận `202` từ server kính | ✅ (`test_live_server_calls.py`) |

### Luồng đầy đủ từ kính: `POST /process` → điện thoại

Kiểm chứng bằng câu lệnh giọng nói thật (TTS sinh WAV 48 kHz) + ảnh, gửi
multipart tới `http://127.0.0.1:8000/process`, rồi bám `request_id` mà server
kính log ra để tra kết quả cuối trên máy điện thoại:

| Câu nói | STT nghe thành | Intent | Kết quả trên máy |
|---|---|---|---|
| "Mở bài hát Nơi này có anh của Sơn Tùng M-TP" | "ngựa bài hát nơi này có anh của sơn tùng mờ thành phố" | `music_play` ✅ | `succeeded`, `playback_state: playing` |
| "Tăng âm lượng lên" | "tăng âm lượng lên" | `music_volume` ✅ | `succeeded`, `level: 66` |
| "Tắt nhạc đi" | "thanh nhạc đi" | `music_stop` ✅ | `succeeded`, `playback_state: stopped` |
| "Chỉ đường cho tôi tới Bưu điện Thành phố Hồ Chí Minh" | "chỉ đường cho tôi từ bưu điện thành phố hồ chí minh" | `nav_start` ✅ | `succeeded`, `nav-ee07939e` |
| "Dừng chỉ đường" | "dân chỉ đường" | `nav_start` ❌ | `succeeded` nhưng **sai action** — xem dưới |
| "Đặt xe đi Đại học Bách Khoa" | "đạt xe đi đại học bách khoa" | `ride_quote` ✅ | `succeeded`, `85000 VND`, `eta 6 phút` |

`/process` trả `HTTP 200`, `X-Audio-Encoding: mp3`, 7-14 KB audio, 3.2-5.2s
tính từ lúc nhận request tới lúc đọc xong câu trả lời.

**Lỗi tìm được — `nav_stop` bị route nhầm thành `nav_start`.** STT nghe "dừng
chỉ đường" thành "dân chỉ đường"; bộ phân loại intent đọc "dân chỉ đường" rồi
suy ra `nav_start` là hợp lý. Hậu quả: người dùng nói "dừng chỉ đường" thì máy
**bắt đầu** điều hướng, tới `"điểm đến yêu cầu"` (giá trị fallback ở
`handlers/navigation.py:11`). Hai chỗ cần sửa:

1. STT sai trên câu lệnh ngắn 1-2 âm tiết. Cần thêm ràng buộc từ vựng hoặc
   danh sách câu lệnh cố định cho nhóm lệnh điều khiển.
2. `handlers/navigation.py:11` lấy `destination` fallback `"điểm đến yêu cầu"`
   khi thiếu tham số, che mất lỗi. `nav_start` không có `destination` thật thì
   phải hỏi lại người dùng, không được tự bịa điểm đến. `handlers/ride.py:11`
   có cùng vấn đề.

### ⚠️ `request_state: "succeeded"` KHÔNG chứng minh máy đã làm

Đo lại từng action bằng `dumpsys` trên máy thật (`telephony.registry`,
`media_session`, `audio`, `activity activities`) thay vì tin server:

| Action | Server báo | Máy thật | Khớp? |
|---|---|---|---|
| `music_volume` | succeeded | `STREAM_MUSIC 9 → 6` | ✅ |
| `navigation_start` | succeeded | Google Maps lên foreground | ✅ |
| `music_play` | succeeded, `playback_state: "playing"` | YT Music session `STOPPED(1)` suốt 30s, app không lên foreground | ❌ |
| `music_stop` | succeeded, `playback_state: "stopped"` | `STOPPED` — nhưng vốn đã STOPPED từ đầu, không chứng minh được gì | ❌ |
| `emergency_call` | succeeded, `sms_sent: true` | `mCallState=0` (idle) suốt | ❌ |
| `contact_call` | succeeded, `call_state: "calling"` | `mCallState=0` (idle) suốt; chỉ 1 lần thấy `InCallActivity` surface | ❌ |
| `ride_quote` | succeeded | Grab (`com.grabtaxi.passenger`) đã cài nhưng không lên foreground | ❌ |
| `navigation_stop` | succeeded | không quan sát được ở tầng OS | n/a |
| `ride_confirm` | succeeded | không quan sát được ở tầng OS | n/a |

**2/9 action kiểm chứng được là chạy thật.** Phần còn lại server báo thành công
trong khi máy không làm gì.

### Nguyên nhân gốc — full-screen intent không tự mở khi máy đang dùng

App gửi lệnh qua notification full-screen-intent + activity trampoline
(`CommandLaunchActivity`) — đúng cơ chế mà app gọi điện/báo thức dùng. Nhưng
Android **chỉ tự mở** full-screen intent khi màn hình tắt hoặc đang khoá. Khi
người dùng đang mở khoá và dùng máy, hệ thống cố tình hạ xuống heads-up
notification để không cắt ngang → **phải chạm tay**. Đúng triệu chứng đã gặp.

Đo được cả hai phía:

- Màn hình khoá: `ActivityTaskManager: Activity requesting to dismiss Keyguard:
  CommandLaunchActivity` → trampoline chạy, YT Music tự mở.
- Màn hình mở khoá (foreground = Maps): appop `USE_FULL_SCREEN_INTENT` ghi nhận
  có dùng (`time=+47s`), nhưng logcat **không có** `CommandLaunchActivity` nào,
  không có `MEDIA_PLAY_FROM_SEARCH` → chỉ hiện heads-up.

Nghĩa là với cấu hình hiện tại **không có trạng thái nào chạy tự động hoàn
toàn**: mở khoá thì cần chạm; khoá thì MIUI chặn (trừ khi bật quyền "Hiển thị
trên màn hình khoá").

### Quyền phải bật, và nó tự tắt lại

`USE_FULL_SCREEN_INTENT` mặc định là `ignore` vì app `targetSdk 36` — từ
Android 14 quyền này không còn tự cấp cho app không phải app gọi điện. Bị
`ignore` thì hệ thống **tước** `fullScreenIntent` khỏi notification
(`dumpsys notification` hiện `fullscreenIntent=null`).

```powershell
adb shell appops set com.youreyes.app USE_FULL_SCREEN_INTENT allow
adb shell appops set com.youreyes.app 10020 allow   # MIUI background start
```

**Quan sát được: MIUI tự reset `USE_FULL_SCREEN_INTENT` về `ignore`** sau vài
phút. Phải bật trong Settings UI (Thông báo → Thông báo toàn màn hình) để bền,
`appops` chỉ sống tạm.

Ngoài ra cần bật tay trong **Cài đặt → Ứng dụng → YourEyes → Quyền khác**:
Hiển thị trên màn hình khoá, Khởi động trong nền, Hiển thị pop-up khi chạy nền,
Tự khởi động.

### Bug trong code app (`apps/android/.../actions/ActionRegistry.kt`)

1. **`MusicPlayHandler` bỏ qua kết quả** — gọi `playViaYouTubeMusicBrowser(...)`
   rồi vứt giá trị trả về, luôn trả `Success(playback_state: "playing")`. Đây là
   lý do server nói dối.
2. **MediaBrowser connect fail ngay** — report gửi sau 0.6s trong khi latch chờ
   tới 8s, tức `onConnectionFailed` gọi lập tức. YouTube Music chỉ cho client
   trong allowlist Android Auto bind `MusicBrowserService`.
3. **Media-key nudge 1800ms không kịp bắn** — app bị `lowmemorykiller` giết
   (`oom_score_adj 955`, giải phóng 184 MB) khoảng 1.5s sau khi mở YT Music.
   `Handler.postDelayed` chết theo process.
4. **`runCatching { startActivity(targetIntent) }`** ở `CommandLaunchActivity`
   nuốt mọi exception — launch thất bại không để lại dấu vết nào trong log.

### Ghi chú cài APK trên HyperOS

`adb install` luôn trả `INSTALL_FAILED_USER_RESTRICTED` kể cả khi đã bật
"Cài đặt qua USB". Cách chạy được:

```powershell
& $adb push app-debug.apk /data/local/tmp/app-debug.apk
& $adb shell pm install -r -t -i com.android.vending --user 0 /data/local/tmp/app-debug.apk
```

`-i com.android.vending` khai installer là Play Store; lớp securitycenter của
MIUI chỉ chặn khi installer là shell. `pm grant` vẫn bị chặn — quyền runtime
(Danh bạ / Điện thoại / SMS / Vị trí) phải cấp bằng tay trong app.
