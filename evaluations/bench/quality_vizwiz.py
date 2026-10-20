"""C5 — cổng chất lượng ảnh (`pipeline.image_quality`) trên VizWiz-QualityIssues val (METRICS.md C5).

    python -m bench.quality_vizwiz [--limit N] [--out DIR]

Nhãn dương = >= 3/5 người gán. Dự đoán lấy từ `check()` thật (ngưỡng `config.IMAGE_*`):
  TỐI<->DRK, CHÓI<->BRT, MỜ<->BLR. intent không-money: need_sharpness=False; money: True.
Metric chính: tỉ lệ chụp lại OAN = bị từ chối mà đa số người gán nói KHÔNG có lỗi tương ứng.
"""
import argparse
import warnings
import json
import os
import sys
import time

from bench import common

common.setup(gpu=False)  # production chạy CPU (numpy+PIL) — không có gì để đặt lên GPU

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from pipeline import image_quality as iq  # noqa: E402  (VH, chỉ đọc)
import config  # noqa: E402

FLAWS = ("DRK", "BRT", "BLR")
REASON_FLAW = {iq._TOO_DARK: "DRK", iq._TOO_BRIGHT: "BRT", iq._TOO_BLURRY: "BLR"}
POS_MIN = 3  # >= 3/5 người
warnings.filterwarnings("ignore", message="All-NaN slice")


def prf(arr) -> np.ndarray:
    """arr: (n,2) cột [dự đoán, nhãn] -> (precision, recall, f1)."""
    pred, lab = arr[:, 0] > 0, arr[:, 1] > 0
    tp = float((pred & lab).sum())
    p = tp / pred.sum() if pred.sum() else float("nan")
    r = tp / lab.sum() if lab.sum() else float("nan")
    if p != p or r != r:
        f = float("nan")
    else:
        f = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return np.array([p, r, f])


def ci_prf(pred, lab) -> dict:
    arr = np.stack([np.asarray(pred, float), np.asarray(lab, float)], 1)
    out = {}
    for k, name in enumerate(("precision", "recall", "f1")):
        v, lo, hi = common.bootstrap_ci(arr, stat=lambda a, k=k: prf(a)[k])
        out[name] = {"value": v, "ci": [lo, hi]}
    out["n_pos"] = int(np.sum(lab)); out["n_pred_pos"] = int(np.sum(pred)); out["n"] = int(len(lab))
    return out


def ci_mean(x) -> dict:
    v, lo, hi = common.bootstrap_ci(np.asarray(x, float))
    return {"value": v, "ci": [lo, hi], "k": int(np.sum(x)), "n": int(len(x))}


def auroc(score, lab) -> dict:
    s, y = np.asarray(score, float), np.asarray(lab, float)
    if y.sum() == 0 or y.sum() == len(y):
        return {"value": float("nan"), "ci": [float("nan")] * 2, "n_pos": int(y.sum())}
    arr = np.stack([s, y], 1)

    def stat(a):
        return roc_auc_score(a[:, 1], a[:, 0]) if 0 < a[:, 1].sum() < len(a) else float("nan")

    v, lo, hi = common.bootstrap_ci(arr, stat=stat)
    return {"value": v, "ci": [lo, hi], "n_pos": int(y.sum())}


def best_threshold(x, lab, kind: str) -> float:
    """Ngưỡng tối đa hoá F1. kind: 'lt' (dự đoán dương khi x < t) hoặc 'gt'."""
    x, lab = np.asarray(x, float), np.asarray(lab) > 0
    cands = np.unique(np.quantile(x, np.linspace(0.001, 0.999, 600)))
    best, bt = -1.0, float(cands[0])
    for t in cands:
        pred = x < t if kind == "lt" else x > t
        f = prf(np.stack([pred, lab], 1).astype(float))[2]
        if f == f and f > best:
            best, bt = f, float(t)
    return bt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ann = json.load(open(os.path.join(common.DATAS, "vizwiz", "quality", "val.json"), encoding="utf-8"))
    ann = common.sample(ann, args.limit)  # None -> tất cả (thứ tự gốc)
    img_dir = os.path.join(common.DATAS, "vizwiz", "val")

    # warm-up (không tính giờ): nạp PIL/numpy
    for a in ann[:20]:
        iq.measure(open(os.path.join(img_dir, a["image"]), "rb").read())

    rows, lat = [], []
    for a in ann:
        raw = open(os.path.join(img_dir, a["image"]), "rb").read()
        t0 = time.perf_counter()
        m = iq.measure(raw)
        ms = (time.perf_counter() - t0) * 1000
        with Image.open(os.path.join(img_dir, a["image"])) as im:
            w, h = im.size
        row = {"image": a["image"], "w": w, "h": h, "bytes": len(raw), "flaws": a["flaws"],
               "unrecognizable": a["unrecognizable"], "measure_ms": ms}
        if m is None:
            row.update(sharpness=None, brightness=None, reject_nomoney=None, reject_money=None)
        else:
            s, b = m
            row.update(sharpness=s, brightness=b,
                       reject_nomoney=REASON_FLAW.get(iq.check(s, b, need_sharpness=False)),
                       reject_money=REASON_FLAW.get(iq.check(s, b, need_sharpness=True)))
            lat.append(ms)
        rows.append(row)

    ok = [r for r in rows if r["sharpness"] is not None]
    sharp = np.array([r["sharpness"] for r in ok]); bright = np.array([r["brightness"] for r in ok])
    lab = {f: np.array([r["flaws"][f] >= POS_MIN for r in ok]) for f in FLAWS}
    unrec = np.array([r["unrecognizable"] >= POS_MIN for r in ok])
    pred_cur = {"DRK": bright < config.IMAGE_MIN_BRIGHTNESS, "BRT": bright > config.IMAGE_MAX_BRIGHTNESS,
                "BLR": sharp < config.IMAGE_MIN_SHARPNESS}

    metrics: dict = {"prf_current_threshold": {}, "wrong_retake": {}, "auroc": {}, "tuned_halfAB": {}}
    for f in FLAWS:
        metrics["prf_current_threshold"][f] = ci_prf(pred_cur[f], lab[f])

    # Chụp lại OAN. Mỗi ảnh bị từ chối vì lý do R oan nếu nhãn đa số của R = 0.
    for intent, key in (("nomoney", "reject_nomoney"), ("money", "reject_money")):
        reasons = [r[key] for r in ok]
        rejected = np.array([x is not None for x in reasons])
        wrong = np.array([x is not None and not lab[x][i] for i, x in enumerate(reasons)])
        rej_unusable_ok = np.array([x is not None and not unrec[i] for i, x in enumerate(reasons)])
        metrics["wrong_retake"][intent] = {
            "reject_rate": ci_mean(rejected),
            "wrong_rate_over_all_images": ci_mean(wrong),  # METRIC CHÍNH
            "wrong_share_of_rejections": (float(wrong.sum() / rejected.sum()) if rejected.sum() else None),
            "reject_but_not_unrecognizable_rate": ci_mean(rej_unusable_ok),
            "by_reason": {f: int(sum(1 for x in reasons if x == f)) for f in FLAWS},
            "wrong_by_reason": {f: int(sum(1 for i, x in enumerate(reasons) if x == f and not lab[f][i])) for f in FLAWS},
        }

    # AUROC: điểm càng "xấu" càng cao
    metrics["auroc"] = {
        "brightness_vs_DRK": auroc(-bright, lab["DRK"]),
        "brightness_vs_BRT": auroc(bright, lab["BRT"]),
        "sharpness_vs_BLR": auroc(-sharp, lab["BLR"]),
        "sharpness_vs_unrecognizable": auroc(-sharp, unrec),
    }
    # Recall ảnh "unrecognizable" (vô dụng thật) bị cổng bắt
    for intent, key in (("nomoney", "reject_nomoney"), ("money", "reject_money")):
        caught = np.array([r[key] is not None for r in ok])
        metrics.setdefault("unrecognizable_recall", {})[intent] = ci_prf(caught, unrec)["recall"] | {"n_pos": int(unrec.sum())}

    # Ngưỡng tối ưu F1 chọn trên nửa A (seed 0), báo trên nửa B
    perm = np.random.default_rng(0).permutation(len(ok))
    A, B = perm[: len(ok) // 2], perm[len(ok) // 2:]
    feat = {"DRK": (bright, "lt", config.IMAGE_MIN_BRIGHTNESS), "BRT": (bright, "gt", config.IMAGE_MAX_BRIGHTNESS),
            "BLR": (sharp, "lt", config.IMAGE_MIN_SHARPNESS)}
    for f, (x, kind, cur) in feat.items():
        t = best_threshold(x[A], lab[f][A], kind)
        pb = (x[B] < t) if kind == "lt" else (x[B] > t)
        pc = (x[B] < cur) if kind == "lt" else (x[B] > cur)
        metrics["tuned_halfAB"][f] = {
            "threshold_tuned_on_A": t, "threshold_current": cur, "n_A": int(len(A)), "n_B": int(len(B)),
            "on_B_tuned": ci_prf(pb, lab[f][B]), "on_B_current": ci_prf(pc, lab[f][B]),
            "paired_f1_note": "xem on_B_tuned vs on_B_current; CI không chồng nhau mới tin"}

    sizes = np.array([(r["w"], r["h"]) for r in rows])
    cfg = {"limit": args.limit, "pos_min": POS_MIN, "min_brightness": config.IMAGE_MIN_BRIGHTNESS,
           "max_brightness": config.IMAGE_MAX_BRIGHTNESS, "min_sharpness": config.IMAGE_MIN_SHARPNESS,
           "device": "CPU (numpy+PIL, như production)", "n_images": len(rows), "n_measure_none": len(rows) - len(ok)}
    payload = {
        "meta": common.run_meta(cfg),
        "metrics": metrics,
        "latency": {"measure": common.latency_summary(lat),
                    "image_size_median_wh": [int(np.median(sizes[:, 0])), int(np.median(sizes[:, 1]))],
                    "image_bytes_median": int(np.median([r["bytes"] for r in rows])),
                    "note": "đo ở ĐỘ PHÂN GIẢI GỐC của VizWiz, không phải 1600x1200 của kính"},
        "per_sample": rows,
    }
    path = common.write_result("quality_vizwiz", "full" if args.limit is None else f"limit{args.limit}", payload, args.out)
    print("ghi", path)
    w = metrics["wrong_retake"]
    print(f"n={len(rows)} oan(nomoney)={w['nomoney']['wrong_rate_over_all_images']['value']:.4f} "
          f"oan(money)={w['money']['wrong_rate_over_all_images']['value']:.4f} "
          f"measure p50={payload['latency']['measure'].get('p50_ms')} ms")


if __name__ == "__main__":
    sys.exit(main())
