# Hợp đồng giữa board và server

Cập nhật **2026-08-23**, đối chiếu trực tiếp `app.py` / `pipeline/adpcm.py` (repo
này) với `AGENTS.md` §2.3/§6 và `CLAUDE.md` §6 của
`D:\Study\innostar\your-eyes-esp32-firmware` (commit `61f81e7`, nhánh
`net-stream-adpcm`). Bản trước của file này mô tả một hợp đồng đã lỗi thời
(một endpoint `/process` gộp ảnh+tiếng, `record.wav` gửi WAV sẵn, ảnh UXGA
q10) — KHÔNG còn đúng, đã thay bằng bản dưới.

🔴 **Hạn chế phần cứng — đọc trước khi "sửa lại cho khớp":** board vật lý
hiện KHÔNG nạp lại được firmware mới (không có quyền truy cập COM8 lúc viết
tài liệu này). `AGENTS.md §2.7` của firmware ghi rõ **"T17 chưa đo trên board
thật"** — tức bản tách kênh `/frame` dưới đây đã có trong mã nguồn firmware
nhưng chưa chắc đã là bản đang chạy thật trên kính. Vì không nạp lại được để
kiểm chứng, server **cố tình giữ cả hai đường** thay vì chọn một:

- Endpoint `/process` vẫn nhận field `image` gộp chung multipart (đời
  firmware cũ hơn `/frame`) — xem `router._resolve()`,
  `tests/test_frame_buffer.py::test_legacy_multipart_image_bypasses_frame_buffer`.
- Thiếu header `X-Device-Id` **không** bị chặn — rơi về
  `config.VISIONCARE_DEVICE_ID` (`app.py:_resolve_device_turn`), chỉ log
  warning. Thiếu `X-Turn-Id` cũng không bị chặn, chỉ mất idempotency/barge-in.
- `Accept` quyết định định dạng trả về (`app.py:_negotiate`) thay vì server tự
  đoán theo "đời firmware" — firmware cũ và mới gọi cùng một endpoint vẫn ra
  đúng định dạng của nó.

Nói cách khác: **đừng xoá nhánh tương thích ngược nào dưới đây chỉ vì thấy nó
"thừa"** — nó thừa cho đến khi biết chắc board đã được nạp bản mới, và hiện
không có cách xác nhận việc đó (không có board vật lý trong tay).

---

## 1. Board gửi lên cái gì

**Hai request độc lập, cùng cặp header `X-Device-Id` + `X-Turn-Id`:**

```
POST /frame HTTP/1.1
Host: api.visioncare-host.uk
Content-Type: image/jpeg
Content-Length: <số byte JPEG>
X-Device-Id: <id board>
X-Turn-Id: <uuid v4 của lượt>
X-Capture-Ts: <millis tương đối, KHÔNG phải epoch>
Connection: close

body: JPEG HD 1280×720 quality 18 (~60–70 KB), KHÔNG phải UXGA q10 như bản cũ
```

Board đóng socket ngay sau byte JPEG cuối, **không đợi 204**. `/frame` hỏng
không huỷ `/process`. Server lưu ảnh vào `services/frame_buffer.py:frames`
(ring 3 khung/`device_id`), khoá theo `(device_id, turn_id)` — xem `app.py`
`POST /frame`.

```
POST /process HTTP/1.1
Host: api.visioncare-host.uk
User-Agent: ESP32S3-VisionCare/1.0
Accept: audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav
Content-Type: multipart/form-data; boundary=----ESP32VisionCareBoundary7d91
Transfer-Encoding: chunked        <-- KHÔNG có Content-Length nữa
Connection: keep-alive
X-Device-Id: <id board>
X-Turn-Id: <uuid v4 của lượt — PHẢI trùng lượt gửi ở /frame>
```

Chỉ còn **một** field:

| Field | Filename | Content-Type | Nội dung |
|---|---|---|---|
| `audio` | `record.adpcm` | `audio/x-adpcm-ima; rate=16000; channels=1; block=256` | ADPCM 4-bit **THÔ, không header RIFF** |

`image` **không còn nằm trong multipart này** — bỏ hẳn, không phải đảo thứ
tự part. Router chỉ tự lấy ảnh từ `frames.latest(device_id, ...)` khi intent
thật sự cần ảnh (`pipeline/router.py:~828`); intent không cần ảnh (gọi điện,
kể chuyện...) thì không đụng tới `/frame` chút nào.

- Không `Expect: 100-continue` — board không gửi, server cũng không trả
  `100 Continue`.
- Board gom **4096 byte** mới ghi một miếng chunked (đo được: ảnh 31–108
  KB/s, tiếng 14–123 KB/s sau khi gom, so với 3.8–15.5 KB/s khi ghi từng
  khối 256 B).

### Định dạng thân field `audio`

Không còn là file WAV hoàn chỉnh — là các khối ADPCM thô nối liền nhau, mỗi
khối **256 byte** (`ADPCM_BLOCK_BYTES` trong `adpcm_codec.h` của firmware):

| Offset trong khối | Trường | Giá trị |
|---|---|---|
| 0–1 | `int16 LE` predictor khởi tạo | mẫu đầu tiên |
| 2 | `uint8` step index khởi tạo | 0–88 |
| 3 | dự trữ | `= 0` |
| 4.. | nibble ADPCM | nibble THẤP đi trước, 2 mẫu/byte |

Một khối 256 B chứa `1 + (256-4)*2 = 505` mẫu. Server dựng lại 60 byte header
WAV bằng `pipeline/adpcm.py:ensure_wav(data, content_type)` — đọc `rate=` và
`block=` từ `Content-Type` của chính field, cắt phần dư không tròn khối rồi
mới ghép header. **Vẫn nhận nguyên một file `.wav` đã có sẵn RIFF** (test
bằng `curl -F audio=@record.wav` hay firmware đời cũ hơn) — `ensure_wav` trả
nguyên xi khi thân đã bắt đầu bằng `RIFF`.

🔴 Đừng dùng `audioop.lin2adpcm()`/`adpcm2lin()` của Python — biến thể riêng,
không tương thích `fmt` tag `0x0011`, giải ra nhiễu trắng.

### Kích thước thực tế

| | Trước ADPCM | Sau ADPCM |
|---|---|---|
| Bản thu 10 giây @ 16 kHz | 320 044 B | **81 212 B** (25.4%) |

---

## 2. Board nhận về được cái gì

Không đổi so với bản trước — board vẫn nuốt được **bốn** định dạng, chọn
theo 4 byte đầu của thân (`bodySniff()` phía firmware), không tin
`x-audio-format`:

### A. WAV IMA ADPCM — nên dùng, board ưu tiên đường này

```
HTTP/1.1 200 OK
Content-Type: audio/wav
X-Audio-Format: adpcm_ima_wav
X-Audio-Sample-Rate: 16000
X-Audio-Block-Align: 256
```
Thân = WAV `fmt` tag **0x0011**, mono, 16000 Hz, `nBlockAlign` 256
(`app.py:_stream_headers`, nhánh `_ADPCM_FORMATS`). 60 byte header phải ra
TRƯỚC, đừng gom cả file rồi mới gửi — `data` size ghi `0xFFFFFFFF` lúc còn
đang stream.

### B. ADPCM thô (`x-audio-format: ima_adpcm;...`), C. MP3, D. WAV/PCM thô

Giữ nguyên như bản trước — chọn qua `Accept` (`app.py:_negotiate`), không
đổi. Board KHÔNG khai `codec=ima_adpcm` trong `Accept` (đời rất cũ) thì vẫn
nhận `adpcm_wav` theo mặc định của `_negotiate()`.

### Ràng buộc chung — không đổi

- **Mono, 16000 Hz.** Trả khác 16 kHz thì board đổi sample rate I2S hai lượt
  mỗi lần bấm nút.
- `Content-Length` **hoặc** `Transfer-Encoding: chunked` — board đọc cả hai
  qua `BodyReader` (`src/net/http_body_reader.h`).

---

## 3. Con số quyết định: tốc độ NHẢ, không phải kích thước

Không đổi — xem lại bản trước, vẫn đúng 100% với code hiện tại
(`audio_player.cpp` phía firmware không nằm trong đợt sửa T17/T22).

| Server nhả được | Board làm gì |
|---|---|
| ≥ **1.30×** thời gian thực | đệm 400 ms rồi phát |
| ≥ **1.12×** | đệm 1500 ms rồi phát |
| < 1.12×, biết tổng độ dài | tính điểm an toàn |
| < 1.12×, không biết độ dài | đợi nhận hết rồi mới phát |

🔴 Tỉ lệ giây-tiếng/giây-đồng-hồ, không phải băng thông mạng — nén không cải
thiện con số này, chỉ đường truyền/TLS mới ăn nhờ nén.

---

## 4. Đồng hồ — board bỏ cuộc lúc nào

Số liệu dưới đây đọc từ `app_config.h` hiện tại của firmware — **bản trước
của file này ghi 90 s/180 s là SAI**, đã lệch từ nhiều phiên trước:

| Mốc | Trần | Ở đâu (firmware) |
|---|---|---|
| Header phản hồi (`200 OK` + headers) | **60 giây** | `NET_TIMEOUT_MS` |
| Cloudflare tự ngắt (lỗi 524) | 100 giây | ngoài tầm cả hai bên |
| Từ lúc gửi xong → byte tiếng đầu tiên | **60 giây** | `FIRST_AUDIO_MS` |
| Khoảng im GIỮA CHỪNG khi đã có tiếng | 30 giây | `BODY_GAP_MS` |

🔴 Trả `200` + header NGAY rồi mới stream thân — trần 60 s ăn hết dư địa
nhanh nếu server đợi sinh xong tiếng mới trả.

🔴 **Bản trước nói "board không đòi miếng kết thúc `0\r\n\r\n`, dựa vào im
lặng 30 s" — SAI, đã đo lại (`docs/tasks/measurements/G10.md`, 2026-08-22):
miếng `0\r\n\r\n` tới **giống hệt nhau** ở localhost lẫn qua tunnel
Cloudflare.** `StreamingResponse` của FastAPI/uvicorn tự phát miếng đó khi
generator sinh audio kết thúc bình thường — không cần code thêm ở
`_stream_audio`. Nếu một bản firmware cũ hơn thật sự chỉ dựa vào khoảng im
30 giây thì nó vẫn đúng luôn (server không rút miếng kết thúc), chỉ là nó
chờ lâu hơn mức cần thiết.

---

## 5. Thử bằng curl — hai bước, không còn một request gộp

```bash
# Bước 1: đẩy ảnh (JPEG bất kỳ, giả lập /frame)
curl -v \
     -H "X-Device-Id: test-device" -H "X-Turn-Id: 11111111-1111-1111-1111-111111111111" \
     -H "Content-Type: image/jpeg" \
     --data-binary @capture.jpg \
     http://localhost:8000/frame

# Bước 2: gửi tiếng, cùng X-Turn-Id
curl -v -H "Expect:" \
     -H "X-Device-Id: test-device" -H "X-Turn-Id: 11111111-1111-1111-1111-111111111111" \
     -F "audio=@record.adpcm;type=audio/x-adpcm-ima; rate=16000; channels=1; block=256" \
     http://localhost:8000/process --output reply.bin
```

🔴 `-H "Expect:"` bắt buộc cho curl (tự thêm `Expect: 100-continue` cho thân
> 1 KB; server không trả `100 Continue`). Board không dính vì tự dựng
header, không đi qua libcurl.

Vẫn thử được đường CŨ (một request, ảnh gộp cùng tiếng, tiếng là WAV có sẵn)
để so — cả hai đường cùng chạy được trên cùng server:

```bash
curl -v -H "Expect:" \
     -F "image=@capture.jpg;type=image/jpeg" \
     -F "audio=@record.wav;type=audio/wav" \
     http://localhost:8000/process --output reply.bin
```

Kiểm tra file server trả:
```bash
ffprobe -v error -show_streams reply.bin | grep -E "codec_name|sample_rate|channels"
# mong doi: adpcm_ima_wav / 16000 / 1
```

---

## 6. Tóm tắt — ba việc server đã làm để khớp firmware T17/T01, không phá đường cũ

1. **Tách nhận ảnh:** `POST /frame` lưu vào `FrameBuffer`, `POST /process`
   chỉ còn field `audio`; router tự kéo ảnh từ buffer đúng lúc cần
   (`pipeline/router.py`). `image` gộp trong multipart cũ vẫn được đọc thẳng,
   không đụng buffer — hai đường cùng sống.
2. **Đọc `record.adpcm` thô** bằng `adpcm.ensure_wav()` thay vì đòi WAV sẵn;
   vẫn nhận nguyên WAV nếu thân đã có `RIFF`.
3. **Định danh qua header, không bắt buộc:** `X-Device-Id`/`X-Turn-Id` đọc từ
   header nếu có, thiếu thì cảnh báo chứ không từ chối — vì chưa xác nhận
   được board thật đang gửi header nào (xem hộp cảnh báo đầu file).

**Khi nào được phép dọn nhánh tương thích ngược:** chỉ sau khi nạp lại được
board thật và xác nhận nó đang chạy đúng bản HEAD hiện tại của firmware repo
— xem `AGENTS.md §2.7` (mục "T17 chưa đo trên board thật") bên
`your-eyes-esp32-firmware`. Nạp xong thì việc đầu tiên là xoá đoạn cảnh báo ở
đầu file này, không phải xoá code.
