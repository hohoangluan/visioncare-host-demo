# T03 — Phiên & pending (nền của mọi luồng nhiều lượt)

| | |
|---|---|
| **Mã spec** | B2 B4 B6 B7 · 21.2 21.3 21.4 |
| **SPEC gốc** | mục 3, 21.2–21.4 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY (sau T01) |
| **Chặn bởi** | **T01** (`device_id`) |
| **Chặn** | T04 T05 T06 T08 T09 T10 T11 T12 T15 |

> Đây là **hạ tầng dùng chung**. Sáu task chức năng đều gọi vào đây. Làm sai
> một lần thì sai ở sáu chỗ, nên test của task này phải dày hơn task chức năng.

---

## 1. Hiện trạng

`handlers/action_flow.py` — hai dict module-level, **không khoá theo thiết bị**:

| Dòng | Biến | Nội dung |
|---|---|---|
| `:61` | `_LAST_IDS` | `navigation_id`, `quote_id` + hai khoá pending tự phát: `pending_song_title`, `pending_ride_destination` |
| `:88` | `_ACTIVE` | việc đang chạy → mốc `time.monotonic()` |
| `:97 :102 :107` | `remember` / `recall` / `forget` | API hiện tại |
| `:112` | `device_state()` | `{music_playing, navigating, ride_quote_pending, most_recent}` |
| `:134-137` | `mark_active()` | gọi `_ACTIVE.clear()` **trước khi** set → Single Active State |

Lịch sử hội thoại nằm riêng ở `handlers/chat.py:226`:
`deque(maxlen=config.CHAT_HISTORY_TURNS)`, TTL `CHAT_HISTORY_TTL_SECONDS = 600`
(`config.py:138`) — **chỉ ghi lượt `chat`**, **chỉ dùng cho prompt `chat`**.

### Sáu chỗ hỏng

1. **Pending không có TTL.** `forget()` chỉ được gọi khi luồng đi đúng đường.
   Bỏ ngang → `pending_song_title` sống mãi. Ngày mai nói "phát nhạc Đen Vâu" →
   nhánh `if pending:` (`handlers/music.py:87`) ghép thành `"bài-cũ - Đen Vâu"`.
2. **Không có đường huỷ pending bằng lời.**
3. **Pending là chuỗi tự do** — không biết đang chờ slot nào cho intent nào.
4. **State toàn cục.** `VISIONCARE_DEVICE_ID` hardcode (`config.py:200`).
   Hai kính = trộn session.
5. **Lịch sử không ghi lượt action.** "Vừa nãy tôi đặt xe đi đâu?" → chịu.
6. **Single Active State sai thực tế** (`:136` `_ACTIVE.clear()`): đi bộ + nghe
   nhạc là ca dùng thật.

---

## 2. Việc phải làm

### B2 — `Pending` dataclass

```python
@dataclass
class Pending:
    slot: str          # "contact_name" | "destination" | "song_title" | ...
    intent: str        # intent chạy lại khi có câu trả lời
    known: dict        # params đã thu được
    question: str      # nguyên văn câu vừa hỏi (dùng cho "nói lại đi")
    candidates: list   # ứng viên danh bạ / dịch vụ xe, nếu có
    asked_at: float
    attempt: int = 0           # 21.2
    max_attempt: int = 2       # 21.2
    ttl: float = 120.0         # 21.3, xem bảng dưới
    kind: str = "fill"         # "fill" | "confirm" | "select"
```

### 21.3 — TTL theo loại, **không** 90 s cho mọi slot

| `kind` | TTL | Vì sao |
|---|---|---|
| `confirm` (sắp gọi / sắp đặt xe) | **25 s** | để lâu rất nguy hiểm: người dùng quên ngữ cảnh rồi "ừ" cho việc khác |
| `select` | **45 s** | |
| `select` bảng giá xe (T11/R4) | **45 s** | giá Farefeed có surge; quá hạn phải gọi lại, **cấm** đọc lại giá cũ |
| `fill` rủi ro thấp (`song_title`) | **120 s** | chốt ở `CONTRACTS.md` (spec mục 17.3) |

**`asked_at` tính từ lúc TTS phát xong**, không phải lúc server tạo pending.
Chênh 1–3 giây — với `confirm` 25 s thì đó là hơn 10 % ngân sách.

Cần một hook từ đường phát audio về pending store. Nếu chưa có hook đó thì ghi
`asked_at = now + ước lượng độ dài câu`, và **ghi comment là ước lượng**.

### 21.2 — `attempt_count`

User đọc sai tên bốn lần → hiện hỏi lại y hệt bốn lần.

Vượt `max_attempt` thì **đổi chiến lược**, không hỏi lại nguyên văn:

```
contact_name  → đọc 3 contact gần nhất / "đánh vần giúp tôi"
destination   → "nói tên đường và quận"
song_title    → "nói tên ca sĩ trước"
ocr (T15/H3)  → ba câu hướng dẫn chụp tăng dần
→ hết cách   → bỏ intent, nói thẳng là chưa làm được
```

### 21.4 — **một pending / device, không lồng nhau**

Tối đa **1**. Không stack. Ghi thành assert trong code **và** thành test.

Không ghi rõ thì lần implement sau sẽ có người tự chế stack rồi vỡ ở ca
"pending mới sinh ra trong lúc pending cũ chưa xong".

### B6 — session khoá theo `device_id`

```python
_SESSIONS: dict[str, Session] = {}   # device_id -> Session

@dataclass
class Session:
    last_ids: dict          # thay _LAST_IDS
    active: dict            # thay _ACTIVE
    pending: Pending | None
    history: deque          # B4
    last_ocr: dict | None   # T14/E2
    contacts: list | None   # T08/P1 cache
```

`device_id` đọc từ context của T01, **không** từ `config.VISIONCARE_DEVICE_ID`.

Cần dọn session cũ: thiết bị không hoạt động > N giờ → xoá, để dict không phình.

### B4 — lịch sử dùng chung, ghi **cả lượt action**

Chuyển `handlers/chat.py:226` `_HISTORY` vào `Session`. Mọi handler ghi vào,
không riêng `chat`.

"Vừa nãy tôi đặt xe đi đâu?" trả lời được. Lượt action ghi dạng gọn:
`("đặt xe tới Bách Khoa", "đã mở Grab, xe máy 32-38 nghìn")`.

### B7 — bỏ `_ACTIVE.clear()`

`handlers/action_flow.py:136`. Nhạc và chỉ đường chạy song song được.

**Giữ nguyên** chỗ hở đã biết ở `action_flow.py:78-86`: host không báo khi bài
tự hết nên `music_playing` vẫn bật sau khi nhạc đã tắt. Comment đã ghi và chấp
nhận — **đừng thay bằng TTL đoán mò**.

### G2 (từ T21, nhưng phải thiết kế ngay ở đây)

```
lock CHỈ bao đọc/ghi state (micro giây)
việc dài (Gemini, host API) chạy NGOÀI lock
mỗi device một generation counter
lượt mới → tăng generation → lượt cũ thấy generation lệch → tự huỷ
```

Retrofit sau rất đắt. Đặt `generation: int` vào `Session` **ngay từ commit đầu**
kể cả khi T04 chưa dùng tới.

---

## 3. Hợp đồng đổi

Nội bộ server kính, không đụng repo khác. Ghi vào `CONTRACTS.md`:
bảng TTL theo `kind`, và luật **một pending / device**.

---

## 4. Test

### 4.1 Unit thuần hàm — `tests/test_pending.py` (mới)

```
test_pending_expires_by_kind
  fill 120s · select 45s · confirm 25s   → mỗi loại hết hạn đúng mốc

test_asked_at_starts_after_tts
  asked_at > thời điểm tạo pending

test_attempt_increments
  ba lượt trả lời sai → attempt = 3

test_attempt_over_max_changes_strategy
  attempt > max_attempt → KHÔNG trả lại question nguyên văn

test_only_one_pending_per_device
  đặt pending thứ hai khi pending cũ còn sống → pending cũ bị thay,
  KHÔNG stack (assert + test)

test_pending_cleared_on_success
  luồng đi trọn → pending biến mất
```

### 4.2 Cách ly thiết bị — `tests/test_session_isolation.py` (mới)

```
test_pending_isolated_between_devices
test_music_state_isolated_between_devices
test_history_isolated_between_devices
test_location_cache_shared_or_isolated     # CHỐT Ở MỤC 6 TRƯỚC KHI VIẾT
test_session_gc_removes_idle_device
```

### 4.3 Trạng thái song song

```
test_music_and_navigation_run_together      # B7
  mark_active("music_playing") rồi mark_active("navigating")
  → device_state() báo CẢ HAI

test_music_stop_does_not_clear_navigation
```

### 4.4 Lịch sử dùng chung

```
test_history_records_action_turns           # B4
  đặt xe → lịch sử có lượt đó
  hỏi "vừa nãy tôi đặt xe đi đâu" → prompt chat CÓ lượt đó

test_history_ttl                            # 600s giữ nguyên
```

### 4.5 Test cũ phải sửa

| File | Vì sao |
|---|---|
| `tests/test_device_state.py` | Toàn bộ file giả định state toàn cục + Single Active State. B6 và B7 phá cả hai. Ca fast-bypass thì thuộc **T04**. |

---

## 5. DoD

```bash
pytest tests/test_pending.py tests/test_session_isolation.py tests/test_device_state.py -q
```

- [ ] `Pending` có đủ 9 trường, `kind` quyết định TTL
- [ ] `asked_at` tính từ sau TTS (hoặc ước lượng **có ghi comment là ước lượng**)
- [ ] **Một** pending / device — có assert trong code, không chỉ trong test
- [ ] `Session` khoá theo `device_id` từ context T01
- [ ] `generation` counter có mặt, kể cả khi T04 chưa dùng
- [ ] `_ACTIVE.clear()` ở `action_flow.py:136` đã bỏ
- [ ] Chỗ hở "bài tự hết" ở `action_flow.py:78-86` **vẫn còn nguyên**, không ai
      thay bằng TTL đoán mò
- [ ] `tests/test_device_state.py` viết lại xong, xanh

---

## 6. Câu hỏi phải chốt

1. **Cache vị trí dùng chung hay theo device?** Hiện là toàn cục
   (`handlers/chat.py:99`). Một kính một người → phải theo device. Nhưng vị trí
   đến từ **điện thoại**, và một điện thoại có thể ghép nhiều kính. Chưa chốt —
   ảnh hưởng T07.
2. **Dọn session sau bao lâu không hoạt động?** Đề xuất 24 h.
3. **`asked_at` sau TTS — có hook không?** Nếu đường phát audio không gọi ngược
   được về pending store thì phải ước lượng. Chốt cách nào trước khi code.
