# Blind-Assist Audio Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI server nhận ảnh + audio (WAV) từ vi điều khiển, STT → intent (5 chức năng AI) → handler → TTS, trả về audio/wav tiếng Việt.

**Architecture:** Server pipeline dạng module rời (stt, intent, tts, router) + 5 handler cùng chữ ký `handle(image, command_text) -> Result`. Mọi bước AI **stub** với interface cố định, để lắp model/API thật sau mà không phải sửa router hay endpoint.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, pytest, httpx (TestClient).

> **Ghi chú phạm vi (cập nhật 2026-07-19):** Bản plan đầu có thêm nhóm tiện ích
> điện thoại (gọi, nhắn tin, FCM push, device store) và hỏi ngày giờ, cùng một
> module mobile app React Native. Phạm vi đã thu hẹp còn **5 chức năng AI**.
> Task 1–6 dưới đây giữ nguyên văn bản gốc để khớp lịch sử commit; **Task 7 gỡ
> sạch** phần ngoài phạm vi, Task 8–10 là bản đã thu hẹp.

## Global Constraints

- Python **3.10+**.
- Audio WAV **mono, 16000 Hz, 16-bit** cả 2 chiều.
- Ngôn ngữ nội dung: **tiếng Việt** (speech + câu lỗi).
- Endpoint `/process` **luôn** trả `audio/wav`, HTTP 200 — kể cả lỗi/thiếu field (không JSON lỗi trần).
- 5 intent (verbatim): `ocr`, `translate`, `find`, `money`, `space`.
- `space` vừa là một intent, vừa là fallback khi không khớp từ khóa nào.
- Handler cùng chữ ký: `def handle(image: bytes, command_text: str) -> Result`.
- `Result` chỉ có một trường: `speech: str`.
- Import server dạng package tương đối từ gốc `Sever_test/` (chạy `uvicorn app:app`, pytest từ gốc).

---

## File Structure (sau khi thu hẹp phạm vi)

- `requirements.txt` — deps runtime + dev
- `config.py` — đọc env, mặc định an toàn
- `schemas.py` — `Intent` (5 hằng), `Result(speech)`
- `pipeline/stt.py` — `transcribe(audio) -> str` [stub]
- `pipeline/intent.py` — `detect(text) -> str`
- `pipeline/tts.py` — `synthesize(text) -> bytes` (wav) [stub]
- `pipeline/router.py` — `process(image, audio) -> bytes` (orchestrate)
- `handlers/text_utils.py` — `has_vietnamese(text) -> bool`
- `handlers/{ocr,translate,find_object,read_money,describe_space}.py`
- `app.py` — FastAPI: `/health`, `/process`
- `models/ocr/.gitkeep`, `models/translate/.gitkeep`, `storage/.gitkeep`
- `tests/` — pytest cho từng module + integration

---

## Task 1: Scaffold + config + schemas

**Files:**
- Create: `requirements.txt`, `config.py`, `schemas.py`
- Create: `models/ocr/.gitkeep`, `models/translate/.gitkeep`, `storage/.gitkeep`
- Create: `pipeline/__init__.py`, `handlers/__init__.py`, `tests/__init__.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `schemas.Intent` (8 hằng str), `schemas.Result(speech: str, action: dict | None = None)`; `config.get(name, default)`.

- [x] **Step 1: Khởi tạo git — ĐÃ LÀM SẴN, BỎ QUA**

Repo đã `git init`, đã có `.gitignore`, đã commit baseline, đang ở branch
`feat/blind-assist-flow`. Không chạy lại `git init`, không tạo lại `.gitignore`.

- [ ] **Step 2: Viết requirements.txt**

```
# runtime
fastapi
uvicorn[standard]
python-multipart
# dev / test
pytest
httpx
# TODO (khi làm FCM thật): firebase-admin
```

- [ ] **Step 3: Cài deps**

Run: `python -m pip install -r requirements.txt`
Expected: cài xong fastapi, uvicorn, python-multipart, pytest, httpx.

- [ ] **Step 4: Tạo thư mục trống + package markers**

```bash
mkdir -p pipeline handlers tests models/ocr models/translate storage
: > pipeline/__init__.py
: > handlers/__init__.py
: > tests/__init__.py
: > models/ocr/.gitkeep
: > models/translate/.gitkeep
: > storage/.gitkeep
```

- [ ] **Step 5: Viết failing test `tests/test_schemas.py`**

```python
from schemas import Intent, Result


def test_intent_has_eight_values():
    vals = {Intent.OCR, Intent.TRANSLATE, Intent.FIND, Intent.MONEY,
            Intent.SPACE, Intent.DATETIME, Intent.CALL, Intent.MESSAGE}
    assert vals == {"ocr", "translate", "find", "money", "space",
                    "datetime", "call", "message"}


def test_result_defaults_action_none():
    r = Result(speech="xin chào")
    assert r.speech == "xin chào"
    assert r.action is None


def test_result_with_action():
    r = Result(speech="Đang gọi Mẹ", action={"type": "call", "name": "Mẹ"})
    assert r.action["type"] == "call"
```

- [ ] **Step 6: Chạy test — phải FAIL**

Run: `python -m pytest tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'schemas'`.

- [ ] **Step 7: Viết `schemas.py`**

```python
from dataclasses import dataclass


class Intent:
    # nhóm AI
    OCR = "ocr"
    TRANSLATE = "translate"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"
    # nhóm tiện ích
    DATETIME = "datetime"
    CALL = "call"
    MESSAGE = "message"


@dataclass
class Result:
    speech: str                    # câu tiếng Việt -> TTS
    action: dict | None = None     # None = chỉ audio; có = đẩy FCM push
```

- [ ] **Step 8: Viết `config.py`**

```python
import os


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


STORAGE_DIR = get("STORAGE_DIR", "./storage")
OCR_MODEL_DIR = get("OCR_MODEL_DIR", "./models/ocr")
TRANSLATE_MODEL_DIR = get("TRANSLATE_MODEL_DIR", "./models/translate")
VISION_API_KEY = get("VISION_API_KEY", "")
FCM_CREDENTIALS = get("FCM_CREDENTIALS", "")
```

- [ ] **Step 9: Chạy test — phải PASS**

Run: `python -m pytest tests/test_schemas.py -v`
Expected: PASS (3 passed).

- [ ] **Step 10: Commit**

```bash
git add requirements.txt config.py schemas.py tests/test_schemas.py \
  pipeline/__init__.py handlers/__init__.py tests/__init__.py \
  models storage
git commit -m "feat: scaffold project, config, schemas (Intent, Result)"
```

---

## Task 2: STT stub

**Files:**
- Create: `pipeline/stt.py`
- Test: `tests/test_stt.py`

**Interfaces:**
- Produces: `stt.transcribe(audio: bytes) -> str`.

- [ ] **Step 1: Viết failing test `tests/test_stt.py`**

```python
from pipeline import stt


def test_transcribe_returns_str():
    out = stt.transcribe(b"fake wav bytes")
    assert isinstance(out, str)
    assert len(out) > 0
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_stt.py -v`
Expected: FAIL — `cannot import name 'stt'`.

- [ ] **Step 3: Viết `pipeline/stt.py`**

```python
def transcribe(audio: bytes) -> str:
    """Audio WAV -> câu lệnh tiếng Việt.

    Giai đoạn stub: trả câu cố định để pipeline chạy đầu-cuối.
    """
    # TODO: nối model STT tiếng Việt, dùng tham số `audio`.
    return "đọc chữ giúp tôi"
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_stt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/stt.py tests/test_stt.py
git commit -m "feat: add STT stub"
```

---

## Task 3: Intent detection

**Files:**
- Create: `pipeline/intent.py`
- Test: `tests/test_intent.py`

**Interfaces:**
- Consumes: `schemas.Intent`.
- Produces: `intent.detect(text: str) -> str` (trả 1 trong 8 giá trị `Intent`).

- [ ] **Step 1: Viết failing test `tests/test_intent.py`**

```python
import pytest
from pipeline import intent
from schemas import Intent


@pytest.mark.parametrize("text,expected", [
    ("đọc chữ giúp tôi", Intent.OCR),
    ("dịch câu này sang tiếng anh", Intent.TRANSLATE),
    ("tìm cái điều khiển ở đâu", Intent.FIND),
    ("đây là tờ tiền mệnh giá bao nhiêu", Intent.MONEY),
    ("miêu tả xung quanh tôi", Intent.SPACE),
    ("bây giờ là mấy giờ", Intent.DATETIME),
    ("gọi cho mẹ", Intent.CALL),
    ("nhắn tin cho bố", Intent.MESSAGE),
])
def test_detect_keywords(text, expected):
    assert intent.detect(text) == expected


def test_detect_default_is_space():
    assert intent.detect("xyz không khớp gì cả") == Intent.SPACE
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_intent.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `pipeline/intent.py`**

```python
from schemas import Intent

# Thứ tự quan trọng: kiểm tra cụm đặc trưng trước cụm chung.
# (dict giữ thứ tự chèn từ Python 3.7+)
_RULES = {
    Intent.MESSAGE: ["nhắn tin", "nhắn"],
    Intent.CALL: ["gọi cho", "gọi điện", "gọi"],
    Intent.DATETIME: ["mấy giờ", "ngày mấy", "hôm nay", "bây giờ"],
    Intent.TRANSLATE: ["dịch"],
    Intent.MONEY: ["mệnh giá", "tờ tiền", "tiền"],
    Intent.OCR: ["đọc", "chữ"],
    Intent.FIND: ["tìm", "ở đâu", "đâu"],
    Intent.SPACE: ["xung quanh", "trước mặt", "không gian", "miêu tả"],
}


def detect(text: str) -> str:
    t = text.lower()
    for intent_name, keywords in _RULES.items():
        if any(kw in t for kw in keywords):
            return intent_name
    return Intent.SPACE  # mặc định: miêu tả không gian
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_intent.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/intent.py tests/test_intent.py
git commit -m "feat: add intent detection (8 intents, keyword rules)"
```

---

## Task 4: TTS stub (WAV hợp lệ)

**Files:**
- Create: `pipeline/tts.py`
- Test: `tests/test_tts.py`

**Interfaces:**
- Produces: `tts.synthesize(text: str) -> bytes` (WAV mono 16kHz 16-bit hợp lệ).

- [ ] **Step 1: Viết failing test `tests/test_tts.py`**

```python
import io
import wave
from pipeline import tts


def test_synthesize_returns_valid_wav():
    data = tts.synthesize("xin chào")
    assert isinstance(data, bytes)
    assert len(data) > 44  # lớn hơn header WAV
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 16000
        assert w.getsampwidth() == 2
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_tts.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `pipeline/tts.py`**

```python
import io
import wave


def synthesize(text: str) -> bytes:
    """Text tiếng Việt -> WAV bytes.

    Giai đoạn stub: sinh 0.2s im lặng (WAV mono 16kHz 16-bit hợp lệ)
    để MCU nhận file phát được. Độ dài không phụ thuộc `text`.
    """
    # TODO: nối TTS tiếng Việt thật, render `text` thành giọng nói.
    frames = b"\x00\x00" * 3200  # 0.2s @ 16000 Hz, 16-bit
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(frames)
    return buf.getvalue()
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_tts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/tts.py tests/test_tts.py
git commit -m "feat: add TTS stub (valid silent WAV)"
```

---

## Task 5: AI handlers (ocr, translate, find, money, space)

**Files:**
- Create: `handlers/text_utils.py`, `handlers/ocr.py`, `handlers/translate.py`, `handlers/find_object.py`, `handlers/read_money.py`, `handlers/describe_space.py`
- Test: `tests/test_handlers_ai.py`

**Interfaces:**
- Consumes: `schemas.Result`.
- Produces: `text_utils.has_vietnamese(text: str) -> bool` (dùng chung bởi ocr + translate); mỗi handler module có `handle(image: bytes, command_text: str) -> Result` với `action is None`.

- [ ] **Step 1: Viết failing test `tests/test_handlers_ai.py`**

```python
from handlers import ocr, translate, find_object, read_money, describe_space
from handlers.text_utils import has_vietnamese
from schemas import Result

IMG = b"fake image"


def test_has_vietnamese_true_for_vi_text():
    assert has_vietnamese("chào buổi sáng") is True


def test_has_vietnamese_false_for_plain_ascii():
    assert has_vietnamese("good morning") is False


def test_ocr_translate_mode_default():
    r = ocr.handle(IMG, "đọc chữ giúp tôi")
    assert isinstance(r, Result) and r.action is None
    assert "dịch" in r.speech.lower()


def test_ocr_raw_mode_when_nguyen_van():
    r = ocr.handle(IMG, "đọc nguyên văn giúp tôi")
    assert "nguyên văn" in r.speech.lower()
    assert "dịch" not in r.speech.lower()


def test_ocr_raw_mode_when_chuyen_nganh():
    r = ocr.handle(IMG, "đọc chữ chuyên ngành")
    assert "nguyên văn" in r.speech.lower()


def test_translate_vi_to_en_when_vietnamese_input():
    r = translate.handle(IMG, "dịch câu chào buổi sáng")
    assert "VI->EN" in r.speech


def test_translate_en_to_vi_when_no_vietnamese():
    r = translate.handle(IMG, "translate good morning")
    assert "EN->VI" in r.speech


def test_find_money_space_return_result_no_action():
    for h in (find_object, read_money, describe_space):
        r = h.handle(IMG, "lệnh bất kỳ")
        assert isinstance(r, Result) and r.action is None
        assert len(r.speech) > 0
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_handlers_ai.py -v`
Expected: FAIL — import error.

- [ ] **Step 3a: Viết `handlers/text_utils.py`** (util dùng chung cho ocr + translate)

```python
# Dấu tiếng Việt, dùng để đoán một chuỗi có phải tiếng Việt không.
_VI_CHARS = "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộ" \
            "ờớởỡợùúủũụừứửữựỳýỷỹỵ"


def has_vietnamese(text: str) -> bool:
    return any(c in _VI_CHARS for c in text.lower())
```

- [ ] **Step 3b: Viết `handlers/ocr.py`**

```python
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    """Đọc chữ trong ảnh. Mặc định dịch sang tiếng Việt.

    Nếu lệnh yêu cầu "nguyên văn"/"chuyên ngành" -> đọc thô, không dịch.
    """
    # TODO: nối model OCR; nếu cần thì dịch kết quả sang tiếng Việt.
    raw = command_text.lower()
    no_translate = "nguyên văn" in raw or "chuyên ngành" in raw
    if no_translate:
        return Result(speech="[OCR] chưa cài model — đọc nguyên văn (kết quả giả)")
    return Result(speech="[OCR] chưa cài model — đọc và dịch sang tiếng Việt (kết quả giả)")
```

- [ ] **Step 4: Viết `handlers/translate.py`**

```python
from schemas import Result
from handlers.text_utils import has_vietnamese


def handle(image: bytes, command_text: str) -> Result:
    """Dịch câu người nói. Có ký tự tiếng Việt -> VI->EN, ngược lại EN->VI."""
    # TODO: nối model dịch; áp dụng đúng hướng lên nội dung thật.
    direction = "VI->EN" if has_vietnamese(command_text) else "EN->VI"
    return Result(speech=f"[TRANSLATE] chưa cài model — hướng {direction} (kết quả giả)")
```

- [ ] **Step 5: Viết `handlers/find_object.py`, `read_money.py`, `describe_space.py`**

`handlers/find_object.py`:
```python
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision tìm đồ vật + hướng ra.
    return Result(speech="[FIND] chưa nối API — hướng đồ vật (kết quả giả)")
```

`handlers/read_money.py`:
```python
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision đọc mệnh giá tiền.
    return Result(speech="[MONEY] chưa nối API — mệnh giá (kết quả giả)")
```

`handlers/describe_space.py`:
```python
from schemas import Result


def handle(image: bytes, command_text: str) -> Result:
    # TODO: nối API vision miêu tả không gian.
    return Result(speech="[SPACE] chưa nối API — miêu tả không gian (kết quả giả)")
```

- [ ] **Step 6: Chạy test — PASS**

Run: `python -m pytest tests/test_handlers_ai.py -v`
Expected: PASS (9 passed).

- [ ] **Step 7: Commit**

```bash
git add handlers/text_utils.py handlers/ocr.py handlers/translate.py \
  handlers/find_object.py handlers/read_money.py handlers/describe_space.py \
  tests/test_handlers_ai.py
git commit -m "feat: add AI handlers (ocr conditional, translate direction, find/money/space stubs)"
```

---

## Task 6: datetime handler (thật)

**Files:**
- Create: `handlers/datetime_util.py`
- Test: `tests/test_datetime_util.py`

**Interfaces:**
- Produces: `datetime_util.handle(image: bytes, command_text: str) -> Result` (action None, speech chứa ngày/giờ hiện tại).

- [ ] **Step 1: Viết failing test `tests/test_datetime_util.py`**

```python
from datetime import datetime
from handlers import datetime_util
from schemas import Result


def test_datetime_speech_contains_now():
    r = datetime_util.handle(b"", "bây giờ là mấy giờ")
    assert isinstance(r, Result) and r.action is None
    now = datetime.now()
    assert str(now.year) in r.speech
    assert f"tháng {now.month}" in r.speech
    assert "giờ" in r.speech
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_datetime_util.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `handlers/datetime_util.py`**

```python
from datetime import datetime
from schemas import Result

_THU = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
        "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]  # weekday(): 0=Mon


def handle(image: bytes, command_text: str) -> Result:
    """Trả ngày giờ hiện tại (handler thật, không cần model/API)."""
    now = datetime.now()
    thu = _THU[now.weekday()]
    speech = (f"Bây giờ là {now.hour} giờ {now.minute} phút, "
              f"{thu} ngày {now.day} tháng {now.month} năm {now.year}")
    return Result(speech=speech)
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_datetime_util.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handlers/datetime_util.py tests/test_datetime_util.py
git commit -m "feat: add real datetime handler"
```

---
## Task 7: Descope — gỡ toàn bộ phần điện thoại + datetime

> **Bối cảnh:** Phạm vi dự án thu hẹp còn **5 chức năng AI thuần**. Bỏ gọi điện,
> nhắn tin, push tới điện thoại, device store, và hỏi ngày giờ. Code các phần đó
> đã build ở bản plan trước — task này gỡ sạch khỏi cây code (vẫn còn trong lịch
> sử git nếu sau cần lấy lại).

**Files:**
- Delete: `handlers/call_phone.py`, `handlers/send_message.py`, `handlers/datetime_util.py`
- Delete: `pipeline/devices.py`, `pipeline/push.py`
- Delete: `tests/test_handlers_phone.py`, `tests/test_datetime_util.py`, `tests/test_devices.py`, `tests/test_push.py`
- Modify: `schemas.py` (rút `Intent` còn 5 hằng; bỏ trường `action` khỏi `Result`)
- Modify: `pipeline/intent.py` (bỏ rule DATETIME / CALL / MESSAGE)
- Modify: `handlers/text_utils.py` (bỏ `extract_name` — chỉ phone handler dùng)
- Modify: `tests/test_schemas.py`, `tests/test_intent.py`, `tests/test_handlers_ai.py`

**Interfaces:**
- Consumes: không.
- Produces (sau descope):
  - `Intent` chỉ còn: `OCR="ocr"`, `TRANSLATE="translate"`, `FIND="find"`, `MONEY="money"`, `SPACE="space"`.
  - `Result(speech: str)` — **không còn** trường `action`.
  - `text_utils.has_vietnamese(text: str) -> bool` (giữ nguyên).
  - `intent.detect(text: str) -> str` (giữ nguyên chữ ký, chỉ còn 5 giá trị trả về).

- [ ] **Step 1: Xóa file phần điện thoại + datetime**

```bash
git rm handlers/call_phone.py handlers/send_message.py handlers/datetime_util.py \
  pipeline/devices.py pipeline/push.py \
  tests/test_handlers_phone.py tests/test_datetime_util.py \
  tests/test_devices.py tests/test_push.py
```

- [ ] **Step 2: Rút gọn `schemas.py`**

Thay toàn bộ nội dung bằng:

```python
from dataclasses import dataclass


class Intent:
    OCR = "ocr"
    TRANSLATE = "translate"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"


@dataclass
class Result:
    speech: str    # câu tiếng Việt -> TTS
```

- [ ] **Step 3: Cập nhật `tests/test_schemas.py`**

Thay toàn bộ nội dung bằng:

```python
from schemas import Intent, Result


def test_intent_has_five_values():
    vals = {Intent.OCR, Intent.TRANSLATE, Intent.FIND, Intent.MONEY, Intent.SPACE}
    assert vals == {"ocr", "translate", "find", "money", "space"}


def test_result_holds_speech():
    r = Result(speech="xin chào")
    assert r.speech == "xin chào"


def test_result_has_no_action_field():
    # Phạm vi chỉ còn chức năng AI -> không còn action đẩy sang điện thoại.
    assert not hasattr(Result(speech="x"), "action")
```

- [ ] **Step 4: Rút gọn `pipeline/intent.py`**

Giữ nguyên cơ chế khớp theo biên từ (pad space + bỏ dấu câu) đã có. Chỉ đổi
`_RULES` còn 4 rule (SPACE vẫn là fallback, không nằm trong dict):

```python
_RULES = {
    Intent.TRANSLATE: ["dịch"],
    Intent.MONEY: ["mệnh giá", "tiền"],
    Intent.OCR: ["đọc", "chữ"],
    Intent.FIND: ["tìm", "ở đâu", "đâu"],
}
```

Không đổi thân hàm `detect`, không đổi bảng bỏ dấu câu.

- [ ] **Step 5: Cập nhật `tests/test_intent.py`**

Bỏ các case `datetime` / `call` / `message`. Giữ lại đúng các case sau (kèm 2 case
chống hồi quy đã thêm trước đó):

```python
import pytest
from pipeline import intent
from schemas import Intent


@pytest.mark.parametrize("text,expected", [
    ("đọc chữ giúp tôi", Intent.OCR),
    ("dịch câu này sang tiếng anh", Intent.TRANSLATE),
    ("tìm cái điều khiển ở đâu", Intent.FIND),
    ("đây là tờ tiền mệnh giá bao nhiêu", Intent.MONEY),
    ("miêu tả xung quanh tôi", Intent.SPACE),
    ("tìm chỗ chữa bệnh ở đâu", Intent.FIND),
    ("bây giờ tôi cần tìm chìa khóa ở đâu", Intent.FIND),
])
def test_detect_keywords(text, expected):
    assert intent.detect(text) == expected


def test_detect_default_is_space():
    assert intent.detect("xyz không khớp gì cả") == Intent.SPACE
```

- [ ] **Step 6: Bỏ `extract_name` khỏi `handlers/text_utils.py`**

Xóa hàm `extract_name` và mọi hằng chỉ phục vụ nó. Giữ nguyên `has_vietnamese`
và `_VI_CHARS`.

- [ ] **Step 7: Bỏ assertion `action` trong `tests/test_handlers_ai.py`**

Trong mọi test, xóa phần `and r.action is None` / `assert r.action is None`,
giữ nguyên `assert isinstance(r, Result)` và các assertion về nội dung `speech`.

- [ ] **Step 8: Chạy toàn bộ test**

Run: `python -m pytest -v`
Expected: tất cả PASS. Không còn test nào của phone/datetime/devices/push.

- [ ] **Step 9: Kiểm tra không còn tham chiếu mồ côi**

Run: `grep -rn "call_phone\|send_message\|datetime_util\|devices\|push\|action\|extract_name" --include=*.py .`
Expected: không có kết quả nào trong `handlers/`, `pipeline/`, `tests/`, `schemas.py`.
(Kết quả trong `.superpowers/` hoặc `docs/` là bình thường — bỏ qua.)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: descope to 5 AI functions, drop phone/datetime features"
```

---

## Task 8: Router (orchestrate pipeline)

**Files:**
- Create: `pipeline/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `stt.transcribe`, `intent.detect`, 5 handler `handle`, `tts.synthesize`.
- Produces: `router.process(image: bytes, audio: bytes) -> bytes` (WAV).
  **Không** có tham số `device_id`, **không** đẩy push.

- [ ] **Step 1: Viết failing test `tests/test_router.py`**

```python
import io
import wave
from unittest.mock import patch

from pipeline import router


def _is_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1


def test_process_returns_wav():
    out = router.process(b"img", b"aud")
    assert isinstance(out, bytes)
    assert _is_wav(out)


def test_process_routes_to_detected_handler():
    with patch("pipeline.intent.detect", return_value="money") as mock_detect, \
         patch("handlers.read_money.handle") as mock_handler:
        from schemas import Result
        mock_handler.return_value = Result(speech="mệnh giá giả")
        router.process(b"img", b"aud")
        mock_detect.assert_called_once()
        mock_handler.assert_called_once()


def test_process_speaks_handler_result():
    from schemas import Result
    with patch("pipeline.intent.detect", return_value="ocr"), \
         patch("handlers.ocr.handle", return_value=Result(speech="nội dung đọc")), \
         patch("pipeline.tts.synthesize", return_value=b"WAVDATA") as mock_tts:
        out = router.process(b"img", b"aud")
        mock_tts.assert_called_once_with("nội dung đọc")
        assert out == b"WAVDATA"


def test_process_unknown_intent_falls_back_to_space():
    with patch("pipeline.intent.detect", return_value="khong-ton-tai"), \
         patch("handlers.describe_space.handle") as mock_space:
        from schemas import Result
        mock_space.return_value = Result(speech="miêu tả giả")
        router.process(b"img", b"aud")
        mock_space.assert_called_once()
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_router.py -v`
Expected: FAIL — `cannot import name 'router'`.

- [ ] **Step 3: Viết `pipeline/router.py`**

```python
from schemas import Intent
from pipeline import stt, intent as intent_mod, tts
from handlers import ocr, translate, find_object, read_money, describe_space

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.TRANSLATE: translate,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
}


def process(image: bytes, audio: bytes) -> bytes:
    """Pipeline đầu-cuối: audio -> STT -> intent -> handler -> TTS."""
    command_text = stt.transcribe(audio)
    intent_name = intent_mod.detect(command_text)
    handler = _HANDLERS.get(intent_name, describe_space)
    result = handler.handle(image, command_text)
    return tts.synthesize(result.speech)
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_router.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/router.py tests/test_router.py
git commit -m "feat: add router orchestrating AI pipeline"
```

---

## Task 9: FastAPI app (endpoints + integration)

**Files:**
- Modify: `app.py` (thay toàn bộ nội dung hiện tại — chỉ có `/health`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `router.process`, `tts.synthesize`.
- Produces 2 route:
  - `GET /health -> {"status": "ok"}`
  - `POST /process` (File: `image`, `audio`) `-> Response audio/wav`

  **Không** có `/register-device`, **không** nhận `device_id`.

- [ ] **Step 1: Viết failing test `tests/test_app.py`**

```python
import io
import wave

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


def _files():
    return {"image": ("i.jpg", b"fake img", "image/jpeg"),
            "audio": ("a.wav", _wav_bytes(), "audio/wav")}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_process_returns_wav():
    r = client.post("/process", files=_files())
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert len(r.content) > 44


def test_process_missing_image_still_returns_wav():
    files = {"audio": ("a.wav", _wav_bytes(), "audio/wav")}
    r = client.post("/process", files=files)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_process_missing_audio_still_returns_wav():
    files = {"image": ("i.jpg", b"fake img", "image/jpeg")}
    r = client.post("/process", files=files)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_process_pipeline_error_still_returns_wav():
    from unittest.mock import patch
    with patch("pipeline.router.process", side_effect=RuntimeError("boom")):
        r = client.post("/process", files=_files())
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert len(r.content) > 44
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL — `/process` trả 404 (app.py hiện chỉ có `/health`).

- [ ] **Step 3: Viết lại `app.py`**

```python
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import Response

from pipeline import router, tts

app = FastAPI(title="Blind-Assist Audio Server")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
async def process(image: UploadFile | None = File(None),
                  audio: UploadFile | None = File(None)):
    # Thiếu field -> vẫn trả audio để người khiếm thị nghe được lý do.
    if image is None or audio is None:
        return Response(content=tts.synthesize("Thiếu ảnh hoặc âm thanh"),
                        media_type="audio/wav")
    try:
        img = await image.read()
        aud = await audio.read()
        wav = router.process(img, aud)
    except Exception:  # noqa: BLE001 - luôn trả audio, không trả JSON lỗi trần
        wav = tts.synthesize("Có lỗi xảy ra, vui lòng thử lại")
    return Response(content=wav, media_type="audio/wav")
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Chạy toàn bộ test**

Run: `python -m pytest -v`
Expected: tất cả PASS.

- [ ] **Step 6: Chạy thử server thật (kiểm tra tay)**

Run: `python -m uvicorn app:app --reload`
Expected: server chạy ở `http://127.0.0.1:8000`; mở `http://127.0.0.1:8000/docs`
thấy đúng 2 endpoint (`/health`, `/process`). Ctrl+C thoát.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: wire FastAPI endpoints (health, process)"
```

---

## Task 10: Root README

**Files:**
- Create: `README.md`

**Interfaces:** none (tài liệu).

- [ ] **Step 1: Viết `README.md`**

```markdown
# Blind-Assist Audio Server

Server hỗ trợ người khiếm thị: vi điều khiển gửi **ảnh + audio (WAV)**,
server chạy STT -> nhận diện ý định -> handler -> TTS, trả về **audio/wav**
tiếng Việt để thiết bị phát cho người dùng.

## Cài
    python -m pip install -r requirements.txt

## Chạy
    python -m uvicorn app:app --reload
Docs: http://127.0.0.1:8000/docs

## Test
    python -m pytest -v

## Endpoint
- `GET  /health` -> `{"status": "ok"}`
- `POST /process` (multipart: `image`, `audio`) -> `audio/wav`

`/process` luôn trả `audio/wav` với HTTP 200 — kể cả khi thiếu field hoặc lỗi
xử lý, câu báo lỗi được đọc thành tiếng để người khiếm thị nghe được.

## 5 chức năng (tự nhận diện từ giọng nói)
| Intent | Chức năng |
|--------|-----------|
| `ocr` | Đọc chữ trong ảnh; mặc định dịch sang tiếng Việt, nói "nguyên văn"/"chuyên ngành" thì đọc thô |
| `translate` | Dịch câu người nói, VI->EN hoặc EN->VI (tự đoán hướng) |
| `find` | Tìm đồ vật, chỉ hướng |
| `money` | Đọc mệnh giá tiền |
| `space` | Miêu tả không gian trước mặt (cũng là mặc định khi không khớp) |

## Trạng thái
Toàn bộ bước AI hiện là **stub** — trả chuỗi giả, interface đã cố định để lắp
model/API thật mà không phải sửa router hay endpoint:

- `pipeline/stt.py` — TODO: model STT tiếng Việt
- `pipeline/tts.py` — TODO: TTS tiếng Việt (hiện sinh WAV im lặng hợp lệ)
- `pipeline/intent.py` — khớp từ khóa; có thể thay bằng classifier sau
- `handlers/ocr.py`, `handlers/translate.py` — TODO: model
- `handlers/find_object.py`, `handlers/read_money.py`, `handlers/describe_space.py` — TODO: API vision

Thư mục `models/ocr/`, `models/translate/` để trống, chờ file model.

## Ngoài phạm vi
Chức năng liên quan điện thoại (gọi, nhắn tin, push tới app di động) và hỏi
ngày giờ đã được gỡ khỏi phạm vi. Code cũ còn trong lịch sử git.
```

- [ ] **Step 2: Chạy lại toàn bộ test**

Run: `python -m pytest -v`
Expected: tất cả PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add root README (run + test instructions)"
```

---

## Self-Review (bản thu hẹp phạm vi)

**Spec coverage:**
- 5 chức năng AI (ocr, translate, find, money, space) → Task 5 (đã xong) + Task 8 router. ✅
- OCR dịch có điều kiện; translate hướng VI↔EN → Task 5. ✅
- STT / intent / TTS → Task 2, 3, 4 (đã xong). ✅
- Gỡ sạch phone/datetime/push/device store → Task 7. ✅
- `/process` luôn trả audio/wav kể cả thiếu field và lỗi pipeline → Task 9 (5 test). ✅
- Server requirements → Task 1 `requirements.txt` (đã xong). ✅

**Placeholder scan:** Mọi bước có code/lệnh thật. `# TODO` là điểm cắm model/API
tương lai (đúng thiết kế stub), không phải placeholder plan. ✅

**Type consistency:** `handle(image: bytes, command_text: str) -> Result` đồng nhất
5 handler; `Result(speech: str)` không còn `action`; `intent.detect(text) -> str`
trả 1 trong 5 giá trị; `router.process(image, audio) -> bytes` (bỏ `device_id`);
`tts.synthesize(text) -> bytes`; `stt.transcribe(audio) -> str`. Khớp giữa các task. ✅
