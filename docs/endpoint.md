# Danh sách endpoint — App Communication Server

Tổng hợp toàn bộ endpoint backend thật (`apps/backend/src/app/api/*.py` +
schema tương ứng trong `apps/backend/src/app/schemas/*.py`), kèm headers,
request/response body và giải thích từng trường. Envelope chung xem mục 11.

## 1. Health (`app/api/health.py`)

Không auth.

### 1.1. `GET /health/live`

Response `200`:

```json
{ "status": "ok" }
```

### 1.2. `GET /health/ready`

Response `200` khi app đã bootstrap xong, `503` khi chưa:

```json
{ "status": "ok" }
```

```json
{ "status": "not_ready" }
```

## 2. Public Service API (`app/api/service.py`)

Dành cho External API Client (server kính). Headers dùng chung cho cả mục 2
và mục 3:

```http
Authorization: Bearer <client_token>
Content-Type: application/json
Accept: application/json
```

Scope bắt buộc: `service:execute` (mục 2), `requests:read` (mục 3). Sai/thiếu
token → `401`/`403` dạng `{"detail": "UNAUTHORIZED"}` / `{"detail": "FORBIDDEN"}`
(không theo envelope lỗi mục 11.2).

Trường chung mọi request body dưới đây (đặt thêm trường lạ → `400
INVALID_REQUEST`):

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `device_id` | Có | string (non-empty, tự trim) | ID phần cứng của kính, đã pairing với một `user_id` qua mục 5. Server tự resolve sang `user_id` nội bộ; chưa pairing → `404 GLASSES_DEVICE_NOT_LINKED` |
| `request_id` | Có | UUID string | ID duy nhất cho lần gọi; gửi lại cùng giá trị + cùng nội dung không tạo lần thực thi mới (idempotent); cùng `request_id` khác nội dung → `409 REQUEST_ID_CONFLICT` |

Response tiếp nhận chung — `HTTP 202 Accepted`:

```json
{
  "status": "ok",
  "data": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "operation": "ride_quote",
    "request_state": "processing",
    "status_url": "/api/v1/requests/550e8400-e29b-41d4-a716-446655440000",
    "accepted_at": "2026-08-02T10:00:00Z"
  }
}
```

| Trường response | Kiểu | Ý nghĩa |
|---|---|---|
| `data.request_id` | UUID string | Dùng để tra trạng thái/callback |
| `data.operation` | string | Tên action ứng với endpoint đã gọi |
| `data.request_state` | string | Luôn `processing` ở bước tiếp nhận |
| `data.status_url` | string | Path `GET` trạng thái cuối (mục 3) |
| `data.accepted_at` | datetime | ISO 8601 UTC |

Kết quả cuối cùng (`succeeded`/`failed`/`timed_out`) không nằm trong response
này — phải tra qua mục 3 hoặc callback (`project_context.md` §6.3).

### 2.1. `POST /api/v1/service/ride/quote` — Lấy báo giá chuyến đi

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "current_location": { "lat": 10.7769, "lng": 106.7009 },
  "destination": {
    "address": "Đại học Bách Khoa TP.HCM",
    "lat": 10.7721,
    "lng": 106.6578
  }
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `current_location.lat` | Có | number | Vĩ độ hiện tại, `-90..90` |
| `current_location.lng` | Có | number | Kinh độ hiện tại, `-180..180` |
| `destination.address` | Có điều kiện | string | Bắt buộc nếu không gửi `lat`+`lng` |
| `destination.lat` / `destination.lng` | Có điều kiện | number | Phải gửi cùng nhau (`-90..90`/`-180..180`) |

`operation`: `ride_quote`. Mã lỗi kết quả: `INVALID_LOCATION`,
`INVALID_DESTINATION`, `RIDE_ACCOUNT_NOT_CONNECTED`, `NO_RIDE_AVAILABLE`,
`RIDE_PROVIDER_ERROR`.

### 2.2. `POST /api/v1/service/ride/confirm` — Xác nhận hoặc hủy đặt xe

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440001",
  "quote_id": "quote-123",
  "confirm": true
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `quote_id` | Có | string | ID nhận từ kết quả `ride/quote` |
| `confirm` | Có | boolean | `true`: đặt xe; `false`: hủy quy trình đặt xe |

`operation`: `ride_confirm`. Mã lỗi: `QUOTE_NOT_FOUND`, `QUOTE_EXPIRED`,
`QUOTE_ALREADY_USED`, `RIDE_CONFIRM_FAILED`.

### 2.3. `POST /api/v1/service/music/play` — Phát nhạc

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440002",
  "song": "Nơi này có anh - Sơn Tùng M-TP",
  "volume": 60
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `song` | Có | string (non-empty) | Chuỗi tìm kiếm: tên bài hát, nghệ sĩ hoặc cả hai |
| `volume` | Không | integer `0..100` | Mức âm lượng ban đầu; bỏ trống dùng mức hiện tại |

`operation`: `music_play`. Mã lỗi: `SONG_NOT_FOUND`,
`MUSIC_ACCOUNT_NOT_CONNECTED`, `SUBSCRIPTION_INACTIVE`, `PLAYBACK_FAILED`.

### 2.4. `POST /api/v1/service/music/stop` — Dừng nhạc

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440003"
}
```

Không có trường đặc thù. `operation`: `music_stop`. Mã lỗi:
`NO_ACTIVE_PLAYBACK`, `PLAYBACK_STOP_FAILED`.

### 2.5. `POST /api/v1/service/music/volume` — Thay đổi âm lượng

Theo hướng:

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440004",
  "direction": "up"
}
```

Theo mức tuyệt đối:

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440004",
  "level": 70
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `direction` | Có điều kiện | enum `up`/`down` | Đúng một trong `direction`/`level`; không gửi cùng lúc, không gửi cả hai đều trống |
| `level` | Có điều kiện | integer `0..100` | Mức âm lượng tuyệt đối |

`operation`: `music_volume`. Mã lỗi: `INVALID_VOLUME`, `VOLUME_CHANGE_FAILED`.

### 2.6. `POST /api/v1/service/navigation/start` — Bắt đầu điều hướng đi bộ

Theo địa chỉ:

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440005",
  "destination": { "address": "Bưu điện Thành phố Hồ Chí Minh" }
}
```

Theo tọa độ:

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440005",
  "destination": { "lat": 10.7798, "lng": 106.6990 }
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `destination.address` | Có điều kiện | string | Dùng khi không gửi tọa độ |
| `destination.lat` / `destination.lng` | Có điều kiện | number | Phải gửi cùng nhau |

Chế độ điều hướng cố định `walking`. `operation`: `navigation_start`. Mã lỗi:
`CURRENT_LOCATION_UNAVAILABLE`, `INVALID_DESTINATION`,
`LOCATION_PERMISSION_DENIED`, `NAVIGATION_PROVIDER_ERROR`,
`NAVIGATION_START_FAILED`.

### 2.7. `POST /api/v1/service/navigation/stop` — Dừng điều hướng

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440006",
  "navigation_id": "nav-123"
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `navigation_id` | Có | string | ID nhận từ kết quả `navigation/start` |

`operation`: `navigation_stop`. Mã lỗi: `NAVIGATION_NOT_FOUND`,
`NAVIGATION_ALREADY_STOPPED`, `NAVIGATION_STOP_FAILED`.

### 2.8. `POST /api/v1/service/emergency/call` — Gọi khẩn cấp

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440007"
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `number` | Không | string/null | Số khẩn cấp override; bỏ trống dùng số đã cấu hình sẵn trên điện thoại (trường này có trong schema thật nhưng chưa có ở ví dụ `project_context.md` §6.11) |

App dùng số khẩn cấp đã cấu hình, gửi vị trí qua SMS, thực hiện chu kỳ gọi.
`operation`: `emergency_call`. Mã lỗi: `EMERGENCY_CONTACT_NOT_CONFIGURED`,
`CURRENT_LOCATION_UNAVAILABLE`, `CALL_PERMISSION_DENIED`,
`SMS_PERMISSION_DENIED`, `CALL_FAILED`, `SMS_FAILED`.

### 2.9. `POST /api/v1/service/contact/call` — Gọi người trong danh bạ

```json
{
  "device_id": "glasses-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440008",
  "name": "Nguyễn Văn A"
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `name` | Có | string (non-empty) | Tên liên hệ cần tìm |
| `contact_id` | Không | string/null | ID liên hệ cụ thể để bỏ qua tìm kiếm mờ theo tên (có trong schema thật, chưa có ở ví dụ `project_context.md` §6.12) |

`operation`: `contact_call`. Khi trùng nhiều liên hệ, kết quả `failed` với
`error.code = "MULTIPLE_CONTACTS_FOUND"` kèm `details.candidates[]
{name, phone_number}`. Mã lỗi khác: `CONTACT_NOT_FOUND`,
`CONTACT_PERMISSION_DENIED`, `CALL_PERMISSION_DENIED`, `CALL_FAILED`.

## 3. Public Request Status API (`app/api/status.py`)

Headers giống mục 2, scope `requests:read`.

### 3.1. `GET /api/v1/requests/{request_id}`

Response `200`:

```json
{
  "status": "ok",
  "data": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "operation": "navigation_start",
    "request_state": "processing | succeeded | failed | timed_out",
    "result": {},
    "error": null,
    "created_at": "2026-08-02T10:00:00Z",
    "updated_at": "2026-08-02T10:00:03Z"
  }
}
```

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `data.request_state` | enum | `processing`, `succeeded`, `failed`, `timed_out` |
| `data.result` | object/null | `null` khi `processing`; cấu trúc theo từng `operation` (mục 2.1–2.9) |
| `data.error` | object/null | Chỉ có khi `failed`/`timed_out`: `{code, message, details}` |

`request_id` không tồn tại hoặc thuộc client khác → `404 REQUEST_NOT_FOUND`
(một lỗi cho cả hai trường hợp, không lộ thông tin request của client khác).

## 4. Internal Device API — app Android (`app/api/device.py`)

### 4.1. `POST /api/v1/device/register`

```http
Authorization: Bearer <device_token>
Content-Type: application/json
```

```json
{
  "user_id": "user-123",
  "device_id": "android-device-123",
  "platform": "android",
  "push_token": "fcm-token"
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `user_id` | Có | string | Người dùng liên kết với thiết bị (= `public_user_id`) |
| `device_id` | Có | string | ID ổn định của bản cài đặt app Android (khác `device_id` kính ở mục 5) |
| `platform` | Có | enum | Luôn `android` |
| `push_token` | Có | string | FCM registration token |

Response `200`:

```json
{ "status": "ok", "data": { "device_id": "android-device-123", "registered": true } }
```

Idempotent nếu cùng `device_id`+`user_id` (xoay `push_token`). `device_id` đã
đăng ký dưới `user_id` khác → `409 {"detail": "DEVICE_OWNER_MISMATCH"}`.
`device_id` đã bị revoke → `403 {"detail": "DEVICE_REVOKED"}` (dạng
`HTTPException`, không theo envelope `error` mục 11.2).

### 4.2. `POST /api/v1/device/report`

```http
Authorization: Bearer <device_token>
Content-Type: application/json
```

```json
{
  "user_id": "user-123",
  "device_id": "android-device-123",
  "request_id": "550e8400-e29b-41d4-a716-446655440008",
  "action": "contact_call",
  "execution_state": "succeeded",
  "result": { "call_state": "calling" },
  "error": null,
  "timestamp": "2026-08-03T10:00:00Z"
}
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `user_id` | Có | string | Người dùng sở hữu command |
| `device_id` | Có | string | Thiết bị Android đã thực thi command |
| `request_id` | Có | UUID string | Request Public API liên quan (mục 2) |
| `action` | Có | string | Action app vừa thực thi |
| `execution_state` | Có | enum | `succeeded` hoặc `failed` |
| `result` | Có điều kiện | object/null | Bắt buộc + không `null` khi `succeeded`; phải `null` khi `failed` |
| `error` | Có điều kiện | object/null | Bắt buộc `{code, message, details}` khi `failed`; phải `null` khi `succeeded` |
| `timestamp` | Có | datetime (UTC, có offset) | Thời điểm app tạo report |

Response `200`:

```json
{ "status": "ok", "data": { "request_id": "550e8400-e29b-41d4-a716-446655440008", "report_received": true } }
```

`request_id` không tồn tại, hoặc `user_id`/`action` không khớp operation gốc
→ `404 REQUEST_NOT_FOUND` (envelope `error` chuẩn). Report trùng/conflict
hoặc operation đã terminal → `409 REQUEST_ID_CONFLICT`.

### 4.3. `POST /api/v1/device/link`

```http
Authorization: Bearer <user_session_token>
Content-Type: application/json
```

```json
{ "device_id": "android-device-123" }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `device_id` | Có | string | `device_id` Android đã đăng ký qua mục 4.1, cần xác nhận là của caller |

Response `200`:

```json
{ "status": "ok", "data": { "device_id": "android-device-123", "platform": "android", "linked": true } }
```

Auth khác hẳn 4.1/4.2: dùng session token của chính phone app (từ mục 6), **không**
dùng Device bearer token. Chỉ xác nhận, không tạo/sửa row `devices`.
`device_id` chưa active → `404 DEVICE_NOT_FOUND`. `device_id` active dưới
user khác → `409 DEVICE_OWNER_CONFLICT`.

## 5. Internal Glasses Pairing API — app Android (`app/api/glasses.py`)

Auth: **Device bearer token** — cùng token với mục 4.1/4.2, không phải user
session (app demo chưa có login riêng từng người dùng để dùng cơ chế như
4.3). Mục đích: app Android khai báo "device_id kính này thuộc user_id này"
khi người dùng nhập device_id kính vào app điện thoại.

```http
Authorization: Bearer <device_token>
Content-Type: application/json
```

### 5.1. `POST /api/v1/device/glasses/link`

```json
{ "user_id": "user-123", "device_id": "glasses-abc" }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `user_id` | Có | string | Người dùng sở hữu app điện thoại thực hiện pairing |
| `device_id` | Có | string | ID phần cứng của kính cần pairing (chính là `device_id` server kính sẽ gửi ở mục 2) |

Response `200`:

```json
{ "status": "ok", "data": { "device_id": "glasses-abc", "linked": true } }
```

Pairing lại cùng `user_id`+`device_id` là idempotent (`200` như trên). Một
`user_id` chỉ có 1 kính active — pairing kính mới tự hủy (chuyển
`inactive`) pairing active cũ của user đó. `device_id` đang active dưới
`user_id` khác → `409 GLASSES_DEVICE_OWNER_CONFLICT`, không tự chuyển chủ
(phải unlink trước, mục 5.2).

### 5.2. `POST /api/v1/device/glasses/unlink`

```json
{ "user_id": "user-123" }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `user_id` | Có | string | Người dùng cần hủy pairing kính active hiện tại |

Response `200`:

```json
{ "status": "ok", "data": { "unlinked": true } }
```

| Trường response | Kiểu | Ý nghĩa |
|---|---|---|
| `data.unlinked` | boolean | `true` nếu có pairing active bị hủy; `false` nếu `user_id` không có pairing nào (không phải lỗi) |

## 6. Demo Auth API — phone app (`app/api/auth.py`)

Không auth, trừ `/logout`. Không có SMS provider thật — OTP được log
server-side (`logger.info`), demo dùng để test round-trip register → verify
→ login.

### 6.1. `POST /api/v1/auth/register`

```json
{ "phone_number": "0901234567", "password": "matkhau123", "display_name": "Nguyễn Văn A" }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `phone_number` | Có | string | Chuẩn hóa còn số + `+` đầu, tối thiểu 8 chữ số |
| `password` | Có | string, 6–200 ký tự | Mật khẩu tài khoản demo |
| `display_name` | Không | string | Tên hiển thị |

Response `200`:

```json
{ "status": "ok", "data": { "user_id": "...", "public_user_id": "user-123", "phone_number": "0901234567", "otp_required": true } }
```

Số điện thoại đã hoàn tất OTP trước đó → `409 PHONE_ALREADY_REGISTERED`.

### 6.2. `POST /api/v1/auth/otp/verify`

```json
{ "phone_number": "0901234567", "otp_code": "123456" }
```

Response `200`:

```json
{ "status": "ok", "data": { "access_token": "...", "user_id": "...", "public_user_id": "user-123", "phone_number": "0901234567", "display_name": null } }
```

`access_token` chỉ trả đúng một lần lúc phát hành. Không có OTP đang chờ →
`400 OTP_EXPIRED`. OTP hết hạn hoặc quá số lần thử → `400 OTP_EXPIRED`. OTP
sai → `400 OTP_INVALID`.

### 6.3. `POST /api/v1/auth/login`

```json
{ "phone_number": "0901234567", "password": "matkhau123" }
```

Response `200`: giống 6.2 (`SessionData`). Sai số điện thoại/mật khẩu →
`401 INVALID_CREDENTIALS` (dùng chung 1 lỗi cho cả hai để tránh dò tài
khoản). Tài khoản chưa xác minh OTP → `403 PHONE_NOT_VERIFIED`.

### 6.4. `POST /api/v1/auth/logout`

```http
Authorization: Bearer <user_session_token>
```

Response `200`:

```json
{ "status": "ok", "data": { "logged_out": true } }
```

Thu hồi **mọi** session đang active của user (logout-everywhere), không chỉ
token hiện tại.

## 7. Preferences API — phone app (`app/api/preferences.py`)

Auth: `Authorization: Bearer <user_session_token>` cho cả 2 endpoint.

### 7.1. `GET /api/v1/preferences`

Response `200`:

```json
{ "status": "ok", "data": { "font_size_option": "Vừa", "voice_option": "Giọng Nữ", "high_contrast": false, "haptics_enabled": true } }
```

### 7.2. `PUT /api/v1/preferences`

```json
{ "font_size_option": "To", "voice_option": "Giọng Nam", "high_contrast": true, "haptics_enabled": false }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `font_size_option` | Có | enum | `Nhỏ` / `Vừa` / `To` |
| `voice_option` | Có | enum | `Giọng Nữ` / `Giọng Nam` |
| `high_contrast` | Có | boolean | Bật/tắt chế độ tương phản cao |
| `haptics_enabled` | Có | boolean | Bật/tắt phản hồi rung |

Ghi đè toàn bộ 4 trường (không phải patch từng phần). Response `200`: cùng
cấu trúc `data` như 7.1, phản ánh giá trị vừa lưu.

## 8. Support API — phone app (`app/api/support.py`)

Auth: `Authorization: Bearer <user_session_token>`.

### 8.1. `POST /api/v1/support/tickets`

```json
{ "category": "feedback", "message": "Ứng dụng chạy tốt, mong thêm tính năng X." }
```

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `category` | Có | enum | `feedback` hoặc `support_request` |
| `message` | Có | string, non-empty, ≤ 2000 ký tự | Nội dung phản hồi/yêu cầu hỗ trợ |

Response `200`:

```json
{ "status": "ok", "data": { "id": "...", "category": "feedback", "created_at": "2026-08-03T10:00:00Z" } }
```

## 9. Public Result Callback (server → server kính, không phải endpoint của App Communication Server)

Nếu server kính đăng ký `callback_url` trong cấu hình client, App
Communication Server chủ động `POST` kết quả cuối thay vì bắt polling mục 3.

```http
POST {client_callback_url}
Authorization: Bearer <callback_token>
Content-Type: application/json
```

Body: cùng cấu trúc `data` như response mục 3.1. Server kính phải trả `200`;
App Communication Server retry khi timeout hoặc nhận `5xx`.

## 10. Giới hạn phạm vi theo nhóm

- Mục 2/3 (Public) không bao giờ trả push token, action nội bộ hay trạng
  thái giao nhận thiết bị.
- Mục 4/5 (Internal Device, Internal Glasses Pairing) chỉ dành cho app
  Android — không công bố cho External API Client (server kính).
- Mục 6/7/8 (Auth/Preferences/Support) chỉ dành cho chính app điện thoại của
  người dùng cuối, không liên quan tới server kính hay app Android device
  channel.

## 11. Response envelope chung

### 11.1. Thành công

`OkResponse`: `{"status": "ok", "data": {...}}` — dùng cho mọi endpoint trừ 9
action ở mục 2.

`AcceptedResponse` (chỉ mục 2, `HTTP 202`):
`{"status": "ok", "data": {"request_id", "operation", "request_state": "processing", "status_url", "accepted_at"}}`.

### 11.2. Lỗi nghiệp vụ (`PublicApiError` → exception handler chung)

```json
{ "status": "error", "error": { "code": "INVALID_REQUEST", "message": "...", "details": {} } }
```

Bảng mã lỗi nghiệp vụ đã dùng trong toàn hệ thống (`app/errors.py`):

| Code | HTTP | Dùng ở |
|---|---|---|
| `INVALID_REQUEST` | 400 | Mọi endpoint, khi validate body thất bại (thay `422` mặc định của FastAPI) |
| `REQUEST_NOT_FOUND` | 404 | Mục 3.1 (status), mục 4.2 (report sai operation/chủ) |
| `REQUEST_ID_CONFLICT` | 409 | Mục 2 (idempotency), mục 4.2 (report conflict) |
| `PHONE_ALREADY_REGISTERED` | 409 | Mục 6.1 |
| `INVALID_CREDENTIALS` | 401 | Mục 6.3 |
| `PHONE_NOT_VERIFIED` | 403 | Mục 6.3 |
| `OTP_INVALID` | 400 | Mục 6.2 |
| `OTP_EXPIRED` | 400 | Mục 6.2 |
| `DEVICE_NOT_FOUND` | 404 | Mục 4.3 |
| `DEVICE_OWNER_CONFLICT` | 409 | Mục 4.3 |
| `GLASSES_DEVICE_OWNER_CONFLICT` | 409 | Mục 5.1 |
| `GLASSES_DEVICE_NOT_LINKED` | 404 | Mục 2 (mọi action, khi `device_id` chưa pairing) |

### 11.3. Lỗi xác thực (`HTTPException` mặc định, khác envelope trên)

```json
{ "detail": "UNAUTHORIZED" }
```

Dùng cho `401`/`403` do sai/thiếu Bearer token — tất cả các mục có auth (2–8).
Riêng mục 4.1 dùng dạng này cho cả `409 DEVICE_OWNER_MISMATCH` và
`403 DEVICE_REVOKED` (không phải lỗi auth nhưng vẫn raise `HTTPException`
trực tiếp thay vì `PublicApiError`).

### 11.4. Lỗi hệ thống

```json
{ "status": "error", "error": { "code": "INTERNAL_ERROR", "message": "Internal server error", "details": {} } }
```

`HTTP 500`, không lộ exception/class/traceback ra ngoài.

## 12. OpenAPI contract xuất riêng

- `contracts/public-api.openapi.yaml` — mục 2 + 3 (`create_public_contract_app`).
- `contracts/device-api.openapi.yaml` — mục 4.1, 4.2, 5.1, 5.2
  (`create_device_contract_app`) — **không** gồm 4.3 (`/device/link` dùng
  user session, không phải Device bearer, nên nằm ngoài cả 2 contract app).

Regenerate: trong `apps/backend`, chạy `uv run python scripts/export_openapi.py`.
