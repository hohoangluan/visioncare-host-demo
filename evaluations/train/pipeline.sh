#!/usr/bin/env bash
# Pipeline nền cải tiến model vật cản (PLAN_cai-tien-ai V1–V3). Chạy tách khỏi session:
#   cd evaluations && setsid nohup bash train/pipeline.sh > /dev/null 2>&1 &
# Chạy lại được: bước nào có train/state/<bước>.done thì bỏ qua; train tự resume từ last.pt, OOM thì đổi GPU trống.
# Log: train/pipeline.log (dòng cuối "HẾT ok" / "HẾT LỖI"). Báo cáo: reports/HAZARD_MODELS.md (sinh lại sau mỗi bước đo).
set -uo pipefail
cd "$(dirname "$0")/.."            # evaluations/
EV=$PWD; T=$EV/train; ST=$T/state; R=$EV/results/hazard_models
mkdir -p "$ST" "$T/models" "$T/weights" "$R"
exec >>"$T/pipeline.log" 2>&1
PYS=$HOME/.venvs/seevia/bin/python
PYY=$HOME/.venvs/yolo/bin/python
CLS=$T/classes_vh.json
BASE_DETECT=$EV/results/hazard/20261020-2045_detect.json

say()  { echo "[$(date '+%F %T')] $*"; }
done_() { [ -f "$ST/$1.done" ]; }
mark() { touch "$ST/$1.done"; say "XONG $1"; }
die()  { say "LỖI: $*"; echo "HẾT LỖI"; exit 1; }
pick_gpu() { (unset CUDA_VISIBLE_DEVICES; "$PYS" -c "from bench import common; print(common.pick_gpu())"); }
report() { "$PYS" -m bench.hazard_models report || say "cảnh báo: sinh báo cáo lỗi"; }

say "=== pipeline bắt đầu (pid $$) ==="

# 1. Dữ liệu train/val (Drive, tải tiếp được) -------------------------------------------------------------
if ! done_ data; then
  for attempt in 1 2 3; do
    ./fetch_obstacle_trainval.sh
    ok=1
    for d in val/img-val val/ann-val train/img-train train/ann-train; do
      name=$(basename "$d")
      want=$(grep -E "^$name: [0-9]+ file trong thư mục Drive" datas/obstacle_trainval.log | tail -1 | awk '{print $2}')
      have=$(ls "datas/obstacle_dataset/$d" 2>/dev/null | grep -vc '\.part$')
      say "$d: $have / ${want:-?}"
      { [ -n "$want" ] && [ "$have" -ge "$want" ]; } || ok=0
    done
    [ $ok = 1 ] && break
    sleep 60
  done
  [ $ok = 1 ] || die "tải train/val chưa đủ sau 3 lần (xem datas/obstacle_trainval.err)"
  mark data
fi

# 2. venv riêng ~/.venvs/yolo (KHÔNG đụng ~/.venvs/seevia: cài ultralytics vào đó sẽ hạ cuDNN/cuBLAS của onnxruntime) --
if ! done_ venv; then
  [ -x "$PYY" ] || uv venv -q --python 3.11 "$HOME/.venvs/yolo" || die "tạo venv"
  ok=0
  for cu in cu130 cu128 cu126; do
    uv pip install -q --python "$PYY" --reinstall-package torch --reinstall-package torchvision \
      torch torchvision --index-url "https://download.pytorch.org/whl/$cu" || continue
    if "$PYY" -c "import torch; assert torch.cuda.is_available(); torch.zeros(1).cuda()"; then ok=1; say "torch $cu chạy CUDA"; break; fi
    say "torch $cu không chạy CUDA, thử bản khác"
  done
  [ $ok = 1 ] || die "không có torch chạy được CUDA"
  uv pip install -q --python "$PYY" ultralytics onnx onnxslim || die "cài ultralytics"
  "$PYY" -c "import torch, ultralytics; print('torch', torch.__version__, 'ultralytics', ultralytics.__version__)"
  mark venv
fi

# Model thử (người dùng 2026-10-20: cho lên đời YOLO mới + train trên đó). YOLO26 train trước, YOLO11 để so.
# YOLO26 lỗi (vd ultralytics không có, đầu ra sai định dạng) thì bỏ qua model đó, không dừng pipeline.
VERS="26s 11s 26m 11m"
declare -A BATCH=([26s]=64 [11s]=64 [26m]=32 [11m]=32)

# 3. Trọng số COCO + xuất ONNX tĩnh 320 (V2) ----------------------------------------------------------------
for v in $VERS; do
  done_ "coco_export_$v" && continue
  if (cd "$T/weights" && "$PYY" -c "from ultralytics import YOLO; YOLO('yolo$v.pt')") \
     && "$PYY" "$T/export_onnx.py" --weights "$T/weights/yolo$v.pt" --out "$T/models/coco_${v}_320.onnx" \
     && CUDA_VISIBLE_DEVICES=$(pick_gpu) "$PYS" "$T/check_onnx.py" "$T/models/coco_${v}_320.onnx"; then
    mark "coco_export_$v"
  else
    say "cảnh báo: yolo$v COCO tải/export/kiểm khói lỗi — bỏ qua model này"; touch "$ST/skip_$v"
  fi
done

# Đo một model: detect test + latency test + detect val + chọn ngưỡng trên val. $1=tag $2=onnx|"" (rỗng = production) $3=classes|""
bench_model() {
  local tag=$1 onnx=$2 cls=$3 g
  local envs=()
  [ -n "$onnx" ] && envs+=("HAZARD_MODEL_PATH=$onnx")
  [ -n "$cls" ] && envs+=("HAZARD_CLASSES_JSON=$cls")
  g=$(pick_gpu); say "đo $tag trên GPU $g"
  if [ -n "$onnx" ]; then
    env "${envs[@]}" CUDA_VISIBLE_DEVICES=$g "$PYS" -m bench.hazard_detect --out "$R/$tag/test" || return 1
    env "${envs[@]}" CUDA_VISIBLE_DEVICES=$g "$PYS" -m bench.hazard_latency --out "$R/$tag/test" || return 1
  fi
  env "${envs[@]}" HAZARD_SPLIT=val CUDA_VISIBLE_DEVICES=$g "$PYS" -m bench.hazard_detect --out "$R/$tag/val" || return 1
  local test_json=$BASE_DETECT
  [ -n "$onnx" ] && test_json=$(ls "$R/$tag/test/"*_detect.json | tail -1)
  env "${envs[@]}" CUDA_VISIBLE_DEVICES=$g "$PYS" -m bench.hazard_models threshold \
    --val "$(ls "$R/$tag/val/"*_detect.json | tail -1)" --test "$test_json" --out "$R/$tag" || return 1
}

# 4. Đo V1 (yolo11n production, chỉ đổi ngưỡng) + V2 (yolo11s/m COCO) ---------------------------------------
specs=("coco_n::")
for v in $VERS; do [ -f "$ST/skip_$v" ] || specs+=("coco_$v:$T/models/coco_${v}_320.onnx:"); done
for spec in "${specs[@]}"; do
  IFS=: read -r tag onnx cls <<<"$spec"
  if ! done_ "bench_$tag"; then
    if bench_model "$tag" "$onnx" "$cls"; then mark "bench_$tag"; else say "cảnh báo: đo $tag lỗi (bỏ qua, chạy tiếp)"; fi
    report
  fi
done

# 5. Dựng tập fine-tune (lọc trùng test + nhãn giả 5 lớp COCO) ------------------------------------------------
if ! done_ dataset; then
  (cd "$T/weights" && "$PYY" -c "from ultralytics import YOLO; YOLO('yolo11m.pt')") || die "tải yolo11m (gán nhãn giả)"
  CUDA_VISIBLE_DEVICES=$(pick_gpu) "$PYY" "$T/build_dataset.py" || die "dựng tập"
  mark dataset
fi

# 6. Fine-tune s rồi m; NGAY SAU mỗi lần train: export → kiểm khói → đo đủ → báo cáo ---------------------------
train_one() {  # $1=26s|11s|26m|11m $2=batch
  local size=$1 batch=$2 name=ft_$1 run=$T/runs/ft_$1 g
  for attempt in 1 2 3; do
    g=$(pick_gpu); say "train $name GPU $g (lần $attempt)"
    if [ -f "$run/weights/last.pt" ]; then
      CUDA_VISIBLE_DEVICES=$g "$HOME/.venvs/yolo/bin/yolo" train resume model="$run/weights/last.pt" device=0 && return 0
    else
      CUDA_VISIBLE_DEVICES=$g "$HOME/.venvs/yolo/bin/yolo" train model="$T/weights/yolo$size.pt" data="$T/obstacle.yaml" \
        imgsz=320 epochs=120 patience="${PATIENCE:-25}" batch="$batch" workers=8 seed=0 device=0 plots=False \
        project="$T/runs" name="$name" exist_ok=True && return 0
    fi
    [ -f "$run/weights/best.pt" ] && grep -q "^" "$run/results.csv" 2>/dev/null && \
      [ "$(tail -1 "$run/results.csv" | cut -d, -f1 | tr -d ' ')" = "120" ] && return 0
    say "train $name lỗi, thử lại sau 60 s (đổi GPU)"; sleep 60
  done
  return 1
}
for size in $VERS; do
  [ -f "$ST/skip_$size" ] && { say "bỏ qua train ft_$size (model COCO lỗi ở bước 3)"; continue; }
  batch=${BATCH[$size]}
  if ! done_ "train_$size"; then
    if ! train_one "$size" "$batch" && [ ! -f "$T/runs/ft_$size/weights/best.pt" ]; then
      say "cảnh báo: train ft_$size thất bại — bỏ qua, chạy model kế"; continue
    fi
    mark "train_$size"
  fi
  if ! done_ "export_$size"; then
    if ! { "$PYY" "$T/export_onnx.py" --weights "$T/runs/ft_$size/weights/best.pt" --out "$T/models/ft_${size}_320.onnx" \
           && HAZARD_CLASSES_JSON=$CLS CUDA_VISIBLE_DEVICES=$(pick_gpu) "$PYS" "$T/check_onnx.py" "$T/models/ft_${size}_320.onnx"; }; then
      say "cảnh báo: export/kiểm khói ft_$size lỗi — bỏ qua"; continue
    fi
    mark "export_$size"
  fi
  if ! done_ "bench_ft_$size"; then
    if bench_model "ft_$size" "$T/models/ft_${size}_320.onnx" "$CLS"; then mark "bench_ft_$size"; else say "cảnh báo: đo ft_$size lỗi"; fi
    report
  fi
done

# 7. Kiểm bàn đo vẫn đúng + báo cáo cuối + nhật ký ---------------------------------------------------------
"$PYS" -m pytest bench/test_hazard.py -q || say "cảnh báo: pytest bench/test_hazard.py không xanh"
report
echo "- $(date '+%F %H:%M') — **Pipeline model vật cản xong** (\`evaluations/train/pipeline.sh\`): \`evaluations/reports/HAZARD_MODELS.md\` (V1 ngưỡng, V2 yolo26s/m + yolo11s/m COCO, V3 fine-tune cả 4). Log \`evaluations/train/pipeline.log\`." \
  >> "$EV/../docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md"
echo "HẾT ok"
