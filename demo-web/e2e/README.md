# Bộ kiểm thử trình duyệt cho trang demo (để tối ưu UX về sau)

`browser_e2e.py` mở **bảng giám sát** (`index.html`) và **kính giả lập** (`client.html`) bằng Chromium thật như người dùng:
bật camera/micro, giữ nút nói, nhìn bảng. Mỗi kịch bản chụp màn hình, đo vài con số UX và in bảng ĐẠT/HỎNG; `report.json`
giữ số đo để **so trước/sau khi sửa giao diện**. Thoát 0 nếu mọi kiểm tra đạt.

```bash
# server thật (đã ./run.sh): trang ở https://localhost:18443, mặc định chạy 6 kịch bản, ~4 phút
~/.venvs/seevia/bin/python demo-web/e2e/browser_e2e.py --mode real

# không cần GPU: tự dựng fake_server + serve.py ở cổng tạm, ~1 phút
~/.venvs/seevia/bin/python demo-web/e2e/browser_e2e.py --mode fake

# chọn kịch bản / nơi lưu / địa chỉ trang
... --mode real --scenarios nav ocr-live --out storage/e2e-demo-web/truoc-khi-sua --url http://localhost:18080
```

Ảnh và `report.json` nằm ở `storage/e2e-demo-web/run-<giờ>/` (đã nằm trong `.gitignore`). Số đo nền đã chạy xong nằm ở
[`baseline-real.json`](baseline-real.json) (47/47 đạt) và [`baseline-fake.json`](baseline-fake.json) (47/47), cả hai ngày 2026-10-21, sau khi sửa giao diện (D1-D5).

## Cài đặt (một lần)

Playwright + Chromium cài thẳng vào venv dự án (venv này dùng `uv`, không có pip):

```bash
uv pip install --python ~/.venvs/seevia/bin/python playwright
# Ubuntu 20.04 không được Playwright hỗ trợ chính thức: tải bản 22.04, chạy vẫn được
PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64 ~/.venvs/seevia/bin/python -m playwright install chromium
```

Cần thêm `ffmpeg` (dựng camera giả) và **dữ liệu thật của workspace SeeVia** cho chế độ `real`: câu lệnh tiếng Việt trong
`../stt-bench-cache/cmd/`, ảnh vật cản trong `../evaluations/datas/obstacle_dataset/`, ảnh biển chữ trong
`../evaluations/datas/vintext/`. Thiếu thì script dừng và nói thiếu file nào.

## Kịch bản

| Kịch bản | Làm gì | Kiểm gì |
|---|---|---|
| `describe` | Nói "Mô tả không gian xung quanh" trước ảnh xe tải | Nối không cần token; POV hiện ảnh lúc bấm nút; timeline có transcript + ý định; lịch sử; **tiếng đầu < 1,5 s** |
| `nav` | "Bật cảnh báo vật cản" trên chuỗi ảnh phố/xe/người, rồi "Tắt cảnh báo vật cản", rồi đóng kính | Chế độ sáng/tắt; fps live; log cảnh báo; client hiện đang gửi live; **mọi `det` đi sau đúng khung JPEG của nó**; người xem Python không token vẫn nhận; kính ngắt thì bảng báo chưa kết nối |
| `ocr-direct` | "Đọc lá thư tôi đang cầm" trước biển "CÔNG TRƯỜNG ĐANG THI CÔNG" | Server đọc thẳng đúng chữ, không mở OCR live |
| `ocr-live` | Cùng câu nhưng trước ảnh không có chữ | Chế độ OCR sáng; chip "Lại gần"; bong bóng "SeeVia · trực tiếp" gộp câu lặp (×N); mọi `ocr` đi sau đúng khung JPEG |
| `fake-flow` | (chỉ `--mode fake`) hỏi cảnh → đọc chữ live → tránh vật cản với server giả | Cùng các kiểm tra hiển thị, không cần GPU: dùng khi chỉnh UX nhanh |
| `fake-tour` | (chỉ `--mode fake`, 1920x1080) cả kịch bản 8 lượt: hỏi cảnh, đọc chữ live, tránh vật cản, gọi điện hai lượt, nhạc hai lượt | Thẻ hội thoại đủ mọi lượt (người dùng nói, ý định, kính trả lời, độ trễ); chip lệnh điện thoại Chờ -> Xong + kết quả; ô Điện thoại; ảnh thu nhỏ ở log cảnh báo và thẻ trực tiếp; **không chữ bị cắt**, không cuộn ngang; câu rỗng |
| `fake-client` | (chỉ `--mode fake`) `client.html`: giữ phím Space | Space = bấm nói, `role=meter` nhích lên khi có tiếng, trạng thái "Đang nghe bạn…", thả phím gửi lượt, không kẹt |
| `phone-mirror` | (chỉ `--mode fake`) `serve.py --phone-mirror` với adb GIẢ (ffmpeg testsrc; không gọi adb thật) | Ô Điện thoại hiện ảnh 540 px thật qua `/phone/stream.mjpg`, thẻ tác vụ nằm dưới khung |
| `layout` | Bảng giám sát ở 1440×900 và 390×800, hộp Cài đặt | Không cuộn ngang; Cài đặt không còn ô camera / Mô phỏng |
| `bad-token` | Chạy một proxy cấu hình token SAI | Trang báo "Token sai", không hiện kính đã kết nối (đối chứng âm cho cấu hình sẵn) |

Mỗi kịch bản mở trình duyệt mới nên độc lập nhau. Ảnh chụp: `<kịch bản>_<bước>.png`, riêng `layout` là `layout_*_{desktop,phone}.png`.

## Cách nó hoạt động (và vì sao)

- **Camera = file MJPEG** dựng từ ảnh thật, Chromium phát qua `--use-file-for-fake-video-capture` (đã đo: phát đúng nhịp thực,
  tự lặp nên 1 vòng ngắn là đủ).
- **Micro = MediaStream do bài test phát file câu lệnh đúng lúc** (`INIT_SCRIPT`). Micro giả của Chromium
  (`--use-file-for-fake-audio-capture`) **trôi giờ khi máy bận** (đã gặp: câu lệnh rơi sang cửa sổ lượt sau), nên lượt nghe sai.
  Từ MediaStream trở đi là đường thu âm thật của `client.html` (worklet, hạ mẫu, WebSocket). Âm thanh client gửi được kiểm là
  giống file gốc (tương quan 0,996).
- **Người xem Python (`PyObserver`)** nối `/api/v2/observe` song song, không mang token: chứng minh proxy gắn token cho client
  không phải trình duyệt, và đếm khung độc lập với giao diện. Nó ping mỗi 20 s vì server ngắt phiên xem im quá 90 s.
- **Bấm nút:** giữ nút, phát câu sau `--say-lead` giây (mặc định 0,2), thả sau câu + 2,5 s.
- Mỗi lượt lưu `*_turnN_sent.wav` (đúng âm thanh client đã gửi) vào thư mục kết quả, để nghe lại hoặc đưa qua
  `demo-web/realcheck.py` khi nghi đường thu âm.
- Số đo trong `report.json`: `ttfa_ms` (tiếng đầu, đo ở trang xem), `fps_text`, `det_frames`, `ocr_frames`, `ocr_chip`,
  `*_scrollWidth`, `alert_*_heard` (câu + ý định server nghe được), `audio_onsets`, `empty_state`.

## Số đo nền (2026-10-21, server thật GPU 1)

| Số đo | Giá trị |
|---|---|
| Tiếng đầu, "Mô tả không gian" | 316–563 ms (5 lần đo; có tính độ trễ tới trang xem) |
| Nav live | qvga 8 fps, server xử lý 8,0 fps; ~120–165 khung `det` mỗi lượt chạy, 100% đi sau đúng JPEG |
| OCR live | vga 5 fps; ~75–100 khung `ocr` mỗi lượt chạy |
| Cuộn ngang bảng giám sát | 1440 px = 1440, 390 px = 390 (không cuộn) |

## Phát hiện ghi lại cho sau (chưa sửa)

1. **STT rớt chữ đầu câu tuỳ vị trí bắt đầu tiếng nói** (server, không phải giao diện). Câu "Tắt cảnh báo vật cản" mà tiếng nói
   bắt đầu quanh 0,6–1,0 s sau khi bấm thì server nghe thành "Cảnh báo vật cản" và **bật nhầm** cảnh báo thay vì tắt. Đã tách bạch
   bằng cách gửi thẳng cùng file qua `realcheck.py` với phần lặng đệm khác nhau:

   | Lặng trước / sau | Server nghe |
   |---|---|
   | 0,63 s / 0 s | "Cảnh báo vật cản" (sai) |
   | 0 s / 2,5 s | "Tắt cảnh báo vật cản" |
   | 0,63 s / 2,5 s | "Cảnh báo vật cản" (sai) |
   | 0,2 s / 2,5 s | "Tắt cảnh báo vật cản" |
   | 1,2 s / 0,5 s | "Tắt cảnh báo vật cản" |

   Không đơn điệu theo độ dài lặng, nên nghi ranh giới khối của STT streaming hoặc VAD quanh mốc ~1 s. Người dùng thật bấm rồi
   mới nói nên có thể gặp. Tái hiện: `--say-lead 0.6` (hỏng 5/7 lần chạy kịch bản `nav`). Bộ test mặc định `--say-lead 0.2` để khỏi chập chờn.
   Tương tự, câu "Bật cảnh báo vật cản" luôn bị nghe thành "Cảnh báo vật cản" nhưng vẫn ra đúng `alert_on`.
2. Ghi nhận khi xem giao diện, **ý tưởng chưa quyết**: bảng chưa cho nghe lại điều người dùng nói (chỉ có transcript); log cảnh báo
   không gắn với khung hình lúc cảnh báo; timeline chỉ giữ 2 câu đầu của lượt; trên điện thoại thanh chế độ bị cắt phải cuộn ngang;
   chỉ xem được một kính tại một thời điểm; chưa có chỉ báo âm lượng khi kính đang nghe.

## Giới hạn

- Chạy headless nên **không nghe được loa**: chỉ kiểm việc nhận khung `0x02` và độ trễ tiếng đầu, không kiểm âm thanh phát ra.
- Trang `client.html` chỉ kiểm bố cục trên máy tính; giao diện điện thoại của client đã bỏ.
- Chế độ `real` thao tác thật trên mã kính hiện tại (`glasses-123`): trang client thay phiên kính thật nếu kính đó đang nối (`4000`),
  và trạng thái server của kính (chế độ, lệnh chờ) bị đổi trong lúc chạy. Đừng chạy khi đang dùng kính thật.
- Cần server thật đã bật (`./run.sh`); kịch bản `describe` cần mạng tới LLM/VLM.
