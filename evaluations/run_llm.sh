#!/usr/bin/env bash
# Gói L: C2b -> C3 -> C2a -> C2c -> C4 (LLM xa, GỌI TUẦN TỰ) + báo cáo. Chạy từ evaluations/. KHÔNG tự chạy trong lúc dev.
# Chạy lại an toàn: kết quả LLM nằm ở results/<task>/cache*.jsonl (theo id mẫu + hash cấu hình) nên mẫu đã gọi không gọi lại.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-$HOME/.venvs/seevia/bin/python}"
mkdir -p results reports
LOG=results/llm.log
exec > >(tee -a "$LOG") 2>&1
trap 'rc=$?; if [ $rc -eq 0 ]; then echo "HẾT ok"; else echo "HẾT LỖI ($rc)"; fi' EXIT
echo "=== run_llm.sh $(date -Is) ==="
echo "--- C2b ocr_sroie (361 hoá đơn x 2 câu = 722 lần gọi)"
"$PY" -m bench.ocr_sroie
echo "--- C3 money_vnd, đường general.answer (360 ảnh)"
"$PY" -m bench.money_vnd --path general
echo "--- C3 money_vnd, đường ocr_live.spoken 'money' (đường thật của làn B, 360 ảnh)"
"$PY" -m bench.money_vnd --path ocr_spoken
echo "--- C2a ocr_vintext (300 ảnh)"
"$PY" -m bench.ocr_vintext
echo "--- C2c ocr_vitextvqa (300 câu)"
"$PY" -m bench.ocr_vitextvqa
echo "--- C4 vqa_vizwiz (300 câu: dịch + trả lời + chấm LLM = ~900 lần gọi)"
"$PY" -m bench.vqa_vizwiz
echo "--- báo cáo"
"$PY" -m bench.report_llm
