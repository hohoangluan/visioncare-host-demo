# C4 — Hỏi về ảnh: prompt `space` (cũ) vs `ask` (mới) — so ghép đôi MÙ

VizWiz-VQA val, mẫu test 300 (seed 0), 150 câu ghép đôi. Giám khảo: Claude Sonnet **nhìn ảnh**, thấy 2 câu trả lời theo thứ tự ngẫu nhiên, không biết câu nào của prompt nào. Prompt `ask` chỉnh trên 100 câu dev KHÁC 300 câu này. CI 95 % bootstrap; Δ = ask − space theo cặp; cột 'chỉ cũ / chỉ mới' = số câu bất đồng.

| Chỉ số | space (cũ) | ask (mới) | Δ [CI] | chỉ cũ / chỉ mới |
|---|---|---|---|---|
| Câu đầu trả lời thẳng câu hỏi ↑ | 26.0 % [19.3; 33.3] | 98.7 % [96.7; 100.0] | +72.7 đ.% [+65.3; +80.0] | 0 / 109 |
| Có nội dung thừa ↓ | 94.7 % [90.7; 98.0] | 6.7 % [3.3; 10.7] | -88.0 đ.% [-92.7; -82.7] | 132 / 0 |
| Đúng với ảnh ↑ | 73.3 % [66.7; 80.7] | 92.0 % [87.3; 96.0] | +18.7 đ.% [+10.7; +26.0] | 7 / 35 |
| Bịa (khẳng định điều ảnh không có) ↓ | 12.0 % [7.3; 18.0] | 8.0 % [4.0; 12.7] | -4.0 đ.% [-10.0; +2.0] | 15 / 9 |
| Từ chối | 11.3 % [6.7; 17.3] | 30.0 % [22.0; 37.3] | +18.7 đ.% [+12.0; +25.3] | 1 / 29 |
| Từ chối CÓ lý do + cách sửa ↑ | 3.3 % [0.7; 6.7] | 27.3 % [20.0; 34.0] | +24.0 đ.% [+16.7; +30.7] | 1 / 37 |
| Số từ (trung vị) | 35 | 20 | ×0.58 (trung bình) | |
| Thời gian đọc TTS ước tính (~3,6 từ/s, trung vị) | 9.7 s | 5.6 s | | |

**Chọn câu tốt hơn:** ask 134 · space 14 · hoà 2 — tỉ lệ thắng của ask (hoà = ½) 90.0 % [85.3; 94.3]. Kiểm thiên vị vị trí: chọn câu số 1 52.7 % [44.6; 60.7].

## Theo loại câu hỏi (nhãn đa số VizWiz)

| Nhóm | n | Chỉ số | space | ask |
|---|---|---|---|---|
| answerable | 100 | Câu đầu trả lời thẳng câu hỏi ↑ | 31.0 % [23.0; 40.0] | 99.0 % [97.0; 100.0] |
| answerable | 100 | Có nội dung thừa ↓ | 97.0 % [93.0; 100.0] | 8.0 % [3.0; 14.0] |
| answerable | 100 | Đúng với ảnh ↑ | 88.0 % [81.0; 94.0] | 94.0 % [88.0; 98.0] |
| answerable | 100 | Bịa (khẳng định điều ảnh không có) ↓ | 8.0 % [3.0; 14.0] | 4.0 % [1.0; 8.0] |
| answerable | 100 | Từ chối | 4.0 % [1.0; 8.0] | 9.0 % [4.0; 16.0] |
| answerable | 100 | Từ chối CÓ lý do + cách sửa ↑ | 2.0 % [0.0; 5.0] | 6.0 % [2.0; 12.0] |
| unanswerable | 50 | Câu đầu trả lời thẳng câu hỏi ↑ | 16.0 % [6.0; 28.0] | 98.0 % [94.0; 100.0] |
| unanswerable | 50 | Có nội dung thừa ↓ | 90.0 % [80.0; 98.0] | 4.0 % [0.0; 10.0] |
| unanswerable | 50 | Đúng với ảnh ↑ | 44.0 % [30.0; 58.0] | 88.0 % [78.0; 96.0] |
| unanswerable | 50 | Bịa (khẳng định điều ảnh không có) ↓ | 20.0 % [10.0; 32.0] | 16.0 % [8.0; 26.0] |
| unanswerable | 50 | Từ chối | 26.0 % [14.0; 38.0] | 72.0 % [60.0; 84.0] |
| unanswerable | 50 | Từ chối CÓ lý do + cách sửa ↑ | 6.0 % [0.0; 14.0] | 70.0 % [58.0; 82.0] |

## Chỉ số cũ của bàn đo (Gemma-chấm, VQA acc chuẩn VizWiz)

| Chỉ số | space | ask |
|---|---|---|
| VQA acc (tất cả) | 70.7 % [65.9; 75.4] | 83.6 % [79.8; 87.3] |
| VQA acc (câu trả lời được) | 82.7 % [77.9; 87.4] | 87.6 % [83.3; 91.5] |
| Không từ chối trên câu unanswerable | 72.1 % [63.5; 80.8] | 40.4 % [30.8; 50.0] |
| Từ chối trên câu trả lời được | 3.6 % [1.0; 6.1] | 4.6 % [2.0; 7.7] |

## Độ trễ (LLM xa Gemma 4 26B; ms p50 / p90 / p99)

Gọi MỚI trên cùng ảnh, hai prompt xen kẽ, thứ tự đảo ngẫu nhiên (`bench/vqa_latency_ab.py`).

| | space | ask | Δ ghép đôi (ask − space) [CI] |
|---|---|---|---|
| TTFT — câu nói đầu ra khỏi `general.answer` (≥ 2 từ + dấu câu, hoặc 8 từ) | 249 / 284 / 310 | 296 / 311 / 337 | +41 ms [+33; +49] |
| Tổng — hết câu trả lời | 544 / 625 / 678 | 386 / 522 / 1342 | -127 ms [-178; -48] |

TTFT của `ask` cao hơn vì câu nói đầu giờ là ĐÁP ÁN (thường đủ 8 từ mới cắt), còn `space` cắt ngay ở "Trong nhà." — đáp án thật của `space` thường nằm ở câu 2–3, tức sau mốc 'tổng' của câu đầu.

## Đối chứng âm (giám khảo có thật sự nhìn ảnh / đọc kỹ không)

- Câu bị tráo sang ảnh khác bị đánh bịa hoặc sai: **100.0 % [100.0; 100.0]** (cần ≥ 80 %)
- Hai câu y hệt được chấm hoà: **100.0 % [100.0; 100.0]** (cần ≥ 80 %)
- Kết luận: **ĐẠT**

## Đối chiếu giám khảo với người chấm tay (50 câu, bản cũ)

Ghi chú tay được mã hoá: 'thừa' = ghi chú có *thừa/dư/dài/lan man/chỉ cần/là đủ*; 'không trúng câu hỏi' = *không trả lời câu hỏi/không tập trung/trọng tâm*.

| Nhãn | Người = 1 | Giám khảo = 1 | Cả hai | Đồng ý |
|---|---|---|---|---|
| Thừa | 32 | 46 | 31 | 68 % (n=50) |
| Không trúng câu hỏi (giám khảo: direct = 0) | 12 | 35 | 10 | 46 % (n=50) |
| Bịa | 8 | 4 | 2 | 84 % (n=50) |

Trên đúng 50 câu bạn đã chấm: Câu đầu trả lời thẳng câu hỏi 30 % → 100 % · Có nội dung thừa 92 % → 10 % · Đúng với ảnh 82 % → 86 % · Bịa (khẳng định điều ảnh không có) 8 % → 10 %

## Định tuyến: câu hỏi về ảnh đi vào chức năng nào (300 câu VizWiz đã dịch, bộ phân loại Gemma production)

| Intent | Đường xử lý | Trước | Sau |
|---|---|---|---|
| `ask` | trả lời đúng câu hỏi (mới) | 0 (0 %) | 254 (85 %) |
| `space` | mô tả không gian | 146 (49 %) | 10 (3 %) |
| `ocr` | đọc cả văn bản, bỏ qua câu hỏi | 83 (28 %) | 22 (7 %) |
| `chat` | trả lời KHÔNG có ảnh | 62 (21 %) | 13 (4 %) |
| `find` | tìm đồ | 6 (2 %) | 0 (0 %) |
| `money` | đọc tiền | 2 (1 %) | 0 (0 %) |
| `nav_start` | dẫn đường | 1 (0 %) | 1 (0 %) |

Hồi quy bộ phân loại trên tập gold intent của VH (nhãn cũ, chưa có `ask` — câu hỏi một chi tiết in trên nhãn mà gold ghi `ocr` nay ra `ask` bị tính là SAI ở đây):

| Tập | acc trước | acc sau | được / mất (McNemar) | p50 / p90 ms |
|---|---|---|---|---|
| gold dev | 94.7 % | 93.9 % | 5 / 7 (p = 0.77) | 92 / 122 → 79 / 102 |
| gold test | 94.6 % | 97.3 % | 4 / 0 (p = 0.12) | 107 / 128 → 82 / 104 |

Nguồn: `results/vqa_vizwiz/20261020-2100_general_space.json` (space), `results/vqa_vizwiz/20261021-1404_general_ask.json` (ask). Chạy lại: `python -m bench.vqa_pair_judge build` → giám khảo (Sonnet subagent theo `BRIEF.md`, hoặc Codex `run.sh`) → `report`.
