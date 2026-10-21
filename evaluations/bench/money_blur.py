"""Ngưỡng độ nét MONEY_BLUR_HINT cho câu "Giữ yên tay." (đọc tiền v2, spec 2026-10-21-doc-tien-3-khung-design §3).

Chọn trên DEV (không đụng test): độ nét tính bằng đúng hàm production `pipeline/image_quality.measure`
(Laplacian 3x3, ảnh JPEG q90 cỡ gốc 192x144 như bench) trên khung đầu `frames[0]` của mỗi ảnh dev mà lượt 1 khung
đọc ĐÚNG ở τ 0,999 (read_money.say). Ngưỡng = phân vị 25 % của các độ nét đó.

python -m bench.money_blur [--results results/money_vnd/20261021-1454_multi_dev.json] [--tau 0.999] [--pct 25]
"""

import argparse
import json
import os

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402
from bench import money_vnd  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(common.ROOT if hasattr(common, "ROOT") else ".", "results", "money_vnd",
                                                      "20261021-1454_multi_dev.json"))
    ap.add_argument("--tau", type=float, default=0.999)
    ap.add_argument("--pct", type=float, default=25.0)
    args = ap.parse_args()

    from handlers import read_money
    from pipeline import image_quality

    data = json.load(open(args.results))
    right, wrong, refused = [], [], []
    for row in data["per_sample"]:
        if row["gt"] == 0:
            continue
        first = row["frames"][0]
        if first.get("error"):
            continue
        with open(os.path.join(money_vnd.ROOT, row["key"]), "rb") as f:
            measured = image_quality.measure(L.to_jpeg(f.read(), quality=90))
        sharp = measured[0]
        said = read_money.LABELS.get(read_money.say(first["label"], first["prob"], args.tau))
        (right if said == row["gt"] else refused if said is None else wrong).append(sharp)
    for name, xs in (("đọc đúng", right), ("nói sai", wrong), ("từ chối", refused)):
        if xs:
            print(f"{name:9} n={len(xs):3} trung vị {np.median(xs):7.1f}  p10 {np.percentile(xs, 10):7.1f}  p25 {np.percentile(xs, 25):7.1f}")
    thr = float(np.percentile(right, args.pct))
    print(f"MONEY_BLUR_HINT = phân vị {args.pct:g} % của {len(right)} ảnh dev đọc đúng ở τ {args.tau} = {thr:.2f}")
    print(f"  tỉ lệ ảnh bị từ chối có độ nét < ngưỡng: {np.mean(np.array(refused) < thr):.2%} ({len(refused)} ảnh)")


if __name__ == "__main__":
    main()
