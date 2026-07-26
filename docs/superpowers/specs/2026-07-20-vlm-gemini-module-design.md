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


def ask_text(text: str, prompt: str) -> str:
    return client.generate_text(prompt, text)
```

Hai hàm export:

- `ask(image, task, command_text="")` — tác vụ có ảnh, prompt build nội bộ
  theo `task` (dùng thẳng hằng số có sẵn ở `schemas.Intent`: `Intent.OCR`,
  `Intent.FIND`, `Intent.MONEY`, `Intent.SPACE` — không tạo enum mới trùng
  lặp).
- `ask_text(text, prompt)` — hàm generic thuần text-to-text, **không** build
  prompt nội bộ theo task; bên gọi tự truyền `prompt` (chỉ dẫn xử lý) và
  `text` (nội dung cần xử lý), Gemini trả lại text. Dùng cho ca hiện tại: OCR
  đọc ảnh ra text thô, rồi gọi `ask_text` để dịch, nhưng hàm này không giới
  hạn chỉ để dịch — bất kỳ tác vụ text-to-text nào sau này cũng gọi được qua
  đây mà không cần sửa `models/vlm`.

### `prompts.py`

Map `task` → hàm build prompt (Vietnamese), giữ đúng yêu cầu response đã ghi ở
README (ngắn gọn, định hướng hành động, không giả định người nghe nhìn được):

- `OCR`: đọc toàn bộ chữ trong ảnh, trả về nguyên văn (không dịch — dịch là
  bước riêng, xem phần "Sửa handler `ocr`" bên dưới).
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
- Thêm `generate_text(prompt: str, text: str) -> str`: gọi `generate_content`
  chỉ với nội dung text (ghép `prompt` + `text`), không kèm ảnh — dùng chung
  client/model, cùng cơ chế raise lỗi như trên.
- Raise `VLMError` (định nghĩa trong `client.py`, export qua `__init__.py`) khi:
  API lỗi (exception từ SDK), hoặc response rỗng/không có `.text`. Áp dụng cho
  cả `generate()` và `generate_text()`.
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

`find_object.py` (`Intent.FIND`), `read_money.py` (`Intent.MONEY`),
`describe_space.py` (`Intent.SPACE`) còn 1 dòng logic, gọi thẳng `vlm.ask`, xóa
TODO/kết quả giả:

```python
# handlers/find_object.py
from models import vlm
from schemas import Intent, Result

def handle(image: bytes, command_text: str) -> Result:
    return Result(speech=vlm.ask(image, Intent.FIND, command_text))
```

### Sửa handler `ocr` (2 bước)

`ocr.py` giữ nguyên logic quyết định raw-vs-translate (không chuyển vào
`models/vlm`), nhưng thay kết quả giả bằng gọi Gemini thật qua 2 bước — bước 1
luôn đọc ảnh ra text thô (`vlm.ask`), bước 2 chỉ chạy khi cần dịch
(`vlm.ask_text`):

```python
# handlers/ocr.py
from models import vlm
from schemas import Intent, Result

_TRANSLATE_PROMPT = "Dịch đoạn văn bản sau sang tiếng Việt, ngắn gọn, tự nhiên:"

def handle(image: bytes, command_text: str) -> Result:
    raw = command_text.lower()
    no_translate = "nguyên văn" in raw or "chuyên ngành" in raw
    text = vlm.ask(image, Intent.OCR, command_text)
    if no_translate:
        return Result(speech=text)
    return Result(speech=vlm.ask_text(text, _TRANSLATE_PROMPT))
```

## Testing

- `tests/test_handlers_ai.py`: sửa lại — monkeypatch `models.vlm.ask` và
  `models.vlm.ask_text`, assert handler gọi đúng tham số và bọc đúng vào
  `Result`. Cho `ocr`: assert khi `no_translate=True` chỉ gọi `ask`, không gọi
  `ask_text`; khi cần dịch thì gọi cả hai, `ask_text` nhận đúng text thô từ
  `ask`.
- `tests/test_vlm_prompts.py` (mới): test `prompts.build()` trực tiếp — mỗi
  task (`OCR`, `FIND`, `MONEY`, `SPACE`) trả prompt hợp lệ (non-empty, chứa
  `command_text` nếu cần). OCR không còn branch raw/translate ở tầng này.
- `tests/test_vlm_client.py` (mới): mock `google-genai` client — test
  `client.generate()` và `client.generate_text()` trả text khi thành công,
  raise `VLMError` khi response rỗng hoặc SDK raise exception. Không gọi
  network thật trong test.

## Ngoài phạm vi

- Không đổi `pipeline/stt.py`, `pipeline/tts.py`, `pipeline/intent.py`,
  `pipeline/router.py` — interface không đổi (handler vẫn `handle(image,
  command_text) -> Result`).
- Không xử lý streaming response, không cache kết quả Gemini.
- Không thêm retry logic khi API lỗi — lỗi propagate ngay, fallback TTS đã lo.
