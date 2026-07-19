# Blind-Assist Audio Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI server nhận ảnh + audio (WAV) + device_id từ MCU, STT → intent (8 chức năng) → handler → TTS, trả audio/wav; lệnh điện thoại đẩy FCM push tới mobile app React Native (Android) để gọi/nhắn.

**Architecture:** Server pipeline dạng module rời (stt, intent, tts, push, devices, router) + 8 handler cùng chữ ký `handle(image, command_text) -> Result`. Mọi bước AI **stub** (interface cố định, lắp model/API sau); `datetime` làm thật; `push` stub log. Mobile app Android nhận FCM push → tra danh bạ → tự gọi/nhắn bằng native lib.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, pytest, httpx (TestClient). Mobile: React Native (Android), @react-native-firebase/messaging, react-native-contacts, react-native-immediate-phone-call, react-native-send-direct-sms, Jest.

## Global Constraints

- Python **3.10+** (dùng cú pháp `dict | None`).
- Audio WAV **mono, 16000 Hz, 16-bit** cả 2 chiều.
- Ngôn ngữ nội dung: **tiếng Việt** (speech + câu lỗi).
- Endpoint `/process` **luôn** trả `audio/wav`, HTTP 200 — kể cả lỗi/thiếu field (không JSON lỗi trần).
- Lỗi hoặc thiếu field → **không** gọi `push.send`.
- 8 intent (verbatim): `ocr`, `translate`, `find`, `money`, `space`, `datetime`, `call`, `message`.
- Handler cùng chữ ký: `def handle(image: bytes, command_text: str) -> Result`.
- Mobile: **chỉ Android** giai đoạn này (iOS hoãn — Apple cấm auto call/SMS).
- Import server dạng package tương đối từ gốc `Sever_test/` (chạy `uvicorn app:app`, pytest từ gốc).

---

## File Structure

**Server:**
- `requirements.txt` — deps runtime + dev
- `config.py` — đọc env, mặc định an toàn
- `schemas.py` — `Intent`, `Result`
- `pipeline/stt.py` — `transcribe(audio) -> str` [stub]
- `pipeline/intent.py` — `detect(text) -> str`
- `pipeline/tts.py` — `synthesize(text) -> bytes` (wav)
- `pipeline/devices.py` — store `register`, `get_token`
- `pipeline/push.py` — `send(device_id, action) -> bool` [stub log]
- `pipeline/router.py` — `process(image, audio, device_id) -> bytes` (orchestrate)
- `handlers/{ocr,translate,find_object,read_money,describe_space,datetime_util,call_phone,send_message}.py`
- `app.py` — FastAPI: `/health`, `/register-device`, `/process`
- `models/ocr/.gitkeep`, `models/translate/.gitkeep`, `storage/.gitkeep`
- `tests/` — pytest cho từng module + integration

**Mobile (`mobile/`, Android):**
- `package.json` — deps RN
- `src/config.js` — `SERVER_URL`, `DEVICE_ID`
- `src/api.js` — `registerDevice()`
- `src/push.js` — `init()`, `onMessage(cb)`
- `src/contacts.js` — `findNumber(name)`
- `src/actions.js` — `execute(action)`
- `src/index.js` — `start()`
- `__tests__/` — Jest (mock native)
- `README-flow.md` — mô tả luồng + cách test trên máy Android

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

## Task 7: Phone handlers (call, message) — trả action

**Files:**
- Create: `handlers/call_phone.py`, `handlers/send_message.py`
- Test: `tests/test_handlers_phone.py`

**Interfaces:**
- Consumes: `schemas.Result`.
- Produces:
  - `call_phone.handle(image, command_text) -> Result` với `action = {"type": "call", "name": <str>}`.
  - `send_message.handle(image, command_text) -> Result` với `action = {"type": "message", "name": <str>, "text": <str>}`.

- [ ] **Step 1: Viết failing test `tests/test_handlers_phone.py`**

```python
from handlers import call_phone, send_message


def test_call_extracts_name_and_action():
    r = call_phone.handle(b"", "gọi cho mẹ")
    assert r.action == {"type": "call", "name": "mẹ"}
    assert "mẹ" in r.speech.lower()
    assert "gọi" in r.speech.lower()


def test_call_without_cho():
    r = call_phone.handle(b"", "gọi bố")
    assert r.action["name"] == "bố"


def test_message_action_shape():
    r = send_message.handle(b"", "nhắn tin cho chị")
    assert r.action["type"] == "message"
    assert r.action["name"] == "chị"
    assert "text" in r.action
    assert "nhắn" in r.speech.lower()
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_handlers_phone.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `handlers/call_phone.py`**

```python
from schemas import Result

_CALL_PREFIXES = ["gọi điện cho", "gọi cho", "gọi điện", "gọi"]


def _extract_name(command_text: str) -> str:
    t = command_text.strip().lower()
    for prefix in _CALL_PREFIXES:  # dài trước, ngắn sau
        if t.startswith(prefix):
            return t[len(prefix):].strip()
    return t


def handle(image: bytes, command_text: str) -> Result:
    name = _extract_name(command_text)
    return Result(speech=f"Đang gọi {name}",
                  action={"type": "call", "name": name})
```

- [ ] **Step 4: Viết `handlers/send_message.py`**

```python
from schemas import Result

_MSG_PREFIXES = ["nhắn tin cho", "nhắn cho", "nhắn tin", "nhắn"]


def _extract_name(command_text: str) -> str:
    t = command_text.strip().lower()
    for prefix in _MSG_PREFIXES:
        if t.startswith(prefix):
            return t[len(prefix):].strip()
    return t


def handle(image: bytes, command_text: str) -> Result:
    name = _extract_name(command_text)
    # TODO: tách nội dung tin nhắn từ lệnh; giờ để rỗng.
    return Result(speech=f"Đã nhắn {name}",
                  action={"type": "message", "name": name, "text": ""})
```

- [ ] **Step 5: Chạy test — PASS**

Run: `python -m pytest tests/test_handlers_phone.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add handlers/call_phone.py handlers/send_message.py tests/test_handlers_phone.py
git commit -m "feat: add phone handlers (call, message) returning action"
```

---

## Task 8: Device store

**Files:**
- Create: `pipeline/devices.py`
- Test: `tests/test_devices.py`

**Interfaces:**
- Produces:
  - `devices.register(device_id: str, fcm_token: str, platform: str = "") -> None`
  - `devices.get_token(device_id: str) -> str | None`

- [ ] **Step 1: Viết failing test `tests/test_devices.py`**

```python
from pipeline import devices


def test_register_and_get_token():
    devices.register("dev-1", "tok-abc", "android")
    assert devices.get_token("dev-1") == "tok-abc"


def test_get_unknown_returns_none():
    assert devices.get_token("khong-ton-tai") is None


def test_register_overwrites():
    devices.register("dev-2", "old")
    devices.register("dev-2", "new")
    assert devices.get_token("dev-2") == "new"
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_devices.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `pipeline/devices.py`**

```python
# Map device_id -> fcm_token. In-memory cho prototype.
# TODO: thay bằng DB/Redis khi cần bền + nhiều thiết bị.
_store: dict[str, str] = {}


def register(device_id: str, fcm_token: str, platform: str = "") -> None:
    _store[device_id] = fcm_token


def get_token(device_id: str) -> str | None:
    return _store.get(device_id)
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_devices.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/devices.py tests/test_devices.py
git commit -m "feat: add in-memory device token store"
```

---

## Task 9: Push stub

**Files:**
- Create: `pipeline/push.py`
- Test: `tests/test_push.py`

**Interfaces:**
- Consumes: `devices.get_token`.
- Produces: `push.send(device_id: str, action: dict) -> bool` (True nếu có token, False nếu không).

- [ ] **Step 1: Viết failing test `tests/test_push.py`**

```python
from pipeline import push, devices


def test_send_returns_true_when_token_registered():
    devices.register("push-dev", "tok-1", "android")
    assert push.send("push-dev", {"type": "call", "name": "mẹ"}) is True


def test_send_returns_false_when_no_token():
    assert push.send("no-such-device", {"type": "call", "name": "x"}) is False
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_push.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `pipeline/push.py`**

```python
import logging

from pipeline import devices

log = logging.getLogger("push")


def send(device_id: str, action: dict) -> bool:
    """Đẩy action tới mobile app qua FCM.

    Giai đoạn stub: chỉ log payload. Không có token -> trả False.
    """
    token = devices.get_token(device_id)
    if not token:
        log.warning("push: chưa có token cho device_id=%s", device_id)
        return False
    # TODO: gọi FCM/APNs thật (firebase-admin) với token + action.
    log.info("PUSH -> device=%s token=%s action=%s", device_id, token, action)
    return True
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_push.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/push.py tests/test_push.py
git commit -m "feat: add push stub (logs payload, looks up token)"
```

---

## Task 10: Router (orchestrate pipeline)

**Files:**
- Create: `pipeline/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `stt.transcribe`, `intent.detect`, tất cả handler `handle`, `push.send`, `tts.synthesize`.
- Produces: `router.process(image: bytes, audio: bytes, device_id: str) -> bytes` (WAV). Gọi `push.send` **chỉ khi** handler trả `action is not None`.

- [ ] **Step 1: Viết failing test `tests/test_router.py`**

```python
import io
import wave
from unittest.mock import patch

from pipeline import router
from schemas import Result


def _is_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1


def test_process_returns_wav():
    out = router.process(b"img", b"aud", "dev-1")
    assert isinstance(out, bytes)
    assert _is_wav(out)


def test_process_calls_push_when_action_present():
    # intent 'call' -> handler trả action -> push.send được gọi
    with patch("pipeline.intent.detect", return_value="call"), \
         patch("pipeline.push.send") as mock_send:
        router.process(b"img", b"aud", "dev-9")
        mock_send.assert_called_once()
        args = mock_send.call_args.args
        assert args[0] == "dev-9"
        assert args[1]["type"] == "call"


def test_process_no_push_when_no_action():
    with patch("pipeline.intent.detect", return_value="ocr"), \
         patch("pipeline.push.send") as mock_send:
        router.process(b"img", b"aud", "dev-9")
        mock_send.assert_not_called()
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_router.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Viết `pipeline/router.py`**

```python
from schemas import Intent
from pipeline import stt, intent as intent_mod, tts, push
from handlers import (ocr, translate, find_object, read_money,
                      describe_space, datetime_util, call_phone, send_message)

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.TRANSLATE: translate,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
    Intent.DATETIME: datetime_util,
    Intent.CALL: call_phone,
    Intent.MESSAGE: send_message,
}


def process(image: bytes, audio: bytes, device_id: str) -> bytes:
    """Pipeline đầy-cuối: audio -> STT -> intent -> handler -> (push) -> TTS."""
    command_text = stt.transcribe(audio)
    intent_name = intent_mod.detect(command_text)
    handler = _HANDLERS.get(intent_name, describe_space)
    result = handler.handle(image, command_text)
    if result.action is not None:
        push.send(device_id, result.action)
    return tts.synthesize(result.speech)
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_router.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/router.py tests/test_router.py
git commit -m "feat: add router orchestrating full pipeline"
```

---

## Task 11: FastAPI app (endpoints + integration)

**Files:**
- Modify: `app.py` (thay nội dung hiện tại — chỉ có `/health`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `router.process`, `devices.register`, `tts.synthesize`.
- Produces: 3 route:
  - `GET /health -> {"status": "ok"}`
  - `POST /register-device` (Form: `device_id`, `fcm_token`, `platform`) `-> {"status": "registered"}`
  - `POST /process` (Form/File: `image`, `audio`, `device_id`) `-> Response audio/wav`

- [ ] **Step 1: Viết failing test `tests/test_app.py`**

```python
import io
import wave
from unittest.mock import patch

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


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_register_device():
    r = client.post("/register-device", data={
        "device_id": "dev-app-1", "fcm_token": "tok-1", "platform": "android"})
    assert r.status_code == 200
    assert r.json()["status"] == "registered"


def test_process_returns_wav():
    files = {"image": ("i.jpg", b"fake img", "image/jpeg"),
             "audio": ("a.wav", _wav_bytes(), "audio/wav")}
    r = client.post("/process", files=files, data={"device_id": "dev-app-1"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert len(r.content) > 44


def test_process_missing_fields_still_returns_wav():
    r = client.post("/process", data={"device_id": "dev-app-1"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_process_call_intent_triggers_push():
    # STT trả câu chứa 'gọi' -> intent call -> push.send được gọi
    with patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"), \
         patch("pipeline.push.send") as mock_send:
        files = {"image": ("i.jpg", b"x", "image/jpeg"),
                 "audio": ("a.wav", _wav_bytes(), "audio/wav")}
        r = client.post("/process", files=files, data={"device_id": "dev-app-1"})
        assert r.status_code == 200
        mock_send.assert_called_once()
```

- [ ] **Step 2: Chạy test — FAIL**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL — `/register-device` 404 / `/process` 404 (app.py chỉ có /health).

- [ ] **Step 3: Viết lại `app.py`**

```python
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response

from pipeline import router, devices, tts

app = FastAPI(title="Blind-Assist Audio Server")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register-device")
def register_device(device_id: str = Form(...),
                    fcm_token: str = Form(...),
                    platform: str = Form("")):
    devices.register(device_id, fcm_token, platform)
    return {"status": "registered"}


@app.post("/process")
async def process(image: UploadFile | None = File(None),
                  audio: UploadFile | None = File(None),
                  device_id: str = Form("")):
    # Thiếu field -> audio báo lỗi, KHÔNG push.
    if image is None or audio is None or not device_id:
        return Response(content=tts.synthesize("Thiếu dữ liệu"),
                        media_type="audio/wav")
    try:
        img = await image.read()
        aud = await audio.read()
        wav = router.process(img, aud, device_id)
    except Exception:  # noqa: BLE001 - luôn trả audio cho người khiếm thị
        wav = tts.synthesize("Có lỗi xảy ra, vui lòng thử lại")
    return Response(content=wav, media_type="audio/wav")
```

- [ ] **Step 4: Chạy test — PASS**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Chạy toàn bộ test server**

Run: `python -m pytest -v`
Expected: tất cả PASS.

- [ ] **Step 6: Chạy thử server thật (kiểm tra tay)**

Run: `python -m uvicorn app:app --reload`
Expected: server chạy ở `http://127.0.0.1:8000`; mở `http://127.0.0.1:8000/docs` thấy 3 endpoint. Ctrl+C thoát.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: wire FastAPI endpoints (health, register-device, process)"
```

---

## Task 12: Mobile scaffold + config + register API

**Files:**
- Create: `mobile/package.json`, `mobile/src/config.js`, `mobile/src/api.js`
- Create: `mobile/__tests__/api.test.js`, `mobile/jest.config.js`, `mobile/babel.config.js`

**Interfaces:**
- Produces: `api.registerDevice(deviceId: string, fcmToken: string, platform: string) -> Promise<boolean>`; `config.SERVER_URL`, `config.DEVICE_ID`.

> Ghi chú deps native: các lib RN cần app RN thật + Android SDK để chạy trên máy.
> Các Jest test ở dưới **mock** native/fetch nên chạy được không cần thiết bị.

- [ ] **Step 1: Viết `mobile/package.json`**

```json
{
  "name": "blind-assist-mobile",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "test": "jest",
    "android": "react-native run-android"
  },
  "dependencies": {
    "react": "18.2.0",
    "react-native": "0.74.0",
    "@react-native-firebase/app": "^20.0.0",
    "@react-native-firebase/messaging": "^20.0.0",
    "react-native-contacts": "^7.0.8",
    "react-native-immediate-phone-call": "^2.0.0",
    "react-native-send-direct-sms": "^1.2.0"
  },
  "devDependencies": {
    "@babel/core": "^7.20.0",
    "@babel/preset-env": "^7.20.0",
    "babel-jest": "^29.0.0",
    "jest": "^29.0.0"
  }
}
```

- [ ] **Step 2: Viết `mobile/babel.config.js` + `mobile/jest.config.js`**

`mobile/babel.config.js`:
```js
module.exports = { presets: ["@babel/preset-env"] };
```

`mobile/jest.config.js`:
```js
module.exports = { testEnvironment: "node" };
```

- [ ] **Step 3: Cài deps test (chỉ babel + jest, đủ chạy unit test)**

Run: `cd mobile && npm install --save-dev @babel/core @babel/preset-env babel-jest jest`
Expected: cài xong jest + babel (không cần cài lib native để chạy unit test mock).

- [ ] **Step 4: Viết `mobile/src/config.js`**

```js
// 10.0.2.2 = host máy tính nhìn từ Android emulator.
// Đổi sang IP LAN của server khi chạy máy thật.
export const SERVER_URL = "http://10.0.2.2:8000";
export const DEVICE_ID = "device-001"; // phải trùng device_id MCU gửi lên
```

- [ ] **Step 5: Viết failing test `mobile/__tests__/api.test.js`**

```js
import { registerDevice } from "../src/api";

describe("registerDevice", () => {
  afterEach(() => { global.fetch = undefined; });

  test("POST /register-device và trả true khi ok", async () => {
    const calls = [];
    global.fetch = (url, opts) => {
      calls.push({ url, opts });
      return Promise.resolve({ ok: true });
    };
    const ok = await registerDevice("dev-1", "tok-1", "android");
    expect(ok).toBe(true);
    expect(calls[0].url).toContain("/register-device");
    expect(calls[0].opts.method).toBe("POST");
  });

  test("trả false khi server lỗi", async () => {
    global.fetch = () => Promise.resolve({ ok: false });
    const ok = await registerDevice("dev-1", "tok-1", "android");
    expect(ok).toBe(false);
  });
});
```

- [ ] **Step 6: Chạy test — FAIL**

Run: `cd mobile && npx jest api.test.js`
Expected: FAIL — không tìm thấy `../src/api`.

- [ ] **Step 7: Viết `mobile/src/api.js`**

```js
import { SERVER_URL } from "./config";

export async function registerDevice(deviceId, fcmToken, platform) {
  const body = new FormData();
  body.append("device_id", deviceId);
  body.append("fcm_token", fcmToken);
  body.append("platform", platform);
  const res = await fetch(`${SERVER_URL}/register-device`, {
    method: "POST",
    body,
  });
  return res.ok;
}
```

- [ ] **Step 8: Chạy test — PASS**

Run: `cd mobile && npx jest api.test.js`
Expected: PASS (2 passed).

- [ ] **Step 9: Commit**

```bash
git add mobile/package.json mobile/babel.config.js mobile/jest.config.js \
  mobile/src/config.js mobile/src/api.js mobile/__tests__/api.test.js
git commit -m "feat(mobile): scaffold RN module, config, registerDevice"
```

---

## Task 13: Mobile contacts + actions (native, Android)

**Files:**
- Create: `mobile/src/contacts.js`, `mobile/src/actions.js`
- Create: `mobile/__tests__/actions.test.js`

**Interfaces:**
- Produces:
  - `contacts.findNumber(name: string) -> Promise<string | null>`
  - `actions.execute(action: {type, name, text?}) -> Promise<boolean>` (gọi/nhắn qua native; false nếu không tra được số hoặc type lạ).

- [ ] **Step 1: Viết `mobile/src/contacts.js`**

```js
import Contacts from "react-native-contacts";

// Tra tên -> số điện thoại đầu tiên khớp trong danh bạ máy.
export async function findNumber(name) {
  const matches = await Contacts.getContactsMatchingString(name);
  if (!matches || matches.length === 0) return null;
  const phones = matches[0].phoneNumbers;
  if (!phones || phones.length === 0) return null;
  return phones[0].number;
}
```

- [ ] **Step 2: Viết failing test `mobile/__tests__/actions.test.js`**

```js
// Mock native modules trước khi import actions.
jest.mock("react-native-immediate-phone-call", () => ({
  immediatePhoneCall: jest.fn(),
}), { virtual: true });
jest.mock("react-native-send-direct-sms", () => jest.fn(), { virtual: true });
jest.mock("../src/contacts", () => ({ findNumber: jest.fn() }));

import ImmediatePhoneCall from "react-native-immediate-phone-call";
import SendDirectSms from "react-native-send-direct-sms";
import { findNumber } from "../src/contacts";
import { execute } from "../src/actions";

describe("actions.execute", () => {
  beforeEach(() => jest.clearAllMocks());

  test("call: tra số rồi quay số", async () => {
    findNumber.mockResolvedValue("0912345678");
    const ok = await execute({ type: "call", name: "mẹ" });
    expect(ok).toBe(true);
    expect(ImmediatePhoneCall.immediatePhoneCall).toHaveBeenCalledWith("0912345678");
  });

  test("message: tra số rồi gửi SMS", async () => {
    findNumber.mockResolvedValue("0912345678");
    const ok = await execute({ type: "message", name: "bố", text: "xin chào" });
    expect(ok).toBe(true);
    expect(SendDirectSms).toHaveBeenCalledWith("0912345678", "xin chào");
  });

  test("không tìm thấy tên -> false, không gọi native", async () => {
    findNumber.mockResolvedValue(null);
    const ok = await execute({ type: "call", name: "người lạ" });
    expect(ok).toBe(false);
    expect(ImmediatePhoneCall.immediatePhoneCall).not.toHaveBeenCalled();
  });

  test("type lạ -> false", async () => {
    findNumber.mockResolvedValue("0912345678");
    const ok = await execute({ type: "email", name: "mẹ" });
    expect(ok).toBe(false);
  });
});
```

- [ ] **Step 3: Chạy test — FAIL**

Run: `cd mobile && npx jest actions.test.js`
Expected: FAIL — không tìm thấy `../src/actions`.

- [ ] **Step 4: Viết `mobile/src/actions.js`**

```js
import ImmediatePhoneCall from "react-native-immediate-phone-call";
import SendDirectSms from "react-native-send-direct-sms";
import { findNumber } from "./contacts";

// Thực thi action nhận từ FCM push. Chỉ Android (auto call/SMS ngầm).
export async function execute(action) {
  const number = await findNumber(action.name);
  if (!number) {
    console.warn(`Không tìm thấy "${action.name}" trong danh bạ`);
    return false;
  }
  if (action.type === "call") {
    ImmediatePhoneCall.immediatePhoneCall(number);
    return true;
  }
  if (action.type === "message") {
    SendDirectSms(number, action.text || "");
    return true;
  }
  console.warn(`Action type không hỗ trợ: ${action.type}`);
  return false;
}
```

- [ ] **Step 5: Chạy test — PASS**

Run: `cd mobile && npx jest actions.test.js`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add mobile/src/contacts.js mobile/src/actions.js mobile/__tests__/actions.test.js
git commit -m "feat(mobile): contacts lookup + execute call/message (Android native)"
```

---

## Task 14: Mobile push + start wiring + README

**Files:**
- Create: `mobile/src/push.js`, `mobile/src/index.js`, `mobile/README-flow.md`
- Create: `mobile/__tests__/index.test.js`

**Interfaces:**
- Consumes: `push.init`, `push.onMessage`, `api.registerDevice`, `actions.execute`, `config.DEVICE_ID`.
- Produces:
  - `push.init() -> Promise<string>` (FCM token)
  - `push.onMessage(cb: (data) => void) -> void`
  - `index.start() -> Promise<void>` (đăng ký token + gắn listener chạy `actions.execute`)

- [ ] **Step 1: Viết `mobile/src/push.js`**

```js
import messaging from "@react-native-firebase/messaging";

// Xin quyền + lấy FCM token.
export async function init() {
  await messaging().requestPermission();
  return messaging().getToken();
}

// Nghe push cả foreground lẫn background. cb nhận payload data (action).
export function onMessage(cb) {
  messaging().onMessage(async (msg) => cb(msg.data));
  messaging().setBackgroundMessageHandler(async (msg) => cb(msg.data));
}
```

- [ ] **Step 2: Viết failing test `mobile/__tests__/index.test.js`**

```js
jest.mock("../src/push", () => ({
  init: jest.fn(),
  onMessage: jest.fn(),
}));
jest.mock("../src/api", () => ({ registerDevice: jest.fn() }));
jest.mock("../src/actions", () => ({ execute: jest.fn() }));
jest.mock("react-native", () => ({ Platform: { OS: "android" } }), { virtual: true });

import { init, onMessage } from "../src/push";
import { registerDevice } from "../src/api";
import { execute } from "../src/actions";
import { start } from "../src/index";

describe("start", () => {
  beforeEach(() => jest.clearAllMocks());

  test("lấy token, đăng ký device, gắn listener execute", async () => {
    init.mockResolvedValue("fcm-tok-123");
    await start();
    expect(registerDevice).toHaveBeenCalledWith("device-001", "fcm-tok-123", "android");
    expect(onMessage).toHaveBeenCalledWith(execute);
  });
});
```

- [ ] **Step 3: Chạy test — FAIL**

Run: `cd mobile && npx jest index.test.js`
Expected: FAIL — không tìm thấy `../src/index`.

- [ ] **Step 4: Viết `mobile/src/index.js`**

```js
import { Platform } from "react-native";
import { init, onMessage } from "./push";
import { registerDevice } from "./api";
import { execute } from "./actions";
import { DEVICE_ID } from "./config";

// Gọi 1 lần khi app khởi động.
export async function start() {
  const token = await init();
  await registerDevice(DEVICE_ID, token, Platform.OS);
  onMessage(execute);
}
```

- [ ] **Step 5: Chạy test — PASS**

Run: `cd mobile && npx jest index.test.js`
Expected: PASS.

- [ ] **Step 6: Chạy toàn bộ Jest**

Run: `cd mobile && npx jest`
Expected: tất cả PASS (api + actions + index).

- [ ] **Step 7: Viết `mobile/README-flow.md`**

```markdown
# Mobile app (React Native, Android) — luồng chạy

## Vai trò
Nhận FCM push từ server, tra danh bạ, tự gọi điện / nhắn tin (Android).

## Luồng
1. App khởi động -> `start()` (src/index.js)
2. `push.init()` xin quyền thông báo + lấy FCM token
3. `api.registerDevice(DEVICE_ID, token, "android")` -> POST /register-device
   (DEVICE_ID phải trùng device_id MCU gửi khi POST /process)
4. `push.onMessage(execute)` gắn listener
5. Server (khi có lệnh gọi/nhắn) đẩy FCM data = {type, name, text?}
6. `actions.execute(payload)`:
   - `contacts.findNumber(name)` tra số trong danh bạ máy
   - type "call"    -> react-native-immediate-phone-call (quay số ngầm)
   - type "message" -> react-native-send-direct-sms (gửi SMS ngầm)

## Quyền Android cần khai trong AndroidManifest.xml
- READ_CONTACTS   (tra danh bạ)
- CALL_PHONE      (immediate phone call)
- SEND_SMS        (send direct sms)
- POST_NOTIFICATIONS (Android 13+, nhận push)

## Cách test trên máy Android thật
1. Cài deps: `cd mobile && npm install`
2. Firebase: thêm google-services.json (Android) vào project RN.
3. Cấp quyền runtime (Contacts/Phone/SMS) khi app hỏi.
4. Chạy: `npm run android`
5. Gửi thử FCM data message qua Firebase Console (hoặc server thật) với
   payload {type:"call", name:"<tên có trong danh bạ>"} -> máy tự quay số.

## Giới hạn
- Chỉ Android. iOS bị Apple chặn auto call + SMS ngầm (hoãn).
- Push thật cần server nối firebase-admin (hiện server đang stub log).
```

- [ ] **Step 8: Commit**

```bash
git add mobile/src/push.js mobile/src/index.js mobile/README-flow.md \
  mobile/__tests__/index.test.js
git commit -m "feat(mobile): FCM push init + start wiring + flow README"
```

---

## Task 15: Root README (chạy + test cả hệ thống)

**Files:**
- Create: `README.md`

**Interfaces:** none (tài liệu).

- [ ] **Step 1: Viết `README.md`**

```markdown
# Blind-Assist Audio Server

Server hỗ trợ người khiếm thị: MCU gửi ảnh + audio (WAV) + device_id,
server STT -> intent -> handler -> TTS, trả audio/wav. Lệnh gọi/nhắn đẩy
FCM push tới mobile app Android.

## Server
### Cài
    python -m pip install -r requirements.txt
### Chạy
    python -m uvicorn app:app --reload
Docs: http://127.0.0.1:8000/docs
### Test
    python -m pytest -v

## Endpoint
- GET  /health
- POST /register-device  (Form: device_id, fcm_token, platform)
- POST /process          (File: image, audio; Form: device_id) -> audio/wav

## 8 chức năng (auto-detect từ giọng nói)
ocr, translate, find, money, space, datetime (thật), call, message.
AI dùng stub — lắp model/API sau (interface cố định trong pipeline/ và handlers/).

## Mobile
Xem mobile/README-flow.md (React Native, Android).

## Trạng thái
- STT / TTS / OCR / translate / find / money / space: STUB.
- datetime: thật. push: stub log (TODO firebase-admin).
```

- [ ] **Step 2: Chạy lại toàn bộ test (server + mobile)**

Run:
```bash
python -m pytest -v
cd mobile && npx jest
```
Expected: tất cả PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add root README (run + test instructions)"
```

---

## Self-Review

**Spec coverage:**
- 5 AI chức năng → Task 5. datetime/call/message → Task 6, 7. ✅
- OCR dịch có điều kiện → Task 5 (test nguyên văn/chuyên ngành). ✅
- Translate hướng VI↔EN → Task 5. ✅
- STT/intent/TTS → Task 2, 3, 4. ✅
- device_id + /register-device + devices store → Task 8, 11. ✅
- FCM push server (stub) + không-push-khi-lỗi → Task 9, 10, 11. ✅
- Mobile RN Android: register, push, contacts, call/SMS native → Task 12–14. ✅
- Requirement lib test gọi/nhắn thật (immediate-phone-call, send-direct-sms, contacts) → Task 12–13 + README quyền + cách test máy thật. ✅
- Server requirements → Task 1 requirements.txt. ✅
- Xử lý lỗi luôn trả audio/wav → Task 11 (test thiếu field). ✅

**Placeholder scan:** Mọi bước có code/lệnh thật. `# TODO` là điểm cắm model/API tương lai (đúng thiết kế stub), không phải placeholder plan. ✅

**Type consistency:** `handle(image, command_text) -> Result` đồng nhất mọi handler; `Result(speech, action)`; `push.send(device_id, action) -> bool`; `router.process(image, audio, device_id) -> bytes`; mobile `execute(action) -> Promise<bool>`, `findNumber(name) -> Promise<str|null>`, `registerDevice(...) -> Promise<bool>`. Khớp giữa các task. ✅
