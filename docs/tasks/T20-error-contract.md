# T20 — Hợp đồng mã lỗi: đối chiếu app ↔ server kính

| | |
|---|---|
| **Mã spec** | P7 · 21.7 · 26.5 |
| **SPEC gốc** | 26.5, 21.7, mục 14 (D4) |
| **Repo đụng** | Server kính · **App Android** |
| **Trạng thái** | READY — **rẻ, làm sớm** |
| **Chặn bởi** | — |
| **Chặn** | 🔴 **T06/D4** · T10 · T12 |

> **Task này chặn D4 của T06.** Không có nguồn lỗi thì không test được, và bảng
> ánh xạ sẽ mô tả một hệ thống không tồn tại.
>
> Rẻ: phần lớn là **đọc và đối chiếu**, không phải viết code.

---

## 1. Hiện trạng

### Chín mã server kính **có câu nói** mà app **không đời nào gửi**

`handlers/result_speech.py:13-45` `_ERROR_SPEECH`:

```
INVALID_DESTINATION · NAVIGATION_NOT_FOUND · NAVIGATION_ALREADY_STOPPED
QUOTE_NOT_FOUND · QUOTE_EXPIRED · MUSIC_ACCOUNT_NOT_CONNECTED
NO_ACTIVE_PLAYBACK · SMS_PERMISSION_DENIED · RIDE_ACCOUNT_NOT_CONNECTED
```

Ví dụ cụ thể (26.5): `NavigationStartHandler` **luôn trả `Success`** — ném chuỗi
địa chỉ vào `google.navigation:q=` rồi để Maps tự hiểu, **không kiểm địa điểm có
tồn tại không**.

### Bảy mã app **có phát** mà server kính **không có câu**

```
PLAYBACK_FAILED · INVALID_VOLUME · INVALID_PARAMS · CALL_FAILED
UNSUPPORTED_ACTION · NAVIGATION_START_FAILED · RIDE_CONFIRM_FAILED
```

Rơi vào `_GENERIC_FAILURE` (`result_speech.py:50-60`) hoặc `_UNSPECIFIED_FAILURE`
— **đúng chỗ 21.7 đòi phải có fallback**, nhưng chưa ai kiểm là fallback đó có
nói ra câu hữu ích không.

### Một mã **gần như không bao giờ nổ**

`MULTIPLE_CONTACTS_FOUND` chỉ nổ khi hai contact **trùng tên hiển thị y hệt**
(26.1) — ca hiếm. D6 của T08 gần như không chạy.

### 21.7 — thiếu phân loại

Bảng ánh xạ hiện không có:

```
retryable | terminal
default fallback khi không khớp dòng nào
```

Không có default → mã lỗi lạ rơi vào **im lặng**, người dùng không biết chuyện gì.

---

## 2. Việc phải làm

### Bước 1 — dựng bảng đối chiếu đầy đủ (đọc code, không viết code)

Liệt kê **mọi** mã lỗi app phát ra (`ActionRegistry.kt`), đối chiếu với
`_ERROR_SPEECH` (`result_speech.py:13-45`) và `_GENERIC_FAILURE` (`:50-60`).

Ra file `docs/tasks/measurements/P7-error-matrix.md`:

| Mã | App phát? | Server có câu? | Loại | Quyết định |
|---|---|---|---|---|
| `CONTACT_NOT_FOUND` | ✅ | ✅ | retryable | đặt pending (D4) |
| `INVALID_DESTINATION` | ❌ | ✅ | — | **app bổ sung** hoặc **server xoá câu** |
| `PLAYBACK_FAILED` | ✅ | ❌ | terminal | **server thêm câu** |
| … | | | | |

### Bước 2 — quyết định từng dòng

Chỉ có **hai** lựa chọn cho mỗi mã. Không có lựa chọn thứ ba là "để đó":

```
(a) app bổ sung đường phát       → mã thật sự cần thì làm
(b) server kính xoá câu chết      → mã không cần thì đừng để câu mồ côi
```

**Không để bảng ánh xạ mô tả một hệ thống không tồn tại.**

Gợi ý theo giá trị:

| Mã | Đề xuất | Vì sao |
|---|---|---|
| `INVALID_DESTINATION` | (a) — app kiểm địa điểm | mở khoá D4 cho `nav_start` (T10); người mù đi bộ theo lộ trình sai là ca nặng |
| `MULTIPLE_CONTACTS_FOUND` | (b) sau khi có T08/P1 | có `contact_list` thì server tự khớp, không cần host báo trùng |
| `NAVIGATION_ALREADY_STOPPED` | (b) | server đã tự biết qua `_ACTIVE` |
| `RIDE_ACCOUNT_NOT_CONNECTED` | giữ | T11 ghi rõ: không dùng cho Farefeed, **giữ cho provider tương lai** |
| `PLAYBACK_FAILED`, `CALL_FAILED`, … | (a) — server thêm câu | app đã phát, người dùng đang nghe câu chung chung |

### Bước 3 — 21.7: phân loại + fallback

```python
@dataclass(frozen=True)
class ErrorPolicy:
    speech: str
    retryable: bool          # có đặt pending hỏi lại không
    reask: tuple | None      # (slot, intent) nếu retryable

_DEFAULT_POLICY = ErrorPolicy(
    speech=<câu chung, NÓI RÕ là chưa làm được và gợi ý xem thông báo>,
    retryable=False, reask=None,
)
```

**Mọi** mã không khớp dòng nào rơi vào `_DEFAULT_POLICY` — **không mã nào rơi vào
im lặng**.

### Bước 4 — mở khoá D4 (T06)

Sau khi bảng chốt, `_ERROR_REASK` của T06 chỉ chứa **mã có nguồn phát thật**. Mã
nào không có thì **xoá khỏi bảng**, và xoá luôn `xfail` tương ứng ở T06/T10/T12.

---

## 3. Hợp đồng đổi

🔴 **Đây LÀ hợp đồng.** Kết quả task này là mục *Mã lỗi* của `CONTRACTS.md`:

```
Danh sách mã lỗi CHÍNH THỨC cho mỗi operation
  - mã nào app phát
  - mã nào server kính có câu
  - retryable / terminal
  - fallback mặc định
```

Mọi mã mới ở **hai phía** phải cập nhật file này trước khi code.

---

## 4. Test

### 4.1 Đối chiếu tự động — `tests/test_error_contract.py` (mới)

Đây là loại test **giữ hai repo khỏi trôi khỏi nhau**:

```
test_no_orphan_speech                        # 🔴 ca chính
  mọi mã trong _ERROR_SPEECH PHẢI có trong danh sách app phát
  (danh sách app đọc từ CONTRACTS.md hoặc fixture chép cứng)

test_no_unhandled_app_code
  mọi mã app phát PHẢI có câu riêng HOẶC rơi vào fallback CÓ Ý NGHĨA

test_every_code_has_policy
  mỗi mã có retryable + reask xác định

test_default_policy_exists                    # 21.7
test_unknown_code_never_silent                # 🔴
  mã bịa "ZZZ_UNKNOWN" → VẪN ra một câu nói được
```

### 4.2 D4 sau khi mở khoá (chung với T06)

```
test_error_reask_only_for_real_codes
  _ERROR_REASK KHÔNG chứa mã không có nguồn phát
```

### 4.3 Fixture — nguồn sự thật

`tests/fixtures/app_error_codes.txt` **(mới)** — danh sách mã app phát, chép từ
`ActionRegistry.kt`, **kèm ngày và commit hash của repo app**.

Đây là chỗ dễ trôi nhất. Ghi ngày để lần sau biết fixture đã cũ chưa.

### 4.4 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| Ép app trả một mã lạ | nghe được câu **có ý nghĩa**, không im lặng |
| Tắt quyền danh bạ rồi gọi | nghe đúng câu về quyền, không phải câu chung |
| Gọi tên không có trong danh bạ | nghe câu **và** được hỏi lại (sau D4) |

---

## 5. DoD

```bash
pytest tests/test_error_contract.py -q
```

- [ ] `measurements/P7-error-matrix.md` liệt kê **đủ hai chiều**, mỗi dòng có quyết định (a)/(b)
- [ ] Không còn mã nào trong `_ERROR_SPEECH` mà app không phát — **hoặc** đã ghi
      rõ lý do giữ lại (như `RIDE_ACCOUNT_NOT_CONNECTED`)
- [ ] Mọi mã app phát đều có câu riêng hoặc fallback có ý nghĩa
- [ ] `_DEFAULT_POLICY` tồn tại, **không mã nào rơi vào im lặng**
- [ ] `retryable`/`terminal` xác định cho mọi mã
- [ ] `tests/fixtures/app_error_codes.txt` có **ngày + commit hash** repo app
- [ ] T06/D4 đã bỏ `xfail` cho mã có nguồn thật, **xoá dòng** cho mã không có
- [ ] `CONTRACTS.md` có mục *Mã lỗi* đầy đủ

---

## 6. Câu hỏi phải chốt

1. **App có kiểm được địa điểm không** (để `INVALID_DESTINATION` có nguồn)?
   Không thì T10/D4 chết theo, và server kính phải xoá câu ở
   `result_speech.py:41`.
2. **`SONG_NOT_FOUND` có nguồn phát thật không?** T12/D4 đang giả định là có.
   Phải xác nhận.
3. **Ai giữ `CONTRACTS.md` khỏi trôi?** Đề xuất: fixture + test 4.1 chạy trong
   CI. Nhưng fixture chép tay vẫn cũ được — cần quy ước cập nhật khi app đổi.
