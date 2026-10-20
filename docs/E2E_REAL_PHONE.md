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
    --only music               # lần lượt từng kịch bản dưới đây
```

`--app-url` không dựng AB/postgres/phone_sim (và tự bật `--no-phone-sim`); công cụ vẫn dựng VH cục bộ trỏ tới app server đó
(hoặc thêm `--vh-url http://127.0.0.1:18888` để dùng VH đang chạy; khi đó đặt `VISIONCARE_DEVICE_CLIENT_TOKEN`).
Không có `phone_sim_log.jsonl`, nên công cụ suy "lệnh đã gửi" từ log VH (`Calling VisionCare API: POST .../service/<op>`), báo FAIL nếu app server
trả `HTTPError`, và KHÔNG kiểm tham số/`report`/"kết quả đọc": bạn tự nhìn điện thoại theo cột "kết quả mong đợi".
Kết quả của `music_play`/`emergency`/`ride` được đọc cho kính qua khung `result-<request_id>` (xem `FIRMWARE_ENDPOINTS.md` §4.1); kịch bản thật nên nghe thử.

## 3. Kịch bản và kết quả mong đợi

| Kịch bản (`--only`) | Kính nói | Mong đợi trên điện thoại | Mong đợi từ kính / công cụ |
|---|---|---|---|
| (gọi điện) | — | `call_mom`/`call_nam`/`call_cancel*` đã bỏ khỏi `e2e_full`: gọi điện giờ đi AB + `WS /v2/call` (qua mạng, không SIM), không còn lệnh `contact_call` tới điện thoại. Kiểm bằng `tools/e2e_calls.py` (11 kịch bản) hoặc app người thân thật. | — |
| `music` | "Mở bài Lạc trôi của Sơn Tùng." -> "Tăng âm lượng lên." (lúc đang phát) -> chỉ bấm nút (không nói) | Spotify mở/phát bài; âm lượng STREAM_MUSIC tăng một bậc mà nhạc vẫn chạy; bấm nút không lời thì dừng. Report `music_play` có `provider:"Spotify"`; thiếu Spotify đăng nhập -> `MUSIC_ACCOUNT_NOT_CONNECTED`. | PASS khi cả 3 lệnh đi |
| `nav` | "Dẫn tôi đến chợ Bến Thành." -> (một câu chat) -> chỉ bấm nút (không nói) | KHÔNG mở live nav. Điện thoại nhận `navigation_start` (có `maps_url` Google Maps, `navigation_id` `nav-xxxxxxxx`) và hiện thông báo; kính đọc "Đã gửi chỉ đường tới ... về điện thoại. Mở thông báo để đi bằng Google Maps." Bấm nút không lời -> `navigation_stop` mang đúng `navigation_id`. | PASS khi `navigation_start` (+ `maps_url`) và `navigation_stop` đi, câu kết quả đúng, không có khung `cam`/`hazard` |
| `alert` | "Bật cảnh báo vật cản." -> một câu chat | Live nav mở (`cam` qvga), hazard tới; câu chat không làm `end`, không sinh lệnh điện thoại. | PASS khi hazard còn tới sau câu chat. Ảnh mặc định `tools/assets/hazard_level2.jpg` có vật cản mức >= 2; ảnh không đạt thì FAIL rõ ràng "không có hazard" |
| `ride` | "Đặt xe đến chợ Bến Thành." -> "Đồng ý, xác nhận đặt xe." | Lượt 1: Grab mở màn báo giá (`ride_quote`: `quote_id` `quote-xxxxxxxx`, `GrabCar`). Lượt 2: `ride_confirm` với đúng `quote_id`, `confirm:true`. | PASS khi `ride_quote` rồi `ride_confirm` đi |
| `ride_cancel` | "Đặt xe..." -> "Hủy chuyến xe." | Sau báo giá, `ride_confirm` với `confirm:false` (`ride_status:"cancelled"`). | PASS khi `ride_confirm` đi |
| `emergency` (ĐƯỜNG DỰ PHÒNG SIM) | "Cấp cứu, gọi người thân giúp tôi." | Chỉ khi kính chưa có token riêng/phiên (đường internet không dùng được): app chủ kính gọi người thân đã cài + gửi SMS `[SOS]`; report `answered:false`, `attempt:1`, `cycle:"stopped"`. Chưa cài người thân -> `EMERGENCY_CONTACT_NOT_CONFIGURED`. Đây là lưới an toàn có chủ ý riêng cho khẩn cấp; đường chính (AB gọi người thân qua mạng) kiểm ở `tools/e2e_calls.py`. | PASS khi lệnh tới |
| `chat` | "Kể cho tôi một câu chuyện cười ngắn." | Không có gì xảy ra trên điện thoại. | PASS khi 0 lệnh |

Chạy hết: bỏ `--only`. Sau mỗi lần có `emergency`, đối chiếu lịch sử cuộc gọi trên điện thoại. Payload mẫu server -> app của cả 9 action:
`AB/tests/fixtures/server_payloads/` (kèm README mô tả từng trường), dùng cho test phía app.

## 4. Nếu lỗi

- Không có lệnh trên điện thoại: kiểm FCM (app mở nền, không bị tối ưu pin), app đã đăng ký + ghép đúng `--glasses-id`
  (app server trả `GLASSES_DEVICE_NOT_LINKED` thì bảng báo "app server từ chối lệnh").
- 401 từ app server: sai `VISIONCARE_CLIENT_TOKEN`.
- Nội dung lệnh sai (tên/điểm đến): kết quả STT/Gemma, xem `results/e2e_full/vh.log` (VH do công cụ dựng ghi log vào đó).
