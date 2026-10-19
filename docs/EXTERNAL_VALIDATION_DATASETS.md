# Đánh Giá Độ Tin Cậy Bằng Dataset Độc Lập — AI Pipeline Your Eyes

> Báo cáo tổng hợp việc kiểm chứng độ chính xác và độ tin cậy của các thành phần AI trong pipeline Your Eyes (STT, TTS, Nhận diện ý định, 4 chức năng Gemini) bằng dataset độc lập bên ngoài — không phải dataset tự tạo dùng để lựa chọn mô hình nội bộ, mà là dữ liệu công khai từ hội nghị khoa học (ưu tiên hạng A/A* theo CORE ranking) hoặc dữ liệu phản ánh đúng môi trường triển khai thực tế: đa vùng miền, đa điều kiện thu âm, do bên thứ ba thu thập và gán nhãn độc lập.
>
> Ba thành phần (STT, Nhận diện ý định, Gemini Function 2) đã được đánh giá đầy đủ với dữ liệu thực, có số liệu cụ thể. Các thành phần còn lại đã xác định được dataset/phương pháp luận phù hợp; triển khai đầy đủ nằm trong kế hoạch tiếp theo, với lý do và điều kiện triển khai được nêu rõ ở mục tương ứng.
>
> Ký hiệu nguồn dữ liệu dùng xuyên suốt: **[EXTERNAL]** — dữ liệu công khai từ bên thứ ba · **[LOCAL]** — kết quả đo trực tiếp trên hệ thống, có thể tái lập · **[DERIVED]** — suy ra từ hai loại trên.

---

## 1. Phương pháp luận

1. Ưu tiên dataset dùng để **kiểm thử** (test), không phải để huấn luyện.
2. Ưu tiên dataset gắn với benchmark tại hội nghị hạng A/A*, hoặc dataset phản ánh đúng điều kiện triển khai thực tế của sản phẩm (đa vùng miền, đa lứa tuổi, môi trường nhiễu) khi dataset chuẩn hội nghị không sẵn có.
3. Domain tối thiểu: tiếng Việt. Riêng STT bắt buộc trải theo 3 miền giọng (Bắc/Trung/Nam) và đa dạng lứa tuổi; các chiều khác (giới tính, điều kiện thu âm, tốc độ nói) được bổ sung khi có dữ liệu phù hợp.
4. Khi một dataset đơn lẻ không phủ đủ mọi chiều đánh giá, kết quả được trình bày dưới dạng phân tầng (stratified) với số mẫu từng nhóm công khai đầy đủ — tránh việc một chỉ số trung bình duy nhất che khuất chênh lệch giữa các nhóm.
5. Với thành phần không có dataset công khai phù hợp: phương án thay thế là xây dựng bộ kiểm thử riêng theo quy trình có kiểm chứng — annotator độc lập thứ hai, báo cáo độ đồng thuận giữa các annotator (inter-annotator agreement), và công bố rõ nguồn gốc dữ liệu là tự xây dựng.
6. Dataset không thuộc domain tiếng Việt (ví dụ VizWiz, GuideDog) vẫn có giá trị như tín hiệu tổng quát hoá (generalization signal) của mô hình, được trình bày tách biệt với bằng chứng domain Việt Nam.

---

## 2. Speech-to-Text (STT)

### 2.1 Dataset đối chiếu

| Dataset | Quy mô | Đặc điểm phù hợp |
|---|---|---|
| **[VietMed](https://huggingface.co/datasets/leduckhai/VietMed)** (LREC-COLING 2024; cùng nhóm nghiên cứu công bố tại INTERSPEECH 2024, ACL 2025, EMNLP 2025) | 16 giờ có nhãn + hơn 2.000 giờ chưa nhãn | Dataset ASR tiếng Việt đầu tiên phủ đầy đủ accent 5 vùng miền và mọi nhóm bệnh theo ICD-10; metadata theo từng câu gồm accent, giới tính, điều kiện thu âm |
| **VLSP ASR** (2020–2025) | ASR-T1: 250 giờ đọc/tự nhiên · ASR-T2: bộ test nhiễu/tự phát riêng | Benchmark tham chiếu chuẩn của cộng đồng ASR tiếng Việt, có track dành riêng cho điều kiện nhiễu thực tế |
| **[Common Voice Vietnamese](https://datacollective.mozillafoundation.org/datasets/cmj8u3q0300ttnxxbzedg83wq)** (Mozilla) | 21,3 giờ / 19.214 clip | Metadata tự khai theo từng clip gồm tuổi, giới tính, accent — nguồn duy nhất tìm được có phủ đầy đủ chiều lứa tuổi; yêu cầu tài khoản Hugging Face đã xác thực để truy cập |
| **Bud500** (VietAI, 2024) | ~500 giờ, đa chủ đề, đa vùng miền | Quy mô lớn; quy trình thu thập/gán nhãn chưa được công bố chi tiết, cần xác minh mẫu trước khi dùng làm bằng chứng chính thức |

### 2.2 Kết quả đánh giá

Đã xây dựng bộ kiểm thử độc lập **168 clip thực** (17,7 phút) từ tập test của VietMed, phân tầng theo accent 5 vùng (quy về Bắc/Trung/Nam), điều kiện thu âm và giới tính, và chạy hai mô hình đang được khuyến nghị sử dụng: `sherpa-onnx-zipformer-vi-int8` (phương án chính) và `phowhisper-small-ct2-int8` kèm VAD (phương án dự phòng).

| | `sherpa-onnx-zipformer-vi-int8` | `phowhisper-small-ct2-int8` + VAD |
|---|--:|--:|
| WER — audio phòng thu sạch (đối chiếu nội bộ) | 3,79% | 3,58% |
| **WER — VietMed (đa vùng miền, thực tế)** | **21,52%** | **25,38%** |
| CER — VietMed | 18,41% | 20,16% |
| Miền Bắc (n=30) | 19,43% | 19,12% |
| Miền Trung (n=59) | **27,36%** | **37,12%** |
| Miền Nam (n=79) | 17,95% | 18,98% |
| Giọng nam | 25,68% | 30,33% |
| Giọng nữ | 18,55% | 21,84% |
| Điều kiện thuận lợi nhất (Podcast) | 11,66% | 12,54% |
| Điều kiện khó nhất (bài giảng) | 28,32% | 41,28% |

**Nhận định:** mức tăng WER tuyệt đối so với audio phòng thu sạch phản ánh cả yếu tố vùng miền lẫn dịch chuyển domain (VietMed thuộc lĩnh vực y tế, từ vựng khác VIVOS). Bằng chứng đáng tin cậy nhất về độ bền vững theo vùng miền đến từ so sánh **trong cùng một bộ dữ liệu** (cùng domain, cùng từ vựng): miền Trung cho kết quả kém hơn Bắc/Nam một cách nhất quán ở cả hai mô hình — chênh lệch 8–19 điểm phần trăm tuỳ mô hình. Đây là tín hiệu rõ ràng về độ bền vững accent cần được cải thiện trước khi triển khai diện rộng. Kết quả trên bộ dữ liệu khó này cũng cho thấy `sherpa-onnx-zipformer-vi-int8` vượt trội hơn phương án dự phòng, củng cố lựa chọn làm phương án chính.

**Phạm vi chưa đánh giá:** VietMed không có trường dữ liệu về độ tuổi người nói. Đánh giá theo lứa tuổi cần Common Voice Vietnamese — nguồn duy nhất có metadata phù hợp — yêu cầu một tài khoản Hugging Face đã xác thực để truy cập; đây là điều kiện triển khai cần chuẩn bị ở bước tiếp theo.

---

## 3. Text-to-Speech (TTS)

Đánh giá TTS đòi hỏi bộ tiêu chí khác STT: bên cạnh độ chính xác nội dung (WER khi chuyển ngược văn bản qua ASR), cần đo **độ tự nhiên** của giọng nói — một trục không thể suy ra từ bất kỳ chỉ số khách quan nào, theo đúng chuẩn đánh giá tổng hợp tiếng nói (ITU-T P.800/P.800.1): thang điểm 5 (Kém → Xuất sắc), do người nghe bản ngữ trực tiếp đánh giá.

| Dataset/Nguồn | Vai trò |
|---|---|
| **[PhoAudiobook](https://aclanthology.org/2025.acl-short.81/)** (ACL 2025) | 941 giờ audiobook tiếng Việt; quy trình đánh giá kết hợp khách quan (WER qua PhoWhisper-large, MCD, F0 RMSE) và chủ quan (MOS/SMOS do người bản ngữ chấm) — dùng làm khuôn mẫu phương pháp luận |
| **VLSP TTS 2021** | Hướng tới giọng nói tự phát tự nhiên, sát với ngữ cảnh trợ lý hơn giọng đọc sách chuẩn mực |

**Trạng thái:** đánh giá khách quan (WER roundtrip) đã được thực hiện ở giai đoạn benchmark nội bộ. Đánh giá độ tự nhiên (MOS) theo chuẩn ITU-T yêu cầu một hội đồng người nghe bản ngữ trực tiếp — đây là bước đánh giá cần tổ chức riêng ngoài quy trình kiểm thử tự động, không thể thay thế bằng mô hình dự đoán MOS (chưa có mô hình nào cho tiếng Việt được xác thực rộng rãi). Bộ câu kiểm thử từ PhoAudiobook/VLSP TTS 2021 đã sẵn sàng để sử dụng khi tổ chức hội đồng đánh giá.

Đánh giá TTS của dự án được thực hiện theo một nhánh công việc riêng (`backend/benchmark/tts/`), độc lập với phạm vi báo cáo này.

---

## 4. Nhận diện ý định (Intent Detection)

### 4.1 Dataset

**[VN-SLU](https://www.isca-archive.org/interspeech_2024/tran24b_interspeech.html)** (INTERSPEECH 2024) — 17.321 câu lệnh, 240 người nói, thu thập độc lập qua crowd-sourcing, domain trợ lý ảo/điều khiển thiết bị thông minh. Đây là dataset tiếng Việt về lệnh trợ lý ảo có quy mô lớn nhất tìm được, và — quan trọng hơn — **không do dự án tự viết**, nên phù hợp làm bộ kiểm thử độc lập cho một hệ thống được huấn luyện/thiết kế trên dữ liệu tự tạo quy mô nhỏ (78 câu train / 38 câu test).

### 4.2 Kết quả đánh giá

Đối chiếu 2.401 câu trong tập test của VN-SLU với taxonomy 7 lớp hiện tại: 2 nhãn có ngữ nghĩa tương đồng trực tiếp (`"gọi taxi"` ~ BOOK_GRAB, 145 câu; `"tra cứu đường đi"` ~ NAVIGATE, 124 câu); 26 nhãn còn lại (2.132 câu — điều khiển thiết bị, đặt lịch, tra cứu thời tiết, gợi ý phim...) là ground-truth OUT_OF_SCOPE thực sự, độc lập với dự án. Đây là quy mô kiểm thử false-positive lớn nhất có thể thực hiện được cho tới thời điểm này.

| Phương án | Tỉ lệ false-positive trên câu ngoài phạm vi | Nhãn bị nhận nhầm nhiều nhất |
|---|--:|---|
| `rule-based-normalized` (bộ định tuyến chính) | **6,6%** (141/2.132) | CALL_CONTACT (135 câu) |
| `embedding-logreg` (phương án dự phòng, mẫu n=244) | **28,7%** (70/244) | MO_TA_CANH (37), DOC_CHU (14), NAVIGATE (14) |

**Nhận định:** đây là phát hiện có giá trị vận hành trực tiếp. Kiến trúc định tuyến 2 tầng hiện tại chuyển câu sang `embedding-logreg` chính xác vào lúc tầng chính (`rule-based-normalized`) không chắc chắn — nhưng số liệu cho thấy tầng dự phòng lại có tỉ lệ nhận nhầm câu ngoài phạm vi cao gấp hơn 4 lần tầng chính. Trên một phân bố thực tế độc lập, gần 1/3 số câu điều khiển thiết bị thông minh không liên quan (ví dụ "tắt đèn phòng khách") có nguy cơ bị hệ thống kích hoạt nhầm một hành động thật (gọi điện, mô tả cảnh...). Bộ kiểm thử tự viết trước đây (38 câu) không có câu nào thuộc domain điều khiển thiết bị nên chưa từng phát hiện được rủi ro này — đây là căn cứ để xem xét lại ngưỡng chuyển tầng hoặc thay thế phương án dự phòng trước khi đưa vào sản xuất.

Trên 269 câu có ngữ nghĩa tương đồng (BOOK_GRAB/NAVIGATE, domain lệch nên chỉ mang tính tham khảo): `rule-based-normalized` đạt 14,9% (khớp từ khoá cụ thể như "Grab", không khớp cách nói "taxi" chung chung — đúng theo thiết kế), `embedding-logreg` đạt 80% (nắm bắt ngữ nghĩa tốt hơn cho cách diễn đạt khác biệt — chính cơ chế này cũng là nguyên nhân khiến tỉ lệ false-positive cao hơn).

---

## 5. Gemini Function 1 — Đọc chữ (DOC_CHU)

**[VinText](https://www3.cs.stonybrook.edu/~minhhoai/papers/vintext_CVPR21.pdf)** (CVPR 2021, Stony Brook & VinAI) — 2.000 ảnh, 56.084 text instance, scene text tiếng Việt thực tế, license AGPL-3.0. Đây là dataset khớp domain tốt nhất tìm được cho tác vụ đọc chữ, cung cấp một tập ground-truth lớn hơn đáng kể so với 11 ảnh dùng trong benchmark nội bộ hiện tại.

Bộ dữ liệu đã được xác nhận có thể truy cập công khai (qua Google Drive, dung lượng khoảng 1,05GB). Xây dựng bộ kiểm thử và chạy đánh giá đầy đủ là bước tiếp theo, chưa nằm trong phạm vi báo cáo này.

Tham chiếu bổ sung: bộ benchmark quốc tế **ICDAR Robust Reading Competition** (2013/2015/2019) — chuẩn OCR đa ngôn ngữ, không có phần tiếng Việt riêng, dùng làm tín hiệu tổng quát hoá.

---

## 6. Gemini Function 2 — Mô tả cảnh (MO_TA_CANH)

### 6.1 Dataset

**[VizWiz](https://vizwiz.org/)** — ảnh chụp thực tế bởi người khiếm thị, kèm câu hỏi và caption tham chiếu do người gán nhãn thực hiện; khoảng 28% câu hỏi không có câu trả lời rõ ràng, phản ánh đúng sự mơ hồ thực tế khi người chụp không nhìn thấy khung hình. Đây là dataset khớp use-case gần nhất tìm được cho tác vụ mô tả cảnh cho người khiếm thị, dù không thuộc domain tiếng Việt/Việt Nam.

### 6.2 Kết quả đánh giá

Đã chạy `gemini-3.5-flash-lite` với prompt tối ưu hiện đang sử dụng, trên 12 ảnh thực từ tập val của VizWiz (có caption tham chiếu công khai).

**Phát hiện thứ nhất — tỉ lệ từ chối cao trên ảnh khó nhưng không thực sự trống:** 4/12 ảnh (33%) nhận phản hồi từ chối mô tả, trong khi caption tham chiếu cho thấy nội dung hoàn toàn có thể mô tả được (ví dụ: hộp thuốc ghi rõ thành phần trên mặt bếp, hộp đĩa trên khăn hoa văn, nhãn thực phẩm). Đây là các ảnh cận cảnh, hơi mờ hoặc lệch góc — đặc trưng của ảnh chụp bởi người không nhìn thấy khung hình, một điều kiện chưa từng được kiểm thử trên bộ 9 ảnh sạch dùng trong benchmark nội bộ. Cơ chế từ chối khi không chắc chắn — vốn có giá trị chống bịa đặt nội dung — đang từ chối vượt mức cần thiết trên nhóm ảnh này.

**Phát hiện thứ hai — lệch domain giữa dữ liệu và mục tiêu prompt:** phần lớn ảnh trong VizWiz là ảnh cận vật thể/màn hình (người khiếm thị xác định "đây là vật gì"), không phải cảnh di chuyển/vật cản. Mô hình vẫn áp khuôn "đường đi an toàn, không vật cản" cho các ảnh không liên quan đến di chuyển (màn hình laptop, hộp thuốc) — cho thấy VizWiz là tín hiệu tổng quát hoá tốt cho hành vi từ chối/tránh bịa đặt, nhưng không phải benchmark khớp domain cho tác vụ mô tả cảnh an toàn di chuyển. Kết luận này có ý nghĩa trực tiếp cho việc hiệu chỉnh ngưỡng từ chối trong prompt.

---

## 7. Gemini Function 3 & 4 — Trích tham số hành động và dự phòng nhận diện ý định

Đã rà soát cả hướng benchmark geocoding/address-parsing quốc tế lẫn NER địa chỉ tiếng Việt: không có dataset công khai nào gán nhãn trích xuất tham số (tên liên hệ, địa chỉ) từ lệnh nói tiếng Việt có nhiễu ASR — nguồn tìm được chỉ ở mức xử lý thực dụng trên văn bản sạch, không phải benchmark học thuật có gán nhãn.

**Phương án thay thế:** VN-SLU (mục 4) có thể dùng làm đối chiếu một phần cho phần trích slot (cùng họ bài toán), nhưng phần cốt lõi — tên riêng tiếng Việt, cách nói địa chỉ đời thường — cần một bộ dữ liệu tự xây theo quy trình có kiểm chứng: annotator độc lập thứ hai xác nhận ground truth và báo cáo độ đồng thuận, thay vì một nguồn gán nhãn duy nhất như bộ 60 dòng hiện có. Đây là bước cần nguồn lực con người bổ sung (một người thứ hai làm annotator độc lập), nằm ngoài phạm vi một quy trình kiểm thử tự động và cần được tổ chức riêng.

---

## 8. Độ tin cậy của đánh giá tự động bằng LLM

Function 1 và 2 hiện được chấm chất lượng bởi một mô hình chấm duy nhất trong quy trình benchmark nội bộ. Đây là một giới hạn phương pháp luận đã được ghi nhận rộng rãi trong nghiên cứu: LLM/VLM dùng làm giám khảo có xu hướng thiên lệch theo vị trí câu trả lời, độ dài câu trả lời, và có thể cho kết quả không nhất quán giữa các lần chấm lặp lại. Giải pháp phù hợp là bổ sung một vòng đánh giá bởi người thật (kể cả quy mô nhỏ, có báo cáo độ đồng thuận), không phải thay bằng một mô hình chấm khác — đây là điều kiện cần tổ chức trước khi coi kết quả chấm chất lượng là kết luận cuối cùng.

---

## 9. Tổng hợp

| Thành phần | Dataset độc lập | Trạng thái | Phát hiện chính |
|---|---|---|---|
| STT | VietMed (168 clip thực) | Đã đánh giá | Chênh lệch rõ rệt theo vùng miền (Trung kém hơn Bắc/Nam 8–19 điểm); lứa tuổi cần Common Voice VN (yêu cầu tài khoản xác thực) |
| Nhận diện ý định | VN-SLU (2.401 câu thực) | Đã đánh giá | Tầng dự phòng `embedding-logreg` có tỉ lệ false-positive 28,7% trên câu ngoài phạm vi — cao hơn đáng kể tầng chính |
| Gemini F2 (mô tả cảnh) | VizWiz (12 ảnh thực) | Đã đánh giá | Tỉ lệ từ chối 33% trên ảnh khó nhưng mô tả được; lệch domain giữa VizWiz và mục tiêu prompt hazard-first |
| Gemini F1 (đọc chữ) | VinText (2.000 ảnh) | Đã xác định, chưa triển khai | Truy cập đã xác nhận; triển khai đầy đủ ở giai đoạn tiếp theo |
| TTS | PhoAudiobook + VLSP TTS 2021 | Đã xác định, chưa triển khai | Cần hội đồng người nghe bản ngữ — tổ chức riêng ngoài quy trình tự động |
| Gemini F3/F4 | Không có dataset công khai phù hợp | Phương pháp riêng | Cần annotator độc lập thứ hai — nguồn lực con người bổ sung |

**Khuyến nghị ưu tiên:** (1) xem lại ngưỡng chuyển tầng của kiến trúc định tuyến ý định 2 tầng trước khi đưa vào sản xuất, dựa trên tỉ lệ false-positive thực đo ở mục 4; (2) thu thập hoặc mở quyền truy cập Common Voice Vietnamese để đóng nốt khoảng trống đánh giá theo lứa tuổi cho STT; (3) tổ chức hội đồng đánh giá MOS cho TTS và một vòng review bởi người thật cho đầu ra Gemini F1/F2 trước khi coi các phương án hiện tại là lựa chọn cuối cùng.

---

## Nguồn tham khảo

- [VLSP 2020 ASR](https://vlsp.org.vn/vlsp2020/eval/asr) · [VLSP 2021 ASR](https://vlsp.org.vn/vlsp2021/eval/asr) · [VLSP 2022 ASR](https://vlsp.org.vn/vlsp2022/eval/asr)
- [VietMed (LREC-COLING 2024)](https://aclanthology.org/2024.lrec-main.1509/) · [VietMed dataset (Hugging Face)](https://huggingface.co/datasets/leduckhai/VietMed)
- [Bud500](https://github.com/quocanh34/Bud500)
- [Common Voice Vietnamese](https://datacollective.mozillafoundation.org/datasets/cmj8u3q0300ttnxxbzedg83wq)
- [PhoAudiobook / Zero-Shot TTS for Vietnamese (ACL 2025)](https://aclanthology.org/2025.acl-short.81/)
- [VLSP 2021 TTS Challenge](https://www.researchgate.net/publication/366505270_VLSP_2021_-_TTS_Challenge_Vietnamese_Spontaneous_Speech_Synthesis)
- [Chuẩn đánh giá MOS — ITU-T P.800](https://milvus.io/ai-quick-reference/how-is-mean-opinion-score-mos-used-in-tts-evaluation)
- [VN-SLU (INTERSPEECH 2024)](https://www.isca-archive.org/interspeech_2024/tran24b_interspeech.html)
- [PhoATIS](https://arxiv.org/abs/2104.02021) · [PhoATIS disfluency (INTERSPEECH 2022)](https://arxiv.org/abs/2209.08359)
- [VinText (CVPR 2021)](https://www3.cs.stonybrook.edu/~minhhoai/papers/vintext_CVPR21.pdf)
- [ICDAR 2019 Robust Reading Challenge](https://arxiv.org/abs/1907.00945)
- [VizWiz](https://vizwiz.org/) · [VizWiz-Caps (Hugging Face)](https://huggingface.co/datasets/lmms-lab/VizWiz-Caps)
- [GuideDog](https://arxiv.org/abs/2503.12844)
- [Geocoding address parsing benchmark](https://arxiv.org/abs/2310.14360)
- [Độ tin cậy của LLM/VLM-as-a-judge](https://www.emergentmind.com/topics/vlm-as-a-judge-protocol)
