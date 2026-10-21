#!/usr/bin/env bash
# Lượt XÁC NHẬN cuối (2026-10-21): chạy lại mọi bàn AI không thuộc vật cản trên nhánh tích hợp vh-chot.
# Tham số đã chọn trên dev ở các đợt trước; lượt này chạy test MỘT lần, không chỉnh theo số test.
# Vật cản (C1a/b/c) chạy riêng sau khi nhánh od-du-doan gộp vào: run_chot_hazard.sh.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-$HOME/.venvs/seevia/bin/python}"
export BENCH_CACHE_TAG="${BENCH_CACHE_TAG:-chot$(date +%Y%m%d)}"
export SEEVIA_VH_DIR="${SEEVIA_VH_DIR:-$(cd .. && pwd)/vh-chot}"
EVAL=$(pwd)
OUT=results/chot
mkdir -p "$OUT"
LOG="$OUT/chot_ai.log"
exec > >(tee -a "$LOG") 2>&1
status=LỖI
trap 'echo "HẾT $status"' EXIT
echo "=== run_chot_ai $(date -Is) · cache=$BENCH_CACHE_TAG · VH=$SEEVIA_VH_DIR @ $(git -C "$SEEVIA_VH_DIR" rev-parse --short HEAD) ==="
uptime; nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader
echo "--- C6 STT · VIVOS test (CPU)"
"$PY" -m bench.stt_vivos --out "$OUT/stt_vivos"
echo "--- C5 cổng chất lượng ảnh · VizWiz-QualityIssues val (CPU)"
"$PY" -m bench.quality_vizwiz --out "$OUT/quality_vizwiz"
echo "--- C2a OCR nguyên văn · VinText test"
"$PY" -m bench.ocr_vintext --out "$OUT/ocr_vintext"
echo "--- C2b SROIE test (tổng tiền/ngày)"
"$PY" -m bench.ocr_sroie --split test --out "$OUT/ocr_sroie"
echo "--- C2b/C2c cảnh báo chữ số chưa chắc · test"
"$PY" -m bench.ocr_numconf --split test
echo "--- C2c ViTextVQA test"
"$PY" -m bench.ocr_vitextvqa --out "$OUT/ocr_vitextvqa"
echo "--- C3 đọc tiền v2 · 1 khung τ MONEY_MIN_PROB (mặc định 0,999), chọn nhãn + system"
"$PY" -m bench.money_vnd --path choice --choice-prompt sys --split test
echo "--- C3 đọc tiền · 3 khung τ0,98 (tham chiếu v1, người dùng đã bác vì trễ)"
"$PY" -m bench.money_multi --split test
echo "--- C3 đọc tiền v2 · thời gian tới câu nói đầu tiên, ghép đôi cũ vs v2 (60 ảnh test có tiền)"
"$PY" -m bench.money_turn_latency --n 60
echo "--- C4 VQA · VizWiz val 300 câu, intent ask"
"$PY" -m bench.vqa_vizwiz --intent ask --out "$OUT/vqa_vizwiz"
echo "--- C4 trễ VQA A/B"
"$PY" -m bench.vqa_latency_ab --n 60
echo "--- định tuyến intent · gold test"
(cd "$SEEVIA_VH_DIR" && "$PY" -m tools.eval_intent --gold data/intent/gold_test.jsonl --backend gemma \
  --out "$EVAL/$OUT/intent_gold_test.json")
status=ok
