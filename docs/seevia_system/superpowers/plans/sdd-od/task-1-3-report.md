# Báo cáo Task 1–3 (vật cản dự đoán, `vh-od`, nhánh `od-du-doan`)

Trạng thái: **DONE_WITH_CONCERNS**

## Commit

| Task | Hash | Ghi chú |
|---|---|---|
| 1 hazard_geom + cấu hình | `f6406a0` | do tôi commit |
| 2 hazard_track | `b991631` | do tôi commit |
| 3 predict + ego_motion + AntiAnnoy + nav_live | `9264fea` | **không phải tôi commit** (xem Concern A); nội dung là công việc Task 3 của tôi |

Sau đó có thêm `5206c82` ("đáy hộp bị cắt -> Z theo tỉ lệ bề rộng") và các sửa đổi chưa commit ở `hazard_geom.py`, `hazard_track.py`, `hazard_predict.py`, `config.py`, `hazard.py`, `tests/test_hazard_predict.py`. Không phải của tôi (xem Concern A). Mọi số liệu dưới đây ứng với `9264fea`.

## Số test

- Mốc ban đầu (trước khi sửa): `pytest -q` = 645 passed, 2 skipped.
- Sau Task 3 (`9264fea`, kiểm bằng `git archive HEAD` ra thư mục riêng): `tests/test_hazard_predict.py` 26 passed; cùng `test_v2_units`, `test_modes_split`, `test_debug_frames` = 127 passed; `test_v2_api` + `test_v2_session` = 39 passed. Bốn file cũ không bị sửa.
- Toàn bộ `pytest -q` với `CUDA_VISIBLE_DEVICES=4`: 665 passed, 2 skipped, 1 failed. Test fail là `test_clipped_bottom_static_object_keeps_true_distance`, của người sửa song song, không phải test của tôi.
- Flaky do môi trường, không do code: nếu không chọn GPU trống, `test_v2_session` (4 test nav live) fail khi onnxruntime CUDA lỗi `bfc_arena` (GPU dùng chung). Lỗi này xuất hiện cả ở lần chạy chưa có code Task 3. `test_v2_calls_routing`/`test_v2_messages` cũng rớt ngẫu nhiên với "Event loop is closed". Chạy riêng lẻ hoặc sau khi đổi GPU thì pass; ở HEAD gốc đã stash vẫn rớt 8/9 một lần. Dùng `CUDA_VISIBLE_DEVICES=<GPU trống>` khi chạy full suite.

## Đã xây

- `config.py`: toàn bộ khối `HAZARD_*` theo brief, đọc bằng `get`, có comment. `HAZARD_LOGIC` mặc định `area`.
- `live/hazard.py`:
  - nạp `HAZARD_CLASSES_JSON` thay `_CLASSES` lúc import;
  - `Hazard.urgent` (`compare=False`);
  - `HazardTracker.assess(dets, t=None, ego=None)` bỏ qua hai tham số mới;
  - `AntiAnnoy(clock, l3_vote, down_hold, bypass_vote)` và `step(level, urgent=False)`;
  - `make_tracker()` / `make_anti()`.
- `live/hazard_geom.py`: `CLASS_HEIGHT_M`, `CLASS_HEIGHT_REL_SIGMA`, `Camera`, `Estimate`, `estimate()`, và thêm `pitch_sample()`.
- `live/hazard_track.py`: `Track`, `TrackSet`. Kalman hai trục tách rời bằng số thực Python (R chéo nên tách được), gán IoU tham lam vector hoá bằng numpy.
- `live/ego_motion.py`: `Ego`, `EgoMeter` (phaseCorrelate 80×60 có cửa sổ Hanning).
- `live/hazard_predict.py`: `PredictParams`, `PredictTracker`. TTE giải kín trên giao hai khoảng thời gian, không lặp từng bước.
- `lanes/nav_live.py`: `process_frame(..., t, meter)`; `run()` dùng `make_tracker/make_anti`, `EgoMeter` chỉ khi `predict`, `t = time.monotonic()`, `anti.step(level, result.urgent)`.

## Chọn lựa khi brief để mở hoặc mâu thuẫn

1. **Ego là góc.** `TrackSet.update(..., ego_shift_rad)`. Theo test `test_ego_shift_removed`, vật đứng yên có X đo tăng khi truyền rad dương, nên cài là **cộng** `Z·rad` vào X của track (dời trạng thái sang hệ camera mới). Tương đương trừ khỏi phép đo; công thức "trừ X của track" trong ruling sẽ làm vX tệ hơn. Có đối chứng âm: không bù thì |vX| > 1.
   - `PredictTracker` đổi `shift_x·w/f`.
   - Thêm kwarg `box_shift_x` (cùng độ trượt theo tỉ lệ bề rộng) để IoU không rớt khi quay nhanh.
   - Thêm `r_scale` và `allow_new` cho ảnh nhoè.
   - `EgoMeter` bỏ shift nếu `response < 0,05` hoặc `|shift| > 0,25`.
2. **Test `Z ∈ {3, 6, 10}` của Task 1 không khả thi:** camera cao 1,6 m, VFOV khoảng 52° nên chân người ở Z < 3,3 m đã chạm mép dưới (đúng ca "bị cắt"). Test dùng `{4, 6, 10}` và thêm test cho vùng bị cắt.
3. **Đáy bị cắt.** Bản của tôi (`9264fea`): `source="near"`, Z kẹp `[0,3; 1,5]`, ca đỉnh vật thấp hơn đường chân trời lấy 1,0. Track đã có ≥ 2 lần thấy thì giữ Z dự đoán kẹp bởi cận `z_max`, X giữ theo góc nhìn. Lý do: nếu lấy cứng Z ≤ 1,5 thì X = góc·Z co về 0 và người đi sượt qua ở X = 1,0 bị coi là trong hành lang (brief đòi pass-by không mức ≥ 2). Công thức "cạnh trên" trong brief dùng chiều cao camera nên sai về vật lý, tôi đã thay bằng `(H − cam_h)·f/(cy − y_top)`.
   - Người sửa song song đã thay cơ chế này bằng tỉ lệ bề rộng (`5206c82`), xem Concern A.
4. **`down_hold`:** luật cũ đã đòi streak ≥ 2 mới hạ `current`, nên `down_hold=2` tương đương cũ; tham số chỉ có tác dụng khi > 2. Test: `down_hold=3`.
5. **`pitch_sample`:** chỉ lấy khi hộp có cả nguồn height lẫn ground, lớp có σ chiều cao ≤ 0,15, Z_height ≥ 3 m. Quy ước dấu `pitch > 0` = cảnh trượt lên, đúng công thức `Z = cam_h·f/(y_đáy − cy + f·tan p)` của brief. Test hội tụ: 0,0296 so với 0,03.
6. **Crossing:** test "ngang vào hành lang ở Z = 4" viết lại thành: người dùng đi 1,2 m/s, người kia đi ngang 1,0 m/s từ X = −3 (Z0 = 6). Hành lang cần Z < 2 nên Z = 4 thuần túy không bao giờ cắt hành lang. Kết quả: mức 2 đầu tiên ở X = −2,25, dir = left.

## Số đo

- `assess` với 20 hộp (máy load ~10): p50 0,50 ms, p90 0,63 ms (trần 1 ms). Trước khi tối ưu (cache `f_px`, bỏ vòng genexpr) là p90 0,88 ms.
- `EgoMeter.measure` trên 320×240: p90 khoảng 1,2 ms (trần 2 ms). Cả hai đo trên ảnh tổng hợp, chưa phải QVGA thật.
- Kịch bản tổng hợp: người đứng yên, người dùng 1,2 m/s từ Z = 12 → mức ≥ 2 đầu ở Z = 5,4; mức 3 ở Z = 3,6 (yêu cầu ≥ 3,8 cho mức ≥ 2). Pass-by 2,4 m/s ở X = +1,0: 42 khung, tối đa mức 1.

## Concern

**A. Có người khác đang sửa/commit cùng worktree `vh-od` song song.** `9264fea` (Task 3) được commit lúc 17:19:05 với đúng tên, email và message theo brief, không phải từ phiên của tôi. Ngay sau đó có `5206c82` và các sửa đổi chưa commit ở `hazard_geom.py`, `hazard_track.py`, `hazard_predict.py`, `config.py`, `hazard.py`, `tests/test_hazard_predict.py`. Cơ chế "đáy bị cắt" thay hẳn bằng `source="clipped"` + `CLASS_WIDTH_M` + tỉ lệ bề rộng, kèm test mới. Tôi không động vào các thay đổi đó và dừng sửa file. Test `test_clipped_bottom_static_object_keeps_true_distance` của họ đang fail ở thời điểm tôi chạy. Controller cần xác định ai đang làm và chốt một nguồn sự thật trước khi tiếp tục Task 4+.

**B.** Thứ tự TDD không đảm bảo hoàn toàn: ở Task 1 và 2 tôi viết test và cài đặt gần như cùng lúc nên không chứng kiến bước "FAIL" riêng cho từng test. Test ego có đối chứng âm; các test còn lại không có mutation-check.

**C. Giới hạn đã biết** (theo thiết kế brief, chưa xử lý):
- Phase-correlate bị lệch khi một vật lớn (xe buýt) chiếm phần lớn khung.
- `vX` Kalman trên dữ liệu thật có nhiễu sẽ khó hơn đường tổng hợp noise-free; `HAZARD_SIGMA_K = 0` đang tắt nới hành lang theo σ.
- Mọi test dùng hộp tổng hợp `_proj`; chưa chạy bàn đo C1b hay ảnh thật.
