#!/usr/bin/env bash
# Gói Q: C5 (chất lượng ảnh VizWiz) + C6 (STT VIVOS) + báo cáo. Chạy từ evaluations/. KHÔNG tự chạy trong lúc dev.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-$HOME/.venvs/seevia/bin/python}"
mkdir -p results
LOG=results/quick.log
exec > >(tee -a "$LOG") 2>&1
trap 'rc=$?; if [ $rc -eq 0 ]; then echo "HẾT ok"; else echo "HẾT LỖI ($rc)"; fi' EXIT
echo "=== run_quick.sh $(date -Is) ==="
echo "--- C5 quality_vizwiz (7.750 ảnh, CPU)"
"$PY" -m bench.quality_vizwiz
echo "--- C6 stt_vivos (760 câu, CPU, production: beam+hotword)"
"$PY" -m bench.stt_vivos
echo "--- C6 stt_vivos tham chiếu greedy_search (cùng tập)"
"$PY" -m bench.stt_vivos --decoding greedy_search
echo "--- báo cáo"
"$PY" -m bench.report_quick
