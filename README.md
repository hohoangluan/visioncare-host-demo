# Blind-Assist Audio Server

Server hỗ trợ người khiếm thị: vi điều khiển gửi **ảnh + audio (WAV)**,
server chạy STT → nhận diện ý định → handler → TTS, rồi trả về **audio/wav**
tiếng Việt để thiết bị phát cho người dùng.

## Cài đặt

```powershell
python -m pip install -r requirements.txt
```

### GPU (tuỳ chọn, khuyến nghị để giảm thời gian trả kết quả)

Nếu máy có GPU NVIDIA, dùng venv riêng trên ổ D để cài bản CUDA của
torch/paddlepaddle — không đụng tới ổ hệ thống (C) và tách khỏi Python global:

```powershell
python -m venv D:\Study\innostar\Sever_test\.venv
D:\Study\innostar\Sever_test\.venv\Scripts\python.exe -m pip install -r requirements.txt
D:\Study\innostar\Sever_test\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
D:\Study\innostar\Sever_test\.venv\Scripts\python.exe -m pip install paddlepaddle-gpu==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/
```

Chạy server bằng interpreter trong `.venv` (`D:\...\.venv\Scripts\python.exe -m uvicorn app:app`).
STT (`pipeline/stt.py`), OCR (`models/ocr/engine.py`) và TTS (`pipeline/tts.py`)
tự phát hiện GPU và chuyển sang chạy CUDA nếu có; không có GPU thì tự rơi về CPU.
Cache model (HuggingFace/torch/PaddleX) được `config.py` trỏ về
`models/.cache/` trong project (ổ D) thay vì thư mục người dùng mặc định (ổ C).

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

## 4 chức năng

| Intent | Chức năng |
| --- | --- |
| `ocr` | Đọc chữ trong ảnh; mặc định dịch sang tiếng Việt, nói “nguyên văn” hoặc “chuyên ngành” để đọc thô |
| `find` | Tìm đồ vật và chỉ hướng |
| `money` | Đọc mệnh giá tiền |
| `space` | Miêu tả không gian trước mặt |

Câu lệnh không khớp intent nào (`pipeline/intent.py`) sẽ không đoán bừa —
server trả lời "Xin lỗi, tôi không hiểu yêu cầu, xin thử lại." thay vì chạy
OCR/gọi Gemini với intent sai.


## Bối cảnh

Người dùng cuối là người khiếm thị (bẩm sinh hoặc sau tai nạn) — không thấy
được, hoàn toàn phụ thuộc vào audio trả về từ thiết bị. Vì vậy mọi output của
4 handler đều phải là câu nói tự nhiên, dễ hiểu qua tai nghe, không phải mô tả
kiểu thị giác cho người sáng mắt:

- `ocr`: đọc chữ trong ảnh thành lời — mặc định dịch sang tiếng Việt.
- `find`: tìm đồ vật và **nói ra hướng** để người dùng tự định vị bằng tay/di
  chuyển tới đồ vật, không phải liệt kê những gì nhìn thấy.
- `money`: đọc mệnh giá tiền cầm trên tay.
- `space`: miêu tả không gian phía trước — dùng để người dùng hình dung
  đường đi, vật cản; cũng là fallback khi không nhận diện được intent.

Mọi thiết kế response (text lẫn giọng đọc) phải ưu tiên: ngắn gọn, định hướng
hành động (đi đâu, cầm gì, tránh gì), không giả định người nghe nhìn được bất
cứ thứ gì trong ảnh.
## Trạng thái hiện tại

Toàn bộ bước AI hiện là **stub**. Các interface đã được cố định để sau này lắp
model hoặc API thật mà không phải sửa router hay endpoint:

- `pipeline/stt.py`: TODO model STT tiếng Việt.
- `pipeline/tts.py`: TODO TTS tiếng Việt; hiện sinh WAV im lặng hợp lệ.
- `pipeline/intent.py`: hiện khớp từ khóa, có thể thay bằng classifier.
- `handlers/ocr.py`: TODO model.
- `handlers/find_object.py`, `handlers/read_money.py`,
  `handlers/describe_space.py`: TODO API vision.

Thư mục `models/ocr/` đang để trống, chờ file model.

## Ngoài phạm vi

Các chức năng điện thoại (gọi, nhắn tin, push tới ứng dụng di động) và hỏi ngày
giờ đã được gỡ khỏi phạm vi hiện tại. Code cũ vẫn còn trong lịch sử Git.
