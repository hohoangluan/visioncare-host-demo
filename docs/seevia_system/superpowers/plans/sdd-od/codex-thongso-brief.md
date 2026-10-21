# Đề bài Codex: nháp phần AI (không vật cản) của báo cáo THÔNG SỐ CHỐT

Viết file MỚI: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/reports/THONG_SO_CHOT_nhap_ai.md (tiếng Việt, số kiểu Việt Nam: dấu phẩy thập phân). KHÔNG sửa file nào khác.
Mỗi con số phải lấy TỪ FILE JSON (đọc bằng python), không đoán; ghi đường dẫn file nguồn dưới mỗi bảng. Có CI thì ghi CI.

## Nguồn lượt chốt (2026-10-21, nhánh tích hợp vh-chot @ce592ae, gọi model MỚI, cache tag chot20261021)
- C6 STT: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/stt_vivos/20261021-1715_full.json
- C5 cổng chất lượng ảnh: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/quality_vizwiz/20261021-1721_full.json (file lớn, chỉ đọc phần tổng hợp)
- C2a OCR VinText: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/ocr_vintext/20261021-1725_raw_spoken.json
- C2b SROIE: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/ocr_sroie/20261021-1730_ask_spoken.json ; cảnh báo chữ số: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/ocr_numconf/20261021-1735_test.json
- C2c ViTextVQA: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/ocr_vitextvqa/20261021-1737_ask_spoken.json
- C3 đọc tiền: 1 khung τ0,999 /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/money_vnd/20261021-1738_choice_sys.json ; 3 khung (tham chiếu v1) /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/money_vnd/20261021-1741_multi_test.json ;
  trễ ghép đôi cũ vs v2: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/money_vnd/20261021-1742_turn_latency_n60.json và /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/money_vnd/20261021-1750_turn_latency_n60.json (lần 2 trên vh-chot @706e08f)
  ; luồng đọc lại (1 khung τ0,999 + đọc lại 1 lần τ0,999): số offline trong spec /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md §2 (test: sai 2,7 %, đúng 65,8 %, từ chối 31,5 %).
- C4 VQA: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/vqa_vizwiz/20261021-1746_general_ask.json ; giám khảo mù Codex: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/reports/VQA_ASK_CHOT.md ; trễ A/B: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/vqa_vizwiz/20261021-1747_latency_ab.json
- Định tuyến intent gold test: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/intent_gold_test.json
- Baseline 2026-10-20 để so: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/reports/TONG_HOP.md (bảng chính).

## Cấu trúc file
1. "Bảng so baseline 2026-10-20 → chốt": một dòng mỗi bàn (C2a, C2b, C2c, C3, C4, C5, C6, định tuyến): metric an toàn chính, metric chuẩn, trễ p50/p90 — cột baseline (từ TONG_HOP.md) và cột chốt (từ JSON), cột Δ.
   Dùng đúng tên metric như TONG_HOP.md. Nếu một metric không có trong JSON chốt thì ghi "—" và lý do.
2. "Thông số chốt" (biến env → giá trị → chọn ở đâu): đọc giá trị mặc định thật trong /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-chot/config.py cho:
   MONEY_MODE, MONEY_MIN_PROB, MONEY_MULTI_MIN_PROB, MONEY_RETRY, MONEY_RETRY_PROB, MONEY_RETRY_SETTLE_S, MONEY_RETRY_TIMEOUT_S, MONEY_BLUR_HINT,
   OCR_DIGIT_HEDGE_PROB, STT_DECODING, LLM_IMAGE_MAX_SIDE, LLM_OCR_IMAGE_MAX_SIDE, OCR_CAPTURE_WIDTH, HAZARD_MIN_SCORE, HAZARD_MIN_LEVEL và nhãn intent  (models/clef/client.py LABELS cuối).
   Cột "chọn ở đâu": báo cáo nguồn (MONEY_OCR_CAI_TIEN.md, VQA_ASK.md, TONG_HOP.md...) — đọc các file trong /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/reports/ để điền.
3. "Ghi chú đọc số": không cache (tag chot20261021), máy dùng chung (loadavg ~10), lượt 1 có cache bị loại (/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/lan1_cache_cu/).
Không hỏi lại.
