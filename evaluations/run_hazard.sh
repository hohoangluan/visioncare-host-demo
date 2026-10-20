#!/usr/bin/env bash
# Gói H — vật cản: C1a (phát hiện) + C1c (độ trễ) + C1b (logic) + report. Tuần tự, log results/hazard.log, dòng cuối "HẾT ok|LỖI".
# Biến môi trường chỉ để chạy thử: HAZARD_LIMIT (số ảnh), HAZARD_SEEDS (mặc định 50), HAZARD_OUT (thư mục kết quả), HAZARD_REPORT, SKIP_WAIT=1.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-$HOME/.venvs/seevia/bin/python}"
mkdir -p results reports
LOG="${HAZARD_LOG:-results/hazard.log}"
exec > >(tee -a "$LOG") 2>&1
status=LỖI
trap 'echo "HẾT $status"' EXIT
echo "=== run_hazard $(date -Is) ==="

# C1a cần đủ 1.583 ảnh test: chờ đủ ảnh hoặc tiến trình tải đã thoát.
N=1583
if [ -z "${SKIP_WAIT:-}" ] && [ -z "${HAZARD_LIMIT:-}" ]; then
  while true; do
    have=$(ls datas/obstacle_dataset/test/img-test/*.jpg 2>/dev/null | wc -l)
    if [ "$have" -ge "$N" ]; then break; fi
    if ! pgrep -f fetch_drive_folder.py >/dev/null; then
      echo "tiến trình tải đã thoát nhưng mới có $have/$N ảnh"; exit 1
    fi
    echo "chờ ảnh: $have/$N"; sleep 60
  done
fi

ARGS=()
[ -n "${HAZARD_LIMIT:-}" ] && ARGS+=(--limit "$HAZARD_LIMIT")
OUTARG=()
[ -n "${HAZARD_OUT:-}" ] && OUTARG+=(--out "$HAZARD_OUT")

echo "--- kiểm nhanh bàn đo (pytest)"
"$PY" -m pytest bench/test_hazard.py -q
echo "--- C1a phát hiện"
"$PY" -m bench.hazard_detect "${ARGS[@]}" "${OUTARG[@]}"
echo "--- C1c độ trễ"
"$PY" -m bench.hazard_latency "${ARGS[@]}" "${OUTARG[@]}"
echo "--- C1b logic"
"$PY" -m bench.hazard_logic --seeds "${HAZARD_SEEDS:-50}" "${OUTARG[@]}"
echo "--- report"
REP=()
[ -n "${HAZARD_OUT:-}" ] && REP+=(--dir "$HAZARD_OUT" --any)
[ -n "${HAZARD_REPORT:-}" ] && REP+=(--out "$HAZARD_REPORT")
"$PY" -m bench.report_hazard "${REP[@]}"
status=ok
