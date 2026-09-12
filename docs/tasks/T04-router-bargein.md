# T04 — Điều phối: bỏ fast-bypass, thứ tự ưu tiên, ngắt lời

| | |
|---|---|
| **Mã spec** | B1 · 21.1 · G2 · G4 |
| **SPEC gốc** | mục 1, 21.1, G2, G4 |
| **Repo đụng** | Server kính (dùng `X-Turn-Id` của T01) |
| **Trạng thái** | READY (sau T03) |
| **Chặn bởi** | **T01 T03** |
| **Chặn** | T08 T09 T10 T11 T12 (validator slot) |

> Ba nguyên tắc xuyên suốt của spec, task này là chỗ thi hành nguyên tắc **1**:
> **trạng thái là gợi ý cho bộ phân loại, không phải hàng rào ở router.**

---

## 1. Hiện trạng

`pipeline/router.py:69-82` — `_resolve()` mở đầu bằng hai nhánh tắt:

```python
def _resolve(image, audio):
    state = device_state()
    if state.get("music_playing"):
        logger.info("Fast-Bypass: đang nghe nhạc -> dừng nhạc ngắt STT/Intent")
        yield from music.handle_stop(image, "", {})
        return
    if state.get("navigating"):
        logger.info("Fast-Bypass: đang chỉ đường -> dừng chỉ đường ngắt STT/Intent")
        yield from navigation.handle_stop(image, "", {})
        return
```

Nhạc đang phát → **mọi** câu nói đều thành "tắt nhạc".
Chỉ đường đang chạy → mọi câu thành "dừng chỉ đường".

### Hỏng ở đâu

- Đang nghe nhạc **không** hỏi được giờ, không gọi được ai, không hỏi được vật
  cản, **không gọi được cấp cứu**.
- Đang chỉ đường **không** hỏi được `hazard`/`space` — đúng thứ người khiếm thị
  cần nhất khi đang đi bộ.
- Bypass giết luôn cơ chế ngữ cảnh đã viết sẵn: `_CONTEXT_TEMPLATE`
  (`pipeline/intent.py:215`) và `_apply_state` (`:267`) **chỉ chạy khi không có
  gì đang chạy** — tức lúc chúng vô dụng.
- Nhánh "cả hai cùng chạy → chọn `most_recent`" (`intent.py:231` `_RECENT_LABELS`)
  là **dead code**, không đường nào tới được.
- `tests/test_device_state.py` đang **khoá đúng hành vi này**.

### Không có ngắt lời

Spec phần I không có một dòng nào về việc người dùng nói đè khi TTS đang chạy.
Với người khiếm thị, câu `describe_space` 40 từ mà không ngắt được là **hỏng
trải nghiệm**.

---

## 2. Việc phải làm

### B1 — bỏ bypass, thay bằng barge-in cục bộ

```python
_LOCAL_STOP = re.compile(
    r"tắt nhạc|dừng nhạc|dừng chỉ đường|dừng lại|thôi|im lặng", re.I
)
```

Chỉ chạy **khi có task đang chạy**. ~0 ms — giữ nguyên độ nhanh của "tắt nhạc",
nhưng không nuốt các câu khác.

Vẫn phải qua STT (regex cần text). Cái bị bỏ là **Gemini intent**, không phải STT.

### 21.1 — thứ tự ưu tiên (đây là **lỗi thật**, không phải tinh chỉnh)

Ca vỡ nếu để resolver pending trên lệnh stop:

```
AI:   "Bạn muốn gọi cho ai?"        (pending fill contact_name)
User: "tắt nhạc"
→ resolver điền contact_name = "tắt nhạc"
→ đi tìm người tên "tắt nhạc"
```

Thứ tự đúng — tách resolver làm **hai pha**:

```
1. EMERGENCY                 ← tuyệt đối, không qua bước nào (T09)
2. PENDING TẤT ĐỊNH          ← ừ/không/số thứ tự/thôi/nói lại
3. STOP / LỆNH TOÀN CỤC      ← chèn vào ĐÂY, giữa hai pha pending
4. PENDING ĐIỀN SLOT         ← qua slot validator
5. CANCEL / REPEAT
6. INTENT DETECT
```

**Pha 2 khác pha 4:** pha 2 là câu trả lời **đóng** (tập hữu hạn, khớp tất định,
< 400 ms, không LLM). Pha 4 là câu trả lời **mở** (tên người, địa điểm) — và
chính pha 4 mới nuốt nhầm "tắt nhạc".

### Slot validator — mỗi slot một bộ luật riêng

| Slot | Nhận | Từ chối |
|---|---|---|
| `contact_name` | danh từ / tên riêng | **động từ mệnh lệnh** (tắt, dừng, mở, gọi, phát) |
| `destination` | địa danh | như trên |
| `volume_direction` | tăng / giảm / số / to / nhỏ | mọi thứ khác |
| `song_title` | gần như mọi thứ | chỉ chặn lệnh stop |

Danh sách từ chối của từng slot do **task chức năng tương ứng cung cấp** (T08,
T10, T12); T04 chỉ dựng khung validator.

### G4 — ngắt lời (barge-in)

```
lượt mới tới → huỷ token của lượt cũ
             → dừng LLM stream
             → dừng TTS stream
```

`X-Turn-Id` (T01) là khoá của **cả hai** việc: chống lặp **và** ngắt lượt.

### G2 — không giữ lock trong lúc gọi LLM

```
lock CHỈ bao đọc/ghi state (micro giây)
việc dài chạy NGOÀI lock
generation counter (đã đặt sẵn ở T03) → lượt cũ thấy lệch thì tự huỷ
```

Gemini 1.5 s mà giữ lock thì ngắt lời bị chặn và lượt kế xếp hàng — tức G4 hỏng
vì G2, không phải vì chính nó.

---

## 3. Hợp đồng đổi

Không đụng repo khác. Ghi vào `CONTRACTS.md`: **bảng thứ tự 6 bước** ở trên —
đây là thứ dễ bị viết lại sai nhất trong cả spec.

---

## 4. Test

### 4.1 Bỏ bypass — `tests/test_router.py` (sửa) + `tests/test_device_state.py` (viết lại)

```
test_music_playing_still_allows_chat
  music_playing = True, nói "mấy giờ rồi"  → chat, KHÔNG phải music_stop

test_music_playing_still_allows_emergency
  music_playing = True, "gọi cấp cứu"      → emergency_call
  ← ca nặng nhất của bug hiện tại

test_navigating_still_allows_hazard
  navigating = True, "phía trước có gì"    → describe_hazard
  ← đúng thứ người khiếm thị cần nhất khi đang đi bộ

test_local_stop_regex_still_fast
  music_playing = True, "tắt nhạc"         → music_stop, KHÔNG gọi Gemini intent

test_local_stop_only_when_task_running
  không có gì chạy, "thôi"                 → KHÔNG rơi vào nhánh stop

test_context_template_now_reachable
  music_playing = True → _context_block() CÓ trong prompt intent
  ← hiện là dead code

test_both_running_picks_most_recent
  music + nav cùng chạy, "dừng lại"        → dừng cái mới nhất
  ← hiện KHÔNG đường nào tới được (intent.py:231)
```

### 4.2 Thứ tự ưu tiên — `tests/test_router_priority.py` (mới)

```
test_stop_beats_pending_fill                # 21.1, ca vỡ chính
  pending(contact_name) mở + "tắt nhạc"     → PHẢI ra music_stop
  → contact_name KHÔNG nhận "tắt nhạc"

test_deterministic_pending_beats_stop
  pending(confirm) mở + "ừ"                 → xác nhận, KHÔNG phải stop

test_emergency_beats_everything
  pending mở + nhạc chạy + "gọi cấp cứu"    → emergency_call, 0 bước trung gian

test_slot_validator_rejects_imperative
  pending(contact_name) + "mở nhạc"         → validator từ chối, không điền

test_volume_validator_only_accepts_direction
  pending(volume_direction) + "Sơn Tùng"    → từ chối

test_cancel_and_repeat_below_pending
  pending mở + "thôi bỏ đi"                 → cancel, xoá pending
  pending mở + "gì cơ"                      → đọc lại pending.question

test_unrelated_intent_during_pending
  pending(song_title) mở + "gọi cho mẹ"     → contact_call, pending bị bỏ
```

### 4.3 Ngắt lời — `tests/test_bargein.py` (mới)

```
test_new_turn_cancels_llm_stream
  lượt cũ đang stream Gemini → lượt mới tới → lượt cũ dừng

test_new_turn_cancels_tts_stream
  TTS đang phát câu 40 từ → lượt mới → cắt

test_new_turn_during_host_api_call
  lượt cũ đang chờ host → lượt mới → lượt cũ tự huỷ theo generation

test_lock_not_held_during_llm                # G2
  đo trực tiếp: lock không bị giữ quá 5 ms
```

### 4.4 Test cũ phải sửa

| File | Vì sao |
|---|---|
| `tests/test_device_state.py` | khoá đúng hành vi fast-bypass mà B1 gỡ bỏ (spec ghi dòng 138-172; **đọc lại số dòng thật trước khi sửa** — file có thể đã trôi) |
| `tests/test_router.py` | mọi ca đi qua `_resolve` |

---

## 5. DoD

```bash
pytest tests/test_router.py tests/test_router_priority.py tests/test_bargein.py tests/test_device_state.py -q
```

- [ ] Hai nhánh bypass ở `router.py:71-82` đã xoá
- [ ] Regex barge-in cục bộ chỉ chạy khi có task đang chạy
- [ ] Thứ tự 6 bước có mặt trong code **theo đúng thứ tự**, kèm comment trỏ về 21.1
- [ ] Slot validator có khung; T08/T10/T12 cắm danh sách từ chối vào được
- [ ] `X-Turn-Id` huỷ được **cả** LLM stream **và** TTS stream
- [ ] Lock đo được ≤ 5 ms (test 4.3 chạy thật, không skip)
- [ ] `tests/test_device_state.py` viết lại xong

---

## 6. Câu hỏi phải chốt

1. **"thôi" thuộc pha 2 hay pha 3?** Đang có mặt ở regex stop (pha 3) **và** là
   câu huỷ pending (pha 2). Trùng nghĩa. Đề xuất: có pending → pha 2 (huỷ
   pending); không pending mà có task chạy → pha 3 (stop).
2. **Cắt TTS giữa câu có gây khó nghe không?** Cắt ngay hay fade 100 ms. Cần thử
   bằng tai, không quyết được trên giấy.
