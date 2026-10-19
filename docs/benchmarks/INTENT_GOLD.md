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
