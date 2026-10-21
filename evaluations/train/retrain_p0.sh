#!/usr/bin/env bash
# Train lại 4 model fine-tune với patience=0 (đủ 120 epoch), MỌI tham số khác giữ như pipeline.sh.
# Lý do (2026-10-21): bản patience=25 cắt ft_11s/26s/26m ở epoch 26 với best = epoch 1 (mAP val sụt sau warmup rồi hồi chậm)
# → so kiến trúc không công bằng. Bản cũ giữ dưới hậu tố _p25 (runs/, models/, results/hazard_models/) để đối chiếu.
# Chạy: cd evaluations && setsid nohup bash train/retrain_p0.sh > /dev/null 2>&1 &
# 4 lượt train song song trên 4 GPU khác nhau; sau đó gọi pipeline.sh để export → kiểm khói → đo (tuần tự, đo trễ khi máy không train).
set -uo pipefail
cd "$(dirname "$0")/.."            # evaluations/
EV=$PWD; T=$EV/train; ST=$T/state; R=$EV/results/hazard_models
exec >>"$T/retrain_p0.log" 2>&1
say() { echo "[$(date '+%F %T')] $*"; }
declare -A BATCH=([26s]=64 [11s]=64 [26m]=32 [11m]=32)
VERS="26s 11s 26m 11m"
say "=== retrain_p0 bắt đầu (pid $$) ==="

# 1. Cất bản patience=25 (một lần; chạy lại script thì bỏ qua) ------------------------------------------------
for v in $VERS; do
  [ -d "$T/runs/ft_${v}_p25" ] && continue
  mv "$T/runs/ft_$v" "$T/runs/ft_${v}_p25"
  mv "$T/models/ft_${v}_320.onnx" "$T/models/ft_${v}_p25_320.onnx"
  mv "$R/ft_$v" "$R/ft_${v}_p25"
  rm -f "$ST/train_$v.done" "$ST/export_$v.done" "$ST/bench_ft_$v.done"
  say "cất bản p25 của ft_$v"
done
[ -f "$EV/reports/HAZARD_MODELS_p25.md" ] || cp "$EV/reports/HAZARD_MODELS.md" "$EV/reports/HAZARD_MODELS_p25.md"

# 2. GPU: lấy 4 GPU ít VRAM nhất lúc khởi động -----------------------------------------------------------------
mapfile -t GPUS < <(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -4 | cut -d, -f1)
say "GPU dùng: ${GPUS[*]}"

train_one() {  # $1=size $2=gpu — resume nếu có last.pt, thử 3 lần (lần sau đổi sang GPU trống nhất lúc đó)
  local size=$1 g=$2 name=ft_$1 run=$T/runs/ft_$1
  for attempt in 1 2 3; do
    say "train $name GPU $g (lần $attempt)"
    if [ -f "$run/weights/last.pt" ]; then
      CUDA_VISIBLE_DEVICES=$g "$HOME/.venvs/yolo/bin/yolo" train resume model="$run/weights/last.pt" device=0 \
        > "$T/retrain_$name.log" 2>&1
    else
      CUDA_VISIBLE_DEVICES=$g "$HOME/.venvs/yolo/bin/yolo" train model="$T/weights/yolo$size.pt" data="$T/obstacle.yaml" \
        imgsz=320 epochs=120 patience=0 batch="${BATCH[$size]}" workers=8 seed=0 device=0 plots=False \
        project="$T/runs" name="$name" exist_ok=True > "$T/retrain_$name.log" 2>&1
    fi
    if [ "$(tail -1 "$run/results.csv" 2>/dev/null | cut -d, -f1 | tr -d ' ')" = "120" ]; then
      touch "$ST/train_$size.done"; say "XONG train_$size (120 epoch)"; return 0
    fi
    say "train $name dừng trước epoch 120, thử lại sau 60 s"; sleep 60
    g=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | sort -t, -k2 -n | head -1 | cut -d, -f1)
  done
  say "LỖI: train $name thất bại sau 3 lần"; return 1
}

i=0; pids=()
for v in $VERS; do
  [ -f "$ST/train_$v.done" ] && continue
  train_one "$v" "${GPUS[$i]}" & pids+=($!); i=$((i + 1)); sleep 20
done
fail=0; for p in "${pids[@]}"; do wait "$p" || fail=1; done
[ $fail = 0 ] || say "cảnh báo: có model train lỗi — pipeline vẫn đo các model còn lại"

# 3. Export + đo + báo cáo: dùng lại pipeline.sh (bước có .done thì bỏ qua) ------------------------------------
say "gọi pipeline.sh để export/đo"
PATIENCE=0 bash "$T/pipeline.sh"
tail -1 "$T/pipeline.log" | grep -q "HẾT ok" && say "HẾT ok" || say "HẾT LỖI (xem train/pipeline.log)"
