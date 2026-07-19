# Thiết kế — Server hỗ trợ người khiếm thị (FastAPI)

Ngày: 2026-07-19

## Mục tiêu

Vi điều khiển (MCU) gửi **ảnh + audio** lên server. Server xử lý, trả về **1 file
audio WAV** (tiếng Việt) là kết quả. Giai đoạn này hoàn thiện **flow đầu-cuối**:
mọi bước AI được stub (trả dữ liệu giả), interface cố định để lắp model/API thật
sau mà không sửa router.

## Phạm vi

5 chức năng, chọn tự động từ giọng nói người dùng:

**Nhóm AI (xử lý ảnh/lời nói):**

| Chức năng | Nguồn dữ liệu | Xử lý bằng | Kết quả |
|-----------|---------------|-----------|---------|
| OCR       | ảnh           | model     | Đọc chữ trong ảnh. Mặc định dịch sang Việt; nếu chữ chuyên ngành / đã tiếng Việt / lệnh yêu cầu "nguyên văn" → đọc thô, **không dịch** |
| Translate | lời nói (STT) | model     | Dịch câu người nói: VI→EN hoặc EN→VI (hướng tự nhận) |
| Find object | ảnh + lời nói | API vision | Tìm đồ vật người hỏi, chỉ hướng ra |
| Read money | ảnh          | API vision | Đọc mệnh giá tiền |
| Describe space | ảnh       | API vision | Miêu tả không gian trước mặt |

**Nhóm tiện ích (device / server utility):**

| Chức năng | Loại | Kết quả |
|-----------|------|---------|
| Hỏi ngày giờ | server tự trả | Audio đọc ngày/giờ hiện tại |
| Gọi điện | điện thoại hành động | Audio "Đang gọi <tên>" cho MCU **+ FCM push** action `call` tới mobile app → app quay số |
| Nhắn tin | điện thoại hành động | Audio "Đã nhắn <tên>" cho MCU **+ FCM push** action `message` tới mobile app → app gửi SMS |

Danh bạ nằm **trên điện thoại**; server chỉ đẩy **tên** trong action, mobile app tự map tên→số.

**Kiến trúc 2 thiết bị (cùng `device_id`):**
- **MCU** (kính/thiết bị): gọi `POST /process` (kèm `device_id`), nhận + phát audio.
- **Mobile app** (React Native, trên điện thoại người dùng): đăng ký FCM token theo
  `device_id`; nhận **push** từ server; thực thi gọi/nhắn bằng danh bạ máy.

MCU không nhận action nữa — server **chủ động đẩy FCM** tới mobile app cùng `device_id`.

Ngoài phạm vi giai đoạn này: cài model thật, nối API thật, xác thực, đa người dùng,
hàng đợi/job. Chỉ tạo thư mục `models/` trống + logic stub.

## Quyết định đã chốt

- Định tuyến: **tự detect chức năng từ giọng nói** (STT → intent).
- Giao thức: **1 request trả luôn audio** (đồng bộ, không job/polling).
- Thiết bị **luôn gửi cả ảnh + audio** mỗi request, kèm **`device_id`**.
- Ngôn ngữ chính: **tiếng Việt** (audio in và out).
- Audio: **WAV** cả 2 chiều.
- Lệnh điện thoại → server đẩy **FCM/APNs push** tới mobile app.
- MCU + mobile app ghép đôi bằng **cùng `device_id`**.
- Mobile app: **React Native** (iOS + Android, chưa cần UI, chỉ luồng).

## Luồng dữ liệu

```
[Đăng ký 1 lần] Mobile app  POST /register-device {device_id, fcm_token, platform}
                            -> server lưu map device_id -> fcm_token

[Mỗi lệnh]
MCU  POST /process  (multipart: image=<file>, audio=<file wav>, device_id=<str>)
  │
  ├─ 1. stt.transcribe(audio_bytes)      -> command_text   [stub]
  ├─ 2. intent.detect(command_text)      -> intent name     [stub, khớp keyword]
  ├─ 3. router.route(intent) -> handler.handle(image, command_text) -> Result(speech, action?)
  │       ocr / translate / find / money / space / datetime / call / message
  ├─ 4. nếu result.action != None:
  │       push.send(device_id, result.action)   [stub FCM] -> mobile app
  ├─ 5. tts.synthesize(result.speech)    -> wav_bytes        [stub]
  └─ 6. Response cho MCU: audio/wav (StreamingResponse)   # chỉ audio, không action

         Mobile app (nền) nhận FCM push:
           action.type == "call"    -> tra danh bạ tên->số -> quay số
           action.type == "message" -> tra danh bạ -> gửi SMS

Lỗi bất kỳ bước -> tts.synthesize("<câu báo lỗi tiếng Việt>") -> trả audio/wav.
Lỗi -> KHÔNG push (điện thoại không hành động nhầm).
Không bao giờ trả JSON lỗi trần (người khiếm thị phải nghe được).
```

## Cấu trúc thư mục

```
Sever_test/
├── app.py                  # FastAPI: /health, /process, /register-device
├── requirements.txt
├── config.py               # env: model dir, API key, FCM key, storage
├── schemas.py              # hằng tên intent, Result, kiểu dữ liệu nội bộ
├── pipeline/
│   ├── __init__.py
│   ├── stt.py              # transcribe(audio: bytes) -> str          [stub]
│   ├── intent.py           # detect(text: str) -> str                 [stub keyword]
│   ├── tts.py              # synthesize(text: str) -> bytes (wav)      [stub]
│   ├── push.py             # send(device_id, action) -> gửi FCM        [stub]
│   ├── devices.py          # map device_id -> fcm_token (in-memory)    [stub store]
│   └── router.py           # route(intent) -> handler; orchestrate 1 lần gọi
├── handlers/
│   ├── __init__.py
│   ├── ocr.py              # model stub — dịch có điều kiện
│   ├── translate.py        # model stub — VI↔EN
│   ├── find_object.py      # API stub
│   ├── read_money.py       # API stub
│   ├── describe_space.py   # API stub
│   ├── datetime_util.py    # server tự trả ngày giờ (không cần model)
│   ├── call_phone.py       # trả speech + action call [tên]
│   └── send_message.py     # trả speech + action message [tên]
├── models/                 # file model tải sau (trống giờ)
│   ├── ocr/.gitkeep
│   └── translate/.gitkeep
├── storage/                # lưu tạm file in/out để debug (tùy chọn)
│   └── .gitkeep
├── mobile/                 # module React Native (xem mục Mobile app)
│   ├── package.json
│   ├── README-flow.md      # mô tả luồng chạy
│   └── src/
│       ├── index.js        # khởi tạo: đăng ký token + gắn listener push
│       ├── config.js       # SERVER_URL, DEVICE_ID
│       ├── api.js          # POST /register-device
│       ├── push.js         # FCM: xin quyền, lấy token, nghe message   [stub native]
│       ├── contacts.js     # tra tên -> số (react-native-contacts)     [stub]
│       └── actions.js      # thực thi call / sms từ payload             [stub native]
└── docs/superpowers/specs/ # tài liệu này
```

## Giao kèo interface (cố định — không đổi khi lắp model thật)

```python
# pipeline/stt.py
def transcribe(audio: bytes) -> str: ...          # audio wav -> câu lệnh

# pipeline/intent.py
def detect(text: str) -> str: ...                 # -> INTENT.* (schemas)

# pipeline/tts.py
def synthesize(text: str) -> bytes: ...           # text VI -> wav bytes

# handlers/*.py  (mọi handler cùng chữ ký, cùng kiểu trả)
def handle(image: bytes, command_text: str) -> Result: ...
```

### schemas.py — intent + Result

```python
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
    speech: str                      # câu tiếng Việt -> TTS
    action: dict | None = None       # None = chỉ audio;
                                     # có = đẩy FCM push tới mobile app
    # ví dụ action: {"type": "call", "name": "Mẹ"}
    #               {"type": "message", "name": "Bố", "text": "..."}
```

Router gom mọi handler về cùng `Result`. `app.py`: nếu `result.action != None` thì
gọi `push.send(device_id, result.action)` trước khi trả audio cho MCU.

```python
# pipeline/push.py
def send(device_id: str, action: dict) -> bool: ...   # tra token, gửi FCM [stub]

# pipeline/devices.py
def register(device_id: str, fcm_token: str, platform: str) -> None: ...
def get_token(device_id: str) -> str | None: ...      # in-memory dict [stub store]
```

## Chi tiết từng module (giai đoạn stub)

- **stt.transcribe**: trả chuỗi cố định, ví dụ `"đọc chữ giúp tôi"` (đủ để intent
  chạy). Đánh dấu `# TODO: nối model STT tiếng Việt`.
- **intent.detect**: khớp keyword tiếng Việt trên text → intent.
  vd "đọc/chữ"→OCR, "dịch"→TRANSLATE, "tìm/đâu"→FIND, "tiền/mệnh giá"→MONEY,
  "xung quanh/trước mặt/không gian"→SPACE, "mấy giờ/ngày mấy/hôm nay"→DATETIME,
  "gọi/gọi cho"→CALL, "nhắn/nhắn tin"→MESSAGE. Không khớp → mặc định SPACE.
- **handlers/** (mỗi hàm trả `Result`):
  - `ocr`: dịch có điều kiện. Mặc định trả kết quả kèm dịch Việt. Nếu
    `command_text` chứa "nguyên văn"/"chuyên ngành" hoặc chữ đoán là tiếng Việt →
    đọc thô, không dịch. Stub trả chuỗi giả ghi rõ chế độ (dịch / nguyên văn).
  - `translate`: đọc `command_text`, đoán hướng VI↔EN (có ký tự tiếng Việt →
    VI→EN, ngược lại EN→VI), trả chuỗi giả kèm hướng.
  - `find/money/space`: chuỗi giả rõ ràng, vd `"[SPACE] chưa nối API"`.
  - `datetime_util`: **thật luôn** — trả `Result(speech=<ngày giờ hiện tại VI>)`.
    Không stub (không cần model/API).
  - `call_phone`: rút tên từ `command_text` (sau chữ "gọi"), trả
    `Result(speech="Đang gọi <tên>", action={"type":"call","name":<tên>})`.
  - `send_message`: tương tự, `action={"type":"message","name":<tên>,"text":...}`,
    speech "Đã nhắn <tên>".
- **tts.synthesize**: sinh WAV hợp lệ tối thiểu (vd 1 đoạn im lặng/beep bằng
  `wave` chuẩn thư viện) để MCU nhận file WAV thật, phát được. `# TODO: TTS thật`.
- **devices.register / get_token**: dict in-memory `{device_id: fcm_token}`.
  `# TODO: thay bằng DB/Redis khi nhiều thiết bị`.
- **push.send**: tra token theo `device_id`; giai đoạn stub chỉ **log** payload
  (`device_id`, `action`) và trả `True`. `# TODO: gọi FCM/APNs thật (firebase-admin)`.
  Token không có → log cảnh báo, trả `False` (không chặn audio về MCU).

## Mobile app (React Native — mô tả luồng, chưa UI)

Mục tiêu giai đoạn này: **luồng chạy đúng**, native call/SMS/FCM để stub + `# TODO`.

- **index.js**: khi khởi động → `push.init()` (xin quyền, lấy FCM token) →
  `api.registerDevice(DEVICE_ID, token, platform)` → gắn listener push.
- **config.js**: `SERVER_URL`, `DEVICE_ID` (khớp id MCU dùng).
- **api.js**: `registerDevice()` = `POST {SERVER_URL}/register-device`.
- **push.js**: `init()` xin quyền + lấy token (stub trả token giả);
  `onMessage(cb)` đăng ký nhận push. `# TODO: @react-native-firebase/messaging`.
- **contacts.js**: `findNumber(name) -> phone` tra danh bạ máy (stub trả số giả).
  `# TODO: react-native-contacts + quyền đọc danh bạ`.
- **actions.js**: `execute(action)`:
  - `call`: `number = contacts.findNumber(action.name)` → mở quay số
    (`Linking.openURL("tel:"+number)`). Stub log.
  - `message`: `number = ...` → gửi SMS (`sms:` hoặc lib). Stub log.
  Không tra được tên → log "không tìm thấy <tên> trong danh bạ".
- **Luồng đầy-cuối**: push tới → `onMessage` → `actions.execute(payload)` →
  tra danh bạ → gọi/nhắn.

## Xử lý lỗi

- Thiếu field `image`, `audio` hoặc `device_id` → trả audio "Thiếu dữ liệu".
- Exception trong pipeline → log + trả audio "Có lỗi xảy ra, vui lòng thử lại".
- Luôn `Content-Type: audio/wav`, HTTP 200 (MCU chỉ phát audio, không parse mã lỗi).
- Lỗi → **không** push (điện thoại không hành động nhầm).
- `push.send` thất bại (chưa đăng ký token) → vẫn trả audio bình thường cho MCU.

## Kiểm thử

- `/health` trả `{"status":"ok"}`.
- `POST /register-device` lưu token; `devices.get_token` trả đúng token.
- `POST /process` với ảnh giả + wav giả + device_id → nhận về `audio/wav`, dài > 0.
- Test từng module stub trả đúng kiểu (`Result` / bytes / str).
- Test intent.detect: mỗi keyword → đúng intent (8 intent).
- Test handler action: intent CALL/MESSAGE → `push.send` được gọi đúng
  `device_id` + action (mock/spy push.send).
- Test intent không-action (ocr…) → `push.send` **không** được gọi.
- Test datetime_util trả câu có ngày/giờ (handler thật).
- Test thiếu field → vẫn trả audio/wav (không crash 500), không push.
- Test push.send khi chưa đăng ký token → trả False, `/process` vẫn trả audio.

## config.py

Đọc từ biến môi trường, có mặc định:
- `STORAGE_DIR` (mặc định `./storage`)
- `OCR_MODEL_DIR`, `TRANSLATE_MODEL_DIR`
- `VISION_API_KEY` (rỗng giờ; handler API stub không dùng)
- `FCM_CREDENTIALS` (đường dẫn key firebase; rỗng giờ; push stub không dùng)

## requirements.txt

```
fastapi
uvicorn[standard]
python-multipart
```
(Model/API lib thêm sau khi cài thật.)
