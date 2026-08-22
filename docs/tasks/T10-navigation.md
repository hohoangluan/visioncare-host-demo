# T10 — Chỉ đường (`nav_start` / `nav_stop`)

| | |
|---|---|
| **Mã spec** | D1 D3 D4 · A3 |
| **SPEC gốc** | mục 11, 26.5 |
| **Repo đụng** | Server kính · App Android |
| **Trạng thái** | PARTIAL — D4 chờ T20 (mã lỗi không có nguồn phát) |
| **Chặn bởi** | T03 T05 T06 · **T20** (chỉ D4) |
| **Chặn** | — |

---

## 1. Hiện trạng

### Server kính

`handlers/navigation.py:29-50` — `handle_start()`:

```python
destination = params.get("destination")
if not destination:
    yield _ASK_DESTINATION        # navigation.py:5
    return                        # ...không nhớ gì

yield from run_action("navigation_start", "api/v1/service/navigation/start",
                      {"destination": {"address": destination}},
                      ack=_START_ACK, ...)     # _START_ACK = "Đang mở chỉ đường."
```

`handle_stop()` (`:53-71`) lấy `navigation_id` từ `recall()`. Không có id → nói
`_NOTHING_TO_STOP` (`:12`) và `mark_inactive`.

> Comment ở `:33-35` đã ghi đúng lý do **không** bịa điểm đến khi thiếu — giữ
> nguyên tinh thần đó, chỉ thêm pending.

### Ba chỗ hỏng

1. **Hỏi rồi quên** — y hệt `contact_call`. "Bạn muốn đi đâu?" → người dùng đáp
   "Bưu điện Thành phố" → intent = `chat` → Gemini tán gẫu về bưu điện.

2. **Không đọc lại điểm đến trước khi gửi.** `_START_ACK` = *"Đang mở chỉ
   đường."* — **không có tên nơi đến**.

   `ride.py` cẩn thận (đọc lại, chờ xác nhận — `ride.py:71-72`) nhưng
   `navigation.py` gửi thẳng. **Cùng một rủi ro, hai mức cẩn thận khác nhau,
   không có lý do.** STT nghe "Bách Khoa" thành "Bát Khoa" → người mù **đi bộ**
   theo lộ trình sai mà không có tín hiệu nào để biết.

3. 🔴 **`INVALID_DESTINATION` không bao giờ được phát ra.**
   `NavigationStartHandler` (app) luôn trả `Success`: ném chuỗi địa chỉ vào
   `google.navigation:q=` rồi để Maps tự hiểu, **không kiểm địa điểm có tồn tại
   không**.

   Nghĩa là D4 đang ánh xạ một mã lỗi **không có nguồn phát**, và
   `result_speech.py:41` có sẵn câu *"Vui lòng nói lại tên địa điểm"* mà app
   không đời nào gửi.

---

## 2. Việc phải làm

### 2.1 Server kính

#### D1 — dùng `SLOTS["destination"]`

Xoá `_ASK_DESTINATION` (`navigation.py:5`) khỏi module, đọc từ `handlers/slots.py`
(T06). Cập nhật `STATIC_SPEECH` (`:18`) để câu không bị dựng sẵn hai chỗ.

#### D2-tương-đương — thiếu điểm đến thì đặt pending

```python
if not destination:
    pending.set(device_id, Pending(
        slot="destination", intent="nav_start",
        known={}, question=SLOTS["destination"].ask,
        kind="fill"))          # TTL 120 s
    yield SLOTS["destination"].ask
    return
```

#### D3 / A5 — ack đọc tên + readback theo `slot_confidence`

```python
ack = f"Đang mở chỉ đường tới {destination}."
```

Và `readback = "low_conf"` (T06): `slot_confidence == "low"` → **đọc lại, chờ
xác nhận trước khi gửi**, `kind="confirm"` → TTL 25 s.

Không chọn `always`: đi lại hằng ngày tới chỗ quen mà lần nào cũng phải xác nhận
là hình phạt cho ca phổ biến nhất (cùng lập luận với `contact_name`).

`ride` vẫn `always` — ở đó có tiền thật.

#### A3 — vị trí trong prompt intent (thuộc T05, ghi ở đây vì đây là lý do)

"Bách Khoa" là Hà Nội hay TP.HCM? `nav_start` là **một trong hai nhãn cần vị trí
nhất** mà hiện không được cấp. Xong T07 → T05/A3 → điểm đến resolve đúng vùng.

#### D4 — pending từ `INVALID_DESTINATION`

```python
"INVALID_DESTINATION": ("destination", "nav_start")
```

⚠️ **Chặn bởi T20.** Chưa có nguồn phát thì:
- vẫn viết dòng ánh xạ (rẻ, đúng khi mã tồn tại)
- test đánh dấu `@pytest.mark.xfail(reason="T20: app luôn trả Success")`
- **không** báo D4 xong

#### Slot validator (cắm vào T04)

`destination` **từ chối động từ mệnh lệnh**: tắt, dừng, mở, gọi, phát, im lặng.

Ca vỡ: pending("Bạn muốn đi đâu?") + người dùng nói "tắt nhạc" → đi tìm đường
tới một nơi tên "tắt nhạc".

### 2.2 App Android

Thuộc **T20/P7**, ghi ở đây để biết ràng buộc:

- `NavigationStartHandler` phải **hoặc** kiểm địa điểm rồi phát
  `INVALID_DESTINATION`, **hoặc** server kính xoá câu chết trong `_ERROR_SPEECH`.
- Cùng cảnh: `NAVIGATION_NOT_FOUND`, `NAVIGATION_ALREADY_STOPPED` cũng không có
  nguồn phát.
- Chiều ngược: app **có** phát `NAVIGATION_START_FAILED` mà server kính **không**
  có câu → rơi vào `_GENERIC_FAILURE` (`result_speech.py:56`).

### 2.3 Server app · Firmware

**Không đụng.**

---

## 3. Hợp đồng đổi

Không đổi. Nhưng T20 sẽ chốt danh sách mã lỗi thật của `navigation_*` — ghi kết
quả vào `CONTRACTS.md`.

---

## 4. Test

### 4.1 Luồng 2 lượt — `tests/test_slots.py` (dùng chung)

```
test_nav_missing_destination_two_turns
  lượt 1 "chỉ đường đi"          → ask + pending(destination, nav_start)
  lượt 2 "Bưu điện Thành phố"    → nav_start, KHÔNG phải chat
                                  → pending bị xoá

test_nav_pending_ttl_120s
test_nav_pending_rejects_imperative        # T04 validator
  pending(destination) + "tắt nhạc"        → music_stop
```

### 4.2 Readback — `tests/test_navigation.py` (mới hoặc mở rộng)

```
test_ack_reads_destination_name            # D3
  ack CHỨA tên điểm đến, không phải "Đang mở chỉ đường."

test_low_confidence_reads_back_first
  slot_confidence=low → KHÔNG gọi host ở lượt này, chờ xác nhận

test_high_confidence_sends_immediately
  slot_confidence=high → gửi ngay, 1 lượt

test_readback_pending_is_confirm_kind      # TTL 25 s không phải 120 s
```

### 4.3 D4 — xfail cho tới khi có T20

```
@pytest.mark.xfail(reason="T20: NavigationStartHandler luôn trả Success")
test_invalid_destination_sets_pending
```

### 4.4 nav_stop — khoá hành vi đang đúng

```
test_stop_without_navigation_id_says_nothing_to_stop
test_stop_marks_inactive
test_stop_while_music_playing_only_stops_navigation     # B7, T03
```

### 4.5 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| "chỉ đường tới Bách Khoa" ở Hà Nội | mở đúng Bách Khoa Hà Nội (cần T07+A3) |
| Nói tên bị STT nghe sai | nghe được tên trong ack **trước khi** Maps mở |
| Đang chỉ đường, hỏi "phía trước có gì" | ra `describe_hazard`, không phải dừng chỉ đường (T04) |

---

## 5. DoD

```bash
pytest tests/test_navigation.py tests/test_slots.py -k nav -q
```

- [ ] `_ASK_DESTINATION` đã dời sang `slots.py`, không còn ở `navigation.py:5`
- [ ] Ack **có tên điểm đến**
- [ ] `readback = low_conf` chạy đúng cả hai nhánh
- [ ] Pending readback dùng `kind="confirm"` (25 s), không phải 120 s
- [ ] Validator từ chối động từ mệnh lệnh
- [ ] D4 đánh dấu `xfail` với lý do trỏ T20 — **không báo xong**
- [ ] Trạng thái file này giữ **PARTIAL** cho tới khi T20 chốt

---

## 6. Câu hỏi phải chốt

1. **App có kiểm địa điểm được không** (để `INVALID_DESTINATION` có nguồn)? Không
   thì xoá câu chết ở `result_speech.py:41` và bỏ dòng D4 tương ứng — thà không
   có còn hơn có mà không chạy.
2. **`readback` cho `destination` là `low_conf` hay `always`?** Đã chốt
   `low_conf`. Nhưng đi bộ sai đường nguy hiểm hơn gọi nhầm điện thoại — nếu
   thử thật thấy sai nhiều thì đổi, và ghi lại số đo.
