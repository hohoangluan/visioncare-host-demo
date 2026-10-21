# Brief A2 — Sửa lỗi app thấy trên máy thật (Xiaomi 24117RN76O, Android 14)

Repo `SeeVia_system/app-demo-backend`, app `mobile/`, nhánh `app-giao-tiep` (sau commit 0972d89). Bối cảnh lượt trước: `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-A.md`.
Commit theo từng mục, kết bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Build `JAVA_HOME=~/jdk-21.0.12.1+1 ANDROID_HOME=~/android-sdk ./gradlew test assembleDebug lint` xanh.
KHÔNG chạy adb (controller cài và thử trên máy thật). Hai file Firebase bí mật.

## Bối cảnh demo (người dùng chốt)
Điện thoại demo duy nhất, đăng nhập tài khoản "Chủ kính" (0988000001, public_user_id `8EB1A80A`), thiết bị `device-100` đã thuộc chủ kính trên AB.
Kính (client web hoặc firmware, cùng mã `glasses-123`) thuộc chủ kính → mọi lệnh kính về điện thoại này. Người thân "em iu" (0988000002, `5CB40CA5`)
đã liên kết (care_link chủ→em iu, active, emergency). AB thật ở `127.0.0.1:18001` (DB container `seevia-ab-pg`, user/db `app_demo`) — đọc được để kiểm API.

## Việc
1. **device_id cố định, không bắt người dùng nhập**: người dùng thường không thấy ô device_id (chỉ có ở chế độ nhà phát triển). Đặt mặc định cố định
   `device-100` (hằng số, có thể đổi ở chế độ nhà phát triển), và sau khi đăng nhập thành công app TỰ đăng ký thiết bị (FCM token + `/device/register`)
   với user đã đăng nhập — không cần bấm gì. Lỗi 409 DEVICE_OWNER_MISMATCH phải hiện câu dễ hiểu, không im lặng.
2. **"Chưa có người thân" sai**: màn chính của Chủ kính báo "Chưa có người thân" dù em iu đã liên kết. Tìm vì sao (app gọi endpoint nào, theo chiều nào —
   chủ kính thấy người thân mình mời; người thân thấy chủ kính) và sửa để cả hai chiều hiện đúng; ô Gọi/Tin nhắn phải dùng được với em iu.
   "Gọi" từ điện thoại chủ kính tới người thân: nếu AB chưa có API thì ô Gọi nói rõ điều đó bằng câu ngắn, còn Tin nhắn phải chạy.
3. **Ô Kính "Chưa kiểm tra được"** dù đã đăng nhập: kiểm app lấy trạng thái kính thế nào (Server Kính `/device/status`?), URL nào, vì sao lỗi; sửa để hiện
   "đang hoạt động"/"mất kết nối" thật.
4. **Thanh tab dưới**: chạm vào giữa ô tab (y ≈ 2276 trên màn 2400) lần đầu không chuyển màn, phải chạm vào chữ. Cả ô (biểu tượng + chữ) phải nhận chạm.
5. **"Hỗ trợ và góp ý … Cần đăng nhập"** hiện khi đã đăng nhập: sửa dòng phụ theo trạng thái thật.
6. **Đặt mặc định Server App/Server Kính** trỏ đúng stack demo nếu đang sai (kiểm BuildConfig/cài đặt hiện tại; điện thoại ra Internet qua
   `https://app.visioncare-host.uk` → AB và `https://api.visioncare-host.uk` → VH). Không đổi nếu đã đúng.

## Bàn giao
Ghi `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-A2.md` (nếu Write bị chặn thì đưa nội dung trong câu trả lời). Trả lời ≤ 5 dòng.
