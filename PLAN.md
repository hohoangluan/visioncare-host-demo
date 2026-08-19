# Plan tối ưu action điện thoại P95 dưới 1 giây

## 1. Mục tiêu và hợp đồng thời gian

- Đo từ lúc `Sever_test` bắt đầu POST tới backend đến lúc backend nhận report xác nhận hiệu ứng action trên điện thoại.
- Tiêu chí nghiệm thu: ít nhất 95/100 lượt của từng action hoàn tất và report dưới `1.000 ms`.
- Action quá 1 giây không bị hủy: tiếp tục chạy, nhận report muộn và đánh dấu `slo_missed=true`.
- Không coi `202 Accepted`, FCM accepted hoặc intent được tạo là thành công nếu action yêu cầu trạng thái quan sát được khác.
- Phân bổ mục tiêu: backend queue 100 ms, FCM 350 ms, Android 300 ms, report HTTPS 200 ms, callback nội bộ 50 ms.

## 2. Backend và Sever_test

- Thay vòng đợi worker 0,5 giây bằng cơ chế đánh thức tức thời sau commit cho cả delivery và callback; vẫn giữ polling làm recovery sau restart.
- FCM tiếp tục là data message high-priority, TTL 10 giây; bổ sung thời điểm phát hành/deadline và ghi nhận original/delivered priority để phát hiện bị hạ ưu tiên.
- Khi `/api/v1/device/report` commit thành công, đánh thức callback worker ngay; callback dùng endpoint localhost mới của `Sever_test`, bearer token riêng và `Idempotency-Key=request_id`.
- `Sever_test` giữ registry `request_id → threading.Event/result`; handler chờ callback tối đa 1 giây thay vì poll status. Quá hạn thì phát câu “điện thoại vẫn đang thực hiện”, giữ registry để callback muộn cập nhật `navigation_id`, `quote_id` và trạng thái nhạc.
- Thêm timing persistence/structured metrics cho `accepted`, `fcm_sent`, `report_received`, `callback_delivered`; không log token, liên hệ hoặc tọa độ raw.
- Cấu hình callback chỉ cho phép `127.0.0.1:8000`; điện thoại vẫn report qua public HTTPS vì khác mạng với backend.

## 3. Android fast path

- Thay single-thread executor toàn cục bằng dispatcher song song có kiểm soát: location/volume/navigation/ride độc lập; media có mutex riêng; call/emergency có mutex riêng. Một `music_play` chậm không được chặn action khác.
- Trong `onMessageReceived`, kiểm tra priority thực nhận, đăng notification user-visible ngay và khởi động foreground service; không fetch thêm payload.
- Thay `HttpURLConnection` bằng singleton OkHttp `4.12.0` để dùng connection pool, HTTP/2 và TLS reuse; report đầu tiên gửi ngay, thất bại thì lưu pending report và retry nền.
- Bổ sung metric monotonic: FCM received, action started/effect observed, report started/completed và action duration.
- Giữ thiết lập HyperOS: Autostart, notification, full-screen intent, battery `No restrictions`; thêm kiểm tra và cảnh báo trong màn hình setup nếu thiếu quyền.

### Location

- Thêm `play-services-location:21.4.0` và foreground location service có `FOREGROUND_SERVICE_LOCATION`.
- Tracking thích nghi: khi di chuyển dùng high-accuracy khoảng 1 giây; khi đứng yên giảm còn 5 giây. Khi FCM đến, nếu live fix quá 1 giây thì gọi `getCurrentLocation(HIGH_ACCURACY, maxUpdateAge=0)` trong phần ngân sách SLO còn lại.
- Chỉ fallback cache khi fresh/live fix thất bại. Cache tối đa 15 phút; cũ hơn trả `CURRENT_LOCATION_UNAVAILABLE`.
- Mở rộng kết quả location với `accuracy_m`, `captured_at`, `age_ms`, `source`, `is_stale`, `stale_reason`. `Sever_test` luôn thông báo rõ tuổi vị trí khi `is_stale=true`.
- Reverse-geocoding không nằm trong critical path; action report tọa độ trước, địa chỉ được enrich nền hoặc để `null`.

### Spotify

- Import Spotify App Remote AAR `0.8.0`; đăng ký client ID, redirect URI, package và SHA fingerprint. Authorization ban đầu diễn ra trong setup và không tính vào SLO.
- Backend thêm Spotify catalog adapter: chuẩn hóa tên bài, resolve thành `spotify:track:...`, cache URI; FCM gửi sẵn URI để điện thoại không search.
- Android gọi `playerApi.play(uri)` và chỉ report success khi `PlayerState` xác nhận đúng URI, playback không pause.
- Giữ App Remote warm tối đa 15 phút sau action nhạc gần nhất rồi disconnect; warm và cold được đo riêng. Cold vượt 1 giây tiếp tục chạy và ghi SLO miss.
- Loại bỏ đường YouTube Music sau khi Spotify warm-path đạt nghiệm thu; giữ feature flag rollback trong giai đoạn thử nghiệm.

## 4. Thay đổi interface

- Public request `music_play` vẫn nhận `song` và optional `volume`; không bắt client gửi Spotify URI.
- Internal FCM params bổ sung `spotify_uri`, `issued_at`, `deadline_at` và timing metadata.
- Location result bổ sung freshness fields nói trên; schema backend, Android DTO, OpenAPI contract và cách đọc của `Sever_test` cập nhật đồng bộ.
- Thêm callback endpoint nội bộ ở `Sever_test`; callback idempotent, xác thực token và không expose ra ngoài localhost.
- Thêm cấu hình secret/runtime: Spotify client credentials, callback URL/token/allow-list và các feature flag; không commit credential.

## 5. Kiểm thử và triển khai

- Backend: test worker wake không chờ poll, report đánh thức callback, callback retry/idempotency, restart recovery và PostgreSQL race tests.
- Android: test duplicate FCM, concurrency isolation, priority downgrade, pending report retry, fresh/stale location, giới hạn cache 15 phút, Spotify authorization/connect/play/PlayerState và cold failure.
- `Sever_test`: test callback auth/idempotency, callback trước/sau deadline, background state reconciliation và câu cảnh báo vị trí cũ.
- Chạy quality gates đầy đủ: backend Ruff/Mypy/Pytest/build, Android `test lint assembleDebug`, `Sever_test` pytest và OpenAPI diff.
- E2E trên điện thoại thật: tối thiểu 100 lượt/action cho màn hình bật, tắt màn hình, Doze, Wi‑Fi và 4G/5G; báo p50/p95/p99, tỷ lệ SLO miss, FCM downgrade, fresh/stale location và Spotify warm/cold.
- Rollout lần lượt: instrumentation → event-driven workers/callback → Android concurrency/report client → location → Spotify. Mỗi phase giữ feature flag rollback và không sửa đè các thay đổi ngoài phạm vi đang có trong hai worktree.

## Giả định đã khóa

- SLO nghiệm thu là P95 dưới 1 giây, không phải guarantee tuyệt đối cho mọi FCM delivery.
- Action muộn vẫn tiếp tục và report, không timeout/hủy ở mốc 1 giây.
- Spotify App Remote là đường phát nhạc mục tiêu; first-time authorization nằm ngoài SLO.
- Vị trí ưu tiên fresh/live; fallback cache tối đa 15 phút và luôn kèm tuổi/cảnh báo.
- Backend chạy một process Uvicorn như hiện tại; polling bền vững vẫn giữ để recovery.
