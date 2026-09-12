# Stream audio TTS theo từng phần về MCU

Ngày: 2026-07-27

## Vấn đề

`POST /process` hiện tổng hợp toàn bộ câu trả lời thành một file WAV rồi mới
trả về (`app.py`, `pipeline/tts.py`). Người dùng phải chờ hết thời gian TTS
(~1-3s, dài hơn với câu trả lời của `space`/`find`) mới nghe được âm thanh đầu
tiên. Với người khiếm thị đang đứng chờ giữa đường, khoảng lặng đó là chi phí
thật.

VieNeu v3 Turbo có sẵn `infer_stream()` yield từng `np.ndarray` ngay khi giải
mã xong mỗi nhóm frame, nên server có thể phát byte đầu tiên trước khi tổng
hợp xong cả câu.

## Phạm vi

Chỉ streaming bước TTS. STT, nhận diện intent, và handler (OCR/Gemini) vẫn chạy
tuần tự tới khi có text hoàn chỉnh, rồi mới bắt đầu stream.

Ngoài phạm vi: streaming STT/VLM, upload ảnh theo chunk, WebSocket, sửa firmware
MCU.

## Quyết định thiết kế

| Hạng mục | Chọn | Lý do |
| --- | --- | --- |
| Client | MCU/ESP32 | Ưu tiên parse tối giản, RAM thấp |
| Transport | HTTP chunked (`StreamingResponse`) | MCU đọc socket tuần tự, không cần WebSocket stack |
| Format | Raw PCM 16-bit little-endian mono, không header | MCU đẩy thẳng vào I2S/DAC, không parse |
| Sample rate | 16000 Hz | 32 KB/s thay vì 96 KB/s; đủ cho dải giọng nói |
| Endpoint | Sửa thẳng `POST /process` | Một đường duy nhất; dự án chưa release nên breaking change rẻ |

`Content-Type` là `application/octet-stream`, kèm header
`X-Audio-Format: pcm_s16le;rate=16000;channels=1`. Không dùng `audio/L16` vì
RFC 2586 quy định L16 là big-endian, còn ta gửi little-endian.

## Luồng

```
MCU POST /process (image + audio)
   |  [chưa gửi byte nào]
   +- STT -> intent -> handler (OCR/Gemini) -> speech text
   |     lỗi ở bước này vẫn đổi thành câu lỗi rồi stream như thường
   +- StreamingResponse
        tts.synthesize_stream(text) yield từng chunk PCM
             -> MCU đọc socket -> đẩy I2S ngay
```

## `pipeline/tts.py`

```python
SAMPLE_RATE = 48000         # VieNeu native
OUTPUT_SAMPLE_RATE = 16000  # gửi MCU

def synthesize_stream(text: str) -> Iterator[bytes]
def synthesize(text: str) -> bytes       # giữ nguyên, dùng cho warm-up và test
```

`synthesize_stream` gọi `Vieneu.infer_stream(text, voice=..., style=...)`. Mỗi
chunk float32 48 kHz được: clip về [-1, 1] -> downsample -> nhân 32767 ->
`int16` -> `tobytes()`.

**Downsample 48k -> 16k** bằng trung bình mỗi 3 mẫu, không phải `pcm[::3]` —
decimate trần gây aliasing. Box filter 3-tap đủ cho giọng nói và không thêm phụ
thuộc scipy.

Chunk từ VieNeu không chắc chia hết cho 3. Số mẫu dư (1-2 mẫu) được giữ làm
carry và ghép vào đầu chunk kế tiếp, nên không mẫu nào bị mất ở biên chunk.
Carry là biến cục bộ trong generator, không phải state toàn cục.

Chunk cuối cùng có thể còn 1-2 mẫu dư không đủ nhóm 3; phần dư này bị bỏ
(tối đa 2 mẫu ở 48 kHz = 42 micro giây, không nghe thấy).

## `app.py`

- `/process` trả `StreamingResponse` thay cho `Response`.
- Endpoint giữ `def` (sync) nên FastAPI chạy thân hàm trong threadpool; Starlette
  bọc sync generator bằng `iterate_in_threadpool` nên TTS không chặn event loop.
- Thiếu `image` hoặc `audio`: cũng stream câu lỗi, không còn trả WAV.
- Debug: generator gom chunk vào list trong lúc stream, chạy xong ghi
  `response{idx}.wav` — WAV 16 kHz thật, mở được bằng player.

## Xử lý lỗi

| Thời điểm | Xử lý |
| --- | --- |
| Trước khi TTS bắt đầu | Như cũ: đổi thành câu lỗi rồi stream |
| Giữa lúc TTS đang stream | Byte đã gửi đi, không rút lại được. Log rồi dừng generator; MCU nghe cụt câu. |
| MCU ngắt kết nối | Generator bị đóng, không ghi file debug |

## Kiểm thử

- `synthesize_stream` yield đúng số chunk mà `infer_stream` sinh ra, mỗi chunk
  là PCM int16 little-endian.
- Số mẫu ra bằng 1/3 số mẫu vào (kiểm với chunk không chia hết cho 3, xác nhận
  carry không làm mất mẫu ở biên).
- Downsample thực sự lọc, không phải lấy mẫu xen kẽ: tín hiệu xen kẽ +1/-1 ở
  48 kHz phải ra gần 0 sau khi trung bình, không ra +1.
- `/process` trả 200, body không bắt đầu bằng `RIFF`, độ dài chia hết cho 2,
  có header `X-Audio-Format`.
- Đường lỗi (`router.process` raise, thiếu field) vẫn trả PCM khác rỗng.
