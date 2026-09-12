# T08 — Gọi danh bạ (`contact_call`)

| | |
|---|---|
| **Mã spec** | D2 D6 D7 D8 D9 · P1 P2 · H1 H2 H3 |
| **SPEC gốc** | mục 9, mục 14 (bảng slot), 26.1, 26.2, 26.10 |
| **Repo đụng** | Server kính · **App Android** |
| **Trạng thái** | PARTIAL — nhánh chính chờ P1 phía app |
| **Chặn bởi** | T03 (Pending) · T05 (bỏ SetFit khi có pending) · T06 (bảng SLOTS) |
| **Chặn** | — |

> Đọc **26.1 trước tiên**. Mục 9 của spec viết *"host tự tìm mờ theo tên"* —
> **sai**. App so khớp bằng nhau tuyệt đối. Cả nhóm D được thiết kế trên giả
> định đó, và giả định đó vỡ.

---

## 1. Hiện trạng

### Server kính

`handlers/phone.py:27-47` — `handle_contact()`:

```python
name = params.get("contact_name")
if not name:
    yield _ASK_CONTACT          # phone.py:5 "Bạn muốn gọi cho ai?..."
    return                      # ...rồi quên sạch, không lưu gì
yield from run_action("contact_call", "api/v1/service/contact/call",
                      {"name": name}, ack=f"Đang tìm số của {name}.", ...)
```

- Không có pending → câu trả lời "mẹ" ở lượt sau đi về `chat`.
- Gửi `name`, **không** gửi `contact_id` (endpoint có nhận — `endpoint.md:265`).
- Ack đọc tên (`phone.py:41`) nhưng **lệnh đã gửi rồi** — nghe tên sai lúc máy
  đang quay số, không có cửa sổ sửa.

`handlers/result_speech.py:180-184` — `speak_result()` vứt `details`:

```python
error = data.get("error") or {}
code = error.get("code", "")
if code in _ERROR_SPEECH:
    return _ERROR_SPEECH[code]      # details.candidates[] chết ở đây
```

`_ERROR_SPEECH` (`result_speech.py:16-17`) cho hai mã của luồng này:

| Mã | Câu hiện tại | Hỏng ở đâu |
|---|---|---|
| `CONTACT_NOT_FOUND` | "Không tìm thấy người này trong danh bạ." | ngõ cụt, không hỏi lại |
| `MULTIPLE_CONTACTS_FOUND` | "…vui lòng nói rõ hơn." | có `candidates[]` thật trong tay mà không đọc |

Cả hai câu nằm trong `STATIC_SPEECH` (`result_speech.py:102-114`, qua
`*_ERROR_SPEECH.values()`) để dựng sẵn audio.

### App Android — `ActionRegistry.kt`

```kotlin
// :110  ContactLookup.findByName
if (name.trim().lowercase(Locale.getDefault()) != normalizedQuery) continue
```

- **So khớp bằng nhau tuyệt đối.** "Nguyệt Anh" không khớp "Nguyễn Nguyệt Anh".
  Sai một dấu → 0 kết quả.
- Quét toàn bộ bảng `Phone` với `selection = null` rồi lọc bằng vòng lặp Kotlin
  — O(n) mỗi cuộc gọi, trên đường tới hạn.
- `:500-511` **có** trả `details.candidates[]`, `phone_number` đã qua
  `maskPhoneNumber()` → `***456`. Che số là **đúng**, giữ nguyên.
- `ContactLookup.Match` chỉ mang `name` + `number`, **không mang `contact_id`**
  của `ContactsContract` → lượt gọi lại buộc phải gửi lại `name` → rơi lại vào
  bug so khớp tuyệt đối. **Vòng kín.**

Hệ quả cho thiết kế: `MULTIPLE_CONTACTS_FOUND` chỉ nổ khi hai contact trùng tên
hiển thị **y hệt** — ca hiếm. Nên **D6 gần như không bao giờ chạy**, còn
`CONTACT_NOT_FOUND` mới là đường hỏng chính.

---

## 2. Việc phải làm

### 2.1 Server kính

#### D7 — `handlers/contact_match.py` (file mới)

Thuần hàm, không I/O. Đây là chỗ chứa toàn bộ trí tuệ so khớp, vì phía app
không có thuật toán nào để cải thiện dần.

Chuẩn hoá **hai tầng** — STT sai theo hai kiểu khác nhau:

```python
def norm(s: str) -> str:
    """Tầng 1: bỏ dấu thanh. Dấu là thứ STT sai nhiều nhất."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", s)

def phon(s: str) -> str:
    """Tầng 2: gộp cặp phụ âm ASR tiếng Việt hay lẫn.

    Digraph phải thay TRƯỚC, không thì "tr" bị "t" ăn mất.
    """
    # tr|ch -> C · ng|nh|n|l -> N · gi|d|r -> D · s|x -> S
    # thêm: iê|i -> I · ươ|ư -> U   (21.6)
```

Điểm: `max(WRatio(norm), 0.95 * WRatio(phon))`.
Hệ số **0.95** để bản viết đúng chính tả thắng khi hoà — `phon` cố ý mất thông
tin, không nên thắng ngang.

Chính sách 3 ngưỡng (**số khởi điểm, phải đo lại trên danh bạ thật** — mục 17.2):

| Điểm cao nhất | Hành vi |
|---|---|
| ≥ 88 **và** hơn ứng viên nhì ≥ 8 | đọc **một** tên, chờ xác nhận: *"Bạn muốn gọi cho Nguyệt Anh, đúng không?"* |
| ≥ 70 | đọc **tối đa 3** tên, hỏi chọn |
| < 70 | *"Không tìm thấy ai giống Nguyệt trong danh bạ. Bạn đọc lại tên giúp tôi."* — **no_match, KHÔNG confirm** |

**Trần 3 tên là cứng.** Nghe bằng tai không giữ nổi 5 cái tên; đọc 5 rồi hỏi
"ai" là bắt người dùng nhớ hộ một danh sách họ không nhìn thấy.

**Ngưỡng từ chối là bắt buộc** (21.6). Thiếu nó thì hệ thống hỏi bừa *"Gọi Nguyệt
Anh đúng không?"* khi người dùng nói "Ngọc Ánh".

**Tên trùng hệt nhau** → thêm đuôi số: *"Mẹ, số đuôi 456; Mẹ, số đuôi 789."*
Chỉ **3-4 chữ số cuối**, và **chỉ khi tên trùng**. Đọc nguyên số điện thoại
thành tiếng là phát tán thông tin cá nhân ra loa nơi công cộng — người khiếm thị
không biết xung quanh có ai đang nghe.

#### D2 — thiếu tên thì đặt pending trước khi hỏi

`handlers/phone.py:33-35`:

```python
if not name:
    pending.set(device_id, Pending(          # T03
        slot="contact_name", intent="contact_call",
        known={}, question=SLOTS["contact_name"].ask,   # T06
        candidates=[], asked_at=<lúc TTS phát xong>))
    yield SLOTS["contact_name"].ask
    return
```

`asked_at` tính từ lúc **TTS phát xong**, không phải lúc server tạo pending
(21.3). Chênh 1-3 giây.

TTL: tầng `fill` → **120 s** (chốt ở `CONTRACTS.md`).

#### D6 — `speak_result` trả `(câu nói, pending | None)`

`handlers/result_speech.py:164` đổi chữ ký. `MULTIPLE_CONTACTS_FOUND` dựng câu
từ **ứng viên thật** trong `details.candidates[]` + đặt pending
`slot="contact_selection"`, `candidates=[...]`.

Câu chứa tên là **động, không dựng sẵn audio được**. Tách phần cố định ra để nửa
đó vẫn trúng cache, giống cách `handlers/music.py:50-53` đã làm với ack có tên
bài:

```
["Có nhiều người trùng tên: "]  +  [tên tổng hợp]  +  ["Bạn chọn ai?"]
 ↑ STATIC_SPEECH                   ↑ TTS thật        ↑ STATIC_SPEECH
```

#### D3 — readback theo `slot_confidence`

`contact_name` = **`low_conf`** (chốt ở `CONTRACTS.md`, mục 17.4).
Lý do không chọn `always`: gọi mẹ 20 lần/ngày mà lần nào cũng phải xác nhận là
**hình phạt cho ca dùng phổ biến nhất**.

`slot_confidence` đến từ intent (T05/A1). `low` → đọc lại tên, chờ xác nhận
**trước khi** gửi `run_action`. Hiện ack đọc tên sau khi đã gửi — vô dụng.

#### D4 — đặt pending từ mã lỗi host

`handlers/action_flow.py` — `run_action` (`:213`) đặt được pending từ kết quả:

```python
_ERROR_REASK = {
    "MULTIPLE_CONTACTS_FOUND": ("contact_name", "contact_call"),
    "CONTACT_NOT_FOUND":       ("contact_name", "contact_call"),
}
```

Người dùng đáp một từ là chạy tiếp, không phải nói lại cả câu.

#### D8 — lượt gọi lại dùng `contact_id`

Có `contact_id` → gửi `{"contact_id": ...}`, **bỏ hẳn `name`**
(`endpoint.md:265`). Không có id (P2 chưa xong) → vẫn gửi `name` và chấp nhận
26.1; ghi log rõ để đếm được ca này.

#### Lượt chọn — khớp theo **hai đường**, lấy đường nào ra kết quả

Pending giữ `candidates[]`:

1. **fuzzy lại vào danh sách** (người dùng đọc tên)
2. **thứ tự** — "cái đầu", "số một", "người thứ hai", "cái cuối"

#### D9 — `requirements.txt`

```
rapidfuzz   # so khớp tên danh bạ (D7). Wheel C++ thuần ~1MB, không model,
            # không torch. difflib stdlib kém hẳn khi đảo thứ tự token
            # ("Anh Nguyệt" vs "Nguyệt Anh") — đúng thứ hay gặp với tên Việt.
```

#### Ràng buộc từ 21.1 — thứ tự ưu tiên router

Slot `contact_name` **không nhận động từ mệnh lệnh**. Ca vỡ phải chặn:

```
AI:   "Bạn muốn gọi cho ai?"
User: "tắt nhạc"
→ SAI: contact_name = "tắt nhạc", đi tìm người tên "tắt nhạc"
→ ĐÚNG: music_stop
```

Validator riêng theo slot nằm ở **T04**. T08 chỉ **cung cấp** danh sách từ chối
cho slot này.

### 2.2 App Android — **đường chính, không phải dự phòng**

#### P1 — action `contact_list` (ưu tiên cao nhất)

Trả cả danh bạ: `[{contact_id, name, phone_tail}]`. Server kính cache ở nền như
đang làm với vị trí, tự so khớp bằng D7.

Lợi:
- "Gọi cho mẹ" resolve thẳng ra `contact_id` — **không round-trip nào**
- Chất lượng so khớp do mình sở hữu, sửa được không cần đụng app
- Mở khoá ca "tên đặt lạ" ("Em iu", "Bà xã", "Sếp Tổng", "Xe ôm hay đi") mà
  `CONTACT_NOT_FOUND` không kèm ứng viên nào — hiện là **ngõ cụt tuyệt đối**,
  `endpoint.md` không có endpoint liệt kê danh bạ

**Chốt: P1 trước P2.** Làm được P1 thì P2 thành thừa.

#### P2 — `contact_id` trong `candidates[]` (mức tối thiểu nếu P1 không làm được)

`ContactLookup.Match` mang thêm `contact_id`; trả trong `candidates[]`;
`contact_call` nhận `contact_id` để bỏ hẳn bước tìm.

Không có P1 lẫn P2 → nhóm D chỉ chạy **nửa vời**: pending và hỏi lại chạy được,
nhưng lượt gọi lại vẫn rơi vào so khớp tuyệt đối.

#### P1b — nếu vẫn giữ `findByName`

Đổi `selection = null` sang truy vấn có `selection` để không quét O(n) trên
đường tới hạn.

### 2.3 Server app · Firmware

**Không đụng.** Hợp đồng `POST /api/v1/service/contact/call` (`endpoint.md:248`)
đã có sẵn `contact_id`, không cần đổi.

---

## 3. Hợp đồng đổi

Chỉ P1 phát sinh hợp đồng mới. Ghi đầy đủ ở `CONTRACTS.md`, tóm tắt:

```jsonc
// MỚI: action contact_list  (app → host → server kính)
{ "contacts": [
    { "contact_id": "raw_contact_42",
      "name": "Nguyễn Nguyệt Anh",
      "phone_tail": "456" }        // 3-4 chữ số cuối, KHÔNG gửi số đầy đủ
] }
```

```jsonc
// ĐỔI: candidates[] hiện có (P2)
{ "details": { "candidates": [
    { "name": "Mẹ", "phone_number": "***456",
      "contact_id": "raw_contact_42" }   // + trường này
] } }
```

Số đầy đủ **không rời khỏi điện thoại** ở cả hai hợp đồng.

---

## 4. Test

### 4.1 Unit thuần hàm — chạy được ngay, không cần host, không cần app

`tests/test_contact_match.py` **(mới)** — bảng ca cho `norm` / `phon` / `rank`:

| Nhóm ca | Vào | Danh bạ | Kỳ vọng |
|---|---|---|---|
| sai dấu thanh | "Nguyet Anh" | Nguyệt Anh | ≥ 88, tầng confirm |
| thừa họ | "Nguyệt Anh" | Nguyễn Nguyệt Anh | ≥ 88 (ca 26.1 làm vỡ) |
| đảo token | "Anh Nguyệt" | Nguyệt Anh | ≥ 88 |
| cặp n/l | "Nan" | Lan | tầng phon cứu được |
| cặp tr/ch | "Chung" | Trung | digraph thay trước |
| cặp s/x | "Xơn" | Sơn | |
| cặp d/gi/r | "Dung" | Giung | |
| **từ chối** | "Ngọc Ánh" | Nguyệt Anh | < 70, **no_match, KHÔNG confirm** |
| trần 3 tên | 1 từ khớp 6 contact | | trả đúng **3** |
| trùng tên hệt | "mẹ" | Mẹ ×2 | kèm đuôi số, chỉ 3-4 chữ số |
| chính tả thắng hoà | | | hệ số 0.95 có tác dụng |
| rỗng / 1 ký tự | "" · "a" | | no_match, không crash |

```
pytest tests/test_contact_match.py -q
```

### 4.2 Test luồng — 2 lượt, fake host

`tests/test_slots.py` **(mới, dùng chung với T06)**:

```
test_contact_missing_name_two_turns
  lượt 1  "gọi điện đi"        → ask + pending(contact_name) tồn tại
  lượt 2  "mẹ"                 → intent = contact_call, KHÔNG phải chat
                                → run_action gửi đi với name/contact_id
                                → pending bị xoá

test_contact_pending_ttl_expired
  lượt 1  ask, pending asked_at = now - 121
  lượt 2  "mẹ"                 → pending đã hết hạn, KHÔNG ghép
                                → phân loại bình thường

test_contact_pending_yields_to_stop_command      # 21.1
  pending(contact_name) mở
  "tắt nhạc"                   → PHẢI ra music_stop
                                → contact_name KHÔNG nhận "tắt nhạc"

test_contact_attempt_max                          # 21.2
  đọc sai tên 3 lần            → lần 3 ĐỔI CHIẾN LƯỢC
                                → không hỏi lại nguyên văn

test_multiple_contacts_reads_real_names           # D6
  host trả MULTIPLE_CONTACTS_FOUND + candidates[3]
  → câu nói CHỨA tên thật, KHÔNG phải "vui lòng nói rõ hơn"
  → pending(contact_selection) có đủ candidates

test_contact_selection_by_ordinal                 # lượt chọn, đường 2
  candidates = [A, B, C]
  "người thứ hai"              → chọn B

test_contact_selection_by_name                    # lượt chọn, đường 1
  "gọi Nguyệt"                 → fuzzy vào candidates

test_contact_not_found_sets_pending               # D4
  host trả CONTACT_NOT_FOUND   → pending(contact_name) được đặt
                                → không phải ngõ cụt

test_low_confidence_reads_back_before_send        # D3
  slot_confidence = "low"      → KHÔNG gọi host ở lượt này
                                → đọc lại tên, chờ xác nhận

test_high_confidence_sends_immediately            # D3
  slot_confidence = "high"     → gọi host ngay, không hỏi thêm

test_contact_id_replaces_name                     # D8
  pending có contact_id        → payload có contact_id, KHÔNG có name
```

```
pytest tests/test_slots.py -k contact -q
```

### 4.3 Test cách ly thiết bị

Thuộc T03 nhưng phải có ca của luồng này:

```
pending contact_name của device A không ảnh hưởng device B
```

### 4.4 Phải sửa test cũ

Không có. `tests/test_services.py` có ca `contact_call` nhưng ở mức
`run_action`, D2–D8 không phá.

### 4.5 Thủ công — chỉ ca này mới cần người thật

| Kịch bản | Nghe được gì thì đạt |
|---|---|
| Danh bạ thật ≥ 200 contact, đọc 20 tên hay gọi | đo lại ngưỡng 88/70/margin 8 — **số trong D7 là khởi điểm** |
| Tên đặt lạ: "Em iu", "Bà xã", "Sếp Tổng" | có P1 thì phải ra đúng người |
| Đọc 3 tên rồi hỏi chọn | nghe xong có nhớ nổi 3 tên không |
| Nơi công cộng, contact trùng tên | chỉ nghe **đuôi 3-4 số**, không nghe số đầy đủ |

---

## 5. Định nghĩa xong (DoD)

```bash
pytest tests/test_contact_match.py tests/test_slots.py -q
```

- [ ] `tests/test_contact_match.py` xanh, đủ 12 nhóm ca ở 4.1
- [ ] `tests/test_slots.py -k contact` xanh, đủ 11 ca ở 4.2
- [ ] `rapidfuzz` trong `requirements.txt` **kèm comment lý do**
- [ ] `speak_result` trả tuple, mọi chỗ gọi đã cập nhật
- [ ] Câu cố định mới có mặt trong `STATIC_SPEECH`; câu động **không** có
- [ ] Ngưỡng 88/70/8 có **bảng số đo trên danh bạ thật** trong repo
      (cùng nguyên tắc `config.py:104-110` và ngưỡng blur: *có bảng số thì mới
      được chốt*)
- [ ] P1 hoặc P2 đã xong phía app — **nếu chưa, đánh dấu PARTIAL và ghi rõ ca
      nào còn hỏng**, đừng báo xong

---

## 6. Câu hỏi phải chốt trước khi code

1. **P1 có tác động được sang team app không?** Có → D7 nhận danh sách đầy đủ,
   D6 chỉ còn là đường dự phòng, kiến trúc sạch hơn hẳn. Không → ca "tên đặt lạ"
   vẫn trượt vĩnh viễn.
2. **Cache danh bạ ở server kính bao lâu?** Vị trí đang 240 s. Danh bạ đổi hiếm
   hơn nhiều — đề xuất 1 giờ + làm mới lúc ghép máy. Chưa chốt.
3. **Đã chốt** (`CONTRACTS.md`): TTL `fill` 120 s · `readback` = `low_conf` ·
   P1 trước P2.
