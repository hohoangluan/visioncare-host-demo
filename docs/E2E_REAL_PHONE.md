# Chạy E2E với điện thoại THẬT

Điện thoại thật chạy app Android `app-demo-backend/mobile` (do bạn build trên máy bạn; server này không có JDK/Android SDK).
Kính vẫn là kính giả lập (`tools/e2e_full.py`), nhưng lệnh đi qua app server thật tới điện thoại thật qua FCM. `phone_sim`
đã được chỉnh để báo kết quả y hệt app (xem chú thích nguồn Kotlin trong `AB/scripts/phone_sim.py`), nên kết quả mong đợi dưới đây
giống cột "kết quả" của E2E mô phỏng, nhưng bạn tự nhìn/nghe điện thoại.

## 1. Chuẩn bị

1. Build và cài APK (trên máy có Android SDK): xem `mobile/README.md`.
   `cd mobile && ./gradlew test lint assembleDebug` (Windows: `.\gradlew.bat ...`), cần `app/google-services.json` của Firebase.
   Cấu hình build trong `local.properties`: `youreyes.serverUrl`, `youreyes.deviceApiToken` (token Device API thô). Bản debug cho phép HTTP.
2. Cài sẵn trên điện thoại: Spotify (đã đăng nhập), Google Maps, Grab. Cấp mọi quyền app hỏi (gọi, danh bạ, SMS, vị trí, thông báo,
   hiển thị trên ứng dụng khác, bỏ tối ưu pin); bật "Truy cập thông báo" cho Your Eyes.
3. Trong app: Hồ sơ -> chạm "phiên bản" 7 lần -> nhập server + token -> "Lưu Cấu Hình & Kết Nối Server".
4. Hồ sơ -> Kính Your Eyes: ghép `device_id` kính. Dùng đúng id này cho `--glasses-id` bên dưới (ví dụ `glasses-123`).
5. Danh bạ: có liên hệ `Mẹ` (đúng 1 số) và `Nam` với 2 số khác nhau (hoặc đặt tên khác qua `--contact-single` / `--contact-multi`).
   Hồ sơ -> An toàn: đặt người thân khẩn cấp (số hoặc tên trong danh bạ).
6. App server chạy sẵn (cổng công khai hoặc LAN) và đã cấu hình `DELIVERY_TRANSPORT=fcm`. Để VH nhận kết quả ngay thay vì poll mỗi 0,5 s,
   cấu hình cả ba `CALLBACK_URL`/`CALLBACK_TOKEN`/`CALLBACK_ALLOWED_HOSTS` trỏ `http://<máy VH>:18893/internal/action-results`
   (token = `VISIONCARE_CALLBACK_TOKEN` của VH); không có thì VH tự poll.

## 2. Chạy

Token công khai của VH tới app server là `VISIONCARE_CLIENT_TOKEN` (nằm trong `SeeVia_system/.env`; công cụ tự đọc, không in). Nếu app
server của bạn dùng token khác, đặt biến môi trường `VISIONCARE_CLIENT_TOKEN` trước lệnh (đừng `source` file `.env`).

```bash
cd VH
CUDA_VISIBLE_DEVICES=2 ~/.venvs/seevia/bin/python tools/e2e_full.py \
    --app-url https://<app server thật> --no-phone-sim --glasses-id <device_id kính đã ghép> --gpu 3 \
    --only call_mom            # lần lượt từng kịch bản dưới đây
```

`--app-url` không dựng AB/postgres/phone_sim (và tự bật `--no-phone-sim`); công cụ vẫn dựng VH cục bộ trỏ tới app server đó
(hoặc thêm `--vh-url http://127.0.0.1:18888` để dùng VH đang chạy; khi đó đặt `VISIONCARE_DEVICE_CLIENT_TOKEN`).
Không có `phone_sim_log.jsonl`, nên công cụ suy "lệnh đã gửi" từ log VH (`Calling VisionCare API: POST .../service/<op>`), báo FAIL nếu app server
trả `HTTPError`, và KHÔNG kiểm tham số/`report`/"kết quả đọc": bạn tự nhìn điện thoại theo cột "kết quả mong đợi".
Lưu ý B1 trong `docs/E2E_FULL_FLOW.md`: với `call`/`music_play`/`emergency`/`ride`, người dùng hiện không nghe được kết quả.

## 3. Kịch bản và kết quả mong đợi

| Kịch bản (`--only`) | Kính nói | Mong đợi trên điện thoại | Mong đợi từ kính / công cụ |
|---|---|---|---|
| `call_mom` | "Gọi cho mẹ." | Sau ~2-3 s, app gọi số của Mẹ (màn hình gọi mở). Report `succeeded`, `contact_name`=tên lưu trong danh bạ, số được che `***xyz`. | Đọc lại "Đang gọi cho mẹ." trong < 1 s; bảng in PASS với `lệnh -> ĐT` ~2-3 s |
| `call_nam` | "Gọi cho Nam." (tên có 2 số) | KHÔNG gọi; report `failed` `MULTIPLE_CONTACTS_FOUND` kèm `candidates` (2 số đã che). | PASS khi lệnh tới |
| `call_cancel`, `call_cancel_newturn`, `call_cancel_disconnect` | "Gọi cho mẹ." rồi huỷ ngay (nút / bấm lượt mới / ngắt kính) | Điện thoại KHÔNG nhận lệnh, KHÔNG gọi. | PASS khi 7 s sau không có `Calling VisionCare API` nào |
| `music` | "Tăng âm lượng lên." -> "Mở bài Lạc trôi của Sơn Tùng." -> "Dừng nhạc lại." (bấm nút) | Âm lượng STREAM_MUSIC tăng một bậc; Spotify mở/phát bài; rồi dừng. Report `music_play` có `provider:"Spotify"`; thiếu Spotify đăng nhập -> `MUSIC_ACCOUNT_NOT_CONNECTED`. | PASS khi cả 3 lệnh đi |
| `nav` | "Dẫn tôi đến chợ Bến Thành." -> (hazard) -> bấm nút | Google Maps mở chỉ đường tới điểm đến; `navigation_id` `nav-xxxxxxxx`; bấm nút -> Maps dừng (`navigation_stop` mang đúng `navigation_id`). | PASS khi `navigation_start`/`navigation_stop` đi (hiện kịch bản FAIL vì B2: live nav không đóng) |
| `ride` | "Đặt xe đến chợ Bến Thành." -> "Đồng ý, xác nhận đặt xe." | Lượt 1 không có gì trên điện thoại. Lượt 2: Grab mở màn báo giá (`ride_quote`: `quote_id` `quote-xxxxxxxx`, `GrabCar`); xác nhận/huỷ chuyến làm TRONG app Grab. | PASS khi `ride_quote` chỉ đi ở lượt 2 |
| `emergency` | "Cấp cứu, gọi người thân giúp tôi." | App gọi người thân đã cài + gửi SMS khẩn cấp; report `answered:false`, `attempt:1`, `cycle:"stopped"`. Chưa cài người thân -> `EMERGENCY_CONTACT_NOT_CONFIGURED`. | PASS khi lệnh tới |
| `chat` | "Kể cho tôi một câu chuyện cười ngắn." | Không có gì xảy ra trên điện thoại. | PASS khi 0 lệnh |

Chạy hết: bỏ `--only`. Sau mỗi lần có `call_*`/`emergency`, đối chiếu lịch sử cuộc gọi trên điện thoại. Payload mẫu server -> app của cả 9 action:
`AB/tests/fixtures/server_payloads/` (kèm README mô tả từng trường), dùng cho test phía app.

## 4. Nếu lỗi

- Không có lệnh trên điện thoại: kiểm FCM (app mở nền, không bị tối ưu pin), app đã đăng ký + ghép đúng `--glasses-id`
  (app server trả `GLASSES_DEVICE_NOT_LINKED` thì bảng báo "app server từ chối lệnh").
- 401 từ app server: sai `VISIONCARE_CLIENT_TOKEN`.
- Nội dung lệnh sai (tên/điểm đến): kết quả STT/Gemma, xem `results/e2e_full/vh.log` (VH do công cụ dựng ghi log vào đó).
