# HAZARD — Vật cản (C1a phát hiện · C1b logic · C1c độ trễ)

Sinh tự động bởi `bench/report_hazard.py` từ JSON mới nhất trong `results/hazard/`. Đây là **baseline đo, không phải cải tiến**.

## C1a — Phát hiện vật cản (Obstacle-Dataset test)

Nguồn: `results/hazard/20261020-2045_detect.json` · 2026-10-20T20:45:07 · 1583 ảnh · ONNX đầu vào tĩnh [1, 3, 320, 320]: chỉ 320.

Dữ liệu: Obstacle-Dataset (Tang et al., *A dataset for the recognition of obstacles on blind sidewalk*, Universal Access in the Information Society 22(1):69–82, 2023; online 2021), tập TEST, 15 lớp, nhãn VOC. Model: `live.hazard.OnnxYolo.detect` (YOLO11n COCO, ONNX tĩnh 320). **Số chính = nhóm `non_coco`** (tên file 6–9 chữ số: VOC + ảnh tác giả tự thu); nhóm `coco` (tên 12 chữ số = id COCO, có thể nằm trong train của YOLO) báo riêng để thấy mức thổi phồng.

Metric chính: **recall@IoU0,5 không phân lớp** của hộp GT **trong lối đi** (tâm x∈[0,3;0,7], diện tích chuẩn hoá ≥0,02), ngưỡng vận hành score ≥0,35. CI 95 % bootstrap theo ảnh. Hộp `difficult` bị loại.

### imgsz 320

| nhóm | biến thể | ảnh | GT trong lối | **recall trong lối (không phân lớp)** | recall trong lối (đúng lớp, 9 lớp ánh xạ) | recall mọi hộp | precision vận hành (đúng lớp) | mAP@0,5 (9 lớp) |
|---|---|---|---|---|---|---|---|---|
| non_coco (**chính**) | orig | 738 | 775 | **42.8 % [38.6–47.1]** | 73.0 % [67.0–79.4] | 20.8 % [18.7–23.1] | 62.5 % [59.1–66.1] | 0.273 [0.244–0.337] (8 lớp) |
| non_coco (**chính**) | glass | 738 | 775 | **37.3 % [33.4–41.0]** | 60.1 % [53.5–66.3] | 15.7 % [14.0–17.6] | 56.9 % [52.8–61.2] | 0.213 [0.184–0.267] (8 lớp) |
| coco | orig | 845 | 973 | **67.1 % [64.1–70.0]** | 73.1 % [70.0–76.2] | 31.1 % [29.3–32.7] | 88.9 % [87.3–90.3] | 0.524 [0.498–0.552] (9 lớp) |
| coco | glass | 845 | 973 | **51.3 % [48.1–54.3]** | 54.2 % [50.5–57.7] | 21.7 % [20.2–23.1] | 85.6 % [83.8–87.6] | 0.391 [0.362–0.419] (9 lớp) |
| all | orig | 1583 | 1748 | **56.4 % [53.6–59.0]** | 73.1 % [70.3–75.8] | 26.9 % [25.6–28.3] | 80.3 % [78.7–82.1] | 0.469 [0.450–0.492] (9 lớp) |
| all | glass | 1583 | 1748 | **45.1 % [42.5–47.5]** | 55.5 % [52.5–58.6] | 19.3 % [18.2–20.4] | 75.9 % [73.9–78.0] | 0.342 [0.325–0.363] (9 lớp) |

Ghép đôi `orig` → `glass` (QVGA + JPEG q15) theo hộp GT trong lối đi (CI của Δ bootstrap theo ảnh):

| nhóm | hộp | recall orig | recall glass | Δ | CI Δ | orig bắt, glass trượt | glass bắt, orig trượt |
|---|---|---|---|---|---|---|---|
| non_coco | 775 | 42.8 % | 37.3 % | -5.5 đ.% | [-8.3, -3.0] | 77 | 34 |
| coco | 973 | 67.1 % | 51.3 % | -15.8 đ.% | [-18.5, -13.5] | 162 | 8 |

Theo lớp — nhóm `non_coco`, biến thể `glass` (6 lớp ngoài COCO: `reflective_cone`, `warning_column`, `spherical_roadblock`, `ashcan`, `pole`, `tricycle` — recall không phân lớp > 0 chỉ do detector COCO gán nhầm lớp khác; đúng lớp = 0 theo thiết kế):

| lớp | GT (không difficult) | GT trong lối | recall trong lối (không phân lớp) | recall mọi hộp (không phân lớp) | AP@0,5 |
|---|---|---|---|---|---|
| stop_sign | 0 | 0 | — | — | — |
| person | 699 | 83 | 73.5 % [62.7–82.7] | 24.9 % [20.5–29.7] | 0.319 [0.266–0.370] |
| bicycle | 119 | 48 | 77.1 % [64.7–88.1] | 42.0 % [31.9–52.7] | 0.446 [0.323–0.550] |
| bus | 59 | 32 | 75.0 % [59.4–88.9] | 57.6 % [44.9–70.7] | 0.448 [0.306–0.601] |
| truck | 38 | 4 | 50.0 % [0.0–100.0] | 15.8 % [3.4–29.6] | 0.026 [0.009–0.056] |
| car | 446 | 45 | 55.6 % [41.1–70.0] | 29.1 % [24.2–34.6] | 0.347 [0.291–0.408] |
| motorbike | 288 | 21 | 28.6 % [10.5–50.0] | 8.7 % [5.4–12.6] | 0.046 [0.027–0.080] |
| reflective_cone | 594 | 99 | 12.1 % [6.3–19.3] | 4.5 % [2.8–6.5] | ngoài COCO |
| ashcan | 270 | 150 | 4.7 % [1.4–8.5] | 3.0 % [1.1–5.2] | ngoài COCO |
| warning_column | 507 | 46 | 6.5 % [0.0–14.5] | 5.9 % [3.3–9.1] | ngoài COCO |
| spherical_roadblock | 303 | 53 | 9.4 % [1.9–20.0] | 3.3 % [1.4–5.3] | ngoài COCO |
| pole | 321 | 37 | 0.0 % [0.0–0.0] | 0.0 % [0.0–0.0] | ngoài COCO |
| dog | 2 | 0 | — | 0.0 % [0.0–0.0] | 0.000 [0.000–0.000] |
| tricycle | 207 | 157 | 68.2 % [60.4–75.3] | 55.1 % [47.4–62.7] | ngoài COCO |
| fire_hydrant | 15 | 0 | — | 6.7 % [0.0–23.1] | 0.067 [0.000–0.250] |

Theo lớp — nhóm `non_coco`, biến thể `orig` (6 lớp ngoài COCO: `reflective_cone`, `warning_column`, `spherical_roadblock`, `ashcan`, `pole`, `tricycle` — recall không phân lớp > 0 chỉ do detector COCO gán nhầm lớp khác; đúng lớp = 0 theo thiết kế):

| lớp | GT (không difficult) | GT trong lối | recall trong lối (không phân lớp) | recall mọi hộp (không phân lớp) | AP@0,5 |
|---|---|---|---|---|---|
| stop_sign | 0 | 0 | — | — | — |
| person | 699 | 83 | 79.5 % [69.1–89.6] | 35.5 % [30.3–41.4] | 0.437 [0.377–0.493] |
| bicycle | 119 | 48 | 85.4 % [75.0–94.3] | 50.4 % [39.4–61.8] | 0.540 [0.414–0.651] |
| bus | 59 | 32 | 90.6 % [78.6–100.0] | 76.3 % [63.2–87.2] | 0.538 [0.393–0.689] |
| truck | 38 | 4 | 75.0 % [0.0–100.0] | 26.3 % [12.9–40.0] | 0.048 [0.017–0.096] |
| car | 446 | 45 | 71.1 % [57.4–83.3] | 42.6 % [36.4–49.6] | 0.485 [0.417–0.556] |
| motorbike | 288 | 21 | 57.1 % [33.3–82.4] | 16.3 % [11.7–22.3] | 0.105 [0.067–0.160] |
| reflective_cone | 594 | 99 | 7.1 % [2.2–13.0] | 5.2 % [3.1–7.6] | ngoài COCO |
| ashcan | 270 | 150 | 5.3 % [2.2–9.3] | 3.3 % [1.3–5.9] | ngoài COCO |
| warning_column | 507 | 46 | 2.2 % [0.0–7.9] | 3.4 % [1.6–5.6] | ngoài COCO |
| spherical_roadblock | 303 | 53 | 1.9 % [0.0–6.1] | 1.3 % [0.3–2.8] | ngoài COCO |
| pole | 321 | 37 | 0.0 % [0.0–0.0] | 0.0 % [0.0–0.0] | ngoài COCO |
| dog | 2 | 0 | — | 0.0 % [0.0–0.0] | 0.000 [0.000–0.000] |
| tricycle | 207 | 157 | 84.1 % [78.1–89.7] | 68.1 % [60.3–75.6] | ngoài COCO |
| fire_hydrant | 15 | 0 | — | 6.7 % [0.0–23.1] | 0.035 [0.000–0.217] |

Recall trong lối (glass) theo nguồn ảnh: voc: 74.3 % [66.9–81.7] (n_hộp=140, 97 ảnh); self: 29.1 % [25.3–33.3] (n_hộp=635, 641 ảnh).

Trần khi bỏ ngưỡng 0,35 (score ≥0,001), non_coco/glass: 72.3 % [68.4–76.3] — phần chênh với số chính là hộp bị ngưỡng vận hành cắt.

Đối chứng âm (ghép detection của ảnh i với GT của ảnh i+1): recall trong lối non_coco/glass = 12.6 % [10.3–15.3] so với số thật 37.3 % [33.4–41.0]. Không về 0 vì vật lớn ở giữa ảnh dễ trùng IoU ≥0,5 ngẫu nhiên — đây là mức chance; số thật phải cao hơn rõ.

Độ trễ `detect()` mỗi ảnh (glass), warm-up 20:

| chặng | n | p50 ms | p90 ms | p99 ms |
|---|---|---|---|---|
| detect (GPU) | 1583 | 5.2 | 5.69 | 6.47 |

Kiểm nội bộ: số ảnh mà lượt vận hành khác lượt AP (lọc ≥0,35) = 0; tên GT bị bỏ: {}; provider `CUDAExecutionProvider`.

GPU lúc bắt đầu/kết thúc: `[{'index': 0, 'name': 'NVIDIA GeForce RTX 2080 Ti', 'mem_used_mib': 7, 'mem_total_mib': 11264, 'util_pct': 0}]` → `[{'index': 0, 'name': 'NVIDIA GeForce RTX 2080 Ti', 'mem_used_mib': 171, 'mem_total_mib': 11264, 'util_pct': 0}]` (CUDA_VISIBLE_DEVICES=0).

## C1b — Logic mức + cảnh báo (`HazardTracker` + `AntiAnnoy`, baseline)

Nguồn: `results/hazard/20261020-2046_logic.json` · 2026-10-20T20:46:03 · 50 seed × 24 loại kịch bản.

Dữ liệu: **tổng hợp** (không có benchmark công khai cho cảnh báo va chạm theo thời gian). Chuỗi hộp 8 fps từ camera pin-hole 320×240, HFOV 66.0°, cao 1.6 m, nhìn thẳng. Nhãn đúng bằng hình học: `t_danger` = khung đầu tiên khoảng cách < 2.0 m **và** |lệch ngang| < 0.6 m. "Kịp thời" = bíp mức ≥2 đầu tiên trước `t_danger` ≥ 1.5 s. Mô phỏng đúng đường nóng: `assess` → mức < HAZARD_MIN_LEVEL(2) coi là 0 → `AntiAnnoy.step`, đồng hồ giả 125 ms/khung. CI bootstrap theo kịch bản.

### Tóm tắt (gộp đều các loại — mỗi loại cùng số seed nên tỉ trọng là do thiết kế bộ kịch bản, đọc bảng theo loại bên dưới)

- **Tỉ lệ cảnh báo kịp thời** (kịch bản nguy hiểm, n=600): **8.3 % [6.0–10.3]**; trượt (không bíp trước t_danger): 28.7 % [25.0–32.3]; muộn: 63.0 %.
- Lead time (kịch bản có bíp, n=428): p50 0.38 s, p90 4.25 s.
- **Báo nhầm/phút** (kịch bản an toàn, n=600, 92.0 phút): 0.54 [0.42–0.68] (50 bíp); kịch bản an toàn có ≥1 bíp: 8.3 % [6.3–10.5].
- Số lần gửi / kịch bản: 0.70; số lần đổi mức gửi đi / kịch bản: 0.13; số lần đổi mức theo khung / kịch bản: 4.24.

### Theo loại kịch bản

| loại | nhãn | n | kịp thời | trượt | lead p50 (s) | báo nhầm/phút | bíp/kịch bản |
|---|---|---|---|---|---|---|---|
| walk_static_person | nguy hiểm | 50 | 0 % [0–0] | 0 % [0–0] | 0.38 | — | 1.46 |
| walk_static_pole | nguy hiểm | 50 | 0 % [0–0] | 100 % [100–100] | — | — | 0.64 |
| walk_static_car | nguy hiểm | 50 | 100 % [100–100] | 0 % [0–0] | 4.25 | — | 4.00 |
| walk_static_bench | nguy hiểm | 50 | 0 % [0–0] | 100 % [100–100] | — | — | 0.00 |
| oncoming_person | nguy hiểm | 50 | 0 % [0–0] | 0 % [0–0] | 0.12 | — | 1.30 |
| motorbike_charge | nguy hiểm | 50 | 0 % [0–0] | 0 % [0–0] | 0.38 | — | 1.00 |
| cross_person | an toàn | 50 | — | — | — | 0.00 (0 bíp/3.5 phút) | 0.00 |
| cross_motorbike | an toàn | 50 | — | — | — | 0.00 (0 bíp/1.0 phút) | 0.00 |
| far_static_person | an toàn | 50 | — | — | — | 0.00 (0 bíp/10.3 phút) | 0.00 |
| far_static_car | an toàn | 50 | — | — | — | 0.00 (0 bíp/10.3 phút) | 0.00 |
| edge_static_person | an toàn | 50 | — | — | — | 0.00 (0 bíp/9.9 phút) | 0.00 |
| edge_static_car | an toàn | 50 | — | — | — | 5.13 (50 bíp/9.7 phút) | 1.00 |
| walk_static_person+shake | nguy hiểm | 50 | 0 % [0–0] | 0 % [0–0] | 0.25 | — | 1.38 |
| walk_static_person+flicker | nguy hiểm | 50 | 0 % [0–0] | 34 % [22–46] | 0.38 | — | 1.56 |
| oncoming_person+shake | nguy hiểm | 50 | 0 % [0–0] | 40 % [26–54] | 0.12 | — | 1.34 |
| oncoming_person+flicker | nguy hiểm | 50 | 0 % [0–0] | 54 % [40–68] | 0.12 | — | 1.08 |
| motorbike_charge+shake | nguy hiểm | 50 | 0 % [0–0] | 0 % [0–0] | 0.38 | — | 1.16 |
| motorbike_charge+flicker | nguy hiểm | 50 | 0 % [0–0] | 16 % [6–26] | 0.38 | — | 0.88 |
| far_static_car+shake | an toàn | 50 | — | — | — | 0.00 (0 bíp/10.0 phút) | 0.00 |
| far_static_car+flicker | an toàn | 50 | — | — | — | 0.00 (0 bíp/9.8 phút) | 0.00 |
| edge_static_person+shake | an toàn | 50 | — | — | — | 0.00 (0 bíp/10.2 phút) | 0.00 |
| edge_static_person+flicker | an toàn | 50 | — | — | — | 0.00 (0 bíp/10.3 phút) | 0.00 |
| cross_person+shake | an toàn | 50 | — | — | — | 0.00 (0 bíp/3.5 phút) | 0.00 |
| cross_person+flicker | an toàn | 50 | — | — | — | 0.00 (0 bíp/3.5 phút) | 0.00 |

### Độ trễ

- `assess()+step()` mỗi khung (CPU, 90340 khung): p50 3.44 µs, p90 4.35 µs, p99 5.42 µs (≪ 1 ms).
- **Trễ thuật toán** (khung chờ xác nhận từ đầu đoạn liên tiếp mức ≥2 đến bíp đầu × 125 ms; n=568 kịch bản có bíp): p50 125.0 ms, p90 125.0 ms, p99 125.0 ms.

### Đối chứng (kiểm bàn đo không gian lận)

| đối chứng | kỳ vọng | kết quả | đạt |
|---|---|---|---|
| positive_control_motorbike_charge | baseline có bíp trước t_danger ở >= 90% seed | {'beep_before_danger_rate': 1.0} | đạt |
| negative_control_far_static | 0 bíp | {'total_beeps': 0} | đạt |
| sabotage_dead_pipeline | kịp thời = 0 | {'timely': 0.0} | đạt |
| sabotage_always_level3 | mọi kịch bản an toàn bị bíp | {'safe_with_beep': 1.0} | đạt |

### Giả định của bộ kịch bản (đọc trước khi dùng số)

- Kích thước vật (cao×rộng m): {'person': ['person', 1.7, 0.5], 'motorbike': ['motorbike', 1.1, 0.8], 'car': ['car', 1.5, 1.8], 'pole': ['parking_meter', 3.0, 0.15], 'bench': ['bench', 0.45, 1.5]}. Cột = `parking_meter`, ghế đá = `bench` (kind tĩnh COCO gần nhất) — detector COCO thật **không thấy cột** (xem C1a); C1b kiểm logic với detector lý tưởng.
- Hộp nhỏ hơn 4 px (ở 320×240) coi là detector không thấy. Đầu lắc: ±10 % kích thước, ±5 % **kích thước hộp** cho vị trí. Chập chờn: mỗi khung mất detection với xác suất 0.33. Score ngẫu nhiên [0.4, 0.9] (logic mức không dùng score).
- Tốc độ "xe máy 4 m/s" hiểu là **tốc độ tiến lại gần tổng cộng** (người ngược chiều 2,4 m/s cũng là tổng, theo PLAN). Vật tiến thẳng có lệch ngang ngẫu nhiên U(−0,4; 0,4) m — luôn trong lối.
- "Trong lối" của nhãn dùng lệch ngang của **tâm** vật (|X| < 0,6 m), không tính bề rộng vật.
- Không có benchmark công khai cho TTC người đi bộ — **không có baseline công bố để đối chiếu C1b**.

## C1c — Độ trễ đường nóng phía server

Nguồn: `results/hazard/20261020-2045_latency.json` · 2026-10-20T20:45:57 · ONNX đầu vào tĩnh: chỉ 320. Ảnh Obstacle-Dataset thu rộng 320 giữ tỉ lệ + JPEG q15 (như kính gửi); một tracker xuyên suốt, thứ tự ảnh cố định (seed 0). Không gồm mạng/kính/Cloudflare.

### imgsz 320 (1583 khung, provider `CUDAExecutionProvider`)

| chặng | n | p50 ms | p90 ms | p99 ms |
|---|---|---|---|---|
| decode JPEG (cv2.imdecode) | 1583 | 0.45 | 0.73 | 0.9 |
| detect (OnnxYolo) | 1583 | 6.49 | 7.37 | 8.76 |
| assess | 1583 | 0.02 | 0.02 | 0.04 |
| AntiAnnoy.step | 1583 | 0.0 | 0.0 | 0.0 |
| **tổng 4 chặng** | 1583 | 7.01 | 7.95 | 9.53 |
| đối chiếu: `nav_live.process_frame`+step | 1583 | 5.96 | 6.83 | 7.54 |

assess p50/p90/p99 = 15.6/24.6/35.3 µs; step = 2.5/3.4/4.8 µs. JPEG q15 trung bình 6063 byte.
Ngân sách server p90 ≤ 10.0 ms: p90 tổng = 7.95 ms → **trong ngân sách**.

GPU lúc bắt đầu `[{'index': 0, 'name': 'NVIDIA GeForce RTX 2080 Ti', 'mem_used_mib': 7, 'mem_total_mib': 11264, 'util_pct': 1}]` → kết thúc `[{'index': 0, 'name': 'NVIDIA GeForce RTX 2080 Ti', 'mem_used_mib': 171, 'mem_total_mib': 11264, 'util_pct': 39}]` (CUDA_VISIBLE_DEVICES=0); GPU có thể đang chia sẻ — đọc util trước khi so với mốc cũ (4,90/5,26 ms).

## Baseline công bố (chép từ bài gốc)

Đối chiếu ngày 2026-10-20. **Chưa đối chiếu được bài gốc của dataset**: Tang et al., UAIS 22(1):69–82 (doi 10.1007/s10209-021-00837-9) — trang Springer chuyển hướng đăng nhập, không đọc được bảng; repo `github.com/TW0521/Obstacle-Dataset` có README (train 5.066 / test 1.583 / val 1.266, 15 lớp) nhưng **không đăng kết quả mAP**. → *chưa đối chiếu*.

Bài dùng dataset làm baseline: He & Saha, *Investigating YOLO Models Towards Outdoor Obstacle Detection For Visually Impaired People*, arXiv:2312.07571 (10/2023). **Đã đối chiếu với PDF** (người dùng chép Table 1–7 từ PDF, 2026-10-20; khớp toàn bộ số trích trước đó qua HTML). **Table 6** (tổng thể, 15 lớp):

| Model (huấn luyện trên train của Obstacle-Dataset) | Precision@0,5 | Recall@0,5 | mAP@0,5 |
|---|---|---|---|
| YOLOv5 | 0,781 | 0,682 | 0,742 |
| YOLOv6 | 0,786 | 0,714 | 0,784 |
| **YOLOv7** (tốt nhất) | 0,786 | 0,778 | **0,817** |
| YOLOv8 | 0,80 | 0,682 | 0,758 |
| YOLO-NAS-S | 0,7888 | 0,5941 | 0,6673 |
| YOLO-NAS-M | 0,7875 | 0,6206 | 0,6906 |
| YOLO-NAS-L | 0,7853 | 0,6274 | 0,698 |

mAP@0,5 theo lớp (Table 3 YOLOv7, Table 4 YOLOv8; 1.262 ảnh, 7.938 nhãn) — đặt cạnh AP@0,5 zero-shot của SeeVia ở bảng theo lớp phía trên:

| Lớp | YOLOv7 | YOLOv8 | Lớp | YOLOv7 | YOLOv8 |
|---|---|---|---|---|---|
| stop_sign | 0,874 | 0,832 | reflective_cone | 0,944 | 0,896 |
| person | 0,749 | 0,677 | ashcan | 0,904 | 0,870 |
| bicycle | 0,728 | 0,624 | warning_column | 0,898 | 0,872 |
| bus | 0,800 | 0,659 | spherical_roadblock | 0,958 | 0,953 |
| truck | 0,626 | 0,542 | pole | 0,642 | 0,625 |
| car | 0,764 | 0,700 | tricycle | 0,947 | 0,916 |
| motorbike | 0,727 | 0,685 | dog | 0,822 | 0,717 |
| fire_hydrant | 0,871 | 0,807 | | | |

Lưu ý về chính bài: (1) các bảng ghi **1.262 ảnh** — gần với tập **val** (README: 1.266) chứ không phải test 1.583 mà SeeVia đo → **khác tập chấm**; (2) mâu thuẫn nội bộ nhỏ: YOLOv8 recall 0,683 (Table 4) vs 0,682 (Table 6); YOLO-NAS-M Table 5 (P 0,7589 / R 0,6148 / mAP 0,6829) vs Table 6 (0,7875 / 0,6206 / 0,6906); (3) Table 7: ngưỡng score 0,3 → 0,7 đổi recall YOLO-NAS-L 0,785 → 0,456 — cùng hiện tượng ngưỡng 0,35 cắt recall ở SeeVia.

`METRICS.md` còn trích PMC 11645096 (YOLO-OD): bài đó dùng **bộ dữ liệu khác** (6.276 ảnh, 4 lớp: car, person, traffic cone, pothole; nguồn Baidu AI Studio) — **không phải** Obstacle-Dataset, không dùng làm baseline ở đây.

## Giới hạn / không so trực tiếp được

- **Không so ngang hàng với baseline bài**: bài huấn luyện YOLO trên train của Obstacle-Dataset (có cả 6 lớp ngoài COCO), SeeVia dùng YOLO11n COCO **zero-shot**; mAP của ta chỉ tính 9 lớp ánh xạ được, ngưỡng AP quét 0,001–1, NMS 0,45 của VH.
- Nhóm `coco` có thể đã nằm trong dữ liệu huấn luyện YOLO11n (COCO train2017) → số đẹp giả; chỉ `non_coco` là số trung thực. Nguồn `voc` cũng là PASCAL VOC (không nằm trong COCO train nhưng cùng phân phối).
- Recall/precision phụ thuộc ngưỡng vận hành 0,35 của `config.HAZARD_MIN_SCORE`; AP dùng ngưỡng 0,001 bằng cách đặt tạm `config.HAZARD_MIN_SCORE` (không sửa file VH).
- Ảnh `glass` giữ tỉ lệ gốc, rộng 320; kính thật gửi QVGA 320×240 (có thể khác tỉ lệ).
- C1b là kiểm chứng LOGIC trên dữ liệu tổng hợp với detector lý tưởng (mọi vật trong ảnh đều được thấy, hộp hoàn hảo trừ nhiễu mô phỏng) — không thay dữ liệu thật; không có baseline công bố.
- C1c chỉ đo phía server (decode → detect → assess → step); chưa gồm mạng, kính, Cloudflare. GPU dùng chung nên p99 có thể nhiễu.
- Phạm vi: chỉ đo baseline, không thử cải tiến (PLAN, bổ sung 2026-10-20).
