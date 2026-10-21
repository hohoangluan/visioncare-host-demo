#!/usr/bin/env bash
# Đo lại độ trễ chuỗi server của mọi model LIỀN NHAU trên CÙNG một GPU (2026-10-21): số trễ trong HAZARD_MODELS.md
# được đo rải rác lúc máy dùng chung bận khác nhau (best/last cùng kiến trúc mà p90 lệch 5 ms). Log train/relatency.log.
set -uo pipefail
cd "$(dirname "$0")/.."
EV=$PWD; T=$EV/train; R=$EV/results/hazard_models; PYS=$HOME/.venvs/seevia/bin/python; CLS=$T/classes_vh.json
exec >>"$T/relatency.log" 2>&1
G=${GPU:-$(nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader,nounits | sort -t, -k2n -k3n | head -1 | cut -d, -f1)}
echo "[$(date '+%F %T')] GPU $G"
for tag in coco_n ft_11s_last ft_26s_last ft_26m_last ft_11m_last ft_11s ft_26s ft_26m ft_11m; do
  envs=(CUDA_VISIBLE_DEVICES=$G)
  [ "$tag" != coco_n ] && envs+=(HAZARD_MODEL_PATH=$T/models/${tag}_320.onnx HAZARD_CLASSES_JSON=$CLS)
  env "${envs[@]}" "$PYS" -m bench.hazard_latency --out "$R/$tag/test" && echo "[$(date '+%F %T')] XONG $tag" || echo "LỖI $tag"
done
"$PYS" -m bench.hazard_models report && echo "HẾT ok" || echo "HẾT LỖI"
