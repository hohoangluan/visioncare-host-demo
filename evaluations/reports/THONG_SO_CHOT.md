# THÔNG SỐ CHỐT AI — 2026-10-21

Nhánh `chot-ai-2026-10-21` (gộp `vqa-hoi-anh`, `ocr-tien`, `od-du-doan`, `che-do-vao-ra`, `demo-ux` vào `app-giao-tiep`). Env: `reports/thong_so_chot.env`.
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
| C4 | VQA acc, công thức chuẩn (trung bình 10 tập bỏ-1-người, LLM chấm khớp) | 69,4 % [64,7–74,2] | **82,6 %** [78,9–86,3] | **+13,2** [8,3–17,8] ghép đôi |
| C4 | VQA acc, bản rút gọn min(#/3, 1) (số cũ trong báo cáo) | 70,7 % | 83,8 % [80,1–87,4] | +13,1 |
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

### 3.1 C1a — phát hiện (Obstacle-Dataset [2] test, ảnh qua kính QVGA + JPEG q15)

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
-> V2 báo muộn. V1 bắt tốt nhóm đột ngột nhưng báo oan với người đi ngang/cùng chiều. Vòng 3 (mục 6) nhắm tách hai trường hợp.

### 3.3 C1d — dữ liệu thật HEADS-UP [1] (chỉ người đi bộ)

Camera ZED Mini gắn mũ, người đeo đi bộ thật (easy: ít quay đầu; hard: quay đầu mạnh; unconstrained: đông người). Hộp người YOLOv8 + ByteTrack
của bộ dữ liệu (detector thật). Đáp án: depth stereo + tư thế VIO (logic không đọc). Mô phỏng kính: cắt 66° HFOV 4:3, 8 fps.
Định nghĩa: vào lối = 0 < Z < 2 m, |X| < 0,6 m theo hướng đi; kịp thời = bíp trong [t − 5 s, t − 1,5 s]; báo oan = bíp không ai vào lối trong 5 s.
Cấu hình V1/V2 chọn trên bàn đo tổng hợp, **không tinh chỉnh trên HEADS-UP**. `bench/heads_up_eval.py`, `results/heads_up/`.

| Logic | Kịp thời [CI 95 %] | Bíp ngẫu nhiên cùng số lần | Báo oan/phút | Báo oan, bỏ ca suýt (\|X\| < 1 m) |
|---|---:|---:|---:|---:|
| `area` (chốt) | 19,2 % [4–35] | 12,3 % | **0,95** | 0,52 |
| V1, ego lý tưởng (từ VIO) | **73,1 %** [54–88] | 22,8 % | 2,42 | 1,68 |
| V2, ego lý tưởng | 61,5 % [42–81] | 21,3 % | 2,16 | 1,34 |
| V1, không bù quay đầu | 65,4 % [46–85] | 28,2 % | 3,32 | 2,24 |
| V2, không bù quay đầu | 61,5 % [42–81] | 19,4 % | 1,98 | 0,95 |

23,2 phút, 39 ca vào lối, 26 ca lộ diện trước ≥ 1,5 s. Ego "lý tưởng" lấy từ tư thế VIO (kính không có): cận trên; bản kính thật dùng
`EgoMeter` trên ảnh: chỉ đo được một phần (bảng dưới). Kiểm dấu ego: hồi quy Δu hộp theo shift hệ số +1,07.
Đọc: predict có tín hiệu thật (vượt xa bíp ngẫu nhiên), nhưng báo oan vượt `area` -> chưa đạt luật "không tăng báo oan" -> giữ `area`.

**Riêng bộ unconstrained, ba cách đo quay đầu** (n = 10 ca, CI rất rộng — chỉ để tham khảo):

| Logic | không bù | ego lý tưởng (VIO) | **`EgoMeter` trên ảnh như kính gửi** |
|---|---|---|---|
| V1 kịp thời / báo oan/phút | 90 % / 4,08 | 90 % / 2,77 | 90 % / 3,56 |
| V2 kịp thời / báo oan/phút | 80 % / 2,50 | 80 % / 3,82 | 80 % / 2,64 |
| `area` | 30 % / 0,92 | (không dùng ego) | (không dùng ego) |

`EgoMeter` chỉ đo được trên 58 % khung: file `rgb_unconstrained.tar.gz` trên Hugging Face có 10.387 PNG cho 13.665 khung, trong đó
2.412 file 32 KB toàn byte 0 (hỏng ở nguồn; kích thước tải về khớp đúng bản công bố). Khung thiếu -> `EgoMeter` khởi lại, shift = 0.
→ Chưa kết luận được hiệu quả bù quay đầu bằng ảnh trên dữ liệu thật.
Đã thử khắc phục rồi dừng (2026-10-21 tối, theo quyết định người dùng): tải lại cho đúng file cũ (SHA-256 `7b156dce…56f4` trùng bản
công bố -> lỗi ở nguồn); bản `unconstrained.zip` cũ (revision `7fa2b577`, 18/12/2024) lỗi zip64 (vị trí/kích thước cắt 32 bit) và có
kích thước RGB đúng bằng bản hỏng; `rgb_easy`/`rgb_hard` (66 GB) mẫu 1.500 ảnh đầu không hỏng nhưng **không tải**. Mọi kết quả C1d ở
mục này dùng **dữ liệu hiện có**: nhãn + tư thế đủ 3 bộ (mục 3.3, bảng trên), ảnh chỉ bộ unconstrained, 58 % khung.

### 3.4 C1e — sai số khoảng cách của kính trên dữ liệu thật (HEADS-UP [1])

Hộp YOLOv8 thật trong vùng cắt kính, camera danh nghĩa kính (320×240, 66°, cao 1,6 m); Z_thật = depth stereo, 1 m < Z < 15 m; 7.957 hộp.
`bench/heads_up_depth.py`, `results/heads_up/depth_*.json`.

| Nhóm | Trung vị \|e\| | Lệch trung vị e | p90 \|e\| | \|e\| ≤ 20 % |
|---|---:|---:|---:|---:|
| Tất cả, góc chúc tự học (như chạy thật) | **11,3 %** | +5,0 % | 37,8 % | 75,2 % |
| Tất cả, giả định nhìn thẳng | 14,3 % | +9,4 % | 39,3 % | 67,5 % |
| Z 1–3 m | 19,0 % | +5,3 % | 96,2 % | 52,5 % |
| **Z 3–6 m** (vùng quyết định cảnh báo) | **9,0 %** | +3,8 % | 24,4 % | **84,1 %** |
| Z 6–10 m | 10,3 % | +6,4 % | 27,1 % | 80,8 % |
| Hộp cắt đáy (vật rất gần) | 17,8 % | −7,7 % | 62,7 % | 56,5 % |

Đọc: gộp "chiều cao người + mặt đất" chính xác ~9–10 % ở 3–10 m. Lệch dương (ước xa hơn thật ~5 %) là hướng báo muộn — cần sửa.
Điểm yếu là 1–3 m khi hộp bị cắt đáy.

### 3.5 Hiệu chỉnh bàn đo tổng hợp bằng nhiễu detector thật

Đo trên track YOLOv8 + ByteTrack của HEADS-UP [1] (8 fps, phần dư so với trung bình trượt 5 khung): tâm ngang σ_bền 11,3 % bề rộng hộp,
chiều cao 2,3 %, bề rộng 4,4 % (đuôi dày); 8,7 % khung mất giữa track, có 41 chuỗi mất ≥ 5 khung (> coast 3 -> track bị xoá rồi sinh lại).
Bộ sinh cũ dùng hộp hoàn hảo ở mọi kịch bản gốc. Đã thêm vào bộ sinh (`C1B_DET_NOISE=1`, Student-t 3 + chuỗi mất Markov):

| Báo oan/phút | `area` | V1 | V2 |
|---|---:|---:|---:|
| Tổng hợp, hộp lý tưởng (vòng 2) | 1,13 | 0,83 | 0,11 |
| **Tổng hợp + nhiễu detector thật** | 1,55 | 3,92 | 0,83 |
| Thật (HEADS-UP, ego lý tưởng) | 0,95 | 2,42 | 2,16 |

V1: bàn đo đã hiệu chỉnh tái hiện đúng tỉ lệ thật (≈ 2,5× `area`). V2: vẫn lạc quan (0,5× so với 2,3× thật) -> còn nguồn báo oan
chưa mô phỏng (nghi cảnh đông người; chưa kiểm). Kịp thời trên bàn đo hiệu chỉnh: `area` 4,9 %, V1 75,8 %, V2 55,5 %.

**Tái lập số:** `SEEVIA_VH_DIR=../vh-od python -m bench.heads_up_eval --ego {none|pose|image}`; `python -m bench.heads_up_depth`;
lưới tổng hợp vòng 2 không nhiễu detector: `C1B_DET_NOISE=0 python -m bench.hazard_grid --split dev` (mặc định nay bật nhiễu đo từ HEADS-UP).

## 4. Giới hạn

> **CHƯA ĐỦ DỮ LIỆU THẬT ĐỂ CHỨNG MINH logic cảnh báo vật cản cho mọi tình huống.** Số C1b (mục 3.2) là kịch bản tổng hợp tự viết,
> detector lý tưởng. Đã kiểm trên dữ liệu thật **chỉ cho người đi bộ** (HEADS-UP [1], mục 3.3; n = 26 ca, CI rộng): predict kịp thời hơn
> `area` 3–4 lần nhưng báo oan cao hơn 2–2,5 lần — **ngược** với bàn đo tổng hợp (V2 báo oan thấp hơn 10 lần) -> bàn đo tổng hợp quá lạc quan
> về báo oan. **Nhóm xe máy / giao thông Việt Nam chưa có dữ liệu thật nào.** Muốn bật `HAZARD_LOGIC=predict` mặc định thì phải thắng `area`
> trên cả hai: dữ liệu thật người đi bộ VÀ clip Việt Nam có xe máy.

- C1b là dữ liệu tổng hợp (bộ sinh tự viết), detector lý tưởng; con số không chuyển thẳng sang đường phố. σ ego đo trên ảnh tĩnh biến đổi affine
  (không có thị sai 3D, vật chuyển động, rolling shutter) nên nhiễu thật cao hơn 0,0013 — bàn đo dùng 3×/6×.
- Hệ thân trong V2 là tích phân rò góc đầu: lúc bắt đầu theo dõi không biết đầu đã lệch bao nhiêu (không IMU), hội tụ trong ~τ = 3 s.
- Đọc tiền 3 khung cần kính gửi 3 ảnh (đặc tả đang làm). Vật không có lớp trong bảng chiều cao: Z suy từ đáy hộp.
- Máy dùng chung (tải 10–20) lúc đo trễ.

## 5. Phương pháp đo, công thức và dữ liệu

Quy ước chung: CI 95 % = bootstrap percentile 1.000 lần theo đơn vị mẫu (ảnh / câu / kịch bản / ca), seed 0; so A/B luôn **ghép đôi**
trên cùng mẫu (Δ và CI của Δ). Chi tiết lý do chọn metric: `evaluations/METRICS.md`. Mỗi bàn: lệnh chạy trong `run_chot_*.sh`.

| Bàn | Đo gì | Công thức | Dữ liệu |
|---|---|---|---|
| C1a | Detector thấy vật trong lối | Recall = TP/(TP+FN), TP = hộp GT có detection IoU ≥ 0,5 (không phân lớp, score ≥ 0,35); chỉ hộp GT "trong lối" (tâm x ∈ [0,3; 0,7], diện tích ≥ 2 %); chỉ 738 ảnh ngoài COCO (tránh rò). mAP@0,5 = trung bình AP theo lớp (diện tích dưới đường P–R). Ảnh như kính gửi: QVGA + JPEG q15 | Obstacle-Dataset test 1.583 ảnh [2]; baseline [3] |
| C1b | Logic cảnh báo (tổng hợp) | Kịp thời = #kịch bản nguy hiểm có bíp ≥ 1,5 s trước t_vào / #kịch bản nguy hiểm; t_vào = khung đầu Z < 2 m và \|X\| < 0,6 m. Báo oan/phút = #bíp trên kịch bản an toàn / tổng phút an toàn. % an toàn có bíp = #kịch bản an toàn có ≥ 1 bíp / #kịch bản an toàn | Kịch bản tổng hợp tự viết (`bench/hazard_scenarios.py`); nhiễu ego và nhiễu hộp **đo từ dữ liệu thật** [1] |
| C1c | Trễ đường nóng server | p50/p90 của (decode → detect → assess → step) mỗi khung, ms | 1.583 ảnh Obstacle-Dataset [2] thu QVGA |
| C1d | Logic cảnh báo (thật) | Kịp thời = #ca có bíp trong [t_vào − 5 s, t_vào − 1,5 s] / #ca lộ diện trước t_vào ≥ 1,5 s; báo oan = bíp mà không ai trong lối và không ai vào lối trong 5 s sau; đối chứng: bíp ngẫu nhiên cùng số lần (200 lần) | HEADS-UP [1] |
| C1e | Sai số khoảng cách (mục 3.4) | e = (Z_ước − Z_thật)/Z_thật; báo trung vị e, trung vị \|e\|, p90 \|e\|, % \|e\| ≤ 20 %; Z_thật = depth stereo dọc trục quang | HEADS-UP [1] |
| C2a | Đọc chữ cảnh | Số sai được nói ra = #chuỗi số trong câu trả lời không có trong GT / #chuỗi số trả lời; BoW F1 từ (NFC, chữ thường, giữ dấu) | VinText test 300 ảnh [4] |
| C2b | Đọc tổng tiền hoá đơn | Nói sai = #câu nêu số khác GT (\|Δ\| > 0,005) / #câu; EM = #đúng / #câu. **Không** phải F1 Task 3 của cuộc thi gốc | SROIE test 361 hoá đơn [5] |
| C2c | Hỏi đáp chữ tiếng Việt | EM, F1 token (metric bài gốc), sau chuẩn hoá chữ thường, bỏ dấu câu | ViTextVQA test, mẫu 300 [6] |
| C3 | Đọc mệnh giá | Sai = #câu nêu mệnh giá khác GT / #ảnh; đúng = #đúng / #ảnh; phần còn lại là từ chối | vnd_kaggle (Kaggle cộng đồng, 360 ảnh) — **không có bài báo, không baseline** |
| C4 | Hỏi đáp về ảnh | VQA acc = (1/10)·Σ₁₀ min(#người trùng trong 9 người còn lại / 3, 1), "trùng" do LLM chấm (câu VN với 10 đáp án EN), kiểm tay 50 mẫu; bịa = #câu unanswerable mà trả lời không khớp đáp án nào / #câu unanswerable | VizWiz-VQA val, mẫu 300 [7] |
| C5 | Cổng chất lượng ảnh | Chụp lại oan = #ảnh bị chặn mà nhãn nói nhận ra được / #ảnh nhận ra được; F1 lớp tối (DRK) | VizWiz-QualityIssues val 7.750 ảnh [8] |
| C6 | Nhận dạng giọng nói | WER = (S + D + I)/N (jiwer, chuẩn hoá chữ thường); báo cả WER người nói tệ nhất | VIVOS test 760 câu [9] |
| Định tuyến | Phân loại ý định | Đúng = #câu nhãn dự đoán = nhãn gold / #câu | Bộ gold nội bộ 149 câu (`data/intent/`) |

Đã kiểm lại 2026-10-21: (a) cite Obstacle-Dataset trong báo cáo cũ ghi năm 2021 là sai, đúng là 2023 [2]; (b) VQA acc trong code là bản
rút gọn min(#/3, 1), cao hơn công thức chuẩn ~1,2 điểm — bảng 2.2 báo cả hai, kết luận A/B không đổi.

## 6. Việc còn treo

1. **Vật cản vòng 3** (không IMU): `v_conf` theo khoảng cách (gần thì phản ứng ngay), cờ "xuất hiện từ chỗ khuất" (track sinh muộn + gần = khẩn),
   bù nhún bước bằng trượt dọc `dy` của `EgoMeter`. Sau đó vòng 4: logistic regression trên đặc trưng đã sạch, chỉ thay mức 2, đối chứng nhãn xáo.
2. Chạy lại C1b trên clip thật trước khi bật `predict` mặc định (tự quay bằng camera kính, hoặc HEADS-UP [1] cho nhóm người đi bộ).
3. `app-giao-tiep` cục bộ trong `visioncare-host-demo` còn 6 commit bản cũ (trước khi đổi author) — đồng bộ với remote khi checkout sạch.

## Tài liệu tham khảo

[1] Y. Haghighi, C. Demonsant, P. Chalimourdas, M. T. Naeini, J. K. Munoz, B. Bacca, S. Suter, M. Gani, A. Alahi.
"HEADS-UP: Head-Mounted Egocentric Dataset for Trajectory Prediction in Blind Assistance Systems". arXiv:2409.20324, 2024.


[2] W. Tang, D.-e. Liu, X. Zhao, Z. Chen, C. Zhao. "A dataset for the recognition of obstacles on blind sidewalk". *Universal Access in the
Information Society* 22(1):69–82, 2023. https://github.com/TW0521/Obstacle-Dataset

[3] C. He, P. Saha. "Investigating YOLO Models Towards Outdoor Obstacle Detection For Visually Impaired People". arXiv:2312.07571, 2023.

[4] N. Nguyen, T. Nguyen, V. Tran, M.-T. Tran, T. D. Ngo, T. H. Nguyen, M. Hoai. "Dictionary-guided Scene Text Recognition" (bộ VinText).
CVPR 2021. doi:10.1109/CVPR46437.2021.00730

[5] Z. Huang, K. Chen, J. He, X. Bai, D. Karatzas, S. Lu, C. V. Jawahar. "ICDAR2019 Competition on Scanned Receipt OCR and Information
Extraction" (SROIE). ICDAR 2019. arXiv:2103.10213

[6] Q. V. Nguyen, D. Q. Tran, H. Q. Pham, T. K.-B. Nguyen, N. H. Nguyen, K. V. Nguyen, N. L.-T. Nguyen. "ViTextVQA: A Large-Scale Visual
Question Answering Dataset for Evaluating Vietnamese Text Comprehension in Images". arXiv:2404.10652, 2024.

[7] D. Gurari, Q. Li, A. J. Stangl, A. Guo, C. Lin, K. Grauman, J. Luo, J. P. Bigham. "VizWiz Grand Challenge: Answering Visual Questions
from Blind People". CVPR 2018. arXiv:1802.08218

[8] T.-Y. Chiu, Y. Zhao, D. Gurari. "Assessing Image Quality Issues for Real-World Problems" (VizWiz-QualityIssues). CVPR 2020, 3646–3656.
arXiv:2003.12511

[9] H.-T. Luong, H.-Q. Vu. "A non-expert Kaldi recipe for Vietnamese Speech Recognition System" (bộ VIVOS). WLSI/OIAF4HLT 2016, 51–55.
ACL Anthology W16-5207

Công thức VQA acc theo bài gốc VQA: S. Antol et al., "VQA: Visual Question Answering", ICCV 2015 (arXiv:1505.00468); trung bình 10 tập
bỏ-1-người theo trang đánh giá chính thức visualqa.org/evaluation.html.

```bibtex
@article{haghighi2024heads,
  title={HEADS-UP: Head-Mounted Egocentric Dataset for Trajectory Prediction in Blind Assistance Systems},
  author={Haghighi, Yasaman and Demonsant, Celine and Chalimourdas, Panagiotis and Naeini, Maryam Tavasoli and Munoz, Jhon Kevin and Bacca, Bladimir and Suter, Silvan and Gani, Matthieu and Alahi, Alexandre},
  journal={arXiv preprint arXiv:2409.20324},
  year={2024}
}
```
