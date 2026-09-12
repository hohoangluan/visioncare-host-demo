# Stream đầu-cuối: Gemini → TTS → MCU

Ngày: 2026-07-27

Tiếp nối [2026-07-27-tts-streaming-response-design.md](2026-07-27-tts-streaming-response-design.md),
vốn chỉ stream bước TTS.

## Vấn đề

Sau khi stream TTS, đo thật trên máy dev cho thấy người dùng vẫn phải chờ
41.8s mới nghe được tiếng đầu tiên. Phân rã:

| Bước | Giây |
| --- | --- |
| STT | 1.4 |
| PaddleOCR đọc chữ (CPU) | 28.0 |
| Gemini dịch | 4 – 12 |
| TTS tới mảnh PCM đầu | 0.2 |

Streaming TTS chỉ cắt được khoảng lặng ở cuối; phần chờ thật nằm ở hai chặng
trước nó.

## Hai thay đổi

### 1. Bỏ PaddleOCR, để Gemini đọc chữ luôn

PaddleOCR chạy CPU tốn 28.0s mỗi ảnh (đo lặp lại: 28.44s, 28.01s) — gần hết
thời gian chờ, chỉ để lấy text rồi lại gửi sang Gemini dịch. Gemini đọc được
chữ thẳng từ ảnh, nên gộp hai chặng thành một lượt gọi.

Kèm theo:
- Bỏ luôn `models/orientation.py` (chỉnh ảnh xoay bằng PaddleX). VLM hiểu ảnh
  nghiêng/ngược, prompt nói rõ điều đó.
- Bỏ warm-up OCR lúc khởi động (81.4s → 24.9s).
- Bỏ ràng buộc thứ tự import torch-trước-paddle trên Windows: import sai thứ
  tự làm paddle giành DLL search path, khiến `import torch` lỗi `shm.dll`.
- `config.OCR_LANG`, `config.OCR_MIN_SCORE`, `PADDLE_PDX_CACHE_HOME` không còn
  chỗ dùng.

Đánh đổi: OCR mất đường chạy offline, phụ thuộc hoàn toàn mạng và quota
Gemini. `RAW` mode trước đây miễn phí (chỉ chạy PaddleOCR) giờ cũng ăn quota,
nên ngân sách lệnh gọi Gemini của `tests/test_bang_am_thanh.py` lên 6.

Prompt dùng mốc quy ước `KHONG_CO_CHU` cho ảnh không có chữ đọc được — không
có mốc thì mỗi lần model chế một câu báo lỗi khác nhau, không tách được với
nội dung đọc được thật.

### 2. Gemini stream text, nối thẳng vào TTS

```
STT (xong hẳn)
  └─ Gemini stream text ──> gom thành câu ──> TTS stream PCM ──> MCU
```

Câu đầu đã thành tiếng trong lúc Gemini còn viết những câu sau.

Contract đổi theo suốt chuỗi:

| Thành phần | Trước | Sau |
| --- | --- | --- |
| `vlm` | `generate() -> str` | `generate_stream() -> Iterator[str]` |
| `models/ocr` | `read() -> str` | `read_stream() -> Iterator[str]` |
| 4 handler | `handle() -> Result` | `handle() -> Iterator[str]` |
| `router` | `resolve_speech() -> str` | `resolve_speech() -> Iterator[str]` |
| `tts` | — | thêm `synthesize_text_stream(Iterable[str]) -> Iterator[bytes]` |

`schemas.Result` (dataclass một trường) và `vlm.generate()` bản không streaming
không còn chỗ dùng nên bị gỡ.

## Gom mảnh text thành câu

Gemini trả mảnh nhỏ tuỳ ý, có khi cắt giữa từ. Đưa nửa câu vào TTS thì ngữ
điệu sai, nên `pipeline/tts._sentences()` gom tới ranh giới câu rồi mới tổng
hợp.

- Cắt ở `[.!?…]` **kèm khoảng trắng theo sau**, hoặc ở xuống dòng. Đòi hỏi
  khoảng trắng là để "50.000 đồng" không bị xẻ đôi — tiếng Việt dùng dấu chấm
  làm dấu phân cách hàng nghìn, cắt ở đó thì TTS đọc thành "năm mươi" rồi
  "không nghìn đồng".
- Text dài quá 200 ký tự mà chưa có dấu câu nào thì cắt ở khoảng trắng gần
  cuối nhất, nếu không câu đầu phải chờ tới lúc model viết xong. 200 nằm dưới
  ngưỡng chia chunk 256 ký tự của VieNeu nên không tạo thêm lần cắt bên trong
  model.
- Trả câu ngay khi đủ, không đọc hết nguồn trước.

## Giữ bảo đảm xử lý lỗi

Gemini chỉ thật sự gọi API khi có người kéo. Nếu endpoint trả
`StreamingResponse` rồi mới kéo, lỗi 503/quota nổ sau khi header 200 đã gửi —
MCU chỉ nhận được im lặng.

`app.process()` vì vậy kéo tới **mảnh PCM đầu tiên** bên trong `try/except`,
rồi mới trả `StreamingResponse` với `chain([mảnh đầu], phần còn lại)`. Không
tốn thêm giây nào (mảnh đó dù sao cũng phải chờ), mà mọi lỗi trên đường tới
byte audio đầu vẫn đổi được thành câu báo lỗi nghe được.

Kéo tới mảnh **text** đầu là chưa đủ — bản đầu của thiết kế này làm vậy và có
lỗ thật, quan sát được trên `storage/request120` (mất mạng do proxy SSL chen
giữa): text được gom tới ranh giới câu mới đưa sang TTS, nên đã nhận vài mảnh
text mà chưa sinh byte audio nào. Mạng rớt đúng khoảng đó thì `_stream_pcm`
nuốt exception, `collected` rỗng, MCU nhận HTTP 200 với **0 byte** và không có
`response{idx}.wav` nào được ghi để lần ra.

`_stream_pcm` vì vậy chỉ nuốt exception **sau khi** đã gửi byte đầu; trước đó
thì để lỗi nổi lên cho endpoint đổi thành câu báo lỗi.

Lỗi nổ giữa lúc đang stream thì vẫn không cứu được: byte đã rời server. Server
dừng stream, ghi log, người dùng nghe cụt câu.

## Đo log

`router` ghi `handler=` tính tới **mảnh text đầu tiên**, không phải tới lúc
Gemini viết xong — đó mới là thứ quyết định người dùng chờ bao lâu.

## Kết quả đo

Cùng ảnh, cùng câu lệnh, `gemini-3.1-flash-lite`:

| | PaddleOCR + Gemini | Gemini một lượt | Gemini streaming |
| --- | --- | --- | --- |
| `handler` | 32.4 – 40.2s | 6.3 – 8.5s | 2.7 – 4.9s |
| `ttfb` | 34.1 – 41.8s | 7.8 – 10.1s | 4.2 – 6.5s |
| warm-up | 81.4s | 24.9s | 25.0s |

Cột PaddleOCR đáng tin vì phần bỏ đi là 28s CPU cục bộ, đo lặp ổn định
(28.44s / 28.01s). Hai cột sau thì `handler` phụ thuộc mạng và tải phía
Google: cuối buổi đo cùng lệnh gọi đó ra 6.5 – 12.3s mà không đổi gì trong
code. Muốn so cấu hình thì phải đo lặp xen kẽ, đừng tin một lần chạy.

## Chống ngắt quãng phía người nghe

Streaming sớm nhất có thể không phải mục tiêu cuối — nghe liền mạch mới là.
Hai thứ đã làm:

**1. Gộp mảnh text ngắn (`_MIN_SENTENCE_CHARS = 24`).** Luật cắt-ở-dấu-chấm xẻ
đầu mục đánh số: "1. Ràng buộc bộ nhớ..." thành "1." và phần còn lại. TTS đọc
rời "một." rồi mới tới nội dung — nghe cụt ngay tại đó. Mỗi lệnh gọi TTS còn
mang chi phí cố định lớn. Đo trên đúng một câu trả lời OCR thật:

| | không gộp | có gộp |
| --- | --- | --- |
| số lệnh gọi TTS | 13 | 5 |
| tốc độ sinh | 0.68x thời gian thực | 2.51x |
| khoảng nghỉ dài nhất | 21.04s | 0.81s |

0.68x nghĩa là sinh chậm hơn phát — không đệm bao nhiêu cũng hụt, vì thiếu hụt
tích luỹ theo độ dài bài. Đây là gốc của ngắt quãng, không phải Gemini (đo
riêng thấy Gemini giao hết text trong một nhịp: `cho_gemini=0.00s` cho mọi câu
sau câu đầu).

**2. Đệm ở server (`config.AUDIO_PREROLL_SECONDS = 2.0`).** `_stream_pcm` gom
sẵn 2s audio rồi mới gửi byte đầu, nên server luôn đi trước người nghe: mỗi lần
MCU đọc socket là có dữ liệu. Đệm nằm ở RAM server thay vì RAM ESP32 (~320 KB).

| | ocr | space |
| --- | --- | --- |
| byte đầu về lúc | 7.16s | 4.80s |
| audio kèm sẵn trong byte đầu | 2.16s | 2.64s |
| khoảng nghỉ dài nhất sau đó | 0.91s | 0.81s |
| MCU cần đệm thêm | 0s | 0s |

Đệm dày hơn khoảng hụt nên phát từ byte đầu không đứt. Chi phí ~1.4s thêm vào
`ttfb` — rẻ vì TTS sinh nhanh gấp 2.5 lần, gom 2s audio chỉ mất ~0.8s.

Phụ lợi: lỗi nổ trong lúc còn đang gom đệm vẫn đổi được thành câu báo lỗi, vì
audio đang giữ chưa rời server. Không có đệm thì người dùng nghe một mẩu 0.006s
rồi im bặt.

Điều kiện không hụt, để tự tính lại khi đổi model hay phần cứng: tại mọi thời
điểm `t`, số giây audio đã nhận `a(t)` phải >= số giây đã phát. Suy ra mốc phát
sớm nhất an toàn là `t_start = max(t − a(t))`.

## Chưa làm

- **Độ dài câu trả lời**: cùng một ảnh, Gemini trả 37s tới 58s audio giữa các
  lần chạy. Người dùng phải nghe hết. Đây là chỗ đáng tấn công tiếp, bằng
  prompt hoặc `max_output_tokens`.
- **Tắt thinking**: đã đo, **không giúp gì**. 3 lần xen kẽ mỗi bên trên
  gemini-3.1-flash-lite: `thinking=0` median 9.03s (8.53–12.32), `thinking=1024`
  median 9.45s (6.53–9.81) — hai dải chồng nhau. Một lần đo đơn lẻ trước đó cho
  9.67s vs 1.87s và suýt dẫn tới kết luận sai; nhiễu ở bước này lớn hơn hiệu
  ứng, phải đo lặp xen kẽ. `config.GEMINI_THINKING_BUDGET` giữ lại làm nút
  chỉnh (mặc định -1 = không đụng tới mặc định của model).
- **TTS lên GPU**: hiện ép CPU (`pipeline/tts.py`). Sau khi bỏ Paddle thì GPU
  còn chỗ, nhưng TTS đang sinh nhanh gấp 2.7 lần tốc độ phát nên nhanh hơn
  cũng không đổi cảm nhận của người nghe.
