# C4 — Hỏi về ảnh: prompt `space` (cũ) vs `ask` (mới) — so ghép đôi MÙ

VizWiz-VQA val, mẫu test 300 (seed 0), 150 câu ghép đôi. Giám khảo: **Codex gpt-6-luna nhìn ảnh** (lượt chốt 2026-10-21, câu trả lời `ask` gọi MỚI trên vh-chot @ce592ae; `space` = baseline 2026-10-20), thấy 2 câu trả lời theo thứ tự ngẫu nhiên, không biết câu nào của prompt nào. Prompt `ask` chỉnh trên 100 câu dev KHÁC 300 câu này. CI 95 % bootstrap; Δ = ask − space theo cặp; cột 'chỉ cũ / chỉ mới' = số câu bất đồng.

| Chỉ số | space (cũ) | ask (mới) | Δ [CI] | chỉ cũ / chỉ mới |
|---|---|---|---|---|
| Câu đầu trả lời thẳng câu hỏi ↑ | 30.7 % [23.3; 38.0] | 98.7 % [96.7; 100.0] | +68.0 đ.% [+60.7; +74.7] | 0 / 102 |
| Có nội dung thừa ↓ | 94.0 % [90.0; 98.0] | 7.3 % [3.3; 11.3] | -86.7 đ.% [-92.0; -80.7] | 131 / 1 |
| Đúng với ảnh ↑ | 67.3 % [60.0; 75.3] | 90.0 % [85.3; 94.0] | +22.7 đ.% [+14.7; +30.0] | 5 / 39 |
| Bịa (khẳng định điều ảnh không có) ↓ | 9.3 % [4.7; 14.0] | 8.0 % [4.0; 12.7] | -1.3 đ.% [-6.7; +4.0] | 9 / 7 |
| Từ chối | 7.3 % [3.3; 12.0] | 27.3 % [20.7; 34.0] | +20.0 đ.% [+14.0; +26.0] | 0 / 30 |
| Từ chối CÓ lý do + cách sửa ↑ | 2.7 % [0.7; 5.3] | 25.3 % [18.7; 32.0] | +22.7 đ.% [+16.0; +29.3] | 0 / 34 |
| Số từ (trung vị) | 35 | 21 | ×0.56 (trung bình) | |
| Thời gian đọc TTS ước tính (~3,6 từ/s, trung vị) | 9.7 s | 5.8 s | | |

**Chọn câu tốt hơn:** ask 138 · space 11 · hoà 1 — tỉ lệ thắng của ask (hoà = ½) 92.3 % [88.0; 96.3]. Kiểm thiên vị vị trí: chọn câu số 1 54.7 % [46.7; 62.7].

## Theo loại câu hỏi (nhãn đa số VizWiz)

| Nhóm | n | Chỉ số | space | ask |
|---|---|---|---|---|
| answerable | 100 | Câu đầu trả lời thẳng câu hỏi ↑ | 34.0 % [25.0; 43.0] | 98.0 % [95.0; 100.0] |
| answerable | 100 | Có nội dung thừa ↓ | 95.0 % [90.0; 99.0] | 8.0 % [3.0; 14.0] |
| answerable | 100 | Đúng với ảnh ↑ | 80.0 % [72.0; 87.0] | 90.0 % [83.0; 95.0] |
| answerable | 100 | Bịa (khẳng định điều ảnh không có) ↓ | 8.0 % [4.0; 14.0] | 6.0 % [2.0; 11.0] |
| answerable | 100 | Từ chối | 2.0 % [0.0; 5.0] | 7.0 % [3.0; 13.0] |
| answerable | 100 | Từ chối CÓ lý do + cách sửa ↑ | 1.0 % [0.0; 3.0] | 6.0 % [2.0; 11.0] |
| unanswerable | 50 | Câu đầu trả lời thẳng câu hỏi ↑ | 24.0 % [12.0; 36.0] | 100.0 % [100.0; 100.0] |
| unanswerable | 50 | Có nội dung thừa ↓ | 92.0 % [84.0; 98.0] | 6.0 % [0.0; 14.0] |
| unanswerable | 50 | Đúng với ảnh ↑ | 42.0 % [28.0; 56.0] | 90.0 % [82.0; 98.0] |
| unanswerable | 50 | Bịa (khẳng định điều ảnh không có) ↓ | 12.0 % [4.0; 22.0] | 12.0 % [4.0; 22.0] |
| unanswerable | 50 | Từ chối | 18.0 % [8.0; 28.0] | 68.0 % [56.0; 80.0] |
| unanswerable | 50 | Từ chối CÓ lý do + cách sửa ↑ | 6.0 % [0.0; 14.0] | 64.0 % [52.0; 76.0] |

## Chỉ số cũ của bàn đo (Gemma-chấm, VQA acc chuẩn VizWiz)

| Chỉ số | space | ask |
|---|---|---|
| VQA acc (tất cả) | 70.7 % [65.9; 75.4] | 83.8 % [80.1; 87.4] |
| VQA acc (câu trả lời được) | 82.7 % [77.9; 87.4] | 86.9 % [82.5; 91.0] |
| Không từ chối trên câu unanswerable | 72.1 % [63.5; 80.8] | 40.4 % [30.8; 50.0] |
| Từ chối trên câu trả lời được | 3.6 % [1.0; 6.1] | 4.1 % [1.5; 7.1] |

## Độ trễ (LLM xa Gemma 4 26B; ms p50 / p90 / p99)

Gọi MỚI trên cùng ảnh, hai prompt xen kẽ, thứ tự đảo ngẫu nhiên (`bench/vqa_latency_ab.py`).

| | space | ask | Δ ghép đôi (ask − space) [CI] |
|---|---|---|---|
| TTFT — câu nói đầu ra khỏi `general.answer` (≥ 2 từ + dấu câu, hoặc 8 từ) | 245 / 287 / 308 | 293 / 308 / 338 | +42 ms [+34; +51] |
| Tổng — hết câu trả lời | 541 / 639 / 714 | 375 / 512 / 1029 | -144 ms [-180; -97] |

TTFT của `ask` cao hơn vì câu nói đầu giờ là ĐÁP ÁN (thường đủ 8 từ mới cắt), còn `space` cắt ngay ở "Trong nhà." — đáp án thật của `space` thường nằm ở câu 2–3, tức sau mốc 'tổng' của câu đầu.

## Đối chứng âm (giám khảo có thật sự nhìn ảnh / đọc kỹ không)

- Câu bị tráo sang ảnh khác bị đánh bịa hoặc sai: **100.0 % [100.0; 100.0]** (cần ≥ 80 %)
- Hai câu y hệt được chấm hoà: **100.0 % [100.0; 100.0]** (cần ≥ 80 %)
- Kết luận: **ĐẠT**

## Đối chiếu giám khảo với người chấm tay (50 câu, bản cũ)

Ghi chú tay được mã hoá: 'thừa' = ghi chú có *thừa/dư/dài/lan man/chỉ cần/là đủ*; 'không trúng câu hỏi' = *không trả lời câu hỏi/không tập trung/trọng tâm*.

| Nhãn | Người = 1 | Giám khảo = 1 | Cả hai | Đồng ý |
|---|---|---|---|---|
| Thừa | 32 | 45 | 29 | 62 % (n=50) |
| Không trúng câu hỏi (giám khảo: direct = 0) | 12 | 35 | 10 | 46 % (n=50) |
| Bịa | 8 | 3 | 2 | 86 % (n=50) |

Trên đúng 50 câu bạn đã chấm: Câu đầu trả lời thẳng câu hỏi 30 % → 100 % · Có nội dung thừa 90 % → 8 % · Đúng với ảnh 74 % → 88 % · Bịa (khẳng định điều ảnh không có) 6 % → 8 %

## Định tuyến: câu hỏi về ảnh đi vào chức năng nào (300 câu VizWiz đã dịch, bộ phân loại Gemma production)

| Intent | Đường xử lý | Trước | Sau |
|---|---|---|---|
| `ask` | trả lời đúng câu hỏi (mới) | 0 (0 %) | 254 (85 %) |
| `space` | mô tả không gian | 146 (49 %) | 10 (3 %) |
| `ocr` | đọc cả văn bản, bỏ qua câu hỏi | 83 (28 %) | 22 (7 %) |
| `chat` | trả lời KHÔNG có ảnh | 62 (21 %) | 13 (4 %) |
| `find` | tìm đồ | 6 (2 %) | 0 (0 %) |
| `nav_start` | dẫn đường | 1 (0 %) | 1 (0 %) |
| `money` | đọc tiền | 2 (1 %) | 0 (0 %) |

Hồi quy bộ phân loại trên tập gold intent của VH (nhãn cũ, chưa có `ask` — câu hỏi một chi tiết in trên nhãn mà gold ghi `ocr` nay ra `ask` bị tính là SAI ở đây):

| Tập | acc trước | acc sau | được / mất (McNemar) | p50 / p90 ms |
|---|---|---|---|---|
| gold dev | 94.7 % | 93.9 % | 5 / 7 (p = 0.77) | 92 / 122 → 79 / 102 |
| gold test | 94.6 % | 97.3 % | 4 / 0 (p = 0.12) | 107 / 128 → 82 / 104 |

Nguồn: `results/vqa_vizwiz/20261020-2100_general_space.json` (space), `results/chot/vqa_vizwiz/20261021-1746_general_ask.json` (ask). Chạy lại: `python -m bench.vqa_pair_judge build` → giám khảo (Sonnet subagent theo `BRIEF.md`, hoặc Codex `run.sh`) → `report`.
