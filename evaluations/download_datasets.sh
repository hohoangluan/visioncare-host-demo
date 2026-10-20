#!/usr/bin/env bash
# Tải các bộ dữ liệu công khai cho bộ benchmark AI của SeeVia vào evaluations/datas/<bo>/.
# Chạy lại được: bộ nào đã có cờ .done thì bỏ qua; aria2c/gdown tải tiếp khi đứt.
# Dữ liệu tải về là dữ liệu NGOÀI: chỉ giải nén, không chạy bất kỳ script nào bên trong.
# Nguồn + điều khoản: evaluations/datas/SOURCES.md (cập nhật sau mỗi bộ).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)/datas"
LOG="$ROOT/download.log"
mkdir -p "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

record() {  # record <bo> <url> <ghi chú>
  local dir="$ROOT/$1"
  { echo "- **$1** — $(date '+%F') — $2 — $3"
    find "$dir" -maxdepth 1 -type f \( -name '*.zip' -o -name '*.tar.gz' -o -name '*.tar' \) -print0 \
      | xargs -0 -r sha256sum | sed 's#^#    sha256 #'
  } >> "$ROOT/SOURCES.md"
}

fetch() {  # fetch <bo> <url> [tên file]
  local dir="$ROOT/$1" url="$2" out="${3:-$(basename "${2%%\?*}")}"
  mkdir -p "$dir"
  aria2c -q -c -x 8 -s 8 --retry-wait=10 --max-tries=20 -d "$dir" -o "$out" "$url"
}

unpack() {  # unpack <bo>: giải nén mọi zip/tar trong thư mục, không ghi đè
  local dir="$ROOT/$1" f
  for f in "$dir"/*.zip; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in  # VizWiz: hai zip cùng tên file val.json -> mỗi zip một thư mục
      vqa_annotations.zip) unzip -q -n "$f" -d "$dir/vqa" ;;
      quality_annotations.zip) unzip -q -n "$f" -d "$dir/quality" ;;
      *) unzip -q -n "$f" -d "$dir" ;;
    esac
  done
  for f in "$dir"/*.tar.gz; do [ -e "$f" ] && tar -xzf "$f" -C "$dir" --skip-old-files; done
}

run() {  # run <bo> <hàm>
  local name="$1" fn="$2"
  if [ -e "$ROOT/$name/.done" ]; then log "$name: đã có, bỏ qua"; return; fi
  log "$name: bắt đầu"
  if "$fn"; then
    touch "$ROOT/$name/.done"
    log "$name: XONG ($(du -sh "$ROOT/$name" | cut -f1))"
  else
    log "$name: LỖI (xem log, chạy lại script để tải tiếp)"
  fi
}

# 1. Obstacle-Dataset (Tang et al., UAIS 2021) — 15 lớp vật cản vỉa hè, VOC + YOLO.
# Thư mục Drive gồm hàng nghìn file lẻ; gdown chỉ lấy 50 file/thư mục → người dùng tải tay bằng trình duyệt
# (Drive tự nén zip) và đặt zip vào datas/obstacle_dataset/. Bước này chỉ giải nén.
dl_obstacle() {
  mkdir -p "$ROOT/obstacle_dataset"
  if ! ls "$ROOT/obstacle_dataset"/*.zip >/dev/null 2>&1; then
    log "obstacle_dataset: chưa có zip — tải tay từ https://drive.google.com/drive/folders/1ksPQTc1BkBljqLqEtIWmXFnkgHWs9Hqv"
    return 1
  fi
  unpack obstacle_dataset
  record obstacle_dataset "https://github.com/TW0521/Obstacle-Dataset (Drive 1ksPQTc1BkBljqLqEtIWmXFnkgHWs9Hqv)" \
    "licence chưa nêu trong repo; có ảnh lấy từ VOC/COCO/TT100K → lọc ảnh COCO khi đo model huấn luyện trên COCO"
}

# 2. VinText (Nguyen et al., CVPR 2021) — bản gốc (x1..y4,TRANSCRIPT).
dl_vintext() {
  mkdir -p "$ROOT/vintext"
  gdown -c -O "$ROOT/vintext/vintext_original.zip" "1UUQhNvzgpZy7zXBFQp0Qox-BBjunZ0ml" >> "$LOG" 2>&1 || return 1
  unpack vintext
  record vintext "https://github.com/VinAIResearch/dict-guided (Drive 1UUQhNvzgpZy7zXBFQp0Qox-BBjunZ0ml)" \
    "CHỈ nghiên cứu/giáo dục, không phân phối lại, phải trích dẫn CVPR 2021"
}

# 3. VizWiz (vizwiz.org) — ảnh val + nhãn VQA, caption, chất lượng ảnh, grounding.
dl_vizwiz() {
  local b="https://vizwiz.cs.colorado.edu/VizWiz_final"
  fetch vizwiz "$b/vqa_data/Annotations.zip" vqa_annotations.zip || return 1
  fetch vizwiz "$b/caption/annotations.zip" caption_annotations.zip || return 1
  fetch vizwiz "$b/image_quality/annotations.zip" quality_annotations.zip || return 1
  fetch vizwiz "$b/VizWiz_grounding/annotations.zip" grounding_annotations.zip || return 1
  fetch vizwiz "$b/VizWiz_grounding/binary_masks_png.zip" grounding_masks.zip || return 1
  fetch vizwiz "$b/VizWiz_grounding/meta_data.zip" grounding_meta.zip || return 1
  fetch vizwiz "$b/images/val.zip" images_val.zip || return 1   # ~3,5 GB
  unpack vizwiz
  record vizwiz "https://vizwiz.org (VizWiz_final: val images, VQA, captions, quality, grounding)" \
    "CC BY 4.0 theo vizwiz.org — kiểm lại trang trước khi trích dẫn"
}

# 4. VIVOS (AILAB-VNUHCM) — ASR tiếng Việt, có tập test chuẩn.
dl_vivos() {
  fetch vivos "https://huggingface.co/datasets/AILAB-VNUHCM/vivos/resolve/main/data/vivos.tar.gz" || return 1
  unpack vivos
  record vivos "https://huggingface.co/datasets/AILAB-VNUHCM/vivos" "CC BY-NC-SA 4.0 (theo thẻ dataset — kiểm lại)"
}

# 5. MC-OCR 2021 (RIVF 2021) — hoá đơn VN chụp điện thoại. Bản sao HF tqhuyen/MC_OCR2021 chỉ có CSV nhãn (đã tải),
# ảnh gốc nằm trên trang thi CodaLab (cần tài khoản) → người dùng tải tay zip ảnh vào datas/mc_ocr2021/. Bước này chỉ giải nén.
dl_mcocr() {
  mkdir -p "$ROOT/mc_ocr2021"
  if ! ls "$ROOT/mc_ocr2021"/*.zip >/dev/null 2>&1; then
    log "mc_ocr2021: chưa có zip ảnh — tải tay từ trang thi CodaLab MC-OCR 2021"
    return 1
  fi
  unpack mc_ocr2021
  record mc_ocr2021 "CodaLab MC-OCR 2021 (tải tay) + nhãn CSV từ huggingface.co/datasets/tqhuyen/MC_OCR2021" \
    "đối chiếu số ảnh với bài MC-OCR 2021 (2.436 hoá đơn) trước khi dùng làm bằng chứng"
}

# 6. ViTextVQA (Nguyen et al., arXiv 2404.10652) — VQA về chữ trong ảnh tiếng Việt (thay MC-OCR cho chế độ "hỏi về chữ").
dl_vitextvqa() {
  huggingface-cli download --repo-type dataset xuandin/ViTextVQA \
    --include "images.zip" "train.json" "dev.json" "test.json" "README.md" \
    --local-dir "$ROOT/vitextvqa" >> "$LOG" 2>&1 || return 1
  unpack vitextvqa
  record vitextvqa "https://huggingface.co/datasets/xuandin/ViTextVQA (bản đăng lại; bài gốc arXiv 2404.10652)" \
    "licence không ghi trên thẻ HF — chỉ dùng đánh giá, trích dẫn bài gốc; đối chiếu số ảnh/QA với bài"
}

# 7. SROIE (ICDAR 2019 Robust Reading Challenge) — hoá đơn, trích trường company/date/address/total (chấm đúng số).
dl_sroie() {
  huggingface-cli download --repo-type dataset jsdnrs/ICDAR2019-SROIE \
    --local-dir "$ROOT/sroie" >> "$LOG" 2>&1 || return 1
  record sroie "https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE (bản đăng lại ICDAR 2019 SROIE)" \
    "CC BY 4.0 theo thẻ HF; trích dẫn Huang et al., ICDAR 2019; 626 train / 361 test (parquet)"
}

log "===== bắt đầu lượt tải ====="
[ -e "$ROOT/SOURCES.md" ] || printf '# Nguồn dữ liệu đã tải\n\nMỗi dòng: bộ — ngày tải — nguồn — điều khoản. Dữ liệu ngoài, không commit vào git.\n\n' > "$ROOT/SOURCES.md"
run obstacle_dataset dl_obstacle
run vintext dl_vintext
run vivos dl_vivos
run mc_ocr2021 dl_mcocr
run vizwiz dl_vizwiz
run sroie dl_sroie
run vitextvqa dl_vitextvqa
log "===== hết lượt ====="
du -sh "$ROOT"/* 2>/dev/null | tee -a "$LOG"
