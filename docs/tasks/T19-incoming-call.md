# T19 — Cuộc gọi đến (`call_incoming`)

| | |
|---|---|
| **Mã spec** | 21.8 · 26.9 |
| **SPEC gốc** | 21.8, 26.9 |
| **Repo đụng** | **cả 4** — Server kính · Server app · App Android · Firmware |
| **Trạng thái** | READY — nhưng **bắt đầu từ con số không ở mọi tầng** |
| **Chặn bởi** | **T18** (kênh SSE) · T03 (pending phải giữ nguyên) · T04 (ưu tiên) |
| **Chặn** | — |

> **Đây là event từ điện thoại, không phải intent từ người dùng.** Mọi cơ chế
> hiện có trong repo đều bắt đầu từ nút bấm — task này đi ngược chiều đó ở cả
> bốn tầng.

---

## 1. Hiện trạng

**Không có gì.** Ghi rõ để không ai tưởng là sửa cái đang có:

| Tầng | Trạng thái |
|---|---|
| App Android | ❌ chưa có `TelephonyCallback`, chưa xin `READ_PHONE_STATE`, chưa có đường đẩy event tự phát lên host (26.9) |
| Server app | ❌ `services/action_callbacks.py` **từ chối** callback không có `request_id` đã đăng ký (*"Callback arrived for unregistered request_id"*) → event tự phát **cần đường riêng** |
| Server kính | ❌ không có handler `call_incoming`, không có kênh downlink |
| Firmware | ❌ board chỉ phát tiếng khi có người bấm nút |

---

## 2. Việc phải làm

### 2.1 Ưu tiên & tương tác với trạng thái đang chạy

```
ưu tiên: DƯỚI emergency_call, TRÊN mọi thứ khác
```

```
TTS đang chạy   → cắt/duck NGAY, không xếp hàng đợi
                  (câu space 40 từ mà đợi đọc xong thì chuông tắt rồi)

pending đang mở → 🔴 GIỮ NGUYÊN
                  chuông là ngắt quãng, KHÔNG phải người dùng đổi ý
```

Vế thứ hai là chỗ dễ làm sai nhất: mọi cơ chế khác trong repo đều **xoá pending**
khi có việc mới. Ở đây thì **không**.

### 2.2 Cửa sổ intent 15 giây

```
mở cửa sổ 15 s: call_answer | call_reject
  "nghe máy" / "nghe" / "trả lời"  → answer
  "từ chối" / "không nghe" / "bỏ"  → reject
hết chuông → đóng cửa sổ

call_ended → xoá state, KHÔNG đọc gì
```

`call_ended` không đọc gì: chuông tắt rồi mà máy còn nói *"cuộc gọi đã kết
thúc"* là tiếng ồn vô ích.

### 2.3 Câu báo — ghép ba mảnh

```
"Có cuộc gọi từ "  +  [TÊN]  +  " đang gọi."
 ↑ dựng sẵn           ↑ tổng hợp 150–300 ms   ↑ dựng sẵn
```

**Cache TTS theo `contact_id`** → lần thứ hai cùng người là **0 ms**. Hoặc dựng
sẵn top-20 contact lúc ghép máy (dùng `contact_list` của T08/P1).

```
không có trong danh bạ → "Số lạ, đuôi bốn năm sáu."   (đọc TỪNG chữ số)
trùng tên              → "Mẹ, đuôi bảy tám chín, đang gọi."
```

### 2.4 🔴 Riêng tư

Đọc tên to giữa chỗ đông người là **lộ thông tin**. Người khiếm thị không biết
xung quanh có ai đang nghe.

Thêm vào Preferences API của host:

```
announce_caller: "name" | "number_only" | "ring_only"
mặc định: "name"
```

Cùng nguyên tắc với luật đọc đuôi số ở T08/D7.

### 2.5 Việc từng repo

| Repo | Việc |
|---|---|
| **App Android** | `TelephonyCallback` bắt `RINGING` · xin `READ_PHONE_STATE` + `READ_CONTACTS` · `POST /api/v1/device/event` |
| **Server app** | forward event sang server kính, **tách khỏi luồng `request_id`** — `action_callbacks.py` hiện từ chối callback không đăng ký, nên event tự phát cần đường riêng |
| **Server kính** | kênh SSE (T18/F6) + handler `call_incoming` + cửa sổ intent 15 s |
| **Firmware** | nhận `call_incoming` trên kênh SSE, phát tiếng **lúc không ai bấm nút** — đường mới trong `audio_service.cpp` (27.6) |

---

## 3. Hợp đồng đổi

**Ba hợp đồng mới.** Ghi đủ vào `CONTRACTS.md`:

```jsonc
// 1. App → Server app  (MỚI, tách khỏi luồng request_id)
POST /api/v1/device/event
{ "device_id": "...", "type": "call_incoming",
  "caller": { "contact_id": "...", "name": "Mẹ", "number_tail": "456" } }

// 2. Server app → Server kính  (MỚI)
POST /internal/device-events        // KHÔNG đi qua /internal/action-results
{ ... như trên ... }

// 3. Server kính → Firmware  (qua SSE, T18)
{ "type": "call_incoming", "caller": {...} }

// 4. Preferences (host)  — MỞ RỘNG
{ "announce_caller": "name" | "number_only" | "ring_only" }
```

Số điện thoại đầy đủ **không rời khỏi điện thoại** — chỉ `number_tail` (3–4 chữ
số cuối), cùng luật với T08.

---

## 4. Test

### 4.1 Server kính — `tests/test_incoming_call.py` (mới)

```
test_cuts_tts_within_200ms                    # 🔴 mục 23
  đang đọc câu 40 từ + chuông → cắt trong <= 200 ms
  → KHÔNG xếp hàng đợi

test_pending_survives_incoming_call           # 🔴 ca dễ làm sai nhất
  pending(contact_name) mở + chuông
  → xử lý xong, pending CÒN NGUYÊN

test_emergency_beats_incoming_call
  chuông + "gọi cấp cứu" → emergency thắng

test_incoming_call_beats_everything_else
  chuông + nhạc đang phát → chuông thắng

test_intent_window_15s
  "nghe máy" trong 15 s  → call_answer
  "nghe máy" sau 15 s    → KHÔNG phải call_answer
test_window_closes_when_ringing_stops

test_call_ended_says_nothing
  call_ended → 0 câu phát ra
```

### 4.2 Câu báo & riêng tư

```
test_known_contact_reads_name
test_unknown_number_reads_digits              # "Số lạ, đuôi bốn năm sáu"
  → đọc TỪNG chữ số, không đọc liền
test_duplicate_name_adds_tail                 # "Mẹ, đuôi bảy tám chín"
test_never_reads_full_number                  # 🔴 riêng tư

test_announce_caller_number_only
test_announce_caller_ring_only                # KHÔNG đọc tên
test_announce_caller_default_is_name
```

### 4.3 Cache TTS

```
test_tts_cached_per_contact_id
  lần 2 cùng người → 0 ms tổng hợp
test_static_parts_prebuilt
  "Có cuộc gọi từ " và " đang gọi." nằm trong tập dựng sẵn (T06/G5)
```

### 4.4 Server app — đường riêng

```
test_device_event_does_not_require_request_id  # 🔴
  event tự phát KHÔNG bị action_callbacks từ chối
test_device_event_forwarded_to_glasses_server
```

### 4.5 Thủ công — 🔴 bắt buộc, không giả lập hết được

| Kịch bản | Đạt khi |
|---|---|
| Gọi vào lúc kính đang đọc câu dài | cắt gần như tức thì, nghe được tên người gọi |
| Gọi vào lúc đang có pending mở | sau khi xử lý xong, hỏi lại đúng câu cũ |
| Nói "nghe máy" | máy bắt máy |
| Nói "từ chối" | máy từ chối |
| Không nói gì, để chuông tắt | không có câu thừa nào |
| Số lạ | nghe đuôi số, **không nghe số đầy đủ** |
| Đặt `ring_only`, ở chỗ đông người | **không nghe tên ai cả** |

---

## 5. DoD

```bash
pytest tests/test_incoming_call.py -q
```

- [ ] **T18 xong trước** — không có kênh SSE thì task này không chạy được
- [ ] Cắt TTS ≤ 200 ms, đo được
- [ ] **Pending còn nguyên** sau cuộc gọi đến — có test
- [ ] Cửa sổ intent 15 s, đóng khi hết chuông
- [ ] `call_ended` không phát câu nào
- [ ] Số đầy đủ **không bao giờ** rời khỏi điện thoại, không bao giờ được đọc
- [ ] `announce_caller` đủ 3 mức, mặc định `name`
- [ ] Server app có **đường riêng** cho event tự phát, không đi qua `request_id`
- [ ] Đã thử tay đủ 7 kịch bản 4.5

---

## 6. Câu hỏi phải chốt

1. **Ai làm trước — app hay server?** Cả bốn tầng đều từ số không. Đề xuất: app
   phát event trước (dễ kiểm bằng log host), server kính giả lập event để phát
   triển song song.
2. **Cắt TTS hay duck (giảm âm)?** Cắt thì mất câu đang đọc; duck thì nghe chồng.
   Cần thử bằng tai.
3. **Cửa sổ 15 s có đủ không?** Chuông thường 20–30 s. 15 s để người dùng nghĩ
   có ít quá với người khiếm thị đang đi bộ?
4. **`announce_caller` lưu ở đâu?** Preferences API của host chưa có trường này.
   Ai thêm?
5. **Board có phát được tiếng khi không ai bấm nút không?** 27.6 nói đây là đường
   mới trong `audio_service.cpp` — file mà kiến trúc firmware gọi là *"file DUY
   NHẤT biết trình tự"*. Rủi ro cao nhất của task.
