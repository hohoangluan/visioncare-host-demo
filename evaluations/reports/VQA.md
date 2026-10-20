# Báo cáo hỏi đáp theo ảnh — VizWiz-VQA (C4)

Sinh tự động bởi `bench/report_llm.py`.

## C4 — VizWiz-VQA val

_Chạy 2026-10-20T21:00:38 trên gpu156; VH commit `ece963b`; file `results/vqa_vizwiz/20261020-2100_general_space.json`; lỗi mạng sau thử lại: 0 mẫu._

**Dữ liệu.** VizWiz-VQA (Gurari et al., CVPR 2018) tập **val** 4.319 câu (ảnh do người khiếm thị chụp); mẫu 300 câu `sample(seed=0)`: 196 answerable, 104 unanswerable. CC BY 4.0 theo vizwiz.org.

**Cách đo.** Câu hỏi EN dịch sang tiếng Việt một lần bằng LLM (`results/vqa_vizwiz/questions_vi.json`, người xem lại được). Trả lời bằng đường production `lanes.general.answer("space", câu_vi, ảnh 896 px)` — lưu ý intent `space` dùng prompt mô tả không gian, câu hỏi chỉ nằm ở dòng 'Người dùng nói'. Chấm: LLM (temperature 0, JSON schema, có ví dụ) nhận câu hỏi + câu trả lời VN + 10 đáp án EN → `{refused, matches}`; VQA acc = min(#người trùng/3, 1) (đáp án 'unanswerable' tính trùng khi trợ lý từ chối, xác định bằng mã). Bàn đo KHÔNG chạy cổng chất lượng trước LLM (đo LLM thuần); dòng 'có cổng' tính thêm.

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **Không từ chối trên câu unanswerable** (trước đây gọi là 'bịa') — metric chính | 72.1 % [63.5; 80.8] |
|   — trong đó trả lời KHỚP đáp án của thiểu số người gán (không phải bịa) | 30.8 % [22.1; 39.4] |
|   — trong đó **không khớp người nào** (cận trên của bịa thật; gồm cả câu né kiểu 'hỏi riêng' — cần chấm tay) | 41.3 % [32.7; 51.0] |
|   — nếu tính cả cổng chất lượng ảnh của production (`reject_reason('space')` chặn = từ chối) | 70.2 % [61.5; 78.8] |
| **VQA accuracy** toàn mẫu (LLM chấm khớp nghĩa × min(#trùng/3, 1)) | 70.7 % [65.9; 75.4] |
| VQA accuracy — câu trả lời được (answerable = 1) | 82.7 % [77.9; 87.4] |
| VQA accuracy — câu unanswerable (từ chối khớp 'unanswerable' của người) | 48.1 % [39.7; 56.4] |
| Tỉ lệ từ chối toàn mẫu | 12.0 % [8.7; 15.7] |
| Từ chối khi câu trả lời được (từ chối oan) | 3.6 % [1.0; 6.1] |
| Precision 'từ chối đúng' (từ chối ∧ unanswerable / từ chối) | 80.6 % [66.7; 91.7] |
| Recall 'từ chối đúng' (từ chối / unanswerable) | 27.9 % [19.2; 36.5] |
| Cổng chất lượng ảnh sẽ chặn | 1.7 % [0.3; 3.3] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 296 ms · p90 340 ms · p99 365 ms (n = 300)
- **Tổng thời gian**: p50 604 ms · p90 679 ms · p99 739 ms (n = 300)

Kiểm tay: file `results/vqa_vizwiz/handcheck_50.csv` (50 mẫu) **chưa có người chấm** — điền cột `human_refused` (0/1) và `human_n_match` (số đáp án EN trong 10 mà câu trả lời khớp nghĩa), rồi chạy lại báo cáo.

### Baseline công bố

| Phương pháp (bảng gốc, tập TEST VizWiz 2018) | Accuracy (VQA) | Unanswerable (độ chính xác, Bảng 4) |
|---|---|---|
| Q+I [18] dùng nguyên (huấn luyện trên VQA 2.0) | 0,137 | 0,070 |
| Q+I+BUA [6] dùng nguyên | 0,134 | 0,060 |
| FT [6] (tinh chỉnh trên VizWiz) | 0,475 | 0,776 |
| VizWiz [6] (huấn luyện chỉ trên VizWiz) | 0,469 | 0,805 |
| Con người | 0,75 | — |

Nguồn: Gurari et al., *VizWiz Grand Challenge: Answering Visual Questions from Blind People*, CVPR 2018 (arXiv 1802.08218): **Bảng 3** (trang 7, cột Acc), **Bảng 4** (trang 8, cột Unans); "human performance 0.75 accuracy" ở trang 7.
Dự đoán câu hỏi có trả lời được hay không (Bảng 6, PDF trang 14, tài liệu bổ sung): mô hình Q+I đạt Average Precision 0,717, Average F1 0,648; ảnh đơn (I) AP 0,640.

### Giới hạn / không so trực tiếp được

- **Không so ngang** với bảng gốc: khác protocol (val vs test; trợ lý zero-shot trả lời văn nói tiếng Việt, câu hỏi dịch qua LLM, LLM chấm khớp nghĩa; bài gốc phân loại đáp án đóng/gần-chính-xác). Công thức acc ở đây là min(n/3, 1) đơn giản, **không phải** leave-one-out chính thức. Chỉ để tham chiếu cỡ số.
- LLM chấm cùng họ với LLM được chấm (Gemma): có thể lệch; độ đồng thuận với người ở mục kiểm tay (cần điền `handcheck_50.csv`).
- Dịch EN→VN có thể làm lệch câu hỏi; câu hỏi `Summary`/'tóm tắt' vốn khó.
- Intent `space` không phải intent sản phẩm sẽ chọn cho mọi câu hỏi; kết quả là cho đường 'hỏi chung theo ảnh' mà PLAN quy định.
