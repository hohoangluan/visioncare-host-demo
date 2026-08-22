# T05 — Phân loại ý định & schema slot

| | |
|---|---|
| **Mã spec** | A1 A2 A3 · B3 B5 |
| **SPEC gốc** | mục 2, mục 18 (ràng buộc thứ tự) |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY (A3 chờ T07) |
| **Chặn bởi** | T03 (pending) · **T07** (chỉ riêng A3 — cần vị trí chạy được) |
| **Chặn** | T08 T10 T11 T12 T16 |

---

## 1. Hiện trạng

`pipeline/intent.py` — hai tầng:

| Tầng | Chỗ | Thời gian |
|---|---|---|
| 1. SetFit cục bộ | `intent_local.classify`, ONNX int8 | ~8 ms |
| 2. Gemini | `config.GEMINI_INTENT_MODEL` (`config.py:121`, `gemini-3.1-flash-lite`) | ~0.9 s |

Tầng 1 đủ chắc (`confidence` + `margin`) **và** nhãn nằm trong `_PARAM_FREE`
(`:28`) → trả ngay, không hỏi Gemini.

`_context_block()` (`:234`) chèn trạng thái thiết bị vào prompt.
`_apply_state()` (`:267`) áp cùng bộ luật ở đường cục bộ.
Schema slot ở `_SCHEMA` (`:62`).

### Năm chỗ hỏng

1. **Không có "hệ thống vừa hỏi gì" trong prompt.** Câu trả lời trần trụi
   ("Sơn Tùng", "đúng rồi", "Bưu điện", "mẹ") không có chỗ bám. Chỉ có đúng
   **một luật hardcode** vá cho ca ca sĩ (quanh `intent.py:184-187` — kiểm lại
   số dòng thật trước khi sửa).
2. **SetFit chặn đường.** "Sơn Tùng M-TP" nhiều khả năng ra `chat` với
   confidence cao → `chat` nằm trong `_PARAM_FREE` → trả về ngay, **Gemini
   không bao giờ được hỏi**. Pending kẹt vĩnh viễn.
3. **Prompt không có vị trí hiện tại.** "Bách Khoa" là Hà Nội hay TP.HCM?
   `chat` **có** được cấp vị trí (`handlers/chat.py:276-287`), còn
   `nav_start`/`ride_quote` — hai nhãn **cần vị trí nhất** — thì không.
4. **Prompt không nói text đến từ STT.** STT là Zipformer-vi 30M int8
   (`pipeline/stt.py:11`), sai tên riêng liên tục. Prompt trích slot không có
   một chữ nào bảo model **sửa lỗi nhận dạng** — nó đang trích span nguyên văn,
   tức **chép lại đúng lỗi rồi đem đi query**.
5. **Không có nhãn thoát.** Không có `cancel` ("thôi bỏ đi") và `repeat`
   ("gì cơ", "nói lại đi"). Người khiếm thị cần cả hai.

---

## 2. Việc phải làm

### A1 — đổi schema params (`intent.py:62` `_SCHEMA`)

```python
"song_title", "artist", "song_is_specific",
"destination", "destination_raw",
"slot_confidence": {"enum": ["high", "low"]},
"focus": {"enum": ["left", "right", "front", "behind"]},
```

Giữ `song` cũ **làm alias trong lúc chuyển** — `handlers/music.py` và host
contract (`endpoint.md:131`) vẫn dùng chuỗi `"Tên - Ca sĩ"`.

`destination_raw` giữ nguyên văn STT; `destination` là bản đã sửa. Cần cả hai để
log được tỉ lệ sửa đúng/sai.

`slot_confidence` là đầu vào của readback (T06/D3) — thiếu nó thì D3 không chạy.

### A2 — khối chỉ dẫn sửa lỗi STT

Chèn vào prompt trích slot:

> Câu lệnh do máy nhận dạng giọng nói tiếng Việt (model nhỏ) ghi lại. TÊN RIÊNG
> bị nghe sai rất nhiều. Khi trích slot, SỬA về dạng đúng mà bạn tin người dùng
> định nói, đừng chép lại lỗi: "Bát Khoa" → "Bách Khoa". Không sửa được thì giữ
> nguyên và đặt `slot_confidence = "low"`. Không bịa số nhà, tên đường, tên
> album không nghe thấy.

Ba mệnh lệnh trong đó đều bắt buộc: **sửa** · **thú nhận khi không sửa được** ·
**cấm bịa**. Bỏ vế thứ ba thì model điền số nhà nó tưởng tượng ra.

### A3 — bơm vị trí vào `_context_block()` (`:234`)

Một dòng, dùng lại `chat._location_text()` (`handlers/chat.py:257`).

⚠️ **Phụ thuộc T07.** Vị trí đang hỏng 100 % (42/42 nhịp) — bơm một chuỗi rỗng
vào prompt là công vô ích. T07 xong thì A3 mới có nghĩa.

Vị trí rỗng → **không** chèn dòng nào, đừng chèn "không rõ vị trí" vào prompt
intent (khác với `chat`, nơi C1 cố ý chèn khối cảnh báo để cấm bịa).

### B3 — có pending thì **bỏ qua SetFit**, đi thẳng Gemini

```
Hệ thống VỪA HỎI: "{câu hỏi}". Câu vừa nói nhiều khả năng là câu trả lời.
Nếu đúng → intent = {intent}, trích slot "{slot}".
Nếu là câu huỷ → cancel.
Nếu là việc hoàn toàn khác → phân loại bình thường, bỏ qua pending.
```

SetFit **không được train cho câu trả lời trần trụi**; ép nó quyết chính là
nguồn bug. +0.9 s nhưng chỉ ở lượt hiếm.

Câu cuối ("việc hoàn toàn khác → bỏ qua pending") là **bắt buộc** — thiếu nó thì
mọi câu trong 120 s sau một câu hỏi đều bị kéo về slot đó.

**Ngoại lệ:** pha 2 của T04 (câu trả lời tất định "ừ", "số hai") **không** đi
Gemini — ngân sách < 400 ms (T21/G1). B3 chỉ áp cho pha 4 (điền slot mở).

### B5 — thêm nhãn `cancel` và `repeat`

| Nhãn | Câu ví dụ | Xử lý |
|---|---|---|
| `cancel` | "thôi bỏ đi", "không cần nữa", "huỷ" | xoá pending, nói "Đã huỷ." |
| `repeat` | "gì cơ", "nói lại đi", "sao cơ" | đọc lại `pending.question`, hoặc câu trả lời trước |

Cả hai: **không mạng ngoài, không LLM, không ảnh** (bảng F4). Ngân sách < 300 ms
(T21/G1). Nghĩa là chúng phải bắt được ở **regex/SetFit**, không đợi Gemini.

Thêm vào `_LABELS` (`:54`) và `_PARAM_FREE` (`:28`).

---

## 3. Hợp đồng đổi

Không đụng repo khác. Nhưng `_SCHEMA` là hợp đồng nội bộ giữa intent và **6
handler** — ghi bảng slot → handler nào đọc vào `CONTRACTS.md`.

---

## 4. Test

### 4.1 Unit — `tests/test_intent.py` (sửa) + `tests/test_intent_slots.py` (mới)

Có thể test **không gọi Gemini thật**: mock `generate_json`, kiểm **prompt** và
kiểm **hậu xử lý**.

```
test_schema_has_new_slots                    # A1
  song_title · artist · song_is_specific · destination · destination_raw
  · slot_confidence · focus

test_song_alias_still_works                  # A1, giai đoạn chuyển
  model trả "song" cũ → handler vẫn chạy

test_prompt_contains_stt_correction_block    # A2
  prompt CÓ cả ba vế: sửa · thú nhận · cấm bịa

test_prompt_contains_location_when_available # A3
  cache vị trí có → prompt intent CÓ vị trí
test_prompt_omits_location_when_empty        # A3
  cache rỗng → KHÔNG chèn dòng nào (khác chat/C1)

test_pending_skips_setfit                    # B3, ca chính
  pending(song_title) mở + "Sơn Tùng"
  → intent_local.classify KHÔNG được gọi
  → Gemini ĐƯỢC gọi, prompt chứa câu hỏi vừa hỏi

test_pending_prompt_allows_unrelated         # B3, vế bắt buộc
  pending(song_title) + "gọi cho mẹ" → contact_call

test_deterministic_answer_skips_gemini       # ngoại lệ pha 2
  pending(confirm) + "ừ" → KHÔNG gọi Gemini

test_cancel_label                            # B5
test_repeat_label                            # B5
test_cancel_repeat_are_param_free            # phải nằm trong _PARAM_FREE
```

### 4.2 Bảng ca STT sai — chạy được không cần mạng

`tests/fixtures/stt_errors.md` **(mới)** — bảng ca thật đã nghe sai, dùng chung
với T08 và T10:

| STT ra | Định nói | Slot | Kỳ vọng |
|---|---|---|---|
| "Bát Khoa" | Bách Khoa | destination | sửa được, `slot_confidence=high` |
| "Nơi này có anh Sơn Tùng" | (nuốt "của") | song/artist | tách được artist |
| "Bưu điện Thành Phố" | — | destination | giữ nguyên |
| (tên lạ không đoán được) | — | — | `slot_confidence=low`, **không bịa** |

Test này cần Gemini thật → đánh dấu `@pytest.mark.llm`, chạy tay, kết quả ghi
vào `docs/tasks/measurements/A2.md`.

### 4.3 Test cũ phải sửa

| File | Vì sao |
|---|---|
| `tests/test_intent.py` | schema đổi, thêm 2 nhãn |
| `tests/test_intent_local.py` | `_PARAM_FREE` đổi |

---

## 5. DoD

```bash
pytest tests/test_intent.py tests/test_intent_local.py tests/test_intent_slots.py -q
pytest -m llm tests/test_intent_slots.py -q     # chạy tay, cần API key
```

- [ ] Schema có đủ 7 slot mới, `song` còn alias
- [ ] Khối A2 có **cả ba vế**, kiểm bằng test trên chuỗi prompt
- [ ] A3 chỉ chèn khi có vị trí thật — **đánh dấu BLOCKED nếu T07 chưa xong**
- [ ] B3: có pending → SetFit **không** được gọi (test kiểm bằng mock, không đọc log)
- [ ] `cancel` / `repeat` bắt được **không cần Gemini** (đo: < 300 ms)
- [ ] Bảng ca STT sai có kết quả đo thật trong `measurements/A2.md`

---

## 6. Câu hỏi phải chốt

1. **`destination_raw` có dùng thật không, hay chỉ để log?** Nếu chỉ log thì cân
   nhắc bỏ khỏi schema và ghi vào trace (T21/G9) — mỗi trường trong schema là
   thêm token mỗi lượt.
2. **B3 +0.9 s có chấp nhận được ở lượt trả lời không?** Bảng G1 (T21) đặt
   "trả lời pending tất định < 400 ms" cho pha 2. Pha 4 chưa có số. Chốt trước
   khi đo T21.
3. **Ngưỡng `confidence`/`margin` của SetFit có phải chỉnh lại** sau khi thêm 2
   nhãn không? Chưa đo.
