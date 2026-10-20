# C5 — Cổng chất lượng ảnh (VizWiz-QualityIssues val)

Nguồn: `results/quality_vizwiz/20261020-2043_full.json` (chạy 2026-10-20T20:43:41, VH `ece963b`, host gpu156).

## Dữ liệu và cách chấm

- Tập: VizWiz-QualityIssues **val** (Chiu, Zhao, Gurari, *Assessing Image Quality Issues for Real-World Problems*, CVPR 2020, arXiv 2003.12511), ảnh do người khiếm thị chụp. Dùng 7750 ảnh (val đủ = 7.750); 0 ảnh `measure()` trả None.
- Nhãn dương = >= 3/5 người gán lỗi đó (DRK, BRT, BLR) hoặc `unrecognizable`.
- Đường chạy: `pipeline.image_quality.measure()` + `check()` của VH, ngưỡng hiện tại `IMAGE_MIN_BRIGHTNESS=30.0`, `IMAGE_MAX_BRIGHTNESS=235.0`, `IMAGE_MIN_SHARPNESS=5.0`. Thiết bị: CPU (numpy+PIL, như production).
- Ánh xạ: TỐI <-> DRK, CHÓI <-> BRT, MỜ <-> BLR. Intent không-money: `need_sharpness=False` (chỉ luật sáng/tối); money: thêm luật nét.
- Mọi số kèm [CI 95 %] bootstrap 1.000 lần theo ảnh.

## Metric chính — chụp lại OAN

OAN = ảnh bị từ chối vì lỗi R mà đa số (>= 3/5) người gán nói KHÔNG có lỗi R.

| Intent | Tỉ lệ bị từ chối | **Chụp lại oan (trên mọi ảnh)** | Oan / số bị từ chối | Từ chối nhưng ảnh không `unrecognizable` |
|---|---|---|---|---|
| không-money (sáng/tối) | 2.37 % [2.04; 2.71] | **0.46 % [0.32; 0.62]** (36/7750) | 19.6 % | 0.43 % [0.28; 0.58] |
| money (+ độ nét) | 2.83 % [2.45; 3.19] | **0.63 % [0.46; 0.80]** (49/7750) | 22.4 % | 0.53 % [0.37; 0.70] |

Phân theo lý do (số ảnh bị từ chối / số oan): nomoney: DRK 148/27, BRT 36/9, BLR 0/0; money: DRK 148/27, BRT 36/9, BLR 35/13.

## Precision / recall / F1 ở ngưỡng hiện tại

| Lỗi (luật) | n dương | n bị bắt | Precision | Recall | F1 |
|---|---|---|---|---|---|
| TỐI (DRK) | 219 | 148 | 81.76 % [75.54; 87.59] | 55.25 % [49.19; 62.05] | 65.94 % [60.75; 71.58] |
| CHÓI (BRT) | 200 | 36 | 75.00 % [61.54; 87.50] | 13.50 % [8.84; 18.52] | 22.88 % [15.63; 30.26] |
| MỜ (BLR) — chỉ money | 2318 | 96 | 34.38 % [25.27; 44.00] | 1.42 % [0.95; 1.97] | 2.73 % [1.82; 3.76] |

Ghi chú: MỜ ở bảng trên tính luật nét như thể áp cho mọi ảnh (chỉ intent money dùng thật).

## AUROC của điểm sáng / nét (không phụ thuộc ngưỡng)

| Điểm -> nhãn | AUROC | n dương |
|---|---|---|
| brightness_vs_DRK | 0.908 [0.885; 0.931] | 219 |
| brightness_vs_BRT | 0.606 [0.561; 0.653] | 200 |
| sharpness_vs_BLR | 0.612 [0.598; 0.626] | 2318 |
| sharpness_vs_unrecognizable | 0.718 [0.695; 0.739] | 751 |

Recall ảnh `unrecognizable` (vô dụng thật) mà cổng bắt: nomoney 20.11 % [17.29; 23.31] (n dương 751); money 23.70 % [20.53; 26.88] (n dương 751).

## Ngưỡng tối ưu F1: chọn trên nửa A (seed 0), báo trên nửa B

| Lỗi | Ngưỡng hiện tại | Ngưỡng chọn trên A | F1 trên B (hiện tại) | F1 trên B (chọn từ A) | Recall B (hiện tại -> chọn) |
|---|---|---|---|---|---|
| DRK | 30.0 | 35.3 | 67.05 % [58.62; 74.45] | 67.03 % [58.48; 74.51] | 55.7 % [46.3; 64.6] -> 58.5 % [48.8; 67.3] |
| BRT | 235.0 | 185.9 | 28.10 % [16.67; 39.07] | 38.41 % [27.20; 48.65] | 17.2 % [9.7; 25.8] -> 29.3 % [20.0; 38.5] |
| BLR | 5.0 | 438.1 | 3.19 % [1.84; 4.72] | 47.43 % [45.51; 49.32] | 1.7 % [1.0; 2.5] -> 89.2 % [87.3; 91.1] |

Đọc: CI hai cột F1 không chồng nhau mới đáng tin là ngưỡng khác tốt hơn. Cổng cố ý chỉ chặn outlier cực đoan (docstring `image_quality.py`) nên F1 thấp ở ngưỡng hiện tại là THIẾT KẾ, không phải lỗi; metric an toàn là oan.

## Độ trễ

`measure()` mỗi ảnh (CPU, ảnh gốc, n=7750): **p50 36.6 ms / p90 59.57 ms / p99 157.38 ms** (mean 41.85, max 229.16).
Kích thước ảnh VizWiz trung vị 968x1296 (ảnh kính là 1600x1200, 1,92 MP) và 394 KB — đo ở ĐỘ PHÂN GIẢI GỐC của VizWiz, không phải 1600x1200 của kính. Tải CPU lúc chạy (loadavg) không kiểm soát được, p99 dễ nhiễu.

## Baseline công bố (chép từ bài gốc, đã mở PDF arXiv 2003.12511v2)

Chiu et al., CVPR 2020. **Phân loại lỗi — Table 4 (Supplementary, mục 8, PDF trang 12)**, mô hình Xception huấn luyện có giám sát:

| Phương pháp | Chỉ số | BLR | BRT | DRK |
|---|---|---|---|---|
| Xception | precision | 80.1 | 62.9 | 58.5 |
| Xception | recall | 80.1 | 49.8 | 57.3 |
| Xception | F1 | 80.1 | 55.6 | 57.9 |
| Random guessing | F1 | 40.4 | 4.5 | 7.0 |

**Unrecognizable — Table 1 (mục 4.2, PDF trang 6):** ResNet-152 AP 80.0 / recall 75.1 / F1 71.2; SIFT 87.2 / 42.3 / 56.9; HOG+SVM 56.4 / 41.2 / 47.6; random 16.6 / 14.6 / 15.5.
Chia tập trong bài: 52,5 % / 37,5 % / 10 % trên 39.181 ảnh (train/val/test).

## Giới hạn / không so trực tiếp được

- Baseline là **CNN học có giám sát** trên train của chính bộ này; cổng SeeVia là 2 phép đo thủ công (Laplacian, độ sáng trung bình) đặt ngưỡng **cực đoan có chủ ý**. F1 của ta thấp hơn là điều mong đợi; so sánh có ý nghĩa là AUROC (ngưỡng-độc-lập) và tỉ lệ oan, chứ không phải F1.
- Ta chấm trên **val công khai** (7.750), bài chấm trên phần test riêng (10 % của 39.181, không công bố nhãn) → khác tập; cách chuyển nhãn cũng khác (bài dùng đa số của 5 người cho nhãn nhị phân, ta cũng vậy nhưng ngưỡng >= 3 là quy ước của ta).
- BLR của VizWiz đo "mờ" cảm nhận bởi người; nhãn không phụ thuộc loại máy. Ảnh VizWiz do điện thoại chụp, khác camera kính (1600x1200, đặc trưng sharpness thấp hệ thống — docstring module).
- Độ trễ đo ở độ phân giải VizWiz, không phải ảnh kính; ngưỡng sharpness 5 được đặt cho ảnh kính nên có thể không tương thích phân bố VizWiz (xem AUROC).
- Không đánh giá được cổng ở intent `hazard`/`find` riêng; cả ba intent không-money dùng chung luật sáng/tối.
