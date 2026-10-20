# Tổng hợp kết quả đo — các chức năng AI SeeVia (baseline, 2026-10-20)

Chỉ ghi số đo, chưa đánh giá/cải tiến (người dùng tự đánh giá). Định nghĩa metric + lý do chọn: `../METRICS.md`. Chi tiết từng bàn đo: các file `*.md` cùng thư mục.
Cấu hình chung: VH commit `ece963b` (nhánh `app-giao-tiep`), GPU 0 RTX 2080 Ti trống (util 0 %), máy dùng chung (loadavg ~11), LLM xa Gemma 4 26B (`llm.uit.edu.vn`) gọi tuần tự 20:42–21:00.
Mọi số: giá trị [CI 95 % bootstrap]. Độ trễ: p50 / p90 / p99.

| # | Chức năng · dataset (n) | Metric an toàn (chính) | Metric chuẩn | Độ trễ | Báo cáo |
|---|---|---|---|---|---|
| C1a | Vật cản phát hiện · Obstacle-Dataset test, 738 ảnh ngoài COCO | Recall vật trong lối: **37,3 % [33,4–41,0]** ảnh qua kính · 42,8 % ảnh gốc | mAP@0,5 (8 lớp): 0,213 kính · 0,273 gốc | detect 5,2 / 5,7 / 6,5 ms (GPU) | HAZARD.md |
| C1b | Vật cản logic · tổng hợp 50 seed × 24 kịch bản | Cảnh báo kịp thời ≥ 1,5 s: **8,3 % [6,0–10,3]** (muộn 63 %, trượt 28,7 %) | Báo nhầm 0,54 / phút [0,42–0,68] | `assess+step` 3,4 / 4,4 / 5,4 µs · trễ thuật toán (chờ xác nhận) 125 ms | HAZARD.md |
| C1c | Vật cản đường nóng server · 300 khung | — | — | decode→detect→assess→step 5,32 / 6,00 / 7,01 ms | HAZARD.md |
| C2a | OCR nguyên văn · VinText test (297/300 chấm được) | Số sai được nói ra: **25,8 % [20,3–31,4]** (bản khoan dung GT tách hộp: 7,1 %) · số bỏ sót 32,7 % | BoW F1 83,3 % · CER 27,7 % | TTFT 393 / 545 / 659 · tổng 610 / 1.301 / 2.399 ms | OCR.md |
| C2b | Hỏi tổng tiền/ngày · SROIE test 361 hoá đơn × 2 | Nói sai: tổng tiền **6,4 % [4,2–9,1]**, ngày **3,9 % [1,9–5,8]**; từ chối 0 % | EM tổng 93,6 % · ngày 96,1 % | TTFT 349 / 484 / 542 · tổng 379 / 505 / 553 ms | OCR.md |
| C2c | Hỏi về chữ tiếng Việt · ViTextVQA test, 300 câu | Bịa số khi đáp án có số: **20,0 % [11,8–29,4]** | EM 8,7 % · F1 43,1 % · đáp án nằm trong câu trả lời 66,3 % | TTFT 285 / 411 / 581 · tổng 304 / 497 / 710 ms | OCR.md |
| C3 | Đọc tiền VND · Kaggle cộng đồng, 360 ảnh — **không baseline, chỉ chứng minh đọc được** | Đọc sai mệnh giá: **11,2 %** (đường thật làn B `ocr_live "money"`) · 6,1 % (đường `general`) · bịa trên ảnh không tiền 0 % | Accuracy 67,3 % / 67,0 % · từ chối 20,9 % / 25,8 % | TTFT 211 / 234 / 253 ms (làn B) | MONEY.md |
| C4 | Hỏi đáp theo ảnh · VizWiz-VQA val, 300 câu (104 unanswerable) | Không từ chối trên câu unanswerable 72,1 % = khớp đáp án thiểu số người gán 30,8 % + **không khớp ai 41,3 % [32,7–51,0]** (cận trên của bịa thật) | VQA acc (LLM chấm) 70,7 % · câu trả lời được 82,7 % | TTFT 296 / 340 / 365 · tổng 604 / 679 / 739 ms | VQA.md |
| C5 | Cổng chất lượng ảnh · VizWiz-QualityIssues val 7.750 | Chụp lại oan: **0,46 % [0,32–0,62]** (money 0,63 %) | F1 tối 65,9 % · chói 22,9 % · mờ 2,7 %; AUROC sáng↔tối 0,91 | `measure()` 36,6 / 59,6 / 157 ms (CPU) | QUALITY.md |
| C6 | STT · VIVOS test 760 câu | WER người nói tệ nhất: **17,6 %** | **WER 4,58 % [3,99–5,18]** · CER 2,18 % | 129 / 177 / 234 ms mỗi câu · RTF 0,037 (CPU) | STT.md |

## Lưu ý khi đọc (giới hạn của chính bàn đo)

- **Không bàn LLM nào chạy cổng chất lượng ảnh trước** (bench gọi thẳng `read_image` / `general.answer`); VQA và MONEY có thêm dòng "nếu có cổng" (cổng chặn 1,7 % / 0 %).
- **C2b/C2c:** VH chưa có đường production "hỏi về chữ" (`final_router` gọi `ocr_live.spoken` không truyền câu hỏi) → bench ghép câu hỏi vào prompt đọc chữ trong tiến trình bench. Số đo khả năng model, chưa phải luồng người dùng hiện có.
- **C2a:** "số sai" bản chặt bị thổi phồng do nhãn VinText tách số theo hộp (vd GT "0","2" vs đọc "02"); bản khoan dung là cận dưới. Không so được với H-mean bài gốc (khác protocol).
- **C4:** intent `space` (prompt mô tả không gian) nhận câu hỏi VizWiz đã dịch; LLM chấm chưa được người kiểm — **cần điền `results/vqa_vizwiz/handcheck_50.csv`** để có độ đồng thuận.
- **C1a:** nhóm ảnh COCO cho recall 67,1 % (rò dữ liệu) — chỉ trích nhóm ngoài COCO. Ngưỡng score 0,35 cắt: bỏ ngưỡng thì recall trong lối 72,3 %. 6 lớp ngoài COCO (cột, cọc tiêu, thùng rác…) gần như không bắt được (0–12 %). Baseline arXiv 2312.07571 (He & Saha) ĐÃ đối chiếu PDF: YOLOv7 huấn luyện trên dataset đạt mAP@0,5 0,817 (Table 6) nhưng chấm trên 1.262 ảnh (≈ val), không phải test 1.583 → khác tập, và họ fine-tune còn SeeVia zero-shot. Tang et al. vẫn chưa đối chiếu (Springer chặn).
- **C1b:** dữ liệu tổng hợp — kiểm chứng logic, không thay dữ liệu thật; đối chứng dương/âm/phá hoại 4/4 đạt.
- **C5:** baseline bài gốc là CNN học giám sát (Xception F1 mờ 80,1 %) — cổng SeeVia cố ý chỉ chặn outlier nên không so ngang.
- **C6:** chưa rõ Zipformer có huấn luyện trên VIVOS không (có thể rò); PhoWhisper large 4,67 % cùng tập (Bảng 2 bài gốc). Câu VIVOS dài hơn câu lệnh kính → trễ tuyệt đối cao hơn thực tế.
- **C3:** ảnh webcam 192×144, một người, khung gần trùng → CI lạc quan; không dùng làm bằng chứng hiệu quả.

## Chạy lại

Từ `SeeVia_system/evaluations/`: `SKIP_WAIT=1 bash run_hazard.sh` · `bash run_quick.sh` · `bash run_llm.sh` (LLM có cache theo mẫu — xoá `results/<task>/cache*.jsonl` để gọi lại thật).
Log: `results/{hazard,quick,llm}.log`; ghi chú dựng bàn đo: `results/{hazard,quick,llm}_NOTES.md`.
