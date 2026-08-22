# T07 — Vị trí: chống câm, chống chết thread

| | |
|---|---|
| **Mã spec** | C1 C2 C3 C4 C5 · P8 P9 |
| **SPEC gốc** | mục 8, 26.6 |
| **Repo đụng** | Server kính · **App Android** |
| **Trạng thái** | READY |
| **Chặn bởi** | — |
| **Chặn** | **T05/A3** · **T11/R6** · T13 |

> Nhóm ưu tiên **C** của spec: *"Vị trí đang hỏng 100%, và A3/A6 phụ thuộc nó."*
> Bằng chứng: `logs/glasses8000.err.log`, **42/42 nhịp hỏng, 0 lần thành công**
> suốt phiên 01:11 → 15:00.

---

## 1. Hiện trạng — ⚠️ code đã đi TRƯỚC spec, kiểm lại từng mục

Spec mục 8 viết trước khi `handlers/chat.py` được sửa. **Ba trong bảy chỗ đã
xong.** Đọc bảng này trước khi code, đừng sửa lại thứ đã đúng.

| Mã | Spec nói hỏng | Thực tế hôm nay | Việc còn lại |
|---|---|---|---|
| **C2** | `refresh_location_once` không có try/except | ✅ **đã có** — `chat.py:150-155` bọc `get_device_location()` | ❌ nhưng `loop()` (`:206-209`) **vẫn không có** try/except, và `result['lat']` (`:176`) **vẫn ngoài try** |
| **C5** | `to_vn_time_str` ném `NameError` | 🔴 **vẫn hỏng** — `chat.py:6` import chỉ có `UTC, datetime`, hàm `:111-121` dùng `timezone`/`timedelta` | phải sửa |
| **P9 / 26.6** | không kiểm tuổi toạ độ | ✅ **đã có** — `_fix_age_seconds()` (`:124`) + `CHAT_LOCATION_MAX_FIX_AGE_SECONDS=600` (`config.py:237`) | chỉ còn: nói ra cho người dùng |
| **C1** | cache rỗng → `""` | 🔴 **vẫn vậy** — `_location_text()` (`:257-267`) `return ""` | phải sửa |
| **C3** | nhịp 240 s, không backoff | 🔴 **vẫn vậy** — `loop()` `time.sleep(config.CHAT_LOCATION_REFRESH_SECONDS)` cố định | phải sửa |
| **C4** | log `INFO` mãi, không escalation | 🟡 **một nửa** — ca "fix quá cũ" đã `logger.warning` (`:170`), ca "không lấy được" vẫn `INFO` (`:161`) | đếm hỏng liên tiếp |

### Xác minh C5 (đã chạy, không phải suy đoán)

```
$ python -c "import handlers.chat as c; print('timezone' in dir(c)); print(repr(c.to_vn_time_str('2026-08-21T10:00:00Z')))"
False
'2026-08-21T10:00:00Z'
```

`NameError` bị `except Exception` ở `:119-120` nuốt, hàm trả về nguyên chuỗi
đầu vào. Chưa gây hại vì `vn_time` (`:164`) gán rồi **không dùng ở đâu** — biến
chết.

### Chuỗi nhân quả của lỗi câm

```
host trả CURRENT_LOCATION_UNAVAILABLE
→ get_device_location() trả None
→ refresh_location_once() "giữ toạ độ cũ" nhưng KHÔNG CÓ toạ độ cũ nào
→ cache vẫn (None, 0.0)
→ _location_text() trả ""
→ prompt HOÀN TOÀN KHÔNG CÓ vị trí
→ nhưng _SEARCH_INSTRUCTION (chat.py:71) VẪN bảo model "tra địa điểm quanh
  người dùng"
→ model bịa quán phở
```

**Lỗi gốc nằm ở app Android**, không ở server. Server đang chạy đúng thiết kế —
nhưng đúng thiết kế mà im lặng thì vẫn là hỏng với người dùng.

---

## 2. Việc phải làm

### 2.1 Server kính

#### C1 — 🔴 quan trọng nhất: cache rỗng phải trả **khối giải thích**, không phải `""`

`handlers/chat.py:257-267`:

```python
_LOCATION_UNAVAILABLE = (
    "CHƯA lấy được vị trí hiện tại của người dùng.\n"
    "TUYỆT ĐỐI không đoán người dùng đang ở đâu, không nêu tên thành phố, "
    "quận, hay địa điểm cụ thể nào như thể biết chỗ họ đứng.\n"
    "Nếu câu hỏi cần vị trí, nói thẳng là chưa xác định được vị trí và gợi ý "
    "người dùng kiểm tra định vị trên điện thoại.\n"
)
```

**Đây là sửa quan trọng nhất của cả task, vì nó cắt đường bịa.** Trả `""` thì
`_SEARCH_INSTRUCTION` vẫn bảo model tra quanh người dùng trong khi prompt không
có người dùng ở đâu — đúng kịch bản mà comment `chat.py:186-190` đã ghi lại
(model tự quy Tân Triều, Đồng Nai thành TP.HCM, lệch ~20 km).

#### P9 — vị trí **cũ** cũng phải nói ra

`_fix_age_seconds` đã có. Hiện fix quá hạn thì **bỏ luôn** (`:167-173` trả
`False`) → rơi về ca cache rỗng. Đúng, nhưng người dùng nghe không phân biệt
được "chưa có vị trí" với "vị trí đã cũ".

Thêm tầng giữa: fix trong khoảng `[TTL, MAX_FIX_AGE]` → vẫn dùng **nhưng** chèn
*"vị trí này đã cũ khoảng N phút"* vào khối prompt.

#### C2 — thread **không được phép chết**

Hai chỗ:

```python
# (1) chat.py:176 — result['lat'] NGOÀI try
where = address or f"toạ độ {result['lat']}, {result['lng']}"
# host trả result thiếu lat/lng → KeyError → thoát refresh_location_once
# → thoát loop() → THREAD CHẾT IM
# và _REFRESHER_STARTED = True (:151) chặn luôn việc gọi lại
# → vị trí chết tới khi restart server

# (2) chat.py:206-209 — loop() không có try/except
def loop():
    while True:
        refresh_location_once()
        time.sleep(...)
```

Sửa: bọc `try/except` **toàn thân** `refresh_location_once`, **và** trong
`loop()`. Dùng `.get()` cho `lat`/`lng`, thiếu thì coi như lấy hỏng.

#### C3 — backoff ngược khi hỏng

```
hỏng → 15 s → 30 s → 60 s → (giữ 60 s)
thành công → về 240 s
```

GPS bật lại lúc t+10 s mà phải chờ 4 phút là mất 230 giây không cần thiết.

#### C4 — escalation

Đếm hỏng liên tiếp. ≥ 3 → `logger.error` thay vì `INFO` mãi. Hiện 42 dòng log
**giống hệt nhau**, không ai nhìn ra là hỏng vĩnh viễn.

#### C5 — sửa biến chết

Chọn một:
- thêm `timezone, timedelta` vào import `chat.py:6` (nếu định dùng `vn_time`), **hoặc**
- xoá hẳn `to_vn_time_str` + `vn_time` (`:164`) — hàm không ai dùng kết quả

Đề xuất **xoá**: `_fix_age_seconds` đã lo phần tuổi toạ độ, `to_vn_time_str` chỉ
để log cho người đọc. Muốn giữ log thì sửa import.

Đừng để nguyên: một hàm luôn ném exception rồi bị nuốt là mìn cho lần sửa sau.

### 2.2 App Android — **lỗi gốc nằm ở đây**

#### P8 — `getCurrentLocation()` thay `getLastKnownLocation()`

`ActionRegistry.kt:335-347` dùng `getLastKnownLocation()` → trả `null` khi máy
chưa có bản cũ nào. Đổi sang `FusedLocationProviderClient.getCurrentLocation()`
để **ép lấy fix mới**.

Kéo theo (26.6): **chưa có `play-services-location`** trong
`app/build.gradle.kts`. Đây là **thêm dependency**, không phải sửa một lời gọi.

Kiểm thêm: quyền `ACCESS_FINE_LOCATION`, battery restriction.

#### P8b — app **từ chối** trả fix cũ

Hiện app trả `captured_at` rồi mặc kệ. Đề xuất: cũ hơn **120 s** thì đi lấy fix
mới thay vì trả bản cũ.

Server kính vẫn giữ `_fix_age_seconds` như tầng phòng thủ thứ hai — hai tầng
không thừa, vì server không kiểm soát được phiên bản app.

### 2.3 Server app · Firmware

**Không đụng.**

---

## 3. Hợp đồng đổi

Không đổi hợp đồng. Ghi vào `CONTRACTS.md`: ngưỡng tuổi toạ độ ở **hai phía**
(app 120 s, server kính `CHAT_LOCATION_MAX_FIX_AGE_SECONDS` 600 s) và lý do có
hai tầng.

---

## 4. Test

### 4.1 Unit — `tests/test_location_degraded.py` (mới)

Không cần host, không cần app. Mock `visioncare_client.get_device_location`.

```
test_empty_cache_returns_warning_block       # 🔴 C1, ca quan trọng nhất
  cache rỗng → _location_text() KHÔNG trả ""
  → chuỗi trả về CÓ chữ "không đoán" / cấm bịa

test_search_instruction_consistent_when_no_location
  cache rỗng → prompt KHÔNG đồng thời chứa "tra quanh người dùng"
  ← đây là kịch bản bịa quán phở

test_stale_fix_says_it_is_stale              # P9
  fix 5 phút tuổi → dùng được NHƯNG khối prompt nói rõ là cũ

test_thread_survives_missing_lat             # 🔴 C2
  host trả {"address": "x"} thiếu lat/lng
  → refresh_location_once trả False, KHÔNG ném
  → gọi lại lần nữa vẫn chạy (thread còn sống)

test_loop_survives_any_exception             # C2
  refresh ném bất kỳ lỗi gì → loop() không thoát

test_backoff_sequence                        # C3
  hỏng ×3 → nhịp 15, 30, 60
  thành công → về 240

test_error_log_after_three_failures          # C4
  hỏng ×3 → logger.error (không phải INFO)

test_to_vn_time_str_or_removed               # C5
  hoặc hàm trả đúng giờ VN, hoặc hàm đã bị xoá
  → KHÔNG được tồn tại ở dạng luôn ném NameError
```

### 4.2 Test cũ phải kiểm

`tests/test_chat.py` — có ca vị trí. `_location_text()` đổi giá trị trả về khi
rỗng → mọi assert `== ""` sẽ đỏ. **Đó là đúng**, sửa assert chứ đừng sửa code
về như cũ.

### 4.3 Thủ công — cần điện thoại thật

| Kịch bản | Đạt khi |
|---|---|
| Tắt định vị trên máy, hỏi "quanh đây có gì" | nghe được câu **nói thẳng chưa có vị trí**, KHÔNG nghe tên quán nào |
| Bật lại định vị | trong vòng ~15-60 s (C3) là có vị trí, không phải 4 phút |
| Chạy server 2 giờ, rút mạng điện thoại giữa chừng | thread vẫn sống, log có `ERROR` sau 3 lần hỏng |
| Đứng yên 10 phút | không bị báo "vị trí đã cũ" nhầm (ngưỡng 600 s hợp lý chưa) |

---

## 5. DoD

```bash
pytest tests/test_location_degraded.py tests/test_chat.py -q
```

- [ ] `_location_text()` **không bao giờ** trả `""` — cache rỗng ra khối cấm bịa
- [ ] `loop()` và toàn thân `refresh_location_once` đều có try/except
- [ ] `result['lat']` đổi sang `.get()`; thiếu → coi như hỏng, không ném
- [ ] Backoff 15/30/60 → 240, đo được bằng test
- [ ] `logger.error` sau 3 lần hỏng liên tiếp
- [ ] `to_vn_time_str` **hoặc** chạy đúng **hoặc** đã bị xoá — không để dạng hỏng câm
- [ ] Đã kiểm bằng tay ca "tắt định vị" và nghe thấy câu đúng
- [ ] **App**: P8 xong hoặc ghi rõ PARTIAL — server kính hết câm, nhưng **lỗi
      gốc vẫn còn** cho tới khi app đổi sang `getCurrentLocation()`

---

## 6. Câu hỏi phải chốt

1. **Cache vị trí toàn cục hay theo device?** (trùng câu hỏi 1 của T03) Vị trí
   đến từ **điện thoại**, mà một điện thoại có thể ghép nhiều kính. Chưa chốt.
2. **`to_vn_time_str`: sửa hay xoá?** Đề xuất xoá.
3. **Ngưỡng "vị trí đã cũ" nói cho người dùng là bao nhiêu?** Server đang có
   TTL 600 s và MAX_FIX_AGE 600 s — bằng nhau nên tầng giữa của P9 hiện **rỗng**.
   Phải tách hai số ra thì P9 mới có chỗ chạy.
4. **Team app có làm được P8 không?** Không thì task này chỉ chữa được triệu
   chứng, ghi PARTIAL.
