# T23 — Quyền & cấu hình mà người khiếm thị không tự bật được

| | |
|---|---|
| **Mã spec** | P10 · P11 · 26.7 26.8 |
| **SPEC gốc** | 26.7, 26.8 |
| **Repo đụng** | **App Android** · Server kính |
| **Trạng thái** | READY |
| **Chặn bởi** | — |
| **Chặn** | — (nhưng cải thiện chất lượng lỗi của T09 T12 và mọi luồng action) |

> Ba thứ phải bật **bằng tay trong Cài đặt hệ thống**, không có API xin. Người
> khiếm thị tự đi qua các màn hình đó là **rất khó**, và **không có đường nào báo
> về server kính rằng chúng chưa bật** — hỏng hiện ra dưới dạng một mã lỗi chung
> ở tận đầu bên kia.

---

## 1. Hiện trạng

### 26.7 — ba thứ không xin được bằng API

| Cần cho | Thứ phải bật bằng tay |
|---|---|
| `music_play` đường dự phòng YouTube Music | Notification listener (`MediaControlListenerService`) |
| Lệnh chạy khi màn hình khoá | `SYSTEM_ALERT_WINDOW` + bỏ tối ưu pin |
| `emergency_call` chạy từ push nền | `ACCESS_BACKGROUND_LOCATION` — phải chọn **"Luôn cho phép"** |

Cộng thêm (T07/P8): `play-services-location` **chưa có** trong
`app/build.gradle.kts`.

### 26.8 — số khẩn cấp nằm trong SharedPreferences

`ActionRegistry.kt:392` đọc từ `SharedPreferences` (đặt ở màn hình Overview /
Safety). Chưa cài → `EMERGENCY_CONTACT_NOT_CONFIGURED`, và người dùng chỉ biết
điều đó **vào đúng lúc gọi cấp cứu**.

> Phần còn lại của handler emergency làm **tốt hơn** mức spec đòi
> (`:424-440`) — SMS song song với cuộc gọi, timeout riêng, không chặn tiếng
> chuông. **Giữ nguyên.** Xem T09.

---

## 2. Việc phải làm

### P10 — action `capabilities_get`

App trả trạng thái từng quyền/cài đặt:

```jsonc
{ "capabilities": {
    "notification_listener":     true,
    "system_alert_window":       false,
    "battery_optimization_off":  false,
    "background_location":       "while_using",   // never | while_using | always
    "fine_location":             true,
    "read_contacts":             true,
    "read_phone_state":          false,           // T19
    "call_phone":                true,
    "send_sms":                  true,
    "emergency_contact_set":     false            // P11
} }
```

Server kính đọc **lúc ghép máy**, và khi một chức năng hỏng thì nói **đúng thứ
đang thiếu**:

| Thay vì | Nói |
|---|---|
| *"chưa phát được nhạc"* | *"chưa bật quyền đọc thông báo nên chưa phát nhạc được"* |
| *"chưa gọi được"* | *"ứng dụng chưa được cấp quyền gọi điện"* |

Đây là điểm của cả task: **biến một mã lỗi chung thành một câu người dùng làm
được gì đó với nó.**

### P11 — kiểm số khẩn cấp lúc ghép máy, **không phải lúc gọi**

`emergency_contact_set = false` → nhắc **một lần** bằng giọng nói lúc ghép kính /
khởi động.

**Biết vào lúc đang ngã là biết quá muộn.**

Đây là một trường của `capabilities_get` — không cần cơ chế riêng.

### Server kính — dùng capabilities ở hai chỗ

```
1. lúc ghép máy / khởi động
   → thiếu thứ QUAN TRỌNG (emergency_contact, call_phone) → nhắc bằng giọng
   → thiếu thứ phụ (notification_listener) → im, để dành cho lúc dùng

2. lúc một action hỏng
   → tra capabilities đã cache
   → thay câu lỗi chung bằng câu chỉ đúng thứ thiếu
```

Cache capabilities như cache vị trí (T07) và danh bạ (T08/P1) — nhưng **làm mới
khi có mã lỗi liên quan quyền**, vì người dùng có thể vừa bật xong.

### Ràng buộc: **không** biến việc này thành rào cản

Thiếu quyền phụ → **vẫn cho thử**, hỏng thì mới nói. Chặn trước là biến một
chức năng dùng được 80 % thành không dùng được.

Ngoại lệ: `emergency_call` — cái này **phải** kiểm trước, vì lúc cần thì không
kịp sửa.

---

## 3. Hợp đồng đổi

```jsonc
// MỚI: action capabilities_get  (server kính → host → app)
GET/POST .../service/capabilities        // tên endpoint do host chốt
→ { "capabilities": { ...bảng ở 2.P10... } }
```

Ghi vào `CONTRACTS.md`. Danh sách khoá phải **đóng** (enum), không phải dict tự
do — không thì server kính không map được sang câu nói.

---

## 4. Test

### 4.1 Server kính — `tests/test_capabilities.py` (mới)

```
test_capabilities_cached_at_pairing
test_missing_emergency_contact_warns_once      # 🔴 P11
  emergency_contact_set=false → nhắc MỘT lần, không nhắc mỗi lượt

test_missing_minor_permission_stays_silent
  notification_listener=false → KHÔNG nhắc lúc khởi động

test_error_speech_mentions_missing_permission  # 🔴 P10, ca chính
  music_play hỏng + notification_listener=false
  → câu nói CHỨA "quyền đọc thông báo"
  → KHÔNG phải "chưa phát được nhạc"

test_capabilities_refreshed_on_permission_error
  mã lỗi liên quan quyền → tra lại, không dùng cache cũ

test_missing_capability_does_not_block_attempt
  thiếu quyền phụ → VẪN thử, hỏng mới nói

test_emergency_checked_before_use              # ngoại lệ
```

### 4.2 Khi app chưa hỗ trợ

```
test_no_capabilities_endpoint_degrades_gracefully
  app cũ không có action này → server kính dùng câu lỗi chung như hiện tại
  → KHÔNG crash, KHÔNG chặn chức năng
```

Ca này quan trọng: app cập nhật chậm hơn server.

### 4.3 Thủ công — cần máy Android thật

| Kịch bản | Đạt khi |
|---|---|
| Tắt notification listener rồi phát nhạc | nghe **đúng thứ đang thiếu** |
| Chưa cài số khẩn cấp, khởi động kính | được nhắc **lúc đó**, không phải lúc gọi |
| Bật quyền xong, thử lại ngay | chạy được, không phải restart |
| Tắt quyền danh bạ rồi gọi tên | nghe câu về quyền danh bạ |
| Khoá màn hình rồi ra lệnh | chạy được, hoặc nói rõ thiếu `SYSTEM_ALERT_WINDOW` |

---

## 5. DoD

```bash
pytest tests/test_capabilities.py -q
```

- [ ] `capabilities_get` có hợp đồng **enum đóng** trong `CONTRACTS.md`
- [ ] App trả đủ 10 trường ở bảng P10
- [ ] Server kính cache, làm mới khi gặp mã lỗi về quyền
- [ ] Câu lỗi **chỉ đúng thứ đang thiếu**, có test so chuỗi
- [ ] `emergency_contact` kiểm **lúc ghép máy**, nhắc **một lần**
- [ ] Thiếu quyền phụ **không chặn** việc thử
- [ ] App cũ không có endpoint → **thoái hoá êm**, không crash
- [ ] `play-services-location` đã thêm (kéo theo T07/P8)

---

## 6. Câu hỏi phải chốt

1. **Tên và dạng endpoint?** `capabilities_get` là action (qua FCM) hay endpoint
   REST đồng bộ? Đồng bộ thì server kính đọc được lúc cần; qua FCM thì phải chờ
   round-trip. Đề xuất **REST đồng bộ**, vì đây là dữ liệu tra cứu.
2. **Nhắc quyền bằng giọng nói bao nhiêu lần là vừa?** Một lần thì có thể người
   dùng đang không nghe. Nhiều lần thì phiền. Đề xuất: một lần mỗi phiên ghép máy.
3. **Ai hướng dẫn người khiếm thị đi qua màn hình Cài đặt hệ thống?** Đây là vấn
   đề **ngoài phần mềm** — có thể cần người sáng hỗ trợ lúc cài đặt lần đầu. Ghi
   vào tài liệu hướng dẫn, đừng giả định app tự lo được.
4. **P11 làm ở đây hay ở T09?** Ở đây thì gọn hơn. Nhưng emergency không nên chờ
   task này — nếu T23 bị hoãn thì T09 tự làm phần P11.
