#!/usr/bin/env bash
# Lượt xác nhận (2026-10-21): Codex chấm MÙ cặp space (baseline 2026-10-20) vs ask (câu trả lời MỚI của run_chot_ai.sh), nhìn ảnh.
# Chờ results/chot/vqa_vizwiz/*_general_ask.json xuất hiện, dựng bộ chấm ở results/chot/vqa_pair, Codex chấm tới đủ dòng, ra reports/VQA_ASK_CHOT.md.
set -uo pipefail
cd "$(dirname "$0")"
EV=$PWD
PY=$HOME/.venvs/seevia/bin/python
export SEEVIA_VH_DIR="${SEEVIA_VH_DIR:-$(cd .. && pwd)/vh-chot}"
export PAIR_JUDGE_DIR=$EV/results/chot/vqa_pair PAIR_JUDGE_REPORT=VQA_ASK_CHOT.md
mkdir -p "$PAIR_JUDGE_DIR"
LOG=$PAIR_JUDGE_DIR/judge.log
say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
MARK=$PAIR_JUDGE_DIR/.start; touch "$MARK"  # chỉ nhận câu trả lời sinh SAU lúc này (tránh vớ kết quả lượt cũ)
until NEW=$(find results/chot/vqa_vizwiz -name "*_general_ask.json" -newer "$MARK" 2>/dev/null | sort | tail -1) && [ -n "$NEW" ]; do
  grep -q "HẾT LỖI" results/chot/chot_ai.log 2>/dev/null && { say "run_chot_ai LỖI trước khi có VQA"; echo "HẾT LỖI" >> "$LOG"; exit 1; }
  sleep 60
done
export PAIR_JUDGE_NEW=$EV/$NEW
say "nguồn ask mới: $PAIR_JUDGE_NEW"
"$PY" -m bench.vqa_pair_judge build --n-real 150 >> "$LOG" 2>&1 || { echo "HẾT LỖI" >> "$LOG"; exit 1; }
C=$(ls -d "$HOME"/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex 2>/dev/null | tail -1)
[ -x "$C" ] || { say "không thấy codex"; echo "HẾT LỖI" >> "$LOG"; exit 1; }
count() { "$PY" -c "import csv,sys; print(sum(1 for _ in csv.DictReader(open(sys.argv[1], encoding='utf-8'))))" "$1"; }
J=$PAIR_JUDGE_DIR
N=$(count "$J/blind.csv")
say "bắt đầu chấm $N dòng, codex $C"
for attempt in 1 2 3 4 5 6 7 8; do
  have=0; [ -f "$J/judge.csv" ] && have=$(count "$J/judge.csv")
  say "lượt $attempt: đã có $have/$N"
  [ "$have" -ge "$N" ] && break
  timeout 3h "$C" exec -m gpt-6-luna -s workspace-write --skip-git-repo-check -C "$J" -o "$J/last_message.txt" \
    "Đọc và làm theo $J/BRIEF.md. Không hỏi lại." >> "$LOG" 2>&1
done
"$PY" -m bench.vqa_pair_judge report >> "$LOG" 2>&1 && echo "HẾT ok" >> "$LOG" || echo "HẾT LỖI" >> "$LOG"
