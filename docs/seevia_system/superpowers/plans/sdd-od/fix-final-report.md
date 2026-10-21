# Báo cáo sửa cuối (commit cedaa8a)
Sửa: live/hazard_predict.py (cổng nhoè EMA 0,35, tối đa 2 khung chặn; góc cúi trung vị 31 mẫu kẹp [-0,02; 0,10]; bỏ detection box không hữu hạn), live/hazard_track.py (reset khi nhảy > 1 s; xoá track x/P không hữu hạn), live/hazard.py (HAZARD_LOGIC lạ -> warning một lần + area), tests/test_hazard_predict.py (+6 test).
Test: trước 39 test hazard_predict pass; sau pytest -q toàn bộ 690 passed, 2 skipped. Không sửa 4 file test cấm.
