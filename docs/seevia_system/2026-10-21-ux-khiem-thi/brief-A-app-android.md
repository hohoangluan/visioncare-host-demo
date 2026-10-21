# Brief A — App Android SeeVia: dễ dùng cho người khiếm thị + người thân, điều khiển bằng giọng nói

Repo: `SeeVia_system/app-demo-backend` (AB), app ở `mobile/`, nhánh `app-giao-tiep` (mốc ad59bd6). Làm thẳng trên checkout này, commit theo từng mục
(kết commit bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).

## Người dùng (người dùng đã chốt)
MỘT app, mọi người là user bình thường: người khiếm thị (dùng TalkBack, có thể đeo kính SeeVia) và người thân (sáng mắt) dùng CÙNG giao diện —
KHÔNG làm màn chọn vai/chế độ riêng. Vì vậy mọi màn phải vừa đẹp, rõ cho người sáng mắt (ban giám khảo sẽ xem), vừa dùng trọn vẹn bằng TalkBack
và bằng giọng nói. Dùng hằng ngày → tin cậy, ít bước, phản hồi rõ.

## Bắt buộc trước khi sửa UI
Gọi skill `ui-ux-pro-max` (Skill tool) để dẫn dắt mọi quyết định giao diện/accessibility. Nhận diện: navy `#041466` chủ đạo, Montserrat
(Be Vietnam Pro cho thân chữ nếu dấu tiếng Việt cỡ nhỏ kém) + Pinyon Script chỉ cho wordmark; logo ở `SeeVia_system/ui/logo/`.
Đọc `AB/docs/superpowers/specs/2026-10-20-app-dot2-design.md` mục "Ẩn màn hình" và "Nhận diện" (chỉ 2 mục đó).

## Việc
A1. Màn chính (Overview) dễ dùng: hàng nút lớn cho việc hằng ngày — Gọi người thân, Tin nhắn, Kính (kết nối/pin), Khẩn cấp (luôn có xác nhận,
    không bấm nhầm), Nói lệnh. Nút ≥ 64dp cao, chữ ≥ 18sp, tương phản AA, không truyền thông tin chỉ bằng màu.
A2. Ẩn màn không có endpoint server (album, cộng đồng, họp, dịch… — kiểm từng màn trong `AppNavigation.kt` xem có gọi API thật không) bằng
    object `FeatureFlags`, giữ code. Giám khảo không được thấy màn chết/giả.
A3. Rà TalkBack MỌI màn còn hiện (Auth, Overview, Glasses, Care/người thân, Chat, Call, Safety, Profile, Readiness, Guide, Support, FunctionTest,
    ActivityLog, Display, Features…): `contentDescription` cho mọi icon/nút chỉ có icon (icon trang trí = null), gộp semantics cho thẻ
    (`Modifier.semantics(mergeDescendants = true)`), `heading()` cho tiêu đề, `role`, `stateDescription` cho công tắc/trạng thái,
    `liveRegion` cho trạng thái cuộc gọi / tin đến / kết quả kiểm tra, thứ tự focus hợp lý, vùng chạm ≥ 48dp, cỡ chữ hệ thống 200% không vỡ,
    trường nhập có label, lỗi được đọc. Màn Call: nút Nghe/Từ chối/Kết thúc rất lớn, đọc rõ tên người gọi và trạng thái.
A4. Điều khiển app bằng giọng nói: nút "Nói lệnh" (Overview + có mặt nhanh ở các màn chính) dùng `android.speech.SpeechRecognizer`
    (`vi-VN`, KHÔNG thêm thư viện), phản hồi bằng `TextToSpeech` + `announceForAccessibility`. Lệnh tối thiểu: "gọi <tên>",
    "nhắn <tên> <nội dung>", "đọc tin nhắn" (đọc tin chưa đọc), "kính thế nào"/"pin kính", "khẩn cấp" (hỏi xác nhận bằng giọng: "có"/"không"),
    "mở <màn>", "trợ giúp" (đọc danh sách lệnh), "dừng". Tên khớp với alias người thân/liên hệ có sẵn trong app (khớp không dấu, gần đúng).
    Hoạt động cả khi TalkBack bật (double-tap nút). Không nghe được/không hiểu → đọc lại điều nghe được + gợi ý, không im lặng.
    Bộ phân tích lệnh là lớp Kotlin thuần, có test JVM đầy đủ (kể cả tên có dấu/không dấu, câu sai). Quyền `RECORD_AUDIO` xin đúng lúc, có giải thích.
A5. Rà chữ hiển thị: tiếng Việt tự nhiên, không "Your Eyes" sót lại, thông báo lỗi nói rõ phải làm gì.

## Ràng buộc
- Không thêm thư viện ngoài danh sách đã duyệt (OkHttp, WorkManager + những gì đang có). Không đổi `applicationId`.
- Hai file Firebase (`mobile/app/google-services.json`, `~/.config/seevia/firebase-adminsdk.json`) bí mật: không commit/copy/in.
- Build: trong `mobile/`: `JAVA_HOME=~/jdk-21.0.12.1+1 ANDROID_HOME=~/android-sdk ./gradlew test assembleDebug lint` phải xanh, lint 0 error.
- Không đụng `server/` trừ khi thật cần (nếu cần, test AB trên Postgres thật).
- Không có emulator. Nếu controller báo có thiết bị adb thì có thể `adb install -r` + `uiautomator dump` để kiểm; không thì chỉ JVM test.

## Bàn giao
Báo cáo `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-A.md` (việc, commit, màn đã ẩn, đường APK, danh sách ca thử tay TalkBack cho người dùng).
Trả lời controller ≤ 5 dòng.
