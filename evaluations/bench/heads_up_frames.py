"""Trích khung HEADS-UP thành ảnh như kính gửi: chỉ khung 8 fps của bàn đo C1d, cắt 66° HFOV 4:3, thu QVGA 320×240, JPEG q15.

Đọc tuần tự file .tar.gz (không giải nén cả bộ ~20 GB PNG). Ra: datas/heads_up/qvga_<seq>/<frame>.jpg.
Dùng (từ evaluations/): python -m bench.heads_up_frames unconstrained
"""

import os
import sys
import tarfile

import cv2
import numpy as np

from bench import heads_up_eval as he


def main(seq: str) -> None:
    want = set(he.sample_frames(sorted(he.body_frames(he.load(seq)))))
    out = os.path.join(he.DATA, f"qvga_{seq}")
    os.makedirs(out, exist_ok=True)
    x0, y0 = int(round(he.CROP[0])), int(round(he.CROP[1]))
    w, h = int(round(he.CROP_W)), int(round(he.CROP_H))
    n = bad = skip = 0
    with tarfile.open(os.path.join(he.DATA, f"rgb_{seq}.tar.gz"), "r|gz") as tf:
        for m in tf:
            if not m.isfile() or not m.name.endswith(".png"):
                continue
            f = int(os.path.basename(m.name).split("_")[-1].split(".")[0])
            if f not in want:
                continue
            dst = os.path.join(out, f"{f:08d}.jpg")
            if os.path.exists(dst):  # chạy lại: giữ khung đã trích
                n, skip = n + 1, skip + 1
                continue
            fh = tf.extractfile(m)
            img = None if fh is None else cv2.imdecode(np.frombuffer(fh.read(), np.uint8), cv2.IMREAD_COLOR)
            if img is None:  # PNG hỏng trong bộ dữ liệu: bỏ, đếm (bàn đo coi như khung không đo được ego)
                bad += 1
                print(f"PNG hỏng: {m.name}", flush=True)
                continue
            crop = img[max(y0, 0):y0 + h, max(x0, 0):x0 + w]
            small = cv2.resize(crop, (320, 240), interpolation=cv2.INTER_AREA)
            cv2.imwrite(dst, small, [cv2.IMWRITE_JPEG_QUALITY, 15])
            n += 1
            if n % 500 == 0:
                print(f"{n}/{len(want)}", flush=True)
    print(f"HẾT ok {n}/{len(want)} khung (giữ lại {skip}, PNG hỏng {bad}) -> {out}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
