# Brief: Task 5

## Global Constraints

- Worktree mới `SeeVia_system/vh-od`, nhánh `od-du-doan`, tách từ `app-giao-tiep` @ `110c642`. Symlink `.env` và `certs/uit-ca-bundle.pem` trỏ về `../visioncare-host-demo/` như `vh-vqa`/`vh-ocr`.
- **Không sửa** checkout chính `SeeVia_system/visioncare-host-demo`. **Không push, không merge** vào `app-giao-tiep`.
- Commit với `-c user.name=LuanLuKim -c user.email=kimluanlu95@gmail.com`, cuối message: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `HAZARD_LOGIC` mặc định `area` (hành vi cũ, byte-by-byte). `predict` chỉ bật bằng env.
- Giao thức kính giữ nguyên: `protocol.hazard(level, dir, kind)`; `dir` ∈ {`left`,`center`,`right`} = **vị trí** (vật đi vào hành lang từ phía nào; đang chắn/lao thẳng = `center`). Không thêm câu "tránh sang…".
- Hành lang và nhãn: `DANGER_Z = 2.0` m, `LANE_HALF = 0.6` m, **tâm** vật (khớp nhãn C1b). Kịp thời: bíp mức ≥ 2 sớm ≥ 1,5 s trước `t_danger`.
- Camera danh nghĩa: 320×240, HFOV 66°, cao 1,6 m (lấy từ config, không hard-code trong logic).
- Ngân sách trễ: `assess + step` p90 ≤ 1 ms/khung (CPU); `ego_motion.measure` p90 ≤ 2 ms trên QVGA thật; tổng chuỗi server C1c p90 ≤ 10 ms.
- Bàn đo C1b thuần CPU (`common.setup(gpu=False)`), song song tối đa 8 tiến trình (máy dùng chung). Đo trễ: kiểm `uptime` + `nvidia-smi` trước, chạy liền nhau.
- Chạy bàn đo từ `SeeVia_system/evaluations/` với `SEEVIA_VH_DIR=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-od`.
- Comment/docstring tiếng Việt, cùng mật độ và giọng như `live/hazard.py`.
- Probe NFS trước khi ghi file kết quả lớn (> 64 KB): ghi file thử 5 MB + fsync, kiểm kích thước.

## Review Focus

1. **Hộp chạm mép dưới/trên (vật sát người):** Z phải nhỏ (< 1,5 m), không được nổ ra xa vì h_hộp bị cắt — test ở Task 1.
2. **Lớp lạ không có trong bảng chiều cao** (`kind="xyz"` hoặc lớp `classes_vh.json`): vẫn ra Z hữu hạn từ đáy hộp, không KeyError — test ở Task 1.
3. **Mốc thời gian trùng/lùi/None** (`_Mailbox` đè khung, đồng hồ giả): dt ≤ 0 → dùng 0,125 s, không chia 0, không NaN — test ở Task 2.
4. **Vật biến mất lâu rồi xuất hiện lại** cùng chỗ: track cũ đã xoá sau `coast` khung, không mang vận tốc cũ, không bíp mức 3 do track ma — test ở Task 2.
5. **Khung đông vật** (20 hộp, dãy xe máy đỗ): `assess` p90 < 1 ms và không bíp khi mọi vật ngoài hành lang — test ở Task 3.


### Task 5: Chấm điểm, đối chứng, lưới + luật chọn, báo cáo (`hazard_logic.py`, `hazard_grid.py`)

**Files:**
- Modify: `SeeVia_system/evaluations/bench/hazard_logic.py`
- Create: `SeeVia_system/evaluations/bench/hazard_grid.py`
- Test: `SeeVia_system/evaluations/bench/test_hazard.py` (thêm)

**Interfaces:**
- Consumes: Task 3 (`PredictTracker`, `PredictParams`, `AntiAnnoy(l3_vote, down_hold, bypass_vote)`, `Hazard.urgent`, `ego_motion.Ego`), Task 4.
- Produces:
  - `hazard_logic.PredictPipeline(params: PredictParams)` với cùng giao diện `frame(k, dets)` như `BaselinePipeline`. Đồng hồ AntiAnnoy = `scn.times[k]`. Ego lấy từ `scn.ego[k]`. Thêm `frame(k, dets, t, ego)`: `BaselinePipeline` bỏ qua hai tham số thêm.
  - `simulate(scn, make)` truyền `t`/`ego`.
  - `score(rec)` thêm, với `group == "sudden"`:
    - `timely_sudden = bíp mức≥2 trước t_danger VÀ (k_bíp − t_visible) ≤ 2`;
    - `reveal_delay_s`;
    - `max_lead_s = (t_danger − t_visible)·dt`. Kịch bản có `max_lead_s` < 1 khung thì đánh dấu `impossible` và loại khỏi mẫu số.
    - `timely` của nhóm sudden **dùng định nghĩa này**.
  - `summarize` báo thêm `dir_correct_rate` (với kịch bản nguy hiểm có bíp: `dir` khớp phía vật đi vào theo hình học) và nhóm theo `group`.
  - `run_controls` thêm:
    - `shuffle_frames`: predict trên khung xáo của kịch bản nguy hiểm dev phải giảm kịp thời ≥ 50 % tương đối;
    - `approach_then_stop`: 0 bíp mức 3.
  - `hazard_grid.py` CLI: `python -m bench.hazard_grid --split dev|test [--config JSON] [--procs 8]`.
    - `dev`: chạy lưới bên dưới song song, áp luật chọn, ghi `results/hazard/predict_grid_dev_<ts>.json` (mọi cấu hình + Pareto + cấu hình chọn hoặc `null`).
    - `test`: chỉ nhận `--config` (cấu hình đã chọn) + baseline, chạy **một lần**, ghi kết quả và `reports/HAZARD_PREDICT.md`.
- Lưới (216 cấu hình, chốt trước):
  - `tte_l3_s` {1,0; 1,5; 2,0}
  - `tte_l2_s` {2,5; 3,5}
  - `new_near_m` {0; 3,0; 4,0}
  - `sigma_k` {0; 1,0}
  - (`l3_vote`, `bypass_vote`) {(1, –); (2, True); (2, False)}
  - `coast` {2; 3}
  - `q` = 1,0, `down_hold` = 2, `horizon_s` = max(3,0; tte_l2_s)
- Luật chọn (sao y spec §6). Mọi so sánh dùng baseline chạy trên **cùng** kịch bản dev:
  1. Báo oan lần/phút (gộp tập an toàn) ≤ baseline; % kịch bản an toàn có bíp ≤ baseline; không loại an toàn nào có % bíp vượt baseline quá 5 điểm.
  2. `assess + step` p90 ≤ 1 ms.
  3. Không loại nguy hiểm nào giảm kịp thời > 5 điểm.
  4. Tối đa kịp thời gộp (các loại nguy hiểm cùng trọng số). Hoà trong 1 điểm thì chọn báo oan thấp hơn, rồi trễ thuật toán thấp hơn.
  5. Không cấu hình nào thoả → `selected = null`.
- `HAZARD_PREDICT.md` gồm:
  - tóm tắt;
  - bảng theo loại (baseline vs chọn, test, CI, bắt thêm/mất);
  - Pareto dev (báo oan/phút, % an toàn bíp, kịp thời; đánh dấu chọn + baseline);
  - ca báo oan còn lại (loại, Z, X, vì sao);
  - ca trượt/muộn theo nguyên nhân;
  - đối chứng;
  - trễ;
  - giới hạn (spec §7).
  - Test vi phạm ràng buộc báo oan → dòng đầu tiên ghi **"KHÔNG ĐẠT"** kèm loại vi phạm.

- [ ] **Step 1: Viết test hỏng:**
  - `test_sudden_timely_definition`: bản ghi giả có `t_visible=10, t_danger=14`, bíp ở 11 → `timely == 1`; bíp ở 13 → `timely == 0`; bản ghi `t_danger == t_visible` → `impossible`.
  - `test_selection_rule`: 3 cấu hình giả: (a) kịp thời cao nhưng báo oan > baseline; (b) hợp lệ, kịp thời 0,6; (c) hợp lệ, kịp thời 0,605, báo oan thấp hơn (b) → chọn (c). Toàn bộ vi phạm → `None`.
  - `test_pareto_nondominated`: không điểm nào trong Pareto bị điểm khác trội.
  - `test_baseline_pipeline_ignores_extra`: baseline chạy với `t`/`ego` cho đúng `levels` như không truyền.
- [ ] **Step 2: Chạy**, kỳ vọng FAIL.
- [ ] **Step 3: Cài.**
- [ ] **Step 4: Chạy** test PASS. Chạy thử `python -m bench.hazard_grid --split dev --procs 8` trên 2 loại × 3 seed để bắt lỗi chạy. Kỳ vọng: file JSON hợp lệ.
- [ ] **Step 5:** ghi nhật ký.

