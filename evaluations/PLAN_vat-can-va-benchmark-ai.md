# PLAN — bộ benchmark AI SeeVia (đợt 1: dựng bàn đo + đo baseline)

Ngày 2026-10-20. Đọc trước: `METRICS.md` (định nghĩa metric — làm ĐÚNG như đó), spec `SPEC_vat-can-va-benchmark-ai.md` mục 7–8.
Khung chung đã có: `bench/common/__init__.py` (`setup`, `run_meta`, `bootstrap_ci`, `paired`, `latency_summary`, `timer`, `write_result`, `sample`) — dùng, đừng viết lại.

## Luật chung cho mọi gói

- Python: `~/.venvs/seevia/bin/python`, chạy từ `SeeVia_system/evaluations/` dạng `python -m bench.<task> ...`. **Không cài/gỡ gói** (có: numpy, cv2, onnxruntime-gpu, scipy, pandas, pyarrow, sklearn, jiwer, rapidfuzz, httpx, datasets; KHÔNG có pycocotools/ultralytics → tự viết AP).
- **VH chỉ đọc** (`../visioncare-host-demo`): import code thật để đo đúng đường production; KHÔNG sửa file nào trong VH. Biến thể thuật toán để trong `bench/`.
- Mỗi script: `common.setup()` đầu tiên; tham số `--limit N` (chạy thử) và `--out`; ghi `results/<task>/...json` có `meta` (= `run_meta(cfg)`), `metrics` (mỗi số kèm CI 95 %), `latency` (`latency_summary`), `per_sample` (đủ để chấm lại không cần gọi lại model/LLM).
- **Luôn có dòng độ trễ** trong JSON và report.
- Report: `reports/<TASK>.md` sinh tự động từ JSON mới nhất (script `bench/report_<gói>.py`): dữ liệu + trích dẫn, bảng metric ± CI, dòng độ trễ p50/p90/p99, **bảng baseline công bố** (chép từ BÀI GỐC, ghi bảng/trang; không mở được bài thì ghi "chưa đối chiếu" — **không đoán số**), mục "giới hạn / không so trực tiếp được".
- Script chạy đủ: `run_<gói>.sh` (tuần tự, log `results/<gói>.log`, dòng cuối `HẾT <ok|LỖI>`, `set -euo pipefail`). **Không tự chạy bản đủ** — chỉ chạy `--limit` nhỏ để kiểm; controller sẽ chạy nền.
- Hand-back ≤ 5 dòng: file đã tạo, lệnh đã kiểm + số mẫu nhỏ ra sao, điều bất thường. Chi tiết để trong `results/<gói>_NOTES.md`.

## Gói H — vật cản (C1a, C1b, C1c)

Code VH: `live/hazard.py` (`OnnxYolo.detect`, `level_of`, `HazardTracker`, `AntiAnnoy`, `_CLASSES`), `lanes/nav_live.py` (đường nóng thật: khung nào gửi, `HAZARD_MIN_LEVEL`), `config.py` (`HAZARD_*`).
Dữ liệu: `datas/obstacle_dataset/test/{img-test,ann-test}` (VOC xml; **chỉ đọc `<object><name>`**, bỏ `<owner><name>`; bỏ tên ngoài 15 lớp: `?`, hand, head, foot…).
img-test có thể còn đang tải (đích 1.583) — dev với phần đã có; `run_hazard.sh` phải chờ đủ 1.583 ảnh (hoặc tiến trình `fetch_drive_folder.py` đã thoát) rồi mới chạy C1a.

**C1a `bench/hazard_detect.py`**
- Nguồn ảnh: tên file 12 chữ số = COCO (845 ảnh) → nhóm `coco`; còn lại `non_coco` (6 chữ số = VOC, 7–9 = tác giả tự thu). **Số chính = `non_coco`**.
- Ánh xạ VH→Obstacle: person, bicycle, car, motorbike, bus, truck, dog, stop_sign, hydrant→fire_hydrant. Lớp Obstacle ngoài COCO: reflective_cone, warning_column, spherical_roadblock, ashcan, pole, tricycle.
- Hai lượt detector: (1) **vận hành**: đúng `detect()` với `config.HAZARD_MIN_SCORE` (0,35) → precision/recall ở ngưỡng vận hành; (2) **AP**: cùng hàm nhưng tạm đặt `config.HAZARD_MIN_SCORE=0.001` (monkeypatch module config) để có đủ đường PR. AP@0,5 kiểu VOC (all-point interpolation), theo lớp + mAP trên 9 lớp ánh xạ.
- **Metric chính:** recall@IoU0,5 **không phân lớp** (bất kỳ detection nào IoU≥0,5 với hộp GT, mọi 15 lớp) cho hộp GT **trong lối đi**: tâm x ∈ [0,3; 0,7] và diện tích chuẩn hoá ≥ 0,02. Báo thêm bản phân lớp (chỉ 9 lớp ánh xạ) và recall theo từng lớp (6 lớp ngoài COCO cho thấy "ngoài khả năng").
- Hai biến thể ảnh: `orig` và `glass` (thu sao cho rộng 320 giữ tỉ lệ, JPEG q15 bằng cv2 encode/decode). Ghép đôi theo hộp GT: số hộp `orig` bắt mà `glass` trượt và ngược lại.
- Độ trễ: `detect()` mỗi ảnh (biến thể glass), warm-up 20.
- Kiểm `models/hazard/yolo11n.onnx` input tĩnh hay động; động thì chạy thêm imgsz 416/640 (chỉ đổi `imgsz`), tĩnh thì ghi "chỉ 320".

**C1b `bench/hazard_logic.py` + `bench/hazard_scenarios.py` + `bench/hazard_variants.py`**
- Sinh chuỗi hộp 8 fps từ camera pin-hole: ảnh 320×240, HFOV 66°, cao 1,6 m, nhìn thẳng (tham số đổi được). Kích thước thật: người 1,7×0,5 m; xe máy 1,1×0,8 (nhìn đầu xe); ô tô 1,5×1,8; cột 3,0×0,15; ghế đá 0,45×1,5. Hộp chiếu từ đáy (chạm đất) và đỉnh vật; cắt theo biên ảnh; vật cách < 0,5 m thì dừng kịch bản.
- Kịch bản (mỗi loại × 50 seed, nhiễu theo seed): tiến thẳng (người đi bộ 1,2 m/s + vật đứng yên; người ngược chiều tổng 2,4 m/s; xe máy 4 m/s), đi ngang qua lối (không bao giờ < 2 m trong lối), vật xa đứng yên (> 8 m), vật ở lề (lệch ngang 1,5 m), đầu lắc (±10 % kích thước, ±5 % vị trí mỗi khung), detection chập chờn (mất ngẫu nhiên 1/3 khung), score ngẫu nhiên 0,4–0,9.
- Nhãn đúng: `t_danger` = lần đầu khoảng cách < 2 m **và** lệch ngang < 0,6 m (trong lối). Kịch bản không có `t_danger` = an toàn.
- Mô phỏng đúng đường nóng: `HazardTracker.assess` → `AntiAnnoy.step` (đồng hồ giả theo khung) → coi là "bíp" khi `step` trả True với mức ≥ `HAZARD_MIN_LEVEL` (kiểm trong nav_live cách VH lọc thật; làm theo VH).
- Metric: tỉ lệ kịp thời (bíp đầu tiên mức ≥ 2 trước `t_danger` ≥ 1,5 s), lead time p50/p90, tỉ lệ trượt (không bíp trước `t_danger`), **báo nhầm/phút** trên kịch bản an toàn, số lần đổi mức gửi đi / kịch bản. CI bootstrap theo kịch bản. Bảng theo loại kịch bản.
- Độ trễ: µs/khung của `assess+step`; **trễ thuật toán** = (khung bíp − khung đầu tiên điều kiện mức thoả) × 125 ms.
- Biến thể (một biến mỗi lần, cùng interface `assess(dets)->Hazard`, cùng seed): H1 tracker IoU+khoảng cách tâm; H2 "tới gần" = hồi quy log(chiều cao hộp) trên 6 khung → TTC, mức theo TTC; H3 khoảng cách từ cạnh đáy hộp (mô hình camera) thay diện tích; H4 corridor hình thang; H5 hysteresis + mức 3 cần 2/3 khung. Báo `paired()` từng biến thể vs baseline trên metric kịp thời + báo nhầm/phút + µs/khung. **Tham khảo** `github.com/LuanLuKim/OD_module` (không bắt buộc).
- Không kiểm chứng gian lận: một test nhỏ chứng minh baseline trên kịch bản "xe máy lao thẳng" có bíp (đối chứng dương) và trên "vật xa đứng yên" không bíp (đối chứng âm).

**C1c `bench/hazard_latency.py`**: chuỗi decode JPEG q15 (bytes như kính gửi) → `detect` → `assess` → `step`, ≥ 200 khung lấy từ img-test, warm-up 20; p50/p90/p99 từng chặng và tổng.

Report: `reports/HAZARD.md`. Run: `run_hazard.sh`. Baseline cần chép: YOLO-OD (PMC 11645096), arXiv 2312.07571, bài gốc Obstacle-Dataset (Tang et al. 2021).

## Gói L — LLM nhìn ảnh (C2a VinText, C2b SROIE, C2c ViTextVQA, C4 VizWiz-VQA)

Code VH: `lanes/ocr_live.py` (`read_image`, `spoken`, `_prompt`), `models/ocr/prompts.py`, `docs/ARCHITECTURE_OCR.md` (3 chế độ: tìm đường production của chế độ **"hỏi về chữ"** — grep; nếu không có hàm riêng thì dùng `llm.stream_chat` với `prompts._COMMON` + câu hỏi, cùng tham số `read_image`, và ghi rõ), `lanes/general.py` (`messages`, `answer`, `short_first_sentence`), `models/llm/client.py`.
LLM xa (`llm.uit.edu.vn`, Gemma 4 26B), đã kiểm chạy (TTFT ~0,16 s văn bản). **Gọi tuần tự** (không song song). Lỗi mạng: thử lại 2 lần, ghi `error` vào per_sample, không dừng cả lượt. Cache đầu ra theo id mẫu (`results/<task>/cache.jsonl`) để chạy lại/chấm lại không gọi lại LLM.
Độ trễ mỗi mẫu: `ttft_ms` (mảnh đầu tiên ra khỏi `spoken()`/`answer()` = lúc TTS có thể bắt đầu) và `total_ms`.

- **C2a `bench/ocr_vintext.py`**: `datas/vintext/vietnamese/test_image/im1201..im1500.jpg` (đủ 300), nhãn `labels/gt_<n>.txt` (`x1,y1,…,x4,y4,TEXT`; bỏ `###`). Chạy `spoken(jpeg, "raw", "bench")`. Metric (METRICS.md C2a): tỉ lệ số sai được nói ra, tỉ lệ số bỏ sót, BoW precision/recall/F1 (NFC, chữ thường, giữ dấu, bỏ dấu câu), CER (GT ghép theo thứ tự trên→dưới, trái→phải), tỉ lệ từ chối. Số: regex chuỗi chữ số, bỏ `.`/`,` phân nghìn rồi so tập (multiset).
- **C2b `bench/ocr_sroie.py`**: `datas/sroie/data/test-*.parquet` (xem cột). Mỗi hoá đơn 2 câu: "Tổng số tiền phải trả trên hoá đơn này là bao nhiêu?" / "Hoá đơn này ghi ngày nào?". Chuẩn hoá: total → số thập phân (so ±0,005); date → (ngày, tháng, năm) chấp nhận nhiều định dạng; câu trả lời có nhiều số khác nhau thì lấy số được nêu là đáp án (số đầu tiên) — ghi phương pháp. Phân loại mỗi câu: đúng / **nói sai** / từ chối (sentinel hoặc "không thấy/không rõ/chụp lại"). Metric: EM từng trường, tỉ lệ nói sai, tỉ lệ từ chối.
- **C2c `bench/ocr_vitextvqa.py`**: `datas/vitextvqa/test.json` (`images`, `annotations`), ảnh `datas/vitextvqa/images/<filename>`; mẫu 300 câu `sample(seed=0)`. Metric bài gốc: EM, F1 token (chuẩn hoá chữ thường, bỏ dấu câu, NFC; max qua các đáp án); thêm "đáp án nằm trong câu trả lời".
- **C4 `bench/vqa_vizwiz.py`**: `datas/vizwiz/vqa/val.json` (4.319 câu; ảnh `datas/vizwiz/val/`), mẫu 300 `sample(seed=0)`. Câu hỏi dịch sang tiếng Việt MỘT lần bằng LLM, cache vào `results/vqa_vizwiz/questions_vi.json` (người xem lại được). Chạy `general.answer("space", câu_vi, jpeg)` (đường production). Chấm: LLM (cùng client, temperature 0, prompt chấm có ví dụ) nhận câu hỏi + câu trả lời VN + 10 đáp án EN → trả JSON `{"refused": bool, "matches": [chỉ số đáp án EN mà câu VN khớp nghĩa]}`; VQA acc = min(#đáp án trùng / 3, 1) (đáp án trùng = đếm số người trong 10 có đáp án thuộc `matches`). Câu `answerable==0`: metric chính = tỉ lệ **không từ chối** (bịa). Xuất `results/vqa_vizwiz/handcheck_50.csv` (50 mẫu seed 0: ảnh, câu, trả lời, phán quyết LLM, cột trống cho người chấm).

Report: `reports/OCR.md`, `reports/VQA.md`. Run: `run_llm.sh` (thứ tự C2b → C2a → C2c → C4). Baseline cần chép: VinText (CVPR 2021), SROIE (ICDAR 2019 Task 3 bảng xếp hạng), ViTextVQA (arXiv 2404.10652), VizWiz (CVPR 2018).

## Gói Q — chất lượng ảnh + STT (C5, C6)

- **C5 `bench/quality_vizwiz.py`**: `datas/vizwiz/quality/val.json` (7.750; `flaws` đếm 0–5 người cho FRM/BLR/DRK/BRT/OBS/OTH/NON/ROT, `unrecognizable` 0–5), ảnh `datas/vizwiz/val/`. Nhãn dương = ≥ 3/5. Gọi `image_quality.measure(bytes)` và `check(..., need_sharpness=True/False)`.
  Metric (METRICS.md C5): P/R/F1 TỐI↔DRK, CHÓI↔BRT, MỜ↔BLR (ngưỡng hiện tại `config.IMAGE_*`), **tỉ lệ chụp lại oan** cho intent không-money (chỉ luật sáng/tối) và money (thêm luật nét) — oan = bị từ chối mà ảnh không có lỗi tương ứng theo đa số; AUROC brightness (DRK, BRT) và sharpness (BLR, unrecognizable); ngưỡng tối ưu F1 chọn trên nửa A (seed 0) báo trên nửa B. Độ trễ `measure()` mỗi ảnh (CPU) p50/p90 + kích thước ảnh trung vị (VizWiz ≠ 1600×1200 — ghi chú).
- **C6 `bench/stt_vivos.py`**: `datas/vivos/vivos/test/{prompts.txt,waves/<spk>/*.wav}` (760 câu, 19 người). Tìm đường STT production trong VH (grep sherpa/zipformer; `tools/bench_stt_compare.py` có sẵn hàm chuẩn hoá + gọi Zipformer — tái dùng, cùng cấu hình decode production như beam/hotword nếu có). WER/CER tổng (jiwer) ± CI bootstrap theo câu; WER từng người nói (báo người tệ nhất); độ trễ / câu p50/p90 + RTF; ghi CPU/GPU đúng như production.

Report: `reports/QUALITY.md`, `reports/STT.md`. Run: `run_quick.sh`. Baseline: VizWiz-QualityIssues (CVPR 2020), PhoWhisper (VIVOS WER, bảng trong bài), Vietnamese Open ASR Leaderboard nếu có Zipformer.

## Bổ sung 2026-10-20 (người dùng)

- **Phạm vi: chỉ đo và ghi kết quả.** Không thử/cài cải tiến; người dùng tự xem kết quả rồi quyết. Gói H: **bỏ biến thể H1–H5**, chỉ đo baseline (kịch bản C1b + đối chứng dương/âm giữ nguyên).
- **C3 — đọc tiền VND (thêm vào gói L)** `bench/money_vnd.py`: `datas/vnd_kaggle/<mệnh giá 6 chữ số>/*.png` (000000 = không có tiền). Mẫu 30 ảnh/thư mục **trải đều theo chỉ số** (sắp theo số trong tên file) = 360.
  Chạy `general.answer("money", "Đây là tờ tiền bao nhiêu?", ảnh)` (đường production; ảnh PNG → JPEG q90 trước khi gửi nếu client cần JPEG). Trích mệnh giá từ câu trả lời (số + "nghìn/ngàn/triệu/đồng", chữ số)
  → phân loại đúng / sai / từ chối; ảnh 000000: nêu mệnh giá = bịa. Metric: tỉ lệ đọc sai, tỉ lệ bịa, accuracy từng mệnh giá, ma trận nhầm, TTFT/tổng p50/p90.
  Report: thêm mục vào `reports/MONEY.md` với câu bắt buộc ở đầu: **"Dữ liệu cộng đồng (Kaggle), không có bài báo/baseline — chỉ chứng minh SeeVia đọc được tiền VND, không chứng minh hiệu quả."** Thêm vào `run_llm.sh` (sau C2b).
