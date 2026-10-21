#!/usr/bin/env bash
# Lượt XÁC NHẬN cuối (2026-10-21) — vật cản. Dùng: run_chot_hazard.sh detect | latency
#   detect : C1a phát hiện trên Obstacle-Dataset test — yolo11n COCO (đang chạy) vs ft_11s_last@0,35 (đề xuất). Không phụ thuộc logic.
#   latency: C1c đường nóng server, HAZARD_LOGIC=area rồi predict, đo liền nhau (cần nhánh od-du-doan đã gộp vào vh-chot).
# C1b (logic) chạy bằng bench.hazard_grid --split test theo kế hoạch Task 6, không ở đây.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-$HOME/.venvs/seevia/bin/python}"
export SEEVIA_VH_DIR="${SEEVIA_VH_DIR:-$(cd .. && pwd)/vh-chot}"
OUT=results/chot/hazard
mkdir -p "$OUT"
LOG="$OUT/chot_hazard_$1.log"
exec > >(tee -a "$LOG") 2>&1
status=LỖI
trap 'echo "HẾT $status"' EXIT
CLS=$PWD/train/classes_vh.json
FT=$PWD/train/models/ft_11s_last_320.onnx
GPU="${GPU:-$(unset CUDA_VISIBLE_DEVICES; "$PY" -c "from bench import common; print(common.pick_gpu())")}"
echo "=== run_chot_hazard $1 $(date -Is) · VH=$SEEVIA_VH_DIR @ $(git -C "$SEEVIA_VH_DIR" rev-parse --short HEAD) · GPU $GPU ==="
uptime; nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader
case "$1" in
  detect)
    echo "--- C1a yolo11n COCO"
    CUDA_VISIBLE_DEVICES=$GPU "$PY" -m bench.hazard_detect --out "$OUT/yolo11n"
    echo "--- C1a ft_11s_last"
    HAZARD_MODEL_PATH=$FT HAZARD_CLASSES_JSON=$CLS CUDA_VISIBLE_DEVICES=$GPU "$PY" -m bench.hazard_detect --out "$OUT/ft_11s_last"
    ;;
  latency)
    for logic in area predict; do
      for m in yolo11n ft_11s_last; do
        echo "--- C1c $m · HAZARD_LOGIC=$logic"
        envs=(HAZARD_LOGIC=$logic CUDA_VISIBLE_DEVICES=$GPU)
        [ "$m" = ft_11s_last ] && envs+=(HAZARD_MODEL_PATH=$FT HAZARD_CLASSES_JSON=$CLS)
        env "${envs[@]}" "$PY" -m bench.hazard_latency --out "$OUT/${m}_$logic"
      done
    done
    ;;
  *) echo "dùng: $0 detect|latency"; exit 2 ;;
esac
status=ok
