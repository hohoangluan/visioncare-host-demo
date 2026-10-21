# Task 4 — báo cáo: bộ sinh kịch bản VN + tách dev/test

Trạng thái: xong. Sửa: `evaluations/bench/hazard_scenarios.py`, `bench/test_hazard.py`, mới `bench/fixtures/c1b_legacy_hash.json`. Không đụng file nào khác, không đụng VH.

## Đã làm
- Lưu fixture hash TRƯỚC khi sửa (sha256 trên hộp làm tròn 12 chữ số; 24 loại x seed 0,1,2).
- Test viết trước: `test_legacy_split_bitwise`, `test_dev_test_disjoint_and_wider`, `test_sudden_t_visible`, `test_safe_labels_hold`, `test_times_monotonic` (+ `test_split_type_sets`, `test_ego_and_motion_noise`).
- `generate(type, seed, split="legacy", cam=None)`, `generate_all(n_seeds, types, split)`. `split=legacy` đi đường cũ nguyên văn (`_generate_legacy`, cùng chuỗi rng); `Camera.project` chỉ thêm tham số `dx, dy` mặc định 0.0 (không đổi bit).
- `Scenario` thêm `t_visible_frame, times, ego, group, split, params` (đều có default; `frames/Z/X` giữ nguyên nên `hazard_logic.simulate` không đổi). `params` = tham số thật đã lấy mẫu (person_h, cam_h, hfov, pitch_deg).
- Dev/test: quỹ đạo dựng liên tục theo thời gian (lưới 10 ms) rồi lấy mẫu tại mốc khung; 9 loại mới + biến thể `+gait/+yaw/+blur` cho 9 loại mới và 6 loại cũ có nhiễu => `ALL_TYPES` = 78 (legacy = đúng 24). Loại ngoài split -> ValueError.
- Seed hiệu dụng lưu vào `Scenario.seed` (dev 1000+s, test 2000+s).

## Lựa chọn brief để ngỏ
- `gait`: "2 % khung / ±5 %" hiểu là ảnh trượt dọc biên độ 2 % chiều cao ảnh (test 3 %) + hộp phình/xẹp ±5 % (test ±8 %), sin 2 Hz pha ngẫu nhiên.
- `yaw`: trượt ngang thật 8 % (12 %) bề rộng, sin 0,3 Hz; `ego.shift` = thật + N(0; 1 %/2 %). Không yaw: shift = N(0; σ).
- `blur`: tại mỗi đỉnh nhún 2 Hz, xác suất 0,25 mở một chuỗi 2–4 (test 2–6) khung MẤT HẾT hộp, blur đo U(10,25); khung nét blur U(80,200). `+blur` không kèm bước nhún dọc (độc lập với `+gait`).
- dt test: U(0,10; 0,20) mỗi bước, 5 % khung rớt (thời gian trôi, không phát khung); khung đầu luôn có. Áp cho mọi loại ở test.
- Legacy: `ego` sinh từ rng riêng (`[idx, seed, 7]`) để không đụng chuỗi hộp; shift N(0; 1 %), blur nét; `params` danh nghĩa.
- Chiều cao người: dev N(1,65; 0,08); test 10 % trẻ N(1,1; 0,05) còn lại N(1,65; 0,10); áp cho mọi vật `person`. Camera cao/HFOV/độ cúi lấy mẫu, truyền `cam=` thì dùng camera đó.
- Nhãn loại mới: rejection sampling theo nhãn khai báo (nguy hiểm: vùng nguy hiểm kéo dài >= 0,3 s trên lưới mịn; an toàn: 0 s), rồi kiểm lại nhãn trên chuỗi đã lấy mẫu (dựng lại nếu khung rớt làm mất). Nhãn cuối vẫn do hình học quyết định.
- `t_visible_frame` = khung đầu có hộp của vật chính (vật đầu tiên trong danh sách); legacy cũng tính như vậy.
- Chi tiết dựng: `sudden_person_behind_car` thêm một xe đỗ ở X=±2,0 làm vật che (cùng khung với người); `parked_motorbike_row` một phía, mỗi xe X riêng U(0,9;1,5); `same_dir_person` đúng 30 s (240 khung dev); `approach_then_stop` chọn ngẫu nhiên person/pole/bench/car.

## Lệch so với brief (cần biết)
1. `sudden_person_behind_car`: Z lộ ra lấy U(3,5; 4,5) thay vì [3,5; 5,5]. Lý do: người dùng 1,2 m/s thì Z=5,5 mất (5,5-2)/1,2 = 2,9 s tới t_danger, vi phạm chính test "t_danger - t_visible <= 2,5 s". Max đo được 2,13 s (dev), 2,07 s (test). Nếu muốn giữ [3,5; 5,5] thì phải nới test lên 3,0 s hoặc cho người đi tới 0,5 m/s.
2. `cross_cut_person`: "cắt chéo lối ở Z 3–4" nếu người đi xuyên qua lối thì hầu như không bao giờ có Z < 2 trong lúc |X| < 0,6 (nhãn thành an toàn). Dựng: người đi chéo 0,9–1,5 m/s và DỪNG lại trong lối (X ngẫu nhiên ±0,3) khi qua tâm ở Z = 3–4 m => nguy hiểm.
3. `sudden_motorbike_alley`: xe lạng vào lối rồi giữ X ≈ 0 (không thì tuỳ seed bay qua lối). Do vZ=-3,2 nên vùng nguy hiểm chỉ 0,47 s; vì rejection nên Z lộ ra hiệu dụng ≳ 4,4 m.

## Kết quả
- `pytest bench/test_hazard.py -q`: 15 passed (8 cũ + 7 mới), ~3,7 s.
- Quét thêm: 78 loại x 20 seed x dev/test không lỗi, `t_visible_frame` luôn khác None, `times` luôn tăng nghiêm ngặt, 78x20x2 khung sinh trong ~5 s.
- Legacy chạy lại `python -m bench.hazard_logic --seeds 50 --out <scratch>/c1b_legacy`: kịp thời 8,3 % (n=600), báo nhầm 0,5436/phút (50 bíp / 91,98 phút), cả 4 đối chứng True — trùng từng chữ số với lần chạy trước khi sửa (`c1b_base`).
- Một dòng nhật ký đã ghi cuối `docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md`.
