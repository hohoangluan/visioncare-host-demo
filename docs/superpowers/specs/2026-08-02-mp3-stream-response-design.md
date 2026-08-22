# Stream MP3 thay PCM trần cho MCU

Ngày: 2026-08-02

## Vấn đề

`POST /process` hiện stream PCM trần 16-bit/16kHz mono (`RESPONSE_FORMAT=pcm_stream`,
mặc định) — 32 KB/s. MCU chạy qua WiFi, băng thông/tốc độ truyền là bottleneck
đang cần giảm. Nén sang MP3 32kbps giảm ~8 lần dung lượng phải gửi (4 KB/s).

## Phạm vi

Chỉ đổi bước encode trước khi trả response. Toàn bộ STT → intent → handler →
TTS PCM 16kHz (pipeline hiện có) giữ nguyên. Không đụng STT/VLM, không sửa
firmware MCU (MCU cần thêm decoder MP3, nằm ngoài phạm vi thay đổi server này).

Giữ lại `pcm_stream` và `wav` như giá trị `RESPONSE_FORMAT` cũ (không xoá) để
còn so sánh/rollback qua env var, nhưng đổi **default sang `mp3_stream`**.

## Quyết định thiết kế

| Hạng mục | Chọn | Lý do |
| --- | --- | --- |
| Codec | MP3 CBR 32kbps, mono, 16kHz | Theo yêu cầu; CBR giữ byte-rate cố định nên tính preroll đơn giản như PCM |
| Thư viện encode | `lameenc` | Wheel dựng sẵn Win/Linux/Mac, không cần cài ffmpeg, API streaming (`encode()` + `flush()`) |
| Điểm chèn encode | Sau `tts.synthesize_text_stream` (PCM), trước khi gom preroll | Không đụng logic sinh PCM/carry/downsample đã có |
| `Content-Type` | `audio/mpeg` | Chuẩn MIME cho MP3 |
| Preroll | Tính theo byte-rate MP3 (4000 B/s) thay vì byte-rate PCM (32000 B/s) | CBR nên byte-rate không đổi suốt stream — công thức đệm cũ (`_stream_pcm`) dùng lại được, chỉ đổi tham số |

## Luồng

```
MCU POST /process (image + audio)
   |  [chưa gửi byte nào]
   +- STT -> intent -> handler (OCR/Gemini) -> speech text
   +- tts.synthesize_text_stream(text) yield PCM 16kHz int16 (không đổi)
   +- tts.encode_mp3(pcm_stream) yield MP3 bytes (LAME CBR 32kbps)
   +- gom đủ AUDIO_PREROLL_SECONDS * 4000 byte rồi mới gửi mảnh đầu
   +- StreamingResponse (Content-Type: audio/mpeg) -> MCU
```

## `pipeline/tts.py`

```python
MP3_BITRATE_KBPS = 32
MP3_BYTE_RATE = MP3_BITRATE_KBPS * 1000 // 8  # 4000 B/s, CBR nên cố định

def encode_mp3(pcm_stream: Iterator[bytes]) -> Iterator[bytes]
```

`encode_mp3` tạo `lameenc.Encoder()` một lần cho cả request (`set_in_sample_rate(16000)`,
`set_channels(1)`, `set_bit_rate(32)` — CBR mặc định khi không gọi `set_vbr`). Với
mỗi PCM chunk vào: `encoder.encode(chunk)` trả mp3 bytes tích luỹ được (có thể
rỗng nếu chưa đủ 1 frame — bỏ qua chunk rỗng, không yield). Hết stream:
`encoder.flush()` yield nốt phần còn lại.

Không đổi `synthesize_stream`/`synthesize_text_stream` — `encode_mp3` là lớp bọc
thêm, nhận đúng iterator PCM mà hai hàm đó đã trả.

## `app.py`

- Đổi tên `_stream_pcm` thành `_stream_audio`, thêm 2 tham số: `encode: Callable[[Iterator[bytes]], Iterator[bytes]] | None = None`
  và `byte_rate: int` (mặc định byte-rate PCM hiện tại, `tts.OUTPUT_SAMPLE_RATE * 2`).
  Khi `encode` được truyền, bọc `tts.synthesize_text_stream(...)` qua nó trước
  khi vào vòng gom preroll; `preroll_bytes` tính từ `byte_rate` truyền vào thay
  vì hardcode PCM.
- `/process` chọn nhánh theo `config.RESPONSE_FORMAT`:
  - `mp3_stream` (mặc định mới): `encode=tts.encode_mp3`, `byte_rate=tts.MP3_BYTE_RATE`,
    `media_type="audio/mpeg"`.
  - `pcm_stream`: như cũ, không đổi.
  - `wav`: như cũ, không đổi (gom trọn PCM rồi bọc WAV — không áp dụng MP3).
- Headers cho `mp3_stream`: `X-Audio-Encoding: mp3`, `X-Audio-Format:
  mp3;bitrate=32kbps;rate=16000;channels=1`, `X-Audio-Byte-Rate: 4000`,
  `X-Audio-Preroll-Seconds` giữ nguyên. Bỏ `X-Audio-Bits` (không có ý nghĩa với
  dữ liệu nén).
- Debug save: khi ở mode nén, ghi thẳng bytes đã gom được ra `response{idx}.mp3`
  (không bọc WAV — LAME xuất frame MP3 hợp lệ độc lập, ghép nối được).

## Xử lý lỗi

Không đổi so với thiết kế PCM stream hiện có: lỗi trước byte đầu (kể cả lỗi
trong `encode_mp3`, ví dụ LAME init thất bại) vẫn nổi lên cho `/process` đổi
thành câu báo lỗi rồi stream lại từ đầu; lỗi giữa chừng thì dừng generator êm,
MCU nghe cụt câu thay vì treo.

## Kiểm thử

- `encode_mp3`: PCM giả (silence) -> bytes ra có frame sync MP3 (`0xFF` +
  3 bit set ở byte kế); nối hết các chunk (kể cả `flush()`) đọc lại được bằng
  chính `lameenc`/thư viện parser mà không lỗi.
- `encode_mp3` bỏ qua chunk rỗng: mock `encoder.encode()` trả `b""` một vài lần
  giữa các lần trả bytes thật -> stream không yield chunk rỗng.
- `/process` với `RESPONSE_FORMAT=mp3_stream` (default): `content-type ==
  "audio/mpeg"`, `X-Audio-Encoding == "mp3"`, `X-Audio-Byte-Rate == "4000"`,
  không còn header `X-Audio-Bits`.
- Preroll với mp3: mảnh đầu gửi về có độ dài byte >= `AUDIO_PREROLL_SECONDS *
  4000` (thay vì `* 32000` như PCM) khi encoder giả lập byte-rate không đổi.
- `pcm_stream`/`wav` mode: toàn bộ test hiện có (`test_app.py`,
  `test_tts.py`) phải xanh không đổi — không breaking hai path cũ.
- Lỗi giữa chừng ở `mp3_stream`: vẫn trả 200, không crash, dừng stream sau
  chunk cuối cùng gửi được.
