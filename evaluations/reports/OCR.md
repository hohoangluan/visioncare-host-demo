# Báo cáo OCR — đọc chữ bằng LLM (Gemma 4 26B)

Sinh tự động bởi `bench/report_llm.py` từ JSON mới nhất trong `results/`. Số liệu = METRICS.md C2a/C2b/C2c.

## C2a — OCR đọc nguyên văn: VinText test

_Chạy 2026-10-20T20:53:31 trên gpu156; VH commit `ece963b`; file `results/ocr_vintext/20261020-2053_raw_spoken.json`; lỗi mạng sau thử lại: 0 mẫu._

**Dữ liệu.** VinText (Nguyen et al., *Dictionary-guided Scene Text Recognition*, CVPR 2021): 300 ảnh test `im1201..im1500` (đủ tập), chữ cảnh Việt có dấu. Dữ liệu chỉ cho nghiên cứu/giáo dục, trích dẫn bài CVPR 2021.

**Cách đo.** `lanes.ocr_live.spoken(jpeg, "raw", "bench")` (đường production: resize 1600 px q90, prompt `_RAW`, temperature 0, câu đầu cắt ≤ 8 từ). 297/300 ảnh được chấm. Số = chuỗi chữ số (nhóm phân nghìn gộp, bỏ dấu), so multiset với GT; BoW = multiset từ (NFC, chữ thường, bỏ dấu câu, giữ dấu tiếng Việt); CER trên GT sắp trên→dưới, trái→phải. Hộp `###` bị bỏ.

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **Tỉ lệ con số SAI được nói ra** (số đầu ra không có trong GT / tổng số trong đầu ra) — metric chính | 25.8 % [20.3; 31.4] |
|   — bản khoan dung với GT tách hộp (số 'sai' mà vẫn là đoạn liền của dãy chữ số GT thì tha) | 7.1 % [4.6; 9.5] |
| Ảnh có ít nhất 1 con số sai | 20.9 % [16.2; 25.6] |
| Tỉ lệ số bỏ sót (số GT không có trong đầu ra) | 32.7 % [27.0; 38.7] |
| BoW precision (trung bình theo ảnh) | 87.9 % [86.2; 89.5] |
| BoW recall | 81.5 % [79.2; 83.8] |
| BoW F1 | 83.3 % [81.3; 85.2] |
| CER (từ chối tính = 100 %) | 27.7 % [24.8; 31.2] |
| CER (chỉ ảnh không từ chối) | 27.7 % [24.8; 31.2] |
| Tỉ lệ từ chối (`KHONG_CO_CHU` / 'không thấy chữ') | 0.0 % [0.0; 0.0] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 393 ms · p90 545 ms · p99 659 ms (n = 300)
- **Tổng thời gian**: p50 610 ms · p90 1301 ms · p99 2399 ms (n = 300)

### Baseline công bố

| Phương pháp (bảng gốc) | Không từ điển (H-mean) | Có từ điển (H-mean) |
|---|---|---|
| Mask TextSpotter v3 (alphabet: Anh + ký tự dẫn xuất) | 53,4 | 57,4 |
| ABCNet (alphabet: Anh + ký tự dẫn xuất) | 50,6 | 55,1 |
| ABCNet (alphabet: Anh + ký hiệu dấu) | 54,2 | 58,5 |
| ABCNet+D (đề xuất, alphabet Anh + ký hiệu dấu) | 57,4 | 63,6 |
| Mask TextSpotter v3+D (alphabet Anh + ký hiệu dấu) | 68,5 | 70,3 |

Nguồn: Nguyen et al., *Dictionary-guided Scene Text Recognition*, CVPR 2021, **Bảng 5** (PDF trang 8, số trang in 7390), "Recognition accuracy (H-mean) on the VinText dataset".
Bản PDF: openaccess.thecvf.com/content/CVPR2021/papers/Nguyen_Dictionary-Guided_Scene_Text_Recognition_CVPR_2021_paper.pdf.

### Giới hạn / không so trực tiếp được

- **Không so được** với bảng trên: bài đo end-to-end (phát hiện + nhận dạng, H-mean theo hộp); SeeVia chỉ đọc cả ảnh ra một đoạn văn. Không có số baseline nào cho 'số bịa'.
- GT chỉ có các hộp được gán nhãn (bỏ `###` không đọc được) → chữ thật mà LLM đọc thêm bị tính là sai: BoW precision và 'số sai' **bị thổi phồng** (thấp hơn thực tế khi người dùng muốn nghe hết). Recall và 'số bỏ sót' công bằng hơn.
- GT tách số thành nhiều hộp ('0','2') còn LLM viết liền ('02') → số 'sai' giả; bản khoan dung ở trên gỡ phần này.
- Đầu ra có thể bị cắt/đổi theo cách đọc của LLM (không theo đúng thứ tự hộp) nên CER chỉ là thước tương đối.

## C2b — OCR hỏi số tiền / ngày: SROIE test

_Chạy 2026-10-20T20:46:59 trên gpu156; VH commit `ece963b`; file `results/ocr_sroie/20261020-2046_ask_spoken.json`; lỗi mạng sau thử lại: 0 mẫu._

**Dữ liệu.** SROIE ICDAR 2019 (Huang et al., ICDAR 2019), bản đăng lại jsdnrs/ICDAR2019-SROIE trên HuggingFace, test 361 hoá đơn (ảnh JPEG; hoá đơn Malaysia, tiếng Anh). Mỗi hoá đơn 2 câu hỏi tiếng Việt: "Tổng số tiền phải trả trên hoá đơn này là bao nhiêu?" / "Hoá đơn này ghi ngày nào?".

**Cách đo.** VH **chưa có đường production riêng cho 'hỏi về chữ'** (chế độ chỉ có trong `docs/ARCHITECTURE_OCR.md`; `final_router` gọi `ocr_live.spoken(.., mode)` không truyền câu hỏi). Bàn đo dùng `prompts._COMMON` + câu hỏi qua đúng `ocr_live.read_image` (resize 1600 px q90, temperature 0, max_tokens 1024, xử lý sentinel) rồi `short_first_sentence`. Total = **số đầu tiên** trong câu trả lời, so ±0,005 với GT; date = ngày đầu tiên đọc được (dd/mm/yy(yy), dd MON yy, 'ngày D tháng M năm Y'…), so (ngày, tháng, năm), mơ hồ ngày/tháng đọc theo d/m/y. Mỗi câu: đúng / **nói sai** / từ chối ('không đọc chắc', 'chụp lại', sentinel) / không phân tích được.

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **Tổng tiền: tỉ lệ NÓI SAI** (nêu giá trị khác GT) — metric chính | 6.4 % [4.2; 9.1] |
| Tổng tiền: nói sai / số lần có trả lời | 6.4 % [4.2; 9.1] |
| Tổng tiền: Exact match | 93.6 % [90.9; 95.8] |
| Tổng tiền: từ chối | 0.0 % [0.0; 0.0] |
| Tổng tiền: không phân tích được (không số/ngày, không phải từ chối) | 0.0 % [0.0; 0.0] |
| **Ngày: tỉ lệ NÓI SAI** (nêu giá trị khác GT) — metric chính | 3.9 % [1.9; 5.8] |
| Ngày: nói sai / số lần có trả lời | 3.9 % [1.9; 5.8] |
| Ngày: Exact match | 96.1 % [94.2; 98.1] |
| Ngày: từ chối | 0.0 % [0.0; 0.0] |
| Ngày: không phân tích được (không số/ngày, không phải từ chối) | 0.0 % [0.0; 0.0] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 349 ms · p90 484 ms · p99 542 ms (n = 722)
- **Tổng thời gian**: p50 379 ms · p90 505 ms · p99 553 ms (n = 722)

### Baseline công bố

| Hạng | Đội (bảng gốc) | Hmean Task 3 (%) |
|---|---|---|
| 1 | Ping An Property & Casualty Insurance Company | 90,49 |
| 2 | EAST det + Multi-class classification (Baidu) | 89,70 |
| 3 | H&H Lab (HUST_VLRGROUP / HUAWEI_CLOUD_EI) | 89,63 |
| 4 | CLOVA OCR | 89,05 |
| 5 | NiuBiHongHang | 87,61 |

Nguồn: Huang et al., *ICDAR2019 Competition on Scanned Receipt OCR and Information Extraction*, arXiv 2103.10213, **Hình 5** ("Top 10 methods for Task 3"), trang 5.
Ba cột số trong hình (Recall / Precision / Hmean; hàng thứ 6: 83,00 / 83,24 / 83,12) — bảng này chép cột cuối. Văn bản bài (trang 5) xác nhận chỉ một phương pháp vượt 90 % Hmean (90,49 %).

### Giới hạn / không so trực tiếp được

- **Không so trực tiếp**: bảng gốc là F1 trích 4 trường (company, date, address, total) của hệ chuyên dụng trên văn bản đã OCR; ở đây là câu hỏi tự nhiên bằng tiếng Việt về 2 trường, chấm đúng/sai tuyệt đối. Bài không công bố riêng total/date.
- Quy tắc 'số đầu tiên' có thể chấm sai khi câu trả lời nêu số khác trước tổng; đã ghi `output` đầy đủ ở `per_sample` để chấm lại không cần gọi LLM.
- Ảnh SROIE nhỏ hơn ảnh kính (UXGA 1600×1200) và là hoá đơn Malaysia (RM) — không đại diện hoá đơn Việt.

## C2c — OCR hỏi đáp tiếng Việt: ViTextVQA test

_Chạy 2026-10-20T20:55:13 trên gpu156; VH commit `ece963b`; file `results/ocr_vitextvqa/20261020-2055_ask_spoken.json`; lỗi mạng sau thử lại: 0 mẫu._

**Dữ liệu.** ViTextVQA (arXiv 2404.10652), bản đăng lại xuandin/ViTextVQA trên HuggingFace; mẫu 300 câu hỏi `sample(seed=0)` (nhóm theo (ảnh, câu hỏi): nhiều dòng annotation cùng câu = nhiều đáp án chấp nhận, lấy max).

**Cách đo.** Như C2b (`ask_prompt` + `ocr_live.spoken`; VH chưa có đường 'hỏi về chữ' riêng). Chuẩn hoá: NFC, chữ thường, dấu câu→khoảng trắng; chữ số nối qua `.`/`,` (nhãn gốc đã tách token kiểu '0938 . 938 . 616') ở cả hai phía. Bịa số = GT có chuỗi số, câu trả lời không từ chối và nêu một chuỗi số không có trong GT.

| Metric | Giá trị (95 % CI bootstrap theo mẫu) |
|---|---|
| **EM** (khớp hoàn toàn sau chuẩn hoá, max qua đáp án) — metric bài gốc | 8.7 % [5.7; 12.0] |
| **F1 token** (max qua đáp án) — metric bài gốc | 43.1 % [39.4; 46.4] |
| Đáp án nằm trong câu trả lời (không phạt văn nói) | 66.3 % [61.3; 71.7] |
| Bịa số khi GT có số (nêu số không có trong đáp án) | 20.0 % [11.8; 29.4] |
| Tỉ lệ từ chối | 9.0 % [5.7; 12.3] |

- **TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)**: p50 285 ms · p90 411 ms · p99 581 ms (n = 300)
- **Tổng thời gian**: p50 304 ms · p90 497 ms · p99 710 ms (n = 300)

### Baseline công bố

| Mô hình (bảng gốc) | F1 (%) | EM (%) |
|---|---|---|
| M4C base | 25,46 | 10,26 |
| BLIP-2 large | 38,47 | 15,58 |
| LaTr large | 42,34 | 20,94 |
| SaL base | 43,49 | 20,11 |
| PreSTU large (tốt nhất trong nhóm baseline) | 44,93 | 22,64 |
| ViTextBLIP-2 (đề xuất) | 53,95 | 25,48 |

Nguồn: arXiv 2404.10652, **Bảng 6** (trang 15) "Results of models on the ViTextVQA test set" (chép 6/10 hàng; đủ ở bài).

| 100 mẫu ngẫu nhiên của test (Bảng 7, trang 16) | F1 0-shot | EM 0-shot | Tốt nhất (số-shot) F1 / EM |
|---|---|---|---|
| GPT-4o | 55,51 | 25,00 | 76,67 (3-shot) / 56,00 (3-shot) |
| Gemini-1.5-flash | 57,75 | 26,00 | 64,40 (5-shot) / 39,00 (5-shot) |
| QwenVL-7b | 53,80 | 28,00 | 54,85 (3-shot) / 36,00 (1-, 3-shot) |
| Người | 96,42 | 88,00 | — |

Metric bài gốc (mục 5.4): EM = tỉ lệ dự đoán khớp hoàn toàn đáp án; F1 = trùng lặp token giữa dự đoán và đáp án. Bản arXiv đã tải 2026-10-20 (có thể khác bản hội nghị).

### Giới hạn / không so trực tiếp được

- Metric giống bài gốc nhưng **tập mẫu khác** (300 câu, không phải 100 mẫu của Bảng 7, không phải cả test) và tiền xử lý đáp án nhóm theo câu hỏi → so *tham khảo*, không so trực tiếp. SeeVia chạy zero-shot, văn nói tiếng Việt dài hơn đáp án ngắn nên EM/F1 bị phạt; dùng 'đáp án nằm trong câu trả lời' để đọc đúng năng lực.
- Các mô hình ở Bảng 6 được huấn luyện trên ViTextVQA; SeeVia thì không.
- Dữ liệu HF đăng lại, licence không ghi trên thẻ; chỉ dùng đánh giá.

