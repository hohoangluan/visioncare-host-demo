# T11 — Đặt xe (`ride_quote` / `ride_confirm`)

| | |
|---|---|
| **Mã spec** | R1 R2 R3 R4 R5 R6 R7 · P3 P4 P5 P6 |
| **SPEC gốc** | mục 12, 26.3, 26.4, 18 |
| **Repo đụng** | **cả 3** — Server kính · Server app · App Android |
| **Trạng thái** | 🔴 **PARTIAL** — R1 R2 R3 R5 **BLOCKED** |
| **Chặn bởi** | **T07** (R6 = vị trí thật) · T03 T06 · ⛔ **quyền partner Farefeed** |
| **Chặn** | — |

> **Đọc 26.3 và 26.4 trước.** Mục 12 mới ghi một nửa: spec nói *"người dùng
> không biết giá"* — thực tế nặng hơn, **đã có sẵn một con số giả nằm đúng chỗ
> R3 định đọc lên**, và **cả điểm đón lẫn điểm đến đều là hằng số**.

---

## 0. Chia BLOCKED / làm được ngay

| Làm được ngay | Điều kiện |
|---|---|
| **R4** pending mới + TTL 45 s | T03 |
| **R6** vị trí thật, bỏ `_DEMO_CURRENT_LOCATION` | T07 |
| **R7** câu bàn giao nói rõ còn phải chạm | — |
| **P3** xoá giá bịa ở app | app |
| **P4 P5** bỏ toạ độ hằng số ở app | app |

| ⛔ BLOCKED | Chặn bởi |
|---|---|
| **R1** lượt 1 gọi Farefeed thật | `client_id`/`client_secret` + scope `ride.estimate` — **chỉ cấp khi onboarding partner**, bản công khai đã gỡ khỏi web từ 20/06/2024 |
| **R2** đọc 2 lựa chọn | R1 |
| **R3** đọc khoảng giá + cảnh báo surge | R1 |
| **R5** `handle_confirm` khớp `serviceID` → deeplink | R1 |
| **P6** geocode `address → lat/lng` | chưa chốt **ai làm** (mục 6) |

**Làm R4/R6/R7 + P3/P4/P5 trước. Đừng chờ Grab.**

---

## 1. Hiện trạng

### Server kính — mẫu tốt nhất repo, nhưng hai lượt đặt sai chỗ

`handlers/ride.py` (số dòng thật, spec ghi 71/83 đã trôi):

| Dòng | Nội dung |
|---|---|
| `:14` | 🔴 `_DEMO_CURRENT_LOCATION = {"lat": 10.7769, "lng": 106.7009}` — Quận 1, TP.HCM |
| `:16` | `_PENDING_DESTINATION = "pending_ride_destination"` (chuỗi tự do, không TTL) |
| `:23` | `_OPENING_RIDE_APP` = *"đang mở ứng dụng đặt xe, bạn chờ một chút"* |
| `:27` | `_WAITING_IN_APP` — ngõ cụt |
| `:44-58` | `_open_ride_app()` — gửi `current_location` hằng số + `{"address": destination}`, **không có lat/lng điểm đến** |
| `:61-72` | `handle_quote()` — **chưa gọi API**, chỉ đọc lại tên, `remember(_PENDING_DESTINATION, ...)` |
| `:75-98` | `handle_confirm()` — có pending → gọi `ride/quote` thật |

**Hai lượt đang đặt sai chỗ.** Lượt 1 không gọi API, chỉ đọc lại tên điểm đến
(thứ vừa nghe từ STT, giá trị thấp). Lượt 2 mới gọi API rồi ném thẳng sang app.
Nghĩa là **lượt xác nhận đắt tiền nhất diễn ra khi trong tay chưa có một dữ kiện
thật nào.**

### App Android — hai lỗi 🔴

#### 26.3 — giá là số bịa, và Grab mở ngay ở lượt báo giá

`ActionRegistry.kt:1391-1397`:

```kotlin
"product_type" to "GrabCar",
"price_estimate" to mapOf("currency" to "VND", "amount" to 85000),
"eta_minutes" to 6,
```

85 000 đ và 6 phút **không đến từ đâu cả** — comment ngay trên ghi là
"demo-deterministic". Làm R1/R3 mà không đụng vào đây thì hệ thống đọc *"tám mươi
lăm nghìn"* bằng giọng tự tin cho **mọi chuyến, mọi quãng đường**.

Thêm nữa: `RideQuoteHandler` **mở Grab ngay tại lượt báo giá** (`:1387`), rồi
`ride_confirm` mở Grab **lần thứ hai**.

#### 26.4 — 🔴 điểm đến là hằng số

```kotlin
// :1418
openGrabDeepLink(context, 10.7721, 106.6578, "diem den")
// :1379-1381
val lat = destObj?.optDouble("lat", 10.7721) ?: 10.7721
```

Server kính **chỉ gửi `{"address": destination}`** (`ride.py:49`), không gửi
`lat`/`lng` → nhánh mặc định **luôn** trúng.

**Mọi chuyến xe đều đón ở Quận 1 và đến 10.7721, 106.6578, nhãn `"diem den"`.**

Với người khiếm thị đây là **ca hỏng tệ nhất trong toàn spec**: họ không nhìn màn
hình Grab, không có cách nào biết điểm đến vừa bị thay.

### Trần kỹ thuật (khảo sát 2026-08)

**Grab không có API đặt xe cho bên thứ ba.** Thứ duy nhất dùng được là Farefeed:

```
POST https://partner-api.grab.com/farefeed/v1/estimate
Authorization: Bearer {token}        # OAuth 2.0, scope: ride.estimate
body: { pickUp: {latitude, longitude, address},
        dropOff: {latitude, longitude, address} }
```

Trả `services[]`: `serviceID`/`serviceName` · `fare.minFare`/`maxFare`/`currency`
(**khoảng** giá, không phải giá chốt) · `eta` (phút xe tới **điểm đón**) ·
`surgeNotice` ∈ `NONE`/`LOW_SURGE`/`HIGH_SURGE`/`FRACTIONAL_SURGE` ·
`deepLink`/`directDeepLink` (prefill sẵn đón + đến + `taxiTypeId`).

**Không có endpoint tạo booking. Không có API trạng thái chuyến.**

→ **Trần của tính năng này là "một chạm", không phải "không chạm".**

---

## 2. Việc phải làm

### Luồng mới

```
lượt 1   "đặt xe tới Bách Khoa"
         → geocode + Farefeed (gọi THẬT)
         → "Đi Bách Khoa. Xe máy 32 đến 38 nghìn, xe tới sau 3 phút.
            Ô tô 78 đến 90 nghìn, 6 phút. Bạn đi xe nào?"
lượt 2   "xe máy"
         → chốt serviceID, lấy deepLink trong pending, đẩy FCM
         → "Đã mở Grab: xe máy đi Bách Khoa, 32 đến 38 nghìn.
            Bạn chạm một lần vào nút đặt xe ở cuối màn hình."
```

### 2.1 Server kính — làm được ngay

#### R4 — pending mới, TTL **45 s** (không phải 120 s)

Thay `_PENDING_DESTINATION` (chuỗi) bằng `Pending` của T03:

```python
Pending(kind="select", slot="ride_service", intent="ride_confirm",
        known={"destination": ...},
        candidates=[...services...],
        ttl=45.0)
```

**Vì sao 45 s:** giá có surge. Đọc lại một bảng giá cũ là **nói sai số tiền**.
Hết hạn → gọi lại Farefeed, **cấm tái dùng `services[]` cũ**.

#### R6 — vị trí thật (= A6, giờ nặng hơn)

Xoá `_DEMO_CURRENT_LOCATION` (`ride.py:14`). Dùng cache vị trí của T07.

Với Farefeed, sai điểm đón không chỉ đón nhầm chỗ mà còn **báo giá sai** và
**prefill sai vào deeplink**.

Không có vị trí → nói thẳng *"chưa xác định được vị trí của bạn, chưa đặt xe
được"*. **Không âm thầm rơi về Quận 1.**

#### R7 — câu bàn giao phải nói rõ **còn phải chạm**

`_OPENING_RIDE_APP` (`:23`) hiện là *"bạn chờ một chút"* → **ngụ ý hệ thống đang
tự đặt**. Sai, và người dùng sẽ đứng đợi một chuyến không bao giờ tới.

Đổi thành câu nói thẳng: đã mở · đúng loại xe · đúng giá · **còn một chạm**.

`_WAITING_IN_APP` (`:27`) giữ vai trò ngõ cụt nhưng phải **nói thật** rằng server
không theo dõi được chuyến sau khi bàn giao (Grab không có API trạng thái).

#### Giữ `readback = "always"` cho ride

Lý do cũ (tốn tiền thật) vẫn đúng, và sau R1 lượt readback còn chở thêm **giá** —
nó trở thành lượt có giá trị nhất trong cả luồng.

### 2.2 Server kính — ⛔ BLOCKED (chờ Farefeed)

- **R1** — `handle_quote` (`:61`) chuyển từ "không gọi API" sang **"gọi API"**;
  `handle_confirm` (`:75`) chuyển ngược lại thành **"không gọi API"**.
- **R2** — đọc **tối đa 2 lựa chọn**: rẻ nhất nhóm 2 bánh + rẻ nhất nhóm 4 bánh.
  Đọc 5 dòng dịch vụ bằng giọng là quá tải trí nhớ ngắn hạn.
  *"còn xe nào khác"* → đọc nốt phần còn lại **từ pending, không gọi API lại**.
- **R3** — **luôn đọc khoảng giá**, đúng như API trả, **không làm tròn thành một
  số**. `surgeNotice ∈ {HIGH_SURGE, FRACTIONAL_SURGE}` → chèn *"đang giờ cao
  điểm, giá thực tế có thể cao hơn"*.
  Đọc một con số chốt rồi bị lệch là mất niềm tin, và người khiếm thị **không có
  cách nào tự kiểm chứng**.
- **R5** — `handle_confirm` **không gọi API nữa**: khớp câu trả lời ("xe máy",
  "ô tô", "cái rẻ hơn") sang `serviceID` trong pending, lấy `deepLink` tương ứng,
  đẩy xuống app. Không round-trip.
  **Tham số `provider` để riêng ngay từ đầu**, đừng viết chết vào Grab.

### 2.3 Server app (8001) — đổi hợp đồng + tích hợp Farefeed

Xem mục 3.

### 2.4 App Android

- **P3** — xoá `price_estimate` / `eta_minutes` bịa (`:1391-1397`). **Không có
  nguồn giá thật thì không trả trường giá**, để server kính không có gì đọc nhầm.
- **P4** — bỏ **mọi** toạ độ mặc định trong `RideQuoteHandler` /
  `RideConfirmHandler`. Thiếu toạ độ → trả `INVALID_DESTINATION`, **không đoán**.
- **P5** — `RideConfirmHandler` dùng lại điểm đến của đúng `quote_id` (lưu map
  `quote_id → {lat, lng, address}` lúc quote), không dựng lại từ hằng số.
- **26.q3** — `ride_quote` **không được mở Grab** ở lượt báo giá.

---

## 3. Hợp đồng đổi

`ride/quote` (`endpoint.md` §2.1) trả thêm danh sách dịch vụ:

```json
{ "services": [
    { "provider": "grab", "service_id": 1, "service_name": "GrabBike",
      "min_fare": 32000, "max_fare": 38000, "currency": "VND",
      "eta_minutes": 3, "surge": "NONE",
      "deep_link": "https://...", "direct_deep_link": "grab://..." } ] }
```

`ride/confirm` (§2.2) **không đặt xe nữa** — nhận `service_id`, trả deeplink để
app mở.

`RIDE_ACCOUNT_NOT_CONNECTED` **không dùng** cho đường Grab/Farefeed (Farefeed
không cần user link tài khoản); giữ lại cho provider tương lai.

**P6 — geocode `address → lat/lng`: hiện KHÔNG AI LÀM.** Server kính không, app
không. Chọn một chỗ rồi ghi vào hợp đồng — hợp lý nhất là **server app 8001**,
cùng chỗ sẽ gọi Farefeed.

---

## 4. Test

### 4.1 Làm được ngay — `tests/test_ride_quote.py` (mới)

Farefeed **giả lập**, không cần quyền partner:

```
test_no_location_refuses_to_book              # 🔴 R6, ca quan trọng nhất
  cache vị trí rỗng → TỪ CHỐI đặt
  → KHÔNG rơi về 10.7769, 106.7009

test_demo_location_constant_is_gone           # R6
  grep _DEMO_CURRENT_LOCATION → không còn

test_pending_ttl_45s_not_120s                 # R4
test_expired_pending_refetches                # R4
  pending quá 45 s → gọi lại Farefeed
  → KHÔNG tái dùng services[] cũ

test_handover_says_one_more_tap               # R7
  câu bàn giao CHỨA ý "còn phải chạm"
  → KHÔNG có "bạn chờ một chút"

test_waiting_in_app_admits_no_tracking        # R7
```

### 4.2 BLOCKED — viết sẵn, `xfail` cho tới khi có Farefeed

```
@pytest.mark.xfail(reason="R1: chưa có quyền partner Farefeed")

test_quote_turn_calls_farefeed                # R1
  lượt 1 PHẢI gọi API (hiện không gọi)
test_confirm_turn_makes_no_request            # R5
  handle_confirm KHÔNG phát sinh request nào ra host

test_reads_fare_range_not_single_number       # R3
  câu nói có CẢ min và max, không phải một số

test_high_surge_adds_warning                  # R3
  surge=HIGH_SURGE → câu CHỨA cảnh báo giờ cao điểm

test_reads_only_two_options                   # R2
  services[] có 5 → đọc đúng 2 (rẻ nhất 2 bánh + rẻ nhất 4 bánh)

test_more_options_no_api_call                 # R2
  "còn xe nào khác" → đọc nốt từ pending, KHÔNG gọi API lại

test_provider_is_a_parameter                  # R5
  không có chuỗi "grab" viết chết trong handler
```

### 4.3 App — kiểm bằng tay hoặc test phía app

```
P3  ride_quote KHÔNG trả price_estimate bịa
P4  thiếu toạ độ → INVALID_DESTINATION, không dùng 10.7721
P5  confirm dùng đúng điểm đến của quote_id
26.q3  ride_quote không mở Grab
```

### 4.4 Thủ công — 🔴 bắt buộc trước khi cho người thật dùng

| Kịch bản | Đạt khi |
|---|---|
| Đặt xe tới một chỗ **không phải Quận 1** | Grab mở ra đúng điểm đón **và** đúng điểm đến |
| Tắt định vị rồi đặt xe | **từ chối**, nói rõ lý do |
| Nghe câu bàn giao | hiểu được là **còn phải chạm**, không đứng đợi |
| Hỏi "xe tới chưa" sau khi bàn giao | nghe câu thật thà, không phải câu ngụ ý đang theo dõi |

---

## 5. DoD

```bash
pytest tests/test_ride_quote.py -q
```

- [ ] `_DEMO_CURRENT_LOCATION` **đã xoá**, không còn đường nào rơi về Quận 1
- [ ] Không có vị trí → **từ chối đặt**, có test
- [ ] Pending ride dùng `kind="select"`, TTL 45 s, hết hạn thì gọi lại
- [ ] Câu bàn giao nói rõ **còn một chạm**
- [ ] `_WAITING_IN_APP` thừa nhận không theo dõi được chuyến
- [ ] App: P3 P4 P5 xong **hoặc** ghi rõ còn hỏng — ⚠️ chưa xong P4/P5 thì luồng
      này **vẫn gửi người dùng tới toạ độ sai**, không được coi là dùng được
- [ ] R1 R2 R3 R5 để `xfail` với lý do Farefeed — **không xoá test**
- [ ] Trạng thái file giữ **PARTIAL** cho tới khi có quyền partner

---

## 6. Câu hỏi phải chốt

1. 🔴 **Quyền partner Farefeed** — đã liên hệ Grab chưa, ai đứng tên pitch? Đây
   là **đường găng** của cả nhóm R. Grab từ chối thì:
   (a) giữ hành vi hiện tại, chỉ làm R4/R6/R7, hay
   (b) đổi provider lấy giá (EMDDI) và chấp nhận phủ xe mỏng hơn?
2. 🔴 **Ai geocode (P6)?** Server kính, server app, hay app. Chưa chốt là **chặn
   cả R lẫn P4/P5**. Đề xuất: server app 8001.
3. **Đọc mấy lựa chọn xe là vừa?** R2 chốt 2. Cần thử với người dùng thật — 2 có
   thể vẫn là nhiều nếu tên dịch vụ dài.
4. **`ride_quote` mở Grab ngay ở lượt báo giá** — sửa ở app (chỉ mở khi confirm)
   hay đổi hợp đồng để có action `ride_quote` không mở UI?

## 7. Ràng buộc ngoài kỹ thuật — đọc trước khi code R1

1. **Farefeed không self-serve.** Phải xin quyền partner trước.
2. 🔴 **Cấm lái UI app Grab bằng AccessibilityService** để bấm hộ nút đặt. Vi
   phạm ToS, ban tài khoản thật của người dùng, vỡ mỗi lần Grab đổi layout — và
   người khiếm thị **không phát hiện được** là nó vừa bấm nhầm cái gì.
3. **Muốn bỏ nốt cú chạm** thì cần provider có API đặt thật (EMDDI bán tích hợp
   như một sản phẩm; Xanh SM / Be phải qua hợp đồng BD). Không thuộc spec này —
   nhưng R5 **tách `provider` ra tham số** để cắm sau mà không viết lại handler.
4. **Nghị định 158/2024** (hiệu lực 01/01/2025): hợp đồng điện tử + hoá đơn phải
   gửi về **tài khoản của chính khách** → không được đặt chung bằng một tài khoản
   hệ thống. Đường deeplink thoả mãn tự nhiên; provider tương lai nào cũng phải
   giữ tính chất đó.
