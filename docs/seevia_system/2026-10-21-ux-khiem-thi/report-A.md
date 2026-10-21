# Report A — App Android SeeVia (2026-10-21)

(Controller chép tóm tắt từ hand-back của agent A; agent không ghi được file.)

Repo `app-demo-backend`, nhánh `app-giao-tiep`. Build `test assembleDebug lint` xanh: 288 test JVM, lint 0 error.
APK: `app-demo-backend/mobile/app/build/outputs/apk/debug/app-debug.apk`.

## Commit
- `56f6a83` nhận diện navy #041466, icon/wordmark từ `ui/logo`, thành phần dùng chung (ChoiceChip, ToggleRow, SecondaryButton, PanelCard), FeatureFlags.
- `14bf410` A1 màn chính nút lớn, A2 ẩn màn không có server, A4 điều khiển bằng giọng nói (`voice/`: VoiceParser, VoiceDialogue, VoiceViewModel).
- `8b2d89d` A3 TalkBack mọi màn, A5 chữ hiển thị, `core/UserErrors.kt`.
- `0972d89` tên app "SeeVia", kênh thông báo "Lệnh từ kính".

## Điểm chính
- Màn chính: Nói lệnh, Gọi người thân, Tin nhắn, Kính, Khẩn cấp (luôn hộp xác nhận, "Không" đứng trước), Sẵn sàng, Xem thêm. Ô ≥ 88dp, chữ 18sp theo cỡ chữ hệ thống.
- Ẩn (FeatureFlags, giữ code): Album, Cộng đồng (còn 4 tab), Biên bản họp, Dịch thuật.
- Giọng nói: SpeechRecognizer vi-VN; nhắn tin + khẩn cấp luôn đọc lại và hỏi có/không; không nghe rõ 2 lần thì huỷ. TalkBack tắt → TextToSpeech; bật → announceForAccessibility (tránh hai giọng chồng nhau).
- Font: Be Vietnam Pro toàn app (chưa dùng Montserrat).
- Pin kính: server không có dữ liệu → app nói "chưa nhận được thông tin pin".

## Cần xác nhận / rủi ro
- Màn "Tính năng" còn "Tìm đồ vật thất lạc" và "Trợ lý Chatbot AI" — kính CÓ làm (`find`, `chat` ở VH) → giữ.
- Chưa thử trên máy thật: giọng nói vi-VN, TalkBack, cỡ chữ 200%.
- Gọi bằng giọng từ app chỉ theo đường gọi hiện có (người thân gọi chủ kính); gọi ngược chủ kính → người thân chưa có API.

## Ca thử tay TalkBack
16 ca (màn chính, Nói lệnh/trợ giúp/gọi/nhắn/khẩn cấp có-không, đọc tin, kính/pin, mở màn, mất mạng/từ chối micro, cuộc gọi đến, chat đọc tin mới,
hồ sơ cỡ chữ/công tắc, cỡ chữ hệ thống lớn nhất, nút Quay lại lịch sử, 4 tab, giao diện cho giám khảo). Controller chạy trên máy thật qua adb.
