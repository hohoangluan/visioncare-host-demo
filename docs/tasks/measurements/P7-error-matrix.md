# P7 — Ma trận mã lỗi hai chiều (T20)

Ngày đo: **2026-08-22**

| Repo | Đường dẫn | Commit |
|---|---|---|
| Server kính | `d:\Study\innostar\Sever_test` | `1581246903fa9b494237e61030773979e9b7c65e` |
| App Android + server app (monorepo) | `d:\Study\innostar\app_demo_backend` | `7ffa42668f8eb1531ef81f60038058809fb7a455` |

Viết tắt đường dẫn dùng trong bảng:

```
result_speech.py  = handlers/result_speech.py                (server kính)
ActionRegistry.kt = apps/android/app/src/main/java/com/youreyes/app/actions/ActionRegistry.kt
delivery.py       = apps/backend/src/app/workers/delivery.py
timeout.py        = apps/backend/src/app/workers/timeout.py
errors.py         = apps/backend/src/app/errors.py
```

---

## 0. Cách đo — và vì sao phân biệt "phát thật" với "có tên trong tài liệu"

Chỉ tính là **phát thật** khi có một chỗ trong code chạy dựng ra mã đó:

- App Android: một lời gọi `ReportErrorPayload("<MÃ>", ...)`. Kiểu dữ liệu ở
  `apps/android/.../model/Models.kt:51-57`; mã đi lên mạng ở
  `apps/android/.../dispatcher/CommandDispatcher.kt:74` và
  `apps/android/.../network/DeviceApiClient.kt:72`.
- Server app: một dict `{"code": ...}` được ghi vào cột `error` của operation.

**Không** tính là phát thật:

- mã chỉ nằm trong tài liệu (`endpoint.md`, `project_context.md`,
  `contracts/contract-matrix.md`, `docs/glasses-server-client-api.md`);
- mã chỉ nằm trong test (`apps/android/app/src/test/.../ActionRegistryTest.kt`
  dòng 60, 90, 98, 106, 176 — nhưng cả 5 mã đó đều có nguồn phát thật ở bản
  chính nên không đổi kết luận);
- mã là hằng số không ai dùng.

Đây chính là chỗ bảng này có giá trị: `INVALID_DESTINATION` xuất hiện **6 lần**
trong tài liệu repo app (`endpoint.md:103`, `:213`; `project_context.md:455`,
`:711`; `docs/glasses-server-client-api.md:161`, `:265`) nhưng **không có một
dòng code nào** phát nó. Đọc tài liệu thì tưởng có nguồn; grep code thì không.

### Hai kênh khác nhau — không phải mã nào cũng tới được `speak_result()`

`speak_result()` (`result_speech.py:164-185`) chỉ tra `_ERROR_SPEECH` cho
`data["error"]["code"]` của `GET /api/v1/requests/{id}`. Có hai lối thoát trước
đó, và chúng làm hai mã "có thật" trở nên vô dụng:

- `result_speech.py:178-179` — `request_state == "timed_out"` trả
  `_TIMEOUT_MESSAGE` **trước khi** đọc `error.code`. `REPORT_TIMEOUT`
  (`timeout.py:30`) luôn đi kèm state này → **không bao giờ** vào bảng.
- `handlers/action_flow.py:245-251` — lỗi HTTP của chính lời gọi `POST` bị bắt
  thành `VisionCareAPIError` và nói câu `failure` của handler.
  `GLASSES_DEVICE_NOT_LINKED` là HTTP 404 (`errors.py:157-161`,
  `apps/backend/src/app/services/glasses.py:44`), không nằm trong `error.code`
  → dòng ở `result_speech.py:14` **không bao giờ chạy**.

---

## 1. Bảng đối chiếu — 31 dòng, mỗi dòng có quyết định

Cột "Loại": `retryable` = hỏi lại / thử lại có nghĩa; `terminal` = người dùng
phải làm gì đó ở điện thoại, hỏi lại chỉ tốn thời gian.

### 1.1 Khớp cả hai chiều — 12 mã

| Mã | App phát? (file:line) | Server có câu? (file:line) | Loại | Quyết định |
|---|---|---|---|---|
| `CONTACT_NOT_FOUND` | CO — `ActionRegistry.kt:484`, `:498` | CO — `result_speech.py:16` | retryable — reask `contact_name` | **(giữ)** — nguồn thật, là ca chính của D4/T06 |
| `MULTIPLE_CONTACTS_FOUND` | CO — `ActionRegistry.kt:502` | CO — `result_speech.py:17` | retryable — `select` | **(giữ)** tạm; xét lại **(b)** sau khi T08/P1 có `contact_list` |
| `CONTACT_PERMISSION_DENIED` | CO — `ActionRegistry.kt:491` | CO — `result_speech.py:18` | terminal | **(giữ)** |
| `CALL_PERMISSION_DENIED` | CO — `ActionRegistry.kt:416`, `:515` | CO — `result_speech.py:19` | terminal | **(giữ)** |
| `EMERGENCY_CONTACT_NOT_CONFIGURED` | CO — `ActionRegistry.kt:395`, `:406` | CO — `result_speech.py:21` | terminal | **(giữ)** |
| `SONG_NOT_FOUND` | CO — `ActionRegistry.kt:986` | CO — `result_speech.py:23` | retryable — reask `song_title` | **(giữ)** — **trả lời câu hỏi 2 mục 6 của T20: CÓ nguồn thật** |
| `PLAYBACK_STOP_FAILED` | CO — `ActionRegistry.kt:1209`, `:1214`, `:1233` | CO — `result_speech.py:24` | retryable — thử lại | **(giữ)** |
| `SUBSCRIPTION_INACTIVE` | CO — `ActionRegistry.kt:1158` | CO — `result_speech.py:31-34` | terminal | **(giữ)** — câu ở server đã sửa đúng nguyên nhân (gói miễn phí) |
| `CURRENT_LOCATION_UNAVAILABLE` | CO — `ActionRegistry.kt:551`, `:564` | CO — `result_speech.py:35` | retryable — thử lại | **(giữ)** |
| `LOCATION_PERMISSION_DENIED` | CO — `ActionRegistry.kt:558` | CO — `result_speech.py:36` | terminal | **(giữ)** |
| `NO_RIDE_AVAILABLE` | CO nhưng **SAI NGỮ NGHĨA** — `ActionRegistry.kt:1402` | CO — `result_speech.py:44` | terminal | **(giữ) + việc riêng phía app** — xem mục 2.1 |
| `DELIVERY_FAILED` | CO — **server app**: `delivery.py:115-124` (đặt `request_state='failed'`, xác nhận ở `repositories/operation.py:384-391`) | CO — `result_speech.py:15` | terminal | **(giữ)** |

### 1.2 Mã MỒ CÔI — server có câu, không ai phát: **10 mã**

| Mã | App phát? (file:line) | Server có câu? (file:line) | Loại | Quyết định |
|---|---|---|---|---|
| `INVALID_DESTINATION` | KHONG — chỉ có trong tài liệu: `endpoint.md:103`, `:213`, `project_context.md:455`, `:711` | CO — `result_speech.py:39` | retryable — reask `destination` (nếu có nguồn) | **CHƯA QUYẾT — chờ người dùng chốt.** Xem mục 3. Không tự chọn (a) hay (b) |
| `NAVIGATION_NOT_FOUND` | KHONG — `NavigationStopHandler` (`ActionRegistry.kt:1316-1330`) luôn `Success` với `navigation_id` bịa `"nav-unknown"` | CO — `result_speech.py:40` | — | **(b) xoá câu** — server kính đã tự biết qua `_ACTIVE`, app không có session Maps để tra |
| `NAVIGATION_ALREADY_STOPPED` | KHONG — cùng lý do trên | CO — `result_speech.py:41` | — | **(b) xoá câu** |
| `QUOTE_NOT_FOUND` | KHONG — `quote_id` do app tự sinh tại chỗ (`ActionRegistry.kt:1391`), không lưu ở đâu để mà "không tìm thấy" | CO — `result_speech.py:42` | — | **(b) xoá câu** |
| `QUOTE_EXPIRED` | KHONG — `expires_at` chỉ là chuỗi trả về (`ActionRegistry.kt:1395`), không ai kiểm | CO — `result_speech.py:43` | — | **(b) xoá câu** |
| `NO_ACTIVE_PLAYBACK` | KHONG — **cố ý**: `ActionRegistry.kt:1221-1223` coi "đang im" là `Success(playback_state=stopped)`, có comment giải thích | CO — `result_speech.py:22` | — | **(b) xoá câu** — app đã quyết không báo lỗi ở ca này |
| `MUSIC_ACCOUNT_NOT_CONNECTED` | KHONG — ca này app trả `SUBSCRIPTION_INACTIVE` (`ActionRegistry.kt:1158`) | CO — `result_speech.py:25` | — | **(b) xoá câu** — trùng vai với `SUBSCRIPTION_INACTIVE` |
| `SMS_PERMISSION_DENIED` | KHONG — **cố ý**: `ActionRegistry.kt:425-443` thiếu quyền SMS thì `smsResult.complete(false)`, vẫn `Success`, chỉ báo qua `sms_sent=false` | CO — `result_speech.py:20` | — | **(b) xoá câu** — `_success_speech` đã nói "chưa gửi được tin nhắn vị trí" (`result_speech.py:123-125`); giữ câu lỗi là giữ một nhánh chết |
| `RIDE_ACCOUNT_NOT_CONNECTED` | KHONG — app mở deeplink Grab, không đăng nhập OAuth (`ActionRegistry.kt:1340-1367`) | CO — `result_speech.py:45` | terminal | **(giữ — ngoại lệ có lý do ghi rõ)** — CONTRACTS mục 5.2 và T11 chốt: không dùng cho Grab/Farefeed, **giữ cho provider tương lai**. Đây là ngoại lệ DoD cho phép |
| `GLASSES_DEVICE_NOT_LINKED` | **CÓ phát nhưng SAI KÊNH** — `errors.py:157-161` là HTTP 404 của chính `POST`, không vào `error.code` | CO — `result_speech.py:14` | terminal | **(b) xoá khỏi `_ERROR_SPEECH`** + việc riêng: bắt 404 ở `action_flow.py:245` và nói đúng câu này. Xem mục 2.2 |

### 1.3 Mã CÂM — app phát, server không có câu riêng: **8 mã**

Cột "rơi vào đâu" là kết quả thật của `result_speech.py:185`.

| Mã | App phát? (file:line) | Server có câu? | Rơi vào đâu hôm nay | Loại | Quyết định |
|---|---|---|---|---|---|
| `PLAYBACK_FAILED` | CO — `ActionRegistry.kt:979`, `:997`, `:1002`, `:1158` | KHONG | `_GENERIC_FAILURE["music_play"]` (`:52-55`) | terminal | **(a) thêm câu** |
| `CALL_FAILED` | CO — `ActionRegistry.kt:385`, `:460`, `:487`, `:521` | KHONG | `_GENERIC_FAILURE["contact_call"]` (`:50`) / `["emergency_call"]` (`:51`) | terminal | **(a) thêm câu** — ưu tiên cao nhất: `:460` là ca **gọi khẩn cấp không quay số được**, hiện nghe câu chung |
| `INVALID_VOLUME` | CO — `ActionRegistry.kt:376` | KHONG | `_GENERIC_FAILURE["music_volume"]` (`:57`) | retryable — reask `volume_direction` | **(a) thêm câu** |
| `NAVIGATION_START_FAILED` | CO — `ActionRegistry.kt:1304` | KHONG | `_GENERIC_FAILURE["navigation_start"]` (`:58`) | terminal | **(a) thêm câu** |
| `NAVIGATION_STOP_FAILED` | CO — `ActionRegistry.kt:1326` | KHONG | `_GENERIC_FAILURE["navigation_stop"]` (`:59`) | retryable | **(a) thêm câu** — **task file T20 KHÔNG liệt kê mã này**, xem mục 2.3 |
| `RIDE_CONFIRM_FAILED` | CO — `ActionRegistry.kt:1434` | KHONG | `_GENERIC_FAILURE["ride_confirm"]` (`:61`) — **nhưng nhánh này chết**, xem mục 2.4 | terminal | **(a) thêm câu** — chỉ khi mở lại đường `ride_confirm`; nếu không thì **(b)** cả mã lẫn dòng `_GENERIC_FAILURE` |
| `INVALID_PARAMS` | CO — `ActionRegistry.kt:1255`, `:1458`, `:1480`, `:1494`, `:1514` | KHONG | `_UNSPECIFIED_FAILURE` (`:86`) — **không** operation nào trong 5 chỗ đó có dòng `_GENERIC_FAILURE` | terminal | **(a) thêm câu** — hoặc để `_DEFAULT_POLICY` mục 4 lo, vì 5 operation này (`media_play`, `quotes_speak`, `camera_capture`, `display_show`, `system_settings`) server kính **không gọi** |
| `UNSUPPORTED_ACTION` | CO — `ActionRegistry.kt:1523` | KHONG | `_GENERIC_FAILURE[<operation>]` hoặc `_UNSPECIFIED_FAILURE` | terminal | **(a) thêm câu** — mã này nổ khi hai repo lệch phiên bản, đúng lúc cần một câu nói rõ nhất |

### 1.4 Mã có thật nhưng không tới được bảng — 1 mã

| Mã | Phát ở đâu | Server có câu? | Loại | Quyết định |
|---|---|---|---|---|
| `REPORT_TIMEOUT` | CO — server app `timeout.py:27-31` | KHONG (và **không cần**) | terminal | **(b) không thêm vào `_ERROR_SPEECH`** — `result_speech.py:178-179` đã chặn trước bằng `_TIMEOUT_MESSAGE`. Ghi vào bảng để test 4.1 không báo nhầm là "mã app phát mà server không có câu" |

---

## 2. Những chỗ đo được khác với mô tả trong task file

### 2.1 `NO_RIDE_AVAILABLE` đang bị dùng sai ngữ nghĩa — sai nghiêm trọng nhất tìm được

`ActionRegistry.kt:1400-1403`: nhánh `getOrElse` của `RideQuoteHandler` bắt **lỗi
parse JSON tham số** và báo về bằng mã `NO_RIDE_AVAILABLE` với message
`"Invalid ride_quote params: ..."`.

Server kính đọc mã đó và nói `"Hiện không có xe nào gần đây."`
(`result_speech.py:44`).

Người mù nghe một câu **hoàn toàn sai sự thật**: máy đang hỏng tham số, họ được
bảo là khu vực hết xe, nên họ sẽ đợi hoặc đi bộ thay vì thử lại. Đây không phải
lỗi ở server kính — câu nói đúng với mã. Phải sửa ở app: dùng `INVALID_PARAMS`
hoặc một mã `RIDE_QUOTE_FAILED` cho nhánh parse.

Cùng dạng, nhẹ hơn (mã ít gây hiểu nhầm hơn):
`NAVIGATION_START_FAILED` (`:1304`), `NAVIGATION_STOP_FAILED` (`:1326`),
`RIDE_CONFIRM_FAILED` (`:1434`) cũng là mã của nhánh parse tham số.

### 2.2 `GLASSES_DEVICE_NOT_LINKED` — mã thật, kênh sai

Task file không nhắc mã này. Nó **có** nguồn phát (`errors.py:161`) nên trông
như một dòng hợp lệ, nhưng đi qua HTTP status chứ không qua `error.code`, nên
dòng `result_speech.py:14` chưa từng chạy một lần nào. Kết quả: kính chưa ghép
nối thì người dùng nghe câu `failure` chung của handler
("Không thể mở ứng dụng đặt xe...", v.v.) thay vì "Kính chưa được ghép nối".

Sửa đúng chỗ là ở `action_flow.py:245-251`, không phải ở `_ERROR_SPEECH`.

### 2.3 Số đếm lệch với task file

| | Task file (T20 mục 1) | Đo được 2026-08-22 | Lệch |
|---|---|---|---|
| Mã mồ côi | 9 | **10** | +1: `GLASSES_DEVICE_NOT_LINKED` (mục 2.2) |
| Mã câm | 7 | **8** | +1: `NAVIGATION_STOP_FAILED` (`ActionRegistry.kt:1326`, tài liệu `endpoint.md:232`) |

Chín mã mồ côi task file liệt kê thì **đúng cả chín**. Bảy mã câm task file liệt
kê cũng **đúng cả bảy**. Chỉ là mỗi chiều thiếu một mã.

Số dòng trong task file cũng đã trôi: task file ghi `_ERROR_SPEECH` ở
`result_speech.py:13-45` — thực tế là `:13-46` (dấu đóng ngoặc ở dòng 46), và
`_GENERIC_FAILURE` ghi `:50-60` — thực tế `:49-62`.

Tổng: `_ERROR_SPEECH` có **22 mã**, phía điện thoại phát **20 mã** (19 từ app
Android + `DELIVERY_FAILED` từ server app), giao nhau **12 mã**.

### 2.4 `ride_confirm`: có mã lỗi, có câu chung, nhưng không có ai gọi

`_GENERIC_FAILURE["ride_confirm"]` (`result_speech.py:61`) và `_success_speech`
nhánh `ride_confirm` (`:156-159`) là code chết ở thời điểm này:
`handlers/ride.py` chỉ gọi `run_action("ride_quote", ...)` (`ride.py:45-58`), và
`handle_confirm` cũng đi qua `_open_ride_app()` → `ride_quote`. Không chỗ nào
trong repo gọi `api/v1/service/ride/confirm`.

Nên `RIDE_CONFIRM_FAILED` là mã app phát mà **server kính không bao giờ nhận**.
Không xoá vội — T11 còn đang chờ Farefeed — nhưng phải ghi rõ để không ai viết
test giả định nó chạy.

### 2.5 `MULTIPLE_CONTACTS_FOUND` — task file nói "gần như không bao giờ nổ", đúng

`ActionRegistry.kt:496-508`: chỉ nổ khi `ContactLookup.findByName` trả về nhiều
hơn một kết quả, mà so khớp là **bằng nhau tuyệt đối, không dấu, không mờ**
(CONTRACTS mục 5.1 đã ghi, `ActionRegistry.kt:110`). Hai contact phải trùng tên
hiển thị y hệt.

---

## 3. Câu hỏi mở số 7 của CONTRACTS — "App có kiểm được địa điểm không?"

**Trả lời được một nửa từ code. Nửa còn lại là quyết định sản phẩm, không tự chốt.**

### Hôm nay: KHÔNG kiểm, có bằng chứng

`NavigationStartHandler` (`ActionRegistry.kt:1281-1307`):

```kotlin
val lat = destObj?.optDouble("lat", 10.7769) ?: 10.7769   // :1286
val lng = destObj?.optDouble("lng", 106.7009) ?: 106.7009 // :1287
val address = destObj?.optString("address", "") ?: ""     // :1288
```

Không có lat/lng thì **mặc định về một toạ độ cứng ở TP.HCM**, rồi
`openGoogleMapsNavigation` (`:1261-1279`) ném thẳng chuỗi địa chỉ vào
`google.navigation:q=${Uri.encode(address)}&mode=w` (`:1263`). Không hỏi ai địa
điểm có tồn tại không. Nhánh lỗi duy nhất (`:1302-1305`) là lỗi parse JSON.

Server kính lại chỉ gửi `{"destination": {"address": destination}}`
(`handlers/navigation.py:41-43`) — **không có lat/lng** — nên đường mặc định
toạ độ cứng ở trên là đường luôn chạy. `RideQuoteHandler` y hệt
(`ActionRegistry.kt:1374-1377`, mặc định `10.7721 / 106.6578`).

Kết luận chắc chắn: **`INVALID_DESTINATION` hôm nay không có nguồn phát nào.**

### Về mặt kỹ thuật: LÀM ĐƯỢC, không cần thêm quyền hay thư viện

- `android.location.Geocoder` đã được import sẵn (`ActionRegistry.kt:12`) và
  đang dùng thật cho **reverse** geocode (`:309-331`), có cả `Geocoder.isPresent()`
  (`:310`), timeout có chặn (`GEOCODE_TIMEOUT_MS`, `:279`) và locale `vi-VN` (`:313`).
- Chiều thuận `Geocoder.getFromLocationName(...)` **chưa được gọi ở đâu cả** —
  grep toàn bộ `*.kt` không có kết quả nào.
- `android.permission.INTERNET` đã khai báo (`AndroidManifest.xml:36`),
  `ACCESS_FINE_LOCATION` (`:24`) và `ACCESS_COARSE_LOCATION` (`:25`) cũng có.

Nghĩa là: thêm `INVALID_DESTINATION` cho `navigation_start` là **một hàm gọi
thêm trong cùng một file, không phụ thuộc gì mới**.

### Cái KHÔNG quyết được thay người dùng

1. Có bỏ công thêm forward geocode vào app không, hay để server kính / server
   app 8001 làm (dính luôn câu hỏi mở số 2 của CONTRACTS: *ai geocode
   address → lat/lng*)?
2. `Geocoder` trả kết quả **gần đúng** rất dễ dãi — "Bến Thành" ra một địa chỉ,
   "abcxyz" cũng có thể ra một địa chỉ nào đó. Ngưỡng nào coi là "không tìm
   thấy" thì cần đo trên tên địa điểm thật, **chưa đo**.

Theo AGENT_RULES mục A6, hai câu này đi vào phần "Cần người dùng chốt" của báo
cáo. Dòng `INVALID_DESTINATION` trong bảng mục 1.2 giữ nguyên trạng thái
**chưa quyết**, không đánh (a) cũng không đánh (b).

---

## 4. Đề xuất `_DEFAULT_POLICY` — nguyên tắc 21.7 (CHỈ ĐỀ XUẤT, KHÔNG THI CÔNG)

Wave này **không** sửa `handlers/result_speech.py`. Phần dưới là bản thiết kế
cho wave sau.

### 4.1 Hôm nay có mã nào rơi vào im lặng không? — KHÔNG, nhưng lý do mong manh

`result_speech.py:185` đã có hai tầng đỡ: `_GENERIC_FAILURE.get(operation)` rồi
`_UNSPECIFIED_FAILURE`. Về mặt cấu trúc, mọi mã lạ **đều ra một câu**. Nguyên
tắc 21.7 hiện **không bị vi phạm về mặt im lặng**.

Cái hỏng không phải im lặng mà là **im lặng về nội dung**: câu ra không nói
người dùng phải làm gì (`_UNSPECIFIED_FAILURE` = "Chưa thực hiện được, vui lòng
thử lại." — thử lại bao nhiêu lần cũng thế nếu là lỗi quyền), và trong ca mục
2.1 thì còn nói sai hẳn. Thêm nữa, hai tầng đỡ này **phụ thuộc vào `operation`**:
mã lạ đi kèm một operation lạ thì rơi thẳng xuống `_UNSPECIFIED_FAILURE`.

### 4.2 Bản đề xuất

```python
@dataclass(frozen=True)
class ErrorPolicy:
    speech: str
    retryable: bool            # có đặt pending hỏi lại không
    reask: tuple | None        # (slot, intent) nếu retryable

_DEFAULT_POLICY = ErrorPolicy(
    speech=(
        "Điện thoại báo chưa làm được việc này và không nói rõ lý do. "
        "Vui lòng kiểm tra thông báo trên điện thoại."
    ),
    retryable=False,
    reask=None,
)
```

Ba điều kiện bản thân câu nói phải đạt, và vì sao:

1. **Nói rõ là KHÔNG làm được.** Người mù không có màn hình để đối chiếu; câu
   mơ hồ bị hiểu là "đang làm".
2. **Nói rõ là không biết lý do.** Thà thừa nhận còn hơn đoán bừa — ca mục 2.1
   cho thấy đoán sai còn tệ hơn không đoán.
3. **Chỉ một hành động khả thi duy nhất**: xem thông báo trên điện thoại. Không
   khuyên "thử lại" ở nhánh mặc định, vì phần lớn mã lạ hôm nay là mã terminal
   (quyền, cấu hình, tham số) — khuyên thử lại là đẩy người dùng vào vòng lặp.

`retryable=False` là mặc định **cố ý an toàn**: chưa biết mã nghĩa là gì thì
không được tự động đặt pending và hỏi lại, vì pending sai sẽ nuốt câu nói kế
tiếp của người dùng (CONTRACTS quyết định #9: một pending / device).

### 4.3 Thứ tự tra sau khi có `_DEFAULT_POLICY`

```
1. request_state == "timed_out"   -> _TIMEOUT_MESSAGE   (giữ nguyên, chặn REPORT_TIMEOUT)
2. _ERROR_SPEECH[code]            -> câu riêng của mã
3. _GENERIC_FAILURE[operation]    -> câu riêng của operation
4. _DEFAULT_POLICY.speech         -> thay chỗ _UNSPECIFIED_FAILURE
```

Bước 4 **thay** `_UNSPECIFIED_FAILURE` chứ không thêm tầng thứ năm — thêm tầng
chỉ làm cây quyết định dài ra mà không đóng thêm lỗ nào.

### 4.4 Ràng buộc thi công cho wave sau

- `_DEFAULT_POLICY.speech` **phải** vào `STATIC_SPEECH` (`result_speech.py:102-116`)
  để `pipeline/phrases.py` dựng sẵn audio. Câu mặc định mà phải chờ TTS thì đúng
  lúc hệ thống đang hỏng lại là lúc nói chậm nhất.
- Ba mã ở mục 1.3 có tính retryable thật (`INVALID_VOLUME` → `volume_direction`,
  `NAVIGATION_STOP_FAILED`, `PLAYBACK_STOP_FAILED`) chỉ được đặt `reask` khi
  T06/D4 đã xong. Trước đó để `retryable=False`.
- `emergency_call` **không** đi qua bất kỳ bước hỏi lại nào (CONTRACTS mục 0.3).
  `CALL_FAILED` ở `ActionRegistry.kt:460` là nhánh khẩn cấp — dù phân loại thế
  nào cũng **cấm** đặt pending cho nó.

---

## 5. Việc còn lại cho các wave sau (không làm ở wave này)

| Việc | File | Thuộc về |
|---|---|---|
| Thi công `ErrorPolicy` + `_DEFAULT_POLICY` | `handlers/result_speech.py` | wave sau |
| Viết `tests/test_error_contract.py` (5 test ở T20 mục 4.1) | `tests/` | wave sau |
| Bắt HTTP 404 `GLASSES_DEVICE_NOT_LINKED` | `handlers/action_flow.py:245-251` | wave sau |
| Sửa mã của nhánh parse tham số (mục 2.1) | repo app — **read-only với task này** | phía app |
| `_ERROR_REASK` chỉ chứa mã có nguồn thật | T06/D4 | T06 |
