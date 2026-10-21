# Vật cản — cảnh báo theo dự đoán quỹ đạo: kế hoạch thực thi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay luật mức theo diện tích hộp bằng logic ước lượng khoảng cách + vận tốc từng vật và dự đoán thời điểm vật cắt hành lang trước mặt. Logic mới chạy sau cờ, đo trên C1b mở rộng (có kịch bản Việt Nam) và chọn tham số bằng luật chốt trước. Cuối cùng chạy lại **mọi** bàn đo AI để ra bộ thông số chốt.

**Architecture:** VH thêm 3 module thuần (`live/hazard_geom.py` hình học/khoảng cách, `live/hazard_track.py` track + Kalman, `live/hazard_predict.py` xếp mức theo TTE) và 1 module ảnh (`live/ego_motion.py` dịch chuyển toàn khung + độ nhoè). `live/hazard.py` giữ logic cũ, thêm `make_tracker()`/`make_anti()` chọn theo `HAZARD_LOGIC`. Bàn đo C1b ở `SeeVia_system/evaluations/bench/` sinh thêm kịch bản Việt Nam, tách dev/test, chạy lưới song song và viết `reports/HAZARD_PREDICT.md`.

**Tech Stack:** Python 3.11 (`~/.venvs/seevia`), numpy, OpenCV (`cv2.phaseCorrelate`, Laplacian), pytest. Không thêm gói.

**Spec:** `SeeVia_system/docs/superpowers/specs/2026-10-21-vat-can-du-doan-quy-dao-design.md` (đọc cùng kế hoạch này).

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

---

### Task 1: Hình học + ước lượng khoảng cách (`live/hazard_geom.py`) và cấu hình

**Files:**
- Create: `vh-od/live/hazard_geom.py`
- Modify: `vh-od/config.py` (khối Hazard, sau `HAZARD_MIN_LEVEL`)
- Test: `vh-od/tests/test_hazard_predict.py`

**Interfaces:**
- Produces:
  - `CLASS_HEIGHT_M: dict[str, float]`: mọi `kind` của `hazard._CLASSES` + `evaluations/train/classes_vh.json`. Mỗi dòng có comment nguồn/lý do. Giá trị gợi ý: person 1,65; dog 0,5; bicycle 1,1; motorbike 1,2 (có người ngồi); tricycle 1,3; car 1,5; bus 3,0; truck 3,0; pole/warning_column 1,0 (không đáng tin → σ lớn); reflective_cone 0,7; spherical_roadblock 0,6; ashcan 0,9; bench 0,45; chair 0,85; plant 0,8; hydrant/fire_hydrant 0,7; stop_sign 2,2; traffic_light 3,0; parking_meter 1,2.
  - `CLASS_HEIGHT_REL_SIGMA: dict[str, float]` (mặc định 0,15; cột/cây/biển 0,5).
  - `@dataclass(frozen=True) class Camera: w: int; h: int; hfov_deg: float; height_m: float` + property `f_px`. `Camera.default()` đọc config.
  - `@dataclass class Estimate: z_m: float; x_m: float; z_sigma: float; source: str  # "height"|"ground"|"fused"|"width"`.
  - `estimate(det: hazard.Detection, cam: Camera, pitch_rad: float = 0.0) -> Estimate`.
- Config mới (đọc bằng `get`, có comment):
  - `HAZARD_LOGIC = get("HAZARD_LOGIC", "area")`
  - `HAZARD_CAM_HFOV_DEG = 66.0`, `HAZARD_CAM_HEIGHT_M = 1.6`
  - `HAZARD_DANGER_Z_M = 2.0`, `HAZARD_LANE_HALF_M = 0.6`
  - `HAZARD_TTE_L3_S = 1.5`, `HAZARD_TTE_L2_S = 3.0`, `HAZARD_HORIZON_S = 3.0`
  - `HAZARD_NEW_NEAR_M = 3.0` (0 = tắt), `HAZARD_COAST_FRAMES = 3`, `HAZARD_SIGMA_K = 0.0`
  - `HAZARD_L3_VOTE = 2`, `HAZARD_NEW_BYPASS_VOTE = "1"`, `HAZARD_KF_Q = 1.0`, `HAZARD_DOWN_HOLD = 2`
  - `HAZARD_CLASSES_JSON = get("HAZARD_CLASSES_JSON", "")`. Trống thì dùng `_CLASSES` COCO như cũ. Có giá trị thì `live/hazard.py` nạp file `{id: [kind, group]}` (định dạng `evaluations/train/classes_vh.json`) thay `_CLASSES` lúc import. `OnnxYolo.detect` lọc theo khoá của bảng đang dùng. Cần cho Task 7: VH hiện hard-code COCO nên `ft_11s_last` gán sai lớp.

Cách gộp mặc định:
- Nguồn **height**: Z = f·H/h_px, σ = rel_σ·Z. Chỉ dùng khi cả cạnh trên lẫn cạnh dưới cách mép ảnh > 0,01.
- Nguồn **ground**: Z = height_m·f / (y_bot_px − cy + f·tan(pitch)), σ = Z²·0,03/height_m. Chỉ dùng khi đáy không chạm mép dưới và nằm dưới tâm ảnh.
- Hai nguồn hợp lệ thì gộp nghịch đảo phương sai.
- Đáy chạm mép dưới thì dùng cạnh trên: Z = height_m·f/(cy − y_top_px) nếu y_top_px < cy, kẹp vào [0,3; 1,5].
- Không nguồn nào hợp lệ thì dùng **width** với bề rộng chuẩn = 0,5·H.
- Lệch ngang: X = (cx_px − w/2)·Z/f.

- [ ] **Step 1: Tạo worktree** — `git -C visioncare-host-demo worktree add ../vh-od -b od-du-doan 110c642`, tạo 2 symlink như Global Constraints. Chạy `cd vh-od && ~/.venvs/seevia/bin/python -m pytest -q`. Kỳ vọng: pass hết (số test ghi lại làm mốc).
- [ ] **Step 2: Viết test hỏng** trong `tests/test_hazard_predict.py`. Dùng hàm `_proj(X, Z, H, W, cam)` trong test (chiếu pin-hole giống `bench/hazard_scenarios.Camera.project`) để sinh hộp:
  - `test_estimate_height_source_recovers_distance`: người H = 1,65 ở Z ∈ {3, 6, 10}, X = 0,3 → `abs(e.z_m - Z)/Z < 0.05`, `abs(e.x_m - 0.3) < 0.1`.
  - `test_estimate_bottom_clipped_is_near`: người ở Z = 1,0 (đáy bị cắt) → `e.z_m < 1.5` và `e.source != "height"`.
  - `test_estimate_unknown_kind_finite`: `Detection("xyz", "static", 0.5, box)` ở Z = 4 → `math.isfinite(e.z_m)` và `abs(e.z_m-4) < 1.0`.
  - `test_estimate_pitch_shifts_ground_only`: hộp có đáy, `pitch_rad = 0.03` đổi Z của nguồn ground nhưng `source="height"` thì không đổi.
  - `test_classes_json_overrides_coco` (monkeypatch env + `importlib.reload(hazard)`): với `classes_vh.json` thì `hazard._CLASSES[11] == ("pole", "static")`; env trống thì `hazard._CLASSES[0] == ("person", "person")`.
  - `test_class_table_covers_all_kinds`: mọi `kind` trong `hazard._CLASSES` và `../evaluations/train/classes_vh.json` (bỏ qua test nếu không có file) đều có trong `CLASS_HEIGHT_M`.
- [ ] **Step 3: Chạy** `python -m pytest tests/test_hazard_predict.py -q`. Kỳ vọng: FAIL (ImportError `live.hazard_geom`).
- [ ] **Step 4: Cài** `hazard_geom.py` + khối config như Interfaces.
- [ ] **Step 5: Chạy lại test.** Kỳ vọng: PASS. Chạy cả `pytest -q`. Kỳ vọng: không hỏng test cũ.
- [ ] **Step 6: Commit** `vật cản: hazard_geom — ước lượng khoảng cách theo chiều cao lớp + đáy hộp; cờ HAZARD_LOGIC`.

### Task 2: Track + Kalman (`live/hazard_track.py`)

**Files:**
- Create: `vh-od/live/hazard_track.py`
- Test: `vh-od/tests/test_hazard_predict.py` (thêm)

**Interfaces:**
- Consumes: `hazard_geom.Estimate`, `hazard.Detection`.
- Produces:
  - `@dataclass class Track: id: int; kind: str; group: str; box: tuple; x: np.ndarray  # [X, Z, vX, vZ]; P: np.ndarray  # 4x4; hits: int; misses: int; age: int`.
  - `Track.predict_xz(t_ahead: float) -> tuple[float, float]`, `Track.sigma_x() -> float`.
  - `class TrackSet: __init__(self, coast: int, q: float)`.
  - `TrackSet.update(dets: list[Detection], ests: list[Estimate], t: float | None, ego_shift_x_m: float = 0.0) -> list[Track]`: trả các track **được thấy ở khung này** (hits ≥ 1, misses == 0) + track đang coast.
  - `TrackSet.reset()`.

Cách làm:
- Kalman vận tốc không đổi, nhiễu quá trình dạng gia tốc trắng (q m²/s³).
- Đo được (X, Z) với R = diag((0,1·Z)², z_sigma²).
- `dt = t − t_prev`. Nếu `t` None hoặc dt ≤ 0 hoặc dt > 1 s thì dùng 0,125.
- Gán track: tham lam theo IoU (hộp dự đoán = hộp cũ) ≥ 0,2, cùng `group`. Hộp không gán được thì tạo track mới với vận tốc 0 và P vận tốc lớn (σ_v = 3 m/s).
- Track không thấy quá `coast` khung thì xoá.
- `ego_shift_x_m`: trừ vào X của **mọi** track trước bước update (quay đầu).

- [ ] **Step 1: Viết test hỏng:**
  - `test_track_velocity_converges`: vật tiến thẳng 1,2 m/s từ Z = 12, 8 fps, 16 khung → `abs(track.x[3] + 1.2) < 0.3`.
  - `test_track_dt_nonpositive_safe`: hai `update` cùng `t` rồi `t` lùi → mọi giá trị `np.isfinite`.
  - `test_track_coast_then_drop`: thấy 5 khung, mất 4 khung, `coast=3` → khung thứ 4 không còn track; vật lại xuất hiện → `track.id` mới, `abs(track.x[3]) < 1e-6` (vận tốc khởi đầu 0).
  - `test_track_two_objects_keep_ids`: 2 người X = −1 và X = +1 tiến song song 10 khung → 2 id không đổi.
  - `test_ego_shift_removed`: vật đứng yên, mỗi khung cộng 0,2 m vào X đo được và truyền `ego_shift_x_m=0.2` → `abs(vX) < 0.3`.
- [ ] **Step 2: Chạy**, kỳ vọng FAIL (ImportError).
- [ ] **Step 3: Cài** `hazard_track.py`.
- [ ] **Step 4: Chạy**, kỳ vọng PASS + `pytest -q` toàn bộ pass.
- [ ] **Step 5: Commit** `vật cản: hazard_track — track IoU + Kalman (X, Z) theo mốc thời gian thật`.

### Task 3: Xếp mức theo TTE + chống làm phiền mới + đường nóng (`live/hazard_predict.py`, `live/hazard.py`, `lanes/nav_live.py`, `live/ego_motion.py`)

**Files:**
- Create: `vh-od/live/hazard_predict.py`, `vh-od/live/ego_motion.py`
- Modify: `vh-od/live/hazard.py` (`Hazard`, `HazardTracker.assess`, `AntiAnnoy.__init__/step`, thêm `make_tracker`, `make_anti`), `vh-od/lanes/nav_live.py:33-42,119,127`
- Test: `vh-od/tests/test_hazard_predict.py` (thêm)

**Interfaces:**
- Consumes: Task 1, Task 2.
- Produces:
  - `hazard.Hazard` thêm field `urgent: bool = False` (`compare=False`).
  - `HazardTracker.assess(self, detections, t: float | None = None, ego: "ego_motion.Ego | None" = None) -> Hazard`. Hai tham số mới bị bỏ qua, hành vi cũ giữ nguyên.
  - `AntiAnnoy.__init__(self, clock=time.monotonic, l3_vote: int = 1, down_hold: int = 1, bypass_vote: bool = True)`. Giá trị mặc định = hành vi cũ y hệt. `step(level: int, urgent: bool = False) -> bool`.
    - `l3_vote = 2`: mức 3 chỉ gửi khi ≥ 2 trong 3 khung gần nhất là 3, trừ khi `urgent and bypass_vote`. Chưa đủ phiếu thì xử lý như mức 2.
    - `down_hold = 2`: `current` chỉ hạ khi mức thấp hơn giữ 2 khung liên tiếp.
  - `@dataclass class PredictParams`: `tte_l3_s, tte_l2_s, horizon_s, new_near_m, coast, sigma_k, q, l3_vote, bypass_vote, down_hold, danger_z_m, lane_half_m`; `PredictParams.from_config()`.
  - `class PredictTracker: __init__(self, params: PredictParams | None = None, cam: Camera | None = None)`; `assess(detections, t=None, ego=None) -> Hazard`, cùng chữ ký `HazardTracker.assess`.
  - `hazard.make_tracker() -> HazardTracker | PredictTracker` và `hazard.make_anti(clock=time.monotonic) -> AntiAnnoy` theo `config.HAZARD_LOGIC` (`predict` → tham số từ `PredictParams.from_config()`).
  - `ego_motion.Ego(shift_x: float, blur: float)`. `shift_x` là tỉ lệ bề rộng, dương = cảnh trượt sang phải; `blur` là phương sai Laplacian.
  - `ego_motion.EgoMeter.measure(bgr: np.ndarray) -> Ego`: xám, thu về 80×60, `cv2.phaseCorrelate` với khung trước. Khung đầu: shift 0.
  - `nav_live.process_frame(det, tracker, jpeg, t: float | None = None, meter: "ego_motion.EgoMeter | None" = None)`: tính `ego` khi có `meter` rồi gọi `tracker.assess(detections, t, ego)`.
  - `run()`: dùng `hazard.make_tracker()` / `hazard.make_anti()`, chỉ tạo `EgoMeter` khi `HAZARD_LOGIC == "predict"`, truyền `t = time.monotonic()` lúc nhận khung, `anti.step(level, result.urgent)`.

Luật xếp mức trong `PredictTracker.assess` (mỗi track, lấy mức cao nhất):
- **Góc cúi (không IMU):** `PredictTracker` giữ `pitch_rad`, EMA hệ số 0,1, kẹp ±0,1 rad. Mỗi track có cả nguồn height lẫn ground hợp lệ thì lấy góc làm hai Z khớp nhau làm mẫu. Gọi `hazard_geom.estimate(det, cam, self.pitch_rad)`. Test `test_pitch_estimate_converges`: hộp sinh với lệch góc cúi 0,03 rad, 40 khung → `abs(pitch_rad - 0.03) < 0.01`.
- `ego.shift_x` đổi sang mét (shift_x · w / f · Z của từng track) trước khi đưa vào `TrackSet.update`. `ego.blur` thấp (< 30) thì nhân R lên 4 lần, không tạo track mới từ khung đó.
- Vật đang ở trong hành lang (Z < danger_z, |X| < lane_half) → mức 3.
- Track mới (`hits == 1`), `new_near_m > 0`, Z < new_near_m, |X| < lane_half → mức 3, `urgent=True`.
- Dự đoán từng bước 0,125 s tới `horizon_s`. TTE = bước đầu tiên có Z_pred < danger_z và |X_pred| < lane_half + sigma_k·σ_X. TTE < tte_l3 → 3; TTE < tte_l2 → 2.
- Không cắt hành lang mà Z < 8 m → 1; còn lại 0.
- `dir`: X hiện tại < −lane_half → `left`; > lane_half → `right`; còn lại `center`.
- `kind` = kind của track có mức cao nhất. `levels` = mức theo thứ tự detection đầu vào (để debug như cũ).

- [ ] **Step 1: Viết test hỏng:**
  - `test_area_default_unchanged`: `config.HAZARD_LOGIC == "area"` thì `make_tracker()` là `HazardTracker` và `make_anti()` có `l3_vote == 1`. Thêm một chuỗi hộp cố định qua `make_anti().step` ra đúng danh sách bool như `AntiAnnoy()` cũ.
  - `test_predict_static_person_timely`: người đứng yên, người dùng đi 1,2 m/s từ Z = 12, X = 0 → khung đầu tiên mức ≥ 2 có Z ≥ 2 + 1,5·1,2 = 3,8 m.
  - `test_predict_pass_by_no_level2`: người ngược chiều 2,4 m/s ở X = +1,0 → không khung nào mức ≥ 2.
  - `test_predict_crossing_dir_left`: người đi ngang từ X = −3 vào hành lang ở Z = 4 → mức ≥ 2 với `dir == "left"` trước khi |X| < 0,6.
  - `test_predict_new_near_urgent`: khung đầu đã có người ở Z = 2,5, X = 0 → `level == 3 and urgent`.
  - `test_anti_l3_vote`: `AntiAnnoy(l3_vote=2)`: chuỗi `3,0,0` không gửi mức 3; `3,3` gửi; `step(3, urgent=True)` gửi ngay với `bypass_vote=True`.
  - `test_anti_down_hold`: `AntiAnnoy(down_hold=2)`: 3 → 2 (1 khung) → 3 không gửi lại (vì `current` vẫn 3).
  - `test_predict_crowded_frame_fast`: 20 hộp xe máy đỗ ở |X| ∈ [0,9; 1,5] m → 200 khung, `assess` p90 < 1 ms, không khung nào mức ≥ 2.
  - `test_ego_meter_shift_sign`: ảnh nhiễu ngẫu nhiên 320×240 cuộn sang phải 16 px → `shift_x ≈ +0.05` (±0,01); ảnh nét có `blur` > ảnh `GaussianBlur(15)`.
  - `test_process_frame_passes_time`: giả `tracker.assess` ghi lại tham số → nhận đúng `t`.
- [ ] **Step 2: Chạy**, kỳ vọng FAIL.
- [ ] **Step 3: Cài** `ego_motion.py`, `hazard_predict.py`, sửa `hazard.py`, `nav_live.py`.
- [ ] **Step 4: Chạy** test mới + `pytest -q` toàn bộ. Kỳ vọng: PASS. Riêng `tests/test_v2_units.py`, `test_v2_api.py`, `test_modes_split.py`, `test_debug_frames.py` phải không đổi.
- [ ] **Step 5: Commit** `vật cản: HAZARD_LOGIC=predict — TTE theo dự đoán quỹ đạo, vật mới gần báo ngay, phiếu 2/3 + hysteresis; ego_motion`.

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

### Task 6: Chạy thật C1b dev → test, C1c, hoàn tất nhánh OD

**Files:**
- Modify: `SeeVia_system/evaluations/bench/hazard_latency.py` (đo thêm `EgoMeter.measure` và `PredictTracker.assess` trên khung QVGA thật khi `HAZARD_LOGIC=predict`)
- Create: `SeeVia_system/evaluations/reports/HAZARD_PREDICT.md` (sinh tự động)
- Copy vào `vh-od/evaluations/bench/`: `hazard_scenarios.py`, `hazard_logic.py`, `hazard_grid.py`, `hazard_latency.py`, `test_hazard.py`, `fixtures/c1b_legacy_hash.json` (bản đo đi theo nhánh)

- [ ] **Step 1:** `uptime` (load < 16). Chạy `python -m bench.hazard_grid --split dev --procs 8` (50 seed/loại). Kỳ vọng: `HẾT ok`; đối chứng đạt (shuffle, approach_then_stop, 4 đối chứng cũ). Đối chứng nào hỏng thì **dừng**, debug bàn đo, không đọc số.
- [ ] **Step 2:** Lấy cấu hình chọn. `selected == null` thì dừng, báo Pareto cho người dùng, **không** chạy test.
- [ ] **Step 3:** `python -m bench.hazard_grid --split test --config <json>` **một lần**. Kỳ vọng: báo cáo được sinh, có kết luận ĐẠT/KHÔNG ĐẠT.
- [ ] **Step 4:** C1c: `HAZARD_LOGIC=predict GPU=<id trống> python -m bench.hazard_latency`, đo liền sau bản `area`. Kỳ vọng: ego p90 ≤ 2 ms, tổng p90 ≤ 10 ms. Ghi số vào `HAZARD_PREDICT.md`.
- [ ] **Step 5:** Đọc 10 ca sai ngẫu nhiên mỗi nhóm, kiểm mỗi ca giải thích được bằng cơ chế ghi trong báo cáo.
- [ ] **Step 6:** Ghi tham số chọn vào giá trị mặc định của `config.py`. `HAZARD_LOGIC` **vẫn** `area`. Copy file bàn đo vào `vh-od/evaluations/bench/`, chạy `pytest -q` (VH) + `bench/test_hazard.py`. Commit `vật cản: tham số predict chọn trên C1b dev (HAZARD_PREDICT.md) + bàn đo C1b Việt Nam`.
- [ ] **Step 7:** Review nhánh (superpowers:requesting-code-review). Cập nhật bàn giao `docs/2026-10-21-ban-giao-cai-tien-ai.md` mục 0/5/6 + nhật ký.

### Task 7: Nhánh tích hợp + chạy lại mọi bàn đo AI → bộ thông số chốt (yêu cầu người dùng 2026-10-21)

**Files:**
- Worktree `SeeVia_system/vh-chot`, nhánh cục bộ `chot-ai-2026-10-21` từ `app-giao-tiep` @ `110c642`, merge `vqa-hoi-anh`, `ocr-tien`, `od-du-doan` (`--no-ff`, không push).
- Create: `SeeVia_system/evaluations/reports/THONG_SO_CHOT.md`, `SeeVia_system/evaluations/reports/thong_so_chot.env`
- Create: `SeeVia_system/evaluations/run_chot.sh` (chạy tuần tự mọi bàn, log `results/chot.log`, `HẾT ok|LỖI`)

**Nguyên tắc:** đây là lượt **xác nhận**. Mọi tham số đã được chọn trên dev ở các đợt trước. Lượt này chạy test **một lần** trên code đã gộp, không chỉnh tham số theo số test. Lệch đáng kể so với báo cáo riêng (> CI) thì ghi lại và điều tra nguyên nhân, không tự đổi tham số.

- [ ] **Step 1:** Tạo worktree, merge 3 nhánh. Xung đột dự kiến:
  - `tests/test_v2_units.py` (vqa vs app-giao-tiep);
  - `lanes/ocr_live.py` (ocr vs app-giao-tiep);
  - `models/clef/client.py` / `pipeline/intent_early.py` nếu đụng nhau.
  
  Giải quyết bằng cách giữ cả hai phía. Nhãn `ask` vẫn đứng **cuối** `LABELS`. Chạy `pytest -q`. Kỳ vọng: pass hết.
- [ ] **Step 2: Bật cấu hình ứng viên** qua env, không sửa code:
  - `HAZARD_MODEL_PATH=evaluations/train/models/ft_11s_last_320.onnx`, `HAZARD_CLASSES_JSON=evaluations/train/classes_vh.json`, `HAZARD_LOGIC=predict` (nếu Task 6 ĐẠT; không thì `area`);
  - `MONEY_MODE=choice`, `MONEY_MIN_PROB=0.995`, `MONEY_MULTI_MIN_PROB=0.98`;
  - `OCR_DIGIT_HEDGE_PROB=0.9`.
  
  Ghi bản env này vào `thong_so_chot.env`.
- [ ] **Step 3: `run_chot.sh`**, `SEEVIA_VH_DIR=…/vh-chot`. Kiểm `uptime`/`nvidia-smi` trước, GPU trống. Bàn đo theo thứ tự (đánh số như `TONG_HOP.md`):
  - C1a `bench.hazard_detect` (ft_11s_last @0,35 vs yolo11n);
  - C1b `bench.hazard_grid --split test --config <đã chọn>` + legacy;
  - C1c `bench.hazard_latency`;
  - C2a `bench.ocr_vintext`;
  - C2b `bench.ocr_sroie` + `bench.ocr_numconf --split test`;
  - C2c `bench.ocr_vitextvqa`;
  - C3 `bench.money_vnd --path choice --choice-prompt sys` + `bench.money_multi` (3 khung);
  - C4 `bench.vqa_vizwiz --intent ask` + `bench.vqa_latency_ab --n 60`;
  - C5 `bench.quality_vizwiz`;
  - C6 `bench.stt_vivos`;
  - định tuyến intent `tools.eval_intent --gold data/intent/gold_dev.jsonl` (từ `vh-chot`).
  
  Tham số mỗi lệnh lấy theo bàn giao §7 và `run_*.sh`. Kỳ vọng: `HẾT ok`.
- [ ] **Step 4:** VQA cần giám khảo nhìn ảnh: `bench.vqa_pair_judge build --n-real 150` → 4 Sonnet subagent, mỗi agent ghi `judge_partK.csv` riêng và đặt tên script riêng → gộp → `report`. Có đối chứng âm (tráo ảnh 15/15, cặp y hệt hoà 15/15).
- [ ] **Step 5:** Viết `THONG_SO_CHOT.md`:
  - (1) **bảng thông số chốt**: biến env, giá trị, chọn ở đâu (báo cáo + tập dev), số test chính;
  - (2) **bảng 10 bàn đo** baseline 2026-10-20 vs chốt (metric an toàn, metric chuẩn, trễ p50/p90, CI, ghép đôi);
  - (3) giới hạn: đọc tiền 3 khung cần kính gửi 3 ảnh (đặc tả đang làm), C1b là dữ liệu tổng hợp, vật không có lớp;
  - (4) việc còn treo.
- [ ] **Step 6:** Cập nhật bàn giao + nhật ký. Báo người dùng: đường dẫn `THONG_SO_CHOT.md`, `thong_so_chot.env`, nhánh `chot-ai-2026-10-21` (chưa push, chưa merge). Không bật gì trong `visioncare-host-demo`.
