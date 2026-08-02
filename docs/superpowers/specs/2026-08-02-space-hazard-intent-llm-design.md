# Tách space/hazard + chuyển intent detection sang LLM

## Vấn đề

`handlers/describe_space.py` hiện gộp một chức năng duy nhất: mô tả không
gian theo hướng **cảnh báo an toàn di chuyển** (vật cản, lối đi, cấm tả màu
sắc/thẩm mỹ). Không có chức năng mô tả không gian đầy đủ (đồ vật, bố cục, màu
sắc, chữ trên biển báo) để người dùng hiểu khung cảnh xung quanh hoặc xác
nhận vị trí — cần thiết cho tính năng GPS định hướng sau này.

Đồng thời, `pipeline/intent.py` phân loại ý định bằng so khớp từ khóa cứng
(`_RULES`). Cách này không mở rộng được khi số intent tăng và không hiểu
được câu nói ngoài các cụm từ đã liệt kê sẵn.

## Thay đổi

### 1. Tách `describe_space` thành 2 hướng chức năng

- `handlers/describe_space.py`: đổi `_PROMPT` sang mô tả không gian đầy đủ —
  đồ vật, bàn ghế, bố cục, màu sắc, đọc chữ trên biển báo/bảng hiệu nếu có.
  Mục tiêu giúp người dùng hiểu khung cảnh và xác nhận có đang ở đúng nơi cần
  đến không. Trả lời 2-4 câu tiếng Việt tự nhiên. Giữ nguyên chữ ký
  `handle(image, command_text) -> Iterator[str]` và cách gọi
  `vlm.generate_stream`.

- `handlers/describe_hazard.py` (mới): nhận nguyên `_PROMPT` cảnh báo cũ của
  `describe_space.py` — tập trung lối đi, vật cản, khoảng cách theo hướng giờ
  đồng hồ hoặc trái/phải, cấm tả màu sắc/chi tiết thị giác. Cùng cấu trúc
  `handle()` như trên.

- `schemas.py`: thêm `Intent.HAZARD = "hazard"`.

- `pipeline/router.py`: import `describe_hazard`, thêm
  `Intent.HAZARD: describe_hazard` vào `_HANDLERS`.

### 2. Intent detection chuyển sang LLM (Gemini)

- `pipeline/intent.py`: bỏ `_RULES` và so khớp từ khóa. `detect(text)`:
  1. Chuỗi rỗng/toàn khoảng trắng → trả `Intent.UNKNOWN` ngay, **không** gọi
     Gemini (giữ tối ưu hiện tại: STT không nghe ra gì thì không có gì để
     phân loại).
  2. Ngược lại, gọi `models.vlm.generate_json(prompt, schema=_SCHEMA)` — dùng
     lại nguyên client Gemini đã có, không thêm client mới. `prompt` liệt kê
     mô tả ngắn từng nhãn (`ocr`, `find`, `money`, `space`, `hazard`, `chat`)
     kèm câu lệnh người dùng cần phân loại. `schema` ép trả JSON
     `{"intent": <enum 6 giá trị trên>}`.
  3. `vlm.VLMError` (lỗi mạng, response rỗng...) hoặc giá trị `intent` trả về
     không nằm trong 6 nhãn hợp lệ → trả `Intent.UNKNOWN`. Không đoán bừa khi
     không chắc, cùng triết lý với `read_money`.
  4. Giá trị hợp lệ → trả thẳng nhãn đó (đã khớp tên `Intent.*`).

  `Intent.UNKNOWN` không nằm trong enum của schema — model không tự chọn
  được nhãn này, chỉ code gán khi input rỗng hoặc lỗi.

### 3. Test

- `tests/test_intent.py`: viết lại toàn bộ, mock `models.vlm.generate_json`
  thay vì test câu chữ trực tiếp qua rule cứng:
  - Chuỗi rỗng/khoảng trắng → `UNKNOWN`, **assert không gọi** `generate_json`.
  - `generate_json` trả `{"intent": "hazard"}` → `detect()` trả
    `Intent.HAZARD` (và tương tự cho 5 nhãn còn lại).
  - `generate_json` raise `VLMError` → `UNKNOWN`.
  - `generate_json` trả nhãn lạ/thiếu field → `UNKNOWN`.
- `tests/test_router.py`: thêm case `("hazard", "describe_hazard")` vào
  `test_router_correctly_maps_all_intents`; thêm assertion tương tự
  `test_space_handler_literal_in_dict` cho `describe_hazard`.
- `tests/test_handlers_ai.py`: thêm `describe_hazard` vào vòng lặp streaming
  cùng `find_object`, `describe_space`.

## Ngoài phạm vi

- Không đổi `schemas.Result` hay giao thức HTTP/WS hiện có.
- Không thêm cơ chế cache/rate-limit cho lệnh gọi classify — chấp nhận thêm
  độ trễ mạng mỗi lệnh thoại, đổi lấy khả năng hiểu ngôn ngữ tự nhiên linh
  hoạt hơn so khớp từ khóa.
- Không giữ song song rule-based làm fallback khi LLM lỗi — lỗi thì trả
  `UNKNOWN` (xin nói lại), không fallback về logic cũ.
- Không đổi `Intent.CHAT` default-khi-không-khớp: giờ `chat` là một nhãn
  LLM tự chọn, không còn là "khớp rule nào cũng trượt" như trước.
- Không nối tính năng GPS định hướng — chỉ chuẩn bị prompt mô tả không gian
  để hướng đó dùng được sau này.
