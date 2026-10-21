# Vật cản (OD) + bộ benchmark AI — ghi chú bàn giao (NHÁP, đang brainstorm)

Ngày 2026-10-20. **Chưa phải spec đã duyệt.** Session sau: đọc file này (nhất là mục 9 — dữ liệu công khai đã tra), tiếp tục brainstorming từ mục 7 (câu hỏi 2–6 còn treo), rồi mới viết spec/plan.
VH = `SeeVia_system/visioncare-host-demo` (server kính), AB = `SeeVia_system/app-demo-backend`.
Tài liệu liên quan: `SeeVia_system/docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md` (mục B1 vật cản, B2 OCR, C benchmark — đề xuất ban đầu).

## 1. Người dùng muốn gì (lời người dùng, 2026-10-20)

- **Tạm gác spec đợt 2 app (gọi điện)**; làm trước những thứ không liên quan gọi điện.
- "Rà soát lại thuật toán vật cản, OD để đảm bảo **cả độ chính xác và latency phải thấp**."
- "Thiết kế **1 bộ benchmark đo đạc cho những chức năng AI** này" (vật cản, OCR, và các task AI chưa có benchmark).
- Mỗi chức năng: tối ưu logic + bảo đảm UX. Nhắc lại nguyên tắc đã chốt: **kính = âm thanh** (người khiếm thị), điện thoại = chữ.
- Người dùng gửi module OD tự làm để tham khảo/thử: `https://github.com/LuanLuKim/OD_module.git` — "có cả công thức tính toán độ sâu, có thể thử nghiệm nếu muốn,
  không đảm bảo chính xác và tốt". Bản clone tạm (chưa chạy code nào): scratchpad session 2026-10-20 — session sau clone lại nếu cần.

Ràng buộc chung đã chốt từ trước (memory): chỉ đổi khi **đo ra tốt hơn** (p50/p90 trước/sau); luôn GPU, chọn GPU trống (`CUDA_VISIBLE_DEVICES`), không lùi CPU;
**hỏi trước khi cài/gỡ gói** trong `~/.venvs/seevia`; một biến mỗi thí nghiệm, so ghép đôi trên cùng mẫu.

## 2. Hiện trạng vật cản trong VH (đã đọc code)

- `VH/live/hazard.py`, `VH/lanes/nav_live.py`. YOLO11n COCO ONNX (`models/hazard/yolo11n.onnx`), `HAZARD_IMGSZ=320`, `HAZARD_MIN_SCORE=0.35`, 14 lớp COCO
  (người, xe đạp/ô tô/xe máy/bus/tải, chó, đèn giao thông, trụ nước, biển stop, đồng hồ đỗ xe, ghế đá, ghế, chậu cây).
- Kính gửi QVGA JPEG q15, ~8 fps; server chỉ xử lý **khung mới nhất** (mailbox).
- Mức 0–3 theo luật: diện tích hộp + tâm trong 0,3–0,7 chiều ngang + "đang tới gần" = diện tích tăng >15 % so với khung trước, khoá theo (lớp, 1/3 khung).
- `AntiAnnoy`: mức phải giữ **2 khung liên tiếp** mới gửi (mức 3 gửi ngay 1 khung), nhắc lại mỗi 2 s, mức 1 tối đa 1 lần/5 s; chỉ gửi kính mức ≥ `HAZARD_MIN_LEVEL=2`.
- Cảnh báo chen trước mọi tiếng nói khác (`_HazardClock`, im 1,5 s sau mức ≥ 2). Kính phát bíp/câu từ flash (không TTS).
- Dữ liệu trong repo: **chỉ 1 ảnh** `VH/tools/assets/hazard_level2.jpg`. Không có video, không có nhãn, không có benchmark vật cản nào.

### Số đo 2026-10-20 (GPU 0, RTX 2080 Ti, onnxruntime CUDA, 200 lượt, ảnh QVGA)

| Đoạn | p50 | p90 |
|---|---|---|
| `det.detect` (YOLO11n, 320) | 4,90 ms | 5,26 ms |
| giải mã JPEG q15 + detect + `assess` | 5,21 ms | 5,72 ms |

**Kết luận quan trọng:** tính toán server ~5 ms là phần nhỏ. Độ trễ người dùng cảm nhận (lúc vật xuất hiện → nghe bíp) chủ yếu là:
chu kỳ khung ~125 ms (8 fps) + xác nhận 2 khung (+~125 ms) + chụp/nén/gửi trên ESP32 + mạng (Cloudflare) + kính phát âm.
⇒ (a) Có **ngân sách** dùng model mạnh hơn (YOLO11s/m ~10–15 ms, hoặc thêm depth) mà gần như không tăng trễ cảm nhận;
(b) muốn **nhanh hơn** thì phải xử lý ở tần số khung / luật xác nhận / truyền tải, không phải ở model. Chưa đo đầu-cuối thật — cần bàn đo (mục 5, C1c).

### Điểm yếu đã thấy (từ rà soát trước)

1. Thiếu vật cản vỉa hè VN: bậc thềm, mép vỉa hè, ổ gà/hố ga, cột điện/biển báo, xe máy đậu, gánh hàng, bàn ghế quán, **vật ngang đầu** (mái hiên, cành cây).
2. Diện tích hộp ≠ khoảng cách (người xa to vs cột mảnh gần).
3. "Tới gần" so 2 khung liền nhau → nhiễu do lắc đầu; mất lịch sử khi vật qua ranh 1/3 khung.
4. Mức 3 gửi chỉ với 1 khung → báo nhầm; streak đòi đúng cùng mức nên dao động 2↔3 reset.
5. Hướng chỉ trái/giữa/phải, không bù camera lệch.

## 3. Module OD của người dùng (`LuanLuKim/OD_module`, commit `f974afc`) — đã đọc, chưa chạy

FastAPI riêng (cổng 8002), ~4,8k dòng. Pipeline: FrameFilter → YOLO11n ONNX (imgsz 640, conf 0,25) → tracker → Corridor/Proximity/Approach → RiskScorer → state machine + debounce.

| Thành phần | Cách làm | Nhận xét / có nên lấy |
|---|---|---|
| **Tracker** (`tracking/`) | IoU + khoảng cách tâm (chuẩn hoá theo đường chéo), ghép tham lam theo chi phí `(1−IoU)+dist`; track xác nhận sau ≥2 khung; lịch sử 10 khung | **Lấy** — sửa đúng điểm yếu 3. Nâng cấp sau: Kalman + Hungarian (SORT) nếu đo ra cần |
| **Approach** (`risk/approach.py`) | độ dốc hồi quy tuyến tính của tỉ lệ diện tích trên N khung | **Lấy ý tưởng** (bền hơn so 2 khung). Nhưng độ dốc tính theo *tỉ lệ khung* nên vật nhỏ ở xa không bao giờ "tới gần" → nên chuẩn hoá theo kích thước chính vật (tốc độ giãn tương đối) và tính **TTC** |
| **Proximity** = "công thức độ sâu" (`risk/proximity.py`) | `0,6·√(diện tích) + 0,4·(cạnh dưới hộp / chiều cao khung)`; tài liệu ghi rõ "không cố đo khoảng cách tuyệt đối theo mét" | Là heuristic gần/xa, **không phải độ sâu mét**. Phần "cạnh dưới hộp" đúng hướng (điểm yếu 2); có thể thay bằng hình học mặt đất có hiệu chỉnh (độ cao kính + góc nghiêng) để ra mét thô |
| **Corridor** (`risk/corridor.py`) | hình thang lối đi, **bù thị sai camera gắn bên phải gọng** (7–14 cm, FOV 120°): gần thì lệch trái | **Lấy** — hợp phần cứng thật hơn dải 0,3–0,7 cố định của VH. Cần xác nhận vị trí camera thật trên kính SeeVia ❓ |
| **RiskScorer** | tổng có trọng số 0,35 corridor + 0,40 proximity + 0,25 approach, luật ép HIGH (trong lối đi + gần; tới nhanh), **trễ (hysteresis)** vào 0,70 / ra 0,55 | **Lấy hysteresis** (điểm yếu 4). Trọng số chưa hiệu chỉnh trên dữ liệu — phải tune bằng bàn đo C1 |
| **Direction** | trục đi lệch 0,45 (do camera bên phải), ngưỡng ±0,13 | Lấy cùng corridor |
| **FrameFilter** | bỏ qua YOLO nếu ảnh thu nhỏ 64×48 ít thay đổi (MAD), ngưỡng theo mức (HIGH thì không bỏ) | **Không cần**: detect chỉ 5 ms trên GPU; bỏ khung có rủi ro bỏ sót vật tĩnh khi người đi chậm |
| **Predictor (TTC)** | stub, trả `None` | Đây là phần nên làm (xem 4) |
| Lớp vật | 24 lớp COCO, có đồ trong nhà (bàn, giường, tủ lạnh, laptop…) | Hữu ích trong nhà; vẫn thiếu lớp vỉa hè (điểm yếu 1) |
| `scripts/benchmark_latency.py` | đo standalone / live HTTP / webcam HUD | Tham khảo cho bàn đo C1c |

Lưu ý tích hợp: VH chạy detector trong tiến trình (không HTTP) để giữ trễ thấp — **không** nên gọi module này như service riêng qua HTTP; lấy thuật toán, cài vào `VH/live/hazard.py`.

## 4. Đề xuất cho thuật toán vật cản (chưa chốt; mỗi bước phải thắng trên bàn đo C1 mới giữ)

| # | Ý tưởng | Nguồn | Chi phí | Kỳ vọng |
|---|---|---|---|---|
| H1 | Tracker IoU+tâm (từ OD_module) thay khoá (lớp, 1/3 khung) | OD_module | thấp | "tới gần" ổn định |
| H2 | **TTC** từ tốc độ giãn tương đối của chiều cao hộp (hồi quy trên ~6 khung): `TTC ≈ h / (dh/dt)` | mới | thấp | mức theo "còn mấy giây tới va chạm" |
| H3 | Khoảng cách thô từ cạnh dưới hộp + hiệu chỉnh độ cao/góc kính | OD_module (mở rộng) | thấp | phân biệt xa-to/gần-nhỏ |
| H4 | Corridor hình thang + bù thị sai camera | OD_module | thấp | giảm báo nhầm vật bên lề |
| H5 | Hysteresis + mức cao cần 2/3 khung gần nhất (thay "1 khung" cho mức 3) | OD_module + mới | thấp | bớt bíp nhầm; +≤125 ms ❓ đánh đổi |
| H6 | Model lớn hơn (YOLO11s/m) hoặc imgsz 416/480 | mới | đo được ngay (đã có ngân sách ~10 ms) | recall vật nhỏ/xa |
| H7 | Độ sâu đơn mắt (Depth Anything V2-Small ONNX) song song: "trong lối đi có gì gần hơn X m" bất kể lớp | mới | trung bình, **cần cài/tải model → hỏi trước** | bắt vật ngoài COCO (cột, tường kính) |
| H8 | Fine-tune YOLO trên dữ liệu vỉa hè VN (thêm lớp cột, bậc, hố ga, vật ngang đầu, xe đậu) | mới | cao, cần nhãn | đúng domain nhất |
| L1 | Giảm trễ đầu-cuối: tăng fps kính / giảm chất lượng JPEG / gửi bíp ngay khi mức 3 có TTC < ngưỡng | mới | cần đụng firmware ❓ | trễ cảm nhận thấp hơn |

## 5. Bộ benchmark AI — thiết kế đề xuất (chưa chốt)

Nguyên tắc: mỗi task một **tập cố định có phiên bản** + **một lệnh chạy** + **CSV/JSON kết quả** + **khoảng tin cậy bootstrap** + **độ trễ p50/p90** cạnh độ chính xác;
so A/B **ghép đôi trên cùng mẫu**, đếm ca bất đồng; ghi kết quả vào `VH/docs/benchmarks/<TASK>.md`. Đặt code ở `VH/tools/bench/` (đã có `tools/benchmarks/latency.py`, `voice.py`,
`bench_stt_*`, `eval_intent.py` — dùng lại khung).

| # | Task | Hiện có | Bàn đo | Metric chính |
|---|---|---|---|---|
| C1a | Vật cản — khung | 1 ảnh | ảnh có hộp nhãn (lớp liên quan + lớp vỉa hè) | recall/precision theo lớp ở IoU 0,5, recall vật **trong lối đi** |
| C1b | Vật cản — sự kiện trên video | không | video đi bộ có nhãn thời điểm "nguy hiểm" (bắt đầu/kết thúc, hướng) | **recall cảnh báo kịp thời** (báo trước va chạm ≥ 1,5 s), **báo nhầm/phút**, lead time p50 |
| C1c | Vật cản — độ trễ | số đo ad-hoc ở mục 2 | (i) server: decode→level p50/p90 theo model/imgsz; (ii) đầu-cuối: phát video vào kính giả lập (`tools/e2e_full.py` có `sc_alert`) qua Cloudflare, đo khung gửi → khung `hazard` nhận | p50/p90 ms |
| C2 | OCR | 11 ảnh nội bộ | VinText test (~500 ảnh, AGPL — chỉ đánh giá) + bộ đời thường VN tự chụp bằng kính (HSD, thuốc, hoá đơn, số phòng, màn LED) | CER/WER; **tỉ lệ con số sai được nói ra** (quan trọng nhất); từ chối đúng/sai; TTFA |
| C3 | Đọc tiền | không | 12 mệnh giá × mặt × điều kiện (tối, nghiêng, gấp, nhiều tờ) | accuracy mệnh giá; "chụp lại" vs đọc sai |
| C4 | Tìm đồ / mô tả không gian | VizWiz 12 ảnh, LLM tự chấm | ảnh có nhãn vật + hướng (giờ) + khoảng cách thô; chấm bằng luật | đúng hướng ±1 giờ, đúng vật, tỉ lệ bịa vật |
| C5 | STT, intent, độ trễ giọng nói | **đã có** (`docs/benchmarks/*`, `bench_stt_*`, `eval_intent.py`) | giữ, chỉ gom vào cùng khung báo cáo | — |
| C6 | TTS | không | để sau (cần người nghe, MOS) | — |

Dữ liệu công khai ứng viên cho C1 (cần tra lại tính khả dụng/licence trước khi dùng): bộ vỉa hè cho người khiếm thị (ví dụ SideGuide/AI Hub Hàn Quốc),
các bộ "obstacle detection for visually impaired" trên Roboflow Universe/Kaggle, video góc nhìn người đi bộ (Ego4D — nặng, licence chặt). Chưa kiểm cái nào.

## 6. Việc có thể làm ngay không cần dữ liệu mới (ứng viên bước đầu)

1. Gói số đo C1c(i) thành script lặp lại được (model × imgsz × provider), ghi `VH/docs/benchmarks/HAZARD_LATENCY.md`.
2. Viết bộ test luật mức (đơn vị) cho tracker/TTC/hysteresis bằng chuỗi hộp tổng hợp (vật tiến lại đều, đầu lắc, vật đi ngang, vật đứng yên khi người đi tới).
3. Khung chạy chung `VH/tools/bench/` + định dạng kết quả, để C2–C4 cắm vào.

## 7. Câu hỏi đang treo (hỏi người dùng ở session sau, từng câu một)

1. ~~Dữ liệu~~ — **ĐÃ TRẢ LỜI 2026-10-20: KHÔNG tự build dữ liệu** (không đủ thời gian). Chỉ dùng **bộ dữ liệu/benchmark công khai, có công bố**,
   vì báo cáo cần **chứng minh tính đúng đắn** để thuyết phục. Xem mục 9.
2. Vị trí camera thật trên kính SeeVia (giữa hay gọng phải, lệch bao nhiêu cm, FOV) — để dùng corridor bù thị sai của OD_module.
3. Có cho cài/tải model độ sâu (H7) và huấn luyện lại YOLO (H8) không (cần GPU + có thể cài gói)?
4. Có được đổi firmware kính (fps, chất lượng JPEG) cho L1 không, hay chỉ sửa server?
5. Mục tiêu số cụ thể: trễ đầu-cuối tối đa (ví dụ ≤ 300 ms như spec làn C), báo nhầm tối đa mỗi phút, lead time tối thiểu.
6. Thứ tự: vật cản trước rồi mới bộ benchmark chung, hay dựng khung benchmark trước (đề xuất: khung + C1 trước, C2–C4 sau).

## 8. Không làm trong hướng này

Gọi điện/đợt 2 app (đã duyệt spec, gác lại: `AB/docs/superpowers/specs/2026-10-20-app-dot2-design.md`). Không triển khai server thật.

## 9. Dữ liệu + benchmark công khai cho từng task (tra web 2026-10-20)

Yêu cầu người dùng: không tự làm dữ liệu; mọi số trong báo cáo phải đo trên **bộ công khai, có bài báo bình duyệt hoặc tác giả uy tín, có baseline đã công bố**
để so sánh — đó là "bằng chứng đúng đắn". Số liệu kích thước dưới đây lấy từ trang bài báo/README; **phải kiểm lại khi tải** (một số nguồn thứ cấp lệch nhau).

| Task SeeVia | Bộ dữ liệu | Nội dung | Licence / truy cập | Dùng để chứng minh | Ghi chú |
|---|---|---|---|---|---|
| **Vật cản — phát hiện (C1a)** | **Obstacle-Dataset (OD)** — Tang et al., *Universal Access in the Information Society* (Springer 2021), GitHub `TW0521/Obstacle-Dataset` | 7.915 ảnh vỉa hè dành cho người khiếm thị, 48.843 hộp, 15 lớp (người, xe đạp, xe máy, ô tô, bus, tải, xe ba gác, chó, trụ nước, biển stop, cột, cột cảnh báo, thùng rác, cọc nón phản quang, cục chặn cầu) — chia sẵn 5.066/1.266/1.583 | chưa kiểm licence ❓ | recall/precision/mAP theo lớp trên **tập test có sẵn**; so với baseline **YOLO-OD** (PMC 11645096) và "Investigating YOLO Models Towards Outdoor Obstacle Detection For VI" (arXiv 2312.07571) đã công bố trên cùng bộ | bối cảnh đường phố châu Á (xe máy, xe ba gác) — gần VN nhất tìm được |
| Vật cản — video góc nhìn người đi bộ (C1b) | **PEDESTRIAN** — Thoma, Theodosiou et al. (CYENS, Síp), arXiv 2512.19190, Zenodo DOI 10.5281/zenodo.10907945 | 340 video quay bằng điện thoại từ góc nhìn người đi bộ, 29 loại vật cản vỉa hè (nguồn thứ cấp: 82.120 khung) | bài báo CC BY 4.0; licence dữ liệu chưa kiểm ❓ (link GitHub `CYENS/PEDESTRIAN` trả 404 lúc tra) | đánh giá theo khung trên video thật góc nhìn người đi; dựng chỉ số **mức sự kiện** (lần đầu cảnh báo trên mỗi video có vật cản) | KHÔNG có nhãn thời điểm va chạm/TTC |
| Vật cản — bổ sung lớp vỉa hè | VIDVIP (Baba, *J. Robotics & Mechatronics* 2021) — 32.036 ảnh, 39 lớp (gạch dẫn đường, nút đèn…); SafeWalkBD / "Outdoor Detection" trên Roboflow (cột, ổ gà, bậc thang) | | VIDVIP: chưa thấy link tải ❓; Roboflow: licence từng dự án | phủ lớp cột/bậc/ổ gà mà COCO không có | Roboflow là nguồn cộng đồng — chỉ dùng phụ, không làm bằng chứng chính |
| Vật cản — TTC / cảnh báo sớm | **Không có** benchmark TTC cho người đi bộ đeo camera (khoảng trống thật: chỉ có dashcam — BADAS, Nexar — và robot trong hành lang, arXiv 1903.09102) | | | | Báo cáo nên **nói thẳng khoảng trống này**; đo luật TTC bằng chuỗi hộp tổng hợp (test đơn vị) + đếm cảnh báo trên PEDESTRIAN |
| **Vật cản — độ trễ** | không cần dữ liệu ngoài | | | p50/p90 decode→level theo model/imgsz/GPU; đầu-cuối qua kính giả lập | đã có mốc: YOLO11n 320 p50 4,9 ms |
| **OCR chữ cảnh (C2)** | **VinText** — Nguyen et al., *CVPR 2021* (VinAI), GitHub `VinAIResearch/dict-guided` | ~2.000 ảnh, ~56.000 vùng chữ tiếng Việt có dấu | **chỉ nghiên cứu/giáo dục, không phân phối lại, phải trích dẫn** (điều khoản riêng; tài liệu cũ ghi AGPL — sai, sửa theo README) | CER/WER, **tỉ lệ con số sai**; so với baseline dict-guided trong bài CVPR | chuẩn mực nhất cho tiếng Việt |
| OCR hoá đơn | **MC-OCR 2021** (RIVF 2021 challenge) | 2.436 hoá đơn VN chụp bằng điện thoại; nhiệm vụ chất lượng ảnh + trích trường (tổng tiền, ngày…) | kiểm trên trang challenge ❓ | đúng trường "tổng tiền", "ngày" — đúng yêu cầu "không bịa số" | |
| OCR — hỏi về chữ | ViOCRVQA (>28.000 ảnh, QA), ViTextVQA | | ❓ | chế độ "Hỏi về chữ" (HSD, tổng tiền) | |
| **Tiền VND (C3)** | **Không có bộ VND có bài báo.** BankNote-Net (Microsoft, CDLA-Permissive-2.0) có 17 tiền tệ nhưng **không có VND**, và chỉ phát hành embedding. Có vài bộ cộng đồng Roboflow: "VND" (kimthai, 9 lớp 100đ–500k, CC BY 4.0), "Vietnamese Currency" (~2,19k ảnh), "currency recoginite VietNamdong" (~1,3k ảnh) | | CC BY 4.0 / từng dự án | accuracy mệnh giá | **Điểm yếu cho báo cáo**: nguồn cộng đồng, cần tự kiểm nhãn một mẫu nhỏ và nói rõ giới hạn |
| **Tìm đồ / mô tả cảnh / hỏi đáp ảnh (C4)** | **VizWiz-VQA** (Gurari et al., CVPR 2018, ~31k câu hỏi thật của người mù); **VizWiz-VQA-Grounding** (2022, vùng chứa đáp án); **VizWiz-Captions**; **ORBIT** (Massiceti et al., ICCV 2021, 3.822 video/486 đồ vật do người mù quay) | ảnh **do chính người khiếm thị chụp** | công khai cho nghiên cứu (vizwiz.org; ORBIT: City Univ. London figshare) | đúng vật / đúng vùng; hành vi từ chối khi ảnh không trả lời được (~28 % câu không trả lời được) | khớp domain người dùng nhất; tiếng Anh → chấm theo nội dung, không theo câu chữ |
| **Chất lượng ảnh (pipeline `image_quality`)** | **VizWiz-QualityIssues** (Chiu et al., CVPR 2020) | ~39k ảnh người mù chụp, nhãn mờ/thiếu sáng/lệch khung/không nhận ra được | vizwiz.org | đánh giá bộ kiểm chất lượng ảnh trước khi gửi VLM/OCR | VH đã có `pipeline/image_quality.py` mà chưa có benchmark |
| **STT** (đã có một phần) | VIVOS, Common Voice vi, VLSP 2020 T1/T2 (PhoWhisper báo WER 4,67 / 8,14 / 13,75 / 26,68); **Vietnamese Open ASR Leaderboard** (HF Space, 9 tập); VietMed (đã chạy) | | công khai | so trực tiếp với PhoWhisper và leaderboard (Zipformer-30M có trên leaderboard) | bổ sung vào bàn đo STT hiện có |
| **Intent** (đã có) | VN-SLU (2.401 câu, đã chạy) | | | | giữ |
| TTS | không có bộ chuẩn chấm tự động tiếng Việt; dùng **chỉ số tự động** (UTMOS dự đoán MOS + CER khi cho STT đọc lại) trên câu của PhoAudiobook/VLSP TTS | | | | proxy, nêu rõ không thay MOS người nghe |

**Cách trình bày "đúng đắn" trong báo cáo (đề xuất):** mỗi task = (1) bộ công khai + trích dẫn, (2) baseline công bố trên cùng bộ, (3) số của SeeVia
kèm khoảng tin cậy 95 % (bootstrap), (4) độ trễ p50/p90 trên phần cứng ghi rõ, (5) giới hạn/khoảng trống (lệch domain VN, TTC không có chuẩn, VND chỉ có nguồn cộng đồng).

Nguồn đã tra: arXiv 2512.19190 (PEDESTRIAN); PMC11645096 (YOLO-OD); Springer s10209-021-00837-9 (Obstacle-Dataset); arXiv 2312.07571; fujipress JRM 33/5 (VIDVIP);
CVPR 2021 dict-guided + github.com/VinAIResearch/dict-guided (VinText); MC-OCR (RIVF 2021); arXiv 2506.05061 (khảo sát OCR tiếng Việt); github.com/microsoft/banknote-net;
universe.roboflow.com/kimthai/vnd; vizwiz.org (VQA, Grounding arXiv 2202.01993, QualityIssues arXiv 2003.12511); ORBIT arXiv 2104.03841; PhoWhisper arXiv 2406.02555;
Vietnamese Open ASR Leaderboard (HF Space vietaudio-team); arXiv 1903.09102 (TTC robot hành lang).
