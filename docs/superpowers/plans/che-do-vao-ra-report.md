# Báo vào/ra chế độ — báo cáo (nhánh `che-do-vao-ra`)

## Đã làm
- `live/device_session.py`: hằng `NAV_PAUSED` "Tạm tắt cảnh báo.", `NAV_RESUMED` "Bật lại cảnh báo." (+ `STATIC_SPEECH`);
  `_announce`/`_say_status` nói câu ngắn ở task riêng (giữ `_audio_lock` trọn câu, FIFO, lỗi chỉ ghi log, huỷ khi `shutdown`);
  `_start_live` nói NAV_PAUSED khi OCR live thay nav live (tạo task trước `_launch_live` nên tới khoá audio trước câu đọc chữ);
  `_resume_nav` nói NAV_RESUMED (đi qua cả đường cúp máy `_on_call_state` -> `_resume_nav`);
  `drop_suspended_nav()` xoá `_nav_suspended`.
- `pipeline/final_router.py::_lane_c` (`alert_off`): gọi `session_for(device).drop_suspended_nav()` (nhập muộn `live.device_session`).
- `lanes/ocr_live.py`: `EXIT_READ` "Thoát đọc chữ.", `EXIT_MONEY` "Thoát đọc tiền." (+ `STATIC_SPEECH`); nói SAU nội dung, TRƯỚC khung `end`,
  chỉ khi không `box.closed`/`session.closed`. Nhánh `image is None` (hết trần, không ảnh) nói EXIT_READ.
- `pipeline/phrases.py::_speech_modules`: thêm `ocr_live`, `device_session` để câu mới được dựng sẵn (không đụng `app.py`).
- Test: `tests/test_che_do_vao_ra.py` (18 test); `tests/test_money_retry.py`: `_Box` tách lời báo "Thoát đọc tiền." khỏi `said` (7 test cũ chỉ kiểm câu nội dung).

## Lệch brief / lưu ý
- Nối STATIC_SPEECH qua `phrases._speech_modules` thay vì `app.py`/`final_router.STATIC_SPEECH` (tránh vòng nhập, mọi module có câu cố định cùng một chỗ).
- Lời báo thoát đứng TRƯỚC `end` (audio đã gửi hết rồi mới `end`); nhánh không ảnh chỉ nói, KHÔNG gửi `end` (giữ nguyên giao thức cũ).
- Lượt mới huỷ OCR giữa chừng vẫn dựng lại nav (hành vi cũ) và vẫn nói "Bật lại cảnh báo." (cảnh báo thật sự được bật lại); chỉ lời báo THOÁT OCR là im.
- Không cần sửa `_live_session` cũ sau khi live xong (vẫn trỏ phiên đã đóng, như trước).
- `ocr_live.run` dùng chung với `WS /v2/live` cũ: lời báo thoát cũng phát ở đó.
