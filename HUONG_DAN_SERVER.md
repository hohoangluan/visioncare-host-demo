# Hợp đồng giữa board và server

Firmware sau khi chuyển sang ADPCM. Mọi con số dưới đây đọc thẳng từ mã nguồn — chỗ nào đo được thì ghi rõ là đo.

---

## 1. Board gửi lên cái gì

```
POST /process HTTP/1.1
Host: api.visioncare-host.uk
User-Agent: ESP32S3-VisionCare/1.0
Accept: audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav
Content-Type: multipart/form-data; boundary=----ESP32VisionCareBoundary7d91
Content-Length: <chính xác>
Connection: close
```

Hai phần:

| Field | Filename | Content-Type | Nội dung |
|---|---|---|---|
| `image` | `capture.jpg` | `image/jpeg` | JPEG UXGA 1600×1200, quality 10 (~250–400 KB) |
| `audio` | `record.wav` | `audio/wav` | **WAV IMA ADPCM 4-bit** — chi tiết dưới |

### Định dạng file `record.wav`

Header đúng **60 byte**, rồi tới dữ liệu nén:

| Offset | Trường | Giá trị |
|---|---|---|
| 0 | `RIFF` + size | |
| 8 | `WAVEfmt ` | |
| 16 | cỡ khối `fmt ` | **20** (không phải 16) |
| 20 | `wFormatTag` | **0x0011** — `WAVE_FORMAT_DVI_ADPCM` |
| 22 | `nChannels` | 1 |
| 24 | `nSamplesPerSec` | 16000 |
| 28 | `nAvgBytesPerSec` | 8110 |
| 32 | `nBlockAlign` | **256** |
| 34 | `wBitsPerSample` | 4 |
| 36 | `cbSize` | 2 |
| 38 | `wSamplesPerBlock` | **505** |
| 40 | khối `fact` | số mẫu THẬT |
| 52 | khối `data` + size | |

Đọc bằng:

```bash
ffmpeg -i record.wav -c:a pcm_s16le -f wav out.wav
```
```python
import soundfile as sf
pcm, sr = sf.read("record.wav", dtype="int16")   # sr = 16000
```

**Hai chỗ dễ vấp:**

- 🔴 **Đừng dùng `audioop.lin2adpcm()` / `adpcm2lin()` của Python.** Đó là biến thể riêng của Python: không có phần đầu 4 byte mỗi khối, không tương thích `fmt` tag 0x0011. Giải bằng nó ra nhiễu trắng.
- Khối cuối được đệm cho tròn 256 byte. Đã đo: **ffmpeg không cắt theo khối `fact`** — nó trả dư tới 504 mẫu (~31 ms) ở cuối. Phần đệm được chọn để gần như im lặng nên vô hại với ASR; muốn cắt chính xác thì đọc số mẫu trong khối `fact`.

### Kích thước thực tế

| | Trước | Nay |
|---|---|---|
| Bản thu 10 giây @ 16 kHz | 320 044 B | **81 212 B** (25.4%) |

---

## 2. Board nhận về được cái gì

Board nuốt được **bốn** định dạng. Xếp theo thứ tự nên dùng:

### A. WAV IMA ADPCM — nên dùng

```
HTTP/1.1 200 OK
Content-Type: audio/wav
```
Thân = WAV `fmt` tag **0x0011**, **mono**, **16000 Hz**, `nBlockAlign` 256.

```bash
ffmpeg -i tts.wav -ar 16000 -ac 1 -c:a adpcm_ima_wav -block_size 256 -f wav pipe:1
```

Board đọc header ngay trên luồng nên **60 byte đầu phải ra trước**, đừng giữ lại chờ gom cả file.

Khối `data` chưa biết dài bao nhiêu thì ghi size = `0` hoặc `0xFFFFFFFF` — board hiểu là "server định dạng dần" và tự chuyển sang phỏng đoán mức đệm.

### B. ADPCM thô — hợp streaming nhất

```
HTTP/1.1 200 OK
Content-Type: application/octet-stream
x-audio-format: ima_adpcm;rate=16000;channels=1;block=256
```
Thân = **chỉ các khối 256 byte**, không header RIFF, không `fact`. Không phải bịa ra độ dài, không tốn 60 byte đầu mỗi câu.

### C. MP3
```
Content-Type: audio/mpeg
```
Nén tốt hơn (32 kbps = 4 KB/s) nhưng server phải encode MP3 từng câu, khâu đó cộng thêm thời gian vào đúng chặng đang là chỗ lâu nhất. Chỉ dùng nếu đường truyền mới là nút thắt.

### D. WAV PCM 16-bit / PCM thô
Đường cũ, vẫn chạy. `x-audio-format: pcm_s16le;rate=16000;channels=1`.

### Ràng buộc chung cho mọi định dạng

- **Mono.** ADPCM stereo cài răng nibble theo kênh — board từ chối thẳng.
- **16000 Hz.** Mic thu 16 kHz. Server trả tần số khác thì mỗi lần bấm nút board phải đổi sample rate của I2S hai lượt (đổi sang tần số server, phát xong đổi về). Trả đúng 16 kHz thì bỏ được cả hai.
- `Content-Length` **hoặc** `Transfer-Encoding: chunked` — board xử lý cả hai.

---

## 3. Con số quyết định: tốc độ NHẢ, không phải kích thước

Đây là phần quan trọng nhất, và nó **không** phải chuyện codec.

Board đo tốc độ nguồn đẩy về rồi tự chọn mức đệm ([audio_player.cpp](src/audio/audio_player.cpp)). Nó so **số giây tiếng nhận được** với **số giây tiếng phát ra**:

| Server nhả được | Board làm gì | Người dùng nghe thấy |
|---|---|---|
| ≥ **1.30×** thời gian thực | đệm 400 ms rồi phát | tiếng ra gần như ngay |
| ≥ **1.12×** | đệm 1500 ms rồi phát | trễ 1.5 giây |
| < 1.12×, biết tổng độ dài | tính chính xác điểm an toàn | trễ vừa đủ |
| < 1.12×, **không** biết độ dài | **đợi nhận xong hết rồi mới phát** | trễ bằng cả thời gian sinh tiếng |

Ở 16 kHz mono, "thời gian thực" =

| Định dạng | 1.00× | 1.30× (ngưỡng để phát ngay) |
|---|---|---|
| ADPCM | 8.0 KB/s | **10.4 KB/s** |
| PCM 16-bit | 32 KB/s | 41.6 KB/s |

🔴 **Đây là tỉ lệ giây-tiếng trên giây-đồng-hồ, không phải băng thông mạng.** Server sinh 1 giây tiếng mất 1 giây thì tỉ lệ là 1.00× dù nén cỡ nào — nén 4 lần **không** cải thiện con số này. Nén chỉ ăn tiền khi nút thắt nằm ở đường truyền/TLS.

Đã đo trước đây: *"198 KB về trong 10 giây"* với WAV 48 kHz = **2.06 giây tiếng trong 10 giây đồng hồ ≈ 0.2×**. Nếu đó là giới hạn sinh tiếng của TTS thì ADPCM không gỡ được, phải sửa ở server. Nếu đó là giới hạn đường truyền thì ADPCM gỡ luôn.

**Chạy một lần rồi đọc dòng board in ra là biết ngay:**
```
Nguon 12.4 KB/s / can 32.0 KB/s = du 39%
```
Tử số là tốc độ server nhả (đã tính theo byte PCM sau giải nén), mẫu số là tốc độ phát. Tỉ lệ ≥ 130% là xong.

### Muốn tỉ lệ đó lên thì làm gì

1. **Nhả từng câu, flush ngay.** Sinh xong câu 1 thì đẩy câu 1 ra luôn, đừng đợi cả đoạn. Board đã dựng để nuốt kiểu này.
2. **Sinh câu n+1 song song với lúc đang đẩy câu n.** Nếu TTS chạy tuần tự thì tỉ lệ không bao giờ vượt 1.0×.
3. **Đừng chèn im lặng dẫn đầu.** Board tính giờ từ byte đầu tiên.

---

## 4. Đồng hồ — board bỏ cuộc lúc nào

| Mốc | Trần | Ở đâu |
|---|---|---|
| Header phản hồi (`HTTP/1.1 200 OK` + headers) | **90 giây** | `NET_TIMEOUT_MS` |
| Cloudflare tự ngắt (lỗi 524) | **100 giây** | ngoài tầm board |
| Từ lúc gửi xong → byte tiếng đầu tiên | 180 giây | `FIRST_AUDIO_MS` |
| Khoảng im GIỮA CHỪNG khi đã có tiếng | **30 giây** | `BODY_GAP_MS` |

🔴 **Trả `200` + headers NGAY, đừng đợi sinh xong tiếng rồi mới trả.** Trần header là 90 s mà Cloudflare cắt ở 100 s — sinh tiếng lâu hơn thế là board không bao giờ thấy phản hồi. Trả headers trước rồi stream thân là đúng cách.

Board **không** đòi miếng kết thúc `0\r\n\r\n` của chunked (server hiện không gửi) — nó dựa vào khoảng im 30 giây để biết đã hết. Gửi miếng kết thúc hoặc đóng kết nối thì board kết thúc ngay, đỡ mất 30 giây cuối mỗi lần.

---

## 5. Thử bằng curl

```bash
curl -v -H "Expect:" \
     -F "image=@capture.jpg;type=image/jpeg" \
     -F "audio=@record.wav;type=audio/wav" \
     https://api.visioncare-host.uk/process --output reply.bin
```

🔴 **`-H "Expect:"` là bắt buộc.** curl tự thêm `Expect: 100-continue` cho thân > 1 KB; server này không trả `100 Continue` nên curl treo tới timeout. Board tự dựng header nên không dính — chỉ curl mới dính.

Kiểm tra file server trả:
```bash
ffprobe -v error -show_streams reply.bin | grep -E "codec_name|sample_rate|channels"
# mong doi: adpcm_ima_wav / 16000 / 1
```

---

## 6. Tóm tắt — cần đổi đúng ba thứ

1. **Đọc `record.wav` bằng ffmpeg/soundfile** thay vì coi nó là PCM 16-bit thô. Không đổi chỗ này thì bản thu thành nhiễu.
2. **Trả `adpcm_ima_wav`, mono, 16000 Hz, block 256.**
3. **Trả headers ngay, stream thân từng câu, flush sau mỗi câu.** Đây mới là chỗ quyết định người dùng đợi bao lâu.
