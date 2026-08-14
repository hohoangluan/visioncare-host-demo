# Blind-Assist Audio Server

Server hỗ trợ người khiếm thị: vi điều khiển gửi **ảnh + audio (WAV)**,
server chạy STT → nhận diện ý định → handler → TTS, rồi **stream về từng mảnh
MP3** tiếng Việt để thiết bị phát dần, không phải chờ tổng hợp xong cả câu.

## Cài đặt

```powershell
python -m pip install -r requirements.txt
```

Dùng venv riêng trên ổ D để không đụng tới ổ hệ thống (C) và tách khỏi Python
global:

```powershell
python -m venv D:\Study\innostar\Sever_test\.venv
D:\Study\innostar\Sever_test\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Chạy server bằng interpreter trong `.venv` (`D:\...\.venv\Scripts\python.exe -m uvicorn app:app`).
Cache model (HuggingFace) được `config.py` trỏ về `models/.cache/` trong
project (ổ D) thay vì thư mục người dùng mặc định (ổ C).

### Không cần GPU

STT và TTS **đều chạy CPU**: STT là Zipformer int8 34MB (0.03s/câu, xem
§Đo thời gian), TTS chạy backend ONNX của vieneu. Không bước nào trong pipeline
hiện tại đòi GPU, và `torch`/`transformers` đã bị bỏ khỏi `requirements.txt` —
chúng chỉ ở đó để chạy PhoWhisper, model STT cũ.

Trước đây đây là mục hướng dẫn cài bản CUDA của torch. Nếu bạn đã cài theo bản
README cũ, có thể gỡ để lấy lại chỗ trống:

```powershell
D:\Study\innostar\Sever_test\.venv\Scripts\python.exe -m pip uninstall torch torchaudio transformers
```

### Model STT

`pipeline/stt.py` dùng **Zipformer-vi 30M RNN-T int8** chạy qua `sherpa-onnx`.
Model không nằm trong repo (`models/` bị gitignore), tải về `models/stt/`:

```powershell
curl -L -o stt.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-vi-30M-int8-2026-02-09.tar.bz2
tar -xjf stt.tar.bz2
Move-Item sherpa-onnx-zipformer-vi-30M-int8-2026-02-09 models\stt
```

Thư mục phải có `encoder.int8.onnx`, `decoder.onnx`, `joiner.int8.onnx`,
`tokens.txt`. Đổi chỗ khác bằng `STT_MODEL_DIR`.

Model trả về **chữ hoa toàn bộ, không dấu câu**; `stt.transcribe()` hạ về dạng
câu thường trước khi trả ra. Đừng bỏ bước này: câu đó đi thẳng vào prompt phân
loại ý định, rồi các tham số trích ra từ nó (`song`, `contact_name`,
`destination`) được gửi tiếp sang host để tìm bài hát và tra danh bạ.

## Chạy server

```powershell
python -m uvicorn app:app --reload
```

Tài liệu API: <http://127.0.0.1:8000/docs>

## Chạy kiểm thử

```powershell
python -m pytest -v
```

## Endpoint

- `GET /health` → `{"status": "ok"}`
- `POST /process` (multipart: `image`, `audio`) → audio stream

`/process` luôn trả HTTP 200 kèm audio, kể cả khi thiếu field hoặc xử lý gặp
lỗi. Câu báo lỗi được đọc thành audio để người khiếm thị nghe được, thay vì
thiết bị nhận một lỗi JSON không phát được.

### Định dạng audio trả về

Chọn bằng `config.RESPONSE_FORMAT` (biến môi trường `RESPONSE_FORMAT`).

**`mp3_stream` (mặc định)** — nén MP3 CBR 32kbps, mono, 16000 Hz, gửi theo HTTP
chunked, phát dần được. 1/8 dung lượng so với PCM trần — đỡ tải WiFi/MCU.
MCU cần decoder MP3 để giải nén trước khi đẩy I2S.

```
Content-Type: audio/mpeg
X-Audio-Encoding: mp3
X-Audio-Sample-Rate: 16000
X-Audio-Channels: 1
X-Audio-Byte-Rate: 4000
X-Audio-Preroll-Seconds: 2.0
X-Audio-Format: mp3;bitrate=32kbps;rate=16000;channels=1
```

**`pcm_stream`** — PCM 16-bit little-endian, mono, 16000 Hz, không header, gửi
theo HTTP chunked. MCU đẩy thẳng vào I2S, không cần decoder, đổi lại tốn gấp 8
lần băng thông so với MP3.

```
Content-Type: application/octet-stream
X-Audio-Encoding: pcm_s16le
X-Audio-Sample-Rate: 16000
X-Audio-Bits: 16
X-Audio-Channels: 1
X-Audio-Byte-Rate: 32000
X-Audio-Preroll-Seconds: 2.0
X-Audio-Format: pcm_s16le;rate=16000;channels=1
```

**`wav`** — tổng hợp xong cả câu rồi gửi một file WAV hoàn chỉnh (PCM trần bọc
header), `Content-Type: audio/wav`, có `Content-Length`. Người dùng chờ lâu hơn
nhưng không phụ thuộc việc đường truyền có giữ đều tốc độ hay không.

Header mang đủ thông tin để MCU tự cấu hình I2S/decoder và tính buffer, không
hardcode: tách thành từng header số riêng thay vì bắt firmware parse chuỗi
ghép — trên MCU `atoi` một header là xong, tách chuỗi là thêm một chỗ để sai.
`X-Audio-Format` giữ lại cho người debug bằng curl.

`X-Audio-Byte-Rate` nhân trực tiếp ra kích thước buffer theo giây.
`X-Audio-Preroll-Seconds` là số giây audio **đã nằm sẵn trong mảnh đầu** — MCU
phát ngay khi nhận được mảnh đó, không phải chờ thêm.

**Chọn cái nào**: `pcm_stream` đòi đường truyền giữ đều **32 KB/s** (16 kHz ×
16-bit). Dưới mức đó thì nghe ngắt quãng dù server có đệm bao nhiêu đi nữa —
đo bằng `test.py`, nó in tốc độ tải thật. MCU qua HTTPS thường không đạt (TLS
tốn CPU), nên mặc định là `wav`.

`wav` chỉ thật sự hết ngắt nếu MCU **tải trọn file rồi mới phát**. Vừa tải vừa
đẩy I2S thì vẫn phụ thuộc băng thông y hệt, chỉ mất thêm thời gian chờ. File
35s audio nặng ~1.1 MB — không vừa RAM nội ESP32 (~320 KB), nên cần SD/PSRAM.

Cả Gemini lẫn TTS đều stream, nối thẳng vào nhau:

```
STT (xong hẳn)
  └─ Gemini stream text ──┐
                          ├─ gom thành câu ──┐
                          │                  ├─ TTS stream PCM ──> MCU
```

Câu đầu tiên đã thành tiếng trong lúc Gemini còn đang viết những câu sau.
Text được gom tới ranh giới câu (`.` `!` `?` xuống dòng) rồi mới đưa sang TTS —
đưa nửa câu vào thì ngữ điệu đọc sai. Hai luật quan trọng khi cắt:

- Dấu chấm chỉ tính là hết câu khi có **khoảng trắng theo sau**, để
  "50.000 đồng" không bị xẻ đôi.
- Mảnh ngắn hơn 24 ký tự được **gộp vào phần theo sau**, không đọc riêng.
  Không có luật này thì đầu mục đánh số bị xẻ: "1. Ràng buộc bộ nhớ..." thành
  "1." và phần còn lại, TTS đọc rời "một." rồi mới tới nội dung. Đo trên một
  câu trả lời OCR thật: bỏ luật gộp cho ra 13 lệnh gọi TTS chạy 0.68x thời
  gian thực (chậm hơn tốc độ phát, ngắt quãng chắc chắn); có luật gộp còn 5
  lệnh gọi, 2.51x. Mỗi lệnh gọi TTS mang chi phí cố định đáng kể.

Endpoint kéo tới **mảnh PCM đầu tiên** trước khi trả `StreamingResponse`. Mọi
thứ trên đường tới đó — gọi Gemini, mất mạng giữa luồng text, TTS lỗi — vẫn đổi
được thành câu báo lỗi nghe được.

Kéo tới mảnh *text* đầu là chưa đủ: text được gom tới ranh giới câu mới đưa
sang TTS, nên có thể đã nhận vài mảnh text mà chưa sinh byte audio nào. Nếu
mạng rớt đúng khoảng đó, MCU nhận HTTP 200 rỗng — người khiếm thị không nghe
gì và không biết vì sao.

Sau mảnh PCM đầu thì header 200 đã gửi, không rút lại được: server dừng stream
và ghi log, người dùng nghe cụt câu.

Muốn nghe bằng máy tính: dùng `test.py` (nó bọc PCM nhận được vào WAV rồi lưu
ra file), hoặc lấy `storage/response*.wav` mà server tự ghi lại để debug.

### Đo thời gian

Mỗi request ghi 2 dòng log để biết giây đi đâu:

```
nghe='đọc chữ trong ảnh giúp tôi.' intent=ocr | stt=1.27s handler=2.70s
request106 | xử lý=3.98s ttfb=4.15s tổng=25.34s audio=58.24s
```

| Trường | Nghĩa |
| --- | --- |
| `stt` | STT chạy cục bộ trên CPU — thường ~0.03s, không còn đáng kể |
| `handler` | Tới **mảnh text đầu tiên** của Gemini, không phải tới lúc viết xong |
| `xử lý` | Tổng phần trước TTS, tính từ lúc request vào |
| `ttfb` | **Lúc MCU nghe được tiếng đầu tiên** — con số người dùng cảm nhận |
| `tổng` | Lúc câu nói kết thúc |
| `audio` | Độ dài audio trả về |

`audio` lớn hơn `tổng - ttfb` nghĩa là TTS sinh nhanh hơn tốc độ phát, MCU
không bị hụt tiếng giữa chừng. Ngược lại thì phải đệm thêm trước khi phát.

#### STT: vì sao đổi khỏi PhoWhisper

Đo trên cùng 8 câu lệnh thật (~1.1–2.0s audio mỗi câu, 13.7s tổng), 5 lần mỗi
câu, cùng một máy:

| | PhoWhisper (cũ, **GPU**) | Zipformer-vi 30M int8 (mới, **CPU**) |
| --- | --- | --- |
| Nạp model lúc khởi động | 39.6s | **1.3s** |
| Nhận dạng, trung bình | 1.005s | **0.032s** |
| Nhận dạng, chậm nhất | 1.165s | **0.038s** |
| RTF (xử lý / độ dài audio) | 0.588 | **0.019** |
| Đúng nguyên văn | 7/8 | **8/8** |
| Dung lượng trên đĩa | ~1.5GB | ~34MB |

Model mới chạy CPU vẫn nhanh hơn model cũ chạy GPU **~31 lần**, và trả lại
toàn bộ GPU cho việc khác. Câu PhoWhisper nghe sai là "Mở bài hát Nơi này có
anh" → *"ngờ mà hát nơi này của anh"* — đúng loại lỗi tốn kém nhất, vì tên bài
hát được gửi thẳng sang host để tìm nhạc.

Hai điều con số này **không** nói:

- Audio đo là do TTS sinh ra nên sạch, không có tiếng ồn nền hay giọng vùng
  miền. Số tuyệt đối trên mic thật sẽ tệ hơn cho cả hai model.
- 39.6s nạp PhoWhisper là chi phí một lần lúc khởi động (`app.py` warm-up),
  không nằm trong thời gian chờ của từng request.

Đổi lại, RNN-T greedy không sinh dấu câu và trả về chữ hoa (xem §Model STT).

Khởi động server (`preload_models`) cũng ngắn theo, đo lại sau khi đổi:

```
import=1.2s  stt=1.8s  tts=15.1s  dựng sẵn câu nói=1.3s  ->  tổng 19.4s
```

Nút thắt khởi động giờ là TTS, không phải STT nữa.

### MCU nên đệm bao nhiêu trước khi phát

Điều kiện không ngắt quãng: tại mọi thời điểm `t`, số giây audio đã nhận `a(t)`
phải lớn hơn số giây đã phát. Suy ra mốc phát sớm nhất an toàn là
`t_start = max(t − a(t))`.

Đo thật, ghi mốc từng mảnh PCM đi ra khỏi `_stream_pcm`:

| | preroll=0, ocr | preroll=2, ocr | preroll=2, space |
| --- | --- | --- | --- |
| audio kèm sẵn trong mảnh đầu | 0.32s | **2.16s** | **2.56s** |
| khoảng nghỉ dài nhất sau đó | 0.71s | 0.81s | 0.72s |
| **MCU cần đệm thêm** | 0.87s | **0s** | **0s** |

Đệm dày hơn khoảng nghỉ (2.16s so với 0.81s) nên phát từ byte đầu không đứt.

### Biên cho mạng

Số trên đo trong máy, chưa qua WiFi. Phần đệm dư ra chính là biên chịu jitter:

```
biên chịu ngắt mạng = preroll − khoảng nghỉ lớn nhất
                    = 2.16s − 0.81s ≈ 1.35s
```

Mạng đứng hình dưới 1.35s thì người nghe không nhận ra. Muốn biên rộng hơn thì
tăng `AUDIO_PREROLL_SECONDS`; mỗi giây đệm thêm chỉ tốn ~0.4s chờ (TTS sinh
nhanh gấp ~2.5 lần).

**Nhưng đệm không cứu được thiếu băng thông.** Đường truyền phải giữ được
`X-Audio-Byte-Rate` = **32 KB/s** liên tục; dưới mức đó thì thiếu hụt tích luỹ
theo độ dài bài và không preroll nào đủ. `test.py` in tốc độ tải thật để kiểm.
Nếu link không đạt, hạ `OUTPUT_SAMPLE_RATE` xuống 8000 (16 KB/s, chất lượng
điện thoại, giọng nói vẫn rõ).

Server sinh nhanh gấp ~2.5 lần tốc độ phát nên không cần đệm vì lý do TTS.
Nhưng khoảng nghỉ tệ nhất vẫn là 0.81s, cộng jitter WiFi thì MCU phát ngay
byte đầu sẽ nghe cụt.

**Server tự lo phần đệm này** — MCU không phải làm gì thông minh. `_stream_pcm`
gom sẵn `AUDIO_PREROLL_SECONDS` (mặc định 2.0s) audio rồi mới gửi byte đầu, nên
server luôn đi trước người nghe một quãng: mỗi lần MCU đọc socket là có sẵn dữ
liệu. Đệm nằm ở RAM server (rẻ) thay vì RAM ESP32 (~320 KB, đắt).

Chi phí rất thấp vì TTS sinh nhanh gấp 2.5 lần: gom 2s audio chỉ mất ~0.8s.

MCU chỉ cần đọc socket rồi đẩy thẳng I2S. Buffer DMA vài KB là đủ; không cần
ring buffer lớn, không cần chờ trước khi phát.
Ví dụ trên: 58.24s audio sinh trong 21.19s — nhanh gấp 2.7 lần, dư sức phát.

Số đo thật trên máy dev (cùng ảnh screenshot chữ, `gemini-3.1-flash-lite`),
qua hai lần tối ưu:

| | PaddleOCR + Gemini | Gemini một lượt | Gemini streaming |
| --- | --- | --- | --- |
| `handler` | 32.4 – 40.2s | 6.3 – 8.5s | **2.7 – 4.9s** |
| `ttfb` | 34.1 – 41.8s | 7.8 – 10.1s | **4.2 – 6.5s** |
| warm-up lúc khởi động | 81.4s | 24.9s | 25.0s |

`tổng` không so được giữa các cột: độ dài câu trả lời của Gemini dao động
mạnh giữa các lần chạy (37s tới 58s audio cho cùng một ảnh), nên nó nói về
model chứ không nói về tốc độ server.

Chi tiết thiết kế:
[format PCM + stream TTS](docs/superpowers/specs/2026-07-27-tts-streaming-response-design.md),
[stream đầu-cuối Gemini→TTS](docs/superpowers/specs/2026-07-27-end-to-end-streaming-design.md)

## 5 chức năng

| Intent | Chức năng |
| --- | --- |
| `ocr` | Đọc chữ trong ảnh; mặc định dịch sang tiếng Việt, nói “nguyên văn” hoặc “chuyên ngành” để đọc thô |
| `find` | Tìm đồ vật và chỉ hướng |
| `money` | Đọc mệnh giá tiền, từ chối khi bằng chứng không vững (xem dưới) |
| `space` | Miêu tả không gian trước mặt |
| `chat` | Trò chuyện tự do với Gemini — fallback khi không khớp luật nào |

`chat` là nhánh **không có ảnh**: mọi câu hỏi thật sự cần ảnh đều đã có intent
riêng bắt trước, nên gửi kèm ảnh ở đây chỉ tốn thêm thời gian chờ và token mà
không đổi được câu trả lời. Đổi lại, câu lệnh không khớp luật nào không còn bị
trả về lời xin lỗi — hỏi giờ, hỏi thời tiết, tán gẫu đều trả lời được bình
thường (`handlers/chat.py`).

Hai thứ prompt phải tự lo, vì Gemini không tự có:

- **Giờ hiện tại** được nhét sẵn vào prompt mỗi lượt. Thiếu nó thì "mấy giờ
  rồi" nhận về một lời từ chối hoặc một con số bịa.
- **`CHAT_HISTORY_TURNS` lượt gần nhất** (mặc định 6) được nhắc lại, để "còn
  cái kia thì sao" vẫn hiểu được bối cảnh. Lịch sử nằm trong RAM tiến trình và
  tự xoá sau `CHAT_HISTORY_TTL_SECONDS` giây im lặng (mặc định 600) — quay lại
  sau vài giờ là một cuộc trò chuyện khác, kéo lượt cũ theo chỉ làm lạc đề.

Câu trả lời chat đi thẳng ra TTS nên prompt cấm markdown/emoji/gạch đầu dòng:
người nghe không nhìn màn hình, mọi ký hiệu chỉ có nghĩa khi đọc bằng mắt đều
thành rác khi đọc thành tiếng.

Chỉ khi STT không nghe ra chữ nào (im lặng, nhiễu) server mới trả
"Xin lỗi, tôi không nghe rõ, vui lòng nói lại." — lúc đó không có gì để chat
cũng không có gì để đoán.


## Phân loại ý định: cục bộ trước, Gemini sau

`pipeline/intent_local.py` chạy SetFit đã fine-tune (ONNX int8, CPU) **trước**
Gemini. Đủ chắc thì trả lời trong ~9ms; không chắc thì trả `None` và rơi xuống
Gemini như cũ. Dựng model: `python tools/train_intent_setfit.py`. Chưa có model
thì mọi câu đi đường Gemini, server vẫn chạy.

| | acc trên eval (236 câu) | tốc độ |
| --- | --- | --- |
| logreg trên embedding đông cứng | 93.6% | 8.8ms |
| **SetFit fine-tune, ONNX int8** | **94.5%** | **8.4ms** (p95 10.3ms) |
| Gemini `gemini-3.1-flash-lite` | — | 1.0–4.0s |

Fine-tune contrastive xoá luôn tổn thất lượng tử hoá: fp32 94.5% = int8 94.5%
(trước khi fine-tune, int8 mất 0.9 điểm).

**Hai ngưỡng, không phải một.** Xác suất cao vẫn có thể là "hai nhãn cùng cao".
Đo trên eval:

| conf / biên | nhận | đúng trong phần nhận | còn lại → Gemini |
| --- | --- | --- | --- |
| 0.50 / 0.15 | 98.3% | 94.8% | 1.7% |
| 0.70 / 0.35 | 95.8% | 96.0% | 4.2% |
| **0.80 / 0.50** | **93.2%** | **96.4%** | **6.8%** |
| 0.90 / 0.70 | 14.0% | 100% | 86.0% |

Chọn 0.80/0.50: nấc cuối trước cái vực giữa 0.80 và 0.90 (93.2% rơi thẳng
xuống 14.0%).

**Chỉ 8/16 nhãn dừng được ở bước cục bộ** — những nhãn không cần tham số
(`ocr` `find` `money` `space` `hazard` `nav_stop` `music_stop` `unknown`).
SetFit chỉ sinh nhãn, không trích slot, nên `nav_start` (destination),
`contact_call` (contact_name), `music_play` (song), `chat` (needs_location /
needs_web)... vẫn phải qua Gemini.

Đó lại đúng chỗ đáng cắt nhất: 5 nhãn ảnh nằm hết ở nhóm không cần tham số, mà
handler của chúng vốn đã gọi Gemini kèm ảnh — lượt gọi phân loại trước đó là
chờ trắng chỉ để lấy một cái nhãn. Đo E2E trên 8 lệnh thật: 4 câu xong ở 9–10ms,
4 câu còn lại 1.0–4.0s.


## Bối cảnh thiết bị khi phân loại ý định

"Tắt đi", "dừng lại", "thôi đủ rồi" **không tự nó cho biết tắt cái gì**. Đo trên
bộ câu huấn luyện, `nav_stop` ↔ `music_stop` là cặp lẫn nhau nhiều nhất — và
thêm dữ liệu không chữa được, vì chính người nghe cũng chịu nếu không biết cái
gì đang chạy.

`handlers/action_flow.py` theo dõi việc đang chạy trên điện thoại (`_ACTIVE`,
chỉ ghi khi host báo `succeeded`) và `device_state()` đưa nó vào prompt phân
loại. Đo thật, 25/25 ô đúng:

| Đang chạy | "tắt đi" | "dừng lại" | "thôi đủ rồi" | "tắt nhạc" | "dừng chỉ đường" |
| --- | --- | --- | --- | --- | --- |
| (không có gì) | `unknown` | `unknown` | `unknown` | `music_stop` | `nav_stop` |
| nhạc | `music_stop` | `music_stop` | `music_stop` | `music_stop` | `nav_stop` |
| chỉ đường | `nav_stop` | `nav_stop` | `nav_stop` | `music_stop` | `nav_stop` |
| cả hai, nhạc bật sau | `music_stop` | `music_stop` | `music_stop` | `music_stop` | `nav_stop` |
| cả hai, nav bật sau | `nav_stop` | `nav_stop` | `nav_stop` | `music_stop` | `nav_stop` |

Ba tính chất cần giữ khi sửa prompt:

- **Câu nói rõ thì bối cảnh không được lấn.** "Tắt nhạc" ra `music_stop` kể cả
  khi chỉ có chỉ đường đang chạy — người dùng nói gì thì làm nấy.

  Ở đường cục bộ, luật này phải xét bằng **mặt chữ**, không bằng độ tự tin của
  model. Đo thật: "tắt đi" ra `nav_stop` với conf 0.848 / biên 0.829 — tự tin
  ngang "dừng chỉ đường" (0.870/0.860), dù câu trước hoàn toàn mơ hồ (dữ liệu
  huấn luyện lỡ gán bừa nó về một bên). Hai ngưỡng không cứu được; chỉ có danh
  sách từ khoá `_MUSIC_WORDS`/`_NAV_WORDS` trong `intent.py` mới cứu được. Bỏ nó
  đi là "tắt nhạc" lúc đang chỉ đường quay lại ra `nav_stop` — bug đã đo được ở
  lần chạy E2E đầu tiên.
- **Không cái nào chạy thì không đoán.** Ra `unknown` để hỏi lại, thay vì gửi
  một lệnh dừng vu vơ.
- **Cả hai cùng chạy thì lấy cái vừa bật gần nhất.** Vì vậy `_ACTIVE` lưu mốc
  thời gian chứ không phải cờ bật/tắt.

Chỗ hở đã biết: host không báo khi bài hát tự hết, nên `music_playing` còn bật
sau khi nhạc đã tắt. Hậu quả nhẹ và không đối xứng — xem comment trong
`action_flow.py`.


## Bối cảnh

Người dùng cuối là người khiếm thị (bẩm sinh hoặc sau tai nạn) — không thấy
được, hoàn toàn phụ thuộc vào audio trả về từ thiết bị. Vì vậy mọi output của
4 handler đều phải là câu nói tự nhiên, dễ hiểu qua tai nghe, không phải mô tả
kiểu thị giác cho người sáng mắt:

- `ocr`: đọc chữ trong ảnh thành lời — mặc định dịch sang tiếng Việt.
- `find`: tìm đồ vật và **nói ra hướng** để người dùng tự định vị bằng tay/di
  chuyển tới đồ vật, không phải liệt kê những gì nhìn thấy.
- `money`: đọc mệnh giá tiền cầm trên tay. **Thà từ chối còn hơn đọc sai** —
  người dùng tiêu tiền thật, sai một chữ số là thiệt hại thật. Model chỉ được
  giao việc khai bằng chứng (chữ số đọc được, màu chủ đạo); quyết định nói hay
  từ chối do `handlers/read_money.py` làm, không nhờ prompt.

  Model khai **từng manh mối rời**, Python ghép lại. Đòi đọc trọn dãy số thì
  hỏng ở ảnh mờ; đòi từng manh mối thì mỗi cái dễ hơn nhiều mà ghép lại vẫn
  xác định:

  | Manh mối | Tách được gì |
  | --- | --- |
  | màu chủ đạo | về một họ — xanh: 5k/20k/500k, nâu: 2k/10k/200k |
  | chữ số đầu | trong họ — xanh + `2` chỉ có thể là 20k |
  | cửa sổ trong suốt | phần còn lại — 500k polymer có, 5k giấy cotton không |

  Ba manh mối giao nhau ra đúng một tờ trong mọi trường hợp. Còn nhiều hơn một
  ứng viên thì tờ đó bị xếp vào "chưa đọc được", không đoán.

  **Xét từng tờ, không bỏ cả nắm.** Đọc chắc tờ nào thì nói tờ đó, số còn lại
  thú nhận: *"Đọc được một tờ 50 nghìn đồng. Còn 2 tờ nữa tôi không đọc được,
  vui lòng chụp lại rõ hơn."* Im hẳn chỉ khiến người dùng chụp đi chụp lại mà
  không nhận thêm thông tin. Khi còn tờ chưa đọc được thì câu **không** mở
  bằng "Đây là tờ..." — người nghe bắt được mỗi vế đầu sẽ tưởng đó là tất cả
  số tiền đang cầm. Không tờ nào chắc thì mới từ chối hẳn.

  Manh mối chỏi nhau nghĩa là model đang bịa. Đo thật trên ảnh ngược sáng:
  model khai `so="10000"` nhưng `mau="xanh_la"` — xanh lá chỉ có 100k, nên
  giao lại rỗng và bị từ chối cả 3 lần chạy. Nhiều khả năng đó là tờ 100k bị
  đọc sót một số 0; không có luật này thì server đã nói "10 nghìn" và người
  dùng đưa nhầm tờ gấp 10 lần.
- `space`: miêu tả không gian phía trước — dùng để người dùng hình dung
  đường đi, vật cản.
- `chat`: trò chuyện tự do, không kèm ảnh — fallback khi không khớp intent nào.

Mọi thiết kế response (text lẫn giọng đọc) phải ưu tiên: ngắn gọn, định hướng
hành động (đi đâu, cầm gì, tránh gì), không giả định người nghe nhìn được bất
cứ thứ gì trong ảnh.
## Trạng thái hiện tại

| Bước | Chạy bằng |
| --- | --- |
| STT | Zipformer-vi 30M RNN-T int8 cục bộ (`pipeline/stt.py`), sherpa-onnx/CPU |
| Nhận diện intent | SetFit ONNX int8 cục bộ (`pipeline/intent_local.py`) → Gemini khi không chắc |
| Cả 5 handler | Gemini streaming, một lượt gọi (ảnh, trừ `chat`) → luồng mảnh text |
| TTS | VieNeu-TTS v3 Turbo cục bộ, ONNX/CPU (`pipeline/tts.py`) |

Handler trả `Iterator[str]` chứ không phải chuỗi hoàn chỉnh — đó là điều kiện
để `app.py` bắt đầu đọc câu đầu trong lúc Gemini còn đang viết. Vì vậy không
còn `schemas.Result` (dataclass một trường bọc chuỗi) và cũng không còn
`vlm.generate()` bản không streaming.

**Không còn model thị giác nào chạy cục bộ.** OCR trước đây dùng PaddleOCR
(đọc chữ) rồi mới đưa text sang Gemini dịch. Trên CPU, riêng bước PaddleOCR
tốn ~28s mỗi ảnh — chiếm gần hết thời gian chờ của người dùng. Giờ Gemini làm
cả đọc lẫn dịch trong một lượt gọi, và tự xử lý ảnh chụp nghiêng/ngược nên
bước chỉnh hướng cũng bỏ được.

Đổi lại: OCR phụ thuộc hoàn toàn vào mạng và quota Gemini, không còn đường
chạy offline. Muốn quay lại PaddleOCR thì lấy `models/ocr/engine.py` và
`models/orientation.py` từ lịch sử Git, cài lại `paddleocr`/`paddlepaddle`.

## Ngoài phạm vi

Các chức năng điện thoại (gọi, nhắn tin, push tới ứng dụng di động) và hỏi ngày
giờ đã được gỡ khỏi phạm vi hiện tại. Code cũ vẫn còn trong lịch sử Git.
