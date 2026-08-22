# T14 — OCR: ngữ cảnh & cache transcript

| | |
|---|---|
| **Mã spec** | E1 E2 E3 E4 |
| **SPEC gốc** | mục 4 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY |
| **Chặn bởi** | T03 (session giữ `last_ocr`) |
| **Chặn** | T13 (E4) |

> Task này lo **ngữ cảnh** của OCR — làm gì với chữ **sau khi** đã đọc được.
> Chuyện **đọc được hay không** (model nào, ảnh xoay ngược, chữ quá nhỏ) nằm ở
> **T15**. Hai task độc lập, **làm song song được**.

---

## 1. Hiện trạng

`handlers/ocr.py:6-19` — hai phép kiểm tra chuỗi rồi **vứt `command_text`**:

```python
raw = command_text.lower()
if "nguyên văn" in raw:      mode = ocr.Mode.RAW
elif "chuyên ngành" in raw:  mode = ocr.Mode.SPECIALIZED
else:                        mode = ocr.Mode.NORMAL
return ocr.read_stream(image, mode)
```

`models/ocr/prompts.py:39` — `build(mode)` **không nhận `command_text`**. Prompt
luôn là "Đọc toàn bộ chữ trong ảnh".

`models/ocr/__init__.py:24` — `read_stream` là generator đẩy thẳng ra TTS. Có
mốc quy ước `NO_TEXT_SENTINEL = "KHONG_CO_CHU"` (`prompts.py:11`) cho ảnh không
có chữ.

Đây là **một lượt gọi Gemini VLM**, không phải PaddleOCR — không có bounding box,
không có cấu trúc dòng.

### Bốn chỗ hỏng

1. **"Đọc dòng thứ 2" → đọc cả trang.** Model **chưa từng được hỏi**. Không kết
   luận được nó làm tốt hay không — nó không nhận được câu hỏi.

2. **Chữ đọc xong là mất.** Không có transcript ở đâu.

3. 🔴 **Bẫy ảnh mới.** Lượt sau kính **chụp ảnh mới**. Người dùng đã hạ tay,
   nghiêng máy, xê dịch tờ giấy. OCR lại ảnh mới → **số dòng khác** → "dòng thứ
   2" của lượt trước không còn là dòng thứ 2. Người khiếm thị **không có cách
   nào biết** hai lần chụp lệch nhau.

4. **"Khái niệm này là gì" đi về `chat`, không về `ocr`.** →  **T13/E4**.

---

## 2. Việc phải làm

### E1 — `build(mode, command_text)`

`models/ocr/prompts.py:39`. Thêm khối:

> Người dùng hỏi: "{…}". Nếu câu hỏi chỉ định một phần cụ thể (dòng thứ mấy,
> đoạn nào, mục nào), chỉ đọc đúng phần đó. Không chỉ định thì đọc toàn bộ.

Hai vế đều cần: **chỉ đọc phần đó** và **không chỉ định thì đọc toàn bộ**. Bỏ vế
sau thì model tự cắt bớt khi câu hỏi mơ hồ.

`handlers/ocr.py` truyền `command_text` xuống thay vì vứt.

Giữ nguyên hai phép kiểm chuỗi cho `mode` (RAW / SPECIALIZED) — chúng đang chạy
đúng, và mode là thứ khác với câu hỏi.

### E2 — cache transcript trong session

```python
session.last_ocr = {"text": ..., "taken_at": ...}   # TTL ~5 phút
```

Gom mảnh **trong lúc stream**, giống `handlers/chat.py:299` `_remember` — dùng
lại helper đó (T13/B4 đã tách ra dùng chung).

Không gom được (stream lỗi giữa chừng) → **không ghi cache**, thà không có còn
hơn có một nửa văn bản mà người dùng tưởng là đủ.

`NO_TEXT_SENTINEL` → **không** ghi cache.

### E3 — 🔴 câu hỏi tiếp theo trả lời **trên text đã cache, bỏ hẳn ảnh**

Một lượt Gemini **text-only**:

- **nhanh hơn nhiều** (không upload ảnh, không xử lý ảnh)
- **tránh bẫy ảnh mới** (vấn đề 3) — đây mới là lý do chính

Bảng F4 (T17) đã ghi: `ocr` follow-up = **không gửi ảnh**.

Điều kiện đi đường E3:
```
last_ocr còn hạn  AND  câu hỏi trỏ vào văn bản đã đọc
```

Vế thứ hai do intent quyết (T05), không đoán bằng chuỗi.

Hết hạn hoặc câu hỏi không trỏ vào văn bản → đường cũ (chụp ảnh mới, OCR lại).

### E4 — bơm transcript vào prompt `chat`

Thuộc **T13**. Ghi ở đây để biết `last_ocr` có **hai** người tiêu thụ:
`ocr` follow-up (E3) và `chat` (E4).

---

## 3. Hợp đồng đổi

Không đụng repo khác. Nhưng **liên quan T17/F4**: dòng "`ocr` follow-up → không
gửi ảnh" trong bảng F4 chỉ có nghĩa khi E2/E3 đã xong. Ghi phụ thuộc đó vào
`CONTRACTS.md`.

---

## 4. Test

### 4.1 Unit — `tests/test_ocr_context.py` (mới)

Mock `vlm.generate_stream`, không gọi Gemini thật.

```
test_command_text_reaches_prompt             # E1
  "đọc dòng thứ hai" → prompt CHỨA câu hỏi

test_prompt_has_both_clauses                 # E1
  prompt có CẢ "chỉ đọc đúng phần đó" VÀ "không chỉ định thì đọc toàn bộ"

test_mode_detection_unchanged
  "nguyên văn" → RAW · "chuyên ngành" → SPECIALIZED

test_transcript_cached_after_stream          # E2
  stream xong → session.last_ocr có text đầy đủ

test_no_cache_on_sentinel                    # E2
  KHONG_CO_CHU → last_ocr vẫn None

test_no_cache_on_partial_stream              # E2
  stream lỗi giữa chừng → KHÔNG ghi cache một nửa

test_followup_uses_text_only                 # 🔴 E3, ca chính
  last_ocr còn hạn + "dòng hai nói gì"
  → gọi Gemini KHÔNG kèm ảnh
  → ảnh trong request bị BỎ QUA hoàn toàn

test_followup_faster_than_full_ocr           # E3
  đếm: không có bước upload/encode ảnh

test_expired_cache_falls_back_to_image       # E3
  last_ocr quá 5 phút → chụp lại, OCR lại

test_unrelated_question_does_not_use_cache
  last_ocr có + "phía trước có gì" → describe_hazard, không đụng cache
```

### 4.2 Ca bẫy ảnh mới — test **quan trọng nhất**

```
test_line_number_stable_across_turns         # 🔴 vấn đề 3
  lượt 1: ảnh A, transcript 5 dòng
  lượt 2: "đọc dòng thứ 2", ảnh B KHÁC (lệch khung, 4 dòng)
  → PHẢI trả dòng 2 của transcript A
  → KHÔNG được OCR lại ảnh B
```

Đây là ca người khiếm thị **không có cách nào tự phát hiện** khi nó sai. Test
này là lý do tồn tại của E3.

### 4.3 Test cũ phải kiểm

`tests/test_models_ocr.py` — `build()` đổi chữ ký. Thêm tham số có default thì
test cũ vẫn chạy, nhưng nên thêm ca mới.

### 4.4 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| Đọc một trang 6 dòng, rồi "đọc dòng thứ 3" | đọc đúng dòng 3, **không đọc lại cả trang** |
| Lượt 2 cố tình **xê tờ giấy đi** | vẫn ra dòng 3 của lần chụp đầu |
| Chờ 6 phút rồi hỏi tiếp | chụp lại, và **nói cho người dùng biết** là đang đọc lại |
| Hỏi "phía trước có gì" ngay sau khi đọc giấy | ra hazard, không dính transcript |

---

## 5. DoD

```bash
pytest tests/test_ocr_context.py tests/test_models_ocr.py -q
```

- [ ] `build(mode, command_text)` nhận và dùng câu hỏi, **cả hai vế** có trong prompt
- [ ] `handlers/ocr.py` không còn vứt `command_text`
- [ ] `session.last_ocr` ghi khi thành công, **không ghi** khi sentinel / stream lỗi
- [ ] Follow-up đi **text-only**, có test đếm được là không có ảnh
- [ ] Ca "bẫy ảnh mới" (4.2) xanh
- [ ] TTL 5 phút, hết hạn → đường cũ
- [ ] Dùng lại helper `_remember` của T13, không copy code

---

## 6. Câu hỏi phải chốt

1. **TTL transcript 5 phút có đủ không?** Đọc một trang dài rồi hỏi từng mục có
   thể lâu hơn. Nhưng để lâu quá thì người dùng đã cầm tờ khác. Chưa đo.
2. **Hết hạn thì có nói cho người dùng biết không?** Đề xuất: **có** — *"tôi
   chụp lại nhé"* — vì im lặng chụp lại là quay về đúng bẫy ảnh mới.
3. **Ai quyết "câu hỏi này trỏ vào văn bản đã đọc"?** Đề xuất: intent (T05), có
   nhãn/slot riêng. Đoán bằng chuỗi ở handler là lặp lại sai lầm của
   `_names_an_artist` (T12).
