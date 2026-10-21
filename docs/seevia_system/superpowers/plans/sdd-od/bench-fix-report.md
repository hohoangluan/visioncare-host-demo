# Báo cáo sửa bàn đo C1b (bench-fix)

Trạng thái: XONG (VH commit f270b38 "đuôi nhả" đã có nên release_s đã nối và chạy được).

## Thay đổi
- hazard_scenarios.py: pole dev/test = kind "pole", group "static" (legacy giữ parking_meter, hash legacy không đổi; tra group không KeyError).
  Thêm `sidestep_avoid` (+gait, +yaw), group "release"; `Scenario.t_clear_frame`; hàm `t_clear()` (dùng cho pass_by_person, cross_person, cross_motorbike, sidestep_avoid và biến thể).
  sidestep_avoid + biến thể được nối CUỐI ALL_TYPES để chỉ số/seed rng của mọi loại cũ không đổi.
- hazard_logic.py: `check_reverse(rec, k_ok)` chỉ đếm bíp mức >= 2 sau khung đầu tiên Z thật > 3 m (reverse_scenario đảo cả Z/X); chỉ số `tail_after_clear_s` (p50/p90, % còn bíp sau +1 s) trong score/summarize; group release ra khỏi số báo oan; PredictPipeline truyền release_s vào AntiAnnoy.
- hazard_grid.py: thêm chiều release_s {0,25; 0,5; 1,0}; BỎ coast=2 (giữ 3) -> lưới 324 cấu hình (108 x 3), không phải ~216 (bản 216 x 3 = 648 chỉ giảm một nửa). Luật chọn thêm tail p90 <= 1,0 s trên dev (chỉ ở select, không ở kiểm test). `to_params` báo lỗi nếu VH thiếu release_s. config_stats có tail_p90/p50/pct và tail theo loại. HAZARD_PREDICT.md thêm mục 7 "Kêu thừa sau khi thoát nguy hiểm" (bảng theo loại); mục cũ đánh số lại.
- test_hazard.py: 27 test pass (gồm legacy bitwise); thêm test pole theo split, reverse_time cửa sổ mới, t_clear của sidestep, tail metric bản ghi giả, ràng buộc tail trong select, lưới 324.

## Smoke
`--split dev --seeds 3 --types sidestep_avoid,cross_person`, chạy hết 324 cấu hình trong 2,4 s: selected=null (bình thường, không có kịch bản nguy hiểm nên không có kịp thời; mọi cấu hình vi phạm tail p90 ~2,6 s > 1 s). Baseline tail p90 = 0 (logic cũ không có t_clear sau bíp trong mẫu này). Không chạy --split test, không chạy lưới dev đầy đủ.

## Lưu ý
- Trong smoke nhỏ, tail p90 giống nhau giữa release_s 0,25/0,5/1,0 (2,575 s): đuôi 2,6 s đến từ tracker/vote chứ chưa chắc từ đuôi nhả; cần xem trên lưới dev đầy đủ.
- Đối chứng reverse_time chưa chạy ở quy mô đầy đủ (chỉ test đơn vị).
