# T13 — Trò chuyện (`chat`), tìm kiếm & lịch sử dùng chung

| | |
|---|---|
| **Mã spec** | B4 · E4 · G7 |
| **SPEC gốc** | mục 8 (phần prompt/lịch sử), E4, G7 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY (E4 chờ T14) |
| **Chặn bởi** | **T07** (vị trí) · T03 (lịch sử dùng chung) · **T14** (chỉ E4) |
| **Chặn** | — |

> Phần **vị trí hỏng** của mục 8 nằm ở **T07**, không ở đây. Task này lo phần
> còn lại của `handlers/chat.py`: lịch sử, transcript OCR, thứ tự prompt.

---

## 1. Hiện trạng

`handlers/chat.py`:

| Dòng | Thứ |
|---|---|
| `:17` | `_SYSTEM_PROMPT` — dài, đã tinh chỉnh: cấm markdown, cố định xưng "tôi"/"bạn", 1-3 câu, cấm bịa |
| `:71` | `_SEARCH_INSTRUCTION` — `CHAT_ALWAYS_SEARCH=1` gắn Google Search vào **mọi** lượt, model tự quyết có tra hay không |
| `:86` | `_SEARCH_UNAVAILABLE_INSTRUCTION` — tra hỏng (429) → nói thẳng là chưa tra được |
| `:226` | `_HISTORY: deque(maxlen=config.CHAT_HISTORY_TURNS)`, TTL `CHAT_HISTORY_TTL_SECONDS=600` (`config.py:138`) |
| `:246` | `_recent_turns()` |
| `:257` | `_location_text()` — **T07 lo** |
| `:276` | `_build_prompt()` — thứ tự: system(+time+search+location) → lịch sử → câu vừa nói |
| `:299` | `_remember()` — gom mảnh trong lúc stream rồi ghi lịch sử khi xong |

### Ba chỗ hỏng

1. **Lịch sử chỉ ghi lượt `chat`, chỉ dùng cho prompt `chat`.** "Vừa nãy tôi đặt
   xe đi đâu?" → chịu.

2. **Không có transcript OCR trong prompt.** "Khái niệm này là gì" đi về `chat`,
   không về `ocr`. `_build_prompt` (`:276`) dựng prompt **không có transcript,
   không có ảnh** → trỏ "chữ này", "mục kia" thành vô nghĩa.

3. **Thứ tự prompt chưa tối ưu cho prefix cache.** `_SYSTEM_PROMPT.format()`
   nhét `now` / `search` / `location` **vào giữa** phần bất biến → mỗi lượt đổi
   một chữ là **trượt prefix cache** toàn bộ system prompt.

---

## 2. Việc phải làm

### B4 — lịch sử dùng chung, ghi **cả lượt action**

Chuyển `_HISTORY` (`:226`) vào `Session` của T03. Mọi handler ghi vào.

Lượt action ghi dạng gọn, không ghi nguyên payload:

```python
history.append(("đặt xe tới Bách Khoa",
                "đã mở Grab, xe máy 32-38 nghìn"))
```

`_remember()` (`:299`) đang làm đúng cách cho `chat` — tách nó thành helper dùng
chung, đừng viết lại ở 6 handler.

Giữ `maxlen` và TTL 600 s. Ghi thêm lượt action → cùng `maxlen` nghĩa là **ít
lượt chat hơn được giữ**. Cân nhắc nâng `CHAT_HISTORY_TURNS` (`config.py`) —
nhưng mỗi lượt là token, đo trước.

### E4 — bơm transcript OCR vào prompt `chat`

Đọc `session.last_ocr` (T14/E2), chèn vào `_build_prompt` (`:276`):

> Người dùng vừa nhờ đọc một văn bản. Nội dung: "{…}". Nếu câu hỏi trỏ vào văn
> bản này ("chữ này", "khái niệm đó", "mục kia") thì trả lời dựa vào nó. **Không
> liên quan thì bỏ qua.**

🔴 **Câu "bỏ qua nếu không liên quan" là BẮT BUỘC.** Thiếu nó thì hỏi "mấy giờ
rồi" cũng bị kéo về tờ giấy.

Chỉ chèn khi `last_ocr` còn hạn (TTL ~5 phút, T14).

### G7 — đặt prompt đúng thứ tự cho prefix cache

```
BẤT BIẾN trước:   system prompt · few-shot · luật xưng hô, cấm markdown
BIẾN THIÊN cuối:  giờ · vị trí · transcript OCR · lịch sử · câu vừa nói
```

Sai thứ tự → trượt prefix cache → **+200–400 ms mỗi lượt chat**.

Nghĩa là `_SYSTEM_PROMPT.format(now=…, search=…, location=…)` (`:277-287`) phải
tách: phần cố định thành hằng số thật, phần động thành các khối nối **sau**.

⚠️ `_SYSTEM_PROMPT` đã qua nhiều vòng tinh chỉnh (comment `:13-16`, `:186-190`).
Tách chuỗi **không được đổi nội dung một chữ nào** — chỉ đổi chỗ nối. Test so
sánh chuỗi kết quả trước/sau khi tách phải bằng nhau (trừ thứ tự).

### Ràng buộc từ T07 — nhất quán vị trí

`_SEARCH_INSTRUCTION` (`:71`) bảo model *"tra địa điểm quanh người dùng"*. Nếu
`_location_text()` trả khối "chưa có vị trí" (C1) thì **hai khối này mâu thuẫn
nhau trong cùng một prompt**.

→ `_search_instruction()` (`:270`) phải biết trạng thái vị trí: không có vị trí
→ bỏ vế "quanh người dùng".

Đây là ca bịa quán phở, và nó **chỉ sửa được khi làm cả hai chỗ**.

---

## 3. Hợp đồng đổi

Không đụng repo khác.

---

## 4. Test

### 4.1 Lịch sử dùng chung — `tests/test_chat.py` (mở rộng)

```
test_action_turn_recorded                    # B4
  đặt xe → lịch sử có lượt đó

test_chat_prompt_contains_action_turn        # B4, ca dùng thật
  "vừa nãy tôi đặt xe đi đâu" → prompt CÓ lượt đặt xe

test_history_shared_across_handlers
test_history_ttl_600s
test_history_maxlen_respected
test_history_isolated_per_device             # T03
```

### 4.2 E4 — transcript OCR

```
test_ocr_transcript_injected                 # E4
  last_ocr còn hạn → prompt chat CÓ transcript

test_ocr_transcript_has_ignore_clause        # 🔴 bắt buộc
  prompt CHỨA câu "không liên quan thì bỏ qua"

test_unrelated_question_not_dragged_to_text  # ca vỡ nếu thiếu câu trên
  last_ocr có + hỏi "mấy giờ rồi"
  → câu trả lời KHÔNG nói về tờ giấy

test_expired_ocr_not_injected
  last_ocr quá 5 phút → KHÔNG chèn
```

### 4.3 G7 — thứ tự prompt

```
test_invariant_prefix_is_stable              # G7, ca chốt
  hai lượt khác nhau (khác giờ, khác vị trí, khác lịch sử)
  → N ký tự ĐẦU của prompt GIỐNG HỆT NHAU

test_prompt_content_unchanged_after_split    # an toàn khi tách chuỗi
  tập hợp các câu trong prompt trước/sau khi tách = nhau
```

### 4.4 Nhất quán vị trí (chung với T07)

```
test_no_location_no_nearby_search_instruction
  cache rỗng → prompt KHÔNG đồng thời có
    "chưa lấy được vị trí"  VÀ  "tra địa điểm quanh người dùng"
```

### 4.5 Khoá hành vi đang đúng

```
test_no_markdown_in_prompt_rules
test_first_person_pronouns_fixed
test_search_failure_says_so                  # nhánh 429
```

### 4.6 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| Nhờ đọc tờ giấy, rồi hỏi "khái niệm đó là gì" | trả lời **dựa vào tờ giấy**, không hỏi lại |
| Ngay sau đó hỏi "mấy giờ rồi" | trả lời giờ, **không** nhắc tờ giấy |
| Đặt xe rồi hỏi "vừa nãy tôi đặt đi đâu" | trả lời đúng |
| Đo TTFB 10 lượt chat liên tiếp | không thấy +200-400 ms do trượt cache |

---

## 5. DoD

```bash
pytest tests/test_chat.py -q
```

- [ ] Lịch sử nằm trong `Session`, ghi **cả lượt action**
- [ ] `_remember()` thành helper dùng chung, không copy sang 6 handler
- [ ] E4 chèn transcript **kèm câu "bỏ qua nếu không liên quan"**
- [ ] Tiền tố bất biến của prompt **giống hệt nhau giữa hai lượt** (test đo được)
- [ ] Nội dung `_SYSTEM_PROMPT` **không đổi một chữ** sau khi tách
- [ ] Không còn ca prompt vừa nói "chưa có vị trí" vừa bảo "tra quanh người dùng"
- [ ] Đã thử tay ca "hỏi mấy giờ sau khi đọc giấy" — không bị kéo về tờ giấy

---

## 6. Câu hỏi phải chốt

1. **`CHAT_HISTORY_TURNS` có phải nâng không?** Thêm lượt action vào cùng deque
   thì lượt chat bị đẩy ra sớm hơn. Đo token trước khi nâng.
2. **Lượt action ghi chi tiết đến đâu?** Ghi "đặt xe tới Bách Khoa, 32-38 nghìn"
   hay chỉ "đặt xe"? Chi tiết hơn thì trả lời được nhiều câu hơn, nhưng tốn token
   mỗi lượt chat sau đó.
3. **Prefix cache của Gemini có thật sự ăn theo tiền tố ký tự không?** G7 giả
   định vậy. Đo bằng `measurements/G7.md` trước khi tách một prompt đã tinh chỉnh
   kỹ — nếu không ăn thì việc tách là rủi ro không đổi lấy gì.
