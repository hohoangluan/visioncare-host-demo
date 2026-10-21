# Review lại phạm vi đợt sửa cuối (20decde..cedaa8a)

pytest tests/test_hazard_predict.py: 45 passed.

| Mục | Kết luận | Lý do (file:dòng) |
|---|---|---|
| Important 1 cổng nhoè | ADDRESSED | hazard_predict.py ~L105-117: EMA α0,1 khởi tạo bằng khung đầu, cập nhật trước khi so, nhoè <0,35·EMA, R×4, tối đa 2 khung chặn rồi khung 3 cho tạo; có 2 test đúng tên |
| Important 2 góc cúi | ADDRESSED | hazard_predict.py _learn_pitch: deque 31, trung vị, kẹp [−0,02;+0,10], giữ điều kiện lấy mẫu |
| Minor 4 khoảng trống | ADDRESSED | hazard_track.py L89: t−t_prev > DT_MAX(1,0) -> reset() trước update |
| Minor 5 NaN | ADDRESSED | box không hữu hạn bị lọc ở assess; track x/P không hữu hạn bị xoá (hazard_track.py L133) |
| Minor 7 HAZARD_LOGIC lạ | ADDRESSED | hazard.py _logic(): warning một lần + area |

## Lỗi mới
- Critical: 0. Important: 0.
- Minor (không chặn): PredictTracker không có reset(); EMA nhoè/deque góc cúi/_blur_run chỉ sạch khi tạo tracker mới. Nếu chỗ gọi chỉ gọi tracks.reset() thì giữ trạng thái cũ (vô hại, vì là thống kê phiên). Khung nhoè dài bị tụt EMA chậm (α0,1) nên cảnh đổi sáng đột ngột có thể coi nhoè vài khung, đã giới hạn 2 khung chặn.
- HAZARD_LOGIC=area: không đổi hành vi (chỉ qua _logic, giá trị hợp lệ trả nguyên). Không có đường làm Z xa hơn (kẹp dưới −0,02) hay chặn cảnh báo quá 2 khung.
