#!/usr/bin/env bash
# Tải tập TRAIN + VAL của Obstacle-Dataset (Tang et al., UAIS 2021) để fine-tune (H8) và chọn ngưỡng trên val.
# Chạy lại được (bỏ qua file đã có). Log: datas/obstacle_trainval.log; lỗi: datas/obstacle_trainval.err
cd "$(dirname "$0")"
D=datas/obstacle_dataset
LOG=datas/obstacle_trainval.log
echo "[$(date '+%F %T')] bắt đầu" >> $LOG
f() { python3 fetch_drive_folder.py "$1" "$D/$2" >> $LOG 2>>datas/obstacle_trainval.err; }
f 1kyDA3gVX0sgNFv--Xr5wJ0CciXHJTs6Z val/ann-val
f 1E2ROHlPdR8zHPJRu4ZndhhUotKiqDUmo val/label-val
f 1EEdC4DegVxSEjty3OlC2-ltwpN7Q1FzM val/img-val
f 1l1XEHq5O4_DlzMeEWEUtk8iK-QWgCU0Z train/ann-train
f 1E2bjG_80BX9KGkcleKimpmgC8WqlgOvf train/label-train
f 1EGt00-9I5iFbvkQ2ZSTzArWS-O5NbkLU train/img-train
for s in val/ann-val val/label-val val/img-val train/ann-train train/label-train train/img-train; do
  echo "$s $(ls $D/$s | grep -vc '\.part$') file, $(du -sh $D/$s | cut -f1)" >> $LOG; done
echo "[$(date '+%F %T')] HẾT" >> $LOG
