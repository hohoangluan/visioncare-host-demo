# Brief: đợt sửa cuối nhánh od-du-doan (sau review cuối)

Worktree: SeeVia_system/vh-od (nhánh od-du-doan, HEAD 20decde). Đọc review: docs/superpowers/plans/sdd-od/final-review.md (mục Important 1–2, Minor 4, 5, 7).
Quyết định của controller (làm ĐÚNG như sau, ledger Ruling 24–26):

1. **Cổng nhoè tương đối (Important 1).** Bỏ ngưỡng tuyệt đối `_BLUR_MIN=30` làm điều kiện duy nhất. PredictTracker giữ EMA độ nét của phiên (α = 0,1, khởi tạo bằng khung đầu tiên có Ego). Khung nhoè ⇔ `blur < 0,35 · EMA` (EMA cập nhật bằng mọi khung, trước khi so). Khung nhoè: phương sai đo ×4 như hiện tại, `allow_new=False` — NHƯNG tối đa 2 khung liên tiếp bị chặn tạo track; khung thứ 3 liên tiếp luôn `allow_new=True`.
   Test: `test_low_texture_scene_still_creates_tracks` (mọi khung blur=10 cố định, người đi tới từ Z=8 → có track và mức ≥ 2 trước Z<3,8); `test_blur_burst_blocks_at_most_two_frames`.
2. **Góc cúi (Important 2).** `_learn_pitch`: lưu 31 mẫu gần nhất (deque), `pitch_rad` = trung vị; kẹp bất đối xứng [−0,02; +0,10] rad. Giữ điều kiện lấy mẫu hiện có (Z ≥ _PITCH_MIN_Z, có cả hai nguồn).
   Test: `test_pitch_children_do_not_push_far` (50 % hộp là người cao 1,15 m, góc cúi thật 0 → pitch_rad ≥ −0,02 và Z ở 3 m của người 1,65 m không xa hơn thật quá 5 %); `test_pitch_estimate_converges` vẫn pass.
3. **Minor 4:** mốc thời gian nhảy > 1,0 s so với khung trước → xoá mọi track (TrackSet.reset) trước khi cập nhật. Test `test_long_gap_resets_tracks`.
4. **Minor 5:** detection có toạ độ không hữu hạn → bỏ qua (không vào estimate/match); track có `x`/`P` không hữu hạn sau cập nhật → xoá. Test `test_nan_box_ignored`.
5. **Minor 7:** `make_tracker()/make_anti()` — `HAZARD_LOGIC` không thuộc {"area","predict"} → `logger.warning` một lần + chạy area. Test bằng caplog.

Bắt buộc: `pytest -q` toàn bộ pass; không sửa tests/test_v2_units.py, test_v2_api.py, test_modes_split.py, test_debug_frames.py; HAZARD_LOGIC=area không đổi hành vi.
Commit MỘT lần: `git -c user.name=LuanLuKim -c user.email=kimluanlu95@gmail.com commit`, message "vật cản: sửa sau review cuối — cổng nhoè tương đối, góc cúi trung vị kẹp bất đối xứng, reset khi mất khung lâu, chặn NaN", dòng cuối `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
Không dispatch subagent. Report: docs/superpowers/plans/sdd-od/fix-final-report.md (file đã sửa, test trước/sau, commit). Trả ≤ 5 dòng.
