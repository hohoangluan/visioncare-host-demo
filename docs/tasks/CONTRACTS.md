# CONTRACTS — hợp đồng liên repo & quyết định đã chốt

Ngày lập: 2026-08-22 · Nguồn: `SPEC_CAI_THIEN_HOI_THOAI.md`

**Đây là nguồn sự thật cho mọi task.** Task file mô tả *việc phải làm*; file này
mô tả *thứ hai bên phải đồng ý với nhau*. Đổi bất cứ thứ gì ở đây thì phải sửa
task file tương ứng **trước khi** code.

---

## 0. Ba nguyên tắc xuyên suốt

1. **Trạng thái là gợi ý cho bộ phân loại, không phải hàng rào ở router.**
   Người dùng phải nói được bất cứ gì, bất cứ lúc nào. → T04
2. **Cache thứ đứng yên (chữ trên giấy), không bao giờ cache thứ di chuyển
   (không gian, vật cản).** → T14 (cache) vs T16 (không cache)
3. 🔴 **`emergency_call` không đi qua bất kỳ bước xác minh nào.** Ngoại lệ tuyệt
   đối, phải viết **tường minh trong code** chứ không để rơi vào mặc định.
   → T06/D5, T09

---

## 1. Quyết định đã chốt

| # | Quyết định | Nguồn |
|---|---|---|
| 1 | **TTL pending mặc định 120 s** (tầng `fill`) | spec mục 17.3 — người dùng đã chốt "lên 120s đi" |
| 2 | **`readback` cho `contact_name` = `low_conf`** (không phải `always`) | spec mục 17.4 |
| 3 | **P1 (`contact_list`) làm trước P2 (`contact_id` trong candidates)** | spec 26.q1 — làm được P1 thì P2 thành thừa |
| 4 | **F2 (đảo thứ tự part multipart) BỊ HUỶ** | 27.1 — thi công sẽ làm chậm đi |
| 5 | **G8: không thêm earcon phía server** | 27.7 — board đã có `cueSent()` ở 0 ms |
| 6 | **Camera thật = 1280×720, quality 18** (thang esp32-camera 0–63, **nhỏ = nét**) | 27.5 / H0 |
| 7 | **HTTPS bắt buộc trước khi phát hành**; mọi số đo độ trễ chỉ có giá trị khi `API_USE_TLS 1` | 27.3 / F9 F10 |
| 8 | **Số điện thoại đầy đủ không rời khỏi điện thoại** — chỉ 3–4 chữ số cuối, và chỉ khi cần phân biệt | D7, 26.2, 21.8 |
| 9 | **Một pending / device. Không stack, không lồng.** | 21.4 |

---

## 2. Giao thức kính ↔ server kính

### 2.1 `POST /process` — headers (T01/F1)

```
X-Device-Id   BẮT BUỘC   string, ổn định theo board
X-Turn-Id     BẮT BUỘC*  uuid v4, MỚI mỗi lần bấm nút
X-Capture-Ts  nên có     🔴 KHÔNG PHẢI epoch ms — xem ghi chú dưới
```

Header **chứ không phải form field**: server đọc được trước khi body upload xong.

`X-Turn-Id` có **hai** vai trò:
1. chống gửi lặp (idempotency) — cửa sổ **60 s** *(TẠM, chưa chốt, xem mục 7
   câu #12 — dùng CHUNG một con số làm cả TTL kết quả xong lẫn hạn "bỏ hoang"
   của một lượt đang chạy dở, xem mục 4.4)*
2. ngắt lượt cũ (barge-in) — T04/G4

Thiếu `X-Device-Id` → **từ chối rõ ràng** (`config.REQUIRE_DEVICE_ID=1`) hoặc
cảnh báo mỗi lần rồi rơi về `config.VISIONCARE_DEVICE_ID`
(`REQUIRE_DEVICE_ID=0`, **mặc định hiện tại** — giai đoạn chuyển, KHÔNG im
lặng). KHÔNG có nhánh nào rơi về hằng số mà không log.

🔴 **`X-Turn-Id` "BẮT BUỘC" nhưng chưa bị enforce** (khác `X-Device-Id`): server
hiện KHÔNG từ chối và KHÔNG có cờ tương đương `REQUIRE_DEVICE_ID` cho
`X-Turn-Id` — thiếu nó chỉ `logger.warning` rồi đi tiếp với `turn_id=None`.
Hệ quả: idempotency (mục 4.4) và barge-in (T04/G4) **lặng lẽ vô hiệu** cho
đúng request đó, không phải lỗi cứng. Chưa enforce ngay vì risk phá board cũ
lớn hơn `X-Device-Id`: mọi board đã gửi `X-Device-Id` một thời gian, còn
`X-Turn-Id` là header hoàn toàn mới, chưa board thật nào gửi tính tới lúc
viết mục này. Xem câu hỏi #14.

🔴 **`X-Capture-Ts` không phải "epoch ms lúc chụp" trên firmware hiện tại**:
board (không NTP, không RTC) gửi `millis()` — **uptime từ lúc boot**, không
phải epoch thật. Chỉ dùng được để so sánh TƯƠNG ĐỐI trong cùng một phiên
chạy của board — **không** suy ra được thời điểm thực hay so sánh giữa hai
lần reboot khác nhau. T17 (ghép `/frame` với `/process` cùng lượt) **không**
được dùng `X-Capture-Ts` để ghép tuyệt đối giữa hai board hoặc qua reboot —
dùng `X-Turn-Id` (ổn định xuyên suốt một lượt) làm khoá ghép.

### 2.2 `POST /frame` — ảnh, fire-and-forget (T17/F3)

```
X-Device-Id   BẮT BUỘC
X-Turn-Id     BẮT BUỘC   (ghép với lượt audio tương ứng)
X-Capture-Ts  nên có
body: JPEG
→ 204, KHÔNG trả gì cho board đợi
```

Handler đọc qua **một API duy nhất**: `frames.latest(device_id, max_age_ms)`.
Handler **không được biết** frame tới từ đâu.

### 2.3 `GET /events` — downlink SSE (T18/F6)

```
X-Device-Id   BẮT BUỘC
→ text/event-stream, board mở và giữ
heartbeat mỗi N giây
event types: frame_request | call_incoming | ping
```

**Một kênh, hai mục đích.** Không đẻ ra kênh thứ hai.

### 2.4 Đầu ra audio cho board — ràng buộc CỨNG (T02/F8)

```
mono BẮT BUỘC              — ADPCM stereo board từ chối thẳng
16 000 Hz BẮT BUỘC         — khác đi thì mỗi lượt board đổi sample rate I2S 2 lần
prelude 60 byte ra TRƯỚC   — board đọc header WAV trên luồng (app.py:286, :310)
chưa biết độ dài           → ghi size 0 hoặc 0xFFFFFFFF
keep-alive                 → thân trả về phải được đọc HẾT
```

🔴 Board tin **4 byte đầu của thân**, không tin header HTTP. Đi nhầm nhánh
ADPCM/PCM → SNR **−11 dB** ("loa rè"), **không có log nào báo**. `x-audio-format`
và thân phải khớp tuyệt đối.

`RESPONSE_FORMAT == "wav"` (`app.py:467`) gom trọn body → **không dùng cho board**.

---

## 3. Kính gửi gì cho lượt nào (T17/F4)

| Chức năng | Audio | Ảnh | Tầng | Ghi chú |
|---|---|---|---|---|
| `chat` | ✅ | ❌ | — | |
| `ocr` | ✅ | ✅ | **cao** | chữ nhỏ cần nét |
| `ocr` follow-up | ✅ | ❌ | — | dùng `last_ocr` (T14/E3) |
| `describe_space` | ✅ | ✅ | thấp | |
| `describe_hazard` | ✅ | ✅ | thấp | theo lượt |
| `find_object` | ✅ | ✅ | giữa | |
| `read_money` | ✅ | ✅ | giữa | |
| `contact_call` | ✅ | ❌ | — | |
| `emergency_call` | ✅ | ❌ | — | 🔴 **không được chờ ảnh** |
| `nav_start` / `nav_stop` | ✅ | ❌ | — | |
| `ride_quote` / `ride_confirm` | ✅ | ❌ | — | |
| `music_*` | ✅ | ❌ | — | |
| `cancel` / `repeat` | ✅ | ❌ | — | không mạng ngoài, không LLM |
| trả lời pending | ✅ | ❌ | — | **không chụp lại ảnh** |

**10/15 intent không đọc ảnh.**

Cách gửi: **(a) song song cho tầng thấp, (b) hai pha cho tầng cao.**
*(cần đo RTT tunnel để chốt — mục 6)*

Số cụ thể của từng tầng: **chưa điền**, chờ T15/H0 quy về thang 0–63.

---

## 4. Session & pending

### 4.1 TTL theo `kind` (T03/21.3)

| `kind` | TTL | Vì sao |
|---|---|---|
| `confirm` | **25 s** | để lâu nguy hiểm: người dùng quên ngữ cảnh rồi "ừ" cho việc khác |
| `select` | **45 s** | |
| `select` bảng giá xe | **45 s** | giá có surge; quá hạn phải gọi lại, **cấm** đọc lại giá cũ |
| `fill` | **120 s** | quyết định #1 |

**`asked_at` tính từ lúc TTS phát xong**, không phải lúc server tạo pending.

### 4.2 Bảng SLOTS (T06/D1)

| Slot | `ask` | `readback` | `risk` | `kind` |
|---|---|---|---|---|
| `contact_name` | Bạn muốn gọi cho ai? | `low_conf` | high | fill |
| `destination` | Bạn muốn đi đâu? | `low_conf` | high | fill |
| `ride_destination` | Bạn muốn đi đâu? | `always` | high | fill |
| `song_title` | Bạn muốn nghe bài hát nào? | `never` | low | fill |
| `artist` | Bạn muốn nghe của ca sĩ nào? | `never` | low | fill |
| `volume_direction` | Bạn muốn tăng hay giảm âm lượng? | `never` | low | fill |

🔴 **`emergency_number` KHÔNG có mặt. Cố ý.** Có assert trong code.

### 4.3 Thứ tự ưu tiên router (T04/21.1)

```
1. EMERGENCY                 ← tuyệt đối
2. PENDING TẤT ĐỊNH          ← ừ/không/số thứ tự/thôi/nói lại
3. STOP / LỆNH TOÀN CỤC      ← chèn vào ĐÂY
4. PENDING ĐIỀN SLOT         ← qua slot validator
5. CANCEL / REPEAT
6. INTENT DETECT
```

**Đây là thứ dễ bị viết lại sai nhất trong cả spec.** Bước 3 nằm **giữa** hai
pha pending, không phải trên hay dưới cả hai.

### 4.4 Idempotency `POST /process` theo (device_id, turn_id) (T01)

Khoá theo **CẶP** `(device_id, turn_id)`, không phải riêng `turn_id` — hai
thiết bị lỡ trùng `turn_id` không ăn nhầm kết quả của nhau.

Trạng thái mỗi lượt đang giữ trong cache:

```
"pending"  đang chạy pipeline, CHƯA có body. Lượt trùng khoá tới trong lúc
           này phải ĐỢI (không tự chạy lại pipeline), dùng lại kết quả khi
           lượt giữ quyền xong — kể cả khi lượt đầu CHƯA XONG. Đây là ca hay
           bị bỏ sót: "board mất ACK, tự gửi lại trong lúc lượt trước còn
           đang chạy dở", KHÔNG chỉ ca "gửi lại sau khi lượt trước đã xong".
"done"     đã có body, phát lại y nguyên cho mọi lượt trùng khoá.
```

Một lượt "pending" bị bỏ hoang (crash, client rớt giữa chừng) tự hết hạn sau
CÙNG cửa sổ 60s (TẠM) dùng cho TTL của "done" — một con số cho cả hai ý
nghĩa. Sau khi hết hạn, lượt trùng khoá kế tiếp CHIẾM lại quyền chạy pipeline.

🔴 **Race hiếm, chưa xử lý:** nếu pipeline chạy LÂU HƠN cửa sổ 60s, lượt đang
chạy dở bị quét là "bỏ hoang" và một lượt trùng khoá khác được phép chiếm
quyền chạy — không có generation token nào chặn việc lượt cũ, khi xong sau
cùng, ghi đè kết quả lên lượt mới hơn. Vì hai lượt xử lý cùng input nên nội
dung trả về thường tương đương, nhưng đây là lỗ hổng thật trong tính loại trừ
của cơ chế reservation. Chưa cần vá ngay (chỉ lộ khi pipeline > 60s), nhưng
task nào rút ngắn/kéo dài cửa sổ này phải biết race này tồn tại.

Cache có chặn trên số entry (FIFO, mặc định 64) và bỏ qua cache cho thân
audio quá lớn (mặc định > 4 MB).

Lỗi (pipeline nổ, đổi thành câu báo lỗi TTS) VẪN được cache như kết quả
"done" bình thường — lượt trùng khoá trong cửa sổ nhận lại đúng câu báo lỗi,
không thử gọi lại API ngoài lần nữa.

---

## 5. Hợp đồng với server app (8001) & app Android

### 5.1 `contact_call` (T08)

```jsonc
// HIỆN CÓ — endpoint.md:248-270
{ "device_id", "request_id", "name",
  "contact_id": "tuỳ chọn — bỏ qua tìm mờ" }

// MỚI (P1): action contact_list
{ "contacts": [
    { "contact_id": "...", "name": "...", "phone_tail": "456" } ] }

// ĐỔI (P2): candidates[] thêm contact_id
{ "details": { "candidates": [
    { "name": "Mẹ", "phone_number": "***456", "contact_id": "..." } ] } }
```

⚠️ App hiện **so khớp tên bằng nhau tuyệt đối** (`ActionRegistry.kt:110`) — không
có tìm mờ nào. Fuzzy phải nằm ở server kính (T08/D7).

### 5.2 `ride/quote` + `ride/confirm` (T11) — ⛔ chờ Farefeed

```jsonc
// ride/quote trả thêm:
{ "services": [
    { "provider": "grab", "service_id": 1, "service_name": "GrabBike",
      "min_fare": 32000, "max_fare": 38000, "currency": "VND",
      "eta_minutes": 3, "surge": "NONE",
      "deep_link": "...", "direct_deep_link": "..." } ] }

// ride/confirm KHÔNG đặt xe nữa — nhận service_id, trả deeplink
```

`RIDE_ACCOUNT_NOT_CONNECTED` **không dùng** cho đường Grab/Farefeed; giữ cho
provider tương lai.

🔴 **Geocode `address → lat/lng`: hiện KHÔNG AI LÀM.** Đề xuất server app 8001.
**Chưa chốt — chặn cả R lẫn P4/P5.**

### 5.3 Event tự phát — cuộc gọi đến (T19)

```jsonc
// App → Server app  (MỚI, TÁCH khỏi luồng request_id)
POST /api/v1/device/event
{ "device_id", "type": "call_incoming",
  "caller": { "contact_id", "name", "number_tail" } }

// Server app → Server kính  (MỚI, KHÔNG qua /internal/action-results)
POST /internal/device-events

// Preferences (host) — MỞ RỘNG
{ "announce_caller": "name" | "number_only" | "ring_only" }   // mặc định "name"
```

⚠️ `services/action_callbacks.py` hiện **từ chối** callback không có `request_id`
đã đăng ký → event tự phát **cần đường riêng**.

### 5.4 `capabilities_get` (T23)

Enum **đóng**, không phải dict tự do:

```
notification_listener · system_alert_window · battery_optimization_off
background_location (never|while_using|always) · fine_location
read_contacts · read_phone_state · call_phone · send_sms
emergency_contact_set
```

### 5.5 Mã lỗi

Đo ngày **2026-08-22**. Server kính `1581246903fa9b494237e61030773979e9b7c65e`,
app + server app `7ffa42668f8eb1531ef81f60038058809fb7a455`.
Bảng đầy đủ 31 dòng: `measurements/P7-error-matrix.md`.
Fixture cho test: `tests/fixtures/app_error_codes.txt`.

**Mã chỉ được coi là có nguồn khi có code chạy dựng ra nó** — một
`ReportErrorPayload("<MÃ>", ...)` ở app, hoặc một `{"code": ...}` được ghi vào
cột `error` của operation ở server app. Tên mã trong `endpoint.md` KHÔNG phải
nguồn. `INVALID_DESTINATION` có tên ở 6 chỗ trong tài liệu và 0 chỗ trong code.

#### Mã có nguồn thật VÀ có câu ở server kính — 12 mã (chốt)

| Mã | Nguồn | Loại |
|---|---|---|
| `CONTACT_NOT_FOUND` | app | retryable — reask `contact_name` |
| `MULTIPLE_CONTACTS_FOUND` | app | retryable — `select` |
| `CONTACT_PERMISSION_DENIED` | app | terminal |
| `CALL_PERMISSION_DENIED` | app | terminal |
| `EMERGENCY_CONTACT_NOT_CONFIGURED` | app | terminal |
| `SONG_NOT_FOUND` | app | retryable — reask `song_title` |
| `PLAYBACK_STOP_FAILED` | app | retryable |
| `SUBSCRIPTION_INACTIVE` | app | terminal |
| `CURRENT_LOCATION_UNAVAILABLE` | app | retryable |
| `LOCATION_PERMISSION_DENIED` | app | terminal |
| `NO_RIDE_AVAILABLE` | app | terminal — ⚠️ app đang phát cho lỗi parse tham số, sai nghĩa |
| `DELIVERY_FAILED` | server app | terminal |

#### Mã app phát mà server kính CHƯA có câu riêng — 8 mã, phải thêm câu

`PLAYBACK_FAILED` · `CALL_FAILED` · `INVALID_VOLUME` · `NAVIGATION_START_FAILED`
`NAVIGATION_STOP_FAILED` · `RIDE_CONFIRM_FAILED` · `INVALID_PARAMS`
`UNSUPPORTED_ACTION`

Tất cả hiện rơi vào `_GENERIC_FAILURE` hoặc `_UNSPECIFIED_FAILURE` — có tiếng
nói, nhưng câu không cho biết phải làm gì. `CALL_FAILED` ưu tiên cao nhất: nó
gồm cả ca **gọi khẩn cấp không quay số được**.

#### Mã server kính có câu mà KHÔNG ai phát — 10 mã

⚠️ Nửa dưới của bảng này (nhánh app/app backend) chỉ được xác nhận bằng grep
một lần trên một commit cụ thể của repo ngoài, không có test tự động canh giữ —
xem lại bằng `git -C <repo app> grep` trước khi xoá dòng nào trong
`_ERROR_SPEECH`, đừng xoá chỉ vì bảng này nói vậy.

Đề nghị xoá (7 dòng, do app/app backend chưa từng phát):
`NAVIGATION_NOT_FOUND` · `NAVIGATION_ALREADY_STOPPED` · `QUOTE_NOT_FOUND`
`QUOTE_EXPIRED` · `NO_ACTIVE_PLAYBACK` · `MUSIC_ACCOUNT_NOT_CONNECTED`
`SMS_PERMISSION_DENIED`

Ba mã còn lại của nhóm "10" xử khác — không xoá:

- `RIDE_ACCOUNT_NOT_CONNECTED` — giữ cho provider tương lai (mục 5.2, T11).
- `GLASSES_DEVICE_NOT_LINKED` — mã CÓ thật nhưng đi bằng **HTTP 404 của chính
  lời gọi POST**, không nằm trong `error.code`, nên `_ERROR_SPEECH` không bao
  giờ tra tới. Xoá khỏi `_ERROR_SPEECH`; bắt nó ở `handlers/action_flow.py`.
- `INVALID_DESTINATION` **chưa quyết** — chờ câu hỏi mở số 7 (mục 7 dưới).

#### Mã KHÔNG bao giờ tới `_ERROR_SPEECH` — không thêm câu

`REPORT_TIMEOUT` (server app) luôn đi kèm `request_state="timed_out"`, mà
`speak_result` trả `_TIMEOUT_MESSAGE` trước khi đọc `error.code`.

#### Fallback mặc định — 21.7

Thứ tự tra, KHÔNG có nhánh nào rơi vào im lặng:

```
1. request_state == "timed_out"   -> _TIMEOUT_MESSAGE
2. _ERROR_SPEECH[code]            -> câu riêng của mã
3. _GENERIC_FAILURE[operation]    -> câu riêng của operation
4. _DEFAULT_POLICY.speech         -> mặc định (thay _UNSPECIFIED_FAILURE)
```

`_DEFAULT_POLICY` = `retryable=False`, `reask=None`, câu nói phải (1) nói rõ là
không làm được, (2) nói rõ là không biết lý do, (3) chỉ đúng một hành động khả
thi là xem thông báo trên điện thoại. Mặc định KHÔNG retryable: chưa biết mã
nghĩa là gì thì không được đặt pending, vì pending sai nuốt câu kế tiếp của
người dùng (quyết định #9).

#### Giữ hợp đồng này khỏi trôi

`tests/fixtures/app_error_codes.txt` là nguồn sự thật chép tay, **bắt buộc có
ngày + commit hash của cả hai repo**. Cập nhật khi `ActionRegistry.kt` thêm/bớt
một `ReportErrorPayload`, hoặc server app thêm một payload lỗi mới.
`tests/test_error_contract.py` đối chiếu fixture với `_ERROR_SPEECH`.

*(Ghi chú thực thi: bảng gốc `_ERROR_SPEECH` có 22 mã — 12 giữ + 10 xử theo mục
trên = 22, khớp. Số này không tự động đối chiếu được — `tests/test_error_contract.py`
phải tự đếm và so, không copy con số 22 này.)*

---

## 6. Ngân sách độ trễ (T21/G1)

⚠️ **Mọi số dưới đây phải đo lại trên bản `API_USE_TLS 1`** (quyết định #7).

| Đường | Mục tiêu |
|---|---|
| `emergency_call` ack | **< 300 ms** |
| `cancel` / `repeat` / stop | **< 300 ms** |
| trả lời pending tất định | **< 400 ms** |
| `contact_call` ack | **< 600 ms** |
| `hazard` | < 800 ms |
| `chat` | < 1.0 s |
| `ocr` / `space` / `find` / `money` | < 1.2 s · 🔴 `ocr` **chưa chốt riêng** |

**Dòng thứ hai, đo khác hẳn (T02/G11):**

```
tỉ lệ (giây tiếng)/(giây đồng hồ) ≥ 1.30×
```

TTFB đạt mà tỉ lệ này không đạt thì người dùng **vẫn không nghe gì** cho tới khi
sinh xong cả câu.

**Mọi lời gọi ngoài có deadline.** Quá deadline → câu dựng sẵn, không treo im lặng.

---

## 7. Câu hỏi CHƯA CHỐT — chặn task nào

| # | Câu hỏi | Chặn |
|---|---|---|
| 1 | 🔴 **Quyền partner Farefeed** — đã liên hệ Grab chưa? | T11 (R1 R2 R3 R5) |
| 2 | 🔴 **Ai geocode `address → lat/lng`?** | T11 · P4 P5 |
| 3 | 🔴 **Ngân sách `ocr` là bao nhiêu?** | T15 nghiệm thu · T21 |
| 4 | 🔴 **Miếng kết thúc chunked có tới board không?** | T21 — **đo trước, 1 lệnh curl** |
| 5 | 🔴 **Bật TLS rồi p95 bao nhiêu?** | T21 · T18 |
| 6 | 🔴 **RAM đủ cho socket SSE thứ hai không?** (đo **sau** khi bật TLS) | T18 · T19 |
| 7 | **App có kiểm được địa điểm** (để `INVALID_DESTINATION` có nguồn)? | T20 · T10/D4 |
| 8 | **P1 (`contact_list`) có làm được không?** | T08 chạy đủ hay nửa vời |
| 9 | **Cache vị trí toàn cục hay theo device?** | T03 · T07 |
| 10 | **`max_age_ms` cho frame là bao nhiêu?** (800 ms gần như chắc chắn sai) | T17 |
| 11 | **RTT thật qua Cloudflare tunnel?** (> 400 ms thì phương án (b) mất giá) | T17/F4 |
| 12 | **Cửa sổ idempotency 60 s?** Cùng con số này còn dùng làm hạn "bỏ hoang" cho một lượt đang chạy dở (mục 4.4) — chốt một lần cho cả hai nghĩa, hay tách riêng? | T01 |
| 13 | **Ngưỡng so khớp danh bạ 88/70/margin 8** — cần danh bạ thật để đo lại | T08 |
| 14 | 🔴 **`X-Turn-Id` thiếu có nên có cờ `REQUIRE_TURN_ID`** (như `REQUIRE_DEVICE_ID`) để tới lúc nào đó ép buộc, hay mãi mãi chỉ cảnh báo? Hiện KHÔNG enforce — mọi board đã có sẽ gửi thiếu header này cho tới khi lên firmware mới. | T01 · T04 (barge-in phụ thuộc) |
| 15 | **`device_id` firmware lấy từ MAC WiFi hay NVS?** Đang dùng MAC WiFi làm TẠM (ổn định, không cần cấu hình) — không đổi được lúc ghép kính↔tài khoản nếu sau này cần. | T01 |

---

## 8. Bảng đo phải có trong repo

Nguyên tắc của repo: **có bảng số thì mới được chốt**
(giống `config.py:104-121` và ngưỡng blur).

| File | Nội dung | Task |
|---|---|---|
| `measurements/G10.md` | miếng kết thúc chunked, localhost vs tunnel | T02 |
| `measurements/G11.md` | tỉ lệ nhả TTS | T02 |
| `measurements/A2.md` | bảng ca STT sai → slot trích được | T05 |
| `measurements/H0-blur-720p.md` | ngưỡng Laplacian trên 1280×720 | T15 |
| `measurements/H4.md` | ma trận 3 model × 3 biến thể OCR | T15 |
| `measurements/P7-error-matrix.md` | đối chiếu mã lỗi hai chiều | T20 |
| `measurements/F9.md` | p50/p95 có TLS, lượt nóng và nguội | T22 |
| `measurements/F6-ram.md` | RAM với 2 socket + TLS | T18 |
| `measurements/G1.md` | ngân sách đo trên bản TLS | T21 |
| `measurements/G7.md` | prefix cache có ăn theo tiền tố không | T13 |
| `measurements/D7-thresholds.md` | ngưỡng danh bạ trên danh bạ thật | T08 |
