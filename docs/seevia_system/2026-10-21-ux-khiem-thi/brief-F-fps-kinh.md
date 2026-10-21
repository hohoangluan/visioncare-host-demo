# Brief F — Tăng FPS camera kính (ESP32-S3) trong mức chịu được

Repo VH `SeeVia_system/visioncare-host-demo`, nhánh `app-giao-tiep`. Commit kết bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
KHÔNG restart VH 18888 (controller làm). GPU: chọn GPU trống nhất (`nvidia-smi`), không lùi CPU. Python `~/.venvs/seevia/bin/python`.

Hiện tại (`docs/FIRMWARE_ENDPOINTS.md`, `live/protocol.py: cam()`): đọc chữ trực tiếp VGA 5 fps q12; cảnh báo vật cản QVGA 8 fps q15;
trần server `LIVE_MAX_FPS=15`, `LIVE_MAX_FRAME_BYTES=300KB` (`config.py`, bỏ khung trong `lanes/ocr_live.py`, `live/device_session.py`).

## Nguyên tắc (người dùng chốt)
KHÔNG tăng fps nếu không đem lại giá trị đo được. Làm mục 3 (đo) TRƯỚC. Chỉ đổi mặc định khi trễ từ lúc vật cản xuất hiện tới lúc cảnh báo (p50) giảm
≥ 100 ms, hoặc tỉ lệ đọc chữ trực tiếp thành công tăng rõ, mà không làm server tụt. Không đạt → giữ nguyên 8/5 fps, chỉ báo số đo; mục 1 khi đó
chỉ đưa fps thành cấu hình với mặc định CŨ (giữ hành vi), mục 4 vẫn làm nếu tìm ra lỗi thật.

## Việc
1. Đưa fps/size/quality từng chế độ thành cấu hình: `LIVE_NAV_FPS`, `LIVE_OCR_FPS` (mặc định theo kết quả đo, xem nguyên tắc), giữ size/quality cũ;
   mọi chỗ gửi `cam(...)` dùng cấu hình. Cập nhật `docs/FIRMWARE_ENDPOINTS.md` (bảng + khuyến nghị firmware: `fb_count=2`, `CAMERA_GRAB_LATEST`,
   bỏ khung khi gửi chậm thay vì xếp hàng).
2. Kiểm server theo kịp và KHÔNG xếp hàng: đọc đường đi khung live (nav/hazard và ocr_live) — xác nhận chỉ xử lý khung MỚI NHẤT, khung đến khi đang bận
   thì thay khung chờ (không queue tích luỹ). Nếu đang queue thì sửa thành "giữ khung mới nhất" + test.
3. Đo: thời gian xử lý mỗi khung của mô hình vật cản và OCR trực tiếp trên GPU (p50/p90, ≥ 200 khung, ảnh QVGA/VGA thật trong `storage/` hoặc
   `tools/benchmarks`), và giả lập luồng 15 fps nav / 10 fps ocr trong 30 s: số khung xử lý, số khung bỏ, trễ từ lúc nhận khung tới lúc có cảnh báo
   (p50/p90) so với 8 fps / 5 fps cũ. Chỉ giữ mặc định mới nếu trễ cảnh báo không tệ hơn và server không tụt (CPU/GPU). Không thì chọn mức cao nhất
   còn đạt, ghi lý do.
4. Rà logic đúng: cảnh báo vật cản không lặp liên tục khi fps tăng (khử lặp/hysteresis theo thời gian chứ không theo số khung) — kiểm các ngưỡng đang
   tính theo "số khung" có bị đổi nghĩa khi fps đổi không; nếu có, đổi sang theo thời gian + test.

pytest toàn bộ VH xanh. Báo cáo `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-F.md` (nếu Write bị chặn thì đưa trong câu trả lời). Trả lời ≤ 5 dòng.
