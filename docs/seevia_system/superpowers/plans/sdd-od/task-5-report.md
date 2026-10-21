# Task 5 — báo cáo: chấm điểm, đối chứng, lưới + luật chọn, báo cáo

Trạng thái: DONE_WITH_CONCERNS (code + test xong, tích hợp với commit Task 3 `9264fea` đã chạy; 2 đối chứng predict FAIL ở smoke, xem Concerns).

## Đã làm
- `bench/hazard_logic.py`:
  - `PredictPipeline(params)` (+ `predict_maker`), `frame(k, dets, t=None, ego=None)`; `BaselinePipeline`/`Dead`/`AlwaysCritical` nhận và bỏ qua `t`, `ego`. Đồng hồ AntiAnnoy = `scn.times[k]`, ego = `Ego(*scn.ego[k])`, `urgent` truyền vào `AntiAnnoy.step`.
  - `simulate` truyền `t`/`ego`; bản ghi thêm `group, t_visible_frame, times, beep_dir, beep_z, beep_x`.
  - `score`: lead dùng `times` thật (fallback 125 ms); nhóm sudden thêm `max_lead_s, impossible (td-tv<1 khung), reveal_delay_s, timely_sudden`, `timely` = định nghĩa sudden (bíp mức>=2 trước t_danger VÀ <=2 khung từ t_visible); `dir_correct` (bíp mức>=2 đầu tiên so với phía theo X thật của vật chính tại khung bíp: |X|<=0,6 = center).
  - `summarize`: loại `impossible` khỏi mẫu số (đếm `n_impossible`), thêm `dir_correct_rate`, `reveal_delay_s`, `by_group`.
  - `run_controls(n, predict_params=None)`: thêm `shuffle_frames` (xáo khung+ego của kịch bản nguy hiểm dev, giữ `times`; pass nếu kịp thời xáo <= 50 % gốc) và `approach_then_stop` (0 bíp mức 3), chỉ khi có `predict_params`.
- `bench/hazard_grid.py` (mới): lưới 216 cấu hình (`make_grid`), `config_stats`, `violations`, `select` (luật §6, hoà trong 1 điểm -> báo oan thấp hơn -> trễ thuật toán thấp hơn; không ai thoả -> `None`), `pareto`, `nfs_probe`/`write_text`/`write_json` (probe 5 MB + fsync + kiểm kích thước khi file > 64 KB, đọc lại JSON), `render_report`.
- `bench/test_hazard.py`: thêm 6 test (sudden timely/impossible, selection rule, Pareto, baseline bỏ qua extra, báo cáo "KHÔNG ĐẠT"/null, NFS probe). 21 passed (15 cũ + 6 mới).

## CLI
```
SEEVIA_VH_DIR=.../vh-od python -m bench.hazard_grid --split dev  [--seeds 50] [--procs 8] [--types a,b] [--out DIR] [--report PATH]
SEEVIA_VH_DIR=.../vh-od python -m bench.hazard_grid --split test --config cfg.json|'{json}' [--dev-grid FILE] [--seeds 50] [--procs 8]
```
- `--config` nhận tham số trần, hoặc file lưới dev (lấy `selected.config`). Dev: ghi `results/hazard/predict_grid_dev_<ts>.json` (mọi cấu hình + vi phạm từng cấu hình + Pareto + `selected`/null), in `selected = null` gọn khi không ai thoả (và ghi báo cáo "KHÔNG CHỌN ĐƯỢC" nếu chạy đủ). Test: ghi `predict_test_<ts>.json` + `reports/HAZARD_PREDICT.md`; vi phạm báo oan -> dòng đầu **KHÔNG ĐẠT** + loại vi phạm.
- Chạy thử một phần (có `--types` hoặc `--seeds < 50`) KHÔNG ghi `reports/HAZARD_PREDICT.md` trừ khi truyền `--report`.
- Tối đa 8 tiến trình (fork, kịch bản dùng chung qua bộ nhớ cha), CPU.

## Smoke (2 loại motorbike_charge + far_static_car x 3 seed, procs 8)
- Dev: 216/216 cấu hình chạy xong trong 2,6 s, JSON hợp lệ, selected hợp lệ (mọi cấu hình thoả vì mẫu quá nhỏ, 216 điểm Pareto trùng nhau/hoà — không có ý nghĩa thống kê).
- Test (chạy riêng một lần, 6 kịch bản): chạy được, JSON + báo cáo sinh đủ 8 mục.
- Tốc độ ước tính cho lưới đủ: 216 cfg x ~3.900 kịch bản dev (78 loại x 50) ≈ 842k mô phỏng; smoke ~ 0,02 s/kịch bản/cfg ⇒ vài giờ trên 8 tiến trình. Controller nên tính trước.

## Concerns
1. Smoke test split với cấu hình chọn từ lưới 6 kịch bản (không đại diện): hai đối chứng predict FAIL — `approach_then_stop`: 18 bíp mức 3 trên 3 seed (vật dừng ở Z=3 m, cấu hình tte_l3=2,0, new_near=0, l3_vote=1, tức là cấu hình hung hăng); `shuffle_frames`: kịp thời gốc 0,75, sau xáo 1,0 (xáo đưa khung gần lên sớm nên bíp sớm = "kịp thời" — định nghĩa kịp thời không phạt bíp ở khung xáo; đối chứng này có thể cần chỉ số khác, ví dụ so lead hoặc báo oan trên kịch bản an toàn xáo). Chưa kiểm trên cấu hình dev thật; controller cần xem lại ở lần chạy đủ.
2. p90 `assess+step` trong lưới đo dưới 8 tiến trình dùng chung nên có thể lệch lên; ngưỡng 1 ms trong luật chọn dùng đúng số đó.
3. `dir_correct` lấy X thật tại khung bíp (hình học), một diễn giải của "phía vật đi vào"; ghi rõ để controller duyệt.
4. Không sửa `hazard_scenarios.py`. Task 3 commit đã xuất hiện (`9264fea`); `pytest bench/test_hazard.py` (21) chạy với `SEEVIA_VH_DIR=vh-od` pass.

## Fix round 1
- `approach_then_stop` redefined (`check_approach_stop`): stop frame = first frame Z reaches its minimum; before stop level-3 beeps are reported but allowed; from stop+1.0 s: 0 level-3 beeps AND no frame at level 3. `group == "control"` is now excluded from `config_stats` (fa/min, % safe with beep, per-type check) and from `summarize` overall safe set (still present in by_type/by_group).
- `shuffle_frames` -> `diag_shuffle_frames` (diagnostic, always pass=True, not in pass/fail). New `reverse_time` (`reverse_scenario`, `check_reverse`): approach-type dev positives (walk_static_*, oncoming_person, motorbike_charge and +noise variants), frames reversed, times rebuilt increasing, ego shift sign flipped; pass iff 0 beeps level>=2 after the first 1.0 s; count reported.
- Deleted (test smoke outputs, scratchpad, none in reports/ or results/): `.../scratchpad/g/predict_test_20261021-1719.json`, `.../scratchpad/rep.md`. No reports/HAZARD_PREDICT.md or results/hazard/predict_* existed in the repo. No --split test run again.
- Tests: `~/.venvs/seevia/bin/python -m pytest bench/test_hazard.py -q` -> 24 passed (3 new: both controls with pass+fail synthetic records, control-group exclusion).
- Smoke: `SEEVIA_VH_DIR=.../vh-od python -m bench.hazard_grid --split dev --procs 8 --types motorbike_charge,far_static_car --seeds 3 --out <scratch>/g2` -> 216/216 in 2.8 s, valid JSON.
- Controls with that smoke-selected config (degenerate 6-scenario grid: tte_l3=2.0, new_near=0, l3_vote=1): the 4 legacy controls PASS. approach_then_stop FAIL (level3 before stop 5, after settle 13 beeps, 216 level-3 frames over 3 seeds); reverse_time FAIL (20 beeps>=2 after 1 s in 20/63 scenarios); diag shuffle 0.75 -> 1.0. These may be genuine logic behaviour for an aggressive config (persistent level 3 on a stopped object at ~3 m deserves a look in the official dev run), not verified on a properly selected config.
