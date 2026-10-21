#!/usr/bin/env bash
# Bước A (2026-10-21): đo `last.pt` (epoch 120) thay vì `best.pt` của 4 model fine-tune.
# Lý do: retrain patience=0 vẫn cho best.pt = epoch 1 ở ft_11s/26s/26m — tiêu chí fitness của Ultralytics (mAP val, có 5 lớp
# nhãn giả do chính YOLO COCO gán) thưởng cho model CHƯA học. Ở đây đo thẳng bằng metric của mình (recall vật trong lối, ảnh qua kính).
# Cùng quy trình với pipeline.sh: export ONNX tĩnh 320 → kiểm khói → detect test + latency + detect val + chọn ngưỡng trên val.
# Chạy: cd evaluations && setsid nohup bash train/bench_last.sh > /dev/null 2>&1 &   — log train/bench_last.log, dòng cuối HẾT ok/LỖI
set -uo pipefail
cd "$(dirname "$0")/.."            # evaluations/
EV=$PWD; T=$EV/train; R=$EV/results/hazard_models
PYS=$HOME/.venvs/seevia/bin/python; PYY=$HOME/.venvs/yolo/bin/python
CLS=$T/classes_vh.json
exec >>"$T/bench_last.log" 2>&1
say() { echo "[$(date '+%F %T')] $*"; }
pick_gpu() { (unset CUDA_VISIBLE_DEVICES; "$PYS" -c "from bench import common; print(common.pick_gpu())"); }

# Không tranh ghi HAZARD_MODELS.md với retrain_p0.sh đang chạy bước cuối
until tail -n 1 "$T/retrain_p0.log" | grep -q "HẾT"; do sleep 20; done
say "=== bench_last bắt đầu ==="
fail=0
for v in 11s 26s 26m 11m; do
  tag=ft_${v}_last; onnx=$T/models/${tag}_320.onnx
  if [ ! -f "$onnx" ]; then
    "$PYY" "$T/export_onnx.py" --weights "$T/runs/ft_$v/weights/last.pt" --out "$onnx" \
      && HAZARD_CLASSES_JSON=$CLS CUDA_VISIBLE_DEVICES=$(pick_gpu) "$PYS" "$T/check_onnx.py" "$onnx" \
      || { say "LỖI export/kiểm khói $tag"; fail=1; continue; }
  fi
  g=$(pick_gpu); say "đo $tag trên GPU $g"
  envs=(HAZARD_MODEL_PATH=$onnx HAZARD_CLASSES_JSON=$CLS CUDA_VISIBLE_DEVICES=$g)
  env "${envs[@]}" "$PYS" -m bench.hazard_detect --out "$R/$tag/test" \
    && env "${envs[@]}" "$PYS" -m bench.hazard_latency --out "$R/$tag/test" \
    && env "${envs[@]}" HAZARD_SPLIT=val "$PYS" -m bench.hazard_detect --out "$R/$tag/val" \
    && env "${envs[@]}" "$PYS" -m bench.hazard_models threshold \
         --val "$(ls "$R/$tag/val/"*_detect.json | tail -1)" --test "$(ls "$R/$tag/test/"*_detect.json | tail -1)" --out "$R/$tag" \
    && say "XONG $tag" || { say "LỖI đo $tag"; fail=1; }
done
"$PYS" -m bench.hazard_models report || fail=1
[ $fail = 0 ] && say "HẾT ok" || say "HẾT LỖI"
