#!/usr/bin/env bash
# C1b lưới dev đầy đủ (Task 6 bước 1) — tách khỏi phiên Claude: setsid nohup bash run_chot_grid_dev.sh &
cd "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations"
export SEEVIA_VH_DIR=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-od
LOG=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/hazard/c1b/grid_dev.log
echo "=== grid dev $(date -Is) · vh-od @ $(git -C $SEEVIA_VH_DIR rev-parse --short HEAD)" > "$LOG"
nice -n 5 $HOME/.venvs/seevia/bin/python -m bench.hazard_grid --split dev --procs 8 --seeds 50 --out /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/hazard/c1b >> "$LOG" 2>&1 && echo "HẾT ok" >> "$LOG" || echo "HẾT LỖI" >> "$LOG"
