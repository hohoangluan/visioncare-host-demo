"""C1e — sai số khoảng cách Z của kính (hazard_geom.estimate) so với depth stereo HEADS-UP [Haghighi et al., arXiv:2409.20324].

Đầu vào: hộp người YOLOv8 thật trong vùng cắt kính (66° HFOV 4:3, chuẩn hoá), camera danh nghĩa của kính (320×240, 66°, cao 1,6 m).
Đáp án: Z_thật = toạ độ dọc trục quang học của tâm người (depth stereo ZED Mini, sai < 4 % tới 15 m theo bài báo), 1 m < Z < 15 m.
Sai số tương đối e = (Z_ước − Z_thật) / Z_thật. Báo: trung vị e (thiên lệch), trung vị |e|, p90 |e|, theo nguồn ước lượng và theo dải Z.
Hai cách lấy góc chúc: 0 (giả định nhìn thẳng) và góc chúc tracker tự học (PredictTracker._learn_pitch, như khi chạy thật).

Dùng (từ evaluations/, SEEVIA_VH_DIR=.../vh-od): python -m bench.heads_up_depth
"""

import collections
import json
import os
import time

import numpy as np

from bench import heads_up_eval as he
from live import hazard, hazard_geom, hazard_predict

BINS = [(1, 3), (3, 6), (6, 10), (10, 15)]


def collect(seq: str, cam) -> list[tuple]:
    d = he.load(seq)
    tr = hazard_predict.PredictTracker(hazard_predict.PredictParams(), cam)
    fs = he.sample_frames(sorted(d["poses"]))
    rows = []
    for f in fs:
        o, R = d["poses"][f]
        dets, zs = [], []
        for ob in d["objs"].get(f, []):
            box = he.crop_box(ob["bbox"])
            if box is None:
                continue
            zt = float((R.T @ (np.array([ob["x"], ob["y"], ob["z"]]) - o))[2])
            dets.append(hazard.Detection("person", "person", 0.9, box))
            zs.append(zt)
        for det, zt in zip(dets, zs):
            if 1.0 < zt < 15.0:
                e0 = hazard_geom.estimate(det, cam, 0.0)
                e1 = hazard_geom.estimate(det, cam, tr.pitch_rad)
                rows.append((seq, zt, e0.source, e0.z_m, e1.z_m, e0.z_width))
        tr._learn_pitch(dets)  # góc chúc học từ khung này, dùng cho khung sau (như PredictTracker.assess)
    return rows


def stats(e: np.ndarray) -> dict:
    e = e[np.isfinite(e)]
    if not len(e):
        return {"n": 0}
    return {"n": int(len(e)), "bias_med": float(np.median(e)), "abs_med": float(np.median(np.abs(e))),
            "abs_p90": float(np.percentile(np.abs(e), 90)), "within_20pct": float(np.mean(np.abs(e) <= 0.2))}


def main() -> None:
    cam = hazard_geom.Camera(320, 240, 66.0, 1.6)
    rows = []
    for seq in he.SEQS:
        rows += collect(seq, cam)
    res = {"meta": {"source": "HEADS-UP (Haghighi et al., arXiv:2409.20324, 2024)", "camera": [320, 240, 66.0, 1.6]}, "groups": {}}
    zt = np.array([r[1] for r in rows])
    src = np.array([r[2] for r in rows])
    for key, idx in [("pitch0", 3), ("pitch_hoc", 4)]:
        zu = np.array([np.nan if r[idx] is None else r[idx] for r in rows], float)
        clip = src == "clipped"
        zu[clip] = np.array([r[5] for r in rows], float)[clip]   # hộp cắt đáy: Z theo bề rộng (như track mới)
        e = (zu - zt) / zt
        g = {"all": stats(e)}
        for s in sorted(set(src)):
            g[f"src_{s}"] = stats(e[src == s])
        for lo, hi in BINS:
            g[f"Z_{lo}-{hi}m"] = stats(e[(zt >= lo) & (zt < hi)])
        for seq in he.SEQS:
            g[f"seq_{seq}"] = stats(e[np.array([r[0] for r in rows]) == seq])
        res["groups"][key] = g
        print(f"## góc chúc {key}")
        for k, v in g.items():
            if v.get("n"):
                print(f"  {k:22s} n={v['n']:5d} lệch TV {100 * v['bias_med']:+6.1f} %  |e| TV {100 * v['abs_med']:5.1f} %  "
                      f"p90 {100 * v['abs_p90']:5.1f} %  trong ±20 %: {100 * v['within_20pct']:5.1f} %")
    print("nguồn:", dict(collections.Counter(src)))
    os.makedirs("results/heads_up", exist_ok=True)
    p = f"results/heads_up/depth_{time.strftime('%Y%m%d-%H%M')}.json"
    json.dump(res, open(p, "w"), ensure_ascii=False, indent=1)
    print("ghi", p)


if __name__ == "__main__":
    main()
