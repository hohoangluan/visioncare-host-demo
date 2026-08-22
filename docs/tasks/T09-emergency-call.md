# T09 — Gọi khẩn cấp (`emergency_call`)

| | |
|---|---|
| **Mã spec** | D5 · 21.5 · P11 |
| **SPEC gốc** | mục 10, 21.5, 26.8 |
| **Repo đụng** | Server kính · App Android |
| **Trạng thái** | READY |
| **Chặn bởi** | T06 (assert D5) · T04 (ưu tiên tuyệt đối) |
| **Chặn** | — |

> 🔴 **Nguyên tắc xuyên suốt số 3 của spec:**
> *`emergency_call` không đi qua bất kỳ bước xác minh nào. Ngoại lệ tuyệt đối,
> phải viết tường minh trong code chứ không để rơi vào mặc định.*
>
> Task này phần lớn là **khoá lại hành vi đúng**, không phải thêm tính năng.
> Mỗi dòng code thêm vào đây phải trả lời được: *nó có làm chậm cuộc gọi cấp cứu
> không?*

---

## 1. Hiện trạng

### Server kính — **đúng, đừng sửa**

`handlers/phone.py:50-65`:

```python
number = params.get("emergency_number")
payload = {}
if number:
    payload["number"] = number
yield from run_action("emergency_call", "api/v1/service/emergency/call",
                      payload, ack=_EMERGENCY_ACK, ...)
```

Thiếu `emergency_number` → **vẫn gửi lệnh** với payload rỗng, host dùng số đã
cấu hình sẵn. Đúng.

Câu trấn an dựng sẵn audio (`phone.py:18-24` `STATIC_SPEECH`) — với nhóm này
dựng sẵn là **bắt buộc**, không phải tối ưu.

### App Android — **tốt hơn mức spec đòi**

`ActionRegistry.kt:392` đọc số khẩn cấp từ `SharedPreferences` (đặt ở màn hình
Overview / Safety). Chưa cài → `EMERGENCY_CONTACT_NOT_CONFIGURED`, và người dùng
chỉ biết điều đó **vào đúng lúc gọi cấp cứu**.

Phần còn lại (`:424-440`): SMS kèm link vị trí chạy **song song** với cuộc gọi,
có timeout riêng, không chặn tiếng chuông. Comment ghi rõ đã từng đo một lần chờ
**20 giây** vì làm tuần tự.

→ Đây là **bản mẫu của G6** (ack và API chạy song song). Giữ nguyên, và trỏ T21
về đây.

### Ba chỗ hở

1. **Nhận nhầm = gọi nhầm cấp cứu.** Không confirm là đúng cho ca thật, nhưng
   không có đường thoát nào sau khi gửi.
2. **Phát hiện chỉ dựa SetFit.** Class này phải ưu tiên **recall hơn precision**.
3. **Phải đợi STT xong (~1.2 s)** mới phát hiện được.

---

## 2. Việc phải làm

### D5 — assert, không phải logic

Đã mô tả ở **T06**. Ở đây chỉ nhắc lại điều kiện nghiệm thu:

```python
# handlers/slots.py
assert "emergency_number" not in SLOTS
```

Và emergency **không** đi qua:
- readback / chờ xác nhận (T06/D3)
- pending / hỏi lại (T03)
- gate chất lượng ảnh (`pipeline/image_quality.py:106` `reject_reason`) —
  emergency **không gửi ảnh** (bảng F4), nên không được chờ ảnh
- barge-in queue của T04 — emergency là **bước 1**, trên mọi thứ

### 21.5 — cửa sổ huỷ, **không phải câu hỏi**

```
đã gửi action → mở cửa sổ huỷ 3–5 s
              → earcon + "nói huỷ để dừng"
              → KHÔNG phải câu hỏi
              → KHÔNG chặn action (action đã gửi rồi; huỷ = gửi abort)
```

Ba chữ "không" ở trên là toàn bộ thiết kế. Biến nó thành *"bạn có chắc không?"*
là phá đúng thứ task này bảo vệ.

Cần host/app có đường **abort** cuộc gọi đang quay số. `endpoint.md` hiện
**không có**. Ghi vào mục 6 là câu hỏi mở, và **đừng chặn phần còn lại** vì nó.

### 21.5b — phát hiện phải ưu tiên recall

```
cổng từ khoá độ chính xác cao   OR   classifier(p > ngưỡng THẤP)
```

Bỏ sót nguy hiểm hơn báo thừa, **vì báo thừa đã có cửa sổ huỷ đỡ**. Hai vế này
đi cùng nhau — làm vế recall mà chưa có cửa sổ huỷ là tăng gọi nhầm.

Danh sách từ khoá phải viết ra và test được: "cấp cứu", "cứu tôi", "gọi cứu
thương", "một một bốn", "khẩn cấp"…

### 21.5c — dò trên **partial STT**

Đường emergency hiện chặn ở chỗ khác: phải đợi STT xong (~1.2 s).

Thêm dò từ khoá trên partial STT — **phụ thuộc T21/G3** (STT streaming). Chưa có
G3 thì ghi PARTIAL, đừng chặn.

### P11 — kiểm số khẩn cấp **lúc ghép máy**, không phải lúc gọi

App: `emergency_contact` chưa cài → nhắc **một lần bằng giọng nói** lúc ghép
kính / lúc khởi động.

Biết vào lúc đang ngã là biết quá muộn.

Liên quan **T23/P10** (`capabilities_get`) — nếu làm T23 thì P11 là một trường
trong đó, không cần cơ chế riêng.

---

## 3. Hợp đồng đổi

| Việc | Trạng thái |
|---|---|
| `POST /api/v1/service/emergency/call` (`endpoint.md:~230`) | **không đổi** |
| Đường **abort** cuộc gọi khẩn cấp | **CHƯA CÓ** — cần cho 21.5, xem mục 6 |
| `emergency_contact` trong `capabilities_get` | thuộc T23 |

---

## 4. Test

### 4.1 Khoá an toàn — `tests/test_slots.py` (dùng chung T06)

Ba test này là **khoá**, không phải test tính năng. Ai xoá phải giải trình:

```
test_emergency_number_not_in_slots
test_emergency_never_asks_back
  emergency_call thiếu MỌI param → VẪN gửi lệnh
test_emergency_never_reads_back
  slot_confidence = "low" → VẪN gửi ngay, không chờ xác nhận
```

### 4.2 Ưu tiên tuyệt đối — `tests/test_router_priority.py` (dùng chung T04)

```
test_emergency_beats_everything
  pending mở + nhạc đang phát + "gọi cấp cứu" → emergency_call

test_emergency_while_music_playing            # ca bug hiện tại
  fast-bypass cũ nuốt câu này thành music_stop

test_emergency_while_pending_open
  pending(contact_name) mở + "cứu tôi" → emergency, pending KHÔNG nuốt

test_emergency_skips_image_gate
  ảnh mờ / không có ảnh → VẪN chạy, không bị reject_reason chặn

test_emergency_does_not_wait_for_image         # bảng F4
```

### 4.3 Phát hiện — `tests/test_emergency_detect.py` (mới)

```
test_keyword_gate_hits            × N từ khoá
  "cấp cứu" · "cứu tôi" · "gọi cứu thương" · "một một bốn" · "khẩn cấp"

test_low_threshold_classifier
  p thấp hơn ngưỡng thường → VẪN ra emergency (recall > precision)

test_false_positive_has_cancel_window          # 21.5
  báo thừa → có cửa sổ huỷ, không phải ngõ cụt
```

### 4.4 Cửa sổ huỷ — `tests/test_emergency_cancel.py` (mới)

```
test_cancel_window_is_not_a_question
  câu phát ra KHÔNG có dấu hỏi, KHÔNG chờ trả lời mới gửi action

test_action_already_sent_before_window
  action đã ra khỏi server TRƯỚC khi cửa sổ mở

test_say_cancel_within_window_sends_abort
  "huỷ" trong 3-5 s → gửi abort
  ⚠️ xfail nếu chưa có endpoint abort

test_silence_within_window_does_nothing
  không nói gì → cuộc gọi tiếp tục
```

### 4.5 Ngân sách — thuộc T21 nhưng ca này phải có

```
test_emergency_ack_under_300ms                 # G1
  audio dựng sẵn, không LLM, không ảnh
```

### 4.6 Thủ công — bắt buộc, không bỏ qua được

| Kịch bản | Đạt khi |
|---|---|
| Nói "gọi cấp cứu" trong lúc nhạc đang phát | máy quay số, **không** tắt nhạc rồi thôi |
| Nói lúc đang có pending mở | quay số ngay |
| Nói nhầm rồi nói "huỷ" trong 3 s | dừng được |
| Chưa cài số khẩn cấp | được nhắc **lúc ghép máy**, không phải lúc gọi |

---

## 5. DoD

```bash
pytest tests/test_slots.py tests/test_router_priority.py tests/test_emergency_detect.py tests/test_emergency_cancel.py -k emergency -q
```

- [ ] `handlers/phone.py:50-65` **không đổi logic** (chỉ thêm comment nếu cần)
- [ ] Assert D5 có trong `slots.py` kèm comment lý do
- [ ] Emergency bỏ qua: readback · pending · gate ảnh · hàng đợi barge-in
- [ ] Cổng từ khoá có danh sách viết ra, test được
- [ ] Cửa sổ huỷ **không phải câu hỏi**, action gửi trước khi cửa sổ mở
- [ ] Ack đo được < 300 ms
- [ ] Đã thử tay đủ 4 kịch bản 4.6
- [ ] Không có bước nào mới được thêm vào đường tới hạn — **so số trước/sau**

---

## 6. Câu hỏi phải chốt

1. **Có endpoint abort cuộc gọi khẩn cấp không?** `endpoint.md` không có. Không
   có thì 21.5 chỉ dừng được ở mức "không quay số tiếp", không rút lại được cuộc
   gọi đã nối. Chặn nửa sau của 21.5.
2. **Cửa sổ huỷ 3 s hay 5 s?** Ngắn thì người đang hoảng không kịp; dài thì cuộc
   gọi thật bị trì hoãn. Cần thử với người dùng.
3. **Từ khoá nào vào cổng recall cao?** Danh sách phải do người Việt đọc duyệt —
   "một một bốn" đọc thành số hay thành chữ tuỳ STT.
4. **P11 làm riêng hay gộp vào T23?** Gộp thì gọn hơn, nhưng T23 chưa chắc được
   ưu tiên. Emergency thì không nên chờ.
