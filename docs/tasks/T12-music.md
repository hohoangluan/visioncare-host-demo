# T12 — Nhạc (`music_play` / `music_stop` / `music_volume`)

| | |
|---|---|
| **Mã spec** | A4 · A1 · D1 D4 · B2 · B7 |
| **SPEC gốc** | mục 13 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY (D4/`SONG_NOT_FOUND` chờ T20 xác nhận nguồn phát) |
| **Chặn bởi** | T03 T05 T06 |
| **Chặn** | — |

> Luồng nhiều lượt **phức tạp nhất repo**, và toàn bộ độ phức tạp đó là
> **heuristic chuỗi** đang thay cho việc trích slot. A4 xoá gần 70 dòng.

---

## 1. Hiện trạng

`handlers/music.py` — ba tầng đoán bằng chuỗi:

| Dòng | Thứ | Cách hoạt động |
|---|---|---|
| `:25` | `_GENERIC_SONG_WORDS` | 10 cụm hardcode, chặn câu chung chung |
| `:76` | `_names_a_song()` | dựa vào bảng trên |
| `:10` | `_ARTIST_MARKERS = (" - ", " của ", " by ")` | đoán "đã có ca sĩ chưa" |
| `:71` | `_names_an_artist()` | dựa vào bảng trên |
| `:6` | `_PENDING_SONG = "pending_song_title"` | chuỗi tự do trong `_LAST_IDS`, **không TTL** |
| `:86-97` | nhánh `if pending:` | ghép câu trả lời vào tên bài |

Ghép chuỗi thô (`:96`):

```python
elif pending.lower() not in answer.lower():
    song = f"{pending} - {answer}"
```

`handle_volume` (`:146`) — thiếu `direction` và `volume` → hỏi `_ASK_VOLUME`
(`:33`), **không nhớ gì**. Cố ý không mặc định "tăng": người khiếm thị không nhìn
được thanh âm lượng. **Giữ nguyên quyết định đó.**

### Bảy chỗ hỏng

**1. `_names_an_artist` sai cả hai chiều:**

| Người dùng nói | STT ra | Kết quả | Hậu quả |
|---|---|---|---|
| "Nơi này có anh **của** Sơn Tùng" | "Nơi này có anh Sơn Tùng" (nuốt "của") | `False` | hỏi lại ca sĩ dù vừa nói xong |
| "mở bài Chuyện **của** mùa đông" | như vậy | `True` | không hỏi, app chọn bừa cover |

**2. Ghép chuỗi thô** (`:96`): lệch một dấu/hoa thường là ra
`"Nơi này có anh - Nơi này có anh của Sơn Tùng"`.

**3. `_GENERIC_SONG_WORDS` là danh sách hữu hạn.** "mở nhạc nào đó đi", "cho
nghe cái gì đó", "nhạc gì cũng được" — **lọt hết**, thành tên bài đem đi query.

**4. `handle_volume` hỏi rồi quên** — người dùng đáp "tăng" thì không chắc về
được `music_volume`.

**5. `SONG_NOT_FOUND` là ngõ cụt** — `result_speech.py:24` nói *"vui lòng nói
lại tên bài"* rồi vứt ngữ cảnh.

**6. Pending không TTL** — bug ghép bài cũ với ca sĩ mới (mục 3 / T03).

**7. Chỗ hở đã biết — GIỮ NGUYÊN:** host không báo khi bài tự hết, nên
`music_playing` vẫn bật sau khi nhạc đã tắt. Comment ở `action_flow.py:78-86` đã
ghi và chấp nhận. **Đừng thay bằng TTL đoán mò.**

---

## 2. Việc phải làm

### A1 — schema riêng (thuộc T05, đây là nơi tiêu thụ)

```
song_title · artist · song_is_specific
```

### A4 — 🔴 xoá hết heuristic chuỗi

**Xoá** `handlers/music.py:10` `_ARTIST_MARKERS`, `:25` `_GENERIC_SONG_WORDS`,
`:71` `_names_an_artist`, `:76` `_names_a_song` — và nhánh ghép chuỗi `:86-97`.

Thay bằng: đọc thẳng `artist` và `song_is_specific` từ params.

```python
if not song_is_specific:
    → hỏi SLOTS["song_title"].ask + pending(song_title)
if song_title and not artist:
    → hỏi SLOTS["artist"].ask + pending(artist, known={"song_title": ...})
if song_title and artist:
    → song = f"{song_title} - {artist}"       # nối CHỈ khi cả hai có
```

**Không còn heuristic chuỗi nào.** Đây là điểm chính của task.

Giữ `_ANY_ARTIST_ANSWERS` (`:13`) — "cứ phát", "bất kỳ", "sao cũng được" là câu
trả lời **cho pending artist**, không phải heuristic đoán. Nhưng chuyển nó thành
một luật của **pending resolver tất định** (T04 pha 2), không phải `in` trên
chuỗi tự do.

### B2 / D1 — pending cho ba slot

| Slot | `ask` | `kind` | TTL |
|---|---|---|---|
| `song_title` | "Bạn muốn nghe bài hát nào?" | fill | 120 s |
| `artist` | "Bạn muốn nghe của ca sĩ nào?" | fill | 120 s |
| `volume_direction` | "Bạn muốn tăng hay giảm âm lượng?" | fill | 120 s |

`known` mang `song_title` sang lượt sau — **đây là thứ thay cho việc ghép
chuỗi**. Không có `known` thì lại phải nối bằng tay và bug quay lại.

Xoá `_PENDING_SONG` (`:6`) và mọi `remember/recall/forget` của nó.

### D4 — `SONG_NOT_FOUND` đặt pending

```python
"SONG_NOT_FOUND": ("song_title", "music_play")
```

Mã này **có nguồn phát thật** (khác `INVALID_DESTINATION`) — nhưng T20 phải xác
nhận. Chưa xác nhận thì `xfail`.

### B7 — nhạc và chỉ đường song song (thuộc T03)

Sau khi bỏ `_ACTIVE.clear()`: đi bộ + nghe nhạc là ca dùng thật. Task này chỉ
cần **test** rằng `music_play` không còn tắt `navigating`.

### Slot validator (cắm vào T04)

`song_title` gần như nhận mọi thứ — **chỉ chặn lệnh stop** ("tắt nhạc", "dừng
lại", "thôi"). Đây là slot lỏng nhất trong bảng, cố ý: tên bài hát tiếng Việt có
thể là bất cứ cụm từ nào.

`volume_direction` **chỉ** nhận: tăng · giảm · to · nhỏ · lớn · bé · số.
Từ chối mọi thứ khác.

### Host contract giữ nguyên

`song` vẫn là **một chuỗi** `"Tên - Ca sĩ"` (`endpoint.md:131`). A4 đổi cách
**dựng** chuỗi đó, không đổi hợp đồng.

---

## 3. Hợp đồng đổi

Không đổi.

---

## 4. Test

### 4.1 A4 — `tests/test_music_slots.py` (mới)

```
test_no_string_heuristics_left               # A4, ca chốt
  grep _ARTIST_MARKERS / _GENERIC_SONG_WORDS / _names_an_artist / _names_a_song
  → không còn trong music.py

test_song_title_and_artist_joined_only_when_both
  chỉ có title       → KHÔNG nối
  có cả hai          → "Title - Artist"

test_generic_request_asks_for_song           # thay cho _GENERIC_SONG_WORDS
  "mở nhạc nào đó đi"      → song_is_specific=False → hỏi lại
  "cho nghe cái gì đó"     → hỏi lại      ← hiện LỌT
  "nhạc gì cũng được"      → hỏi lại      ← hiện LỌT

test_artist_swallowed_cua_still_detected     # ca sai chiều 1
  "Nơi này có anh Sơn Tùng" (STT nuốt "của")
  → artist = "Sơn Tùng", KHÔNG hỏi lại

test_song_title_containing_cua_not_split     # ca sai chiều 2
  "mở bài Chuyện của mùa đông"
  → song_title đầy đủ, artist = None → HỎI ca sĩ
```

### 4.2 Luồng 2 lượt — `tests/test_slots.py` (dùng chung)

```
test_music_missing_song_two_turns
test_music_missing_artist_two_turns
  lượt 1 "mở bài Nơi này có anh"  → hỏi ca sĩ, pending(artist)
                                    known = {"song_title": "Nơi này có anh"}
  lượt 2 "Sơn Tùng"               → song = "Nơi này có anh - Sơn Tùng"
                                    KHÔNG có ghép chuỗi thô

test_any_artist_answer                       # _ANY_ARTIST_ANSWERS
  pending(artist) + "cứ phát"     → gửi chỉ song_title

test_volume_missing_direction_two_turns      # bug 4
  lượt 1 "chỉnh âm lượng"         → hỏi + pending(volume_direction)
  lượt 2 "tăng"                   → music_volume, KHÔNG phải chat

test_volume_validator_rejects_non_direction
  pending(volume_direction) + "Sơn Tùng"  → từ chối

test_music_pending_ttl_expired               # bug 6, ca kinh điển
  pending(artist) đặt hôm qua
  hôm nay "phát nhạc Đen Vâu"
  → KHÔNG ra "bài-cũ - Đen Vâu"
```

### 4.3 D4

```
test_song_not_found_sets_pending
  host trả SONG_NOT_FOUND → pending(song_title), không phải ngõ cụt
```

### 4.4 Khoá chỗ hở cố ý — đừng ai "sửa"

```
test_music_playing_stays_true_after_song_ends
  host KHÔNG báo bài hết → music_playing vẫn True
  → đây là hành vi ĐÃ CHẤP NHẬN (action_flow.py:78-86)
  → KHÔNG được thay bằng TTL đoán mò
```

### 4.5 Song song với chỉ đường

```
test_music_play_does_not_stop_navigation     # B7
```

### 4.6 Test cũ phải sửa

| File | Vì sao |
|---|---|
| `tests/test_services.py` | khoá logic ghép chuỗi tên bài mà A4 gỡ bỏ (spec ghi dòng 306-330; **kiểm số dòng thật trước khi sửa**) |

---

## 5. DoD

```bash
pytest tests/test_music_slots.py tests/test_slots.py -k music -q
pytest tests/test_services.py -q
```

- [ ] Bốn thứ ở A4 đã xoá khỏi `music.py` — kiểm bằng grep, có test
- [ ] Nối `"Title - Artist"` **chỉ khi cả hai có**
- [ ] Ba slot có pending, `known` mang `song_title` sang lượt sau
- [ ] `_PENDING_SONG` và `remember/recall/forget` của nó đã xoá
- [ ] `_ASK_SONG` / `_ASK_VOLUME` dời sang `slots.py`, `STATIC_SPEECH` cập nhật
- [ ] `handle_volume` **vẫn không** mặc định "tăng"
- [ ] Chỗ hở "bài tự hết" **còn nguyên** + có test khoá lại
- [ ] `tests/test_services.py` sửa xong, xanh

---

## 6. Câu hỏi phải chốt

1. **`song_is_specific` do model quyết — độ tin cậy bao nhiêu?** Đây là thứ thay
   cho `_GENERIC_SONG_WORDS`. Model quyết sai thì hoặc hỏi thừa, hoặc query rác.
   Cần bảng ca đo thật (dùng chung `measurements/A2.md` của T05).
2. **`artist` thiếu thì hỏi hay cứ phát?** Hiện hỏi. Nhưng "mở Nơi này có anh"
   là câu đủ rõ với người dùng — bắt họ nói thêm ca sĩ có thể là phiền. Cân nhắc:
   `song_is_specific=True` + không có artist → **cứ gửi**, để app chọn.
   Đổi thì bỏ luôn slot `artist` khỏi bảng SLOTS.
3. **`SONG_NOT_FOUND` có nguồn phát thật không?** T20 phải xác nhận trước khi bỏ
   `xfail`.
