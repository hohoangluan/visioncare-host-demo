# Brief: sửa bàn đo C1b — cột "pole", đối chứng reverse_time, kịch bản né + chỉ số kêu thừa sau khi thoát

Thư mục: SeeVia_system/evaluations (không phải git). File: bench/hazard_scenarios.py, bench/hazard_logic.py, bench/hazard_grid.py, bench/test_hazard.py.
Đọc trước: docs/superpowers/plans/sdd-od/task-4-report.md và task-5-report.md (bộ sinh + chấm điểm hiện tại), spec
docs/superpowers/specs/2026-10-21-vat-can-du-doan-quy-dao-design.md §5–7.
VH để import: SEEVIA_VH_DIR=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-od (một agent khác đang sửa nó song song:
thêm `AntiAnnoy(release_s=…)`, `PredictParams.release_s`, sửa ước lượng Z khi đáy hộp bị cắt). Không sửa VH.

## 1. Ruling 17 — cột
Split dev/test: vật "pole" dùng kind `"pole"`, group `"static"` (lớp của model fine-tune; bảng chiều cao VH có pole). Split legacy GIỮ
`parking_meter` — `test_legacy_split_bitwise` phải vẫn pass. Lookup group không được KeyError khi kind không có trong `hazard._CLASSES` COCO.

## 2. Ruling 17 — reverse_time
Chỉ đếm bíp mức ≥ 2 SAU khung đầu tiên mà Z thật > DANGER_Z + 1,0 m (bỏ "1,0 s đầu"). Pass = 0 bíp. Cập nhật unit test của đối chứng này.

## 3. Ruling 18 — yêu cầu người dùng: "thoát nguy hiểm thì kêu thêm chút rồi dừng"
- Kịch bản mới `sidestep_avoid` (group `"release"`, nhãn an toàn theo hình học): người dùng đi 1,2 m/s tới người/xe máy đứng yên trong lối
  (Z0 ∈ [10; 14], X ∈ [−0,2; 0,2]); khi Z ∈ [4,5; 5,5] người dùng bước né sang một bên 1,0–1,2 m trong 1,0 s (X của vật dịch ra ±1,0–1,2) rồi đi tiếp qua.
  Ghi `t_clear_frame` = khung đầu tiên |X thật| > LANE_HALF + 0,2 m. Thêm biến thể `+gait`, `+yaw` ở dev/test như các loại khác.
- Với `pass_by_person`, `cross_person`, `cross_motorbike` (và biến thể): `t_clear_frame` = khung đầu tiên vật đã đi qua (Z < 0,5 hoặc |X| > LANE_HALF + 0,2 m
  sau khi từng < LANE_HALF + 0,2 m); không có thì None.
- Chỉ số mới `tail_after_clear_s` = (khung bíp cuối − t_clear_frame)·dt, chỉ trên kịch bản có t_clear và có bíp; 0 nếu bíp cuối trước t_clear.
  Báo p50/p90 và % kịch bản còn bíp sau t_clear + 1,0 s. Group `"release"` LOẠI khỏi mọi số báo oan của luật chọn (như group control).
- Lưới: thêm chiều `release_s` ∈ {0,25; 0,5; 1,0} (truyền vào AntiAnnoy qua PredictParams.release_s; nếu VH chưa có tham số đó thì dừng, báo BLOCKED).
  Lưới thành 648 cấu hình — được phép GIẢM chiều khác để giữ ~216: bỏ `coast` = 2 (giữ 3). Ghi rõ trong report.
- Luật chọn thêm ràng buộc (chốt trước): `tail_after_clear_s` p90 ≤ 1,0 s trên dev.
- HAZARD_PREDICT.md thêm mục "Kêu thừa sau khi thoát nguy hiểm" (bảng theo loại).

## Kiểm
- bench/test_hazard.py pass hết (kể cả legacy bitwise); thêm test: pole kind theo split, reverse_time cửa sổ mới, t_clear của sidestep, tail metric (bản ghi giả).
- Smoke dev 2 loại × 3 seed chạy hết lưới. KHÔNG chạy --split test, KHÔNG chạy lưới dev đầy đủ.
- Không dispatch subagent. Report: docs/superpowers/plans/sdd-od/bench-fix-report.md; trả ≤5 dòng.
