# SeeVia — Vật cản (OD) + bộ benchmark AI: thiết kế

Ngày 2026-10-20. **Trạng thái: NGƯỜI DÙNG ĐÃ DUYỆT 2026-10-20** (kể cả các mặc định ở mục 11).

> **Session sau bắt đầu ở đây.** Session 2026-10-20 chỉ tải dữ liệu + viết spec (người dùng dặn: "phần còn lại session sau chạy").
> 1. Kiểm dữ liệu: `tail datas/obstacle_fetch.log` (phải có dòng `HẾT` và `img-test 1583 file`), `grep -E '^\[' datas/download.log | tail`;
>    thiếu thì chạy lại `./fetch_obstacle_test.sh` / `bash download_datasets.sh` (đều tải tiếp được).
> 2. `superpowers:writing-plans` từ spec này → lưu `evaluations/PLAN_vat-can-va-benchmark-ai.md` → thực thi (Sonnet cho logic, Codex gpt-6-luna cho việc cơ học — memory `seevia-dung-codex-luna`).
> 3. Thứ tự mặc định (11.1): khung chung + C1a/b/c + thuật toán vật cản → C2 → C5 → C4 → C6.
Ghi chú nền (hiện trạng, số đo, đánh giá module OD của người dùng, tra cứu dữ liệu): `SeeVia_system/docs/2026-10-20-vat-can-va-benchmark-ai.md`.
VH = `SeeVia_system/visioncare-host-demo` (server kính). Thư mục này = `SeeVia_system/evaluations/`.

## 1. Vì sao

SeeVia phục vụ người khiếm thị: cảnh báo vật cản sai hoặc chậm thì người dùng va chạm; OCR đọc sai số (thuốc, tiền) thì gây hại.
Báo cáo dự án phải **chứng minh tính đúng đắn** của từng chức năng AI bằng số đo **trên dữ liệu công khai, có công bố, có baseline**,
không phải ảnh tự chụp vài tấm. Người dùng không có thời gian tự làm dữ liệu.

## 2. Người dùng đã chốt

- Không tự build dữ liệu; chỉ dùng bộ công khai có bài báo/baseline (2026-10-20).
- Vật cản phải **vừa chính xác vừa trễ thấp**; mỗi chức năng tối ưu logic + UX; kính = âm thanh, điện thoại = chữ.
- Chỉ đổi thuật toán khi **đo ra tốt hơn** (trên bàn đo, ghép đôi, p50/p90 trước/sau). Luôn GPU, chọn GPU trống. **Hỏi trước khi cài/gỡ gói** trong `~/.venvs/seevia`.
- Dữ liệu tải nền vào `SeeVia_system/evaluations/datas/` (script `evaluations/download_datasets.sh`, nguồn + sha256 ở `datas/SOURCES.md`).
- Tham khảo module OD của người dùng `github.com/LuanLuKim/OD_module` (không bảo đảm chính xác).

## 3. Mục tiêu

1. **Bộ benchmark** chạy bằng một lệnh cho mỗi task, kết quả máy đọc được (JSON/CSV) + báo cáo Markdown có trích dẫn, baseline, khoảng tin cậy 95 %, p50/p90.
2. **Vật cản**: đo detector hiện tại trên bộ công khai; cải thiện thuật toán mức/cảnh báo (H1–H6) và chọn model theo số đo; giữ đường nóng nhanh.
3. Có **chương báo cáo** dùng được ngay: mỗi task = dữ liệu + trích dẫn, baseline công bố, số SeeVia ± CI, độ trễ, giới hạn.

## 4. Không làm

Tự gán nhãn/quay dữ liệu mới; sửa firmware kính (mặc định, xem 11.4); gọi điện/app đợt 2; huấn luyện lại model khi chưa được duyệt cài gói (11.3);
đưa dữ liệu ngoài vào git; dùng dữ liệu có điều khoản "chỉ nghiên cứu" cho việc gì khác ngoài đánh giá.

## 5. Điều sẽ khiến việc này hỏng dù "chạy được"

- **Rò dữ liệu test**: Obstacle-Dataset có ảnh lấy từ **COCO/VOC/TT100K**; YOLO11n huấn luyện trên COCO → đo trên ảnh COCO là chấm model trên chính bài nó đã học.
  Bắt buộc: tách kết quả theo nguồn ảnh, **số chính báo trên tập con không thuộc COCO train** (lọc bằng tên file/so khớp hash với COCO train2017 nếu được); ghi rõ cách lọc.
- Báo số không có khoảng tin cậy, hoặc so A/B trên hai tập mẫu khác nhau.
- Lệch lớp: đếm "sai" cho lớp mà SeeVia không cảnh báo (vd. `traffic_light`) hoặc ánh xạ lớp sai giữa COCO và bộ dữ liệu.
- Trộn độ trễ GPU khác nhau / GPU đang bị job khác chiếm mà không ghi lại.
- Trích số baseline từ nguồn thứ cấp mà không đối chiếu bài gốc.
- Tối ưu làm vật cản **chậm hơn** trên đường nóng (khung → bíp) mà không ai thấy.

## 6. Dữ liệu (chi tiết tra cứu ở ghi chú nền, mục 9)

| Bộ | Task | Trạng thái tải | Ghi chú dùng |
|---|---|---|---|
| Obstacle-Dataset (Tang et al., UAIS 2021) | vật cản — phát hiện | **chỉ tải TẬP TEST** (đủ cho benchmark): `datas/obstacle_dataset/test/{img-test,ann-test,label-test}` (1.583 ảnh + nhãn VOC + nhãn YOLO) bằng `evaluations/fetch_obstacle_test.sh` (dùng `fetch_drive_folder.py`, vượt giới hạn 50 file của gdown); log `datas/obstacle_fetch.log` | 15 lớp; **lọc ảnh nguồn COCO** (mục 5); licence chưa nêu → chỉ đánh giá, trích dẫn. Train (5.066) không tải — chỉ cần nếu làm H8 |
| VinText (CVPR 2021) | OCR chữ cảnh | **ĐÃ TẢI** 2,0 GB (train_images, test_image, unseen_test_images, labels) | chỉ nghiên cứu, không phân phối lại |
| ~~MC-OCR 2021~~ | OCR hoá đơn VN | **bỏ** (2026-10-20): ảnh chỉ có trên CodaLab cần tài khoản, người dùng không có | thay bằng 2 bộ dưới |
| **SROIE** (ICDAR 2019, Huang et al.) | OCR hoá đơn — **đúng con số** (tổng tiền, ngày) | tải tự động (HF `jsdnrs/ICDAR2019-SROIE`, CC BY 4.0; 626 train / 361 test) | hoá đơn tiếng Anh/Malaysia — chấm số không phụ thuộc ngôn ngữ; baseline ICDAR 2019 công bố |
| **ViTextVQA** (arXiv 2404.10652) | OCR — **hỏi về chữ** tiếng Việt (biển hiệu, bao bì) | tải tự động (HF `xuandin/ViTextVQA`, bản đăng lại; licence không ghi → chỉ đánh giá) | có baseline trong bài gốc |
| VizWiz (VQA, Captions, QualityIssues, Grounding) | tìm đồ / mô tả / chất lượng ảnh | **ĐÃ TẢI** 6,8 GB (ảnh val + nhãn VQA/caption/quality/grounding) | ảnh do người khiếm thị chụp |
| VIVOS | STT | **ĐÃ TẢI** 3,2 GB | CC BY-NC-SA |
| PEDESTRIAN (arXiv 2512.19190) | video góc người đi | **không tải được** (DOI Zenodo chưa đăng ký, GitHub 404) — thử lại sau | chỉ nhãn phân loại, không hộp → phụ |
| VIDVIP, ORBIT, Common Voice vi, VLSP 2020, Roboflow VND | bổ sung | **thủ công** (không link / cần tài khoản / API key / rất lớn) | xem mục 11.6 |
| VN-SLU, VietMed | intent, STT | đã có từ trước | giữ |

## 7. Kiến trúc bộ benchmark

```
SeeVia_system/evaluations/
  datas/<bo>/                 dữ liệu ngoài (KHÔNG git), SOURCES.md, download.log
  download_datasets.sh        tải/tiếp tục tải
  bench/                      code benchmark (Python, chạy bằng ~/.venvs/seevia)
    common/                   đọc dữ liệu, bootstrap CI, đo trễ, ghi kết quả, thông tin máy
    hazard_detect.py          C1a
    hazard_logic.py           C1b (chuỗi hộp tổng hợp) 
    hazard_latency.py         C1c
    ocr_vintext.py, ocr_sroie.py, ocr_vitextvqa.py   C2
    quality_vizwiz.py         C5
    vqa_vizwiz.py             C4
    stt_vivos.py              C6 (bọc lại bench STT sẵn có của VH)
  results/<task>/<YYYYMMDD-HHMM>_<cấu hình>.json   kết quả thô + metadata
  reports/<TASK>.md           bảng cuối cho báo cáo (sinh từ results/)
```

Quy ước chung (bắt buộc cho mọi task):
- Import code thật của VH (`sys.path` trỏ VH) — đo **đúng đường chạy production**, không viết lại thuật toán trong benchmark.
- Mỗi lần chạy ghi: commit VH, cấu hình (model, imgsz, ngưỡng), GPU (tên, `CUDA_VISIBLE_DEVICES`, % đang dùng lúc chạy), số mẫu, seed, phiên bản dữ liệu (sha256 trong SOURCES.md).
- **CI 95 % bằng bootstrap** (1.000 lần, theo ảnh/clip). **So A/B ghép đôi** trên cùng mẫu: báo Δ, CI của Δ, số ca bất đồng (A đúng B sai / ngược lại).
- Độ trễ: warm-up 20 lượt, đo ≥ 200 lượt, báo p50/p90/p99, trên GPU trống; ghi nếu GPU dùng chung.
- Mỗi task một bảng "baseline công bố" chép **từ bài gốc** (ghi trang/bảng), cạnh số SeeVia; chỗ không so được (khác protocol) thì ghi rõ.
- Lệnh chạy: `~/.venvs/seevia/bin/python -m bench.<task> --data datas/<bo> --out results/<task>/` (+ `--limit N` để chạy nhanh khi phát triển).
- Không cài gói mới; nếu thiếu (vd. `pycocotools`) thì viết hàm tối giản hoặc hỏi người dùng.

## 8. Các bàn đo

### C1a — Vật cản: phát hiện (Obstacle-Dataset test, 1.583 ảnh)
- Chạy `live.hazard.OnnxYolo.detect` (đúng tiền xử lý letterbox + NMS của VH) trên ảnh test; ảnh được **thu về QVGA + nén JPEG q15** như kính gửi (biến thể "ảnh gốc" chạy song song để thấy mất mát do kính).
- Ánh xạ lớp COCO → 15 lớp bộ dữ liệu (bảng ánh xạ cố định trong code; lớp không có tương ứng trong COCO — `reflective_cone`, `ashcan`, `warning_column`, `spherical_roadblock`, `pole`, `tricycle` — báo riêng là **"ngoài khả năng COCO"**, chính là bằng chứng cho H6/H8).
- Metric: AP@0.5 và recall@0.5 theo lớp; **recall vật trong lối đi** (tâm hộp trong vùng corridor, diện tích ≥ ngưỡng mức 1) — thứ người dùng cần nhất; tách theo nguồn ảnh (COCO / VOC / TT100K / tự chụp).
- Baseline công bố: arXiv 2312.07571 — chép mAP từ bài gốc. (Sửa 2026-10-20: PMC 11645096 là bộ dữ liệu khác, bỏ.)
- Ma trận cấu hình: model {yolo11n hiện tại, yolo11s, yolo11m} × imgsz {320, 416, 640}. Model mới chỉ cần **xuất ONNX từ trọng số COCO công khai** — cần `ultralytics` để export: **hỏi trước** (11.3); nếu không được thì chỉ đo yolo11n.

### C1b — Vật cản: logic mức/cảnh báo (không cần dữ liệu ngoài)
- Bộ **kịch bản tổng hợp** chuỗi hộp theo thời gian (8 fps): vật tiến thẳng tới (người, xe máy, cột) với tốc độ khác nhau; vật đi ngang qua; vật đứng yên khi người đi tới;
  đầu lắc (nhiễu ±10 % kích thước, ±5 % vị trí); detection chập chờn (mất 1/3 khung); vật nhỏ ở xa không tới gần; vật ở lề.
- Nhãn đúng cho từng kịch bản sinh từ hình học (thời điểm vật vào "vùng nguy hiểm" — khoảng cách < 2 m tính từ mô hình camera pin-hole với độ cao/FOV giả định ghi rõ).
- Metric: **cảnh báo kịp thời** (bíp trước thời điểm nguy hiểm ≥ 1,5 s), **lead time**, **báo nhầm/phút** trên kịch bản không nguy hiểm, số lần nhảy mức.
- So: `HazardTracker+AntiAnnoy` hiện tại vs. từng thay đổi H1–H5 (một biến mỗi lần).
- Nói rõ trong báo cáo: đây là **kiểm chứng logic**, không thay dữ liệu thật (không có benchmark TTC người đi bộ công khai — khoảng trống đã ghi nhận).

### C1c — Vật cản: độ trễ
- (i) Server: decode JPEG q15 → detect → assess, theo model × imgsz × GPU; mốc 2026-10-20: YOLO11n/320 p50 4,90 / p90 5,26 ms (detect), 5,21 / 5,72 ms (cả chuỗi).
- (ii) Đầu-cuối có mạng: kính giả lập (`VH/tools/e2e_full.py` kịch bản `sc_alert`) gửi khung qua đường thật (local và Cloudflare), đo khung gửi → khung `hazard` nhận; báo cáo
  tách: fps × xác nhận N khung + xử lý + mạng. Mục tiêu "khung → bíp ≤ 300 ms" (spec làn C) — không tính phần phát âm trên kính (không đo được ở server).

### C2 — OCR
- **VinText test**: chạy đường đọc chữ thật (`lanes/ocr_live.read_image` → LLM, chế độ `raw` "nguyên văn" để chấm được) trên ảnh test.
  Metric: CER/WER (chuẩn hoá Unicode NFC, giữ dấu), **tỉ lệ con số sai được nói ra** (mọi chuỗi số trong đầu ra đối chiếu với ground truth — số bịa/sai/thiếu), tỉ lệ từ chối.
  Thứ tự đọc khác ground truth → chấm theo **bag-of-words** + CER sau khi khớp dòng (ghi phương pháp).
- **SROIE test (361 hoá đơn)**: chế độ "hỏi về chữ" (`tổng bao nhiêu tiền`, `ngày nào`) → so **chính xác tuyệt đối** với `total`, `date` đã chuẩn hoá;
  báo riêng tỉ lệ **nói sai số** vs **từ chối** (từ chối được coi là an toàn hơn nói sai). Baseline: bảng Task 3 ICDAR 2019 SROIE (chép từ bài gốc).
- **ViTextVQA test**: câu hỏi tiếng Việt về chữ trong ảnh → metric của bài gốc (EM/F1 theo token), so với baseline công bố.
- Độ trễ: tới mảnh chữ đầu tiên (TTFA) và toàn bộ, p50/p90. LLM ở xa (`llm.uit.edu.vn`) → ghi rõ thời điểm/tải.
- Giới hạn chi phí: mặc định chạy mẫu ngẫu nhiên cố định seed **300 ảnh VinText + 361 hoá đơn SROIE (đủ test) + 300 câu ViTextVQA** (CI ghi kèm); chạy đủ tập khi người dùng đồng ý (11.5).

### C4 — Tìm đồ / mô tả cảnh (VizWiz val)
- VizWiz-VQA val: câu hỏi có đáp án → chạy handler tương ứng của VH (VLM), chấm **VQA accuracy chuẩn VizWiz** (min(#người trả lời trùng/3, 1)) sau khi dịch đáp án SeeVia (tiếng Việt) → so khớp
  bằng từ điển/LLM chấm có kiểm tra tay 50 mẫu ❓ (xem 11.7); câu "unanswerable" → đo **tỉ lệ từ chối đúng**.
- VizWiz-Grounding: đáp án có nằm trong vùng mask không (với handler tìm đồ: hướng nói ra có khớp vị trí mask theo giờ đồng hồ ±1 giờ).
- Baseline: số trong bài VizWiz (CVPR 2018) và Grounding (2022).

### C5 — Chất lượng ảnh (VizWiz-QualityIssues val)
- Chạy `pipeline/image_quality.py` của VH → so với nhãn mờ/thiếu sáng/lệch khung/không nhận ra được: precision/recall/F1 từng loại, AUROC nếu có điểm số.
- Ý nghĩa UX: bộ kiểm này quyết định khi nào bảo người dùng "chụp lại" — báo cả tỉ lệ bắt chụp lại oan.

### C6 — STT (VIVOS test) + giữ bàn đo hiện có
- Bọc `tools/bench_stt_*` sẵn có: WER trên VIVOS test, so với số công bố PhoWhisper (VIVOS 4,67 WER large) và Vietnamese Open ASR Leaderboard (Zipformer-30M có mặt).
- Common Voice vi / VLSP cần tài khoản → khi người dùng cung cấp.

### Ngoài phạm vi đợt này
Tiền VND (chỉ có nguồn cộng đồng Roboflow cần API key — 11.6), TTS (proxy UTMOS cần cài gói — để sau).

## 9. Thuật toán vật cản — các thay đổi sẽ thử (mỗi cái phải thắng C1a/C1b, không làm chậm C1c)

| # | Thay đổi | Đo bằng |
|---|---|---|
| H1 | Tracker IoU + khoảng cách tâm (theo OD_module) thay khoá (lớp, 1/3 khung) | C1b |
| H2 | "Tới gần" bằng hồi quy tốc độ giãn **tương đối** của chiều cao hộp trên ~6 khung → **TTC** | C1b |
| H3 | Khoảng cách thô từ cạnh dưới hộp + mô hình camera (độ cao, góc nghiêng, FOV) | C1b |
| H4 | Corridor hình thang (+ bù lệch camera nếu camera không ở giữa — 11.2) | C1a (recall trong lối đi) + C1b |
| H5 | Hysteresis vào/ra mức + mức 3 cần 2/3 khung (thay 1 khung) | C1b (báo nhầm vs lead time) |
| H6 | Model/imgsz lớn hơn | C1a + C1c |
| H7 | Depth đơn mắt | **để sau** (cần cài, 11.3) |
| H8 | Fine-tune trên Obstacle-Dataset train (thêm 6 lớp ngoài COCO) | **để sau** (cần cài/huấn luyện, 11.3) — lưu ý: sau khi fine-tune trên bộ này thì C1a phải dùng **test split chưa từng thấy**, và báo thêm một bộ ngoài (VIDVIP/PEDESTRIAN) nếu có |

Thay đổi được giữ sẽ cài vào `VH/live/hazard.py` (trong tiến trình, không gọi HTTP sang service khác), kèm test đơn vị VH.

## 10. Tiêu chí chấp nhận

- `datas/SOURCES.md` có đủ nguồn, điều khoản, sha256 cho mọi bộ đã dùng.
- Mỗi task trong mục 8 (trừ "ngoài phạm vi") có: script chạy được một lệnh, file kết quả, `reports/<TASK>.md` với dữ liệu + trích dẫn, baseline công bố (ghi nguồn bảng), số SeeVia ± CI 95 %, p50/p90, giới hạn.
- C1a báo **tách nguồn COCO / ngoài COCO**.
- Mọi thay đổi thuật toán vật cản: bảng trước/sau ghép đôi trên C1a + C1b, p50/p90 C1c không tăng quá ngân sách (mặc định +5 ms server).
- VH pytest vẫn xanh sau khi cài thay đổi.
- Mỗi bước xong ghi vào nhật ký `SeeVia_system/docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md`.

## 11. Câu hỏi còn mở (mặc định của controller — người dùng sửa được)

1. Thứ tự — **mặc định:** khung chung + C1 (a→b→c) + thuật toán vật cản trước; rồi C2, C5, C4, C6.
2. Vị trí camera trên kính SeeVia (giữa hay gọng phải, lệch bao nhiêu, FOV, độ cao đeo) — **mặc định:** camera ở giữa, FOV theo OV2640 ống kính thường (~66°), độ cao mắt 1,6 m, có tham số để đổi.
3. Cài gói / tải model mới (`ultralytics` để export YOLO11s/m; depth; fine-tune) — **mặc định: không cài**, chỉ đo YOLO11n hiện có; hỏi lại khi tới H6.
4. Sửa firmware (fps/JPEG) — **mặc định: không**, chỉ server; C1c chỉ báo phần đóng góp của fps.
5. Chi phí LLM cho C2/C4 — **mặc định:** mẫu cố định 300 ảnh/bộ.
6. Dữ liệu thủ công: VIDVIP (không có link), ORBIT (lớn), Common Voice/VLSP (tài khoản), Roboflow VND (API key) — **mặc định: bỏ qua đợt này**, ghi là giới hạn.
7. Chấm câu trả lời tiếng Việt với đáp án tiếng Anh của VizWiz — **mặc định:** LLM chấm + người kiểm tay 50 mẫu, báo độ đồng thuận.
