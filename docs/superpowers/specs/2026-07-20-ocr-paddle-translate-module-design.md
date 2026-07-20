# Module `models/ocr` — PaddleOCR detect + dịch qua `models/vlm`

## Bối cảnh

`handlers/ocr.py` hiện là stub (xem `docs/superpowers/specs/2026-07-19-blind-assist-audio-server-design.md`).
Đã có spec `docs/superpowers/specs/2026-07-20-vlm-gemini-module-design.md` (đã
commit) định nghĩa `models/vlm` để 4 handler gọi Gemini vision trực tiếp
(image → text) cho cả nhận diện lẫn xử lý ngôn ngữ.

Với riêng OCR, thay vì để Gemini tự đọc chữ từ ảnh, chuyển sang dùng
**PaddleOCR chạy local** để nhận diện text thật, rồi chỉ dùng LLM cho bước
dịch (text → text), không đưa ảnh vào bước dịch. Đây là amend so với spec vlm
cũ: `models/vlm` sẽ có thêm public function `generate_text()` — hàm tương tác
văn bản chung (prompt vào, text ra), tách biệt khỏi `ask()` (vision, dành cho
`find`/`money`/`space`, chưa build trong task này). `models/ocr` tự xây prompt
dịch của riêng nó và không đụng vào nội bộ `models/vlm`, chỉ gọi qua
`generate_text()`.

## Mục tiêu

Cung cấp một điểm vào duy nhất `models/ocr.read(image, mode) -> str`: nhận
ảnh + mode, nội bộ tự lo detect + dịch, trả câu tiếng Việt sẵn sàng cho TTS.
Bên gọi (`handlers/ocr.py`) không biết gì về PaddleOCR hay Gemini.

## Kiến trúc

```
models/ocr/
  __init__.py   # public: read(image: bytes, mode: str = Mode.NORMAL) -> str
                # class Mode: NORMAL / SPECIALIZED / RAW
  engine.py     # internal: PaddleOCR singleton (lazy), extract_text(image: bytes) -> str
  prompts.py    # internal: build(text: str, mode: str) -> str

models/vlm/
  __init__.py   # public: generate_text(prompt: str) -> str   (mới, ngoài phạm vi: ask())
  client.py     # internal: google-genai client (lazy singleton), generate(prompt, image=None) -> str
```

### `models/ocr/__init__.py`

```python
from models import vlm
from . import engine, prompts


class Mode:
    NORMAL = "normal"
    SPECIALIZED = "specialized"
    RAW = "raw"


def read(image: bytes, mode: str = Mode.NORMAL) -> str:
    raw_text = engine.extract_text(image)
    if not raw_text:
        return "Không tìm thấy chữ trong ảnh."
    if mode == Mode.RAW:
        return raw_text
    return vlm.generate_text(prompts.build(raw_text, mode))
```

### `models/ocr/engine.py`

- Singleton `PaddleOCR(lang=config.OCR_LANG)` khởi tạo lazy ở lần gọi đầu
  tiên (tránh load model khi import module, để test không phải tải model).
- `extract_text(image: bytes) -> str`: decode bytes → ảnh (numpy array qua
  `cv2.imdecode`), chạy `.ocr()`, nối các dòng nhận diện được bằng `"\n"`
  theo đúng thứ tự PaddleOCR trả về. Không tự lọc theo confidence (out of
  scope — xem bên dưới).
- Không catch lỗi PaddleOCR — để lỗi propagate lên `models/ocr/__init__.py`
  rồi lên `handlers/ocr.py` rồi lên `app.py` (đã có `except Exception` bọc
  sẵn thành câu TTS lỗi).

### `models/ocr/prompts.py`

- `build(text: str, mode: str) -> str`, 2 nhánh (RAW không tới đây):
  - `Mode.NORMAL`: yêu cầu dịch toàn bộ đoạn text sang tiếng Việt tự nhiên,
    ngắn gọn, chỉ trả bản dịch không giải thích thêm.
  - `Mode.SPECIALIZED`: yêu cầu dịch nhưng **giữ nguyên** thuật ngữ chuyên
    ngành, tên riêng, mã số, đơn vị đo — chỉ dịch phần văn bản thông thường
    xung quanh.
- Prompt luôn nhúng `raw_text` gốc từ PaddleOCR.

### `models/vlm/__init__.py` (amend)

```python
from . import client


def generate_text(prompt: str) -> str:
    return client.generate(prompt)
```

### `models/vlm/client.py` (mới, tối giản — chỉ phần text cần cho OCR)

- Client `google-genai` khởi tạo lazy (singleton module-level), dùng
  `config.GEMINI_API_KEY` và `config.GEMINI_MODEL`.
- `generate(prompt: str, image: bytes | None = None) -> str`: gọi
  `generate_content`; khi `image` có giá trị thì đính kèm image part (chuẩn
  bị sẵn cho `ask()` vision sau này, nhưng task này chỉ dùng nhánh
  `image=None`). Trả `.text.strip()`.
- Raise `VLMError` (định nghĩa trong `client.py`, export qua `__init__.py`)
  khi: API lỗi (exception từ SDK), hoặc response rỗng/không có `.text`.
- Không tự catch/nuốt lỗi ở bất kỳ tầng nào — propagate lên trên, giống
  nguyên tắc đã ghi trong spec vlm gốc.

## Config

`config.py`:
- Đổi `VISION_API_KEY` → `GEMINI_API_KEY` (theo spec vlm gốc, áp dụng ở task
  này vì `models/ocr` cần dùng ngay).
- Thêm `GEMINI_MODEL` (default `"gemini-2.5-flash"`).
- Thêm `OCR_LANG` (default `"vi"`).

`requirements.txt`: thêm `paddleocr`, `paddlepaddle`, `opencv-python-headless`,
`google-genai`.

## Sửa `handlers/ocr.py`

Giữ logic parse từ khóa hiện có (đã đúng), chỉ đổi phần gọi model thật thay
vì chuỗi giả:

```python
from models import ocr
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    raw = command_text.lower()
    if "nguyên văn" in raw:
        mode = ocr.Mode.RAW
    elif "chuyên ngành" in raw:
        mode = ocr.Mode.SPECIALIZED
    else:
        mode = ocr.Mode.NORMAL
    return Result(speech=ocr.read(image, mode))
```

## Testing

- `tests/test_models_ocr.py` (mới): monkeypatch `models.ocr.engine.extract_text`
  và `models.ocr.vlm.generate_text` (không tải PaddleOCR thật, không gọi
  network). Assert: RAW mode trả đúng raw_text, **không** gọi `generate_text`;
  NORMAL/SPECIALIZED gọi `generate_text` với prompt chứa raw_text, prompt của
  SPECIALIZED có nhắc giữ thuật ngữ; raw_text rỗng → trả câu "Không tìm thấy
  chữ trong ảnh." và không gọi `generate_text`.
- `tests/test_vlm_client.py` (mới): mock SDK `google-genai` — test
  `client.generate()` trả text khi thành công, raise `VLMError` khi response
  rỗng hoặc SDK raise exception. Không gọi network thật.
- `tests/test_handlers_ai.py`: sửa lại phần OCR — monkeypatch
  `handlers.ocr.ocr.read`, assert handler chọn đúng mode theo từ khóa
  command_text và bọc đúng vào `Result`. Bỏ các assert nội dung chuỗi giả cũ
  ("dịch"/"nguyên văn" trong response).

## Ngoài phạm vi

- Không lọc theo confidence score của PaddleOCR (dùng toàn bộ text nhận
  diện được).
- Không wiring `OCR_MODEL_DIR` vào PaddleOCR (dùng cache mặc định của thư
  viện) — biến này để sẵn cho việc custom model path sau nếu cần.
- Không build `vlm.ask()` (vision, cho `find`/`money`/`space`) — task riêng
  sau, dùng lại `client.generate(prompt, image=...)` đã chuẩn bị sẵn tham số
  `image`.
- Không cache/rate-limit lời gọi Gemini, không retry khi lỗi.
- Không xử lý ảnh nhiều khối text tách rời theo layout phức tạp (bảng biểu,
  cột) — chỉ nối theo thứ tự PaddleOCR trả về.
