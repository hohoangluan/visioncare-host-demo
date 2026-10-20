#!/usr/bin/env bash
# Tải tập TEST của Obstacle-Dataset (Tang et al., UAIS 2021) từ Drive công khai — chỉ phần cần cho benchmark.
# Chạy lại được (bỏ qua file đã có). Log: datas/obstacle_fetch.log; lỗi chi tiết: datas/obstacle_fetch.err
cd "$(dirname "$0")"
D=datas/obstacle_dataset/test
LOG=datas/obstacle_fetch.log
echo "[$(date '+%F %T')] bắt đầu" >> $LOG
python3 fetch_drive_folder.py 1E7ej0QCrSgr3KW-kSA8dZeyx28qXGXkS $D/label-test >> $LOG 2>>datas/obstacle_fetch.err
python3 fetch_drive_folder.py 1l5i0LCyEeVyzVYuZWJ-LnbJ1bvKAbAQO $D/ann-test   >> $LOG 2>>datas/obstacle_fetch.err
python3 fetch_drive_folder.py 1EIUqtUC1QJ_77jAg0TOUSt71OmcQr8VQ $D/img-test   >> $LOG 2>>datas/obstacle_fetch.err
for s in label-test ann-test img-test; do echo "$s $(ls $D/$s | grep -vc '\.part$') file, $(du -sh $D/$s | cut -f1)" >> $LOG; done
echo "[$(date '+%F %T')] HẾT" >> $LOG
