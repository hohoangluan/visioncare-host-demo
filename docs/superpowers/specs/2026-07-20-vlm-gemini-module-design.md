# Module `models/vlm` — Gemini-backed vision module

## Bối cảnh

4 handler (`ocr`, `find_object`, `read_money`, `describe_space`) hiện là stub, chờ
"nối API vision" (xem README, `docs/superpowers/specs/2026-07-19-blind-assist-audio-server-design.md`).
Đây đều là tác vụ ảnh + văn bản → văn bản (vision-language), nên gộp thành một
module `models/vlm` dùng Gemini API, thay vì đặt tên `models/llm`.

## Mục tiêu

Cung cấp một điểm vào duy nhất trong `models/vlm` để 4 handler gọi, nhận
`(image, task, command_text)` trả về câu tiếng Việt sẵn sàng cho TTS. Toàn bộ
logic build prompt, gọi Gemini API, xử lý lỗi nằm gọn trong `models/vlm`; bên
gọi (handlers) không biết gì về Gemini, prompt, hay SDK.

## Kiến trúc

```
models/vlm/
  __init__.py   # public: ask(image: bytes, task: str, command_text: str = "") -> str
  prompts.py    # internal: build prompt theo task
  client.py     # internal: gọi google-genai, trả text hoặc raise VLMError
```

### `__init__.py`

```python
def ask(image: bytes, task: str, command_text: str = "") -> str:
    prompt = prompts.build(task, command_text)
    return client.generate(prompt, image)
```

Đây là **hàm duy nhất được export**. Handler chỉ import `from models import vlm`
và gọi `vlm.ask(...)`. `task` dùng thẳng hằng số có sẵn ở `schemas.Intent`
(`Intent.OCR`, `Intent.FIND`, `Intent.MONEY`, `Intent.SPACE`) — không tạo enum
mới trùng lặp.

### `prompts.py`

Map `task` → hàm build prompt (Vietnamese), giữ đúng yêu cầu response đã ghi ở
README (ngắn gọn, định hướng hành động, không giả định người nghe nhìn được):

- `OCR`: đọc chữ trong ảnh. Nếu `command_text` chứa "nguyên văn" hoặc
  "chuyên ngành" → prompt yêu cầu đọc thô, không dịch. Ngược lại → đọc và dịch
  sang tiếng Việt. (Logic raw/translate chuyển từ `handlers/ocr.py` vào đây.)
- `FIND`: yêu cầu Gemini trả lời 1 câu có hướng (giờ hoặc trái/phải), khoảng
  cách ước lượng, vật cản nếu có — theo đúng ví dụ đã ghi trong
  `handlers/find_object.py` hiện tại.
- `MONEY`: đọc mệnh giá tiền trong ảnh, trả lời ngắn gọn.
- `SPACE`: miêu tả không gian phía trước phục vụ định hướng di chuyển (fallback
  intent).

Mỗi hàm build nhận `command_text` để có thể tham chiếu câu lệnh gốc của người
dùng khi cần (vd OCR).

### `client.py`

- Client `google-genai` khởi tạo lazy (singleton module-level), dùng
  `config.GEMINI_API_KEY` và `config.GEMINI_MODEL`.
- Nhận `image: bytes`, tự nhận diện mime type qua magic number (JPEG: `FF D8`,
  PNG: `89 50 4E 47`), mặc định `image/jpeg` nếu không khớp.
- Gọi `generate_content(prompt, image_part)`, trả `.text.strip()`.
- Raise `VLMError` (định nghĩa trong `client.py`, export qua `__init__.py`) khi:
  API lỗi (exception từ SDK), hoặc response rỗng/không có `.text`.
- Không tự catch/nuốt lỗi ở bất kỳ tầng nào trong `models/vlm` — để lỗi
  propagate lên handler rồi lên `app.py`, nơi đã có `except Exception` bao trùm
  biến lỗi thành câu TTS fallback ("Có lỗi xảy ra, vui lòng thử lại"). Do đó
  `models/vlm` không cần biết gì về `Result`/TTS.

## Config

`config.py`:
- Đổi `VISION_API_KEY` → `GEMINI_API_KEY`.
- Thêm `GEMINI_MODEL` (default `"gemini-2.5-flash"`).

`requirements.txt`: thêm `google-genai`.

## Sửa 4 handler

Mỗi handler còn 1 dòng logic, gọi thẳng `vlm.ask`, xóa TODO/kết quả giả:

```python
# handlers/ocr.py
from models import vlm
from schemas import Intent, Result

def handle(image: bytes, command_text: str) -> Result:
    return Result(speech=vlm.ask(image, Intent.OCR, command_text))
```

Tương tự cho `find_object.py` (`Intent.FIND`), `read_money.py` (`Intent.MONEY`),
`describe_space.py` (`Intent.SPACE`).

## Testing

- `tests/test_handlers_ai.py`: sửa lại — monkeypatch `models.vlm.ask` (qua
  `handlers.ocr.vlm.ask` etc., hoặc `monkeypatch.setattr`), assert handler gọi
  đúng `task`/`command_text` và bọc đúng vào `Result`. Không còn assert nội
  dung "dịch"/"nguyên văn" ở tầng handler (logic đó đã chuyển vào
  `prompts.py`).
- `tests/test_vlm_prompts.py` (mới): test `prompts.build()` trực tiếp — OCR
  raw vs translate theo từ khóa, các task khác trả prompt hợp lệ (non-empty,
  chứa `command_text` nếu cần).
- `tests/test_vlm_client.py` (mới): mock `google-genai` client — test
  `client.generate()` trả text khi thành công, raise `VLMError` khi response
  rỗng hoặc SDK raise exception. Không gọi network thật trong test.

## Ngoài phạm vi

- Không đổi `pipeline/stt.py`, `pipeline/tts.py`, `pipeline/intent.py`,
  `pipeline/router.py` — interface không đổi (handler vẫn `handle(image,
  command_text) -> Result`).
- Không xử lý streaming response, không cache kết quả Gemini.
- Không thêm retry logic khi API lỗi — lỗi propagate ngay, fallback TTS đã lo.
