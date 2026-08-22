# T21 — Ngân sách độ trễ, deadline & quan sát được

| | |
|---|---|
| **Mã spec** | G1 G3 G5 G6 G9 · F10 · G8 (đổi nội dung) |
| **SPEC gốc** | mục 20, 27.7, 27.9 |
| **Repo đụng** | Server kính (đo trên bản có TLS của **T22**) |
| **Trạng thái** | READY (G3 chờ T17) |
| **Chặn bởi** | **T02** (hai khoản độ trễ chưa đếm) · **T22** (phải đo có TLS) · T17 (chỉ G3) |
| **Chặn** | — |

> Spec **không có một con số ngân sách nào**, và code **không có một timeout nào**
> trên lời gọi ngoài. Nghĩa là **không có định nghĩa "chậm"**, nên không phát
> hiện được lúc nào bị chậm đi.

---

## 1. Hiện trạng

`DETAILED_STAGE_LATENCY_BENCHMARK.md` đo được:

| Chặng | Thời gian |
|---|---|
| STT | 0.8–1.6 s |
| intent SetFit | **8 ms** |
| Gemini | 0.5–1.5 s |
| TTFB | 0.6–1.6 s |
| **tổng** | **3–6 s** |

### Ba vấn đề về chính con số

1. **Không có deadline nào** trên lời gọi ngoài → treo là treo im lặng.
2. 🔴 **Mọi số hiện có đo với `API_USE_TLS 0`** (README firmware §4 ghi rõ) —
   tức đo trên **một cấu hình không được phép phát hành** (xem T22).
3. 🔴 **Bảng TTFB không nhìn thấy hai khoản lớn nhất** — cả hai nằm ở đầu ra,
   sau khi TTFB đã tính xong (xem **T02**):
   - khoảng im **30 giây** cuối lượt nếu miếng kết thúc chunked không tới
   - tỉ lệ nhả TTS < 1.30× → board **đợi nhận xong hết mới phát**

---

## 2. Việc phải làm

### G1 — bảng ngân sách TTFB

| Đường | Mục tiêu | Ghi chú |
|---|---|---|
| `emergency_call` ack | **< 300 ms** | audio dựng sẵn, không LLM, không ảnh |
| `cancel` / `repeat` / stop | **< 300 ms** | không gọi mạng ngoài |
| trả lời pending tất định ("ừ", "số hai") | **< 400 ms** | không LLM, không ảnh |
| `contact_call` ack | **< 600 ms** | ack song song với API |
| `hazard` (theo lượt) | < 800 ms | |
| `chat` | < 1.0 s | |
| `ocr` / `space` / `find` / `money` | < 1.2 s | ⚠️ `ocr` xem mục 6 |

**Kèm: mọi lời gọi ngoài có deadline.** Quá deadline → nói một câu **dựng sẵn**,
không treo im lặng.

### G11 — dòng thứ hai của bảng, đo khác hẳn (từ T02)

```
tỉ lệ (giây tiếng)/(giây đồng hồ) ≥ 1.30×
đo từ chunk ĐẦU tới chunk CUỐI
```

TTFB đạt mà tỉ lệ này không đạt thì **người dùng vẫn không nghe gì** cho tới khi
sinh xong cả câu. Hai dòng phải cùng xanh.

### F10 — 🔴 đo **trên bản có TLS**

Chốt ngân sách trên bản `API_USE_TLS 0` là chốt trên một cấu hình không phát hành
được. **T22 phải xong trước khi chốt số G1.**

### G2 — không giữ lock trong lúc gọi LLM

Đã thiết kế ở **T03** (`generation`) và thi hành ở **T04**. Ở đây chỉ **đo**:

```
test: lock không bị giữ quá 5 ms (đo trực tiếp)
```

### G5 — câu cố định dựng sẵn audio

Thuộc **T06**. Ở đây chỉ kiểm: những lượt đó **TTS = 0 ms**.

### G6 — ack và API chạy **song song**

`contact_call` / `music_play`: phát ack **ngay khi resolve xong**, gửi host API
**đồng thời**. Idempotency (`action_id`) đã bảo vệ.

**Đừng nối tiếp** `handler → API → ActionResult → speech`.

> Bản mẫu đã có sẵn: `ActionRegistry.kt:424-440` (app) chạy SMS song song với
> cuộc gọi khẩn cấp, comment ghi rõ đã từng đo **một lần chờ 20 giây** vì làm
> tuần tự. Xem T09.

### G7 — thứ tự prompt cho prefix cache

Thuộc **T13**.

### G8 — 🔴 **ĐỔI NỘI DUNG**: không làm earcon phía server

`cueSent()` (firmware `audio_cues.cpp`) kêu **ngay khi nhả nút**, chạy trên core
1 song song với lúc core 0 chờ server (~0.94 s). **Earcon đã ở 0 ms sau khi nhả
nút** — sớm hơn mọi thứ server làm được.

Thêm earcon phía server → **bíp hai lần**.

Việc còn lại:
- bảo đảm câu trả lời **không đè lên** `cueSent()`
- **cân âm lượng** giữa hai bên

### G3 — STT streaming + intent suy đoán

SetFit chỉ **8 ms** nên chạy được trên **giả thuyết dở dang**:

```
partial "đọc chữ..."  → intent ổn định qua 2 partial liên tiếp
                      → khởi động ngay: xin ảnh tầng cao, mở kết nối, prefill prompt
STT final về          → chỉ còn phần sinh chữ
intent đổi ở final    → HUỶ việc đã khởi động
```

Ước tính **400–700 ms**.

⚠️ Làm **sau T17**, vì nó cần `audio.file.read()` (`app.py:483`) đổi thành đọc
theo chunk.

Cũng mở khoá **T09/21.5c**: dò từ khoá emergency trên partial STT.

### G9 — quan sát được

**Không có trace thì không phát hiện được hồi quy độ trễ.** Mỗi lượt log:

```
turn_id, device_id,
thời gian từng chặng (stt / intent / slot / api / ttfb),
intent, confidence, pending trước/sau, error_code
```

`turn_id` từ T01 làm khoá — cùng khoá với idempotency và barge-in.

---

## 3. Hợp đồng đổi

Không đổi. Ghi bảng G1 + dòng G11 vào `CONTRACTS.md` mục *Ngân sách độ trễ*, kèm
ghi chú **"đo trên bản có TLS"**.

---

## 4. Test

### 4.1 Ngân sách — `tests/test_latency_budget.py` (mới, `@pytest.mark.perf`)

```
test_p50_p95_per_intent                       # G1
  mỗi intent → p50/p95, FAIL BUILD nếu vượt bảng

test_emergency_ack_under_300ms                # ca an toàn
test_cancel_repeat_under_300ms
test_deterministic_pending_under_400ms
test_static_speech_turns_have_zero_tts        # G5
```

### 4.2 Deadline

```
test_every_external_call_has_deadline          # 🔴
  liệt kê mọi lời gọi ngoài → mỗi cái có timeout

test_hung_call_yields_prebuilt_sentence
  giả lập treo → PHẢI ra câu dựng sẵn, KHÔNG treo im lặng

test_deadline_does_not_leak_task
```

### 4.3 G2 — lock

```
test_lock_held_under_5ms                       # đo trực tiếp
test_llm_call_outside_lock
```

### 4.4 G6 — song song

```
test_ack_before_api_result
  contact_call → ack phát ra TRƯỚC khi host trả kết quả
test_api_called_concurrently_with_ack
```

### 4.5 G3 — STT streaming (sau T17)

```
test_speculative_intent_after_two_partials
test_speculative_work_cancelled_on_intent_change
test_final_intent_wins
```

### 4.6 G9 — trace

```
test_trace_has_all_stages
test_trace_keyed_by_turn_id
test_trace_records_pending_transition
```

### 4.7 Đo thật — không phải test

| Script | Ra file | Điều kiện |
|---|---|---|
| `tools/measure_budget.py` | `measurements/G1.md` | 🔴 **chạy trên bản TLS=1** |
| tỉ lệ nhả TTS (T02) | `measurements/G11.md` | |

---

## 5. DoD

```bash
pytest tests/test_latency_budget.py -m perf -q
python tools/measure_budget.py
```

- [ ] **T22 xong trước** — số đo trên bản `TLS=1`, ghi rõ trong file đo
- [ ] **T02 xong trước** — hai khoản đầu ra đã biết, không còn ẩn số 30 giây
- [ ] Bảng G1 có **số thật đo được** cho mọi dòng, kể cả `ocr`
- [ ] Dòng G11 (tỉ lệ ≥ 1.30×) cùng xanh với dòng TTFB
- [ ] **Mọi** lời gọi ngoài có deadline; treo → câu dựng sẵn
- [ ] Lock ≤ 5 ms, đo trực tiếp
- [ ] `contact_call` ack **trước** kết quả API
- [ ] **Không thêm earcon phía server** (G8) — có comment ghi rõ lý do
- [ ] Trace G9 đủ trường, khoá bằng `turn_id`
- [ ] CI **fail** khi vượt ngân sách (không chỉ cảnh báo)

---

## 6. Câu hỏi phải chốt

1. 🔴 **Ngân sách cho `ocr` là bao nhiêu?** Bảng G1 ghi < 1.2 s chung với
   space/find/money, nhưng T15/H1 **cố tình làm OCR chậm hơn** (bỏ `-lite`). Số
   này phải chốt riêng, nếu không thì T15 không nghiệm thu được. **Đây là câu hỏi
   mở số 3 của mục 25.**
2. 🔴 **Bật TLS rồi thì p95 là bao nhiêu?** Chưa đo (T22). Không có số này thì cả
   bảng G1 đang mô tả một cấu hình không phát hành được.
3. **CI có chạy được test perf không?** Máy CI chậm hơn máy dev → ngưỡng nào?
   Đề xuất: CI chỉ chạy ca "có deadline / không treo"; ngưỡng thời gian đo tay
   trên máy chuẩn, ghi vào `measurements/`.
