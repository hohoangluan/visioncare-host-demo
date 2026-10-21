#!/usr/bin/env bash
# C1b vòng 2 (2026-10-21 tối): bàn đo sửa ego (trượt giữa khung, σ đo trên ảnh thật) + v_conf_k + yaw_tau_s. Tách phiên: setsid nohup
cd "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations"
export SEEVIA_VH_DIR=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/../vh-od
LOG=/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/hazard/c1b_v2/grid_dev.log
mkdir -p $(dirname "$LOG")
echo "=== grid dev v2 $(date -Is) · vh-od @ $(git -C $SEEVIA_VH_DIR rev-parse --short HEAD)+dirty" > "$LOG"
nice -n 5 $HOME/.venvs/seevia/bin/python -m bench.hazard_grid --split dev --procs 24 --seeds 50 --out /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/results/chot/hazard/c1b_v2 >> "$LOG" 2>&1 && echo "HẾT ok" >> "$LOG" || echo "HẾT LỖI" >> "$LOG"
