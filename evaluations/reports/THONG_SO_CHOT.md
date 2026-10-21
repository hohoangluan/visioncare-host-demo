# THÔNG SỐ CHỐT AI — 2026-10-21

Nhánh `chot-ai-2026-10-21` (gộp `vqa-hoi-anh`, `ocr-tien`, `od-du-doan` vào `app-giao-tiep`). Env: `reports/thong_so_chot.env`.
Baseline = `reports/TONG_HOP.md` (2026-10-20). Lượt chốt gọi model mới (cache tag `chot20261021`, không dùng cache cũ).
Phần trăm theo thang 0–100, CI 95 % bootstrap khi có; trễ p50 / p90 (ms). Δ = chốt − baseline.

## 1. Thông số chốt

| Biến | Giá trị | Chọn ở đâu (tập dev) | Số test chính |
|---|---|---|---|
| `HAZARD_MODEL_PATH` | `evaluations/train/models/ft_11s_last_320.onnx` | `HAZARD_MODELS.md` (val Obstacle-Dataset) | C1a recall trong lối 89,9 % |
| `HAZARD_CLASSES_JSON` | `evaluations/train/classes_vh.json` | lớp của model fine-tune | — |
| `HAZARD_MIN_SCORE` | 0,35 | `HAZARD.md` | — |
| `HAZARD_LOGIC` | **`area`** (giữ logic cũ) | C1b: predict vòng 1 và vòng 2 đều `selected = null` (mục 3.2) | — |
| `MONEY_MODE` | `choice` | `MONEY_OCR_CAI_TIEN.md` | — |
| `MONEY_MIN_PROB` / `MONEY_RETRY_PROB` | 0,999 / 0,999 | `MONEY_OCR_CAI_TIEN.md` | sai 2,7 %, đúng 65,8 % (có hướng dẫn + đọc lại) |
| `MONEY_RETRY` | 1 (đọc lại đúng một lần) | `MONEY_OCR_CAI_TIEN.md` | lượt đọc chắc Δ trễ ±1 ms, CI chứa 0 |
| `MONEY_MULTI_MIN_PROB` | 0,98 | 3 khung B3 | — |
| `OCR_DIGIT_HEDGE_PROB` | 0,9 | `MONEY_OCR_CAI_TIEN.md`, `OCR.md` | — |
| Intent `ask` (cuối `LABELS`) | bật | `VQA_ASK.md` | định tuyến 98,0 % (146/149) |

Các tham số predict mới (`HAZARD_V_CONF_K`, `HAZARD_YAW_TAU_S`, `HAZARD_TTE_*`…) có trong code nhưng chỉ chạy khi `HAZARD_LOGIC=predict`.

## 2. Bảng 10 bàn đo: baseline 2026-10-20 → chốt 2026-10-21

### 2.1 Metric an toàn chính

| Bàn | Metric | Baseline | Chốt | Δ |
|---|---|---:|---:|---:|
| C1a | Recall vật trong lối (ảnh qua kính, ngoài COCO) | 37,3 % [33,4–41,0] | **89,9 %** | **+52,6** |
| C1b | Báo oan / phút (logic chốt = `area`) | 1,13 (bàn đo vòng 2) | 1,13 | 0 |
| C2a | Số sai được nói ra (bản chặt) | 25,8 % [20,3–31,4] | 26,4 % [20,8–32,3] | +0,6 |
| C2b | Nói sai tổng tiền | 6,4 % [4,2–9,1] | 6,6 % [4,2–9,4] | +0,2 |
| C2c | Bịa số khi đáp án có số | 20,0 % [11,8–29,4] | 20,0 % [11,8–29,4] | 0,0 |
| C3 | Đọc sai mệnh giá (1 khung, τ 0,999) | — | 2,4 % [0,9–4,8] | — |
| C3 | Đọc sai mệnh giá (đọc tiền v2: hướng dẫn + đọc lại) | — | 2,7 % | — |
| C4 | Không khớp đáp án nào trên câu unanswerable | 41,3 % [32,7–51,0] | 40,4 % [30,8–50,0] | −0,9 |
| C5 | Chụp lại oan, ảnh không tiền | 0,46 % [0,32–0,62] | 0,46 % [0,32–0,62] | 0,00 |
| C6 | WER người nói tệ nhất | 17,6 % | 17,6 % [12,3–23,6] | 0,0 |
| Định tuyến | Intent sai (gold test) | — | 2,0 % (3/149) | — |

### 2.2 Metric chuẩn

| Bàn | Metric | Baseline | Chốt | Δ |
|---|---|---:|---:|---:|
| C1a | mAP@0,5 (ảnh qua kính) | 0,213 | **0,520** | +0,307 |
| C1b | Kịp thời ≥ 1,5 s (logic `area`) | 3,3 % (bàn đo vòng 2) | 3,3 % | 0 |
| C2a | BoW F1 | 83,3 % | 82,2 % [79,9–84,2] | −1,1 |
| C2b | EM tổng tiền | 93,6 % | 93,4 % [90,6–95,8] | −0,2 |
| C2c | EM | 8,7 % | 8,0 % [5,0–11,0] | −0,7 |
| C3 | Đúng (1 khung, τ 0,999) | — | 50,3 % [43,3–57,6] | — |
| C3 | Đúng (đọc tiền v2) | — | 65,8 % | — |
| C4 | VQA acc (LLM chấm) | 70,7 % | **83,8 %** [80,1–87,4] | **+13,1** |
| C4 | Trả lời thẳng ở câu đầu / thừa / đúng với ảnh | — | 98,7 % / 7,3 % / 90 % | — |
| C5 | F1 ảnh tối (DRK) | 65,9 % | 65,9 % [60,8–71,6] | 0,0 |
| C6 | WER | 4,58 % [3,99–5,18] | 4,58 % [3,99–5,18] | 0,00 |
| Định tuyến | Intent đúng | — | 98,0 % (146/149) | — |

C2a/b/c: code đường đọc không đổi nên chênh trong CI là kỳ vọng. C5, C6 chạy CPU, model không đổi: trùng tuyệt đối.
C4: Codex chấm mù 180/180, đối chứng âm 15/15 cặp tráo ảnh + 15/15 cặp y hệt; ask thắng 138 / thua 11 / hoà 1 (`VQA_ASK_CHOT.md`).

### 2.3 Độ trễ p50 / p90 (ms)

| Bàn | Đo | Baseline | Chốt | Δ |
|---|---|---:|---:|---:|
| C1c | Chuỗi server decode→detect→assess→step, yolo11n + `area` | 5,32 / 6,00 (300 khung) | 6,04 / 7,04 (1.583 khung) | máy tải ~10–20 |
| C1c | ft_11s_last + `area` (**cấu hình chốt**) | — | **5,26 / 5,98** | — |
| C1c | ft_11s_last + `predict` (để tham khảo) | — | 6,37 / 7,26 (ego 0,68 / 1,07; assess 0,34 / 0,48) | — |
| C2a | TTFT / tổng | 393 / 545 · 610 / 1.301 | 361 / 560 · 626 / 1.322 | −32 / +15 · +16 / +21 |
| C2b | Tổng | 379 / 505 | 369 / 505 | −10 / 0 |
| C2c | Tổng | 304 / 497 | 301 / 508 | −3 / +11 |
| C3 | Tổng (1 khung) | — | 197 / 213 | — |
| C4 | Tổng | 604 / 679 | **439 / 569** | **−165 / −110** |
| C5 | `measure()` | 36,6 / 59,6 | 38,3 / 62,1 | +1,7 / +2,5 |
| C6 | Mỗi câu | 129 / 177 | 133 / 181 | +4 / +4 |
| Định tuyến | Thời gian intent | — | 106 / 130 | — |

Ngân sách C1c (tổng p90 ≤ 10 ms): cả 4 cấu hình đạt. Máy dùng chung, tải 10–20 lúc đo.

## 3. Vật cản chi tiết

### 3.1 C1a — phát hiện (Obstacle-Dataset test, ảnh qua kính QVGA + JPEG q15)

| Model | Recall vật trong lối (ngoài COCO) | mAP@0,5 | detect p50 / p90 (ms) |
|---|---:|---:|---:|
| yolo11n COCO (đang chạy) | 37,3 % | 0,213 | 5,48 / 6,42 |
| **ft_11s_last @0,35 (chốt)** | **89,9 %** | **0,520** | **4,78 / 5,39** |

### 3.2 C1b — logic cảnh báo (kịch bản tổng hợp, detector lý tưởng)

Luật chọn chốt trước (spec §6): báo oan/phút ≤ baseline; % kịch bản an toàn có bíp ≤ baseline; **không loại an toàn nào vượt baseline
quá 5 điểm; không loại nguy hiểm nào giảm quá 5 điểm**; đuôi bíp p90 ≤ 1 s; assess+step p90 ≤ 1 ms. Tối đa kịp thời.

| Vòng | Thay đổi | Lưới | Thoả | Tốt nhất (báo oan/phút · % an toàn bíp · kịp thời) | Còn vi phạm |
|---|---|---:|---:|---|---|
| baseline `area` | — | — | — | 1,13 · 13,3 % · 3,3 % | — |
| 1 (18:36) | bàn đo cũ | 324 | 0 | 2,48 · 23,8 % · 55,7 % | cả 3 ràng buộc gộp + 14 loại |
| V1 | **sửa bàn đo** (ego là trượt giữa 2 khung; σ ego đo trên ảnh thật) | 108 | 0 | 0,83 · 11,4 % · **80,1 %** | 8 loại an toàn (người đi ngang / cùng chiều) |
| V2 | V1 + vận tốc chắc `v_conf_k`=0,5 + hệ thân `yaw_tau_s`=3 | 108 | 0 | **0,11 · 1,9 %** · 64,4 % | 3 loại (dưới) |

Lưới vòng 2 (648 cấu hình = 6 biến thể × 108): `results/chot/hazard/c1b_v2/predict_grid_dev_20261021-1927.json`, Pareto trong
`HAZARD_PREDICT.md`. Vòng 1: `HAZARD_PREDICT_vong1_bando_loi.md`. Không cấu hình nào thoả nên **không chạy test** (spec: chọn trên dev, test một lần).

**Hai lỗi bàn đo đã sửa** (ảnh hưởng predict, không ảnh hưởng `area` vì `area` không dùng ego):
1. Kịch bản quay đầu đưa *độ lệch tuyệt đối* của ảnh, trong khi `EgoMeter` thật (phaseCorrelate khung trước/khung này) trả *trượt giữa hai khung*.
   Tracker cộng dồn mỗi khung -> X trôi 1–2 m. Đối chứng 30 seed: `edge_static_person+yaw` bíp oan 90 % -> 0 %, `motorbike_charge+yaw` kịp thời 0 % -> 77 %.
2. σ nhiễu ego 0,01 / 0,02 bề rộng là giả định chưa đo. Đo trên 400 ảnh đường phố thật (đi tới + nhún + quay, JPEG q15): σ 0,0010–0,0013.
   Đặt dev 0,004 (3× đo), test 0,008. Đối chứng: `pass_by_person` bỏ ego -> bíp oan 56,7 % -> 0 % (nhiễu ego × Z là nguồn duy nhất).

**Theo loại (dev, 50 seed/loại)** — % kịch bản an toàn có bíp / % kịp thời:

| Loại | baseline | V1 | V2 |
|---|---:|---:|---:|
| *an toàn:* `pass_by_person+yaw` | 0 | 80 | 10 |
| `pass_by_person+gait` | 0 | 28 | 2 |
| `same_dir_person+gait` | 0 | 44 | 16 |
| `parked_motorbike_row+gait` / `+yaw` | 88 / 96 | 60 / 60 | 4 / 8 |
| `edge_static_car` | 100 | 0 | 0 |
| *nguy hiểm:* `sudden_person_behind_car` (4 biến thể) | 0–20 | **64–76** | **0** |
| `sudden_motorbike_alley` (4 biến thể) | 0–6 | **56–78** | 4–26 |
| `motorbike_swerve` (4 biến thể) | 0 | 42–68 | 24–48 |
| `motorbike_charge` / `wrong_way` / `oncoming_person` | 0 | 70–100 | 82–100 |
| `walk_static_*` | 0–100 | 98–100 | 80–100 |

**Đánh đổi:** V2 cắt báo oan bằng cách không tin vận tốc của track mới, nhưng vật **xuất hiện đột ngột** (nhóm người dùng lo nhất) cũng là track mới
-> V2 báo muộn. V1 bắt tốt nhóm đột ngột nhưng báo oan với người đi ngang/cùng chiều. Vòng 3 (mục 5) nhắm tách hai trường hợp.

## 4. Giới hạn

- C1b là dữ liệu tổng hợp (bộ sinh tự viết), detector lý tưởng; con số không chuyển thẳng sang đường phố. σ ego đo trên ảnh tĩnh biến đổi affine
  (không có thị sai 3D, vật chuyển động, rolling shutter) nên nhiễu thật cao hơn 0,0013 — bàn đo dùng 3×/6×.
- Hệ thân trong V2 là tích phân rò góc đầu: lúc bắt đầu theo dõi không biết đầu đã lệch bao nhiêu (không IMU), hội tụ trong ~τ = 3 s.
- Đọc tiền 3 khung cần kính gửi 3 ảnh (đặc tả đang làm). Vật không có lớp trong bảng chiều cao: Z suy từ đáy hộp.
- Máy dùng chung (tải 10–20) lúc đo trễ.

## 5. Việc còn treo

1. **Vật cản vòng 3** (không IMU): `v_conf` theo khoảng cách (gần thì phản ứng ngay), cờ "xuất hiện từ chỗ khuất" (track sinh muộn + gần = khẩn),
   bù nhún bước bằng trượt dọc `dy` của `EgoMeter`. Sau đó vòng 4: logistic regression trên đặc trưng đã sạch, chỉ thay mức 2, đối chứng nhãn xáo.
2. Chạy lại C1b trên clip thật trước khi bật `predict` mặc định.
3. `app-giao-tiep` cục bộ trong `visioncare-host-demo` còn 6 commit bản cũ (trước khi đổi author) — đồng bộ với remote khi checkout sạch.
