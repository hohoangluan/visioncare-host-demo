# Bàn giao — đánh giá và cải tiến các chức năng AI (session 2026-10-21)

Đọc file này trước khi làm tiếp. Mọi số đều có CI 95 % bootstrap trong báo cáo gốc; ở đây chỉ chép số chính.

## 0. Trạng thái tức thời (đọc trước)

| Mục | Trạng thái |
|---|---|
| Nhánh `vqa-hoi-anh` — worktree `SeeVia_system/vh-vqa` | **Đã commit `adc7e9b`** (tác giả LuanLuKim, 2026-10-21), CHƯA push (lệnh push bị chặn quyền). Intent mới `ask`. pytest 530 passed, 2 skipped |
| Nhánh `ocr-tien` — worktree `SeeVia_system/vh-ocr` | **Đã commit `a907ff9`**, CHƯA push. Đọc tiền chọn nhãn + gộp khung, cảnh báo chữ số OCR. pytest 540 passed, 2 skipped |
| Hai worktree | Đều tách từ `app-giao-tiep@00ad021`. Có symlink `.env` và `certs/uit-ca-bundle.pem` trỏ về `visioncare-host-demo/` (đã gitignore) |
| `visioncare-host-demo` (bản chính) | Có thay đổi CHƯA commit của người dùng (`app.py`, `demo-web/README.md`, xoá `demo-web/mock.js`). **Không đụng.** Chưa thay model hay prompt nào trong bản chính |
| Đo lại trễ vật cản | `train/relatency.sh` **HẾT ok** 15:17; `HAZARD_MODELS.md` khớp bảng mục 5 |
| Quyết định 2026-10-21 tối | (a) sửa logic OD: **LÀM** — thiết kế `docs/superpowers/specs/2026-10-21-vat-can-du-doan-quy-dao-design.md` (chờ duyệt; người dùng: báo oan KHÔNG được tăng, ghi đủ đánh đổi). (b) đọc tiền: **Claude soạn đặc tả** — chưa viết; phát hiện: firmware đã có `cam`/`capture`/`cue` của live OCR → có thể không cần đổi firmware. (c) commit: xong, chưa rebase |
| Nhánh lệch | `app-giao-tiep` đã tới `110c642` (+6 commit sau `00ad021`); trùng file: vh-vqa `tests/test_v2_units.py`, vh-ocr `lanes/ocr_live.py`; với thay đổi chưa commit của người dùng: `pipeline/image_quality.py`, `config.py` |
| File thừa | `evaluations/judge_part1.csv`: bản trùng 40 dòng do subagent ghi nhầm chỗ, đã gộp vào `pair_judge/judge_part2.csv`. Xoá được. Agent bị từ chối quyền xoá, để người dùng quyết |
| Codex | Extension `openai.chatgpt` **đã bị gỡ** khỏi `~/.vscode-server` → giám khảo nhìn ảnh dùng Claude Sonnet subagent |
| Người dùng cần làm | Chấm lại tay `SeeVia_system/handcheck_50_ask_vs_space.csv`: cùng 50 ảnh đã chấm, câu cũ + ghi chú cũ đặt cạnh câu mới |

Nguyên tắc người dùng chốt trong session:
- **Đo là để tìm tổ hợp tham số cân bằng tốc độ và độ chính xác.** Lưới cấu hình chạy trên tập dev riêng, luật chọn chốt trước khi xem số, báo một lần trên test và so ghép đôi.
- Tìm đồ: chức năng bổ sung, **chưa đo**.
- Vật cản: giả định **không có IMU**, áp dụng **Việt Nam** trước.
- Không tự thay model/prompt trong VH chính khi người dùng chưa duyệt.

## 1. Hỏi về ảnh (VQA) — intent `ask`

**Đầu vào:** bản chấm tay `handcheck_50_human.csv`. Lỗi chung là trả lời thừa và không tập trung vào câu hỏi; 40/50 ghi chú nói điều đó. Người dùng thích chi tiết **khi được nhờ mô tả**.

**Gốc lỗi.** Không phải module OD:
- Câu hỏi về ảnh đi qua prompt `describe_space`. Prompt này bắt buộc nói loại phòng + bố cục, và cấm đọc chữ, nên "số thẻ là bao nhiêu" bị đẩy sang "hãy hỏi riêng".
- Bộ phân loại intent không có nhãn cho loại câu này. Trên 300 câu VizWiz: 21 % rơi vào `chat` (không gửi ảnh), 28 % vào `ocr` (đọc cả trang, bỏ qua câu hỏi), 49 % vào `space`.

**Đã làm (`vh-vqa`):**
- `handlers/ask_image.py`: prompt ghi rõ "TRẢ LỜI CÂU HỎI CHO NGƯỜI MÙ". Câu đầu chính là đáp án, tối đa 2 câu. Khi ảnh không đủ thì nói lý do + một cách sửa.
- Nhãn `ask`, đặt ở **CUỐI** `LABELS` trong `models/clef/client.py`. Chèn vào giữa danh sách làm lệch `message_send`: mất 14 câu gold.
- Làn A, cổng ảnh, luật từ khoá. Thêm luật "lệnh ĐỌC nói thẳng (`đọc…`, `nguyên văn`) thắng nhãn `ask`".

**Số (VizWiz val, 300 câu test; prompt chỉnh trên 100 câu dev riêng)** — báo cáo `evaluations/reports/VQA_ASK.md`:

| Chỉ số | `space` cũ | `ask` mới |
|---|---|---|
| Câu đầu trả lời thẳng câu hỏi (giám khảo Sonnet nhìn ảnh, chấm mù 150 cặp) | 26 % | **99 %** |
| Có nội dung thừa | 95 % | **7 %** |
| Đúng với ảnh | 73 % | **92 %** |
| Chọn câu tốt hơn | 14 | **134** (hoà 2) |
| VQA acc (Gemma chấm, chuẩn VizWiz) | 70,7 % | **83,6 %** |
| Không từ chối khi ảnh không đủ | 72,1 % | **40,4 %** |
| Số từ trung vị | 35 (~9,7 s đọc) | **20 (~5,6 s)** |
| Câu hỏi về ảnh rơi vào `chat` (không ảnh) | 62/300 | **13/300** |
| Độ trễ A/B gọi mới, cùng ảnh | | TTFT +41 ms [+33; +49] · tổng −127 ms |

- Đối chứng âm của giám khảo đạt: 15/15 câu tráo ảnh bị bắt, 15/15 cặp y hệt được chấm hoà.
- Gold intent: test 94,6 → 97,3 % (+4 / −0); dev 94,7 → 93,9 % (+5 / −7). 6/7 câu "mất" ở dev là câu hỏi một chi tiết mà gold ghi `ocr`.
- Nhiễu chạy lại bộ phân loại: 1/158 câu.

## 2. Đọc tiền VND

Báo cáo: `evaluations/reports/MONEY_OCR_CAI_TIEN.md`.

**Dữ liệu:** `vnd_kaggle`, ảnh webcam 192×144, không có baseline. Dev là 180 khung nằm xen giữa các khung test (không trùng); test là 360 ảnh như baseline.

**Luật chọn (chốt trước):** độ đúng cao nhất với điều kiện nói sai ≤ 3 %, trễ p90 ≤ bản cũ + 100 ms.

**Đã làm (`vh-ocr`, `handlers/read_money.py`):**
- Gemma **chọn 1 trong 13 nhãn** (structured choice) + xác suất token, kèm system prompt làn A.
- `combine()`: nói mệnh giá khi có ≥ 1 khung chắc và không khung nào chắc một mệnh giá khác.
- `read_choice(images)` chạy các khung song song.
- Cờ: `MONEY_MODE=choice`, `MONEY_MIN_PROB=0.995` (1 ảnh), `MONEY_MULTI_MIN_PROB=0.98` (≥ 2 ảnh).

**Kết quả test (330 ảnh có tiền, ghép đôi với làn B cũ):**

| Cấu hình | Nói sai | Đúng | Từ chối | Trễ p50 / p90 |
|---|---|---|---|---|
| Làn B cũ | 11,2 % | 67,3 % | 20,9 % | 211 / 234 ms |
| 1 khung, τ 0,995 (production hiện tại: kính gửi 1 ảnh) | 3,3 % | 57,3 % | 39,4 % | 202 / 215 ms |
| **3 khung song song, τ 0,98** | **1,8 %** (Δ −9,4) | **77,3 %** (Δ +10,0) | 20,9 % | 228 / 340 ms |

**Vì sao còn sai/từ chối:** con số bị **cắt ở mép khung, gập, hoặc ngón tay che**. Gemma đọc đúng phần nhìn thấy và rất chắc: "50000" của tờ 500.000 lệch mép, 9 ca. Độ mờ không phải nguyên nhân chính (nhóm nét nhất đúng 83 %, nhoè nhất 76 %). Theo mệnh giá: 1.000 cũ đúng 23 %, 500.000 đúng 63 %.

**Đã thử và LOẠI (đều có số trên dev):**

| Cách | Lý do loại |
|---|---|
| JSON chép số + chữ rồi code đối chiếu | Trễ ×3; model chép luôn số khớp điều nó đoán |
| Prompt "đếm kỹ chữ số 0" | Sai 43 % |
| Tầng 2 "quan sát kỹ" | Không thêm được ca đúng nào, p90 768 ms |
| Chuẩn hoá xác suất trên 13 nhãn | 1 khung: nói sai gấp đôi |
| 5 khung | 69,7 % đúng, thấp hơn 3 khung |
| Prompt "chỉ kết luận khi thấy trọn số" | Không khác (trong nhiễu ±2 điểm) |
| Luật "số dài hơn thắng" | Đúng 12 / sai 8 |

## 3. OCR chữ số

- **Mảnh phóng to (2 tile):** loại. SROIE dev chỉ sửa 1 ca mỗi loại mà +180 ms. Ảnh SROIE chỉ ~463 px, lỗi không do thiếu điểm ảnh.
- **Cảnh báo "chưa chắc" theo xác suất token chữ số** (`lanes/ocr_live.read_image`, `stream_chat(on_logprobs=)`, `OCR_DIGIT_HEDGE_PROB=0.9`). Vẫn đọc số, rồi nói thêm "Có con số tôi đọc chưa chắc, bạn đưa lại gần để tôi đọc lại."
  - Test: AUROC 0,85 (SROIE 0,92 · ViTextVQA 0,69).
  - Bắt được 16 % số sai, gắn cảnh báo cho 2,7 % câu. Trễ thêm 0.
- **Lỗi SROIE còn lại** có 2 loại: đọc nhầm chữ số, và chọn nhầm dòng (tiền khách đưa / làm tròn thay vì tổng). **Chưa sửa.**

## 4. Tốc độ LLM (đo trong session)

Mạng tới `llm.uit.edu.vn` mất 4 ms. Một lượt Gemma không ảnh 40–51 ms; có ảnh ~200 ms bất kể cỡ ảnh. Như vậy **~150 ms là server xử lý ảnh, và server không cache phần này** (prewarm 199 → 200 ms). Đòn bẩy còn lại nằm ở cấu hình vLLM của server.

## 5. Vật cản (OD)

**Retrain `retrain_p0.sh`** (patience=0, đủ 120 epoch, 4 model): xong.
- ft_26s từng treo NFS 3,5 giờ (worker kẹt chờ NFS); đã kill, script tự resume.
- Phát hiện: `best.pt` do Ultralytics chọn **vẫn là epoch 1** với 11s/26s/26m, vì tiêu chí mAP val có 5 lớp nhãn giả do chính YOLO COCO gán.
- ft_11m ra số trùng tuyệt đối bản cũ vì `seed=0` tái lập, và epoch tốt nhất (74) nằm trước chỗ bản cũ dừng (94).

**Bước A (`train/bench_last.sh`):** đo `last.pt` bằng metric của mình (test, ảnh qua kính, ngưỡng 0,35, recall vật trong lối):

| Model | `best.pt` | **`last.pt`** | Precision (last) | Detect p50 / p90 (đo lại, cùng GPU) |
|---|---|---|---|---|
| yolo11n COCO (đang chạy) | 37,3 % | — | 90,6 % | 5,3 / 5,8 ms |
| **ft_11s** | 88,1 % | **89,9 %** | 94,1 % | **4,9 / 5,3 ms** |
| ft_26s | 83,9 % | 90,3 % | 95,7 % | 5,1 / 6,1 ms |
| ft_26m | 85,3 % | 90,6 % | 95,0 % | 6,5 / 7,0 ms |
| ft_11m | 90,7 % (ep 74) | 90,8 % | 95,3 % | 6,5 / 7,0 ms |

- **Đề xuất: `train/models/ft_11s_last_320.onnx`**, cần lớp `train/classes_vh.json`. Chưa cài vào VH.
- Trong `HAZARD_MODELS.md`, cột trễ của một số dòng bị nhiễu do máy dùng chung (load CPU lên 62). Dùng số trong bảng trên, đo liền nhau lúc máy yên.

**Vì sao OD vẫn tệ — 3 tầng (đã thảo luận với người dùng):**
1. **Logic cảnh báo** (`live/hazard.py::level_of`, dựa trên DIỆN TÍCH hộp). Với detector hoàn hảo vẫn chỉ cảnh báo kịp 8,3 % kịch bản.
   - Người chạm mức 2 ở ~2,9 m (lead p50 0,38 s).
   - Cột mảnh 15 cm và ghế đá không bao giờ lên mức 2 (trượt 100 %).
2. **Model:** COCO zero-shot chỉ 37 %. Đã giải bằng fine-tune (~90 %).
3. **Dữ liệu/bàn đo chưa phải Việt Nam:** thiếu bậc thềm, mép vỉa hè, ổ gà, vật ngang đầu, xe máy đỗ dày. Bàn đo C1a chỉ dùng ảnh tĩnh.

**Đề xuất sửa logic, CHƯA làm, chờ duyệt** (không IMU, đo trên C1b + thêm kịch bản Việt Nam):
1. TTC từ tốc độ hộp giãn ra: bất biến với góc đầu và kích thước vật.
2. Tracker IoU.
3. Lối đi theo phần hộp lấn vào giữa, không chỉ theo tâm.
4. Mức 3 cần 2/3 khung đồng ý + hysteresis; câu nói kèm hướng tránh.

## 6. Việc cho session sau (theo thứ tự)

1. ~~Hỏi người dùng 3 quyết định còn treo~~ (đã hỏi 2026-10-21, xem mục 0):
   (a) làm sửa logic OD như mục 5;
   (b) đọc tiền 3 khung + căn khung — bên kính/app tự làm, hay Claude soạn đặc tả giao thức;
   (c) commit hai nhánh `vqa-hoi-anh` và `ocr-tien` lên nhánh riêng (chưa merge, chưa push).
2. Nếu người dùng đã chấm `handcheck_50_ask_vs_space.csv`: tính đồng thuận người ↔ giám khảo Sonnet trên bản mới, ghi vào `VQA_ASK.md`.
3. Gộp intent `ask` với cảnh báo chữ số. Câu hỏi về chữ giờ đi làn `ask` (ảnh 896 px), chưa có `on_logprobs`. Đo C2b/C2c qua đường `ask` để so với làn OCR 1600 px.
4. OCR: lỗi "chọn nhầm dòng" trên hoá đơn (tổng vs tiền khách đưa) chưa xử lý.
5. Cài `ft_11s_last` vào VH (nhánh riêng) sau khi người dùng duyệt. Lưu ý lớp model khác COCO (`HAZARD_CLASSES_JSON`).

## 7. Chạy lại

Chạy từ `SeeVia_system/evaluations/`. Đặt `SEEVIA_VH_DIR=<worktree>` để đo một nhánh mà không đụng bản VH chính.

| Việc | Lệnh |
|---|---|
| VQA | `python -m bench.vqa_vizwiz --intent ask [--split dev]` → `python -m bench.vqa_pair_judge build --n-real 150` → giám khảo (4 Sonnet subagent, mỗi agent ghi `judge_partK.csv` riêng, **dặn đặt tên script riêng** vì scratchpad dùng chung) → gộp `judge.csv` → `python -m bench.vqa_pair_judge report` |
| Trễ VQA | `python -m bench.vqa_latency_ab --n 60` |
| Định tuyến | `results/intent_ask/route.py`; gold: `python -m tools.eval_intent --gold data/intent/gold_dev.jsonl --backend gemma --baseline …` (chạy từ thư mục VH) |
| Đọc tiền | `python -m bench.money_vnd --path choice --choice-prompt sys [--split dev]`; `python -m bench.money_multi [--split dev] [--frames 5] [--prompt edge] [--renorm]` |
| OCR | `python -m bench.ocr_sroie --split dev --tiles 2`; `python -m bench.ocr_numconf [--split test]` |
| Vật cản | `bash train/bench_last.sh`; `GPU=<id> bash train/relatency.sh`. Đo trễ khi máy yên: kiểm `uptime` và `nvidia-smi` trước |

**Báo cáo:**
- `evaluations/reports/`: `VQA_ASK.md`, `MONEY_OCR_CAI_TIEN.md`, `HAZARD_MODELS.md` (+ `_p25`), `TONG_HOP.md` (baseline 2026-10-20)
- Nhật ký: `docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md`
