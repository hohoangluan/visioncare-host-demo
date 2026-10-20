# Cải tiến các chức năng AI theo kết quả đo (đợt 2)

Ngày 2026-10-20. Đầu vào: `reports/TONG_HOP.md` (baseline 10 bàn đo). Người dùng chốt: cải tiến các task AI dựa trên kết quả;
cho cài `ultralytics` (cài vào venv RIÊNG `~/.venvs/yolo` — cài vào `~/.venvs/seevia` sẽ hạ cuDNN/cuBLAS mà onnxruntime production dùng) và tải Obstacle-Dataset train/val.

**Luật giữ thay đổi (giống đợt 1):** mỗi thay đổi một biến, so ghép đôi trên CÙNG bàn đo, CI của Δ không chứa 0 theo hướng tốt,
metric an toàn không xấu đi, độ trễ p90 không tăng quá ngân sách (vật cản server +5 ms; LLM TTFT +100 ms). Chọn tham số trên tập
riêng (val / nửa A), báo trên test / nửa B. Thay đổi giữ lại mới cài vào VH (nhánh riêng) + pytest VH xanh.

## 1. Việc cải tiến (xếp theo lợi ích / chi phí)

| # | Task | Bằng chứng (baseline) | Thay đổi | Bàn đo kiểm | Chi phí trễ |
|---|---|---|---|---|---|
| V1 | Vật cản — ngưỡng | Recall trong lối 37,3 %; trần không ngưỡng 72,3 % | Chọn `HAZARD_MIN_SCORE` trên **val** (ràng buộc precision trong lối ≥ hiện tại − 5 đ.%) | C1a test + C1b (báo nhầm/phút) | 0 ms |
| V2 | Vật cản — model | Nano: người 79 %, xe máy 57 % | YOLO11s, YOLO11m COCO @320 (ONNX tĩnh như hiện tại) | C1a + C1c | đo; ≤ +5 ms |
| V3 | Vật cản — fine-tune | 6 lớp ngoài COCO 0–12 %; bài He & Saha fine-tune đạt mAP 0,76–0,82 | Fine-tune model tốt nhất của V2 trên Obstacle train (15 lớp); kiểm ảnh trùng train↔test (hash); giữ lớp COCO cần thiết (ghế, ghế đá, chậu cây) — **câu hỏi mở**, xem 3.1 | C1a test (chỉ ảnh không trùng train) | như V2 |
| V4 | Vật cản — logic | Kịp thời 8,3 % (muộn 63 %), báo nhầm 0,54/phút do xe đỗ ở lề (`approaching` không xét lối đi) | Lần lượt: sửa luật `approaching` chỉ trong lối; H2 TTC (hồi quy chiều cao hộp 6 khung); H3 khoảng cách từ cạnh đáy hộp; H5 hysteresis | C1b (+ C1a không đổi) | µs |
| O1 | OCR — "hỏi về chữ" | VH không truyền câu hỏi vào làn OCR; bench cho thấy model làm được (SROIE EM 93,6 % / 96,1 %) | `final_router` truyền câu hỏi → chế độ hỏi về chữ trong `ocr_live` | C2b, C2c (đường production thật) | ~0 |
| O2 | OCR — số sai | Số sai bản chặt 25,8 % / khoan dung 7,1 %; SROIE nói sai 6,4 %; ViTextVQA bịa số 20 % | Trước hết **chấm tay/độc lập** 50 ca số sai để biết lỗi thật hay lỗi chấm; rồi mới thử prompt "số phải đọc từng chữ số" hoặc OCR thứ hai kiểm số | C2a/b/c | đo |
| M1 | Đọc tiền | Đường thật làn B (`ocr_live "money"`) đọc sai 11,2 % vs `general` 6,1 % | So ghép đôi 2 đường, giữ đường ít nói sai hơn; ảnh 500.000 sai 26,7 % → xem prompt | C3 | ~0 |
| Q1 | Hỏi đáp theo ảnh | Intent `space` mô tả cảnh thay vì trả lời câu hỏi; không từ chối 72,1 % (41,3 % không khớp ai) | Prompt/intent riêng cho "hỏi về ảnh" (trả lời đúng câu hỏi, từ chối khi không thấy) | C4 (+ chấm độc lập) | đo |
| G1 | Cổng chất lượng | Chói recall 13,5 %; mờ chỉ áp cho tiền, F1 2,7 % | Chỉ chỉnh ngưỡng chói nếu nửa B xác nhận và chụp lại oan không tăng > 0,2 đ.%; mờ giữ nguyên (cố ý) | C5 | 0 |
| S1 | STT | WER 4,58 % (ngang PhoWhisper large 4,67 %) | **Không đổi** | — | — |

## 2. Còn thiếu (chưa đo được / chưa có bàn đo)

1. **Tìm đồ (`find_object`)** — chức năng AI chưa có bàn đo nào. Dữ liệu có sẵn: VizWiz-Grounding (đã tải) → chấm hướng nói ra (giờ đồng hồ) với vị trí mask ±1 giờ.
2. **Mô tả nguy hiểm theo yêu cầu (`describe_hazard`)** — chưa đo (VLM); có thể dùng ảnh Obstacle test: câu trả lời có nêu vật trong lối đi không.
3. **Chấm độc lập cho C4 (VizWiz)** — `handcheck_50.csv` chưa có người chấm. Codex KHÔNG có trên máy này (không thấy extension `openai.chatgpt`) → thay bằng **Claude Sonnet nhìn ảnh, chấm mù** (bản `handcheck_blind.csv` không có cột phán quyết của Gemma), báo đồng thuận Gemma-chấm vs Sonnet-chấm. Không thay được người, ghi rõ.
4. **Độ trễ vật cản đầu-cuối có mạng** (kính giả lập → Cloudflare → bíp, C1c phần ii) — chưa đo.
5. **TTS** — chưa đo (cần UTMOS/người nghe).
6. **Baseline Tang et al. (UAIS 2021)** — chưa đối chiếu (Springer chặn).
7. **Dữ liệu Việt Nam** cho vật cản vỉa hè, tiền VND chuẩn, TTC — không tồn tại bộ công khai có bài báo → giới hạn ghi trong báo cáo (người dùng chốt không tự làm dữ liệu).

## 3. Câu hỏi mở

1. **V3 mất lớp:** fine-tune 15 lớp Obstacle làm model quên `chair`, `bench`, `plant`, `traffic_light`, `parking_meter` (SeeVia đang cảnh báo các lớp này).
   Mặc định đề xuất: gán nhãn giả các lớp này trên ảnh train bằng YOLO11m COCO rồi huấn luyện 15 + 5 lớp (không cần dữ liệu mới) — chờ người dùng chốt.
2. Thứ tự: V1 → V2 → V4 → O1 → M1 → Q1 → V3 (dài nhất, chạy nền song song) → O2 → G1; song song làm mục 2.1 và 2.3.
