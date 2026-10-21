# Brief: Task 1–3 (một implementer làm tuần tự)

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

