# T06 — Bảng chính sách slot (`handlers/slots.py`)

| | |
|---|---|
| **Mã spec** | D1 D3 D4 D5 · G5 |
| **SPEC gốc** | mục 14, mục 10 (D5), G5 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY (D4 chờ T20) |
| **Chặn bởi** | T03 (Pending) · **T20** (chỉ riêng D4) |
| **Chặn** | T08 T09 T10 T11 T12 |

> Đây là chỗ **gom 5 hằng số `_ASK_*` rải rác + 4 câu lỗi ngõ cụt** về một mối.
> Không phải 9 bug rời — là **một** thiếu sót: `run_action` không có đường đặt
> pending từ kết quả trả về.

---

## 1. Hiện trạng

Năm hằng số `_ASK_*`, mỗi handler tự quyết khi nào hỏi lại:

| Hằng số | Chỗ |
|---|---|
| `_ASK_CONTACT` | `handlers/phone.py:5` |
| `_ASK_DESTINATION` | `handlers/navigation.py:5` |
| `_ASK_DESTINATION` | `handlers/ride.py:18` |
| `_ASK_SONG` | `handlers/music.py:29` |
| `_ASK_VOLUME` | `handlers/music.py:33` |

**Không ai đọc lại thông tin trước khi gửi, trừ `ride`.**

Cộng thêm **4 câu lỗi của host đặt câu hỏi mà hệ thống không nghe được câu trả
lời** (`handlers/result_speech.py:13-45`):

| Mã lỗi | Câu nói | Trả lời đi đâu |
|---|---|---|
| `MULTIPLE_CONTACTS_FOUND` | "…vui lòng **nói rõ hơn**" | → `chat` |
| `CONTACT_NOT_FOUND` | "Không tìm thấy người này…" | ngõ cụt |
| `SONG_NOT_FOUND` | "…vui lòng **nói lại tên bài**" | → `chat` |
| `INVALID_DESTINATION` | "…vui lòng **nói lại tên địa điểm**" | → `chat` |

---

## 2. Việc phải làm

### D1 — `handlers/slots.py` (file mới), một chỗ duy nhất

```python
@dataclass(frozen=True)
class SlotSpec:
    ask: str          # câu hỏi khi thiếu
    readback: str     # "always" | "low_conf" | "never"
    risk: str         # "high" -> sai là không sửa được
    kind: str         # "fill" | "confirm" | "select"  -> quyết định TTL (T03)

SLOTS = {
    "contact_name":     SlotSpec("Bạn muốn gọi cho ai?",             "low_conf", "high", "fill"),
    "destination":      SlotSpec("Bạn muốn đi đâu?",                 "low_conf", "high", "fill"),
    "ride_destination": SlotSpec("Bạn muốn đi đâu?",                 "always",   "high", "fill"),
    "song_title":       SlotSpec("Bạn muốn nghe bài hát nào?",       "never",    "low",  "fill"),
    "artist":           SlotSpec("Bạn muốn nghe của ca sĩ nào?",     "never",    "low",  "fill"),
    "volume_direction": SlotSpec("Bạn muốn tăng hay giảm âm lượng?", "never",    "low",  "fill"),
}
# emergency_number KHÔNG có mặt ở đây. Cố ý. Xem D5.
```

### D5 — 🔴 ngoại lệ tuyệt đối cho `emergency_call`

**Không đổi logic `handlers/phone.py:50-65`.** Thêm **assert** trong `slots.py`:

```python
assert "emergency_number" not in SLOTS, (
    "emergency_call KHÔNG được thêm bất kỳ bước hỏi lại hay "
    "đọc-lại-chờ-xác-nhận nào. Người dùng gọi khẩn cấp là lúc họ có thể đang "
    "ngã, đang bị thương, không nói thêm được câu thứ hai. Mọi cơ chế xác minh "
    "phải loại trừ nhãn này TƯỜNG MINH trong code, không để mặc định rơi vào."
)
```

Assert **và** test khoá lại. Đây là một trong ba nguyên tắc xuyên suốt của spec.

### D3 — readback theo `slot_confidence`

`slot_confidence` đến từ T05/A1.

| `readback` | Hành vi |
|---|---|
| `always` | luôn đọc lại + chờ xác nhận trước khi gửi |
| `low_conf` | chỉ khi `slot_confidence == "low"` |
| `never` | gửi thẳng |

**Vì sao `contact_name`/`destination` là `low_conf` chứ không `always`:** gọi mẹ
20 lần/ngày mà lần nào cũng phải xác nhận là **hình phạt cho ca dùng phổ biến
nhất**. `ride` giữ `always` — lý do cũ (tốn tiền thật) vẫn đúng, và sau T11/R1
lượt readback còn chở thêm **bảng giá**, thành lượt có giá trị nhất.

Pending của readback là `kind="confirm"` → TTL **25 s** (T03), không phải 120 s.

### D4 — `run_action` đặt được pending từ mã lỗi host

`handlers/action_flow.py:213`:

```python
_ERROR_REASK = {
    "MULTIPLE_CONTACTS_FOUND": ("contact_name", "contact_call"),
    "CONTACT_NOT_FOUND":       ("contact_name", "contact_call"),
    "SONG_NOT_FOUND":          ("song_title",   "music_play"),
    "INVALID_DESTINATION":     ("destination",  "nav_start"),
}
```

Người dùng đáp bằng **một từ** là chạy tiếp, không phải nói lại cả câu.

> ⚠️ **Hai trong bốn mã này chưa có nguồn phát** — `INVALID_DESTINATION` (app
> luôn trả `Success`) và `MULTIPLE_CONTACTS_FOUND` (chỉ nổ khi trùng tên y hệt).
> **Làm T20 trước D4**, nếu không là viết bảng ánh xạ cho mã lỗi không tồn tại
> rồi viết test cho một đường không chạy được.

### 21.7 — phân loại lỗi + fallback mặc định

Bảng `_ERROR_REASK` phải kèm:

```
retryable | terminal
default fallback khi không khớp dòng nào
```

Không có default → mã lỗi lạ rơi vào im lặng, người dùng không biết chuyện gì.
(`_GENERIC_FAILURE` ở `result_speech.py:50-60` đã là một nửa; nửa còn lại là
**có đặt pending hay không**.)

### G5 — câu cố định phải dựng sẵn audio

`pipeline/phrases.py` đã có cơ chế (`:47` `_speech_modules`, `:64` `collect`,
`:183` `warm`). Bắt buộc mở rộng cho **toàn bộ**:

```
6 câu ask trong bảng SLOTS
"Đã huỷ."
"Không có nhạc đang phát."
"Không có lộ trình nào đang chạy."
"Tôi không quan sát được phía sau."
ack của emergency_call
3 câu hướng dẫn chụp lại của T15/H3
```

Những lượt này **TTS = 0 ms**.

`pipeline/phrases.py:47` `_speech_modules()` phải thấy `handlers/slots.py`. Và
các `STATIC_SPEECH` cũ ở `phone.py:18`, `music.py:56`, `navigation.py:18` phải
**bỏ câu đã dời sang `slots.py`** — để hai chỗ thì cache dựng hai lần và một chỗ
sẽ trôi khỏi chỗ kia.

### Câu động không dựng sẵn được — tách đôi

Câu chứa tên ứng viên là **động**. Tách phần cố định ra để nửa đó vẫn trúng
cache, giống cách `handlers/music.py:50-53` đã làm với ack có tên bài.

---

## 3. Hợp đồng đổi

Không đụng repo khác. Ghi vào `CONTRACTS.md`: bảng `SLOTS` đầy đủ + luật
`emergency_number` **không bao giờ** có mặt.

---

## 4. Test

### 4.1 Unit thuần hàm — `tests/test_slots.py` (mới, dùng chung với T08/T10/T12)

```
test_every_slot_has_ask_readback_risk_kind
test_readback_matrix
  always    → luôn đọc lại
  low_conf  + slot_confidence=low   → đọc lại
  low_conf  + slot_confidence=high  → gửi thẳng
  never     → gửi thẳng

test_confirm_pending_uses_25s_ttl        # không phải 120s

test_emergency_number_not_in_slots       # 🔴 D5, ca quan trọng nhất file này
test_emergency_never_asks_back
  emergency_call thiếu mọi param → VẪN gửi lệnh, KHÔNG hỏi lại
test_emergency_never_reads_back
  slot_confidence=low → VẪN gửi ngay
```

Ba test emergency là **khoá an toàn**, không phải test tính năng. Đừng ai xoá.

### 4.2 Luồng 2 lượt — mỗi slot một ca

```
test_<slot>_missing_two_turns   × 6 slot
  lượt 1 → ask + pending đúng slot/intent
  lượt 2 → intent gốc chạy lại với slot đã điền
```

### 4.3 D4 — pending từ mã lỗi

```
test_error_reask_sets_pending           × 4 mã
test_unknown_error_code_has_fallback    # 21.7, KHÔNG im lặng
test_terminal_error_does_not_set_pending
```

⚠️ Hai trong bốn ca chỉ chạy được sau **T20**. Chưa có T20 thì đánh dấu
`@pytest.mark.xfail(reason="T20: mã lỗi chưa có nguồn phát")` — **đừng xoá test,
đừng báo xanh giả**.

### 4.4 G5 — audio dựng sẵn

```
test_all_slot_asks_are_static
  6 câu ask đều nằm trong tập collect() của phrases.py
test_no_duplicate_static_sentence
  câu đã dời sang slots.py KHÔNG còn ở STATIC_SPEECH cũ
test_dynamic_sentence_not_prebuilt
  câu chứa tên ứng viên KHÔNG nằm trong tập dựng sẵn
```

### 4.5 Test cũ phải sửa

| File | Vì sao |
|---|---|
| `tests/test_phrases.py` | tập câu dựng sẵn đổi |
| `tests/test_services.py` | `run_action` đổi (D4) |

---

## 5. DoD

```bash
pytest tests/test_slots.py tests/test_phrases.py tests/test_services.py -q
```

- [ ] `handlers/slots.py` là **chỗ duy nhất** định nghĩa câu hỏi lại — 5 hằng số
      `_ASK_*` cũ đã xoá khỏi 4 handler
- [ ] Assert `emergency_number not in SLOTS` có trong code, **kèm comment lý do**
- [ ] 3 test khoá emergency xanh
- [ ] `phrases.py:47` thấy `slots.py`; không có câu nào bị dựng sẵn hai lần
- [ ] D4 có fallback mặc định (21.7), không mã nào rơi vào im lặng
- [ ] D4 đánh dấu `xfail` đúng chỗ nếu T20 chưa xong — **không báo xanh giả**

---

## 6. Câu hỏi phải chốt

1. **Đã chốt** (`CONTRACTS.md`): `contact_name` = `low_conf`, `ride` = `always`.
2. **`ride_destination` và `destination` có cần là hai slot riêng không?** Khác
   nhau đúng một trường `readback`. Gộp lại rồi truyền `readback` theo intent thì
   bảng gọn hơn — nhưng dễ quên. Đề xuất **giữ hai dòng**, rõ hơn.
3. **Câu ask có nên khác nhau theo `attempt`?** T15/H3 làm vậy cho OCR (3 câu
   tăng dần). Các slot khác thì 21.2 chỉ nói "đổi chiến lược". Chốt: `attempt`
   vượt ngưỡng → gọi hàm `escalate(slot, attempt)` do từng task chức năng cung cấp.
