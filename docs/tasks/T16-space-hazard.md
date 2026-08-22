# T16 — Mô tả không gian (`space`) & cảnh báo vật cản (`hazard`)

| | |
|---|---|
| **Mã spec** | E5 · E6 |
| **SPEC gốc** | mục 5, mục 6, mục 7 |
| **Repo đụng** | Server kính |
| **Trạng thái** | READY |
| **Chặn bởi** | T05 (slot `focus`) |
| **Chặn** | — |

> Task nhỏ nhất trong bộ, và **một nửa của nó là cố ý không sửa gì**.
> Đọc mục 2.2 trước khi định "cải tiến" `hazard`.

---

## 1. Hiện trạng

### `space` — `handlers/describe_space.py`

`handle(image, command_text)` (`:69`) nhận `command_text` nhưng **không dùng**.

`_PROMPT` (`:15-67`) cố định, **đã qua nhiều vòng đo**:
- ngân sách **25–40 từ**
- **3 phần bắt buộc** theo thứ tự
- **6 điều cấm** — mỗi điều đến từ **một lần hỏng đo được** (comment `:6-12`)

**Vấn đề:** "Bên trái có gì" và "trước mặt có gì" ra **câu y hệt nhau**.

🔴 Nhưng **không được** chữa bằng cách dán `command_text` vào prompt — làm vậy là
**thổi bay ngân sách 40 từ và bộ luật thứ tự đã đo**.

### `hazard` — `handlers/describe_hazard.py`

`handle` (`:15`) bỏ qua `command_text`. `_PROMPT` (`:5-13`) cố định 1–2 câu, cấm
mô tả màu sắc và chi tiết thị giác.

**Vấn đề: KHÔNG CÓ. Đây là hành vi đúng.**

### `find` / `money` — ngoài phạm vi

| File | Trạng thái |
|---|---|
| `handlers/find_object.py:27` | **có** dùng `command_text` (`{command_text}` trong `_PROMPT` `:5`). Handler ảnh duy nhất làm đúng. |
| `handlers/read_money.py:20` | bỏ qua `command_text`. Đúng — mệnh giá là mệnh giá. |

**Hai chức năng này nằm ngoài spec. Không đổi.** Ghi ở đây để rõ phạm vi.

---

## 2. Việc phải làm

### 2.1 E5 — `space` nhận **một slot ràng buộc**, không nhận câu hỏi

```python
focus: "left" | "right" | "front" | "behind" | null
```

Trích ở intent (T05/A1), chèn thành **một dòng** vào `_PROMPT`.

**Giữ nguyên mọi luật** — ngân sách 40 từ, 3 phần, 6 điều cấm. Thêm **đúng một
bậc tự do có ích**.

```
focus = "left"  → "Chỉ mô tả phía BÊN TRÁI khung hình."
focus = null    → không chèn dòng nào (hành vi như hiện tại)
```

`focus = "behind"` → không có ảnh phía sau. Câu trả lời cố định
*"Tôi không quan sát được phía sau."* — **dựng sẵn audio** (T06/G5), không gọi
VLM, **0 ms**.

#### 🔴 Không đưa lịch sử hội thoại vào `space`

Ảnh mới mỗi lượt. "Cái ghế bên trái" của 30 giây trước có thể **đã không còn ở
đó** — mô tả cũ không phải context, nó là **thông tin sai**.

Đây là nguyên tắc xuyên suốt số 2 của spec: *cache thứ đứng yên (chữ trên giấy),
không bao giờ cache thứ di chuyển (không gian, vật cản)*.

Ghi thành **comment trong code** để lần refactor sau không ai "cải tiến" bằng
cách thêm `_recent_turns()` vào.

### 2.2 E6 — `hazard`: **KHÔNG ĐỔI LOGIC**, chỉ thêm comment

Thêm vào `handlers/describe_hazard.py`:

> Đây là chức năng an toàn: nó phải báo **mọi** vật cản trong khung hình. Nhét
> câu hỏi người dùng vào là làm model **thiên về thứ họ hỏi**, và **giảm báo cáo
> thứ họ không hỏi** — đúng cái sắp làm họ vấp.

Ghi rõ để lần refactor sau không ai "cải tiến" nó.

Cụ thể, `hazard` **không** nhận: `command_text` · `focus` · lịch sử · transcript
OCR · vị trí.

### 2.3 Phạm vi phần II

Spec đã ghi rõ: **cảnh báo vật cản thời gian thực** (vòng lặp nền, phát bíp)
**đã bị đưa ra khỏi kế hoạch**. `hazard` giữ nguyên dạng **theo lượt**.

---

## 3. Hợp đồng đổi

Không đổi. Nhưng bảng **F4** (T17) ghi cả hai dùng **640×480** — sau H0 (T15) thì
số thật là 1280×720 và thang quality là 0–63. Quy lại số ở T17.

---

## 4. Test

### 4.1 `space` — `tests/test_space_focus.py` (mới)

```
test_focus_left_changes_prompt               # E5
  focus="left" → prompt CÓ dòng ràng buộc bên trái
test_focus_null_prompt_unchanged             # E5
  focus=None → prompt GIỐNG HỆT bản hiện tại (so chuỗi)

test_left_and_front_give_different_answers   # ca vỡ hiện tại
  cùng ảnh, focus="left" vs "front" → prompt KHÁC nhau

test_prompt_rules_intact                     # 🔴 khoá
  ngân sách 25-40 từ · 3 phần bắt buộc · 6 điều cấm
  → VẪN CÒN ĐỦ sau khi thêm dòng focus

test_command_text_still_not_injected          # 🔴 khoá
  câu hỏi nguyên văn KHÔNG có trong prompt
  → chỉ có slot focus

test_behind_answers_without_vlm               # E5
  focus="behind" → câu dựng sẵn, KHÔNG gọi VLM

test_no_history_in_space_prompt               # 🔴 khoá nguyên tắc 2
  lịch sử có nội dung → prompt space VẪN không chứa
```

### 4.2 `hazard` — test **khoá không đổi**

```
test_hazard_ignores_command_text              # 🔴 E6
  hai câu hỏi khác nhau → prompt GIỐNG HỆT NHAU

test_hazard_ignores_focus
test_hazard_ignores_history
test_hazard_ignores_ocr_transcript
test_hazard_ignores_location

test_hazard_prompt_unchanged_from_baseline
  so với chuỗi baseline chép cứng trong test
  → ai đổi prompt phải đổi test và giải trình
```

Sáu test này **không** kiểm tính năng — chúng kiểm **rằng không ai thêm gì vào**.
Đó là điểm của E6.

### 4.3 `find` / `money` — khoá phạm vi

```
test_find_object_still_uses_command_text
test_read_money_still_ignores_command_text
```

### 4.4 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| "bên trái có gì" vs "trước mặt có gì", cùng chỗ đứng | **hai câu khác nhau** |
| "phía sau có gì" | nghe *"Tôi không quan sát được phía sau"* ngay, không chờ |
| Câu space bất kỳ | vẫn 25–40 từ, vẫn đủ 3 phần |
| Hỏi hazard nhiều kiểu khác nhau | câu trả lời **báo mọi vật cản**, không chỉ thứ vừa hỏi |

---

## 5. DoD

```bash
pytest tests/test_space_focus.py -q
```

- [ ] `space` nhận `focus`, **không** nhận `command_text` nguyên văn
- [ ] `focus=None` → prompt **giống hệt** bản hiện tại (test so chuỗi)
- [ ] Ngân sách 40 từ + 3 phần + 6 điều cấm còn nguyên
- [ ] `focus="behind"` trả câu dựng sẵn, 0 lời gọi VLM
- [ ] Comment "không đưa lịch sử vào space" có trong code
- [ ] `describe_hazard.py` **không đổi một dòng logic** — chỉ thêm comment E6
- [ ] 6 test khoá hazard xanh
- [ ] `find_object.py` / `read_money.py` **không bị đụng**

---

## 6. Câu hỏi phải chốt

1. **`focus` có cần "trên/dưới" không?** Hiện 4 hướng. "Trên đầu có gì" (cành
   cây, biển hiệu thấp) là ca thật với người khiếm thị — nhưng camera đeo đầu
   chụp ngang thì có thể không thấy. Đo trước khi thêm.
2. **`focus="behind"` — có nên gợi ý người dùng quay đầu không?** Câu hiện tại
   chỉ nói "không quan sát được". Thêm *"bạn quay đầu lại rồi hỏi tôi"* thì hữu
   ích hơn, nhưng dài hơn.
