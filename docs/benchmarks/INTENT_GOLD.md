# Mốc đo intent trên gold_dev (2026-10-19)

Tập `data/intent/gold_dev.jsonl`: 160 dòng (104 clean + 56 STT SNR 10 dB), `--min-snr 10`.
Lệnh: `python -m tools.eval_intent --gold data/intent/gold_dev.jsonl --backend <b> [--params] --concurrency <n>`.
Gemma và Clef đều là dịch vụ từ xa (llm.uit.edu.vn, Cloudflare) nên không cần GPU local.

| backend | concurrency | acc | acc clean | acc STT10 | p50 ms | p90 ms | action_fp |
|---|---|---|---|---|---|---|---|
| gemma (+params) | 1 | 0,881 | – | – | 256 | 261 | 5 |
| gemma (+params) | 8 | 0,875 | 0,919 | 0,722 | 368 | 407 | 5 |
| clef | 1 | 0,806 | – | – | 431 | 758 | 20 |
| clef | 8 | 0,744 | 0,790 | 0,583 | 556 | 958 | 21 |
| keyword | – | 0,456 | 0,484 | 0,361 | 0 | 0 | 15 |

Ghi chú
- Độ trễ đáng tin chỉ ở concurrency 1; ở 8 bị xếp hàng phía server (Clef còn timeout 1 s vài lần, tính là sai). Gemma p50 256 ms hôm nay cao hơn mốc 161 ms ghi trong `intent_classifier.py` (cùng prompt; do tải server/mạng lúc đo).
- keyword: không khớp luật thì dự đoán `chat`, vì vậy lỗi chủ yếu là "-> chat".
- `action_fp` đếm trên cả clean lẫn STT; gemma: 5 (6 câu chat bị đoán nav_start là nguồn lỗi lớn nhất).
- Sai số chuẩn của acc ~3 điểm: so A/B bằng `discordant` (McNemar), không so acc đứng riêng.
- Kết quả thô nằm ở `results/` (gitignore), dựng lại được bằng lệnh trên.

## Task 4: chỉnh prompt (2026-10-19, gold_dev, concurrency 1, Gemma +params)

Mỗi vòng đổi một trục; so với vòng trước bằng McNemar (a_only/b_only = mới/trước).

| vòng | thay đổi | acc | p50 ms | p90 ms | action_fp | vs trước |
|---|---|---|---|---|---|---|
| 0 | mốc chạy lại (code Task 3) | 0,894 | 263 | 269 | 4 | – |
| 1 | mô tả nhãn: chat "X ở đâu" ≠ nav_start, hazard ≠ alert_on, nav_start cần điểm đến | 0,925 | 268 | 325 | 4 | 9/4, p=0,27 |
| 2 | few-shot tĩnh trong `_PREFIX` + quy tắc tắt/dừng theo bối cảnh | 0,912 | 268 | 274 | 8 | 2/4 (tệ: "Tắt ngay" -> music_stop) |
| 3 | bỏ ví dụ music_stop; `_context` nói thẳng "tắt/dừng trống không = nav_stop/…" khi đúng 1 trạng thái bật; enum ocr_mode thêm raw/specialized | **0,956** | 267 | 273 | 3 | vs vòng 1: 5/0, p=0,06 |
| 3+ | luật từ khoá + prompt tham số (không đổi đường Gemma intent) | 0,956 | 265 | 273 | 1 | 0/0 |

p50 tăng +2..+5 ms so với mốc (< ngưỡng +10 ms, nằm trong nhiễu mạng). Rút gọn khoá JSON (1c) bỏ qua: ghi chú Fast mode, p50 bị mạng chi phối (~250 ms) chứ không phải token đầu ra.
Clef dùng chung `LABELS`: dev 0,806 -> 0,844, p50 365, p90 618, FP 22 (fallback, không tối ưu thêm).

Lỗi còn lại trên dev đều là STT SNR 10 bị méo nặng ("Phát sóng short", "Tình dạt của cái tơ lợn"…), không sửa được bằng prompt.

### Luật từ khoá (`--backend keyword`)
Precision từng luật trên dev: trước 8 luật < 90% ("đọc" 50%, "gọi" trần 33%, "tìm" 50%, "vật cản/nguy hiểm" 50%, "đi tới" 88%, "trước mặt" 83%, "nghe nhạc" 67%). Sửa: "đọc" chỉ ở đầu câu, "số tiền" -> money, bỏ "gọi" trần, "tìm đường" -> nav_start, "đi tới/đến" chỉ ở đầu câu, "chướng ngại/có nguy hiểm không" -> hazard, thêm các biến "tắt/ngừng cảnh báo", "dừng nghe nhạc". Sau sửa mọi luật >= 100% trừ hazard 78% (2 câu STT méo). Keyword acc 0,456 -> 0,550, action_fp 15 -> 8. Luật chỉ phục vụ đoán sớm + dự phòng.

### Prompt tham số (`--params`, 33 câu làn D có tham số)
Sai 7/33 (21%) trước -> 2/33 (6%) sau; 2 câu còn lại là STT méo ("Tình dạt của cái tơ lợn"). Nguyên nhân sửa được: prompt "KHÔNG đoán" khiến Gemma trả rỗng cho "người thân", "địa chỉ này", thể loại nhạc. p50 trích tham số 172 -> 138 ms (nhiễu).

### Ngưỡng cổng ACTION_MIN_CONFIDENCE (dev, bản chốt)
Quét ngưỡng (ask_rate = tỉ lệ câu làn D bị hỏi lại): 0,85 -> FP 1, ask 1,8%; 0,99 -> FP 1, ask 3,6%; **0,999 -> FP 0, ask 9,1%**; 1,0 -> ask 36%.
Ngưỡng nhỏ nhất cho FP = 0 là **0,999**: FP duy nhất là "Phát sóng short" (emergency_call -> music_play, conf 0,9987), một mẫu méo, nên 0,999 khớp một điểm — ghi nhận là đường cong dốc, không phải biên chắc chắn.

### gold_test (chạy một lần, bản chốt, --gate 0,999)
| | acc | clean | STT10 | acc nhóm đủ biến thể | p50 | p90 | action_fp | ask_rate |
|---|---|---|---|---|---|---|---|---|
| mốc (trước Task 4) | 0,888 | 0,908 | 0,800 | 0,866 | 264 | 270 | 7 | – |
| sau Task 4 | 0,963 | 0,966 | 0,950 | 0,951 | 267 | 273 | 0 | 0,050 |

McNemar mới vs mốc: 8/0, p = 0,0078.

### Hedge (Step 4b)
Không bật (`INTENT_HEDGE_AFTER_S` không tồn tại trong nhánh này; không thêm). Trên dev p90 chỉ cách p50 ~8 ms (273 vs 265): đuôi đã sát, không có gì để hedge cắt, mà mỗi hedge tăng request.
