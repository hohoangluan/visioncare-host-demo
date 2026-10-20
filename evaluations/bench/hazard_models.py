"""So model vật cản (PLAN_cai-tien-ai V1–V3): chọn ngưỡng trên VAL, áp lên TEST, so ghép đôi với baseline YOLO11n, kiểm ngân sách trễ.

    python -m bench.hazard_models threshold --val results/hazard_models/<tag>/val/X_detect.json \
        --test results/hazard_models/<tag>/test/Y_detect.json --out results/hazard_models/<tag>
    python -m bench.hazard_models report            # -> reports/HAZARD_MODELS.md

Luật chọn ngưỡng (một tham số, chọn trên val — không nhìn test): ngưỡng NHỎ NHẤT trong lưới sao cho precision của detection
trong lối đi (nhóm non_coco, ảnh qua kính) >= precision ở 0,35 − 5 đ.%. Hạ ngưỡng chỉ lọc bớt detection đã có (NMS giữ nguyên
với hộp score >= t, hazard_detect đã kiểm `op_vs_any_mismatch_images` = 0) nên chấm lại từ `dets_any` không cần chạy model.
"""

import argparse
import glob
import json
import os

import numpy as np

from bench import common
from bench import hazard_detect as hd

GRID = [round(x, 3) for x in np.arange(0.05, 0.601, 0.025)]
PREC_DROP = 0.05
BASELINE_DETECT = os.path.join(common.RESULTS, "hazard", "20261020-2045_detect.json")
BASELINE_LATENCY = os.path.join(common.RESULTS, "hazard", "20261020-2045_latency.json")
MODELS_DIR = os.path.join(common.RESULTS, "hazard_models")
TRAIN_DIR = os.path.join(common.EVAL_DIR, "train")
BUDGET_TOTAL_P90 = 10.0
BUDGET_DETECT_DELTA = 5.0


def per_sample(path: str) -> list[dict]:
    return json.load(open(path, encoding="utf-8"))["imgsz"]["320"]["per_sample"]


def at_threshold(images: list[dict], t: float) -> list[dict]:
    out = []
    for im in images:
        ops = {v: [s for s in im["dets_any"][v] if hd.parse_det(s)[1] >= t] for v in hd.VARIANTS}
        out.append({**im, "dets_op": ops})
    return out


def lane_pr(images: list[dict], t: float, variant: str = "glass", group: str = "non_coco") -> dict:
    """Recall GT trong lối (không phân lớp) + precision detection trong lối (tâm ∈ LANE_X, diện tích >= LANE_AREA)."""
    hit = n_gt = tp = n_det = 0
    n_img = 0
    for im in images:
        if group != "all" and im["group"] != group:
            continue
        n_img += 1
        gt = [g for g in im["gt"]]
        gtb = np.array([g["box"] for g in gt]).reshape(-1, 4)
        dets = [d for d in (hd.parse_det(s) for s in im["dets_any"][variant]) if d[1] >= t]
        db = np.array([d[2] for d in dets]).reshape(-1, 4)
        iou = hd.iou_matrix(gtb, db)
        lane_gt = np.array([g["in_lane"] and not g["difficult"] for g in gt], bool)
        if len(gt):
            n_gt += int(lane_gt.sum())
            hit += int(((iou >= hd.IOU).any(axis=1) & lane_gt).sum()) if len(dets) else 0
        for k, b in enumerate(db):
            cx, area = (b[0] + b[2]) / 2, (b[2] - b[0]) * (b[3] - b[1])
            if hd.LANE_X[0] <= cx <= hd.LANE_X[1] and area >= hd.LANE_AREA:
                n_det += 1
                tp += int(len(gt) > 0 and (iou[:, k] >= hd.IOU).any())
    return {"t": t, "recall_inlane": hit / n_gt if n_gt else None, "precision_inlane": tp / n_det if n_det else None,
            "false_inlane_per_image": (n_det - tp) / n_img if n_img else None, "n_gt_inlane": n_gt, "n_det_inlane": n_det}


def cmd_threshold(a) -> None:
    val, test = per_sample(a.val), per_sample(a.test)
    sweep = [lane_pr(val, t) for t in GRID]
    base = lane_pr(val, hd.OP_SCORE)
    ok = [s for s in sweep if s["precision_inlane"] is not None and s["precision_inlane"] >= base["precision_inlane"] - PREC_DROP]
    t_star = min(s["t"] for s in ok) if ok else hd.OP_SCORE
    res = {"rule": f"ngưỡng nhỏ nhất có precision trong lối (val, non_coco, glass) >= precision@{hd.OP_SCORE} − {PREC_DROP}",
           "val_at_0.35": base, "val_sweep": sweep, "t_star": t_star,
           "test_at_0.35": lane_pr(test, hd.OP_SCORE), "test_at_t_star": lane_pr(test, t_star)}
    m, _ = hd.evaluate(at_threshold(test, t_star), with_ap=False)
    res["test_metrics_at_t_star"] = {g: {v: {k: m[g][v][k] for k in ("recall_inlane_agnostic", "precision_op_classaware",
                                                                       "precision_op_agnostic", "detections_per_image_op")}
                                         for v in hd.VARIANTS} for g in ("non_coco", "coco")}
    res["meta"] = common.run_meta({"val": a.val, "test": a.test, "grid": GRID, "prec_drop": PREC_DROP})
    path = common.write_result("hazard_models", "threshold", res, a.out)
    print("ghi", path, "t* =", t_star, "| test@0,35", res["test_at_0.35"], "| test@t*", res["test_at_t_star"])


# ----------------------------------------------------------------------------- báo cáo

def latest(pattern: str) -> str | None:
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def lane_hits(images: list[dict], t: float) -> tuple[list[int], list[int], int]:
    """Cờ trúng của từng hộp GT trong lối (non_coco, glass, không difficult) theo thứ tự cố định -> để ghép đôi."""
    flags, img_idx = [], []
    sel = [im for im in images if im["group"] == "non_coco"]
    for k, im in enumerate(at_threshold(sel, t)):
        s = hd.score_image(im, "glass")
        for j in np.where((~s["diff"]) & s["in_lane"])[0]:
            flags.append(int(s["agn_op"][j])); img_idx.append(k)
    return flags, img_idx, len(sel)


def pct(x) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def ci(d: dict) -> str:
    return f"{100 * d['value']:.1f} % [{100 * d['ci'][0]:.1f}–{100 * d['ci'][1]:.1f}]"


def cmd_report(a) -> None:
    base_imgs = per_sample(BASELINE_DETECT)
    base_flags, base_idx, n_img = lane_hits(base_imgs, hd.OP_SCORE)
    base_lat = json.load(open(BASELINE_LATENCY, encoding="utf-8"))["by_imgsz"]["320"]["latency"]
    # V1 = cùng model production, chỉ đổi ngưỡng: test dùng lại JSON baseline, ngưỡng chọn trên val ở tag coco_n
    rows = [("yolo11n COCO (production)", BASELINE_DETECT, BASELINE_LATENCY,
             latest(os.path.join(MODELS_DIR, "coco_n", "*_threshold.json")))]
    for tag in sorted(os.listdir(MODELS_DIR)) if os.path.isdir(MODELS_DIR) else []:
        d = latest(os.path.join(MODELS_DIR, tag, "test", "*_detect.json"))
        if d:
            rows.append((tag, d, latest(os.path.join(MODELS_DIR, tag, "test", "*_latency.json")),
                         latest(os.path.join(MODELS_DIR, tag, "*_threshold.json"))))
    L = ["# HAZARD_MODELS — so model vật cản (V1 ngưỡng · V2 model COCO lớn hơn · V3 fine-tune)", "",
         "Sinh tự động bởi `bench/hazard_models.py report`. Tập: Obstacle-Dataset **test** (1.583 ảnh); số chính = nhóm **non_coco**, "
         "ảnh **qua kính** (QVGA + JPEG q15), recall@IoU0,5 không phân lớp của hộp GT trong lối đi. Ngưỡng t* chọn trên **val** (không nhìn test). "
         f"Ghép đôi với baseline yolo11n@0,35 trên CÙNG {len(base_flags)} hộp GT (CI của Δ bootstrap theo ảnh). "
         f"Ngân sách trễ: tổng chuỗi server p90 ≤ {BUDGET_TOTAL_P90:.0f} ms và detect p90 ≤ baseline + {BUDGET_DETECT_DELTA:.0f} ms.", "",
         "| Model | Ngưỡng | **Recall trong lối** [CI] | Δ vs baseline [CI Δ] (bắt thêm / mất) | Precision trong lối | Precision đúng lớp | mAP@0,5 (số lớp) | detect p50/p90 ms | tổng chuỗi p90 ms | Trong ngân sách |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    per_cls_rows = []
    for name, dpath, lpath, tpath in rows:
        data = json.load(open(dpath, encoding="utf-8"))
        imgs = data["imgsz"]["320"]["per_sample"]
        m = data["imgsz"]["320"]["metrics"]["non_coco"]["glass"]
        mp = m["mAP50_mapped"]
        lat = json.load(open(lpath, encoding="utf-8"))["by_imgsz"]["320"]["latency"] if lpath else None
        thr = json.load(open(tpath, encoding="utf-8")) if tpath else None
        ts = [hd.OP_SCORE] + ([thr["t_star"]] if thr and thr["t_star"] != hd.OP_SCORE else [])
        for t in ts:
            flags, idx, _ = lane_hits(imgs, t)
            assert len(flags) == len(base_flags), "GT khác nhau giữa hai lượt — không ghép đôi được"
            pc = hd.paired_cluster(base_flags, flags, idx, n_img)
            pr = lane_pr(imgs, t)
            rec = m["recall_inlane_agnostic"] if t == hd.OP_SCORE else \
                hd.evaluate(at_threshold(imgs, t), with_ap=False)[0]["non_coco"]["glass"]["recall_inlane_agnostic"]
            prec_cls = m["precision_op_classaware"]["value"] if t == hd.OP_SCORE else \
                thr["test_metrics_at_t_star"]["non_coco"]["glass"]["precision_op_classaware"]["value"]
            delta = "—" if name.startswith("yolo11n") and t == hd.OP_SCORE else \
                f"{100 * pc['delta']:+.1f} đ.% [{100 * pc['delta_ci_by_image'][0]:+.1f}; {100 * pc['delta_ci_by_image'][1]:+.1f}] ({pc['glass_only']} / {pc['orig_only']})"
            if lat:
                det_p90, tot_p90 = lat["detect"]["p90_ms"], lat["total"]["p90_ms"]
                ok = tot_p90 <= BUDGET_TOTAL_P90 and det_p90 <= base_lat["detect"]["p90_ms"] + BUDGET_DETECT_DELTA
                lat_s, tot_s, ok_s = f"{lat['detect']['p50_ms']} / {det_p90}", f"{tot_p90}", "✅" if ok else "❌"
            else:
                lat_s = tot_s = ok_s = "—"
            mp_s = "—" if mp["map"] is None else f"{mp['map']:.3f} ({mp['n_classes']})"
            L.append(f"| {name} | {t:g}{' (t*, val)' if t != hd.OP_SCORE else ''} | **{ci(rec)}** | {delta} | "
                     f"{pct(pr['precision_inlane'])} | {pct(prec_cls)} | {mp_s} | {lat_s} | {tot_s} | {ok_s} |")
        per_cls_rows.append((name, m["per_class"]))
    L += ["", "Recall trong lối theo lớp (ngưỡng 0,35, non_coco, qua kính) — 6 lớp đầu là lớp NGOÀI COCO:", "",
          "| Model | " + " | ".join(hd.NON_COCO_CLASSES + ["person", "motorbike", "car", "bicycle"]) + " |",
          "|---|" + "---|" * (len(hd.NON_COCO_CLASSES) + 4)]
    for name, pc in per_cls_rows:
        cells = []
        for c in hd.NON_COCO_CLASSES + ["person", "motorbike", "car", "bicycle"]:
            r = pc.get(c, {}).get("recall_inlane_agnostic")
            cells.append("—" if not r or r["value"] != r["value"] else f"{100 * r['value']:.0f} %")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    dd = os.path.join(TRAIN_DIR, "dedup.json")
    if os.path.exists(dd):
        st = json.load(open(dd, encoding="utf-8"))
        L += ["", "## Dữ liệu fine-tune", ""]
        for sp, s in st["splits"].items():
            L.append(f"- **{sp}**: {s['images']} ảnh, bỏ {s['dropped_near_test']} ảnh trùng/gần trùng test (md5 hoặc dHash ≤ {st['dhash_max_bits']} bit), "
                     f"giữ {s['kept']}; hộp theo lớp: {s['boxes_per_class']}; nhãn giả bỏ vì trùng GT: {s['pseudo_skipped_overlap_gt']}"
                     + (f"; thêm {s['glass_copies']} bản 'như kính gửi' (rộng 320, JPEG q{s['glass_jpeg_q'][0]}–{s['glass_jpeg_q'][1]})" if s.get("glass_copies") else "") + ".")
        L.append(f"- 5 lớp COCO SeeVia đang cảnh báo (chair, bench, plant, traffic_light, parking_meter) là **nhãn giả** từ YOLO11m COCO "
                 f"(conf ≥ {st['pseudo_conf']}) — chống quên lớp; không có nhãn thật để chấm các lớp này trên test.")
    for run in sorted(glob.glob(os.path.join(TRAIN_DIR, "runs", "*", "results.csv"))):
        import csv
        r = list(csv.DictReader(open(run)))
        if r:
            key = [k for k in r[0] if k.strip() == "metrics/mAP50(B)"]
            best = max(r, key=lambda x: float(x[key[0]])) if key else r[-1]
            L.append(f"- Huấn luyện `{os.path.basename(os.path.dirname(run))}`: {len(r)} epoch, mAP50 val tốt nhất "
                     f"{float(best[key[0]]):.3f} (epoch {best[[k for k in best if k.strip() == 'epoch'][0]].strip()})." if key else "")
    L += ["", "## Giới hạn", "",
          "- Model fine-tune được huấn luyện trên CHÍNH Obstacle-Dataset (train) → test là **cùng phân phối** (vỉa hè Trung Quốc); "
          "không chứng minh cho vỉa hè Việt Nam. Model COCO thì zero-shot.",
          "- mAP của model COCO tính trên 9 lớp ánh xạ được (8 có GT trong non_coco), model fine-tune trên 15 lớp → **không so mAP chéo**; so bằng recall trong lối (cùng định nghĩa).",
          "- Nhóm ảnh COCO vẫn rò với mọi model (đều khởi từ trọng số COCO) → chỉ trích non_coco.",
          "- Thay model trong VH chỉ sau khi người dùng xem bảng này (cần đổi `HAZARD_MODEL_PATH` + bảng lớp `_CLASSES`)."]
    out = os.path.join(common.REPORTS, "HAZARD_MODELS.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(x for x in L if x is not None) + "\n")
        f.flush(); os.fsync(f.fileno())
    print("ghi", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("threshold"); t.add_argument("--val", required=True); t.add_argument("--test", required=True)
    t.add_argument("--out", required=True)
    sub.add_parser("report")
    a = ap.parse_args()
    cmd_threshold(a) if a.cmd == "threshold" else cmd_report(a)


if __name__ == "__main__":
    main()
