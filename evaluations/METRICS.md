# SeeVia — Bảng metric cho các chức năng AI (vì sao chọn metric này, dataset này)

Ngày 2026-10-20. Đi kèm spec `SPEC_vat-can-va-benchmark-ai.md` (đã duyệt). Code đo: `bench/`, kết quả thô: `results/`, bảng báo cáo: `reports/`.

## 0. Nguyên tắc chọn (áp dụng cho mọi dòng bên dưới)

1. **Metric phải đo đúng cái gây hại cho người khiếm thị**, không phải cái dễ đo. Người dùng không nhìn được để tự kiểm tra:
   bỏ sót vật cản → va chạm; đọc sai con số (thuốc, tiền) → hại thật; bắt "chụp lại" oan → bực, bỏ dùng. Vì vậy mỗi chức năng có
   **một metric an toàn** (bỏ sót / nói sai số) đứng trước metric "điểm tổng" quen thuộc.
2. **Metric phải so được với bài báo gốc** → luôn kèm một metric chuẩn của dataset (AP@0.5, EM/F1, VQA accuracy, WER) để đặt số SeeVia cạnh baseline công bố.
   Chỗ protocol khác (vd. ta chấm đầu ra tiếng Việt với đáp án tiếng Anh) thì ghi rõ là **không so trực tiếp được**.
3. **Dataset: công khai, có bài báo, có baseline** (người dùng chốt 2026-10-20, không tự build). Ưu tiên tập **test**; nếu ảnh trùng dữ liệu huấn luyện của model thì **lọc** (rò dữ liệu).
4. **Mọi số đều có khoảng tin cậy 95 %** (bootstrap 1.000 lần theo ảnh/clip/câu) và **mọi so sánh A/B đều ghép đôi trên cùng mẫu** (Δ, CI của Δ, số ca bất đồng).
5. **Mọi bàn đo có dòng độ trễ** p50/p90/p99 (ms), ghi GPU nào, GPU có đang bị job khác dùng không. Độ chính xác tăng mà trễ tăng quá ngân sách thì **không nhận**.

## 1. Bảng tổng

| # | Chức năng (đường chạy thật trong VH) | Dataset (tập dùng) | Metric chính — an toàn | Metric chuẩn — so với bài báo | Metric phụ | Dòng độ trễ |
|---|---|---|---|---|---|---|
| C1a | Vật cản — phát hiện (`live.hazard.OnnxYolo.detect`, YOLO11n COCO ONNX, 320 px) | **Obstacle-Dataset** test (Tang et al., UAIS 2021), 1.583 ảnh, 15 lớp; **số chính trên 738 ảnh KHÔNG thuộc COCO** | **Recall@IoU 0,5 của vật trong lối đi** (tâm hộp ∈ giữa khung, đủ lớn để thành mức ≥1) | **AP@0,5 theo lớp** + mAP@0,5 trên các lớp COCO ánh xạ được | Precision ở ngưỡng vận hành 0,35; recall theo nguồn ảnh; độ tụt khi ảnh qua kính (QVGA + JPEG q15) | detect / ảnh p50/p90/p99 (GPU) |
| C1b | Vật cản — logic mức + cảnh báo (`HazardTracker` + `AntiAnnoy`) | **Kịch bản tổng hợp** chuỗi hộp 8 fps sinh từ hình học camera (không có benchmark công khai cho TTC người đi bộ — khoảng trống đã ghi) | **Tỉ lệ cảnh báo kịp thời** (bíp ≥ 1,5 s trước khi vật vào vùng < 2 m) | — (không có chuẩn công khai) | Lead time p50; **báo nhầm / phút** trên kịch bản an toàn; số lần nhảy mức | `assess()+step()` / khung p50/p90 **+ trễ thuật toán** (số khung chờ xác nhận × 125 ms) |
| C1c | Vật cản — độ trễ đường nóng | Ảnh Obstacle-Dataset thu QVGA q15 (như kính gửi) | **khung → quyết định bíp** p90 ≤ ngân sách (server ≤ 10 ms, đầu-cuối ≤ 300 ms) | — | Tách: decode / detect / assess; theo imgsz | p50/p90/p99 từng chặng |
| C2a | OCR đọc nguyên văn (`lanes.ocr_live.read_image`, mode `raw`, Gemma 4 26B) | **VinText** test (Nguyen et al., CVPR 2021), đủ 300 ảnh test | **Tỉ lệ con số sai được nói ra** (số bịa / đọc sai trên tổng số chuỗi số trong đầu ra) | CER, WER (NFC, giữ dấu; chấm bag-of-words vì thứ tự đọc khác GT) | Tỉ lệ số bị bỏ sót; tỉ lệ từ chối (`KHONG_CO_CHU`) | TTFT, tổng thời gian đọc p50/p90 |
| C2b | OCR hỏi về chữ — số tiền, ngày (`read_image`, câu hỏi tổng tiền/ngày) | **SROIE** test (Huang et al., ICDAR 2019), 361 hoá đơn — đủ tập | **Tỉ lệ NÓI SAI số** (khác GT, không phải từ chối) | **Exact match** `total`, `date` (đã chuẩn hoá) | Tỉ lệ từ chối (an toàn hơn nói sai) | TTFT, tổng p50/p90 |
| C2c | OCR hỏi về chữ tiếng Việt | **ViTextVQA** test (arXiv 2404.10652), mẫu 300 câu | Tỉ lệ trả lời bịa khi GT có số | **EM, F1 token** (đúng metric bài gốc) | — | TTFT, tổng p50/p90 |
| C3 | Đọc tiền VND (`lanes.general.answer("money", câu hỏi, ảnh)` → Gemma, prompt `handlers/read_money`) | **vnd_kaggle** (Kaggle cộng đồng, 11 mệnh giá + 250 ảnh không có tiền) — ⚠ **không bài báo, không baseline**: chỉ chứng minh *đọc được*, không chứng minh hiệu quả | **Tỉ lệ ĐỌC SAI mệnh giá** (nói một mệnh giá khác GT) + **tỉ lệ bịa tiền** trên ảnh không có tiền | — (không có chuẩn công bố) | Accuracy mệnh giá theo từng mệnh giá; tỉ lệ từ chối/"chụp lại"; ma trận nhầm (cặp dễ nhầm: 10k↔100k, 20k↔200k) | TTFT, tổng p50/p90 |
| C4 | Hỏi đáp / mô tả theo ảnh (`lanes.general.messages('space', câu hỏi, ảnh)` → Gemma) | **VizWiz-VQA** val (Gurari et al., CVPR 2018), mẫu 300 câu (ảnh do người khiếm thị chụp) | **Tỉ lệ bịa trên câu "unanswerable"** (không từ chối khi ảnh không trả lời được) | **VQA accuracy** = min(#người trả lời trùng / 3, 1), sau khi LLM chấm khớp câu VN với đáp án EN | Precision/recall "từ chối đúng"; độ đồng thuận LLM-chấm vs. người (50 mẫu) | TTFT, tổng p50/p90 |
| C5 | Cổng chất lượng ảnh (`pipeline.image_quality.measure/check`) | **VizWiz-QualityIssues** val (Chiu et al., CVPR 2020), 7.750 ảnh — đủ tập | **Tỉ lệ bắt chụp lại OAN** (ảnh bị từ chối mà người gán nhãn nói không có lỗi đó) | Precision/recall/F1 cho TỐI (DRK), CHÓI (BRT), MỜ (BLR); **AUROC** của điểm sáng/nét | Recall ảnh "unrecognizable" (ảnh vô dụng thật) | `measure()` / ảnh p50/p90 (CPU, ảnh gốc) |
| C6 | STT (Zipformer-vi 30M sherpa-onnx, đường VH) | **VIVOS** test (AILAB VNU-HCM), 760 câu, 19 người nói — đủ tập | WER theo người nói (người tệ nhất) | **WER** (chuẩn hoá thường + bỏ dấu câu) — so PhoWhisper | CER; RTF | / câu p50/p90 + RTF |

Ngoài phạm vi đợt này (giới hạn ghi trong báo cáo): TTS (cần người nghe/UTMOS cài gói),
VizWiz-Grounding (để vòng sau, sau khi C4 ổn), độ trễ đầu-cuối qua Cloudflare (C1c phần ii).

## 2. Giải thích từng dòng

### C1a — Vật cản: phát hiện

**Vì sao Obstacle-Dataset.** Là bộ công khai hiếm hoi được làm **riêng cho hỗ trợ người khiếm thị đi đường** (Tang et al., *Universal Access in the
Information Society*, 2021), nhãn hộp chuẩn VOC, có tập test tách sẵn và có bài sau dùng làm baseline (arXiv 2312.07571 — cần đối chiếu PDF). PMC 11645096 (YOLO-OD) KHÔNG dùng: đó là bộ dữ liệu khác (6.276 ảnh, 4 lớp).
Có 15 lớp gồm cả vật **ngoài COCO** mà vỉa hè thật có: cọc tiêu (`reflective_cone`), cột cảnh báo, chướng ngại cầu, thùng rác, cột (`pole`), xe ba bánh.
Đây đúng là điểm mù của detector COCO hiện tại → dataset cho thấy **cái ta chưa bắt được**, không chỉ cái ta làm tốt.

**Bẫy rò dữ liệu và cách xử lý.** 845/1.583 ảnh test mang tên ảnh COCO (12 chữ số; 487 có `<folder>COCO2017`). YOLO11n được huấn luyện trên COCO train2017 →
chấm trên những ảnh này là chấm bài nó đã học (số đẹp giả). Vì vậy: **số chính chỉ trên 738 ảnh không thuộc COCO** (VOC 2007 + ảnh tự chụp/TT100K của tác giả),
nhóm COCO báo riêng để thấy mức "thổi phồng". Lọc theo tên file (12 chữ số = id COCO), ghi rõ trong báo cáo.

**Vì sao Recall-trong-lối-đi là metric chính.** Chi phí lỗi bất đối xứng: bỏ sót một xe máy trước mặt = va chạm; báo nhầm một vật = một tiếng bíp thừa
(và còn được logic C1b lọc tiếp). Hơn nữa SeeVia không cảnh báo mọi vật trong ảnh — chỉ vật **ở giữa khung và đủ lớn**. Recall toàn ảnh trộn vật ở lề, ở xa
(không bao giờ thành cảnh báo) với vật cần cảnh báo → không phản ánh trải nghiệm. Vùng "lối đi" dùng đúng ngưỡng của `level_of` (tâm x ∈ [0,3; 0,7], diện tích ≥ 0,02).

**Vì sao vẫn báo AP@0,5.** Đây là metric các bài baseline dùng (mAP@0,5) → cần để đặt số cạnh bài báo. Chỉ tính trên lớp **ánh xạ được** COCO → Obstacle
(person, car, truck, bus, motorbike, bicycle, dog, stop_sign, fire_hydrant); 6 lớp ngoài COCO báo riêng là **"ngoài khả năng model"** (recall = 0 theo thiết kế) —
đó là bằng chứng định lượng cho đề xuất fine-tune (H8), không phải lỗi đo.
Lưu ý: bài baseline huấn luyện trên chính Obstacle-Dataset train, còn ta dùng model COCO **zero-shot** → không so ngang hàng; ghi rõ.

**Hai biến thể ảnh.** Ảnh gốc vs **ảnh như kính gửi** (thu về QVGA 320×240 + JPEG q15). Hiệu hai cột = mất mát do phần cứng kính, tách khỏi mất mát do model.

**Độ trễ.** `detect()` mỗi ảnh trên GPU trống (warm-up 20, ≥ 200 lượt), p50/p90/p99. Mốc 2026-10-20: 4,90 / 5,26 ms.

### C1b — Vật cản: logic mức và cảnh báo

**Vì sao dữ liệu tổng hợp.** Không có benchmark công khai cho "cảnh báo va chạm người đi bộ theo thời gian" (đã tra; PEDESTRIAN chỉ có nhãn phân loại,
không tải được). Logic `HazardTracker`/`AntiAnnoy` chỉ nhận **chuỗi hộp** → kiểm được bằng chuỗi hộp sinh từ mô hình camera pin-hole (độ cao 1,6 m, FOV ~66°,
8 fps), có **đáp án đúng tính bằng hình học** (thời điểm vật vào vùng < 2 m). Kịch bản: vật tiến thẳng (người/xe máy/cột, nhiều tốc độ), vật đi ngang, vật đứng yên
khi người đi tới, đầu lắc (±10 % kích thước, ±5 % vị trí), detection chập chờn (mất 1/3 khung), vật nhỏ ở xa, vật ở lề. Báo cáo ghi rõ: đây là **kiểm chứng logic**, không thay dữ liệu thật.

**Vì sao "cảnh báo kịp thời ≥ 1,5 s".** Người đi bộ ~1,2 m/s; cần ~1 s để nghe – hiểu – dừng/né. 1,5 s trước khi vào vùng 2 m ≈ còn ~3,8 m — đủ dừng.
Cảnh báo đúng nhưng muộn = vô dụng, nên metric chính là **kịp thời**, không phải "có bíp". Lead time p50 cho biết dư bao nhiêu.

**Vì sao báo nhầm / phút.** Bíp oan làm người dùng tắt tính năng (mất toàn bộ giá trị an toàn). Đo trên kịch bản **an toàn** (vật đi ngang ngoài lối đi, vật xa đứng yên, đầu lắc).

**Vì sao số lần nhảy mức.** Mức dao động 2↔3 làm bíp lặp và reset streak (điểm yếu #4 của rà soát). Hysteresis (H5) phải giảm số này mà không giảm "kịp thời".

**Độ trễ.** (a) thời gian tính `assess()+step()` mỗi khung (CPU, phải ≪ 1 ms); (b) **trễ thuật toán**: số khung phải chờ xác nhận × 125 ms — đây mới là phần lớn trễ cảm nhận.

### C1c — Vật cản: độ trễ đường nóng

Đo chuỗi server thật: decode JPEG q15 → `detect` → `assess`/`step`, theo imgsz {320, 416, 640} (cùng file ONNX động nếu export cho phép; không thì chỉ 320).
Ngân sách: mọi thay đổi thuật toán không được làm p90 server tăng > 5 ms (spec 10). Phần mạng/kính (fps, Cloudflare) đo sau bằng `tools/e2e_full.py`.

### C2a — OCR nguyên văn: VinText

**Vì sao VinText.** Bộ chữ cảnh **tiếng Việt có dấu** chuẩn duy nhất có bài hội nghị A* (Nguyen et al., *Dictionary-guided Scene Text Recognition*, CVPR 2021):
biển hiệu, bao bì, quảng cáo — đúng thứ người khiếm thị nhờ đọc ngoài đường. Chế độ `raw` ("nguyên văn, không dịch") để đầu ra chấm được với nhãn.

**Vì sao "con số sai được nói ra" là metric chính.** Lời hứa "không bao giờ bịa số" hiện chỉ nằm trong prompt. Sai một chữ cái thì người nghe vẫn hiểu;
sai một **con số** (giá, giờ, liều, số điện thoại) thì hiểu sai hoàn toàn. Định nghĩa: tách mọi chuỗi số trong đầu ra và trong GT (bỏ dấu `.`/`,` phân nghìn);
số trong đầu ra không có trong GT = **số sai/bịa**; số GT không có trong đầu ra = **bỏ sót**. Báo cả hai, CI theo ảnh.

**Vì sao CER và WER bag-of-words.** CER/WER là chuẩn của OCR. Nhưng nhãn VinText là từng hộp chữ không thứ tự, còn LLM đọc theo thứ tự nó chọn → WER
theo trình tự sẽ phạt oan thứ tự. Chấm **bag-of-words** (precision/recall/F1 từ, NFC, chữ thường, giữ dấu) + CER trên chuỗi đã sắp theo vị trí hộp GT (trên→dưới, trái→phải).
Bỏ hộp nhãn `###` (không đọc được). **Không so trực tiếp** với h-mean của bài gốc (bài chấm detection+recognition end-to-end) — ghi rõ.

### C2b — OCR số tiền/ngày: SROIE

**Vì sao SROIE.** Thay MC-OCR (ảnh khoá trên CodaLab). SROIE Task 3 có **đáp án đúng từng trường** `total`, `date` cho 361 hoá đơn test và bảng xếp hạng ICDAR 2019
công bố → chấm **đúng/sai tuyệt đối** con số, độc lập ngôn ngữ (hoá đơn Malaysia tiếng Anh). Hỏi bằng tiếng Việt như người dùng thật ("tổng bao nhiêu tiền?").

**Vì sao tách "nói sai" và "từ chối".** Với tiền, "không đọc được, chụp lại" an toàn hơn nhiều so với đọc sai. Một hệ từ chối 20 % nhưng nói sai 0 % tốt hơn
hệ đúng 85 % nhưng nói sai 15 %. Exact match vẫn báo để so baseline (baseline là F1 trích trường của hệ chuyên dụng — khác bản chất, ghi rõ).

### C2c — OCR hỏi đáp tiếng Việt: ViTextVQA

**Vì sao ViTextVQA.** Bộ VQA dựa trên chữ **tiếng Việt** lớn nhất có bài (arXiv 2404.10652): câu hỏi tự nhiên về biển hiệu, bao bì — đúng chế độ "hỏi về chữ".
Dùng **đúng metric bài gốc** (EM, F1 theo token) → so được baseline trong bài. Câu trả lời LLM dài hơn đáp án ngắn → chuẩn hoá (chữ thường, bỏ dấu câu) và báo thêm
"đáp án nằm trong câu trả lời" để không phạt oan văn nói.

### C3 — Đọc tiền VND: dữ liệu cộng đồng Kaggle (chỉ chứng minh khả năng)

**Vì sao bộ này và vì sao nó KHÔNG phải bằng chứng hiệu quả.** Không tồn tại bộ tiền VND công khai có bài báo + baseline (đã tra 2026-10-20:
BankNote-Net của Microsoft không có VND và chỉ công bố embedding, không có ảnh). Người dùng chốt: dùng bộ Kaggle `nguyentrongdai/vietnamese-currency`
để **chứng minh SeeVia đọc được tiền VND** — không dùng số này để khẳng định độ chính xác ngoài đời. Lý do số không tổng quát được: một người, một phông,
webcam 192×144 (thấp hơn nhiều ảnh 1600 px của kính), khung video gần trùng nhau, licence không rõ. Báo cáo phải ghi đúng câu: *"dữ liệu cộng đồng, không có baseline"*.

**Mẫu.** 30 ảnh/mệnh giá × 11 + 30 ảnh không tiền = 360, lấy **trải đều theo chỉ số khung** (không ngẫu nhiên) để giảm khung gần trùng; CI bootstrap theo ảnh vì thế vẫn lạc quan — ghi rõ.

**Vì sao "đọc sai mệnh giá" là metric chính.** Đọc nhầm 500.000 thành 20.000 là mất tiền thật; nói "không rõ, chụp lại" thì chỉ phiền. Nên tách 3 loại:
đúng / **sai** / từ chối. Ảnh không có tiền: mọi câu nêu mệnh giá = **bịa**. Ma trận nhầm cho thấy cặp màu giống nhau (10k↔100k xanh lá-lục, 20k↔200k) có bị lẫn không.

### C4 — Hỏi đáp theo ảnh: VizWiz-VQA

**Vì sao VizWiz.** Ảnh **do chính người khiếm thị chụp** (mờ, lệch, thiếu sáng) kèm câu hỏi thật của họ — không bộ nào gần điều kiện SeeVia hơn (Gurari et al., CVPR 2018).
32 % câu ở tập val là "unanswerable" (1.385/4.319) (ảnh không đủ thông tin) → đo được hành vi quan trọng nhất của trợ lý: **biết nói "tôi không thấy rõ"** thay vì bịa.

**Vì sao metric chính là "bịa trên câu unanswerable".** Prompt SeeVia dặn "tuyệt đối không đoán bừa"; đây là chỗ kiểm lời dặn đó. Câu bịa tự tin trên ảnh vô dụng
là lỗi nguy hiểm (người dùng hành động theo).

**Vì sao VQA accuracy qua LLM chấm.** Metric chuẩn VizWiz là min(#người trùng/3, 1) trên 10 đáp án tiếng Anh. SeeVia trả lời tiếng Việt văn nói →
dùng LLM chấm "câu trả lời VN khớp đáp án EN nào" rồi áp công thức; **kiểm tay 50 mẫu** và báo độ đồng thuận (spec 11.7). Không so ngang baseline bài gốc (khác protocol), chỉ tham chiếu.

### C5 — Cổng chất lượng ảnh: VizWiz-QualityIssues

**Vì sao bộ này.** Nhãn chất lượng (tối, chói, mờ, lệch khung, che, xoay, "không nhận ra được") do 5 người gán **trên ảnh người khiếm thị chụp**
(Chiu et al., CVPR 2020) — đúng câu hỏi "khi nào bảo người dùng chụp lại". Dùng đủ 7.750 ảnh val (không tốn LLM).

**Định nghĩa nhãn.** Một lỗi là "có" khi **≥ 3/5** người gán (đa số). So: `check()` trả TỐI ↔ DRK, CHÓI ↔ BRT, MỜ ↔ BLR (chỉ `money` dùng luật mờ).

**Vì sao "chụp lại oan" là metric chính.** Cổng này chỉ được phép chặn outlier cực đoan (docstring module): chặn oan một câu hỏi hợp lệ = người dùng phải chụp lại
không lý do. Báo kèm **AUROC** của điểm sáng/nét để biết có ngưỡng nào tốt hơn không (chọn ngưỡng trên nửa A, kiểm trên nửa B để khỏi tự khớp).

**Độ trễ.** `measure()` ở độ phân giải gốc (docstring nói ~0,1 s ở 1600×1200) — đo thật.

### C6 — STT: VIVOS

**Vì sao VIVOS.** Tập test STT tiếng Việt công khai chuẩn (AILAB VNU-HCM), được PhoWhisper và Vietnamese Open ASR Leaderboard báo WER → so được trực tiếp
(cùng tập, cùng metric). VietMed/FLEURS đã có số từ trước (giữ). Metric phụ "WER người nói tệ nhất" vì trung bình che những giọng hệ thống nghe kém.

## 3. Chuẩn thống kê chung

| Hạng mục | Quy tắc |
|---|---|
| Khoảng tin cậy | Bootstrap 1.000 lần theo đơn vị mẫu (ảnh / câu / clip / kịch bản), seed 0, CI 95 % percentile |
| So A/B | Ghép đôi trên cùng mẫu; báo Δ, CI(Δ), số ca A-đúng-B-sai / ngược lại; chỉ đổi **một** biến mỗi lần |
| Mẫu LLM | VinText test 300 (đủ tập), SROIE 361 (đủ), 360 ảnh tiền VND (trải đều); cố định seed 0: 300 ViTextVQA, 300 VizWiz-VQA; LLM gọi **tuần tự** để độ trễ không bị nhiễu bởi chính bench |
| Độ trễ | Warm-up ≥ 20 (model cục bộ), đo ≥ 200 lượt; p50/p90/p99; ghi GPU, `CUDA_VISIBLE_DEVICES`, util lúc đầu/cuối; LLM xa ghi giờ đo |
| Metadata | commit VH, nhánh, dirty, cấu hình, số mẫu, seed — trong mỗi `results/*.json` |
