# Spec: hội thoại nhiều lượt, trích thông tin, và ngữ cảnh

Ngày lập: 2026-08-19 · Trạng thái: **chờ duyệt, chưa code dòng nào**

Tài liệu này liệt kê **từng chức năng**: luồng đang chạy hôm nay, chỗ hỏng, và
việc sẽ sửa. Đọc để duyệt hoặc bổ sung trước khi bắt tay.

---

## 0. Tóm tắt
| Vai trò | Đường dẫn | Cổng |
|---|---|---|
| Server kính (repo này) | `D:\Study\innostar\Sever_test` | 8000, ra ngoài qua Cloudflare tunnel |
| Server app | `D:\Study\innostar\app_demo_backend\apps\backend` | 8001 |
| Firmware | `D:\Study\innostar\your-eyes-esp32-firmware` | ESP32-S3-CAM (OV2640) |
| App Android | `app_demo_backend\apps\android` (Kotlin) | nhận FCM — xem **mục 26** |
|Postgres | docker start app-demo-postgres-1 |


| Nhóm | Nội dung | Vì sao |
|---|---|---|
| **C** | Vị trí: chống câm, chống chết thread | Vị trí đang hỏng 100%, và A3/A6 phụ thuộc nó |
| **A** | Trích slot: tách `song`/`artist`, chuẩn hoá `destination` | Query sai thì action sai |
| **E** | Ngữ cảnh cho OCR / mô tả cảnh | OCR đang không nhận câu hỏi của người dùng |
| **D** | Hỏi lại thống nhất + so khớp danh bạ | 6 chỗ hỏi rồi vứt câu trả lời |
| **B** | Session, pending, bỏ fast-bypass | Bug nặng nhất, nhưng đụng router + phải viết lại test |
| **H** | OCR: model riêng, hướng dẫn chụp, hướng ảnh (**mục 25**) | Có ca thật OCR không đọc ra chữ nào |
| **R** | Đặt xe: đọc giá và loại xe trước khi bàn giao sang app (**mục 12**) | Người khiếm thị đang xác nhận mù một khoản tiền thật |

**Thứ tự thi công: C → A → E → D → B.** Nhóm **H** độc lập với cả năm nhóm trên,
chạy song song được — xem thứ tự riêng ở cuối mục 25. Nhóm **R** phụ thuộc **C**
và bị chặn bởi một điều kiện ngoài kỹ thuật (quyền partner Farefeed) — xem mục
12 và mục 18.

Nhóm **W** (mục 28, cảnh báo vật cản thời gian thực) là **tính năng mới**,
không thuộc năm nhóm sửa lỗi trên. Phụ thuộc **T18** (kênh downlink) và cần hai
module firmware mới — xem mục 28.

Ba nguyên tắc xuyên suốt, mọi mục dưới đây đều quy về:

1. **Trạng thái là gợi ý cho bộ phân loại, không phải hàng rào ở router.**
   Người dùng phải nói được bất cứ gì, bất cứ lúc nào.
2. **Cache thứ đứng yên (chữ trên giấy), không bao giờ cache thứ di chuyển
   (không gian, vật cản).**
3. **`emergency_call` không đi qua bất kỳ bước xác minh nào.** Ngoại lệ tuyệt
   đối, phải viết tường minh trong code chứ không để rơi vào mặc định.

---

## 1. Điều phối chung (router)

### Hiện tại

`pipeline/router.py:69-85` — `_resolve()` mở đầu bằng hai nhánh tắt:

```python
if state.get("music_playing"):
    yield from music.handle_stop(...)   # không STT, không intent
    return
if state.get("navigating"):
    yield from navigation.handle_stop(...)
    return
```

Nhạc đang phát → **mọi** câu nói đều thành "tắt nhạc". Chỉ đường đang chạy →
mọi câu thành "dừng chỉ đường".

Không có bypass thì luồng bình thường là:
STT → `intent.detect_with_params()` → gate chất lượng ảnh → handler → stream text
→ `app.py` gọi TTS.

### Vấn đề

- Đang nghe nhạc **không** hỏi được giờ, không gọi được ai, không hỏi được vật
  cản, **không gọi được cấp cứu**.
- Đang chỉ đường **không** hỏi được `hazard`/`space` — đúng thứ người khiếm thị
  cần nhất khi đang đi bộ.
- Bypass giết luôn cơ chế ngữ cảnh đã viết sẵn: `_CONTEXT_TEMPLATE` và
  `_apply_state` trong `pipeline/intent.py` chỉ chạy khi **không** có gì đang
  chạy — tức lúc chúng vô dụng. Nhánh "cả hai cùng chạy → chọn `most_recent`" là
  **dead code**, không đường nào tới được.
- `tests/test_device_state.py:138-172` đang khoá đúng hành vi này.

### Cải thiện

- **B1** — Bỏ hai nhánh bypass. Thay bằng **barge-in cục bộ**: regex
  `tắt nhạc|dừng nhạc|dừng chỉ đường|dừng lại|thôi|im lặng`, chỉ chạy khi có
  task đang chạy. ~0ms, giữ nguyên độ nhanh của "tắt nhạc", nhưng không nuốt
  các câu khác.
- Viết lại `tests/test_device_state.py:138-172`.

---

## 2. Phân loại ý định (intent)

### Hiện tại

`pipeline/intent.py` — hai tầng:

1. **SetFit cục bộ** (`intent_local.classify`, ONNX int8, ~8ms). Hai ngưỡng:
   `confidence` và `margin`. Đủ chắc + nhãn không cần tham số → trả ngay.
2. **Gemini** (`GEMINI_INTENT_MODEL = gemini-3.1-flash-lite`, ~0.9s) — cho nhãn
   cần trích slot, hoặc khi tầng 1 không chắc.

`_context_block()` chèn trạng thái thiết bị (nhạc / chỉ đường / chuyến chờ xác
nhận) vào prompt. `_apply_state()` áp cùng bộ luật đó ở đường cục bộ.

### Vấn đề

- **Không có "hệ thống vừa hỏi gì" trong prompt.** Câu trả lời trần trụi
  ("Sơn Tùng", "đúng rồi", "Bưu điện", "mẹ") không có chỗ bám. Chỉ có đúng một
  luật hardcode vá cho ca ca sĩ (`pipeline/intent.py:184-187`).
- **SetFit chặn đường.** "Sơn Tùng M-TP" nhiều khả năng ra `chat` với confidence
  cao → `chat` nằm trong `_PARAM_FREE` → trả về ngay, Gemini không bao giờ được
  hỏi. Pending kẹt vĩnh viễn.
- **Prompt không có vị trí hiện tại.** "Bách Khoa" là Hà Nội hay TP.HCM? `chat`
  thì được cấp vị trí (`handlers/chat.py:284`), còn `nav_start`/`ride_quote` —
  hai nhãn cần vị trí nhất — thì không.
- **Prompt không nói text đến từ STT.** STT là Zipformer-vi 30M int8
  (`pipeline/stt.py:11`), sai tên riêng liên tục. Nhưng prompt trích slot không
  có một chữ nào bảo model **sửa lỗi nhận dạng** — nó đang trích span nguyên
  văn, tức chép lại đúng lỗi rồi đem đi query.
- **Không có nhãn thoát.** Không có `cancel` ("thôi bỏ đi") và `repeat`
  ("gì cơ", "nói lại đi"). Người khiếm thị cần cả hai.

### Cải thiện

- **A1** — Đổi schema params:
  ```python
  "song_title", "artist", "song_is_specific",
  "destination", "destination_raw",
  "slot_confidence": {"enum": ["high", "low"]},
  "focus": {"enum": ["left", "right", "front", "behind"]},
  ```
  Giữ `song` cũ làm alias trong lúc chuyển.
- **A2** — Thêm khối chỉ dẫn sửa lỗi STT vào prompt:
  > Câu lệnh do máy nhận dạng giọng nói tiếng Việt (model nhỏ) ghi lại. TÊN
  > RIÊNG bị nghe sai rất nhiều. Khi trích slot, SỬA về dạng đúng mà bạn tin
  > người dùng định nói, đừng chép lại lỗi: "Bát Khoa" → "Bách Khoa". Không sửa
  > được thì giữ nguyên và đặt `slot_confidence = "low"`. Không bịa số nhà, tên
  > đường, tên album không nghe thấy.
- **A3** — Bơm vị trí hiện tại vào `_context_block()`, một dòng, dùng lại
  `chat._location_text()`.
- **B3** — Có pending → **bỏ qua SetFit**, đi thẳng Gemini kèm khối:
  > Hệ thống VỪA HỎI: "{câu hỏi}". Câu vừa nói nhiều khả năng là câu trả lời.
  > Nếu đúng → intent = {intent}, trích slot "{slot}". Nếu là câu huỷ → `cancel`.
  > Nếu là việc hoàn toàn khác → phân loại bình thường, bỏ qua pending.

  SetFit không được train cho câu trả lời trần trụi; ép nó quyết chính là nguồn
  bug. +0.9s nhưng chỉ ở lượt hiếm.
- **B5** — Thêm nhãn `cancel` và `repeat`.

---

## 3. Trạng thái phiên (session)

### Hiện tại

`handlers/action_flow.py` — hai dict module-level:

- `_LAST_IDS` (dòng 61): `navigation_id`, `quote_id`, và hai khoá pending tự
  phát `pending_song_title`, `pending_ride_destination`.
- `_ACTIVE` (dòng 88): việc đang chạy → mốc `time.monotonic()`.

`mark_active()` (dòng 134) gọi `_ACTIVE.clear()` trước khi set → **Single Active
State**, nhạc và chỉ đường loại trừ nhau.

`device_state()` (dòng 112) trả `{music_playing, navigating, ride_quote_pending,
most_recent}`.

Lịch sử hội thoại nằm riêng ở `handlers/chat.py:226` — `deque(maxlen=6)`,
TTL 600s, **chỉ ghi lượt `chat`**, **chỉ dùng cho prompt `chat`**.

### Vấn đề

- **Pending không có TTL.** `forget()` chỉ được gọi khi luồng đi đúng đường.
  Người dùng bỏ ngang → `pending_song_title` sống mãi. Ngày mai nói "phát nhạc
  Đen Vâu" → nhánh `if pending:` (`handlers/music.py:87`) ghép thành
  `"bài-cũ - Đen Vâu"`.
- **Không có đường huỷ pending** bằng lời.
- **Pending là chuỗi tự do**, không có cấu trúc, không biết đang chờ slot nào
  cho intent nào.
- **State toàn cục**, không khoá theo thiết bị. `VISIONCARE_DEVICE_ID` hardcode
  (`config.py:200`). Hai kính = trộn session.
- **Lịch sử không ghi lượt action.** "Vừa nãy tôi đặt xe đi đâu?" → chịu.
- **Single Active State sai thực tế**: đi bộ + nghe nhạc là ca dùng thật.

### Cải thiện

- **B2** — `Pending` dataclass + TTL 90s:
  ```python
  @dataclass
  class Pending:
      slot: str          # "contact_name" | "destination" | "song_title" | ...
      intent: str        # intent chạy lại khi có câu trả lời
      known: dict        # params đã thu được
      question: str      # nguyên văn câu vừa hỏi (dùng cho "nói lại đi")
      candidates: list   # ứng viên danh bạ, nếu có
      asked_at: float
      ttl: float = 90.0
  ```
- **B4** — Lịch sử dùng chung, ghi **cả lượt action**, không riêng `chat`.
- **B6** — Session khoá theo `device_id`.
- **B7** — Bỏ `_ACTIVE.clear()` ở `handlers/action_flow.py:135` → nhạc và chỉ
  đường chạy song song được.

---

## 4. Đọc chữ (OCR)

### Hiện tại

`handlers/ocr.py:13-20` — hai phép kiểm tra chuỗi rồi **vứt `command_text`**:

```python
raw = command_text.lower()
if "nguyên văn" in raw:      mode = ocr.Mode.RAW
elif "chuyên ngành" in raw:  mode = ocr.Mode.SPECIALIZED
else:                        mode = ocr.Mode.NORMAL
return ocr.read_stream(image, mode)
```

`models/ocr/prompts.py:38` — `build(mode)` **không nhận `command_text`**. Prompt
luôn là "Đọc toàn bộ chữ trong ảnh".

`models/ocr/__init__.py:31` — `read_stream` là generator đẩy thẳng ra TTS. Có mốc
quy ước `KHONG_CO_CHU` cho ảnh không có chữ.

Đây là **một lượt gọi Gemini VLM**, không phải PaddleOCR — không có bounding box,
không có cấu trúc dòng.

### Vấn đề

- **"Đọc dòng thứ 2" → đọc cả trang.** Model chưa từng được hỏi. Không kết luận
  được nó làm tốt hay không — nó không nhận được câu hỏi.
- **Chữ đọc xong là mất.** Không có transcript ở đâu.
- **Bẫy ảnh mới:** lượt sau kính **chụp ảnh mới**. Người dùng đã hạ tay, nghiêng
  máy, xê dịch tờ giấy. OCR lại ảnh mới → **số dòng khác** → "dòng thứ 2" của
  lượt trước không còn là dòng thứ 2. Người khiếm thị **không có cách nào biết**
  hai lần chụp lệch nhau.
- **"Khái niệm này là gì" đi về `chat`, không về `ocr`.** `handlers/chat.py:276`
  dựng prompt không có transcript, không có ảnh. Trỏ "chữ này", "mục kia" thành
  vô nghĩa.

### Cải thiện

- **E1** — `build(mode, command_text)`. Thêm khối: *"Người dùng hỏi: '{…}'. Nếu
  câu hỏi chỉ định một phần cụ thể (dòng thứ mấy, đoạn nào, mục nào), chỉ đọc
  đúng phần đó. Không chỉ định thì đọc toàn bộ."*
- **E2** — Cache transcript trong session: `last_ocr: {text, taken_at}`, TTL
  ~5 phút. Gom mảnh trong lúc stream, giống `handlers/chat.py:299` `_remember`.
- **E3** — Câu hỏi tiếp theo trả lời **trên text đã cache, bỏ hẳn ảnh**. Một
  lượt Gemini text-only: nhanh hơn nhiều và tránh bẫy lệch khung hình.
- **E4** — Bơm transcript vào prompt `chat` (`handlers/chat.py:276`):
  > Người dùng vừa nhờ đọc một văn bản. Nội dung: "{…}". Nếu câu hỏi trỏ vào văn
  > bản này ("chữ này", "khái niệm đó", "mục kia") thì trả lời dựa vào nó. Không
  > liên quan thì bỏ qua.

  Câu "bỏ qua nếu không liên quan" là **bắt buộc** — thiếu nó thì hỏi "mấy giờ
  rồi" cũng bị kéo về tờ giấy.

> Mục này giả định OCR **đã đọc được chữ**. Chuyện đọc được hay không — model
> nào, ảnh xoay ngược, chữ quá nhỏ trong khung — nằm ở **mục 25**. Hai mục độc
> lập, làm song song được.

---

## 5. Mô tả không gian (space)

### Hiện tại

`handlers/describe_space.py:69` — `handle(image, command_text)` nhận
`command_text` nhưng **không dùng**. Prompt cố định, đã qua nhiều vòng đo:
ngân sách 25-40 từ, 3 phần bắt buộc theo thứ tự, 6 điều cấm (mỗi điều đến từ
một lần hỏng đo được, xem comment dòng 6-12).

### Vấn đề

"Bên trái có gì" và "trước mặt có gì" ra **câu y hệt nhau**.

Nhưng **không được** chữa bằng cách dán `command_text` vào prompt — làm vậy là
thổi bay ngân sách 40 từ và bộ luật thứ tự đã đo.

### Cải thiện

- **E5** — Trích **một slot ràng buộc** `focus: left | right | front | behind |
  null`, chèn thành một dòng vào prompt. Giữ nguyên mọi luật, thêm đúng một bậc
  tự do có ích.
- **Không** đưa lịch sử hội thoại vào. Ảnh mới mỗi lượt; "cái ghế bên trái" của
  30 giây trước có thể đã không còn ở đó — mô tả cũ không phải context, nó là
  **thông tin sai**.

---

## 6. Cảnh báo vật cản (hazard)

### Hiện tại

`handlers/describe_hazard.py:14` — bỏ qua `command_text`, prompt cố định 1-2 câu,
cấm mô tả màu sắc và chi tiết thị giác.

### Vấn đề

Không có. **Đây là hành vi đúng.**

### Cải thiện

- **E6** — **Không đổi logic.** Chỉ thêm comment giải thích vì sao **cố ý**
  không nhận context:

  > Đây là chức năng an toàn: nó phải báo **mọi** vật cản trong khung hình. Nhét
  > câu hỏi người dùng vào là làm model thiên về thứ họ hỏi, và **giảm báo cáo
  > thứ họ không hỏi** — đúng cái sắp làm họ vấp.

  Ghi rõ để lần refactor sau không ai "cải tiến" nó.

---

## 7. Tìm đồ vật (find) và Đọc tiền (money)

### Hiện tại

- `handlers/find_object.py:26` — **có** dùng `command_text` (`{command_text}`
  trong prompt). Handler ảnh duy nhất làm đúng.
- `handlers/read_money.py:19` — bỏ qua `command_text`. Đúng: mệnh giá là mệnh
  giá.

### Vấn đề

Không có.

### Cải thiện

Không đổi. Ghi ở đây để rõ phạm vi: **hai chức năng này nằm ngoài spec.**

---

## 8. Trò chuyện (chat) và vị trí

### Hiện tại

`handlers/chat.py`:

- Prompt hệ thống dài, đã tinh chỉnh: cấm markdown, cố định xưng "tôi"/"bạn",
  1-3 câu, cấm bịa.
- `CHAT_ALWAYS_SEARCH=1` → Google Search gắn vào **mọi** lượt, model tự quyết có
  tra hay không. Tra hỏng (429) → nhánh dự phòng nói thẳng là chưa tra được.
- Vị trí do **thread nền** giữ nóng (`start_location_refresher`, dòng 199), nhịp
  240s. Đường xử lý request **chỉ đọc cache**, không bao giờ tự đi lấy.
- `_location_text()` (dòng 257): cache còn hạn → trả khối text; hết hạn hoặc
  chưa có → trả **chuỗi rỗng**.
- Lịch sử: `deque(maxlen=6)`, TTL 600s.

### Vấn đề — vị trí đang hỏng 100%

Bằng chứng, `logs/glasses8000.err.log`, **42/42 nhịp hỏng, 0 lần thành công**
suốt cả phiên 01:11 → 15:00:

```
14:56:07 INFO Vị trí không sẵn sàng: {'code': 'CURRENT_LOCATION_UNAVAILABLE',
              'message': 'No last known location on this device'}
14:56:07 INFO Chưa lấy được vị trí ở nhịp này, giữ toạ độ cũ
```

Chuỗi nhân quả: host trả lỗi → `get_device_location()` trả `None` →
`refresh_location_once()` "giữ toạ độ cũ" nhưng **không có toạ độ cũ nào**, cache
vẫn `(None, 0.0)` → `_location_text()` trả `""` → **prompt hoàn toàn không có vị
trí**.

**Lỗi gốc nằm ở app Android**, không ở server: `getLastKnownLocation()` trả null.
Server đang chạy đúng như thiết kế.

Nhưng 5 chỗ phía server biến nó thành lỗi câm và không tự hồi phục:

1. **Hỏng vĩnh viễn nhìn giống hỏng tạm thời** (dòng 155-158). `if not result:
   return False` gộp "mạng chớp một nhịp" với "GPS tắt đã 4 tiếng". Log giống hệt
   nhau 42 lần, không escalation.
2. **Người dùng không được báo** (dòng 257). Cache rỗng → `""`. Không có câu nào
   kiểu "chưa lấy được vị trí, hãy kiểm tra định vị". Tệ hơn:
   `_SEARCH_INSTRUCTION` vẫn bảo model "tra địa điểm quanh người dùng" trong khi
   prompt không có người dùng ở đâu → đúng kịch bản bịa quán phở mà comment dòng
   340-348 đã ghi lại.
3. **Nhịp 240s, không retry nhanh.** GPS bật lại lúc t+10s → vẫn chờ tới 4 phút.
4. **Thread nền chết là chết luôn** (dòng 159-176):
   ```python
   try:
       result = visioncare_client.get_device_location()
   except Exception:
       return False
   ...
   where = address or f"toạ độ {result['lat']}, {result['lng']}"   # NGOÀI try
   ```
   `result['lat']` nằm ngoài `try`. Host trả result thiếu `lat`/`lng` →
   `KeyError` → thoát khỏi `refresh_location_once` → thoát khỏi `loop()` →
   **thread chết im**. `_REFRESHER_STARTED = True` chặn luôn việc gọi lại. Vị trí
   chết tới khi restart server.
5. **`to_vn_time_str` luôn ném `NameError`** (dòng 118): dùng `timezone` và
   `timedelta` nhưng import ở dòng 6 chỉ có `UTC, datetime`. Bị `except Exception`
   nuốt. Chưa gây hại vì `vn_time` (dòng 164) gán rồi **không dùng ở đâu** — biến
   chết.

### Cải thiện

- **C1** — `_location_text()` trả **khối giải thích** khi cache rỗng, không trả
  `""`: nói thẳng chưa lấy được vị trí và **cấm model đoán địa điểm**. Đây là
  sửa quan trọng nhất vì nó cắt đường bịa.
- **C2** — Bọc `try/except` toàn thân `refresh_location_once` + trong `loop()`.
  Thread không được phép chết.
- **C3** — Backoff ngược khi hỏng: 15s → 30s → 60s, thành công rồi mới về 240s.
- **C4** — Đếm hỏng liên tiếp, `logger.error` khi ≥3 lần thay vì `INFO` mãi.
- **C5** — Xoá `vn_time` chết, hoặc thêm `timezone, timedelta` vào import.
- **B4** — Lịch sử dùng chung với các handler khác (xem mục 3).
- **E4** — Bơm transcript OCR vào prompt (xem mục 4).

### Việc phía Android (ngoài phạm vi repo này)

Đổi `getLastKnownLocation()` → `FusedLocationProviderClient.getCurrentLocation()`
để ép lấy fix mới thay vì trả null khi không có bản cũ. Kiểm tra quyền
`ACCESS_FINE_LOCATION` và battery restriction.

---

## 9. Gọi danh bạ (contact_call)

### Hiện tại

`handlers/phone.py:28-46`:

```python
name = params.get("contact_name")
if not name:
    yield _ASK_CONTACT          # "Bạn muốn gọi cho ai?"
    return                      # ...rồi quên sạch
yield from run_action("contact_call", "api/v1/service/contact/call",
                      {"name": name}, ack=f"Đang tìm số của {name}.", ...)
```

> 🔴 **Đoạn dưới đây SAI, đã kiểm lại ở mục 26.1:** app so khớp tên
> **bằng nhau tuyệt đối**, không có tìm mờ nào. Đọc 26.1 trước khi thi
> công nhóm D.

Host tự tìm mờ theo tên. Trùng nhiều người → `failed` với
`error.code = "MULTIPLE_CONTACTS_FOUND"` kèm `details.candidates[] {name,
phone_number}` (xem `endpoint.md:267-270`).

`endpoint.md:265` — có tham số `contact_id` để **bỏ qua tìm mờ** phía host.

### Vấn đề

1. **Hỏi rồi quên.** "Bạn muốn gọi cho ai?" không lưu pending. Người dùng đáp
   "mẹ" → intent = `chat` → Gemini tán gẫu về mẹ.
2. **`details.candidates[]` bị vứt.** `handlers/result_speech.py:181-184`:
   ```python
   error = data.get("error") or {}
   code = error.get("code", "")
   if code in _ERROR_SPEECH:
       return _ERROR_SPEECH[code]      # details.candidates[] chết ở đây
   ```
   Danh sách tên thật trong danh bạ đang nằm sẵn trong tay, bị thay bằng câu
   chung "vui lòng nói rõ hơn".
3. **Tên sai thì hậu quả xã hội, không sửa được sau.** STT Zipformer 30M không
   phân biệt nổi "Nguyệt" / "Nguyên" / "Nguyệt Anh". Ack **có** đọc tên
   (`handlers/phone.py:40`) nhưng **lệnh đã gửi rồi** — người dùng nghe tên sai
   lúc máy đang quay số.
4. **Tên đặt lạ.** "Em iu", "Bà xã", "Sếp Tổng", "Xe ôm hay đi" — nếu tìm mờ phía
   host trượt hẳn thì `CONTACT_NOT_FOUND` **không kèm ứng viên nào**, server
   không có gì để so khớp. Ngõ cụt. Không có endpoint liệt kê danh bạ trong toàn
   bộ `endpoint.md`.

### Cải thiện

- **D2** — Thiếu tên → đặt `Pending(slot="contact_name", intent="contact_call")`
  rồi mới hỏi. Trả lời "mẹ" chạy thẳng vào `contact_call`.
- **D6** — `speak_result` trả `(câu nói, pending | None)` thay vì chỉ chuỗi.
  `MULTIPLE_CONTACTS_FOUND` → dựng câu từ **ứng viên thật** + đặt pending.
- **D7** — File mới `handlers/contact_match.py`. Thuần hàm, không I/O → test được
  bằng bảng ca, không cần host.

  **Chuẩn hoá hai tầng** (STT sai theo hai kiểu khác nhau):
  ```python
  def norm(s):   # tầng 1: bỏ dấu thanh — dấu là thứ STT sai nhiều nhất
      s = unicodedata.normalize("NFD", s.lower())
      s = "".join(c for c in s if not unicodedata.combining(c))
      return re.sub(r"[^a-z0-9\s]", " ", s)

  def phon(s):   # tầng 2: gộp cặp phụ âm ASR tiếng Việt hay lẫn
      # digraph TRƯỚC, không thì "tr" bị "t" ăn mất
      # tr|ch -> C · ng|nh|n|l -> N · gi|d|r -> D · s|x -> S
  ```

  **Điểm** = `max(WRatio(norm), 0.95 * WRatio(phon))`. Hệ số 0.95 để bản viết
  đúng chính tả thắng khi hoà — `phon` cố ý mất thông tin, không nên thắng ngang.

  **Chính sách 3 ngưỡng** (số khởi điểm, phải đo lại trên danh bạ thật):

  | Điểm cao nhất | Hành vi |
  |---|---|
  | ≥ 88 **và** hơn ứng viên nhì ≥ 8 | Đọc lại **một** tên, chờ xác nhận: *"Bạn muốn gọi cho Nguyệt Anh, đúng không?"* |
  | ≥ 70 | Đọc **tối đa 3** tên, hỏi chọn |
  | < 70 | *"Không tìm thấy ai giống Nguyệt trong danh bạ. Bạn đọc lại tên giúp tôi."* |

  **Trần 3 tên là cứng.** Nghe bằng tai không giữ nổi 5 cái tên; đọc 5 tên rồi
  hỏi "ai" là bắt người dùng nhớ hộ một danh sách họ không nhìn thấy.

  **Tên trùng hệt nhau** → thêm đuôi số: *"Mẹ, số đuôi 456; Mẹ, số đuôi 789."*
  Chỉ đọc **3-4 chữ số cuối**, và chỉ khi tên trùng — đọc nguyên số điện thoại
  thành tiếng là phát tán thông tin cá nhân ra loa ở nơi công cộng, người khiếm
  thị không biết xung quanh có ai đang nghe.

  **Lượt chọn**: pending giữ `candidates[]`. Câu trả lời khớp theo **hai đường**,
  lấy đường nào ra kết quả: fuzzy lại vào danh sách (đọc tên), hoặc thứ tự
  ("cái đầu", "số một", "người thứ hai", "cái cuối").
- **D8** — Gọi lại bằng `contact_id`, không gửi `name` nữa.
- **D9** — Thêm `rapidfuzz` vào `requirements.txt` kèm comment lý do. Wheel C++
  thuần, ~1MB, không model, không torch. `difflib` stdlib làm được nhưng kém hẳn
  khi đảo thứ tự token ("Anh Nguyệt" vs "Nguyệt Anh") — đúng thứ hay gặp với tên
  Việt.

### Cần host bổ sung

| Mã | Yêu cầu | Vì sao |
|---|---|---|
| **H1** | `candidates[]` kèm `contact_id` | Hiện chỉ `{name, phone_number}`. Không có id thì lượt gọi lại vẫn gửi `name` và host lại tìm mờ lần nữa — hai người trùng tên y hệt là quay lại vòng cũ. |
| **H2** | `CONTACT_NOT_FOUND` cũng kèm `candidates[]` (top-N theo điểm của host, kể cả dưới ngưỡng) | Mở khoá ca "tên đặt lạ" |
| **H3** | `GET /api/v1/service/contact/list` (**việc phía app** — xem 26.1/P1) | **Bản đúng.** Server cache danh bạ ở nền như đang làm với vị trí, tự so khớp. "Gọi cho mẹ" resolve thẳng ra `contact_id`, **không round-trip nào**, và chất lượng so khớp do mình sở hữu. Làm được H3 thì H1/H2 thành thừa. |

---

## 10. Gọi khẩn cấp (emergency_call)

### Hiện tại

`handlers/phone.py:51-65`. Thiếu `emergency_number` → **vẫn gửi lệnh** với
payload rỗng, host dùng số đã cấu hình sẵn. Câu trấn an được dựng sẵn audio
(`STATIC_SPEECH`) — với nhóm này dựng sẵn là **bắt buộc**, không phải tối ưu.

### Vấn đề

Không có. **Đây là hành vi đúng.**

### Cải thiện

- **D5** — **Không đổi logic.** Thêm assert trong `handlers/slots.py`:
  `emergency_number` **không được** có mặt trong bảng chính sách slot. Thêm test
  khoá lại.

  > `emergency_call` không được thêm bất kỳ bước hỏi lại hay đọc-lại-chờ-xác-nhận
  > nào. Người dùng gọi khẩn cấp là lúc họ có thể đang ngã, đang bị thương,
  > không nói thêm được câu thứ hai. Mọi cơ chế xác minh phải loại trừ nhãn này
  > **tường minh trong code**, không để mặc định rơi vào.

---

## 11. Chỉ đường (nav_start / nav_stop)

### Hiện tại

`handlers/navigation.py:31-44` — thiếu `destination` → `yield _ASK_DESTINATION`
rồi return, **không nhớ gì**. Có destination → gửi thẳng
`{"destination": {"address": destination}}`, ack = `"Đang mở chỉ đường."`
(**không đọc tên nơi đến**).

`handle_stop` (dòng 62) lấy `navigation_id` từ `recall()`. Không có id → nói
"không có lộ trình nào đang chạy" và `mark_inactive`.

### Vấn đề

1. **Hỏi rồi quên** — y hệt `contact_call`. "Bạn muốn đi đâu?" → người dùng đáp
   "Bưu điện Thành phố" → intent = `chat` → Gemini tán gẫu về bưu điện.
2. **Không đọc lại điểm đến trước khi gửi.** `ride.py` cẩn thận (đọc lại, chờ
   xác nhận) nhưng `navigation.py` gửi thẳng. Cùng một rủi ro, hai mức cẩn thận
   khác nhau, không có lý do. STT nghe "Bách Khoa" thành "Bát Khoa" → người mù đi
   bộ theo lộ trình sai mà không có tín hiệu nào để biết.
3. **`INVALID_DESTINATION` không bao giờ được phát ra** — app luôn trả
   `Success` (xem 26.5). Câu dưới đây mô tả một mã lỗi chưa có nguồn.
   **`INVALID_DESTINATION` là ngõ cụt.** `result_speech.py` nói *"Vui lòng nói
   lại tên địa điểm"* rồi vứt ngữ cảnh.

### Cải thiện

- **A3** — Prompt intent có vị trí hiện tại → "Bách Khoa" resolve đúng vùng.
- **A5 → D3** — Ack đọc tên: `f"Đang mở chỉ đường tới {destination}."`
  Readback + chờ xác nhận khi `slot_confidence == "low"`.
- **B2/D1** — Pending cho slot `destination`.
- **D4** — `INVALID_DESTINATION` đặt pending `destination` trước khi đọc câu lỗi.

---

## 12. Đặt xe (ride_quote / ride_confirm)

### Hiện tại

`handlers/ride.py` — luồng **hai lượt có chủ ý**, và là mẫu tốt nhất trong repo:

1. `handle_quote` (dòng 71) — **chưa gọi API**. Đọc lại điểm đến, lưu
   `pending_ride_destination`, chờ xác nhận.
2. `handle_confirm` (dòng 83) — `confirm=False` → huỷ. Có pending → gọi
   `ride/quote` thật. Không pending nhưng có `quote_id` → "chuyến đang chờ trong
   app".

Kết thúc luồng, server app đẩy FCM xuống điện thoại, app Android mở Grab. Việc
đặt thật xảy ra **trong app Grab**, không ở đây.

### Vấn đề

**Người dùng không biết giá, không biết loại xe.** `_OPENING_RIDE_APP` (dòng 23)
chỉ nói *"đang mở ứng dụng đặt xe, bạn chờ một chút"*. Người sáng nhìn màn hình
Grab thấy danh sách dịch vụ kèm giá rồi mới bấm; người khiếm thị **xác nhận mù
một khoản tiền thật**. Đây là khoảng trống lớn nhất của tính năng — lớn hơn cả
lỗi toạ độ bên dưới.

**Hai lượt đang đặt sai chỗ.** Lượt 1 không gọi API, chỉ đọc lại tên điểm đến
(thứ vừa nghe từ STT, giá trị thấp). Lượt 2 mới gọi API rồi ném thẳng sang app.
Nghĩa là lượt xác nhận đắt tiền nhất diễn ra khi trong tay **chưa có một dữ kiện
thật nào**.

**Toạ độ đón hardcode.** `handlers/ride.py:14`:
```python
_DEMO_CURRENT_LOCATION = {"lat": 10.7769, "lng": 106.7009}   # Quận 1, TP.HCM
```
Cộng với lỗi vị trí ở mục 8: **mọi chuyến Grab đều đón ở Quận 1** bất kể người
dùng ở đâu.

> 🔴 **Nửa còn lại nặng hơn:** điểm **đến** cũng là hằng số — xem **26.4**.
> Và giá 85 000 đ mà R3 định đọc lên đang là số bịa sẵn trong app — **26.3**.

**`_WAITING_IN_APP` là ngõ cụt.** Sau khi mở app, server không còn biết gì về
chuyến — Grab không có API trạng thái. Mọi câu hỏi sau đó ("xe tới chưa?", "biển
số gì?") chỉ nhận lại đúng một câu.

Ngoài ra: pending không có TTL (mục 3), và câu trả lời "đúng rồi" phụ thuộc
Gemini vì SetFit chặn đường (mục 2).

### Trần kỹ thuật — khảo sát nhà cung cấp (2026-08)

**Grab không có API đặt xe cho bên thứ ba.** Thứ duy nhất dùng được là **Farefeed**:

```
POST https://partner-api.grab.com/farefeed/v1/estimate
Authorization: Bearer {token}          # OAuth 2.0, scope: ride.estimate
body: { pickUp:  {latitude, longitude, address},
        dropOff: {latitude, longitude, address} }
```

Trả về `services[]`, mỗi phần tử:

| Field | Nội dung |
|---|---|
| `serviceID` / `serviceName` | loại xe (GrabBike, GrabCar, …) |
| `fare.minFare` / `fare.maxFare` / `fare.currency` | **khoảng** giá, không phải giá chốt |
| `eta` | phút xe tới **điểm đón** (không phải tới đích) |
| `surgeNotice` | `NONE` / `LOW_SURGE` / `HIGH_SURGE` / `FRACTIONAL_SURGE` |
| `deepLink` / `directDeepLink` | mở app Grab, **prefill sẵn đón + đến + `taxiTypeId`** |

Không có endpoint tạo booking. Không có API trạng thái chuyến. `Login with Grab`
chỉ là danh tính, `Grab for Business` chỉ là tài khoản DN + đối soát.

→ **Trần của tính năng này là "một chạm", không phải "không chạm".** Spec dưới
đây tối ưu đúng trần đó: dồn toàn bộ phần khó vào giọng nói, để lại đúng một cú
chạm cuối trong app Grab.

### Cải thiện

Luồng mới:

```
lượt 1   "đặt xe tới Bách Khoa"
         → geocode + Farefeed (gọi thật)
         → "Đi Bách Khoa. Xe máy 32 đến 38 nghìn, xe tới sau 3 phút.
            Ô tô 78 đến 90 nghìn, 6 phút. Bạn đi xe nào?"
lượt 2   "xe máy"
         → chốt serviceID, lấy deepLink trong pending, đẩy FCM
         → "Đã mở Grab: xe máy đi Bách Khoa, 32 đến 38 nghìn.
            Bạn chạm một lần vào nút đặt xe ở cuối màn hình."
```

- **R1** — **Lượt 1 gọi Farefeed thật**, đọc lại điểm đến **kèm bảng giá**. Đây
  mới là lý do tồn tại của lượt 1; đọc suông tên điểm đến thì không đáng một
  lượt. Kéo theo: `handle_quote` (dòng 71) chuyển từ "không gọi API" sang "gọi
  API", `handle_confirm` (dòng 83) chuyển ngược lại thành "không gọi API".
- **R2** — **Đọc tối đa 2 lựa chọn**: rẻ nhất nhóm 2 bánh + rẻ nhất nhóm 4 bánh.
  Đọc 5 dòng dịch vụ bằng giọng là quá tải trí nhớ ngắn hạn. *"còn xe nào
  khác"* → đọc nốt phần còn lại từ pending, không gọi API lại.
- **R3** — **Luôn đọc khoảng giá**, đúng như API trả, không làm tròn thành một
  số. `surgeNotice ∈ {HIGH_SURGE, FRACTIONAL_SURGE}` → chèn *"đang giờ cao
  điểm, giá thực tế có thể cao hơn"*. Đọc một con số chốt rồi bị lệch là mất
  niềm tin, và người khiếm thị không có cách nào tự kiểm chứng.
- **R4** — **Pending đổi nội dung và TTL riêng.** Thay `pending_ride_destination`
  (string) bằng `Pending(kind="ride", data={destination, services[], quoted_at})`
  của **B2**. TTL **45 s** — tầng `select` của bảng **21.3**, không phải 90 s
  mặc định: giá có surge, đọc lại một bảng giá cũ là nói sai số tiền. Hết hạn →
  gọi lại Farefeed, **cấm** tái dùng `services[]` cũ.
- **R5** — **`handle_confirm` không gọi API nữa**: khớp câu trả lời ("xe máy",
  "ô tô", "cái rẻ hơn") sang `serviceID` trong pending, lấy `deepLink` tương
  ứng, đẩy xuống app. Không round-trip, không tốn thêm giây nào.
  Tham số `provider` để riêng ngay từ đầu, đừng viết chết vào Grab — xem
  *Ngoài phạm vi* bên dưới.
- **R6** — **Vị trí thật** (chính là **A6**, giờ nặng hơn). Với Farefeed, sai
  điểm đón không chỉ đón nhầm chỗ mà còn **báo giá sai** và prefill sai vào
  deeplink. Không có vị trí → nói thẳng *"chưa xác định được vị trí của bạn,
  chưa đặt xe được"*, không âm thầm rơi về Quận 1.
- **R7** — **Câu bàn giao phải nói rõ là còn phải chạm.** `_OPENING_RIDE_APP`
  hiện tại (*"bạn chờ một chút"*) ngụ ý hệ thống đang tự đặt — sai, và người
  dùng sẽ đứng đợi một chuyến không bao giờ tới. Đổi thành câu nói thẳng: đã
  mở, đúng loại xe, đúng giá, **còn một chạm**. `_WAITING_IN_APP` giữ vai trò
  ngõ cụt nhưng phải nói thật rằng server không theo dõi được chuyến sau khi
  bàn giao.
- Giữ **`readback = "always"`** cho ride: lý do cũ (tốn tiền thật) vẫn đúng, và
  giờ lượt readback còn chở thêm giá — nó trở thành lượt có giá trị nhất.

### Hợp đồng phải đổi (server app 8001)

`ride/quote` (`endpoint.md` §2.1) trả thêm danh sách dịch vụ:

```json
{ "services": [
    { "provider": "grab", "service_id": 1, "service_name": "GrabBike",
      "min_fare": 32000, "max_fare": 38000, "currency": "VND",
      "eta_minutes": 3, "surge": "NONE",
      "deep_link": "https://...", "direct_deep_link": "grab://..." } ] }
```

`ride/confirm` (§2.2) không đặt xe nữa — nhận `service_id`, trả deeplink để app
mở. Mã lỗi `RIDE_ACCOUNT_NOT_CONNECTED` **không dùng** cho đường Grab/Farefeed
(Farefeed không cần user link tài khoản); giữ lại cho provider tương lai.

### Ngoài phạm vi kỹ thuật — phải xử trước khi code R1

1. **Farefeed không self-serve.** `client_id`/`client_secret` và scope
   `ride.estimate` chỉ cấp khi **onboarding partner**; bản công khai đã gỡ khỏi
   web từ 20/06/2024. **R1–R3, R5 bị chặn ở đây** — phải xin quyền partner
   trước. R4, R6, R7 làm được ngay, độc lập.
2. **Cấm lái UI app Grab bằng AccessibilityService** để bấm hộ nút đặt. Vi phạm
   ToS, ban tài khoản thật của người dùng, vỡ mỗi lần Grab đổi layout — và
   người khiếm thị **không phát hiện được** là nó vừa bấm nhầm cái gì.
3. **Muốn bỏ nốt cú chạm** thì phải có provider có API đặt thật: EMDDI bán tích
   hợp như một sản phẩm (nền cho BeTaxi, đặt xe trong Viettel Money); Xanh SM /
   Be phải qua hợp đồng BD. Không thuộc spec này, nhưng **R5 tách `provider` ra
   tham số** để cắm thêm sau mà không viết lại handler.
4. **Nghị định 158/2024** (hiệu lực 01/01/2025): hợp đồng điện tử + hoá đơn phải
   gửi về **tài khoản của chính khách** → không được đặt chung bằng một tài
   khoản hệ thống. Đường deeplink thoả mãn điều này tự nhiên vì chuyến đứng tên
   tài khoản Grab của người dùng; provider tương lai nào cũng phải giữ tính chất
   đó.

---

## 13. Nhạc (music_play / music_stop / music_volume)

### Hiện tại

`handlers/music.py` — luồng nhiều lượt phức tạp nhất:

1. `_names_a_song()` (dòng 78) chặn câu chung chung bằng `_GENERIC_SONG_WORDS`
   (10 cụm hardcode) → hỏi `_ASK_SONG`.
2. `_names_an_artist()` (dòng 72) đoán đã có ca sĩ chưa bằng
   `_ARTIST_MARKERS = (" - ", " của ", " by ")` → chưa có thì lưu
   `pending_song_title` và hỏi ca sĩ.
3. Lượt sau, nhánh `if pending:` (dòng 87) ghép câu trả lời vào tên bài.

`handle_volume` (dòng 146) — thiếu `direction` và `volume` → hỏi `_ASK_VOLUME`,
**không nhớ gì**. Cố ý không mặc định "tăng": người khiếm thị không nhìn được
thanh âm lượng.

### Vấn đề

1. **`_names_an_artist` sai cả hai chiều:**

   | Người dùng nói | STT ra | Kết quả | Hậu quả |
   |---|---|---|---|
   | "Nơi này có anh **của** Sơn Tùng" | "Nơi này có anh Sơn Tùng" (nuốt "của") | `False` | Hỏi lại ca sĩ dù vừa nói xong |
   | "mở bài Chuyện **của** mùa đông" | như vậy | `True` | Không hỏi, app chọn bừa cover |

2. **Ghép chuỗi thô** (dòng 96): `if pending.lower() not in answer.lower()`.
   Lệch một dấu/hoa thường là ra
   `"Nơi này có anh - Nơi này có anh của Sơn Tùng"`.
3. **`_GENERIC_SONG_WORDS` là danh sách hữu hạn.** "mở nhạc nào đó đi", "cho
   nghe cái gì đó", "nhạc gì cũng được" — lọt hết, thành tên bài đem đi query.
4. **`handle_volume` hỏi rồi quên** — người dùng đáp "tăng" thì không chắc về
   được `music_volume`.
5. **`SONG_NOT_FOUND` là ngõ cụt** — nói "vui lòng nói lại tên bài" rồi vứt ngữ
   cảnh.
6. **Pending không TTL** (mục 3) — bug ghép bài cũ với ca sĩ mới.
7. **Chỗ hở đã biết:** host không báo khi bài tự hết, nên `music_playing` vẫn bật
   sau khi nhạc đã tắt. Comment ở `action_flow.py:78-86` đã ghi và chấp nhận —
   **giữ nguyên**, đừng thay bằng TTL đoán mò.

### Cải thiện

- **A1** — Tách schema `song_title` + `artist` + `song_is_specific` **riêng**.
- **A4** — **Xoá** `_ARTIST_MARKERS`, `_names_an_artist`,
  `_GENERIC_SONG_WORDS`, `_names_a_song` (dòng 10-79). Đọc thẳng `artist` và
  `song_is_specific`. Nối `f"{title} - {artist}"` chỉ khi cả hai có. Không
  heuristic chuỗi nào còn lại.
- **B2/D1** — Pending cho `song_title`, `artist`, `volume_direction`.
- **D4** — `SONG_NOT_FOUND` đặt pending `song_title`.
- Host contract giữ nguyên: `song` vẫn là một chuỗi `"Tên - Ca sĩ"`
  (`endpoint.md:131`).

---

## 14. Xuyên suốt: bảng chính sách slot

### Hiện tại

5 hằng số `_ASK_*` rải rác, mỗi handler tự quyết khi nào hỏi lại, không ai đọc
lại thông tin trước khi gửi (trừ `ride`):

| Hằng số | File |
|---|---|
| `_ASK_CONTACT` | `handlers/phone.py:5` |
| `_ASK_DESTINATION` | `handlers/navigation.py:5` |
| `_ASK_DESTINATION` | `handlers/ride.py:28` |
| `_ASK_SONG` | `handlers/music.py:29` |
| `_ASK_VOLUME` | `handlers/music.py:33` |

Cộng thêm **4 câu lỗi của host đặt câu hỏi mà hệ thống không nghe được câu trả
lời** (`handlers/result_speech.py`):

| Mã lỗi | Câu nói | Trả lời đi đâu |
|---|---|---|
| `MULTIPLE_CONTACTS_FOUND` | "…vui lòng **nói rõ hơn**" | → `chat` |
| `CONTACT_NOT_FOUND` | "Không tìm thấy người này…" | ngõ cụt |
| `SONG_NOT_FOUND` | "…vui lòng **nói lại tên bài**" | → `chat` |
| `INVALID_DESTINATION` | "…vui lòng **nói lại tên địa điểm**" | → `chat` |

Đây không phải 4 bug rời — là **một** thiếu sót: `run_action` không có đường đặt
pending từ kết quả trả về.

### Cải thiện

- **D1** — File mới `handlers/slots.py`, một chỗ duy nhất:
  ```python
  @dataclass(frozen=True)
  class SlotSpec:
      ask: str          # câu hỏi khi thiếu
      readback: str     # "always" | "low_conf" | "never"
      risk: str         # "high" -> sai là không sửa được

  SLOTS = {
      "contact_name":     SlotSpec("Bạn muốn gọi cho ai?",             "low_conf", "high"),
      "destination":      SlotSpec("Bạn muốn đi đâu?",                 "low_conf", "high"),
      "ride_destination": SlotSpec("Bạn muốn đi đâu?",                 "always",   "high"),
      "song_title":       SlotSpec("Bạn muốn nghe bài hát nào?",       "never",    "low"),
      "artist":           SlotSpec("Bạn muốn nghe của ca sĩ nào?",     "never",    "low"),
      "volume_direction": SlotSpec("Bạn muốn tăng hay giảm âm lượng?", "never",    "low"),
  }
  # emergency_number KHÔNG có mặt ở đây. Cố ý. Xem mục 10.
  ```
- **D3** — Readback theo `slot_confidence`. Chọn `low_conf` chứ không `always`
  cho `contact_name`/`destination` vì gọi mẹ 20 lần/ngày mà lần nào cũng phải xác
  nhận là **hình phạt cho ca dùng phổ biến nhất**. `ride` giữ `always`.
- **D4** — `run_action` đặt được pending từ mã lỗi host:
  ```python
  _ERROR_REASK = {
      "MULTIPLE_CONTACTS_FOUND": ("contact_name", "contact_call"),
      "CONTACT_NOT_FOUND":       ("contact_name", "contact_call"),
      "SONG_NOT_FOUND":          ("song_title",   "music_play"),
      "INVALID_DESTINATION":     ("destination",  "nav_start"),
  }
  ```
  Người dùng đáp bằng một từ là chạy tiếp, không phải nói lại cả câu.

  ⚠️ Hai trong bốn mã này (`INVALID_DESTINATION`, và `MULTIPLE_CONTACTS_FOUND`
  trong thực tế) **chưa có nguồn phát** — xem **26.5/P7**. Làm P7 trước D4,
  nếu không là viết bảng ánh xạ cho mã lỗi không tồn tại.

**Lưu ý phụ:** `_ERROR_SPEECH.values()` đang nằm trong `STATIC_SPEECH`
(`handlers/result_speech.py:107`) để dựng sẵn audio. Câu chứa tên ứng viên là
**động, không dựng sẵn được** — tách phần cố định ("Bạn muốn gọi cho ai?") ra để
nửa đó vẫn trúng cache, giống cách `handlers/music.py:50-53` đã làm với ack có
tên bài. `pipeline/phrases.py` phải cập nhật khi các câu `_ASK_*` dời sang
`slots.py`.

---

## 15. Phạm vi ảnh hưởng

| File | Nhóm |
|---|---|
| `handlers/slots.py` **(mới)** | D1 D5 |
| `handlers/contact_match.py` **(mới)** | D7 |
| `pipeline/intent.py` | A1 A2 A3 · B3 B5 · E5 |
| `pipeline/router.py` | B1 |
| `handlers/action_flow.py` | B2 B6 B7 · D4 · R4 |
| `handlers/chat.py` | B4 · C1 C2 C3 C4 C5 · E4 |
| `handlers/phone.py` | D2 D3 D8 |
| `handlers/result_speech.py` | D4 D6 |
| `handlers/music.py` | A4 · D1 |
| `handlers/navigation.py` | D3 · D1 |
| `handlers/ride.py` | A6 · D1 · R1 R2 R3 R5 R6 R7 |
| `handlers/ocr.py` | E1 |
| `models/ocr/__init__.py` | E2 |
| `models/ocr/prompts.py` | E1 |
| `handlers/describe_space.py` | E5 |
| `handlers/describe_hazard.py` | E6 (chỉ comment) |
| `pipeline/phrases.py` | D1 · R7 (cập nhật `STATIC_SPEECH`) |
| `config.py` | C3 · TTL pending · R4 (TTL 45 s cho `ride`) |
| `requirements.txt` | D9 (`rapidfuzz`) |

**Không đụng tới:** `find_object`, `read_money`, TTS, ADPCM, STT, benchmark.

**Ngoài repo này:** server app 8001 phải đổi hợp đồng `ride/quote` + `ride/confirm`
và tự tích hợp Farefeed (xem mục 12). App Android phải mở `deep_link` nhận được
thay vì tự dựng màn hình đặt xe.

---

## 16. Test

### Phải viết lại

| File | Vì sao |
|---|---|
| `tests/test_device_state.py:138-172` | Khoá đúng hành vi fast-bypass mà **B1** gỡ bỏ |
| `tests/test_services.py:306-330` | Khoá logic ghép chuỗi tên bài mà **A4** gỡ bỏ |

### Thêm mới

- `tests/test_slots.py` — mỗi slot một ca thiếu-thông-tin đi trọn 2 lượt, cộng
  **một test khẳng định `emergency_call` không bao giờ hỏi lại**.
- `tests/test_contact_match.py` — bảng ca cho `norm`/`phon`/`rank`. Thuần hàm,
  không cần host.
- `tests/test_ocr_context.py` — cache transcript, trả lời lượt sau không dùng
  ảnh, TTL hết hạn.
- `tests/test_location_degraded.py` — cache rỗng phải ra khối cảnh báo chứ không
  phải `""`; thread không chết khi result thiếu `lat`.
- `tests/test_ride_quote.py` — Farefeed giả lập: đọc đúng **khoảng** giá chứ
  không phải một số; chỉ đọc 2 lựa chọn (**R2**) và "còn xe nào khác" đọc nốt
  phần còn lại **không gọi API lại**; `HIGH_SURGE` phải chèn cảnh báo (**R3**);
  pending quá 45 s phải gọi lại chứ không tái dùng giá cũ (**R4**);
  `handle_confirm` **không** phát sinh request nào ra host (**R5**); cache vị trí
  rỗng → từ chối đặt, không rơi về Quận 1 (**R6**).

---

## 17. Câu hỏi còn mở

1. **H3 (endpoint danh bạ)** — có tác động được sang team host không? Có thì
   **D7** nhận thẳng danh sách đầy đủ và **D6** chỉ còn là đường dự phòng, kiến
   trúc sạch hơn hẳn. Không thì ca "tên đặt lạ" vẫn trượt khi tìm mờ phía host
   không ra.
2. **Ngưỡng so khớp danh bạ** (88/70, margin 8) là số khởi điểm. Cần một danh bạ
   thật để đo lại.
3. **TTL pending 90s** — đủ cho người khiếm thị nghĩ và trả lời chưa? Lên 120s đi
4. **`readback = low_conf` cho `contact_name`** — đủ an toàn, hay muốn `always`
   và chấp nhận thêm một lượt mỗi cuộc gọi?
5. **Quyền partner Farefeed** — đã liên hệ Grab chưa, ai đứng tên pitch? Đây là
   đường găng của cả nhóm **R**. Nếu Grab từ chối: (a) giữ nguyên hành vi hiện
   tại và chỉ làm R4/R6/R7, hay (b) đổi provider lấy giá (EMDDI) và chấp nhận
   phủ xe mỏng hơn?
6. **Đọc mấy lựa chọn xe là vừa?** R2 chốt 2 (rẻ nhất mỗi nhóm 2 bánh / 4 bánh).
   Cần thử với người dùng thật — 2 có thể vẫn là nhiều nếu tên dịch vụ dài.

---

## 18. Ràng buộc thứ tự

**D chạy được ở mức cơ bản với B2 (Pending), nhưng chưa hoàn chỉnh nếu chưa có
B3.** Không có B3 thì câu trả lời một từ ("mẹ", "Bách Khoa", "Sơn Tùng") vẫn bị
SetFit cục bộ nuốt thành `chat` trước khi tới Gemini. Nên **D phải kéo theo B2 +
B3 tối thiểu**.

**A3 và A6 phụ thuộc C** — cả hai cần vị trí chạy được.

**R phụ thuộc C, và R1–R3 + R5 còn phụ thuộc một thứ không nằm trong tầm kiểm
soát của team: quyền partner Farefeed** (mục 12, *Ngoài phạm vi kỹ thuật*). Vị
trí sai thì giá cũng sai, nên **R6 = A6** phải xong trước. **R4, R6, R7 làm được
ngay** kể cả khi chưa có quyền partner — làm trước ba cái đó, đừng chờ Grab.

---
---

# PHẦN II — Chốt từ phiên rà soát kiến trúc

Phần I (mục 1–18) rà soát code hiện có. Phần II là những thứ **chưa tồn tại**:
giao thức kính ↔ server, ngân sách độ trễ, ngắt lời, và cuộc gọi đến.

Mã cải thiện phần này dùng tiền tố **F** (giao thức/firmware) và **G** (độ trễ).

> Phạm vi: spec này **chỉ** tối ưu các chức năng đang có, **ngoại trừ mục 28**.
> Bản đầu của Phần II từng loại cảnh báo vật cản thời gian thực ra khỏi kế
> hoạch; quyết định đó **đã bị lật lại** theo yêu cầu tường minh (2026-08-24) —
> xem mục 28. `hazard` theo lượt (mục 6 phần I) **giữ nguyên, không bị thay
> thế** — mục 28 là tính năng song song mới.

## Bối cảnh hệ thống — ba repo

| Vai trò | Đường dẫn | Cổng |
|---|---|---|
| Server kính (repo này) | `D:\Study\innostar\Sever_test` | 8000, ra ngoài qua Cloudflare tunnel |
| Server app | `D:\Study\innostar\app_demo_backend\apps\backend` | 8001 |
| Firmware | `D:\Study\innostar\your-eyes-esp32-firmware` | ESP32-S3-CAM (OV2640) |

Mạng: kính nối **WiFi phát từ điện thoại**. Nghĩa là điện thoại vừa là gateway
(cách kính đúng một hop) vừa là đích của mọi action. Đường ra internet vẫn đi
qua sóng di động của điện thoại rồi qua Cloudflare tunnel — băng thông đủ, nhưng
RTT và jitter thì không.

---

## 19. Giao thức kính ↔ server

### Hiện tại

`app.py:448`:

```python
def process(request, image: UploadFile | None, audio: UploadFile | None)
```

Không có `device_id`. Không có `turn_id`. Ảnh và audio nằm chung một multipart.

### Vấn đề

1. **Không có `device_id` → toàn bộ mục 3 (session), pending, và idempotency
   không implement được.** Đây là thứ chặn nhiều việc nhất trong cả spec.
2. Ảnh 1600x1200 (~250–400 KB) gửi kèm **mọi** lượt, kể cả 10/15 intent không
   hề đọc ảnh: `chat`, `music_*`, `nav_*`, `contact_call`, `emergency_call`,
   `ride_*`, `cancel`, `repeat`.
3. **Thứ tự part trong multipart đang quyết định độ trễ mà không ai để ý.** Nếu
   firmware ghi part `image` trước `audio`, server không thể bắt đầu STT cho tới
   khi ảnh upload xong.
4. Không có đường server → kính. Kính chỉ nói được khi người dùng bấm. Mọi thứ
   server muốn chủ động báo (cuộc gọi đến, đổi cấu hình camera) đều không gửi
   được.

### Cải thiện

#### F1 — Header bắt buộc trên mọi request

```
X-Device-Id:  glasses-123
X-Turn-Id:    <uuid, mới mỗi lượt>
X-Capture-Ts: <epoch ms lúc chụp>
```

Header chứ không phải form field: server đọc được **trước khi** body upload
xong, nên tra được session và bắt được lượt trùng ngay.

`X-Turn-Id` có **hai** vai trò, không phải một:
```
1. chống gửi lặp (idempotency, mục 28 phần I)
2. ngắt lượt cũ   (barge-in, xem G4)
```

#### F2 — Thứ tự part: audio TRƯỚC ảnh — 🔴 **HUỶ, xem 27.1**

> Firmware đã đẩy ảnh **trong lúc người dùng đang nói** (289 ms, ngoài đường
> tới hạn). Đảo thứ tự part làm ảnh rơi xuống sau nhả nút → **chậm đi**.
> Giữ đoạn dưới để biết lý lẽ ban đầu; việc thay thế là **F3**.

```
SAI : [boundary] image (~2s upload) [boundary] audio   → STT bắt đầu ở t=2s
ĐÚNG: [boundary] audio (chunked, gửi trong lúc thu) [boundary] image
                                                       → STT bắt đầu ngay
```

Một dòng firmware. Ăn 1–2 giây. Kiểm tra ngay trước khi làm gì khác.

#### F3 — Tách ảnh sang `POST /frame`

```
socket A → POST /process   audio ADPCM, chunked, giữ mở, nhận audio stream về
socket B → POST /frame     ảnh, fire-and-forget, cùng X-Turn-Id
```

Server giữ **FrameBuffer theo device** (ring 1–3 frame + timestamp). Handler
không đọc bytes trực tiếp từ request nữa mà gọi:

```python
frames.latest(device_id, max_age_ms=800)
```

Đây là chỗ quan trọng nhất của cả phần II: **handler không cần biết frame tới
từ đâu.** Ảnh tới trước hay sau lượt audio, tới một tấm hay vài tấm — cùng một
API, handler không phải sửa.

Audio không còn đợi ảnh một byte nào.

#### F4 — Bảng: chức năng nào cần kính gửi gì

Bảng này là hợp đồng giữa firmware và server. Mọi thay đổi phải sửa ở đây trước.

| Chức năng | Gửi audio | Gửi ảnh | Độ phân giải | jpeg_q | Ghi chú |
|---|---|---|---|---|---|
| `chat` | ✅ | ❌ | — | — | không đọc ảnh |
| `ocr` | ✅ | ✅ | **1600x1200** | 8 | chữ nhỏ cần nét, không hạ được |
| `ocr` follow-up ("dòng hai nói gì") | ✅ | ❌ | — | — | dùng `OCRContext` đã cache |
| `describe_space` | ✅ | ✅ | 640x480 | 15 | |
| `describe_hazard` (theo lượt, mục 6) | ✅ | ✅ | 640x480 | 15 | |
| `find_object` | ✅ | ✅ | 800x600 | 12 | |
| `read_money` | ✅ | ✅ | 800x600 | 12 | |
| `contact_call` | ✅ | ❌ | — | — | |
| `emergency_call` | ✅ | ❌ | — | — | không được chờ ảnh |
| `nav_start` / `nav_stop` | ✅ | ❌ | — | — | |
| `ride_quote` / `ride_confirm` | ✅ | ❌ | — | — | |
| `music_play` / `stop` / `volume` | ✅ | ❌ | — | — | |
| `cancel` / `repeat` | ✅ | ❌ | — | — | không mạng ngoài, không LLM |
| trả lời pending ("ừ", "người thứ hai") | ✅ | ❌ | — | — | không chụp lại ảnh |

Kính **không biết trước intent**, nên không tự quyết được cột "gửi ảnh". Hai
cách, chọn một:

```
(a) SONG SONG  — kính cứ gửi ảnh qua socket B; server dùng nếu cần, bỏ nếu không
    ưu: 0ms thêm vào đường tới hạn
    nhược: tốn băng thông cho 10/15 intent

(b) HAI PHA   — kính gửi audio trước; server biết intent rồi mới xin ảnh qua
    kênh downlink (F6); kính gửi khi được xin
    ưu: tiết kiệm băng thông và pin
    nhược: +1 RTT (~80–300ms) cho các intent CÓ dùng ảnh
```

**Chốt: (a) cho tầng ảnh nhỏ, (b) cho tầng ảnh lớn** — xem F5.

#### F5 — Ảnh phân tầng   *(số trong mục này phải quy lại — xem 27.5)*

```
gửi NGAY, không hỏi   : 640x480 q15  (~30–50 KB, < 300ms)
gửi khi server XIN    : 1600x1200 q8 (~250–400 KB) — chỉ `ocr`
```

`space` / `find` / `money` / `hazard` dùng luôn tầng 640, không đợi gì.
Chỉ `ocr` mới phải trả giá một vòng hỏi-đáp, và `ocr` vốn là intent người dùng
chấp nhận chờ lâu hơn.

> ⚠️ Ngưỡng Laplacian trong `pipeline/image_quality.py` đo trên **1600x1200
> native**, và comment trong chính file đó đã ghi rõ resize làm hỏng đúng tín
> hiệu tần số cao cần đo. **Mỗi tầng phải đo lại ngưỡng riêng.** Dùng chung số
> cũ cho tầng 640 là sai âm thầm — không có log nào báo.

> ⚠️ Cả F4 lẫn F5 đang giả định firmware gửi được **1600x1200**. Đo 37 ảnh
> trong `storage/` ra **1280x720**, không có ngoại lệ — xem **25.4**. Xác minh
> (H0) trước khi thi công F5, nếu không là dựng kế hoạch cho một tầng ảnh có
> thể không tồn tại.

#### F6 — Kênh downlink server → kính (SSE)

Kính mở `GET /events` và giữ. Một kênh, **hai** mục đích:

```
1. xin ảnh tầng cao (F5)
2. báo cuộc gọi đến (mục 21)
```

Hai nhu cầu, xây một lần.

#### F7 — Danh sách sửa firmware, xếp theo lợi trên công

| Việc | Tiết kiệm (ước tính) | Công |
|---|---|---|
| Đổi thứ tự part: audio trước ảnh | **1–2 s** | 1 dòng |
| Thêm `X-Device-Id` / `X-Turn-Id` | — (chặn cả spec) | nhỏ |
| `Connection: keep-alive` | 50–150 ms | nhỏ |
| TLS session resumption (nếu HTTPS) | **300–800 ms** | vừa |
| Cache IP, bỏ DNS mỗi request | 20–100 ms | nhỏ |
| `TCP_NODELAY` | 40–200 ms | 1 dòng |
| Chụp lúc **bắt đầu** nói, không phải lúc kết thúc | 100–300 ms | nhỏ |
| Bỏ hẳn ảnh cho intent không cần | **1.5–2 s** trên 10/15 intent | vừa |
| Ảnh phân tầng 640 | 1–1.5 s cho space/find/money | vừa |
| Phát audio ngay từ chunk đầu | ~ thời lượng file | nhỏ |

TLS handshake RSA trên ESP32 rất đắt — nếu đang chạy HTTPS mà mở socket mới mỗi
lượt thì đây là khoản tốn lớn nhất trong bảng, và nó vô hình trong mọi log
phía server.

Chụp lúc **bắt đầu** nói còn sửa luôn một lỗi khác: OV2640 vừa bật thì 2–3 frame
đầu sai AEC/AGC. Bấm nút → camera thức → nói xong thì phơi sáng đã ổn định, và
camera đang chỉ đúng thứ người dùng vừa quay đầu về phía nó.

#### F8 — Bẫy phía server

`RESPONSE_FORMAT == "wav"` (`app.py:531`) gom trọn body rồi mới gửi. **Không
được dùng cho board.** Board phải đi đường ADPCM stream có `prelude`.

`audio.file.read()` hiện đọc hết audio mới chạy. Muốn STT streaming (G3) thì
phải đổi sang đọc theo chunk — làm sau F1–F3.

---

## 20. Xuyên suốt: ngân sách độ trễ

### Hiện tại

`DETAILED_STAGE_LATENCY_BENCHMARK.md` đo được: STT 0.8–1.6 s, intent SetFit
**8 ms**, Gemini 0.5–1.5 s, TTFB 0.6–1.6 s, tổng 3–6 s.

### Vấn đề

Spec **không có một con số ngân sách nào**, và code **không có một timeout nào**
trên lời gọi ngoài. Nghĩa là không có định nghĩa "chậm", nên không phát hiện
được lúc nào bị chậm đi.

### Cải thiện

#### G1 — Bảng ngân sách TTFB

| Đường | Mục tiêu | Ghi chú |
|---|---|---|
| `emergency_call` ack | **< 300 ms** | audio dựng sẵn, không LLM, không ảnh |
| `cancel` / `repeat` / stop | **< 300 ms** | không gọi mạng ngoài |
| trả lời pending tất định ("ừ", "số hai") | **< 400 ms** | không LLM, không ảnh |
| `contact_call` ack | **< 600 ms** | ack song song với API |
| `hazard` (theo lượt) | < 800 ms | |
| `chat` | < 1.0 s | |
| `ocr` / `space` / `find` / `money` | < 1.2 s | |

Kèm: **mọi lời gọi ngoài có deadline.** Quá deadline → nói một câu dựng sẵn,
không treo im lặng.

#### G2 — Không giữ lock trong lúc gọi LLM

Mục 27 phần I viết `lock → đọc state → xử lý lượt → ghi state → nhả`. Nếu "xử
lý lượt" chứa Gemini 1.5 s thì lock bị giữ 1.5 s → ngắt lời bị chặn, lượt kế
xếp hàng.

```
lock CHỈ bao đọc/ghi state (micro giây)
việc dài chạy NGOÀI lock
mỗi device có một generation counter
lượt mới → tăng generation → lượt cũ thấy generation lệch → tự huỷ
```

#### G3 — STT streaming + intent suy đoán

SetFit chỉ 8 ms nên chạy được trên **giả thuyết dở dang**, không cần đợi STT
xong.

```
partial "đọc chữ..."  → intent ổn định qua 2 partial liên tiếp
                      → khởi động ngay: xin ảnh tầng cao, mở kết nối, prefill prompt
STT final về          → chỉ còn phần sinh chữ
intent đổi ở final    → huỷ việc đã khởi động
```

Ước tính 400–700 ms. Làm **sau** F1–F3, vì nó cần `audio.file.read()` đổi thành
đọc chunk.

#### G4 — Ngắt lời (barge-in)

Spec phần I **không có một dòng nào** về việc người dùng nói đè khi TTS đang
chạy. Với người khiếm thị, câu `describe_space` 40 từ mà không ngắt được là hỏng
trải nghiệm.

```
lượt mới tới → huỷ token của lượt cũ → dừng LLM stream + dừng TTS stream
X-Turn-Id là khoá của cả hai việc: chống lặp VÀ ngắt lượt
```

#### G5 — Câu cố định phải dựng sẵn audio

`pipeline/phrases.py` đã có cơ chế. Bắt buộc mở rộng cho **toàn bộ**:

```
6 câu ask trong bảng SLOTS (mục 14 phần I)
"Đã huỷ."
"Không có nhạc đang phát."
"Không có lộ trình nào đang chạy."
"Tôi không quan sát được phía sau."
ack của emergency_call
```

Những lượt này TTS = 0 ms.

#### G6 — Ack và API chạy song song

`contact_call` / `music_play`: phát ack ngay khi resolve xong, gửi host API
đồng thời. Idempotency (`action_id`) đã bảo vệ. Đừng nối tiếp
`handler → API → ActionResult → speech`.

#### G7 — Đặt prompt đúng thứ tự cho prefix cache

Phần bất biến (system prompt, few-shot) **đặt trước**; phần biến thiên (OCR
text, lịch sử, vị trí) **đặt cuối**. Sai thứ tự → trượt prefix cache →
+200–400 ms mỗi lượt chat.

#### G8 — Earcon   *(board đã có sẵn `cueSent()` — đổi nội dung, xem 27.7)*

Earcon **< 150 ms** sau khi STT chốt endpoint. Không giảm độ trễ thật nhưng
giảm độ trễ **cảm nhận** mạnh nhất trong cả bảng này, và gần như miễn phí —
`chime_earcon.wav` đã có sẵn trong repo.

#### G9 — Quan sát được

Không có trace thì không phát hiện được hồi quy độ trễ. Mỗi lượt log:

```
turn_id, device_id, thời gian từng chặng (stt/intent/slot/api/ttfb),
intent, confidence, pending trước/sau, error_code
```

---

## 21. Sửa thứ tự ưu tiên router, pending, và cuộc gọi đến

### 21.1 — Thứ tự ưu tiên đang sai (lỗi thật)

Spec đặt `PENDING RESOLVER` **trên** `EXPLICIT STOP COMMAND`. Ca vỡ:

```
AI:   "Bạn muốn gọi cho ai?"        (pending fill contact_name)
User: "tắt nhạc"
→ resolver điền contact_name = "tắt nhạc"
→ ContactResolver đi tìm người tên "tắt nhạc"
```

Sửa: tách resolver làm hai pha.

```
EMERGENCY
→ PENDING TẤT ĐỊNH      (ừ/không/số thứ tự/thôi/nói lại)
→ STOP / LỆNH TOÀN CỤC   ← chèn vào đây
→ PENDING ĐIỀN SLOT      (qua slot validator)
→ CANCEL / REPEAT
→ INTENT DETECT
```

Bước điền slot phải qua **validator riêng theo slot**: `contact_name` không nhận
động từ mệnh lệnh; `volume_direction` chỉ nhận tăng/giảm/số.

### 21.2 — Pending thiếu `attempt_count`

User đọc sai tên bốn lần → hỏi lại y hệt bốn lần.

```python
attempt: int = 0
max_attempt: int = 2
```

Vượt ngưỡng thì **đổi chiến lược**, không hỏi lại nguyên văn: đọc 3 contact gần
nhất / "đánh vần giúp tôi" / bỏ intent.

### 21.3 — TTL 90 s cho mọi slot là sai

| Loại | TTL | Vì sao |
|---|---|---|
| `confirm` (sắp gọi / sắp đặt xe) | **20–30 s** | để lâu rất nguy hiểm: người dùng quên ngữ cảnh rồi "ừ" cho việc khác |
| `select` | 45 s | |
| `select` bảng giá xe (**R4**) | 45 s | giá Farefeed có surge; quá hạn phải gọi lại, không đọc lại giá cũ |
| `fill` rủi ro thấp (`song_title`) | 90 s | |

Và `asked_at` phải tính từ lúc **TTS phát xong**, không phải lúc server tạo
pending. Chênh 1–3 giây.

### 21.4 — Ghi rõ: một pending, không lồng nhau

Tối đa **1 pending / device**. Không stack. Không ghi rõ thì lần implement sau
sẽ có người tự chế stack rồi vỡ ở ca "pending mới sinh ra trong lúc pending cũ
chưa xong".

### 21.5 — Emergency thiếu đường thoát

Mục 15 phần I: "không confirm, không hỏi lại". Đúng cho ca thật. Nhưng nhận
nhầm = gọi nhầm cấp cứu.

```
sau khi đã gửi action → mở cửa sổ huỷ 3–5 s
→ earcon + "nói huỷ để dừng"
→ KHÔNG phải câu hỏi, KHÔNG chặn action (action đã gửi rồi; huỷ = gửi abort)
```

Và phát hiện emergency **không được** chỉ dựa SetFit:

```
cổng từ khoá độ chính xác cao   OR   classifier(p > ngưỡng thấp)
```

Class này ưu tiên **recall hơn precision** — bỏ sót nguy hiểm hơn báo thừa, vì
báo thừa đã có cửa sổ huỷ đỡ.

Đường emergency cũng chặn ở chỗ khác: hiện phải đợi STT xong (~1.2 s) mới phát
hiện được. Thêm dò từ khoá trên **partial STT** (G3) để rút ngắn.

### 21.6 — Contact: fallback phiên âm phải ghi rõ cho tiếng Việt

"ASR phonetic fallback" quá mơ hồ. Ghi thành chuỗi bước:

```
lowercase
→ bỏ dấu thanh
→ chuẩn hoá cặp ASR hay nhầm:  n/l  s/x  tr/ch  d/gi/r  iê/i  ươ/ư
→ token set ratio
→ NGƯỠNG TỪ CHỐI: dưới ngưỡng = no_match, KHÔNG confirm
```

Thiếu ngưỡng từ chối thì hệ thống hỏi bừa "Gọi Nguyệt Anh đúng không?" khi người
dùng nói "Ngọc Ánh".

### 21.7 — Error recovery thiếu phân loại và fallback

Bảng `(origin_intent, error_code)` ở mục 25 phần I là đúng, nhưng thiếu:

```
retryable | terminal
default fallback khi không khớp dòng nào
```

Không có default → mã lỗi lạ rơi vào im lặng, người dùng không biết chuyện gì.

### 21.8 — Cuộc gọi đến (`call_incoming`)

Spec hiện không có. Đây là **event từ điện thoại**, không phải intent từ người
dùng.

```
ưu tiên: dưới emergency_call, TRÊN mọi thứ khác

TTS đang chạy   → cắt/duck NGAY, không xếp hàng đợi
                  (câu space 40 từ mà đợi đọc xong thì chuông tắt rồi)
pending đang mở → GIỮ NGUYÊN — chuông là ngắt quãng, không phải người dùng đổi ý

mở cửa sổ intent 15 s: call_answer | call_reject
  "nghe máy" / "nghe" / "trả lời"  → answer
  "từ chối" / "không nghe" / "bỏ"  → reject
hết chuông → đóng cửa sổ

call_ended → xoá state, không đọc gì
```

Câu báo, ghép ba mảnh:

```
"Có cuộc gọi từ "  +  [TÊN]  +  " đang gọi."
 ↑ dựng sẵn           ↑ tổng hợp 150–300ms    ↑ dựng sẵn
```

**Cache TTS theo `contact_id`** → lần thứ hai cùng người là 0 ms. Hoặc dựng sẵn
top-20 contact lúc ghép máy.

```
không có trong danh bạ → "Số lạ, đuôi bốn năm sáu."   (đọc từng chữ số)
trùng tên              → "Mẹ, đuôi bảy tám chín, đang gọi."
```

Riêng tư: đọc tên to giữa chỗ đông người là lộ thông tin. Thêm vào Preferences
API của host: `announce_caller: name | number_only | ring_only`, mặc định `name`.

**Cần phía Android:** `TelephonyCallback` bắt `RINGING` + `READ_PHONE_STATE` +
`READ_CONTACTS` → `POST /api/v1/device/event`.

**Cần phía host:** forward event sang server kính, **tách khỏi luồng
`request_id`**. `services/action_callbacks.py` hiện từ chối callback không có
`request_id` đã đăng ký (`"Callback arrived for unregistered request_id"`), nên
event tự phát cần đường riêng.

**Cần phía server kính:** kênh SSE F6 + handler `call_incoming`.

---

## 22. Thứ tự triển khai phần II

```
1.  F1  X-Device-Id / X-Turn-Id            ← chặn toàn bộ session + pending + idempotency
2.  F2  đổi thứ tự part multipart          ← rẻ nhất, lợi nhất
3.  F7  keep-alive + TLS resumption + NODELAY + cache IP
4.  G2  thu hẹp lock + generation counter  ← retrofit sau rất đắt
5.  G1  bảng ngân sách + deadline cho mọi lời gọi ngoài
6.  21.1 sửa thứ tự ưu tiên router + slot validator
7.  21.2–21.4 pending: attempt, TTL theo slot, một pending
8.  G5  dựng sẵn audio toàn bộ câu cố định
9.  G4  ngắt lời
10. F3  tách /frame + FrameBuffer + frames.latest()
11. F6  kênh downlink SSE
12. F5  ảnh phân tầng + đo lại ngưỡng blur cho từng tầng
13. 21.8 cuộc gọi đến (dùng lại F6)
14. G3  STT streaming + intent suy đoán
15. G9  trace từng chặng
```

Bước 1–3 làm được trong một ngày, ăn khoảng 1.5–2.5 giây — đây là phần lợi
nhất trên công bỏ ra của cả spec.

> ⚠️ Bảng trên viết trước khi đọc firmware. **Mục 27.9 sửa lại**: bước 2 (F2)
> bị huỷ, và thêm F9/G10/G11 — trong đó **G10** có thể đáng 30 giây mỗi lượt.

---

## 23. Test phần II

### Giao thức

```
thiếu X-Device-Id      → server từ chối rõ ràng, KHÔNG im lặng bỏ qua
X-Turn-Id trùng        → không gọi API lần hai, trả kết quả cũ
multipart: audio part phải ra trước ảnh
/frame tới trước /process, tới sau /process, không bao giờ tới
frames.latest() quá max_age → handler xử lý được, không crash
```

### Độ trễ

```
p50/p95 mỗi intent, fail build nếu vượt bảng G1
mọi lời gọi ngoài có deadline: giả lập treo → phải ra câu dựng sẵn, không treo
lock không bị giữ quá 5 ms   (đo trực tiếp)
```

### Ngắt lời

```
nói đè khi TTS đang chạy
nói đè khi LLM đang stream
lượt mới trong lúc lượt cũ đang gọi host API
```

### Router / pending

```
pending "gọi cho ai?" + user nói "tắt nhạc"   → PHẢI ra music_stop
pending fill/confirm yes/confirm no/select 1/select 2/cancel/repeat
attempt vượt max → đổi chiến lược, không hỏi lại nguyên văn
TTL hết đúng lúc user đang trả lời
intent lạ chen vào giữa pending
emergency khi đang có pending
emergency khi nhạc đang phát
```

### Cuộc gọi đến

```
chuông khi TTS đang đọc câu 40 từ  → cắt trong <= 200 ms
chuông khi đang có pending          → pending còn nguyên sau khi xử lý xong
số lạ → đọc từng chữ số
trùng tên → đọc đuôi số
announce_caller = ring_only → không đọc tên
```

### Nhiều thiết bị

```
pending device A độc lập với device B
nhạc device A độc lập với device B
hai request cùng device cách nhau < 100 ms
```

---

## 24. Câu hỏi còn mở của phần II

1. **F4 — chọn (a) song song hay (b) hai pha** cho tầng ảnh lớn? Đang đề xuất
   (a) cho tầng 640 và (b) cho tầng 1600. Cần đo RTT thật qua Cloudflare tunnel
   để chốt: nếu RTT > 400 ms thì (b) mất giá.
2. **Ngưỡng blur cho từng tầng ảnh (F5)** — chưa đo. Phải chụp mẫu ở 640 và
   800 native rồi tính lại phân bố Laplacian, không suy ra từ số của 1600.

---

## 25. Chất lượng đọc chữ (OCR): model, khung hình, hướng ảnh

Mục 4 lo **ngữ cảnh** của OCR ("đọc dòng thứ 2", cache transcript) — tức là làm
gì với chữ **sau khi** đã đọc được. Mục này lo chuyện trước đó: **đọc được hay
không**. Hai mục độc lập, làm song song được.

Ngày bổ sung: 2026-08-21 · Nguồn: một ca thật — ảnh chụp cuốn brochure RMIT đặt
trên bàn, Gemini không đọc ra chữ nào.

### Hiện tại

`models/ocr/__init__.py:31` gọi đúng **một** lượt Gemini, model lấy từ
`config.GEMINI_MODEL`. Không có bước tiền xử lý ảnh nào giữa bytes của kính và
`types.Part.from_bytes` ở `models/vlm/client.py:96` — không xoay, không crop,
không tăng tương phản.

Việc chỉnh hướng ảnh **đang được giao hết cho prompt**
(`models/ocr/prompts.py:15`):

> "Ảnh có thể bị nghiêng hoặc ngược chiều — tự xoay lại trong đầu rồi hãy đọc."

Gate ảnh (`pipeline/image_quality.py`) **cố ý không** chặn `ocr` theo độ nét —
chỉ `money` mới chặn. Quyết định đó vẫn đúng, mục này không đụng vào.

### Vấn đề

#### 25.1 — Đang chạy model `-lite` cho tác vụ khó nhất trong pipeline

`models/.env` đặt `GEMINI_MODEL=gemini-3.5-flash-lite`. Biến này dùng chung cho
**mọi** handler VLM: `ocr`, `space`, `hazard`, `find`, `money`, `chat`.

Trong nhóm đó, `ocr` đòi hỏi cao nhất: `space`/`hazard` chỉ cần nhận ra khối
lớn, sai vài chi tiết vẫn ra câu trả lời có ích; `ocr` sai một ký tự là đọc sai.
Đọc chữ nhỏ trên ảnh nghiêng đúng là chỗ bản `-lite` thua bản đầy đủ nhiều nhất.

Đây là biến dùng chung nên **không đổi thẳng được**: nâng `GEMINI_MODEL` kéo
theo `space`/`hazard` chậm hơn — mà hai cái đó là intent đi bộ, cần nhanh.

Cùng lý do đã tách `GEMINI_INTENT_MODEL` và `GEMINI_SEARCH_MODEL`
(`config.py:95-121`): mỗi bước có ràng buộc riêng thì phải có biến riêng.

#### 25.2 — Ba lỗi khung hình, không phải lỗi model

Ca thật đang xét, ảnh hỏng ở ba chỗ cùng lúc:

```
1. xoay 180°            — chữ lộn ngược hoàn toàn
2. góc chụp sát mặt bàn — perspective gắt, dòng chữ bị nén dẹp còn vài pixel
3. chữ quá nhỏ trong khung — hơn nửa khung là mặt bàn trống
```

Lỗi (3) là lỗi giết chết. Dưới khoảng **20 px chiều cao ký tự**, không model nào
— VLM hay OCR chuyên biệt — đọc chắc được; nó chuyển sang đoán theo hình dạng
từ. Lỗi (2) nhân thêm (3): perspective làm chiều cao ký tự ở nửa xa co lại thêm
vài lần.

Không sửa được ba thứ này bằng cách đổi model. Phải sửa ở **lúc chụp**.

#### 25.3 — Người khiếm thị không biết mình chụp hỏng ở đâu

Ảnh trả về `KHONG_CO_CHU` → câu duy nhất người dùng nghe được là
`"Không thấy rõ chữ trong ảnh, vui lòng chụp lại."` (`models/ocr/__init__.py:10`).

Câu này **không nói phải sửa cái gì**. Người sáng nhìn màn hình là biết ngay
"à, chụp xa quá"; người khiếm thị chụp lại y hệt tư thế cũ, hỏng y hệt, và
không có gì trong luồng ngăn vòng lặp đó. Lần chụp thứ hai không được cấp thêm
một thông tin nào so với lần một.

#### 25.4 — Độ phân giải thật đang **mâu thuẫn với tài liệu**

`CLAUDE.md` và docstring `pipeline/image_quality.py:8` đều ghi camera là
**1600x1200**. Nhưng đo 37 ảnh trong `storage/`:

```
Counter({(1280, 720): 37})     # 37/37 ảnh, không có ngoại lệ
```

1280x720 = 0.92 MP, so với 1600x1200 = 1.92 MP — **chưa tới một nửa số pixel**,
và tỉ lệ 16:9 cắt mất chiều dọc, đúng chiều mà một trang giấy cần nhất.

Hai hệ quả, cả hai đều **âm thầm**:

```
1. Ngưỡng Laplacian trong image_quality.py đo trên 83 request "1600x1200"
   — nếu nguồn thật là 1280x720 thì bộ số min=0.70 / median=19.38 / max=108.94
   không mô tả cấu hình đang chạy. Cùng loại bẫy đã cảnh báo ở F5.
2. Bảng F4 ghi `ocr` dùng 1600x1200 q8. Nếu firmware không hề gửi được mức đó
   thì F5 (xin ảnh tầng cao) đang lên kế hoạch cho một tầng ảnh không tồn tại.
```

**Chưa kết luận được** đây là firmware đã đổi cấu hình hay `storage/` là ảnh từ
nguồn test khác. Phải xác minh trước khi làm gì tiếp — xem H0.

#### 25.5 — Không có số liệu về tỉ lệ đọc hỏng

`KHONG_CO_CHU` không được đếm ở đâu. Không biết OCR hỏng 5% hay 50% số lượt, nên
không có mốc để nói bất kỳ cải tiến nào dưới đây có tác dụng hay không.

### Cải thiện

- **H0** — ✅ **ĐÃ XONG, xem 27.5**: firmware chốt **1280×720 quality 18**
  (`src/camera/camera_device.cpp`). Tài liệu ghi 1600×1200 là sai, không phải
  firmware đổi. Việc còn lại: sửa tài liệu + đo lại ngưỡng Laplacian.
  *(mô tả gốc)* Xác minh độ phân giải firmware đang gửi
  thật. Đọc `your-eyes-esp32-firmware.ino`, đối chiếu `storage/`. Sửa cho khớp:
  hoặc sửa `CLAUDE.md` + docstring `image_quality.py` + bảng F4 về đúng số thật,
  hoặc sửa firmware về 1600x1200 nếu đó vẫn là ý định. Nếu số thật là 1280x720
  thì **đo lại ngưỡng Laplacian** trên chính bộ ảnh đó.

- **H1** — Tách `GEMINI_OCR_MODEL`, mặc định **bản không `-lite`**:

  ```python
  # config.py, cạnh GEMINI_SEARCH_MODEL
  GEMINI_OCR_MODEL = get("GEMINI_OCR_MODEL", "gemini-3.5-flash")
  ```

  `models/ocr/__init__.py` truyền model này xuống `vlm.generate_stream` (hiện
  `client.py:96-120` hardcode `config.GEMINI_MODEL` — thêm tham số
  `model: str | None = None`). Handler khác không đổi một dòng.

  Rẻ nhất trong mục này và phải làm trước, vì nó đổi **mốc so sánh** cho mọi mục
  sau: đo H2/H3 trên nền model lite là đo nhầm.

  Đổi lại: OCR chậm hơn. Chấp nhận được — `ocr` vốn là intent người dùng chờ lâu
  nhất (đã ghi ở F5), và đọc sai đắt hơn đọc chậm.

- **H2** — Retry xoay ảnh, **chỉ trên đường hỏng**. Lượt đầu trả `KHONG_CO_CHU`
  → xoay 180° bằng PIL rồi gọi lại một lần. Đường thành công không đổi, nên
  không tốn một mili giây nào của lượt đọc được.

  Chỉ 180°, không quét cả 4 hướng: mỗi hướng là một lượt gọi nữa, và kính đeo
  đầu thì lỗi hay gặp là lộn ngược chứ không phải nằm ngang.

  > Làm H2 **sau** khi đo H1. Có khả năng bản không `-lite` tự xử lý được ảnh
  > ngược, lúc đó H2 là công thừa. Đừng làm cả hai rồi mới đo.

- **H3** — Câu hướng dẫn chụp lại phải **cụ thể và tăng dần**, thay cho một câu
  chung chung dùng mãi:

  ```
  lần 1: "Không thấy rõ chữ. Đưa kính lại gần trang giấy hơn, cách khoảng một
          gang tay."
  lần 2: "Vẫn chưa đọc được. Hướng kính thẳng xuống trang giấy, đừng chụp
          chếch từ bên cạnh."
  lần 3: "Chưa đọc được. Thử đặt trang giấy lên mặt phẳng, chỗ đủ sáng."
  ```

  Đếm lần bằng `attempt_count` của pending (21.2) — không dựng bộ đếm riêng.
  Ba câu cố định → dựng sẵn audio qua `pipeline/phrases.py` (G5), thêm vào
  `STATIC_SPEECH` của module tương ứng.

  Đây là mục **lợi nhất trên công bỏ ra** của cả mục 25: không tốn compute,
  không tốn độ trễ, và nó sửa đúng nguyên nhân số một (25.2) mà H1 không chạm
  tới được.

- **H4** — Bench trước khi chốt, không chốt theo cảm giác. Script chạy trên bộ
  ảnh thật trong `storage/`, ma trận:

  ```
  model:    gemini-3.5-flash-lite  ×  gemini-3.5-flash  ×  gemini-2.5-flash
  biến thể: nguyên bản  ×  xoay 180°  ×  crop vùng chữ
  đo:       đọc đúng / đọc sai / KHONG_CO_CHU  +  p50, p95 độ trễ
  ```

  Bộ ảnh phải gồm cả ca hỏng (ảnh brochure lộn ngược ở 25.2) lẫn ca thường, nếu
  không thì chỉ đo được một đầu của phân bố.

  Cùng nguyên tắc đã dùng cho `GEMINI_INTENT_MODEL` (`config.py:104-110`) và cho
  ngưỡng blur: **có bảng số trong repo thì mới được chốt**.

- **H5** — Ghi log `KHONG_CO_CHU` kèm `sharpness` / `brightness` đã đo sẵn ở
  gate. Có số này mới trả lời được "OCR hỏng bao nhiêu phần trăm", và mới biết
  H1–H3 kéo được xuống bao nhiêu. Rẻ, làm sớm.

- **H6** — Ưu tiên **khung hình hơn độ phân giải**. Nâng 1280x720 → 1600x1200
  chỉ tăng chiều cao ký tự khoảng 1.5×; đưa kính lại gần để chữ chiếm trọn khung
  thì tăng 3–5×. Kết luận cho F5: tầng ảnh lớn dành cho `ocr` là **đúng nhưng
  không đủ** — không có H3 thì tầng đó chỉ chụp nét hơn đúng cái khung hình sai.

- **H7** — OCR chuyên biệt: **phương án cuối**, chỉ khi H1+H3+H4 đo xong vẫn
  không đạt.

  Không quay lại PaddleOCR local. Lý do đã ghi ở `models/ocr/prompts.py:3-6`
  (CPU mất hàng chục giây), và còn một lý do nặng hơn: **PaddleOCR hỏng trên
  đúng ca 25.2** — perspective gắt cộng chữ nhỏ là điểm yếu chung của mọi OCR,
  nó không cứu được gì mà mất thêm 20 s.

  Nếu vẫn cần, đi hướng cloud: Google Cloud Vision `DOCUMENT_TEXT_DETECTION`
  (~200–400 ms, chịu ảnh xoay/nghiêng tốt hơn VLM), lấy text rồi đẩy sang Gemini
  dịch. Đổi lại: quay về kiến trúc **hai chặng** vừa bỏ, mất khả năng "vừa đọc
  vừa dịch trong một lượt", và thêm một nhà cung cấp nữa phải quản key + hạn
  mức. Chỉ trả cái giá đó khi có số của H4 chứng minh là cần.

### Thứ tự thi công mục 25

```
1. H0  xác minh độ phân giải thật     ← chặn: sai số nền thì đo gì cũng sai
2. H5  log KHONG_CO_CHU               ← rẻ, tạo mốc để đo H1/H3
3. H1  tách GEMINI_OCR_MODEL          ← đổi mốc so sánh, phải trước H2
4. H4  bench ma trận model × biến thể
5. H3  câu hướng dẫn chụp tăng dần    ← lợi nhất trên công, độc lập H1/H2
6. H2  retry xoay 180°                ← chỉ làm nếu H4 chứng minh là cần
7. H7  OCR chuyên biệt                ← chỉ khi tất cả trên đều không đạt
```

H3 độc lập với H0–H2, làm song song được. H2 và H7 đều **có điều kiện** — không
lên lịch trước khi có số.

### Test mục 25

```
ảnh xoay 180°  → H2 bật: đọc ra chữ; H2 tắt: ra KHONG_CO_CHU, không crash
ảnh không có chữ (tường trắng) → KHONG_CO_CHU, KHÔNG retry vô hạn
H2 chỉ gọi Gemini lần hai khi lượt đầu ra KHONG_CO_CHU (đếm số lời gọi)
GEMINI_OCR_MODEL khác GEMINI_MODEL → space/hazard vẫn dùng model cũ
attempt 1/2/3 ra ba câu hướng dẫn KHÁC nhau, cả ba đều có audio dựng sẵn
p95 độ trễ ocr sau H1 vẫn nằm trong ngân sách bảng G1
```

### Câu hỏi còn mở của mục 25

1. **Độ phân giải thật là bao nhiêu (H0)?** Chưa xác minh. Chặn F5 và chặn việc
   đo lại ngưỡng blur.
2. **Bản không `-lite` có tự xử lý được ảnh xoay 180° không?** Chưa đo. Quyết
   định H2 có tồn tại hay không nằm ở câu trả lời này.
3. **Ngân sách độ trễ cho `ocr` là bao nhiêu (G1)?** Bảng G1 chưa chốt số cho
   `ocr`. Không có nó thì không nói được H1 "chậm hơn" là chấp nhận được hay
   không.

---

## 26. App Android (`apps/android`) — trạng thái thật

Ngày bổ sung: 2026-08-21 · Nguồn: đọc thẳng
`D:\Study\innostar\app_demo_backend\apps\android`.

Mục 8, 9, 11, 12 và 21.8 đều có phần "việc phía Android". Mục này gom **trạng
thái thật của app** — thứ mà các mục đó đang giả định mà chưa ai mở ra kiểm.
Vài giả định trong đó **sai**, và sai theo hướng làm hỏng đúng nhóm việc đang
tựa lên nó.

Mã cải thiện mục này dùng tiền tố **P**.

### Bối cảnh: có ba thư mục cùng tên "app"

| Đường dẫn | Là gì | Chạy được chưa |
|---|---|---|
| `app_demo_backend\apps\android` | **App thật** — Kotlin + Compose, nhận FCM, chạy action | ✅ đang chạy, là thứ mọi mục khác nói tới |
| `innostar\app` | Mockup Expo/React Native, **không có một lời gọi mạng nào** | ❌ chỉ là UI demo |
| `visioncare-workspace\Your-eyes-visioncare-mobile-app` | Skeleton tài liệu, **chưa chọn framework** (ADR-005) | ❌ chưa có mã nguồn |

Mọi chỗ trong spec này nói "app" đều là dòng **đầu tiên**. Ghi ra đây vì ba thư
mục rất dễ đọc nhầm, và hai cái dưới không làm được gì.

### 26.1 — 🔴 `contact_call`: **không hề có tìm mờ** (sửa lại mục 9)

Mục 9 viết *"Host tự tìm mờ theo tên"*. **Sai.** `ActionRegistry.kt:110` so khớp
**bằng nhau tuyệt đối**, chỉ bỏ qua hoa thường:

```kotlin
if (name.trim().lowercase(Locale.getDefault()) != normalizedQuery) continue
```

Hệ quả, cái nào cũng nặng:

- "Nguyệt Anh" **không** khớp "Nguyễn Nguyệt Anh". Sai một dấu, thừa một họ,
  lệch một khoảng trắng → 0 kết quả.
- STT sai dấu là hỏng hẳn, không có tầng nào đỡ.
- `MULTIPLE_CONTACTS_FOUND` chỉ nổ khi hai contact **trùng tên hiển thị y hệt**
  — ca hiếm. Nghĩa là **D6 gần như không bao giờ chạy**, còn `CONTACT_NOT_FOUND`
  mới là đường hỏng chính.
- Quét **toàn bộ** bảng `Phone` với `selection = null` rồi lọc bằng vòng lặp
  Kotlin — O(n) mỗi cuộc gọi, ngay trên đường tới hạn.

→ Kết luận cho nhóm **D**: **H3 (endpoint danh bạ) không còn là "bản đẹp hơn",
nó là bản duy nhất chạy được.** Fuzzy phải nằm ở server kính (**D7**), vì phía
app không có gì để cải thiện dần — nó không có thuật toán nào cả.

- **P1** — `ContactLookup.findByName` đổi sang tìm mờ, hoặc **tốt hơn**: thêm
  action `contact_list` trả cả danh bạ (id, tên, đuôi số) để server kính tự
  khớp. Đây chính là **H3** của mục 9, giờ đã biết phải sửa ở file nào.

### 26.2 — `candidates[]` có thật, nhưng số bị che và **không có id**

`ActionRegistry.kt:500-511` **có** kèm `details.candidates[]`, nên D6 đọc được
tên thật. `phone_number` đi qua `maskPhoneNumber()` → còn `***456`.

- Việc che số **đúng** với luật riêng tư ở D7 (chỉ đọc 3-4 chữ số cuối). Giữ.
- Nhưng **H1 (`contact_id`) không có đường nào lấy**: `ContactLookup.Match` chỉ
  mang `name` + `number`, không mang id của `ContactsContract`. Lượt gọi lại
  **buộc** phải gửi lại `name`, mà `name` thì rơi vào 26.1. Vòng kín.

- **P2** — `Match` mang thêm `contact_id`, trả trong `candidates[]`, và
  `contact_call` nhận `contact_id` để bỏ hẳn bước tìm. Đây là **H1** ở mục 9 —
  và nó là **việc phía app**, không phải việc phía host như đang ghi.

### 26.3 — `ride_quote`: giá là số bịa, và Grab mở ngay ở lượt báo giá

`ActionRegistry.kt:1391-1397` trả về **hằng số**:

```kotlin
"product_type" to "GrabCar",
"price_estimate" to mapOf("currency" to "VND", "amount" to 85000),
"eta_minutes" to 6,
```

85 000 đ và 6 phút **không đến từ đâu cả** — comment ngay phía trên đã ghi rõ là
"demo-deterministic". Mục 12 nói *"người dùng không biết giá"*; thực tế nặng
hơn: **đã có sẵn một con số giả nằm đúng chỗ mà R3 định đọc lên**. Làm R1/R3 mà
không đụng vào đây thì hệ thống đọc "tám mươi lăm nghìn" bằng giọng tự tin cho
mọi chuyến, mọi quãng đường.

Thêm nữa, `RideQuoteHandler` **mở Grab ngay tại lượt báo giá** (dòng 1387), rồi
`ride_confirm` mở Grab **lần thứ hai**.

- **P3** — Xoá `price_estimate` / `eta_minutes` bịa. Không có nguồn giá thật thì
  **không trả trường giá**, để server kính không có gì đọc nhầm. Giá thật chỉ
  xuất hiện khi có Farefeed (mục 12) — và lúc đó nó thuộc server app 8001, không
  thuộc app Android.

### 26.4 — 🔴 `ride_confirm` gửi người dùng tới một toạ độ cố định

`ActionRegistry.kt:1418`:

```kotlin
openGrabDeepLink(context, 10.7721, 106.6578, "diem den")
```

Điểm đến bị **viết chết**. Không đọc `quote_id`, không đọc điểm đến của lượt
trước. Nói "đặt xe đi Bưu điện Thành phố" rồi xác nhận → Grab mở ra với một toạ
độ cố định, nhãn `"diem den"`.

`RideQuoteHandler:1379-1381` cũng mặc định về đúng cặp số đó khi thiếu toạ độ:

```kotlin
val lat = destObj?.optDouble("lat", 10.7721) ?: 10.7721
```

Mà server kính **chỉ gửi `{"address": destination}`**, không gửi `lat`/`lng`
(`handlers/ride.py:47-51`). Nên nhánh mặc định **luôn** trúng: **mọi chuyến xe
đều có điểm đến là 10.7721, 106.6578.**

Ghép với `_DEMO_CURRENT_LOCATION` ở mục 12: **cả điểm đón lẫn điểm đến đều là
hằng số.** Mục 12 mới ghi một nửa vế đó.

Với người khiếm thị đây là ca hỏng tệ nhất trong toàn spec: họ không nhìn màn
hình Grab, không có cách nào biết điểm đến vừa bị thay.

- **P4** — Bỏ mọi toạ độ mặc định trong `RideQuoteHandler` / `RideConfirmHandler`.
  Thiếu toạ độ → trả `INVALID_DESTINATION`, **không đoán**.
- **P5** — `RideConfirmHandler` dùng lại điểm đến của đúng `quote_id` (lưu map
  `quote_id → {lat, lng, address}` lúc quote), không dựng lại từ hằng số.
- **P6** — Phải có bước **geocode** `address → lat/lng` trước khi tới Grab. Hiện
  **không ai làm**: server kính không, app không. Chọn một chỗ rồi ghi vào hợp
  đồng — hợp lý nhất là server app 8001, cùng chỗ sẽ gọi Farefeed (mục 12).

### 26.5 — `nav_start` không bao giờ trả `INVALID_DESTINATION`

`NavigationStartHandler` luôn trả `Success`: ném chuỗi địa chỉ vào
`google.navigation:q=` rồi để Maps tự hiểu, không kiểm địa điểm có tồn tại
không.

Nghĩa là **D4** (đặt pending từ `INVALID_DESTINATION`, mục 14) đang ánh xạ một
mã lỗi **không có nguồn phát**. Cùng cảnh — server kính có câu nói sẵn trong
`_ERROR_SPEECH` nhưng app không đời nào gửi:

```
INVALID_DESTINATION · NAVIGATION_NOT_FOUND · NAVIGATION_ALREADY_STOPPED
QUOTE_NOT_FOUND · QUOTE_EXPIRED · MUSIC_ACCOUNT_NOT_CONNECTED
NO_ACTIVE_PLAYBACK · SMS_PERMISSION_DENIED · RIDE_ACCOUNT_NOT_CONNECTED
```

Chiều ngược lại, mã app **có** phát mà server kính **không** có câu:
`PLAYBACK_FAILED`, `INVALID_VOLUME`, `INVALID_PARAMS`, `CALL_FAILED`,
`UNSUPPORTED_ACTION`, `NAVIGATION_START_FAILED`, `RIDE_CONFIRM_FAILED` — rơi
vào nhánh mặc định, đúng chỗ **21.7** đòi phải có fallback.

- **P7** — Đối chiếu danh sách mã app phát ra với `_ERROR_SPEECH`
  (`handlers/result_speech.py:13-45`), rồi chọn cho từng mã: app bổ sung đường
  phát, hoặc server kính xoá câu chết. Không để bảng ánh xạ mô tả một hệ thống
  không tồn tại. Việc này **chặn D4** — không có nguồn lỗi thì không test được.

### 26.6 — Vị trí: không ai kiểm độ cũ của toạ độ (bổ sung mục 8)

Mục 8 đã chỉ đúng nguyên nhân (`getLastKnownLocation()` trả null,
`ActionRegistry.kt:335-347`). Hai thứ mục 8 **chưa** ghi:

1. **Không có kiểm tra tuổi.** App trả `captured_at` lấy từ `location.time`
   nhưng không lọc; server kính cache lại và cũng không so với hiện tại. Một fix
   từ ba tiếng trước được dùng y như fix mới — cho câu "quanh đây có gì", và
   (nếu làm nhóm R) cho **điểm đón xe**.
2. **Chưa có `play-services-location`** trong `app/build.gradle.kts`. Đề xuất
   "đổi sang `FusedLocationProviderClient`" ở mục 8 kéo theo thêm dependency,
   không phải sửa một lời gọi.

- **P8** — App: dùng `getCurrentLocation()` (Fused), và **từ chối** trả fix cũ
  hơn ngưỡng (đề xuất 120 s) thay vì trả kèm timestamp rồi mặc kệ.
- **P9** — Server kính: `_location_text()` đọc `captured_at`, quá hạn thì nói
  thẳng *"vị trí này đã cũ"*. Cùng chỗ đang sửa ở **C1**, không phát sinh việc
  mới.

### 26.7 — Quyền và cấu hình mà người khiếm thị không tự bật được

Ba thứ phải bật **bằng tay trong Cài đặt hệ thống**, không có API xin:

| Cần cho | Thứ phải bật |
|---|---|
| `music_play` đường dự phòng YouTube Music | Notification listener (`MediaControlListenerService`) |
| lệnh chạy khi màn hình khoá | `SYSTEM_ALERT_WINDOW`, bỏ tối ưu pin |
| `emergency_call` chạy từ push nền | `ACCESS_BACKGROUND_LOCATION` — phải chọn "Luôn cho phép" |

Người khiếm thị tự đi qua các màn hình đó là rất khó, và **không có đường nào
báo về server kính rằng chúng chưa bật** — hỏng hiện ra dưới dạng một mã lỗi
chung ở tận đầu bên kia.

- **P10** — Action `capabilities_get`: app trả trạng thái từng quyền/cài đặt.
  Server kính đọc lúc ghép máy, và khi một chức năng hỏng thì nói đúng thứ đang
  thiếu (*"chưa bật quyền đọc thông báo nên chưa phát nhạc được"*) thay vì
  *"chưa phát được nhạc"*.

### 26.8 — `emergency_call`: số khẩn cấp nằm trong SharedPreferences

`ActionRegistry.kt:392` đọc từ `SharedPreferences` (đặt ở màn hình Overview /
Safety). Chưa cài → `EMERGENCY_CONTACT_NOT_CONFIGURED`, và người dùng chỉ biết
điều đó **vào đúng lúc gọi cấp cứu**.

Phần còn lại của handler làm **tốt hơn** mức spec đòi: SMS kèm link vị trí chạy
**song song** với cuộc gọi, có timeout riêng, không chặn tiếng chuông (dòng
424-440) — comment ghi rõ đã từng đo một lần chờ 20 giây vì làm tuần tự. Giữ
nguyên; đây là bản mẫu của **G6**.

- **P11** — Kiểm `emergency_contact` lúc ghép kính / lúc khởi động, không phải
  lúc gọi. Chưa cài → nhắc một lần bằng giọng nói.

### 26.9 — Chưa có gì cho mục 21.8 (cuộc gọi đến)

App **chưa có** `TelephonyCallback`, chưa xin `READ_PHONE_STATE`, chưa có đường
đẩy event tự phát lên host. Mục 21.8 mô tả đúng việc phải làm; ghi ở đây để rõ
rằng nó bắt đầu từ **con số không**, không phải sửa cái đang có.

### 26.10 — Tổng hợp: mục nào của spec đang tựa lên giả định sai

| Nhóm | Spec tưởng | Thật ra | Phải làm gì trước |
|---|---|---|---|
| **D6/D7** | host tìm mờ, chỉ cần xử `candidates[]` | so khớp bằng nhau tuyệt đối | **H3/P1** thành đường chính, không phải dự phòng |
| **H1** | host bổ sung `contact_id` | app không lấy id bao giờ | **P2**, việc phía app |
| **D4** | `INVALID_DESTINATION` có thật | không có nguồn phát | **P7** |
| **R1/R3** | thiếu giá | có sẵn **giá giả** đúng chỗ sẽ đọc | **P3** |
| **R6** | sai mỗi điểm đón | sai **cả** điểm đến | **P4/P5** |

### Câu hỏi còn mở của mục 26

1. **P1 hay P2 trước?** Làm được `contact_list` (P1) thì P2 thành thừa — server
   kính tự có id. Không tác động được vào app thì P2 là mức tối thiểu, và nhóm D
   chỉ chạy được nửa vời.
2. **Ai geocode (P6)?** Server kính, server app, hay app Android. Chưa chốt là
   chặn cả **R** lẫn **P4/P5**.
3. **`ride_quote` mở Grab ngay ở lượt báo giá** — sửa ở app (chỉ mở khi confirm)
   hay đổi hợp đồng để có một action `ride_quote` không mở UI? Ảnh hưởng thẳng
   tới luồng hai lượt của mục 12.

---

## 27. Firmware ESP32 — đối chiếu với bản đang chạy

Ngày bổ sung: 2026-08-21 · Nguồn: `your-eyes-esp32-firmware\README.md`,
`src/net/api_client.cpp`, `src/audio/audio_service.cpp`, `app_config.h`,
`src/camera/camera_device.cpp`.

Phần II (mục 19-24) viết trước khi đọc firmware. Bản đang chạy đã đi xa hơn
nhiều so với những gì F2/F7 giả định: vài mục **đã xong**, một mục **sẽ làm hỏng
nếu thi công đúng như đang viết**. Mục này sửa lại, không lặp phần còn đúng.

### 27.1 — 🔴 F2 (audio trước ảnh) sẽ làm CHẬM đi, không nhanh lên

F2 giả định luồng `[image ~2s][audio]` — ảnh chặn STT hai giây. Bản thật không
chạy như vậy (`src/audio/audio_service.cpp`):

```
t=0   BAM NUT   apiBegin() -> photoCapture() -> apiPushImage()  > anh di NGAY
                apiAudioOpen()                                  > mo part audio
...   GIU NUT   nen ADPCM, day tung khoi 256 B  > tieng di TRONG LUC DANG NOI
t=T   NHA NUT   con lai 0-101 ms
```

Số đo thật (README §4): đẩy ảnh 25 KB mất **289 ms**, và 289 ms đó nằm **trong
lúc người dùng còn đang nói** — không tốn của đường tới hạn một mili giây nào.
Không phải 1-2 giây như F2 ước tính.

Đảo thứ tự part thì **hỏng**: part `audio` chỉ đóng được lúc nhả nút, mà
multipart là tuần tự → ảnh buộc phải đợi tới sau nhả nút. Ảnh chuyển từ "miễn
phí" thành "+289 ms trên đường tới hạn".

- **F2 bị huỷ.** Cách đúng để ảnh không chắn audio là **F3** (tách socket
  `/frame`), vốn đã có trong spec. F3 lên thay chỗ F2 ở bảng thứ tự mục 22.

### 27.2 — F7: phần lớn đã xong

| Việc trong F7 | Trạng thái thật |
|---|---|
| audio trước ảnh | ❌ **huỷ** — xem 27.1 |
| `Connection: keep-alive` | ✅ có, giữ phiên 60 s (`TLS_KEEPALIVE_MS`) |
| Cache IP, bỏ DNS mỗi request | ✅ `apiResolve()`; DNS chỉ một lần lúc khởi động |
| Chụp lúc **bắt đầu** nói | ✅ `photoCapture()` chạy ngay khi bấm nút |
| Phát audio từ chunk đầu | ✅ `waitAndPlay()`, đệm tự điều chỉnh |
| TLS session resumption | ⚠️ không áp dụng — **TLS đang TẮT**, xem 27.3 |
| `TCP_NODELAY` | ⚠️ chỉ có ở đường **chẩn đoán** (`wifi_manager.cpp:520`); socket thật trong `api_client.cpp` không gọi `setNoDelay()` |
| `X-Device-Id` / `X-Turn-Id` | ❌ chưa có (`api_client.cpp:432`) — **F1 vẫn chặn nhiều nhất** |
| Bỏ ảnh cho intent không cần | ❌ chưa — cần F3 + F6 trước |
| Ảnh phân tầng | ❌ chưa — xem 27.5 |

Còn đúng ba việc: **F1**, `setNoDelay(true)` trên socket thật, và nhóm F3/F5/F6.

### 27.3 — 🔴 TLS đang tắt: ảnh và giọng nói đi bản rõ

`app_config.h:52` — `#define API_USE_TLS 0`.

Quyết định này có số đo đằng sau: bắt tay TLS tốn **3992-4851 ms** CPU của
ESP32-S3 (không có tăng tốc phần cứng cho ECC). Nhưng hệ quả phải nằm trong
spec chứ không chỉ trong README firmware:

> Ảnh chụp **trong nhà người dùng** và **giọng nói** của người khiếm thị đang đi
> **không mã hoá** trên chặng kính → Cloudflare. Ai ở cùng lớp Wi-Fi (hotspot
> điện thoại) đều đọc được.

Đây là chặn phát hành, không phải việc tối ưu.

Đường thoát đã có sẵn, chỉ chưa ghép: `apiWarmUp()` mở phiên **trước** khi người
dùng bấm nút và giữ 60 s. Bật TLS mà giữ được phiên nóng thì 4-5 giây kia nằm
ngoài đường tới hạn. Rủi ro còn lại: bấm nút sau hơn 60 s im lặng → lượt đó ăn
trọn 4-5 giây.

- **F9** — Bật `API_USE_TLS 1`, đo lại p50/p95 với `apiWarmUp()` đang chạy. Lượt
  "nguội" vẫn 4-5 giây thì nới `TLS_KEEPALIVE_MS` và cho `loop()` warm-up chủ
  động — đừng bù bằng cách tắt mã hoá.
- **F10** — Ngân sách **G1 phải đo trên bản có TLS**. Mọi số hiện có đo với
  `API_USE_TLS 0` (README §4 ghi rõ); chốt ngân sách trên nền đó là chốt trên
  một cấu hình không được phép phát hành.

### 27.4 — Hai khoản độ trễ phía **server kính** mà mục 20 chưa đếm

Cả hai nằm ở đầu ra, sau khi TTFB đã tính xong — nên bảng G1 không nhìn thấy.

**(a) Khoảng im 30 giây ở cuối mỗi lượt.** README firmware §4:

> Board **không** đòi miếng kết thúc `0\r\n\r\n` của chunked (server hiện không
> gửi) — nó dựa vào khoảng im 30 giây để biết đã hết.

`BODY_GAP_MS = 30000`. Nếu đúng là server không đóng luồng, mỗi lượt trả về mất
thêm **30 giây** trước khi board coi là xong.

Có mâu thuẫn phải kiểm chứng: `app.py:536` dùng `StreamingResponse`, mà
Starlette + uvicorn **bình thường có** gửi miếng kết thúc khi generator cạn.
Nghĩa là hoặc README firmware đã cũ, hoặc Cloudflare tunnel đang đệm/nuốt nó.

- **G10** — Đo bằng `curl -v --raw` qua đúng tunnel, xem `0\r\n\r\n` có tới
  không. Có thì sửa README firmware; không thì đóng kết nối tường minh sau chunk
  cuối. **Đo trước, sửa sau** — đây có thể là 30 giây, khoản lớn nhất phần II.

**(b) Tốc độ nhả TTS quyết định lúc loa kêu, không phải TTFB.** README §3.3:
board so **giây tiếng nhận được** với **giây đồng hồ**.

| Server nhả | Board làm |
|---|---|
| ≥ 1.30× | đệm 400 ms rồi phát |
| ≥ 1.12× | đệm 1500 ms |
| < 1.12× và **không** biết tổng độ dài | **đợi nhận xong hết rồi mới phát** |

Luồng ADPCM không có `Content-Length` → rơi đúng vào ô cuối. Nghĩa là TTFB
600 ms mà TTS sinh chậm hơn thời gian thực thì người dùng vẫn **không nghe gì**
cho tới khi sinh xong cả câu trả lời. Ngưỡng phải vượt: **10.4 KB/s** với ADPCM
16 kHz.

- **G11** — Thêm vào bảng G1 một dòng đo riêng: **tỉ lệ giây-tiếng / giây-đồng
  hồ ≥ 1.30×**, đo từ chunk đầu tới chunk cuối. Ba việc kéo tỉ lệ lên (README
  liệt kê): flush ngay từng câu; sinh câu n+1 song song với lúc đẩy câu n; không
  chèn im lặng dẫn đầu.

### 27.5 — H0 đã có câu trả lời: **1280×720, JPEG quality 18**

Câu hỏi mở số 1 của mục 25 đóng lại được. Nguồn duy nhất là
`src/camera/camera_device.cpp` — **HD 1280×720, quality 18**, ~67 KB, khớp đúng
37/37 ảnh đo được trong `storage/` (25.4).

Vậy `CLAUDE.md` và docstring `pipeline/image_quality.py:8` ghi 1600×1200 là
**sai tài liệu**, không phải firmware vừa đổi cấu hình.

Kéo theo ba việc:

1. **Sửa tài liệu** về 1280×720 ở cả ba chỗ, kể cả bảng **F4**.
2. **Đo lại ngưỡng Laplacian** trên chính bộ ảnh 1280×720. Bộ số cũ
   (min 0.70 / median 19.38 / max 108.94) đang mô tả một cấu hình không chạy.
3. **F5 phải viết lại thang chất lượng.** Spec ghi `jpeg_q 8` và `q15`, nhưng
   esp32-camera dùng thang **0-63, số nhỏ = nét hơn**, và bản thật đang ở **18**.
   Quy hết số trong F4/F5 về thang đó, nếu không là đọc ngược.

Tầng ảnh lớn của F5 **vẫn làm được** — OV2640 lên tới UXGA 1600×1200, đổi ở
`camera_device.cpp`. Nhưng đổi sang 4:3 là đổi luôn khung nhìn, và **H6** đã kết
luận khung hình quan trọng hơn số pixel. Làm **H3** trước.

> Ghi thêm cho mục 25: `photoCapture()` đã chụp **một loạt rồi giữ khung nét
> nhất** vào PSRAM, và board có sẵn `photoMeasureSharpness()`. Nghĩa là ảnh mà
> gate chất lượng phía server nhận được **đã là khung tốt nhất của loạt** —
> ngưỡng blur phải đo trên phân bố đó, không phải trên ảnh chụp đơn.

### 27.6 — F6 (kênh SSE) nặng hơn spec giả định

Ba thứ chưa có, phải ghi trước khi lên lịch:

1. **Board không có đường nhận chủ động.** Task audio xoay quanh nút bấm; web
   server cổng 80/81 chỉ để chẩn đoán, và board nằm sau NAT của hotspot điện
   thoại nên **server không gọi vào được**. Kênh do board mở là cách duy nhất —
   đúng như F6, nhưng đó là một module mạng **mới**, không phải cấu hình thêm.
2. **Thêm một socket giữ mở lâu** song song với socket POST, trên board đang
   chạy camera + `esp_http_server` + I2S full-duplex. Bật TLS (27.3) thì thành
   **hai** phiên TLS cùng lúc. Phải đo RAM trước — `bigAlloc()` xin buffer lớn
   một lần lúc khởi động, phần còn lại rất mỏng.
3. **21.8 đòi board tự phát tiếng lúc không ai bấm nút.** Trình tự hiện nằm gọn
   trong `audio_service.cpp` và luôn bắt đầu từ nút. Đây là đường mới trong đúng
   file mà kiến trúc firmware gọi là "file DUY NHẤT biết trình tự".

Không có gì chặn hẳn, nhưng F6 **không phải việc nhỏ** — xếp lại công trong bảng
mục 22.

### 27.7 — G8 (earcon) board đã có sẵn

`cueSent()` kêu ngay khi nhả nút, chạy trên core 1 song song với lúc core 0 chờ
server (`audio_cues.cpp`, ~0.94 s). Earcon đã ở **0 ms sau khi nhả nút** — sớm
hơn mọi thứ server làm được.

- **G8 đổi nội dung**: **không** thêm earcon phía server (sẽ thành bíp hai lần).
  Việc còn lại là bảo đảm câu trả lời không đè lên `cueSent()`, và cân âm lượng
  giữa hai bên.

### 27.8 — F8 bổ sung: ràng buộc của board với đầu ra TTS

Ghi lại từ README §3.2, vì `app.py` phải tuân:

```
mono bat buoc            - ADPCM stereo board tu choi thang
16 000 Hz bat buoc       - khac di thi moi luot board doi sample rate I2S hai lan
prelude 60 byte ra TRUOC - board doc header WAV tren luong (app.py:310 dang dung)
chua biet do dai         -> ghi size 0 hoac 0xFFFFFFFF
keep-alive               -> than tra ve phai duoc doc HET, khong thi hai luong lech vinh vien
```

Và mã đọc phía board tin **4 byte đầu của thân**, không tin header HTTP. Đi nhầm
nhánh ADPCM/PCM → SNR **−11 dB**, nghe ra là "loa rè", **không có log nào báo**.
Nên `x-audio-format` và thân phải khớp nhau tuyệt đối.

### 27.9 — Bổ sung vào bảng thứ tự mục 22

```
huy:    F2  (27.1)
them:   F9  bat lai TLS + do warm-up        <- chan phat hanh
        G10 do mieng ket thuc chunked        <- co the la 30 s/luot, DO TRUOC
        G11 ti le nha TTS >= 1.30x
        H0 da xong -> sua tai lieu + do lai nguong blur (27.5)
doi:    G8  khong lam earcon phia server (27.7)
        F6  nang hon du tinh (27.6)
```

Làm ngay, rẻ: **G10** (một lệnh curl), **F1**, `setNoDelay(true)`, và sửa tài
liệu độ phân giải.

### Câu hỏi còn mở của mục 27

1. **Miếng kết thúc chunked có tới board không (G10)?** Chưa đo. Đây là 30 giây
   mỗi lượt nếu README firmware đúng.
2. **Bật TLS rồi thì p95 là bao nhiêu (F9)?** Chưa đo. Không có số này thì bảng
   ngân sách G1 đang mô tả một cấu hình không phát hành được.
3. **RAM còn đủ cho socket SSE thứ hai không (F6)?** Chưa đo, và phải đo **sau
   khi** bật TLS chứ không phải trước.

---

## 28. Cảnh báo vật cản thời gian thực (`hazard_watch`)

| | |
|---|---|
| Mã | W1–W6 |
| Trạng thái | MỚI — chưa có dòng code nào |
| Nguồn tham khảo | `github.com/LuanLuKim/OD_module` (YOLO11n ONNX + risk engine) |

### 28.0 Vì sao mục này tồn tại

Mở đầu Phần II (mục 19) ghi: "cảnh báo vật cản **thời gian thực** (vòng lặp
nền, phát bíp) đã bị đưa ra khỏi kế hoạch." Mục này **lật lại quyết định đó
theo yêu cầu tường minh** — không phải sửa nhầm. `docs/tasks/T16-space-hazard.md`
mục 2.3 cũng chép lại quyết định cũ; T16 **giữ nguyên** (không đổi `hazard`
theo lượt), mục 28 là **tính năng song song mới**, không thay thế.

Thiết kế dưới đây tham khảo `github.com/LuanLuKim/OD_module` — YOLO11n ONNX,
risk engine 3 tầng corridor/proximity/approach, state machine hysteresis +
cooldown. Giữ phần suy luận, đổi phần vận chuyển và cách phát cảnh báo cho khớp
ràng buộc thật của hệ thống này: ESP32-S3-CAM quá yếu để chạy AI (AI **luôn**
chạy phía server), băng qua Cloudflare tunnel, camera hiện chỉ chụp theo nút
bấm (T17), và chưa có đường server → kính chủ động (T18, đang PARTIAL).

### 28.1 Kích hoạt & vòng đời — theo lệnh thoại, không cảm biến

Chức năng là **intent mới**, không phải nền tự động luôn bật:

```
hazard_watch_start   — "bật cảnh báo vật cản" (tên hiển thị cuối cùng để mở)
hazard_watch_stop    — nói khi đang bật, hoặc barge-in cục bộ
```

`device_state()` (mục 3) thêm cờ `hazard_watching: bool`, **độc lập** với
`music_playing`/`navigating` — đúng tinh thần **B7** (đa active-state, không
loại trừ nhau). Trong lúc bật, mọi intent khác (gọi điện, nhạc, chat, chỉ
đường...) vẫn dùng bình thường; chỉ `emergency_call` giữ quyền tuyệt đối như
mục 10, và `hazard_watch` không tranh gì với nó vì cảnh báo không đi qua kênh
TTS (28.5).

- **W1** — Thêm intent `hazard_watch_start`/`hazard_watch_stop` vào SetFit +
  Gemini (mục 2). Thêm regex tắt vào barge-in cục bộ **B1**
  (`pipeline/router.py`): `tắt cảnh báo|dừng cảnh báo|tắt an toàn|dừng chế độ
  an toàn` — chạy khi `hazard_watching=True`, 0 ms, không cần STT đầy đủ, cùng
  cơ chế đã có cho "tắt nhạc"/"dừng chỉ đường".

### 28.2 Uplink khung hình liên tục — tái dùng `/frame` (T17), không giao thức mới

- **W2** — mở rộng `POST /frame`:

```
POST /frame
  X-Device-Id       BẮT BUỘC (như cũ)
  X-Stream-Kind     "turn" (mặc định, hành vi cũ) | "hazard"
  X-Turn-Id         bắt buộc khi Stream-Kind=turn; KHÔNG cần khi =hazard
  X-Capture-Ts      nên có
  body: JPEG tầng thấp (F5)
  → 204 (như cũ)
```

Board mở **một kết nối keep-alive**, gọi lại API đã xanh (F3/T17) liên tục
theo chu kỳ khi `hazard_watching=True` — không bắt tay TLS lại mỗi khung hình.
**Không phải giao thức mới**, chỉ gọi lại API đã có nhiều lần.

**Vì sao HTTP, không UDP:**

| Tiêu chí | UDP | HTTP lặp lại (chọn) |
|---|---|---|
| JPEG tầng thấp ~20-50 KB > MTU 1472B | phải tự phân mảnh + ráp lại, mất gói = ảnh vỡ | TCP lo phân mảnh, ảnh nguyên vẹn hoặc không tới |
| Qua Cloudflare tunnel | cần cấu hình `cloudflared` riêng, rủi ro vận hành thêm | dùng đúng đường HTTPS đang chạy |
| TLS (T22 đang bật) | phải tự làm bảo mật/toàn vẹn gói | có sẵn qua keep-alive |
| Rủi ro code mới trên board | thư viện UDP + logic ráp gói mới hoàn toàn | gọi lại API đã xanh, không tầng giao thức mới |
| Tiền lệ trong repo | — | khớp lý do **F2 bị huỷ** (27.1) — đổi cách gói tin phức tạp trên board đã bị từ chối trước đây |

Khung `Stream-Kind=hazard` lưu vào **slot riêng, 1 khung mới nhất/thiết bị**,
tách khỏi ring 1-3 khung của lượt hỏi-đáp (T17) — tránh đụng
`test_frame_matched_by_turn_id`. Worker suy luận (28.4) tự kéo khung mới nhất
theo nhịp nó xử lý được — đúng chiến lược "latest-frame, size=1" gốc của
OD_module, khớp **nguyên tắc xuyên suốt số 2** (không cache thứ di chuyển).

🔴 Chưa chốt: tần suất gửi (fps), băng thông thực qua Cloudflare tunnel ở tần
suất đó, độ bền kết nối keep-alive qua tunnel khi rảnh — cả ba phải **đo trên
board thật**, giống cách T17/T18 đang xử lý ngưỡng blur/RAM. Không chốt số
trong spec này.

### 28.3 Downlink lệnh — mở rộng kênh T18, không xây kênh mới

- **W3** — hai event mới trên `GET /events` (T18):

```jsonc
// bật/tắt vòng lặp chụp liên tục phía board
{ "type": "hazard_watch", "action": "start" | "stop" }

// mức cảnh báo hiện tại — gửi MỖI KHI MỨC ĐỔI, không phải mỗi khung hình
{ "type": "hazard_level", "level": "SAFE" | "LOW" | "MEDIUM" | "HIGH" }
```

Không gửi audio qua kênh này. Board tự sinh tông cục bộ theo `level` (28.5) —
nhẹ hơn nhiều so với đường T19 (board phát audio khi không bấm nút), vì không
cần giải mã ADPCM, không cần đồng bộ với TTS.

🔴 **Phụ thuộc cứng: T18 phải xong trước.** T18 hiện PARTIAL (server SSE xanh,
firmware chờ board — xem memory board-firmware-lags-repo-head). Không có kênh
downlink thì `hazard_watch` không khởi động được vòng lặp chụp phía board và
không phát được cảnh báo — toàn bộ mục 28 **đứng yên chờ T18**.

### 28.4 Suy luận — nhúng process riêng trong server kính

- **W4** — Kiến trúc: **process/worker riêng trong server kính**, không tách
  microservice port 8002 như OD_module gốc — giữ **nguyên tắc một cửa ra
  ngoài** (chỉ server kính đi qua Cloudflare tunnel). Worker nhận khung qua
  queue nội bộ (đọc từ slot 28.2), chạy tách khỏi vòng lặp asyncio chính để
  không giành CPU với STT/intent ONNX đang chạy in-process
  (`pipeline/intent_local.py`).

Giữ nguyên từ OD_module:

```
YOLO11n ONNX, input 640×640 letterbox, confidence 0.25, NMS IoU 0.45
CorridorEngine   — % diện tích box chồng hành lang đi bộ (trái 20% – phải 80%)
ProximityEngine  — area_weight 0.60 + bottom_weight 0.40
ApproachEngine   — hồi quy tuyến tính độ dốc diện tích box theo thời gian
Risk = w1·Corridor + w2·Proximity + w3·Approach
```

Đổi so với gốc:

```
SAFE/LOW/HIGH (2 tầng)  →  SAFE/LOW/MEDIUM/HIGH (3 tầng)
```

để khớp tông cảnh báo tăng dần 3 mức (28.5). Ngưỡng enter/exit gốc
(0.70/0.55, cooldown 2500 ms) chỉ là điểm khởi đầu cho 2 tầng — **phải đo lại**
để chia 3 khoảng, giữ nguyên cơ chế hysteresis (tăng mức phát ngay, giảm mức
trễ theo cooldown) để chống giật cảnh báo qua lại — đặc biệt cần vì ngưỡng
confidence 0.25 ưu tiên recall, dễ báo dư.

### 28.5 Cảnh báo ra tai người dùng — tông cục bộ, không TTS

- **W5/W6** — board tự sinh tông theo mức, **không** stream audio từ server:

```
SAFE    im lặng
LOW     tít chậm
MEDIUM  tít nhanh hơn, chưa dồn dập
HIGH    liên tục / dồn dập nhất
```

Cùng triết lý đã chọn cho earcon nút bấm (**G8**, `cueSent()` trong
`audio_cues.cpp`): tông cục bộ nhanh hơn và rẻ hơn bất cứ thứ gì server gửi
qua mạng. Cần cơ chế trộn/né cục bộ để tông không chồng lấp lúc board đang
phát TTS câu trả lời khác — đã có tiền lệ kỹ thuật ở chính file đó (earcon
core 1 song song lúc core 0 chờ server).

- **W6** — vòng lặp chụp liên tục: module mới trong `audio_service.cpp`/camera
  loop, kích hoạt bởi event `hazard_watch.start`, dừng bởi
  `hazard_watch.stop`. Cùng loại rủi ro đã ghi ở **27.6/T18** (board không có
  đường chủ động, phải đo RAM/pin trước khi viết) — **không** phải giao thức
  mạng mới (xem 28.2), chỉ là vòng lặp gọi lại API đã có.

### 28.6 Ngoài phạm vi / giới hạn nêu rõ

- Không đọc tên loại vật cản bằng lời (stretch, để mở — xem câu hỏi mở).
- Không đụng server app 8001 — thuần server kính + firmware, khác `ride`/
  `contact_call`.
- Không chốt fps, ngưỡng risk 3 tầng, hay mức tiêu hao pin/băng thông — tất cả
  **để đo trên board thật**.
- Không thay thế `hazard` theo lượt (mục 6/T16) — hai chức năng song song,
  dùng chung ý tưởng risk engine nhưng khác đường vận chuyển và cách phát.

### 28.7 Hợp đồng đổi

Ghi vào `CONTRACTS.md` khi thi công (chưa ghi ở bước spec này, theo đúng quy
ước các mục 19/21 khác):

```
POST /frame          + X-Stream-Kind (mới, mặc định "turn" — không phá đường cũ)
GET  /events          + event hazard_watch, hazard_level (mới)
device_state()        + hazard_watching (mới)
```

### 28.8 Test (phác thảo — chi tiết ở T24)

```
test_hazard_watch_start_sets_state
test_hazard_watch_coexists_with_music_and_navigation      # B7
test_hazard_watch_stop_via_bargein_regex                  # W1, 0ms
test_emergency_call_wins_during_hazard_watch               # mục 10 không đổi

test_hazard_frame_uses_separate_slot_from_turn_frame        # W2
test_hazard_frame_does_not_require_turn_id
test_turn_frame_contract_unchanged                          # X-Stream-Kind mặc định "turn"

test_risk_engine_three_tier_hysteresis                       # W4
test_risk_cooldown_prevents_flicker
test_od_worker_does_not_block_stt_pipeline                   # cách ly CPU

test_hazard_level_event_sent_only_on_change                  # W3, không mỗi khung
test_no_audio_bytes_sent_for_hazard_level                    # 🔴 khoá kiến trúc — không TTS
```

### 28.9 Câu hỏi còn mở

1. Tên chức năng cuối cùng cho người dùng gọi (`hazard_watch` là tên nội bộ).
2. fps thật gửi được qua Cloudflare tunnel ở tầng ảnh thấp — chưa đo (liên
   quan câu hỏi mở T17 mục 6 câu 1).
3. Ngưỡng risk cắt 3 tầng LOW/MEDIUM/HIGH — chưa đo trên dữ liệu thật, chỉ có
   điểm khởi đầu từ bản 2 tầng gốc.
4. Pin tiêu hao thêm khi board vừa giữ kết nối keep-alive `/frame` vừa nghe
   kênh `/events` — chưa đo, cùng loại câu hỏi đã mở ở T18 mục 6 câu 3.
5. Có nên nói một từ (loại vật cản) ở mức HIGH lần đầu trong mỗi cooldown,
   thay vì luôn im lặng-chỉ-tông? Để mở, không phải yêu cầu ban đầu.
