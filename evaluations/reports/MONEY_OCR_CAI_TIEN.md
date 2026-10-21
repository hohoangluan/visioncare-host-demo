# Đọc tiền + OCR — tìm cấu hình cân bằng độ chính xác và tốc độ (2026-10-21)

Code: worktree `SeeVia_system/vh-ocr`, nhánh `ocr-tien` (chưa commit, chưa gộp). Bàn đo: `bench/money_vnd.py --path choice`,
`bench/money_multi.py`, `bench/ocr_sroie.py --tiles`, `bench/ocr_numconf.py`. Máy LLM: Gemma 4 26B xa (`llm.uit.edu.vn`).

**Cách làm (giống mọi bàn đo đợt này):** mỗi chức năng là một lưới cấu hình; đo độ đúng + độ trễ trên tập **dev** riêng; chọn theo
luật chốt TRƯỚC khi xem số; báo **một lần** trên tập test, ghép đôi với cấu hình đang chạy (CI 95 % bootstrap, đếm câu bất đồng).

## 1. Đọc tiền VND (làn B, `money`)

Dữ liệu: `vnd_kaggle` (cộng đồng, không baseline; ảnh webcam 192×144 — kính thật gửi tới 1600 px nên số từ chối ở đây là bi quan).
Dev = 180 khung nằm giữa các khung test (không trùng); test = 360 ảnh như baseline 2026-10-20.
Phân tích lỗi baseline: gần như mọi ca nói sai là **sai số chữ số 0** (5.000↔50.000, 10.000↔100.000, 500.000→50.000).

**Luật chọn (chốt trước):** độ đúng cao nhất với nói sai ≤ 3 %, trễ p90 ≤ bản cũ + 100 ms.

### Lưới trên dev (180 ảnh, 165 có tiền)

| Cấu hình | τ | Nói sai | Đúng | Từ chối | Trễ p50 / p90 ms | Kết luận |
|---|---|---|---|---|---|---|
| Làn B cũ — prompt tự do | — | 10,9 % | 66,1 % | 23,0 % | 218 / 237 | baseline |
| Đường `general` (system prompt làn A) | — | 4,8 % | 69,1 % | 26,1 % | 210 / 226 | system prompt có ích |
| JSON: chép số + chữ in trên tờ, code đối chiếu | — | 7,9 % | 64,8 % | 0,6 % | **668 / 812** | loại: trễ ×3, model chép luôn số khớp điều nó đoán |
| Chọn nhãn (13 nhãn) + xác suất, prompt "đếm kỹ chữ số 0" | 0,9 | 0,6 % | 12,7 % | 86,7 % | 193 / 227 | loại: prompt này làm sai 43 % ở τ = 0 |
| Chọn nhãn, prompt cũ | 0,99 | 2,4 % | 51,5 % | 46,1 % | 185 / 205 | |
| Chọn nhãn + system prompt (1 khung) | 0,995 | 3,0 % | 59,4 % | 37,6 % | 177 / 199 | tốt nhất khi chỉ có 1 ảnh |
| 3 khung song song, trung bình xác suất | 0,95 | 0 % | 38,8 % | 61,2 % | 218 / 230 | loại: từ chối quá nhiều |
| 3 khung, đa số (≥ 2 khung chắc cùng nhãn) | 0,95 | 0 % | 61,8 % | 38,2 % | 218 / 230 | |
| **3 khung, ≥ 1 khung chắc + không khung nào chắc nhãn khác** | **0,98** | **3,0 %** | **75,2 %** | **21,8 %** | **218 / 230** | **chọn** |
| Tầng 2 "quan sát kỹ" cho ca xác suất thấp | bất kỳ | 1,8 % | 60,0 % | 38,2 % | 198 / **768** | loại: không đọc thêm được, trễ |

(Khung kề = khung i ± 3 của cùng video — mô phỏng kính chụp liên tiếp. 3 lượt Gemma chạy song song nên trễ = lượt chậm nhất.)

### Test (360 ảnh, ghép đôi trên 330 ảnh có tiền) — cấu hình chọn trên dev

| | Làn B cũ | 1 khung, chọn nhãn + system, τ 0,995 | **3 khung (B3), τ 0,98** |
|---|---|---|---|
| **Nói sai mệnh giá** | 11,2 % | 3,3 % (Δ −7,9 [−10,9; −5,2]) | **1,8 %** (Δ −9,4 [−13,0; −6,1]; bất đồng 35/4) |
| **Đúng** | 67,3 % | 57,3 % (Δ −10,0) | **77,3 %** (Δ +10,0 [+4,5; +15,8]; bất đồng 27/60) |
| Từ chối | 20,9 % | 39,4 % | 20,9 % |
| Bịa tiền (ảnh không có tiền) | 0 % | 0 % | 0 % |
| Trễ p50 / p90 ms | 211 / 234 | 202 / 215 | 228 / 340 (p90 vượt ngân sách +100 ms đúng 6 ms) |

### Vì sao còn sai / từ chối (B3, test, 330 ảnh có tiền)

Đúng 77,3 % · xác suất < τ 11,5 % · mâu thuẫn giữa 2 khung chắc 8,5 % · sai 1,8 % · cả 3 khung "không rõ" 0,9 %.
Độ mờ KHÔNG phải nguyên nhân chính (Laplacian: nhóm nét nhất đúng 83 %, nhoè nhất 76 %). Theo mệnh giá: 1.000 đúng 23 %,
500.000 63 %, 500 67 %; 5.000/10.000/100.000 93–97 %.
**Cơ chế (xem tận mắt 34 ca sai + mâu thuẫn):** con số bị **cắt ở mép khung, bị gập hoặc ngón tay che** — Gemma đọc ĐÚNG phần nhìn
thấy và rất chắc ("50000" của tờ 500.000 lệch mép: 9 ca; tờ 200 đồng chỉ thấy "200" → "20 nghìn"). 3 khung giúp vì khung kề
thường thấy trọn số. Đã thử và LOẠI (dev): luật "số dài hơn thắng" (đúng 12 / sai 8 trên ca mâu thuẫn), prompt "chỉ kết luận khi
thấy trọn số" (74,5 % vs 75,2 %, trong nhiễu), 5 khung (69,7 % — thêm khung = thêm khung cắt "chắc mà sai"), chuẩn hoá xác suất
trên 13 nhãn (1 khung: sai 3,6 → 7,3 %). **Hướng sửa đúng gốc nằm ở khâu chụp:** hướng dẫn người dùng đưa TRỌN tờ tiền vào khung
(như vòng căn khung của OCR, `live/text_align.py`) rồi mới chụp 3 khung.

### Tốc độ

Mạng tới server LLM 4 ms; một lượt Gemma không ảnh 40–51 ms; có ảnh ~200 ms bất kể cỡ ảnh (192 hay 896 px) → ~150 ms là server
xử lý ảnh. Prewarm (nạp trước system + ảnh) KHÔNG giảm (199 → 200 ms): server không cache phần ảnh. Gộp sớm khi 2 khung đầu
khớp: p90 330 → 324 ms (không đáng). Đòn bẩy còn lại ở cấu hình vLLM của server (cache encoder ảnh / prefix cache đa phương tiện).

**Cài trong VH (`handlers/read_money.py`):** `choose` (structured choice + logprobs), `combine` (luật B3, dùng chung với bàn đo),
`read_choice(images)` chạy song song. `MONEY_MODE=choice`, `MONEY_MIN_PROB=0.995` (1 ảnh), `MONEY_MULTI_MIN_PROB=0.98` (≥ 2 ảnh).
**Hiện kính chỉ gửi 1 ảnh/lượt** → production đang chạy cấu hình 1 khung; muốn có B3 cần kính chụp liên tiếp 3 khung khi đọc tiền.

## 2. OCR — chữ số

### Phân tích lỗi (SROIE test, baseline 2026-10-20)

Hai loại: (a) **đọc nhầm chữ số** (8→2, 14,85→4,85, 26→28, 2018→2015); (b) **chọn nhầm dòng** (lấy tiền khách đưa thay vì tổng,
tổng trước/sau làm tròn). Ảnh SROIE chỉ ~463×1013 nên gửi 1600 px không giúp.

### Gửi thêm mảnh phóng to (SROIE dev = 120 hoá đơn tập TRAIN × 2 câu)

| Cấu hình | Sai tổng tiền | Sai ngày | TTFT p50 / p90 ms |
|---|---|---|---|
| 1 ảnh (hiện tại) | 5,0 % | 3,3 % | 344 / 399 |
| + 2 mảnh chồng lấn | 4,2 % | 2,5 % | 523 / 607 |

Loại: chỉ sửa 1 ca mỗi loại, tốn +180 ms (vượt ngân sách +100 ms). Lỗi số không phải do thiếu điểm ảnh.

### Độ tin cậy chữ số → câu cảnh báo "chưa chắc"

Xác suất token nhỏ nhất trong các chữ số Gemma sinh ra, so với đúng/sai của con số (dev: SROIE train 120 × 2 + ViTextVQA dev 200 câu có số):

| Tập | đúng / sai | AUROC | τ = 0,9: ca sai bị bắt | câu bị gắn cảnh báo |
|---|---|---|---|---|
| SROIE | 230 / 10 | 0,85 | 20 % | 0,8 % |
| ViTextVQA | 122 / 40 | 0,77 | 35 % | 11,4 % |
| Gộp | 352 / 50 | 0,82 | 32 % | 5,4 % |

Tín hiệu vừa phải → dùng để **cảnh báo**, không để từ chối: vẫn đọc con số, rồi nói thêm "Có con số tôi đọc chưa chắc, bạn đưa lại gần
để tôi đọc lại." Không mất câu đúng nào, không thêm trễ (logprobs đi kèm luồng stream, câu cảnh báo nói sau cùng).
Cài: `lanes/ocr_live.read_image` + `models/llm/client.stream_chat(on_logprobs=...)`, `OCR_DIGIT_HEDGE_PROB=0.9`.

**Test** (SROIE test 361 × 2 + ViTextVQA test 200 câu có số; τ = 0,9 chọn trên dev):

| Tập | đúng / sai | AUROC | ca sai bị bắt | câu bị gắn cảnh báo |
|---|---|---|---|---|
| SROIE | 684 / 37 | 0,92 | 22 % | 1,8 % |
| ViTextVQA | 114 / 36 | 0,69 | 11 % | 6,0 % |
| Gộp | 798 / 73 | 0,85 | 16 % | 2,7 % |

Lưới an toàn bổ sung (bắt ~1/6 số sai, gắn cảnh báo ~3 % câu), không phải lời giải. Trễ 1 lượt không stream p50 328 ms.

## 3. Đọc tiền v2 — đọc chặt 1 khung, hướng dẫn, đọc lại 1 lần (2026-10-21)

Thiết kế: `docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md` (đã duyệt). Cài: `vh-ocr` nhánh `ocr-tien`, commit `b212d38`.
Mục tiêu người dùng: không tăng trễ, ưu tiên giảm đọc sai (chấp nhận từ chối nhiều hơn), khi không đọc được thì nói việc cụ thể.

**Luồng.** Lượt đầu đọc 1 khung (ảnh buffer UXGA) ở τ **0,999** (trước 0,995): chắc thì nói mệnh giá, trễ như cũ. Không chắc (`UNSURE`) thì nói đúng
một câu hướng dẫn rồi mở live `money_retry`: bỏ khung 1,0 s đầu, lấy khung VGA đầu tiên đủ nét (hết 3,0 s thì khung nét nhất), đọc 1 khung ở
τ 0,999, nói kết quả hoặc "Tôi vẫn chưa đọc chắc được tờ này.", `end`. Chỉ đọc lại 1 lần. Không WS (`/process`) thì chỉ nói câu hướng dẫn.
"Không có tiền" và lỗi mạng giữ câu cũ, không đọc lại. `MONEY_RETRY=0` = đường cũ (chỉ khác τ).

**Luật chọn câu** (`handlers/read_money.hint`, từ trên xuống, không tốn lượt model; top-2 lấy từ logprobs của chính lượt chọn nhãn):
1. độ nét < `MONEY_BLUR_HINT` → "Giữ yên tay.";
2. top-1 là "không rõ", hoặc top-1/top-2 là hai mệnh giá lệch đúng ×10 → "Lùi ra xa một chút, để cả tờ tiền nằm giữa.";
3. còn lại → "Đưa tờ tiền lại gần hơn một chút."

**Ngưỡng độ nét (chọn trên dev, không đụng test).** `MONEY_BLUR_HINT = 341,4` = phân vị 25 % độ nét (hàm production `image_quality.measure`,
Laplacian 3×3, JPEG q90 cỡ gốc 192×144) của 81 ảnh dev mà khung đầu đọc ĐÚNG ở τ 0,999. Lệnh:
`cd evaluations && SEEVIA_VH_DIR=../vh-ocr python -m bench.money_blur` (đọc `results/money_vnd/20261021-1454_multi_dev.json`, `frames[0]`).

| Nhóm dev (165 ảnh có tiền, khung đầu, τ 0,999) | n | độ nét trung vị | p25 |
|---|---|---|---|
| đọc đúng | 81 | 454,5 | 341,4 |
| nói sai | 2 | 573,1 | 455,4 |
| từ chối | 82 | 321,4 | 227,5 |

Trong 82 ảnh bị từ chối, 55 % dưới ngưỡng. Trên đường production, luật 1 chọn nhóm "Giữ yên tay." cho 44/82, "Lùi ra xa" 21/82, "Lại gần" 17/82
(27/82 có cặp top-1/top-2 lệch ×10). Độ nét trong production tính sau khi thu ảnh về cạnh dài 192 px (`read_money.blur_score`) để cùng cỡ với ảnh dev.

**Bảng spec §2 (test, 330 ảnh có tiền; khung đọc lại = khung i+3 của cùng video):**

| Cấu hình | Nói sai | Đúng | Từ chối | Bịa | Lượt đọc lại | Trễ lượt thành công |
|---|---|---|---|---|---|---|
| Trước: 1 khung, τ 0,995 | 3,6 % (12) | 57,0 % | 39,4 % | 0 | 0 | như cũ |
| 1 khung τ 0,999, không đọc lại | 2,1 % (7) | 49,4 % | 48,5 % | 0 | 0 | như cũ |
| **v2: 1 khung τ 0,999 + đọc lại 1 lần τ 0,999** | 2,7 % (9) | **65,8 %** | 31,5 % | 0 | 53 % | **như cũ** |
| v1: 3 khung song song τ 0,98 (để so) | 1,8 % | 77,3 % | 20,9 % | 0 | 0 | +~0,5 s mọi lượt |

**Bàn đo offline vừa chạy lại trên mã đã đổi** (`python -m bench.money_vnd --path choice --choice-prompt sys --split dev|test`, từ `evaluations/`,
`SEEVIA_VH_DIR=../vh-ocr`; 1 khung, chưa tính đọc lại):

| τ 0,999, 1 khung | Nói sai | Đúng | Từ chối | Bịa |
|---|---|---|---|---|
| dev (165 có tiền + 15 không tiền) | 1,2 % | 49,1 % | 49,7 % | 0 |
| test (330 có tiền + 30 không tiền) | **1,8 %** | **49,7 %** | **48,5 %** | 0 |
| test, τ 0,995 (đối chiếu) | 3,3 % | 57,3 % | 39,4 % | 0 |

Test khớp spec §2 trong nhiễu (sai 2,1 → 1,8 % = chênh 1 ca; đúng 49,4 → 49,7 %; từ chối trùng 48,5 %). Kết quả: `results/money_vnd/20261021-1701_choice_sys.json`
(test), `20261021-1700_choice_sys_dev.json` (dev). Trễ lượt Gemma: p50 202 ms, p90 215 ms (test).

**Đo kèm trên đường production** (180 ảnh dev, cùng thông điệp):
- `choose_ranked` (top_logprobs=5) và `choose` (top_logprobs=1) cùng p50 188 ms, p90 204/208 ms; lượt chắc qua `final_router._money` p50 187 / p90 200 ms,
  bằng thời gian tới mảnh text đầu của đường cũ (`ocr_live.spoken`).
- Server không tất định: hai lần `choose` liên tiếp trên cùng ảnh khác nhãn ở 12/180 ảnh (biên); `choose` vs `choose_ranked` khác 7–9/180. Câu nói ở τ 0,999 trùng 174/180.
- `blur_score` tốn ~22 ms cho UXGA, ~5 ms cho VGA (chỉ tính ở lượt không chắc và khung live đọc lại).

**Giới hạn.**
- Khung đọc lại trong bàn đo là khung kề của video webcam 192×144, KHÔNG phải khung sau khi người dùng làm theo hướng dẫn → 65,8 % là cận dưới.
- Câu nào đúng hơn (lùi / lại gần / giữ yên) và ngưỡng 341,4 chưa kiểm được trên bàn tĩnh: ngưỡng chọn ở 192×144 rồi áp lên khung kính đã thu nhỏ; phải
  hiệu chỉnh lại bằng ảnh thật.
- Đọc lại làm số ca nói sai tăng 7 → 9 (thêm 1 lượt đọc = thêm 1 cơ hội sai); muốn chặt hơn thì `MONEY_RETRY_PROB=0.9995` (chưa đo).
- **Bắt buộc trước khi bật mặc định:** thử thật trên kính, 10 tờ × 3 tư thế khó (lệch mép, xa, rung tay): % đọc được sau 1 lần hướng dẫn, % nói sai,
  thời gian lượt có đọc lại, và p90 lượt đọc chắc không chậm hơn bản hiện tại (cùng máy). Chỉnh `MONEY_RETRY_SETTLE_S`, `MONEY_BLUR_HINT` theo kết quả.
