# Kết quả Codex: chặn Z cho hộp cắt đáy

## Thay đổi

- `live/hazard_geom.py`: thêm `Estimate.z_max`, giới hạn `z_width` của detection cắt đáy ở giới hạn mặt đất nhân biên 15%.
- `live/hazard_track.py`: giới hạn phép đo Z từ tỉ lệ bề rộng theo `est.z_max` khi giới hạn hữu hạn; khởi tạo track mới tiếp tục dùng `est.z_width` đã chặn.
- `tests/test_hazard_predict.py`: thêm hai regression test cho track mới cắt đáy và cạnh phải, cùng cập nhật tỉ lệ bề rộng bị chặn.

Không sửa `test_v2_units.py`, `test_v2_api.py`, `test_modes_split.py`, `test_debug_frames.py` hay thêm gói.

## Số test

- `tests/test_hazard_predict.py`: trước có 37 test; thêm 2, tổng sau là 39.
- Sau thay đổi, pytest thu thập được 686 test toàn repo khi môi trường `nvidia-smi` được xử lý để báo không có GPU.

## Kiểm chứng

- RED: hai regression test mới thất bại trước implementation (track mới Z=4.019 m vượt giới hạn 3.778 m; track estimate chưa có `z_max`).
- GREEN: `~/.venvs/seevia/bin/python -m pytest tests/test_hazard_predict.py -q` — **39 passed**.
- `~/.venvs/seevia/bin/python -m pytest -q` — dừng khi thu thập tại `evaluations/bench/test_hazard.py`; `nvidia-smi` trên máy không kết nối được NVIDIA driver, nên hàm `_gpus()` cố phân tích thông báo lỗi driver như một hàng CSV.
- Đã thử chạy suite với `nvidia-smi` stub rỗng trong `/tmp` để phản ánh môi trường không GPU; lần chạy không tạo thêm đầu ra trong thời gian dài và đã được dừng, nên không tính là kết quả pass.

Các dòng cuối pytest:

```text
39 passed in 0.93s
```

```text
4 warnings, 1 error in 1.69s
```
