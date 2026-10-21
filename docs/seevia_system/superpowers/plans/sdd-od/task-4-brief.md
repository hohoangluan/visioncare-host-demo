# Brief: Task 4

Spec: SeeVia_system/docs/superpowers/specs/2026-10-21-vat-can-du-doan-quy-dao-design.md

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


### Task 4: Bộ sinh kịch bản Việt Nam + tách dev/test (`evaluations/bench/hazard_scenarios.py`)

**Files:**
- Modify: `SeeVia_system/evaluations/bench/hazard_scenarios.py`
- Test: `SeeVia_system/evaluations/bench/test_hazard.py` (thêm)

**Interfaces:**
- Produces:
  - `Scenario` thêm `t_visible_frame: int | None`, `times: list[float]` (mốc thời gian mỗi khung), `ego: list[tuple[float, float]]` (shift_x đo được, blur), `group: str` (`"legacy"|"vn"|"sudden"|"control"`).
  - `generate(type_name: str, seed: int, split: str = "legacy", cam: Camera | None = None) -> Scenario`.
  - `generate_all(n_seeds: int = 50, types=None, split: str = "legacy") -> list[Scenario]`.
  - Seed: `legacy` = 0.. (y hệt cũ); `dev` = 1000 + s; `test` = 2000 + s.
  - `split="legacy"` phải tái lập **đúng** chuỗi hộp cũ cho 24 loại cũ, tức là camera và kích thước vật không lấy mẫu.

Tham số thật lấy mẫu theo split (logic luôn dùng giá trị danh nghĩa):

| | dev | test |
|---|---|---|
| Chiều cao người | N(1,65; 0,08) | N(1,65; 0,10), 10 % trẻ em 1,1 |
| Cao camera | U(1,50; 1,70) | U(1,45; 1,75) |
| HFOV | U(64; 68) | U(62; 70) |
| Lệch góc cúi | U(−2°; 2°) | U(−4°; 4°) |
| Nhún bước (`gait`): 2 Hz, biên độ dọc | 2 % khung, cỡ ±5 % | 3 %, ±8 % |
| Quay đầu (`yaw`): sin 0,3 Hz, trượt ngang | 8 % bề rộng, đo được = thật + N(0; 1 %) | 12 %, N(0; 2 %) |
| Nhoè (`blur`): chuỗi mất khung ở đỉnh nhún | 2–4 khung, blur đo 10–25 | 2–6 khung |
| dt | 0,125 cố định | U(0,10; 0,20) + 5 % khung rớt |

Loại mới, nhãn bằng hình học như cũ:

| Loại | group | Nhãn | Mô tả |
|---|---|---|---|
| `sudden_person_behind_car` | sudden | nguy hiểm | Người bị che tới Z ∈ [3,5; 5,5], rồi bước ngang 0,8 m/s từ X = ±1,2 vào X ≈ 0. Người dùng đi 1,2 m/s |
| `sudden_motorbike_alley` | sudden | nguy hiểm | Xe máy lộ ra ở X = ±2,5, Z ∈ [4; 6], vX = ∓2,5, vZ = −3,2 |
| `motorbike_swerve` | vn | nguy hiểm | Xe máy đi tới ở X = ±1,5, tiếp cận 4 m/s; khi Z ∈ [8; 12] lạng vào X = 0 trong 1 s |
| `motorbike_wrong_way` | vn | nguy hiểm | Xe máy ngược chiều trên vỉa hè trong lối, tiếp cận 1,2 + 3 m/s, Z0 ∈ [15; 25] |
| `cross_cut_person` | vn | nguy hiểm | Người cắt chéo lối ở Z ≈ 3–4 |
| `parked_motorbike_row` | vn | an toàn | 4–8 xe máy ở X = ±U(0,9; 1,5), cách nhau 1,0–1,5 m theo Z, người dùng đi ngang qua |
| `pass_by_person` | vn | an toàn | Người ngược chiều ở X = ±U(0,8; 1,2), tiếp cận 2,4 m/s |
| `same_dir_person` | vn | an toàn | Người đi trước cùng tốc độ ở Z ∈ [3; 5], trong lối, 30 s |
| `approach_then_stop` | control | an toàn | Người dùng tiến tới vật đứng yên rồi dừng ở Z = 3 m trong 10 s (đối chứng âm: không được mức 3) |

Mỗi loại mới và 6 loại cũ có nhiễu được ghép thêm `+gait`, `+yaw`, `+blur` (split dev/test). Trường `ego` luôn được điền: không có yaw thì shift đo = N(0; σ đo).

- [ ] **Step 1: Viết test hỏng** trong `bench/test_hazard.py`:
  - `test_legacy_split_bitwise`: `generate(t, s, "legacy")` cho 24 loại cũ × 3 seed giống y hệt bản cũ. Trước khi sửa, lưu hash chuỗi hộp vào `bench/fixtures/c1b_legacy_hash.json`.
  - `test_dev_test_disjoint_and_wider`: tập seed không giao nhau; độ lệch chuẩn chiều cao người ở test > dev.
  - `test_sudden_t_visible`: với `sudden_*` thì `t_visible_frame` không None và `t_danger_frame - t_visible_frame` ≤ 2,5 s/dt.
  - `test_safe_labels_hold`: `parked_motorbike_row`, `pass_by_person`, `same_dir_person`, `approach_then_stop` có `positive == False` ở 50 seed dev.
  - `test_times_monotonic`: `times` tăng nghiêm ngặt ở cả hai split.
- [ ] **Step 2: Chạy** `cd evaluations && SEEVIA_VH_DIR=../vh-od ~/.venvs/seevia/bin/python -m pytest bench/test_hazard.py -q`. Kỳ vọng: FAIL ở các test mới.
- [ ] **Step 3: Cài** theo bảng.
- [ ] **Step 4: Chạy lại.** Kỳ vọng: PASS, kể cả test cũ. `python -m bench.hazard_logic` (legacy) ra lại **đúng** 8,3 % / 0,54 lần/phút.
- [ ] **Step 5:** (bàn đo không nằm trong git) ghi một dòng vào nhật ký `docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md`.

