# Đề bài Codex: chặn Z trên của hộp bị cắt đáy theo giới hạn nhìn thấy mặt đất

Repo: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-od (git worktree; KHÔNG commit — người điều phối commit).
Python: ~/.venvs/seevia/bin/python. Chỉ sửa: live/hazard_geom.py, live/hazard_track.py, tests/test_hazard_predict.py.

## Vấn đề
Hộp chạm mép dưới ảnh ("clipped") => chân vật nằm dưới hàng ảnh cuối => vật GẦN hơn khoảng nhìn thấy mặt đất gần nhất:
Z_lim = cam.height_m · f / (cam.h − cy + f·tan(pitch_rad))  với cy = cam.h/2 (đúng công thức nguồn "ground" trong `_ground_z` khi y_bot = cam.h).
Hiện tại track mới bị cắt cả đáy lẫn mép bên lấy Z theo bề rộng NHÌN THẤY (hẹp hơn thật) => Z quá xa (nguy hiểm: báo muộn).

## Làm
1. `hazard_geom.py`: thêm field `z_max: float = math.nan` vào `Estimate`; ở nhánh "clipped" của `estimate`, tính
   `z_max = Z_lim · 1.15` (biên 15 % cho sai số cao camera/góc cúi; hằng số tên `_CLIP_Z_MARGIN = 1.15`, comment tiếng Việt)
   và `zw = min(zw, z_max)`. Dùng lại `_ground_z(cam, cam.h, pitch_rad)` nếu nó trả được Z cho y_bot = cam.h; nếu không thì tính trực tiếp.
2. `hazard_track.py`: trong nhánh `est.source == "clipped"` của `update`, nếu `zm` (tỉ lệ bề rộng) không None thì `zm = min(zm, est.z_max)` khi `est.z_max` hữu hạn.
   Trong `_new` (track mới bị cắt): `z = est.z_width` đã được chặn ở bước 1 — giữ nguyên.
3. Test mới trong tests/test_hazard_predict.py (theo kiểu và helper chiếu pin-hole sẵn có trong file):
   - `test_clipped_bottom_and_side_new_track_not_far`: người (H 1,7, W 0,5) ở Z=2,0, X=1,3 sao cho hộp chạm mép dưới VÀ mép phải;
     một khung đầu tiên => track mới có 1,0 ≤ Z ≤ Z_lim·1,15 (tính Z_lim trong test từ camera mặc định).
   - `test_clipped_width_ratio_capped`: track có neo ở Z=6 rồi hộp bị cắt đáy với bề rộng nhỏ bất thường => Z cập nhật ≤ z_max.
4. Chạy `~/.venvs/seevia/bin/python -m pytest tests/test_hazard_predict.py -q` rồi `~/.venvs/seevia/bin/python -m pytest -q`; tất cả phải pass
   (không sửa tests/test_v2_units.py, test_v2_api.py, test_modes_split.py, test_debug_frames.py).
5. Ghi kết quả (file đã sửa, số test trước/sau, output pytest dòng cuối) vào
   /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/plans/sdd-od/codex-clip-report.md

Cấm: sửa file khác; thêm gói; đổi hành vi khi HAZARD_LOGIC=area. Không hỏi lại.
