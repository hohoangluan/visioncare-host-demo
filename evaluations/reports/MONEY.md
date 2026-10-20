# Báo cáo đọc tiền VND (C3)

**Dữ liệu cộng đồng (Kaggle), không có bài báo/baseline — chỉ chứng minh SeeVia đọc được tiền VND, không chứng minh hiệu quả.**

Sinh tự động bởi `bench/report_llm.py`.

**Dữ liệu.** `nguyentrongdai/vietnamese-currency` (Kaggle, licence 'Unknown'): ảnh PNG 192×144 webcam, 11 mệnh giá (200 đ … 500.000 đ) + thư mục `000000` không có tiền. Mẫu 30 ảnh/thư mục (360), **trải đều theo chỉ số khung** (sắp theo số trong tên file), không ngẫu nhiên. PNG → JPEG q90 trước khi gửi.

**Cách đo.** Câu hỏi "Đây là tờ tiền bao nhiêu?". Mệnh giá trích từ câu trả lời (chữ số + nghìn/ngàn/triệu/đồng, số có dấu chấm phân nghìn, hoặc chữ 'năm mươi nghìn'…); chỉ nhận 11 mệnh giá hợp lệ. Đúng = chỉ nêu đúng mệnh giá GT; sai = nêu mệnh giá khác (hoặc nhiều mệnh giá khác nhau); từ chối = không nêu giá và nói không thấy/chụp lại. Ảnh không tiền: nêu bất kỳ mệnh giá = bịa.

### Đường `general.answer("money", …)` (theo PLAN/METRICS)

_Chạy 2026-10-20T20:48:24 trên gpu156; VH commit `ece963b`; file `results/money_vnd/20261020-2048_general.json`; lỗi mạng sau thử lại: 0 mẫu._

360 ảnh. 

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **Tỉ lệ ĐỌC SAI mệnh giá** (nêu mệnh giá khác GT) — metric chính | 6.1 % [3.6; 8.8] |
| **Tỉ lệ bịa tiền** (ảnh KHÔNG có tiền mà nêu mệnh giá) | 0.0 % [0.0; 0.0] |
| Accuracy (đúng mệnh giá, ảnh có tiền) | 67.0 % [61.8; 71.8] |
| Sai / số lần có trả lời | 8.3 % [5.2; 12.0] |
| Từ chối / 'chụp lại' (ảnh có tiền) | 25.8 % [20.9; 30.6] |
| Không phân tích được mệnh giá | 1.2 % [0.3; 2.4] |
| Nêu nhiều mệnh giá khác nhau | 0.0 % [0.0; 0.0] |
| Cổng chất lượng ảnh `reject_reason('money')` sẽ chặn | 0.0 % [0.0; 0.0] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 222 ms · p90 236 ms · p99 251 ms (n = 360)
- **Tổng thời gian**: p50 222 ms · p90 258 ms · p99 262 ms (n = 360)

**Accuracy từng mệnh giá**

| Mệnh giá | Accuracy | Nói sai |
|---|---|---|
| 200 | 66.7 % [50.0; 83.3] | 3.3 % [0.0; 10.0] |
| 500 | 56.7 % [40.0; 73.3] | 0.0 % [0.0; 0.0] |
| 1.000 | 70.0 % [53.3; 86.7] | 0.0 % [0.0; 0.0] |
| 2.000 | 53.3 % [36.7; 70.0] | 6.7 % [0.0; 16.7] |
| 5.000 | 56.7 % [40.0; 73.3] | 6.7 % [0.0; 16.7] |
| 10.000 | 90.0 % [80.0; 100.0] | 6.7 % [0.0; 16.7] |
| 20.000 | 56.7 % [36.7; 73.3] | 0.0 % [0.0; 0.0] |
| 50.000 | 66.7 % [50.0; 83.3] | 6.7 % [0.0; 16.7] |
| 100.000 | 93.3 % [83.3; 100.0] | 3.3 % [0.0; 10.0] |
| 200.000 | 76.7 % [63.3; 90.0] | 6.7 % [0.0; 16.7] |
| 500.000 | 50.0 % [30.0; 70.0] | 26.7 % [13.3; 43.3] |

**Ma trận nhầm** (hàng = GT, cột = mệnh giá đầu tiên được nêu; `none` = không nêu mệnh giá; `multi` = nêu ≥ 2 mệnh giá khác nhau)

| GT \ nói | 200 | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 200000 | 500000 | none |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| không tiền | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 |
| 200 | 20 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 |
| 500 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 13 |
| 1000 | 0 | 0 | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 |
| 2000 | 0 | 0 | 1 | 16 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| 5000 | 0 | 0 | 0 | 0 | 17 | 0 | 0 | 2 | 0 | 0 | 0 | 11 |
| 10000 | 0 | 0 | 0 | 0 | 0 | 27 | 0 | 0 | 1 | 0 | 1 | 1 |
| 20000 | 0 | 0 | 0 | 0 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 13 |
| 50000 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 20 | 0 | 0 | 0 | 8 |
| 100000 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 28 | 0 | 0 | 1 |
| 200000 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 23 | 0 | 5 |
| 500000 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 6 | 0 | 0 | 15 | 7 |

### Đường `ocr_live.spoken(jpeg, "money")` (đường thật của làn B trong `pipeline/final_router.py`)

_Chạy 2026-10-20T20:49:46 trên gpu156; VH commit `ece963b`; file `results/money_vnd/20261020-2049_ocr_spoken.json`; lỗi mạng sau thử lại: 0 mẫu._

360 ảnh. 

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **Tỉ lệ ĐỌC SAI mệnh giá** (nêu mệnh giá khác GT) — metric chính | 11.2 % [8.2; 14.5] |
| **Tỉ lệ bịa tiền** (ảnh KHÔNG có tiền mà nêu mệnh giá) | 0.0 % [0.0; 0.0] |
| Accuracy (đúng mệnh giá, ảnh có tiền) | 67.3 % [62.4; 72.1] |
| Sai / số lần có trả lời | 14.3 % [10.4; 18.6] |
| Từ chối / 'chụp lại' (ảnh có tiền) | 20.9 % [16.7; 25.5] |
| Không phân tích được mệnh giá | 0.6 % [0.0; 1.5] |
| Nêu nhiều mệnh giá khác nhau | 0.3 % [0.0; 0.9] |
| Cổng chất lượng ảnh `reject_reason('money')` sẽ chặn | 0.0 % [0.0; 0.0] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 211 ms · p90 234 ms · p99 253 ms (n = 360)
- **Tổng thời gian**: p50 211 ms · p90 255 ms · p99 259 ms (n = 360)

**Accuracy từng mệnh giá**

| Mệnh giá | Accuracy | Nói sai |
|---|---|---|
| 200 | 66.7 % [50.0; 83.3] | 13.3 % [3.3; 26.7] |
| 500 | 56.7 % [40.0; 73.4] | 13.3 % [3.3; 26.7] |
| 1.000 | 66.7 % [50.0; 83.3] | 6.7 % [0.0; 16.7] |
| 2.000 | 53.3 % [36.7; 70.0] | 23.3 % [10.0; 40.0] |
| 5.000 | 53.3 % [36.7; 70.0] | 6.7 % [0.0; 16.7] |
| 10.000 | 90.0 % [80.0; 100.0] | 6.7 % [0.0; 16.7] |
| 20.000 | 56.7 % [40.0; 73.3] | 0.0 % [0.0; 0.0] |
| 50.000 | 76.7 % [60.0; 90.0] | 6.7 % [0.0; 16.7] |
| 100.000 | 93.3 % [83.3; 100.0] | 6.7 % [0.0; 16.7] |
| 200.000 | 73.3 % [56.7; 86.7] | 13.3 % [3.3; 26.7] |
| 500.000 | 53.3 % [33.3; 73.3] | 26.7 % [13.3; 43.3] |

**Ma trận nhầm** (hàng = GT, cột = mệnh giá đầu tiên được nêu; `none` = không nêu mệnh giá; `multi` = nêu ≥ 2 mệnh giá khác nhau)

| GT \ nói | 200 | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 200000 | 500000 | multi | none |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| không tiền | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 |
| 200 | 20 | 0 | 0 | 1 | 0 | 0 | 2 | 1 | 0 | 0 | 0 | 0 | 6 |
| 500 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 2 | 0 | 9 |
| 1000 | 0 | 0 | 20 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 8 |
| 2000 | 0 | 0 | 2 | 16 | 0 | 3 | 1 | 1 | 0 | 0 | 0 | 0 | 7 |
| 5000 | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 12 |
| 10000 | 0 | 0 | 0 | 0 | 0 | 27 | 0 | 0 | 1 | 0 | 1 | 0 | 1 |
| 20000 | 0 | 0 | 0 | 0 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 13 |
| 50000 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 23 | 0 | 0 | 0 | 1 | 5 |
| 100000 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 28 | 0 | 0 | 0 | 0 |
| 200000 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 2 | 22 | 0 | 0 | 4 |
| 500000 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 6 | 0 | 0 | 16 | 0 | 6 |

### Baseline công bố

**Không có** — không tồn tại bộ tiền VND công khai có bài báo + baseline (đã tra 2026-10-20; BankNote-Net của Microsoft không có VND và chỉ công bố embedding). Không đối chiếu.

### Giới hạn / không so trực tiếp được

- Một người, một phông nền, webcam 192×144 (thấp hơn ảnh kính 1600 px); khung video gần trùng nhau → **CI bootstrap theo ảnh lạc quan**, số này **không tổng quát** ra ngoài đời.
- Licence Kaggle không rõ; chỉ dùng đánh giá nội bộ.
- Ảnh nhỏ hơn mọi ảnh thật của kính nên cổng chất lượng ảnh (`gate_reject_rate_money`) có thể chặn khác ngoài đời.
