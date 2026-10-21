# THÔNG SỐ CHỐT — phần AI (nháp)

Lượt chốt ngày 2026-10-21 chạy trên nhánh `chot-ai-2026-10-21`, commit `ce592ae`, gọi model mới với cache tag `chot20261021`. Số đo phần trăm được ghi theo thang 0–100; CI là CI 95% nếu JSON có cung cấp. Trễ ghi p50/p90, đơn vị ms. Δ = chốt − baseline; với metric rủi ro, số âm là giảm rủi ro.

## Bảng so baseline 2026-10-20 → chốt

### Metric an toàn chính

| Bàn | Metric | Baseline 20-10 | Chốt 21-10 | Δ (điểm %) |
|---|---|---:|---:|---:|
| C2a | Số sai được nói ra (bản chặt) | 25,8% [20,3–31,4] | 26,4% [20,8–32,3] | +0,6 |
| C2b | Nói sai tổng tiền | 6,4% [4,2–9,1] | 6,6% [4,2–9,4] | +0,2 |
| C2c | Bịa số khi đáp án có số | 20,0% [11,8–29,4] | 20,0% [11,8–29,4] | 0,0 |
| C3 | Đọc sai mệnh giá, 1 khung, τ=0,999 | — (baseline chỉ có các đường cũ, không cùng cấu hình) | 2,4% [0,9–4,8] | — |
| C4 | Không khớp đáp án nào trên câu unanswerable (cận trên bịa thật) | 41,3% [32,7–51,0] | 40,4% [30,8–50,0] | −0,9 |
| C5 | Chụp lại oan, ảnh không tiền | 0,46% [0,32–0,62] | 0,46% [0,32–0,62] | 0,00 |
| C6 | WER người nói tệ nhất | 17,6% | 17,6% [12,3–23,6] | 0,0 |
| Định tuyến | Intent sai trên gold test | — (TONG_HOP.md không có baseline định tuyến) | 2,0% (3/149) | — |

Nguồn số chốt: C2a `results/chot/ocr_vintext/20261021-1725_raw_spoken.json`; C2b `results/chot/ocr_sroie/20261021-1730_ask_spoken.json`; C2c `results/chot/ocr_vitextvqa/20261021-1737_ask_spoken.json`; C3 `results/money_vnd/20261021-1738_choice_sys.json`; C4 `results/chot/vqa_vizwiz/20261021-1746_general_ask.json`; C5 `results/chot/quality_vizwiz/20261021-1721_full.json`; C6 `results/chot/stt_vivos/20261021-1715_full.json`; định tuyến `results/chot/intent_gold_test.json` (JSONL). Baseline: `reports/TONG_HOP.md`.

### Metric chuẩn

| Bàn | Metric | Baseline 20-10 | Chốt 21-10 | Δ (điểm %) |
|---|---|---:|---:|---:|
| C2a | BoW F1 | 83,3% | 82,2% [79,9–84,2] | −1,1 |
| C2b | EM tổng tiền | 93,6% | 93,4% [90,6–95,8] | −0,2 |
| C2c | EM | 8,7% | 8,0% [5,0–11,0] | −0,7 |
| C3 | Accuracy, 1 khung, τ=0,999 | — (không có baseline cùng cấu hình) | 50,3% [43,3–57,6] | — |
| C4 | VQA acc (LLM chấm) | 70,7% | 83,8% [80,1–87,4] | +13,1 |
| C5 | F1 tối (DRK) | 65,9% | 65,9% [60,8–71,6] | 0,0 |
| C6 | WER | 4,58% [3,99–5,18] | 4,58% [3,99–5,18] | 0,00 |
| Định tuyến | Intent đúng exact | — (không có metric baseline) | 98,0% (146/149) | — |

Nguồn số chốt: như bảng metric an toàn; C5 dùng summary `metrics.prf_current_threshold.DRK.f1`; định tuyến dùng `gold`/`pred` trong `results/chot/intent_gold_test.json`. Baseline: `reports/TONG_HOP.md`.

### Độ trễ p50/p90

| Bàn | Metric trễ | Baseline p50 / p90 (ms) | Chốt p50 / p90 (ms) | Δ p50 / p90 (ms) |
|---|---|---:|---:|---:|
| C2a | TTFT | 393 / 545 | 361,40 / 560,12 | −31,60 / +15,12 |
| C2a | Tổng | 610 / 1.301 | 625,66 / 1.322,39 | +15,66 / +21,39 |
| C2b | Tổng | 379 / 505 | 369,37 / 505,47 | −9,63 / +0,47 |
| C2c | Tổng | 304 / 497 | 301,16 / 508,15 | −2,84 / +11,15 |
| C3 | Tổng (1 khung τ=0,999) | — | 196,55 / 213,46 | — |
| C4 | Tổng | 604 / 679 | 439,12 / 569,42 | −164,88 / −109,58 |
| C5 | `measure()` | 36,6 / 59,6 | 38,27 / 62,14 | +1,67 / +2,54 |
| C6 | Mỗi câu | 129 / 177 | 133,38 / 180,96 | +4,38 / +3,96 |
| Định tuyến | Thời gian intent | — | 106,36 / 130,30 | — |

Nguồn số chốt: C2a `results/chot/ocr_vintext/20261021-1725_raw_spoken.json`; C2b `results/chot/ocr_sroie/20261021-1730_ask_spoken.json`; C2c `results/chot/ocr_vitextvqa/20261021-1737_ask_spoken.json`; C3 `results/money_vnd/20261021-1738_choice_sys.json`; C4 `results/chot/vqa_vizwiz/20261021-1746_general_ask.json`; C5 `results/chot/quality_vizwiz/20261021-1721_full.json`; C6 `results/chot/stt_vivos/20261021-1715_full.json`; định tuyến `results/chot/intent_gold_test.json` (p50/p90 tính từ trường `seconds` của 149 dòng). Baseline: `reports/TONG_HOP.md`.

**Ghi chú metric:** C2a có thêm số sai bản khoan dung 7,6% [5,3–10,2] (baseline 7,1%) và số bỏ sót 34,3% [28,4–40,4] (baseline 32,7%). C2b ngày: nói sai 3,9% [1,9–5,8], EM 96,1% [94,2–98,1] (baseline lần lượt 3,9% và 96,1%). C2c F1 42,2% [38,7–45,7], đáp án nằm trong câu trả lời 66,7% [61,7–72,0] (baseline 43,1% và 66,3%). Không có metric tương ứng trong JSON chốt cho một số breakdown của TONG_HOP.md thì ghi “—”; không suy ra thay cho metric không được báo cáo.

## Thông số chốt

Giá trị là mặc định thật được đọc từ `vh-chot/config.py`; biến `MONEY_*` dùng quy tắc đọc tiền hiện hành. “Chọn ở đâu” dẫn tới báo cáo đánh giá có căn cứ/ghi chú liên quan.

| Biến env / nhãn | Giá trị mặc định | Chọn ở đâu |
|---|---:|---|
| `MONEY_MODE` | `choice` | `MONEY_OCR_CAI_TIEN.md` — so sánh đường chọn nhãn và nhiều khung |
| `MONEY_MIN_PROB` | 0,999 | `MONEY_OCR_CAI_TIEN.md` — kết quả 1 khung và luồng đọc lại |
| `MONEY_MULTI_MIN_PROB` | 0,98 | `MONEY_OCR_CAI_TIEN.md` — 3 khung B3 |
| `MONEY_RETRY` | `true` (env mặc định `1`) | `MONEY_OCR_CAI_TIEN.md` — luồng đọc lại đúng một lần |
| `MONEY_RETRY_PROB` | 0,999 | `MONEY_OCR_CAI_TIEN.md` — ngưỡng lượt đọc lại; mức cao hơn chưa đo |
| `MONEY_RETRY_SETTLE_S` | 1,0 s | `MONEY_OCR_CAI_TIEN.md` — bỏ khung đầu trong lượt đọc lại |
| `MONEY_RETRY_TIMEOUT_S` | 3,0 s | `MONEY_OCR_CAI_TIEN.md` — giới hạn chờ khung đủ nét |
| `MONEY_BLUR_HINT` | 341,4 | `MONEY_OCR_CAI_TIEN.md` — ngưỡng độ nét chọn trên dev |
| `OCR_DIGIT_HEDGE_PROB` | 0,9 | `MONEY_OCR_CAI_TIEN.md` — hiệu chỉnh cảnh báo chữ số; `OCR.md` |
| `STT_DECODING` | `modified_beam_search` | `STT.md` — beam search, bốn đường và hotword |
| `LLM_IMAGE_MAX_SIDE` | 896 px | `VQA_ASK.md` — đánh giá đường hỏi ảnh |
| `LLM_OCR_IMAGE_MAX_SIDE` | 1.600 px | `OCR.md` — resize đường OCR |
| `OCR_CAPTURE_WIDTH` | 1.600 px | `OCR.md` — chiều rộng ảnh thu cho OCR |
| `HAZARD_MIN_SCORE` | 0,35 | `HAZARD.md` — ngưỡng vận hành recall |
| `HAZARD_MIN_LEVEL` | 2 | `HAZARD.md` — mức cảnh báo trong bàn logic |
| Nhãn intent (`models/clef/client.py`, `LABELS`) | `chat`, `space`, `hazard`, `ocr`, `money`, `find`, `nav_start`, `nav_stop`, `alert_on`, `alert_off`, `contact_call`, `message_send`, `message_read`, `emergency_call`, `ride_quote`, `ride_confirm`, `music_play`, `music_stop`, `music_volume`, `ask` | `TONG_HOP.md` mô tả các bàn chức năng; danh sách nhãn thực tế lấy nguyên từ `vh-chot/models/clef/client.py`. Không thấy báo cáo sweep/chọn riêng toàn bộ nhãn intent. |

## Ghi chú đọc số

- Lượt chốt dùng cache tag `chot20261021`; các file lượt chốt được chỉ định không đánh dấu mẫu cache (`cached: false` ở mẫu có trường này).
- Máy dùng chung, tải trung bình khoảng 10 trong ghi chú lượt chốt. C6 ghi `loadavg_end` = 14,06 / 11,74 / 10,82; tải thay đổi trong khi chạy nên độ trễ là số đo tại máy lúc đó.
- Lượt 1 có cache cũ đã loại khỏi phần so sánh: `results/chot/lan1_cache_cu/`.
- C3 có thêm phép thử 3 khung trong `results/money_vnd/20261021-1741_multi_test.json`, nhưng đó là tham chiếu B3 của v1, không phải dòng 1 khung τ=0,999 trong bảng. Lượt trễ ghép đôi cũ/v2: `20261021-1742_turn_latency_n60.json`; lần chạy thứ hai trên `vh-chot` commit `706e08f`: `20261021-1750_turn_latency_n60.json`.
- C3 luồng đọc lại có số offline trong `docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md` §2: sai 2,7%, đúng 65,8%, từ chối 31,5%. Đây là số từ spec được brief chỉ định, không phải số của bảng JSON 1 khung.
- C4 có đánh giá mù Codex tại `reports/VQA_ASK_CHOT.md`; độ trễ A/B nằm ở `results/vqa_vizwiz/20261021-1747_latency_ab.json`. Bảng độ trễ chính phía trên dùng tổng hợp `general_ask.json`.
