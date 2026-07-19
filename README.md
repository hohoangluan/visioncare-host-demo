# Blind-Assist Audio Server

Server hỗ trợ người khiếm thị: vi điều khiển gửi **ảnh + audio (WAV)**,
server chạy STT → nhận diện ý định → handler → TTS, rồi trả về **audio/wav**
tiếng Việt để thiết bị phát cho người dùng.

## Cài đặt

```powershell
python -m pip install -r requirements.txt
```

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
- `POST /process` (multipart: `image`, `audio`) → `audio/wav`

`/process` luôn trả `audio/wav` với HTTP 200, kể cả khi thiếu field hoặc
xử lý gặp lỗi. Câu báo lỗi được chuyển thành WAV để người khiếm thị có thể nghe,
thay vì thiết bị nhận một lỗi JSON không phát được.

## 5 chức năng

| Intent | Chức năng |
| --- | --- |
| `ocr` | Đọc chữ trong ảnh; mặc định dịch sang tiếng Việt, nói “nguyên văn” hoặc “chuyên ngành” để đọc thô |
| `translate` | Dịch câu người nói VI→EN hoặc EN→VI, tự nhận diện hướng |
| `find` | Tìm đồ vật và chỉ hướng |
| `money` | Đọc mệnh giá tiền |
| `space` | Miêu tả không gian trước mặt; cũng là fallback khi không nhận diện được intent |

## Trạng thái hiện tại

Toàn bộ bước AI hiện là **stub**. Các interface đã được cố định để sau này lắp
model hoặc API thật mà không phải sửa router hay endpoint:

- `pipeline/stt.py`: TODO model STT tiếng Việt.
- `pipeline/tts.py`: TODO TTS tiếng Việt; hiện sinh WAV im lặng hợp lệ.
- `pipeline/intent.py`: hiện khớp từ khóa, có thể thay bằng classifier.
- `handlers/ocr.py`, `handlers/translate.py`: TODO model.
- `handlers/find_object.py`, `handlers/read_money.py`,
  `handlers/describe_space.py`: TODO API vision.

Hai thư mục `models/ocr/` và `models/translate/` đang để trống, chờ file model.

## Ngoài phạm vi

Các chức năng điện thoại (gọi, nhắn tin, push tới ứng dụng di động) và hỏi ngày
giờ đã được gỡ khỏi phạm vi hiện tại. Code cũ vẫn còn trong lịch sử Git.
