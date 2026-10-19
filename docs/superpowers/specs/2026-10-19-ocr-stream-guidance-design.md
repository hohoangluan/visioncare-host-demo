# OCR có hướng dẫn căn khung — stream 640, chụp full-res, đọc bằng PP-OCRv6 + Gemma

## Bối cảnh

Hôm nay OCR là một lượt chụp duy nhất: kính POST `/process` với audio + một
ảnh 1600×1200, `handlers/ocr.py` gọi `models/ocr.read_stream()`, Gemini vừa đọc
vừa dịch trong một lượt (`models/ocr/prompts.py`). Người dùng không biết ảnh
mình vừa chụp có trúng chữ không, có đủ gần không, có bị cắt mép không — họ
chỉ nghe kết quả, và kết quả sai thì không biết sửa thế nào.

Phần cứng hiện tại (đã chốt cho thiết kế này, không đổi):

| | |
|---|---|
| Board | ESP32-S3-WROOM N16R8 CAM — 16MB flash, 8MB PSRAM octal |
| Cảm biến | OV2640, max 1600×1200 (UXGA), JPEG nén trong cảm biến |
| Lens | 120°, tiêu cự cố định |

Giới hạn quang học quyết định mọi thứ phía sau. Ước lượng hình học (chưa đo —
xem "Hiệu chuẩn"), giữa ảnh, ở 1600px:

| Khoảng cách giấy–kính | px / dòng chữ 10pt |
|---|---|
| 30cm | ~7–11 |
| 20cm | ~10–17 |
| 10cm | ~20–33 |

Ngưỡng đọc chắc tiếng Việt có dấu ước khoảng 28–30px/dòng. Nghĩa là với lens
này, chữ cỡ sách báo chỉ đọc được khi cầm rất gần — và ở khoảng đó lens tiêu
cự cố định có thể mất nét. Thiết kế dưới đây không giả vờ vượt qua được giới
hạn đó; nó (1) đưa người dùng tới vị trí tốt nhất phần cứng cho phép, (2) nói
thật khi chữ quá nhỏ, và (3) không phụ thuộc phần cứng — đổi sang OV5640 sau
này chỉ đổi số hiệu chuẩn, không đổi code.

## Mục tiêu

1. Người dùng **tự căn khung** theo hướng dẫn âm thanh, không cần người sáng
   mắt hỗ trợ.
2. Server **tự chụp** khi khung hình đạt, không bắt người dùng đoán lúc bấm.
3. Đọc chữ chính xác nhất có thể từ ảnh full-res, ưu tiên đúng dấu và đúng số.
4. Làm được tác vụ phức tạp trong bối cảnh Việt Nam: hoá đơn, nhãn thuốc,
   NSX/HSD, giấy tờ, menu/bảng giá, hỏi đáp về tài liệu vừa đọc.

## Không làm (non-goals)

- Quét tài liệu nhiều trang, ghép trang.
- Chữ viết tay (không cam kết; chạy được thì tốt).
- Đổi phần cứng camera trong phạm vi này.

## Thất bại dù chạy đúng kỹ thuật (anti-goals)

- **Hướng dẫn nói nhiều hoặc nhảy qua lại** ("trái… phải… trái…"). Người khiếm
  thị chỉ có một kênh âm thanh; nói dồn dập tệ hơn không nói.
- **Đọc sai số một cách tự tin** — số tiền, liều thuốc, ngày hết hạn. Câu "tôi
  không chắc con số này" luôn tốt hơn một con số bịa.
- **Chậm hơn hiện tại mà không chính xác hơn.** Baseline là luồng Gemini một
  lượt đang chạy; hệ thống mới phải thắng nó trên bộ test (xem "Đánh giá").

## Nguyên tắc thiết kế

1. **Hai tầng tách hẳn.** Vòng hướng dẫn (nhanh, nhẹ, chạy mỗi frame) không
   bao giờ gọi model lớn. Gemma chỉ chạy một lần, sau khi đã có ảnh tốt.
2. **Chỉ hướng dẫn thứ phần mềm không sửa được.** Xoay ảnh, nghiêng nhẹ, phối
   cảnh nhẹ → server tự sửa, không bắt người dùng làm. Chỉ nói khi thiếu
   pixel (khoảng cách), thiếu nội dung (cắt mép), mờ, chói, tối, nghiêng quá
   nặng.
3. **Ngưỡng tính bằng pixel của ảnh chụp, không bằng mm hay % khung hình.**
   "Đủ gần" nghĩa là chiều cao dòng chữ trong ảnh full-res ≥ `OCR_MIN_LINE_PX`.
   Đổi camera → đổi tỉ lệ preview/capture, ngưỡng giữ nguyên.
4. **Âm thanh hướng dẫn phát tại kính, không đi qua TTS.** Server chỉ gửi mã
   lệnh; clip đã nằm sẵn trong flash của ESP32. Độ trễ từ lúc server quyết
   định tới lúc người dùng nghe ≈ một chuyến WiFi.
5. **Độ tin cậy của bước nhận dạng là tín hiệu chất lượng chính.** Laplacian
   trên cả ảnh đã được chứng minh vô dụng với camera này
   (`pipeline/image_quality.py`); mọi chỉ số độ nét chỉ đo trong vùng box chữ
   và chỉ so tương đối trong cùng phiên.

## Kiến trúc tổng thể

```
 Người dùng: "đọc chữ giùm tôi"
        │
        ▼
 Kính ──POST /process (audio, header X-Capabilities: ocr-stream/1)──▶ server
        ◀── audio "Đưa chữ ra trước mặt" + header X-Next-Action: ocr-session; id=…
        │
        ▼  mở WebSocket /ws/ocr/{id}
 ┌──────────────────────── PHIÊN OCR (tối đa OCR_SESSION_MAX_SECONDS) ────────────────────────┐
 │                                                                                           │
 │  Kính ──frame VGA JPEG (≤2 frame đang bay, theo credit)──▶ frame_metrics (det tiny, GPU)   │
 │   ▲                                                              │                        │
 │   │ {"type":"guide","code":"closer"} → kính phát clip có sẵn       ▼                        │
 │   └─────────────────────────────────────────── guidance (máy trạng thái, có trễ)          │
 │                                                                  │ đạt N frame liên tiếp  │
 │  Kính ◀── {"type":"capture","burst":3} ──────────────────────────┘                        │
 │  Kính: chuyển UXGA, bỏ 2 frame, gửi 3 frame, về VGA, dừng stream                           │
 │                                                                                           │
 │  reader: chọn frame nét nhất → xoay/nắn → PP-OCRv6 medium det+rec → dòng + box + conf     │
 │        │ quá ít dòng tin được và còn lượt thử → quay lại vòng hướng dẫn (tối đa 1 lần)     │
 │        ▼                                                                                  │
 │  tasks: chọn tác vụ → (RAW: đọc thẳng) | (khác: Gemma ảnh+text → JSON → kiểm số → câu)   │
 │        ▼                                                                                  │
 │  TTS hiện có → audio chunk qua chính WebSocket → kính phát                                │
 └───────────────────────────────────────────────────────────────────────────────────────────┘
```

Kính cũ không gửi `X-Capabilities: ocr-stream/1` → server giữ nguyên luồng một
lượt hiện tại. Không có ngày "cắt điện" firmware.

## Giao thức kính ↔ server

Một WebSocket cho cả phiên, cả hai chiều. Lý do chọn WS thay vì nhiều HTTP
request: kính phải gửi frame liên tục *và* nhận lệnh bất kỳ lúc nào; HTTP
request của `/process` đã gửi header 200 rồi thì không nhận thêm gì được.

### Kính → server

| Message | Dạng | Nội dung |
|---|---|---|
| Frame preview | binary | header: `kind=0x01` u8, `seq` u32, `t_ms` u32 (đồng hồ kính); sau đó là JPEG (kích thước đọc từ JPEG) |
| Frame capture | binary | `kind=0x02` u8, `seq` u32, `t_ms` u32, `burst_idx` u8; sau đó JPEG UXGA |
| Sự kiện | text JSON | `{"type":"cancel"}` (nút bấm nếu có), `{"type":"error","msg":…}` |

### Server → kính

| Message | Nội dung | Kính làm gì |
|---|---|---|
| `{"type":"credit","n":1}` | cho phép gửi thêm 1 frame preview | gửi frame mới nhất (không xếp hàng frame cũ) |
| `{"type":"guide","code":"closer"}` | mã hướng dẫn (bảng dưới) | phát clip tương ứng trong flash |
| `{"type":"tone","code":"text_found"}` | earcon ngắn | phát earcon |
| `{"type":"capture","burst":3}` | yêu cầu chụp full-res | chuyển UXGA, bỏ 2 frame, gửi `burst` frame, về VGA, **dừng gửi preview** |
| `{"type":"resume"}` | quay lại vòng hướng dẫn | tiếp tục gửi preview |
| binary `kind=0x10` | chunk audio (cùng định dạng `RESPONSE_FORMAT` đang dùng) | phát |
| `{"type":"end"}` | hết phiên | đóng WS |

**Điều khiển luồng bằng credit, tối đa 2 frame đang bay.** Server chỉ cấp
credit khi xử lý xong một frame. Kính không bao giờ gửi nhanh hơn server xử
lý, nên không có hàng đợi tích tụ độ trễ — frame nào tới server cũng là frame
gần như mới nhất. 2 thay vì 1 để che một chuyến RTT.

### Clip hướng dẫn trong flash kính

Câu cố định, ngắn (≤1s), dựng bằng chính TTS của server (`pipeline/tts.py`,
cùng giọng `TTS_VOICE`) rồi nạp vào LittleFS lúc build firmware. Tool mới
`tools/build_guidance_clips.py` sinh bộ clip + file `manifest.json` có
`version`; kính gửi version trong `X-Capabilities` để server không gửi mã kính
chưa có clip.

| Mã | Câu (đề xuất, cần thử với người dùng thật) |
|---|---|
| `no_text` | "Chưa thấy chữ." |
| `maybe_small_text` | "Có thể có chữ nhỏ, đưa lại gần." |
| `closer` | "Lại gần hơn." |
| `farther` | "Ra xa một chút." |
| `look_left` / `look_right` / `look_up` / `look_down` | "Nhìn sang trái." / "…phải." / "…lên." / "…xuống." |
| `face_flat` | "Để mặt giấy thẳng trước mặt." |
| `glare` | "Bị chói, nghiêng giấy một chút." |
| `too_dark` | "Tối quá, ra chỗ sáng hơn." |
| `hold_still` | "Giữ yên." |
| `too_small_limit` | "Chữ quá nhỏ so với camera, tôi sẽ đọc thử." |
| `timeout` | "Chưa căn được chuẩn, tôi đọc thử." |
| tone `text_found`, `shutter` | earcon |

**Hướng theo đầu, không theo tay** ("nhìn sang trái" chứ không phải "đưa giấy
sang phải"): camera gắn trên đầu, nên quay đầu đúng cho cả giấy cầm tay lẫn
biển trên tường. Đây là quyết định của người thiết kế, chưa thử với người khiếm
thị — là thứ đầu tiên cần kiểm chứng ở giai đoạn P2.

## Server

### Module mới

```
pipeline/
  ocr_session.py     # vòng đời phiên: WS handler, credit, timeout, chuyển trạng thái
  frame_metrics.py   # 1 frame preview -> FrameMetrics (dataclass), không biết gì về chính sách
  guidance.py        # chuỗi FrameMetrics -> mã hướng dẫn / capture, có trễ chống nhảy
models/ocr/
  engine.py          # PP-OCRv6: detect(img, tier) / recognize(crops) — singleton lazy theo tier
  reader.py          # burst full-res -> OcrResult (dòng, box, conf, thứ tự đọc)
  tasks/
    __init__.py      # route(command_text, ocr_result) -> Task
    plain.py         # đọc thường / RAW / dịch (giữ 3 mode hiện có)
    receipt.py  medicine.py  expiry.py  id_card.py  menu.py
    schemas.py       # JSON schema từng tác vụ
    verify.py        # đối chiếu số trong JSON với text OCR
models/llm/
  client.py          # OpenAI-compatible client tới Gemma (endpoint trong docs/LLM_PROVIDER.md)
```

`app.py` thêm route WS `/ws/ocr/{session_id}` và nhánh trong `/process`: intent
`ocr` + kính có `ocr-stream/1` → tạo phiên, trả câu mở đầu + header
`X-Next-Action`. Cổng `image_quality.reject_reason` không áp cho nhánh này (ảnh
ban đầu không còn được dùng để đọc).

### `frame_metrics` — đo gì trên mỗi frame preview

Chạy PP-OCRv6 **det tiny** trên frame 640×480. Mọi chỉ số "px" quy về pixel ảnh
capture bằng `scale = capture_w / preview_w` (OV2640: 1600/640 = 2,5).

| Chỉ số | Cách tính | Dùng cho |
|---|---|---|
| `n_boxes` | số box chữ | có chữ hay không |
| `prob_mass` | tổng xác suất bản đồ det khi không thành box | chữ quá nhỏ để thành box ở 640 → `maybe_small_text` |
| `line_px` | trung vị chiều cao box × `scale` | khoảng cách (`closer` / `farther`) |
| `clipped` | tập cạnh {trái, phải, trên, dưới} có box chạm trong lề `OCR_EDGE_MARGIN` | cắt mép → hướng nhìn |
| `center_offset` | tâm hợp các box so với tâm ảnh | lệch tâm (chỉ khi không có cạnh bị cắt) |
| `perspective` | tỉ lệ chiều cao box lớn nhất / nhỏ nhất trên cùng một hàng | nghiêng nặng → `face_flat` |
| `glare` | tỉ lệ pixel ≥250 trong hợp các box | `glare` |
| `brightness` | độ sáng trung bình trong hợp các box | `too_dark` |
| `sharp_rel` | Laplacian variance trong box / max của phiên | mờ do động hoặc quá gần |
| `motion` | dịch chuyển tâm box giữa 2 frame liền nhau | ổn định → được chụp |

Góc xoay của dòng chữ được đo nhưng **không** sinh hướng dẫn — reader tự xoay.

### `guidance` — chính sách

Mỗi frame chỉ ra *một* vấn đề, theo thứ tự ưu tiên (cái trên chặn cái dưới):

1. Không có chữ: `n_boxes == 0` → `maybe_small_text` nếu `prob_mass` đủ lớn, ngược lại `no_text`.
2. `too_dark`, `glare`.
3. Khoảng cách: `line_px < OCR_MIN_LINE_PX` → `closer`; `line_px > OCR_MAX_LINE_PX` hoặc (`sharp_rel` tụt trong khi `line_px` tăng) → `farther`.
4. Cắt mép → hướng nhìn về phía cạnh bị cắt. Cắt cả hai cạnh đối diện → `farther`.
5. `face_flat`.
6. Mọi thứ đạt nhưng `motion` lớn → `hold_still`.
7. Đạt và ổn định `OCR_STABLE_FRAMES` frame liên tiếp → `capture`.

Chống nhảy lệnh:

- Một vấn đề phải lặp lại `OCR_GUIDE_CONFIRM_FRAMES` frame mới được nói.
- Giữa hai câu cách nhau ít nhất `OCR_GUIDE_MIN_GAP_SECONDS` (≥ độ dài clip).
- Cùng một câu không lặp trong `OCR_GUIDE_REPEAT_SECONDS` trừ khi vấn đề vẫn còn.
- Lần đầu thấy chữ trong phiên → tone `text_found` (người dùng biết mình đang đúng hướng).

Giới hạn phần cứng: nếu `closer` đã nói `OCR_TOO_SMALL_AFTER` lần mà `line_px`
không còn tăng (người dùng đã sát hết mức, hoặc lens hết nét) → nói
`too_small_limit` rồi chụp luôn. Hết `OCR_SESSION_MAX_SECONDS` → `timeout` rồi
chụp frame tốt nhất có được. Không bao giờ kết thúc phiên mà không đọc gì.

### `reader` — đọc ảnh full-res

1. Nhận burst 3 frame UXGA; chọn frame có Laplacian trong vùng chữ cao nhất
   (vùng chữ lấy từ box preview cuối, nhân `scale`).
2. Phân loại hướng tài liệu 0/90/180/270 → xoay. Nắn phẳng (unwarp) chỉ khi
   phát hiện được tứ giác trang giấy.
3. PP-OCRv6 **medium** det + rec trên ảnh đã xoay, kèm phân loại hướng dòng.
4. Thứ tự đọc: gom cột theo toạ độ x, trong cột đọc trên xuống. Bố cục phức tạp
   (bảng, hoá đơn nhiều cột) để Gemma sắp lại ở bước tác vụ.
5. Kết quả `OcrResult`: danh sách dòng `{text, box, conf}` + `line_px` thực đo.
6. Nếu tỉ lệ dòng có `conf < OCR_LINE_MIN_CONF` quá `OCR_RETRY_LOW_CONF_RATIO`
   và phiên còn lượt thử (`OCR_MAX_RETRIES`, mặc định 1) → `resume` vòng hướng
   dẫn kèm câu lý do; hết lượt → đọc những gì có, báo phần không chắc.

### `tasks` — tác vụ phức tạp

**Chọn tác vụ**, theo thứ tự: (1) câu lệnh người dùng từ STT ("đọc hoá đơn",
"thuốc này uống sao", "hạn sử dụng"), (2) từ khoá trong text OCR ("HÓA ĐƠN",
"TỔNG CỘNG", "CĂN CƯỚC", "HSD", "NSX", "mg", "viên"), (3) không rõ → `plain`.
Không gọi model chỉ để phân loại.

| Tác vụ | Đầu ra cho người dùng |
|---|---|
| `plain` | 3 mode hiện có: NORMAL (dịch), SPECIALIZED (giữ thuật ngữ), RAW (nguyên văn) |
| `receipt` | cửa hàng, ngày, tổng tiền, (hỏi thêm mới đọc từng món) |
| `medicine` | tên thuốc, hàm lượng, liều/cách dùng, cảnh báo |
| `expiry` | NSX, HSD, còn bao nhiêu ngày (so với ngày server) |
| `id_card` | họ tên, ngày sinh, số giấy tờ |
| `menu` | danh sách món + giá, đọc theo nhóm |

**RAW không gọi Gemma**: text OCR đi thẳng vào TTS, nhanh nhất có thể.

Các tác vụ khác gọi Gemma 4 26B-A4B một lần với:

- ảnh full-res đã xoay (resize vừa ngân sách token ảnh của endpoint),
- danh sách dòng OCR dạng JSON `{text, box, conf}`,
- câu lệnh gốc của người dùng,
- JSON schema của tác vụ.

Prompt quy định: text OCR là nguồn chính, ảnh chỉ để kiểm tra và sắp thứ tự;
trường không chắc thì `null`; không tự suy ra con số.

**`verify.py` — chặn số bịa.** Mọi trường số (tiền, liều, ngày, số giấy tờ)
trong JSON phải xuất hiện trong text OCR sau khi chuẩn hoá (bỏ dấu chấm phân
cách nghìn, `đ`/`VNĐ`, khoảng trắng, nhầm `O`/`0` và `l`/`1`). Không khớp →
trường đó đọc thành "không đọc chắc được". Đây là lớp bảo vệ cho anti-goal số
2, không phụ thuộc vào việc Gemma có nghe lời prompt hay không.

JSON → câu tiếng Việt bằng formatter cố định trong code (đọc số tiền, ngày
tháng đúng kiểu nói), không nhờ model viết câu.

**Hỏi tiếp.** Giữ `OcrResult` + JSON của lượt gần nhất trong
`OCR_FOLLOWUP_TTL_SECONDS`; intent `chat` trong khoảng đó được đưa kèm làm ngữ
cảnh ("ngày hết hạn là bao giờ?" không phải chụp lại).

**Riêng tư.** Tác vụ `id_card` và `medicine` không ghi ảnh/text vào
`STORAGE_DIR` (bỏ qua `_save_debug_image`).

### Model và nơi chạy

| Thành phần | Model | Chạy ở đâu |
|---|---|---|
| Det preview | PP-OCRv6 tiny | GPU local (1× 2080 Ti) |
| Det + rec final | PP-OCRv6 medium | cùng GPU |
| Hướng tài liệu / hướng dòng / nắn | bộ phân loại + UVDoc đi kèm PaddleOCR 3.x | cùng GPU |
| Tác vụ | Gemma 4 26B-A4B | endpoint có sẵn: LAN `192.168.20.150:8899` (chính), UIT (dự phòng) — `docs/LLM_PROVIDER.md` |

Rec tiếng Việt của PP-OCRv6 **chưa được kiểm chứng** (hãng nói phủ 50 ngôn
ngữ, số liệu là benchmark nội bộ). Nếu thua trên bộ test, thay riêng bước rec
bằng VietOCR trên crop dòng; det vẫn dùng PP-OCRv6. Quyết định bằng số đo ở P1,
không quyết định trước.

Giữ Gemini làm nhánh so sánh qua `OCR_LLM_PROVIDER=gemma|gemini` cho tới khi
bộ test cho thấy Gemma không kém hơn.

## Firmware ESP32-S3 (hợp đồng, không phải code)

- Arduino: board "ESP32S3 Dev Module", PSRAM **OPI**, flash 16MB; IDF:
  `CONFIG_SPIRAM_MODE_OCT=y`. GPIO 35–37 bị PSRAM chiếm.
- `esp_camera_init` với `FRAMESIZE_UXGA` (buffer cấp phát theo size lúc init),
  `fb_location=PSRAM`, `fb_count=2`, `grab_mode=CAMERA_GRAB_LATEST`; ngay sau
  đó `set_framesize(VGA)` cho preview.
- Preview: VGA, `jpeg_quality` ~12–15 (số nhỏ = đẹp hơn), chỉ gửi khi có credit.
- Capture: `set_framesize(UXGA)` → bỏ 2 frame → gửi `burst` frame
  (`jpeg_quality` ~10) → `set_framesize(VGA)`; phát tone `shutter` ngay khi nhận
  lệnh, không chờ gửi xong.
- Chỉ bật camera stream trong phiên OCR (nhiệt, pin, tranh băng thông PSRAM với
  I2S audio).
- Clip hướng dẫn trong LittleFS theo `manifest.json`.

## Cấu hình mới (`config.py`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `OCR_STREAM_ENABLED` | `1` | tắt để quay về luồng một lượt |
| `OCR_PREVIEW_WIDTH` / `OCR_CAPTURE_WIDTH` | `640` / `1600` | suy ra `scale` |
| `OCR_MIN_LINE_PX` | `28` | chiều cao dòng tối thiểu trên ảnh capture — **hiệu chuẩn lại** |
| `OCR_MAX_LINE_PX` | `120` | quá to → ra xa |
| `OCR_EDGE_MARGIN` | `0.02` | lề tính là "chạm mép" (tỉ lệ cạnh ảnh) |
| `OCR_STABLE_FRAMES` | `3` | frame ổn định liên tiếp trước khi chụp |
| `OCR_GUIDE_CONFIRM_FRAMES` | `3` | vấn đề phải lặp lại bao nhiêu frame mới nói |
| `OCR_GUIDE_MIN_GAP_SECONDS` | `1.5` | khoảng cách tối thiểu giữa 2 câu |
| `OCR_GUIDE_REPEAT_SECONDS` | `4.0` | không lặp cùng câu trong khoảng này |
| `OCR_TOO_SMALL_AFTER` | `3` | số lần `closer` không tiến triển trước khi bỏ cuộc |
| `OCR_SESSION_MAX_SECONDS` | `30` | trần thời gian một phiên |
| `OCR_LINE_MIN_CONF` / `OCR_RETRY_LOW_CONF_RATIO` / `OCR_MAX_RETRIES` | `0.8` / `0.5` / `1` | quyết định chụp lại |
| `OCR_FOLLOWUP_TTL_SECONDS` | `300` | giữ kết quả cho câu hỏi tiếp |
| `OCR_LLM_PROVIDER` | `gemma` | `gemma` \| `gemini` |

Mọi số mặc định trên là điểm xuất phát, không phải số đo. Mỗi số được chốt phải
kèm comment đo trên dữ liệu gì, theo đúng lối `config.py` đang làm.

## Hiệu chuẩn

1. **px/mm thật của lens.** Thước kẻ ở giữa khung, cách kính 10/15/20/30cm, chụp
   UXGA, đếm pixel trên 10mm. Lặp lại ở góc ảnh để thấy méo thùng. Kết quả
   thay bảng ước lượng ở đầu tài liệu.
2. **Khoảng lấy nét gần nhất.** Tờ chữ 10pt ở các khoảng trên, kính đặt trên
   giá cố định; xem từ khoảng nào chữ bắt đầu nhoè. Đây là trần của `closer`.
3. **`OCR_MIN_LINE_PX`.** Từ bộ test (dưới), vẽ CER có dấu theo `line_px`; lấy
   điểm CER bắt đầu tăng vọt.

## Đánh giá

Bộ test mới `data/ocr_eval/`: 60–100 ảnh UXGA chụp bằng chính kính, chia theo
tác vụ (văn bản thường, hoá đơn, hộp thuốc, HSD trên bao bì, biển hiệu, tiền,
CCCD mẫu/không phải giấy thật), mỗi ảnh có text chuẩn gõ tay và — với tác vụ
có cấu trúc — JSON chuẩn.

| Chỉ số | Đo cái gì |
|---|---|
| CER có dấu | độ chính xác tổng |
| CER bỏ dấu | tách riêng lỗi dấu khỏi lỗi chữ |
| Độ đúng từng trường | tổng tiền, HSD, liều… — đúng / sai / `null` |
| Tỉ lệ số bịa | trường số sai mà không bị `verify.py` chặn — **mục tiêu 0** |
| Độ trễ | từ lúc chụp tới tiếng đầu tiên |

So 4 cấu hình trên cùng ảnh: (a) Gemini một lượt hiện tại — baseline;
(b) PP-OCRv6 + Gemma; (c) PP-OCRv6 det + VietOCR rec + Gemma; (d) Gemma đọc
thẳng ảnh. Câu hỏi so sánh là "câu nào cấu hình này đúng mà kia sai", không chỉ
trung bình CER.

Vòng hướng dẫn đo riêng ở P2: thời gian tới lúc chụp, số câu hướng dẫn mỗi
phiên, tỉ lệ phiên chụp được ảnh đạt `OCR_MIN_LINE_PX` — trước với người sáng
mắt bịt mắt, sau với người khiếm thị thật.

## Độ trễ dự kiến (chưa đo)

| Chặng | Ước lượng |
|---|---|
| 1 vòng preview (WiFi + decode + det tiny + chính sách) | ~50–100ms |
| Lệnh `capture` → có burst trên server | ~0,5–1s |
| reader (xoay + det/rec medium) | ~0,3–1s |
| Gemma tới token đầu | ~1–3s |
| RAW: text → tiếng đầu | như TTS hiện tại |

## Giai đoạn

| | Việc | Cần firmware? |
|---|---|---|
| P0 | Hiệu chuẩn + dựng bộ test + đo baseline Gemini | không (chỉ chụp ảnh) |
| P1 | `engine`, `reader`, `tasks`, `verify`, `models/llm` chạy offline trên bộ test; chọn rec | không |
| P2 | `ocr_session`, `frame_metrics`, `guidance` + `tools/ocr_stream_sim.py` (webcam laptop, resize về góc nhìn/độ phân giải của kính) để thử hướng dẫn | không |
| P3 | Firmware: WS, credit, chuyển size, clip LittleFS | có |
| P4 | Thêm tác vụ, hỏi tiếp, tinh chỉnh ngưỡng từ log thật | — |

P1 và P2 độc lập, làm song song được.

## Để người làm tự quyết

- PaddleOCR 3.x Python (đủ bộ xoay/nắn có sẵn) hay ONNX Runtime GPU (nhẹ phụ
  thuộc hơn, phải tự viết hậu xử lý DB/CTC). Đề xuất bắt đầu bằng PaddleOCR,
  chỉ chuyển khi đo thấy nặng.
- Định dạng header binary chính xác, tên field JSON.
- Câu chữ của từng clip — sau khi thử với người dùng.
- Thuật toán gom cột cho thứ tự đọc.
- Cách huỷ phiên nếu kính không có nút bấm (hiện tại: chỉ có timeout).
