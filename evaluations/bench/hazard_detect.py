"""C1a — Vật cản: phát hiện (METRICS.md §C1a, PLAN Gói H).

Đo đúng đường production: `live.hazard.OnnxYolo.detect` (YOLO11n COCO ONNX, 320 px) trên TẬP TEST Obstacle-Dataset.
- Số chính: recall@IoU0,5 KHÔNG phân lớp của hộp GT trong lối đi, nhóm `non_coco` (ảnh không phải COCO — tránh rò dữ liệu).
- Chuẩn: AP@0,5 kiểu VOC (all-point), theo lớp + mAP trên 9 lớp ánh xạ được COCO->Obstacle.
- Hai biến thể ảnh: `orig` và `glass` (rộng 320 giữ tỉ lệ + JPEG q15).
- Hai lượt detector: vận hành (HAZARD_MIN_SCORE=0,35) và AP (đặt tạm 0,001).

Dùng:  python -m bench.hazard_detect [--limit N] [--out DIR] [--rescore results/hazard/xxx.json]
`--rescore` chấm lại từ `per_sample` đã lưu, không gọi model.
"""

import argparse
import glob
import json
import os
import sys
import time
import warnings
import xml.etree.ElementTree as ET

import numpy as np

from bench import common

warnings.filterwarnings("ignore", message="All-NaN slice")
common.setup()  # TRƯỚC khi import onnxruntime / module VH

import cv2  # noqa: E402

import config  # noqa: E402  (VH)
from live import hazard  # noqa: E402  (VH)

# Đo model khác (PLAN_cai-tien-ai V2/V3): HAZARD_MODEL_PATH (config VH tự đọc từ môi trường) + HAZARD_CLASSES_JSON
# {"<id>": ["kind", "group"]} thay bảng lớp COCO của VH (kind trùng tên lớp Obstacle thì chấm thẳng lớp đó);
# HAZARD_SPLIT=val để chọn tham số trên val. Không đặt gì = như cũ (YOLO11n COCO, test).
CLASSES_JSON = os.environ.get("HAZARD_CLASSES_JSON")
if CLASSES_JSON:
    hazard._CLASSES = {int(k): tuple(v) for k, v in json.load(open(CLASSES_JSON, encoding="utf-8")).items()}
SPLIT = os.environ.get("HAZARD_SPLIT", "test")
TEST_DIR = os.path.join(common.DATAS, "obstacle_dataset", SPLIT)
IMG_DIR = os.path.join(TEST_DIR, f"img-{SPLIT}")
ANN_DIR = os.path.join(TEST_DIR, f"ann-{SPLIT}")

OBSTACLE_CLASSES = ["stop_sign", "person", "bicycle", "bus", "truck", "car", "motorbike", "reflective_cone",
                    "ashcan", "warning_column", "spherical_roadblock", "pole", "dog", "tricycle", "fire_hydrant"]
# VH kind -> lớp Obstacle (9 lớp ánh xạ được). Kind khác (traffic_light, bench, chair, ...) không có lớp tương ứng.
VH_TO_OBS = {"person": "person", "bicycle": "bicycle", "car": "car", "motorbike": "motorbike", "bus": "bus",
             "truck": "truck", "dog": "dog", "stop_sign": "stop_sign", "hydrant": "fire_hydrant"}
if CLASSES_JSON:  # model fine-tune có đủ 15 lớp -> AP/mAP trên cả 15
    VH_TO_OBS = {**VH_TO_OBS, **{c: c for c in OBSTACLE_CLASSES}}
MAPPED = sorted(set(VH_TO_OBS.values()))
NON_COCO_CLASSES = ["reflective_cone", "warning_column", "spherical_roadblock", "ashcan", "pole", "tricycle"]

LANE_X = (0.3, 0.7)    # cùng ngưỡng level_of
LANE_AREA = 0.02       # diện tích chuẩn hoá tối thiểu để thành mức >= 1
OP_SCORE = 0.35
AP_SCORE = 0.001
IOU = 0.5
GLASS_W, GLASS_Q = 320, 15
GROUPS = ("non_coco", "coco", "all")
VARIANTS = ("orig", "glass")


# ----------------------------------------------------------------------------- dữ liệu

def source_of(name: str) -> str:
    """Tên file 8–12 chữ số: 12 = id COCO; 6 = VOC; 7–9 = tác giả tự thu (ghi trong METRICS.md/PLAN)."""
    n = len(os.path.splitext(name)[0])
    if n == 12:
        return "coco"
    if n == 6:
        return "voc"
    return "self"


def group_of(name: str) -> str:
    return "coco" if source_of(name) == "coco" else "non_coco"


def parse_ann(path: str) -> dict:
    """Chỉ đọc <object><name> (bỏ <owner><name>); bỏ tên ngoài 15 lớp. Hộp chuẩn hoá theo <size> trong xml."""
    root = ET.parse(path).getroot()
    W = float(root.findtext("size/width"))
    H = float(root.findtext("size/height"))
    gts, skipped = [], {}
    for obj in root.findall("object"):
        cls = (obj.findtext("name") or "").strip()
        if cls not in OBSTACLE_CLASSES:
            skipped[cls] = skipped.get(cls, 0) + 1
            continue
        bb = obj.find("bndbox")
        x0, y0, x1, y1 = (float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax"))
        box = [max(0.0, x0 / W), max(0.0, y0 / H), min(1.0, x1 / W), min(1.0, y1 / H)]
        cx = (box[0] + box[2]) / 2
        area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        gts.append({"cls": cls, "box": [round(v, 5) for v in box], "difficult": int(obj.findtext("difficult") or 0),
                    "in_lane": bool(LANE_X[0] <= cx <= LANE_X[1] and area >= LANE_AREA)})
    return {"W": W, "H": H, "gt": gts, "skipped": skipped}


def to_glass(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (GLASS_W, max(1, int(round(h * GLASS_W / w)))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, GLASS_Q])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def glass_jpeg(bgr: np.ndarray) -> bytes:
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (GLASS_W, max(1, int(round(h * GLASS_W / w)))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, GLASS_Q])
    assert ok
    return buf.tobytes()


def list_images(limit: int | None) -> list[str]:
    names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(IMG_DIR, "*.jpg")))
    if limit:
        # --limit: mẫu cố định seed, giữ cả hai nhóm (không lấy N ảnh đầu toàn COCO)
        names = sorted(common.sample(names, limit, seed=0))
    return names


def fmt_det(d) -> str:
    return "%s %.5f %.5f %.5f %.5f %.5f" % (d.kind, d.score, *d.box)


def parse_det(s: str):
    p = s.split()
    return p[0], float(p[1]), [float(x) for x in p[2:6]]


# ----------------------------------------------------------------------------- chấm điểm (thuần numpy, từ per_sample)

def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    ix0 = np.maximum(a[:, None, 0], b[None, :, 0]); iy0 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix1 = np.minimum(a[:, None, 2], b[None, :, 2]); iy1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix1 - ix0, 0, None) * np.clip(iy1 - iy0, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + bb[None, :] - inter, 1e-12)


def voc_ap(rec: np.ndarray, prec: np.ndarray) -> float:
    """All-point interpolation (VOC2010+). rec/prec: (..., n) theo thứ tự score giảm dần."""
    z = np.zeros(rec.shape[:-1] + (1,))
    mrec = np.concatenate([z, rec, z + 1], axis=-1)
    mpre = np.concatenate([z, prec, z], axis=-1)
    mpre = np.maximum.accumulate(mpre[..., ::-1], axis=-1)[..., ::-1]
    return np.sum((mrec[..., 1:] - mrec[..., :-1]) * mpre[..., 1:], axis=-1)


def score_image(im: dict, variant: str) -> dict:
    """Mọi thứ cần cho một ảnh/biến thể: hit từng hộp GT + TP/FP từng detection. Không phụ thuộc ảnh khác."""
    gt = im["gt"]
    gtb = np.array([g["box"] for g in gt]).reshape(-1, 4)
    gcls = [g["cls"] for g in gt]
    diff = np.array([g["difficult"] for g in gt], dtype=bool)
    dop = [parse_det(s) for s in im["dets_op"][variant]]
    dany = [parse_det(s) for s in im["dets_any"][variant]]

    def hits(dets):
        """-> (agnostic[n_gt], classaware[n_gt]) : có detection IoU>=0,5 (cùng lớp ánh xạ cho classaware)."""
        if not dets or len(gt) == 0:
            return np.zeros(len(gt), bool), np.zeros(len(gt), bool)
        iou = iou_matrix(gtb, np.array([d[2] for d in dets]))
        agn = (iou >= IOU).any(axis=1)
        same = np.array([[VH_TO_OBS.get(d[0]) == gcls[i] for d in dets] for i in range(len(gt))])
        return agn, ((iou >= IOU) & same).any(axis=1)

    agn_op, cls_op = hits(dop)
    agn_any, _ = hits(dany)

    def tpfp(dets):
        """VOC: theo lớp, score giảm dần; khớp GT 'difficult' thì bỏ qua. Chỉ detection thuộc lớp ánh xạ.
        Trả list (obstacle_class, score, status) status 1=TP 0=FP; bỏ ignore."""
        out = []
        by_cls = {}
        for k, d in enumerate(dets):
            c = VH_TO_OBS.get(d[0])
            if c:
                by_cls.setdefault(c, []).append(k)
        for c, idx in by_cls.items():
            idx.sort(key=lambda k: -dets[k][1])
            gi = [i for i, x in enumerate(gcls) if x == c]
            used = set()
            for k in idx:
                if gi:
                    ious = iou_matrix(np.array([dets[k][2]]), gtb[gi])[0]
                    j = int(ious.argmax())
                    if ious[j] >= IOU:
                        g = gi[j]
                        if diff[g]:
                            continue
                        if g not in used:
                            used.add(g); out.append((c, dets[k][1], 1)); continue
                out.append((c, dets[k][1], 0))
        return out

    def agn_prec(dets):
        """Precision không phân lớp: detection (mọi kind) trùng IoU>=0,5 với GT bất kỳ (kể cả difficult)."""
        if not dets:
            return 0, 0
        if len(gt) == 0:
            return 0, len(dets)
        ok = (iou_matrix(np.array([d[2] for d in dets]), gtb) >= IOU).any(axis=1)
        return int(ok.sum()), int((~ok).sum())

    tf_op, tf_any = tpfp(dop), tpfp(dany)
    return {"agn_op": agn_op, "cls_op": cls_op, "agn_any": agn_any, "diff": diff,
            "gcls": gcls, "in_lane": np.array([g["in_lane"] for g in gt], bool),
            "tf_op": tf_op, "tf_any": tf_any, "aprec_op": agn_prec(dop), "n_det_op": len(dop)}


def _ratio(num_den: np.ndarray) -> float:
    d = num_den[:, 1].sum()
    return float(num_den[:, 0].sum() / d) if d > 0 else float("nan")


def ratio_ci(per_img_nd: np.ndarray) -> dict:
    """per_img_nd: (n_ảnh, 2) = (tử, mẫu) ; CI bootstrap THEO ẢNH của tỉ số gộp."""
    v, lo, hi = common.bootstrap_ci(per_img_nd, stat=_ratio)
    return {"value": v, "ci": [lo, hi], "num": int(per_img_nd[:, 0].sum()), "den": int(per_img_nd[:, 1].sum())}


def ap_boot(per_class: dict, n_img: int, gt_cnt: dict, B: int = 1000, seed: int = 0, chunk: int = 40) -> dict:
    """AP và mAP + CI bootstrap theo ảnh bằng trọng số (mỗi lần lấy mẫu = đa thức số lần ảnh được chọn).
    per_class[c] = (score, tp, img_idx) đã sắp score giảm dần; gt_cnt[c] = mảng (n_img,) số GT không-difficult."""
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(n_img, np.ones(n_img) / n_img, size=B).astype(np.float64)
    ones = np.ones((1, n_img))
    out = {}
    aps_b = {}
    for c in MAPPED:
        sc, tp, im = per_class.get(c, (np.zeros(0), np.zeros(0), np.zeros(0, int)))
        g = gt_cnt[c]
        res = []
        for W in [ones] + [counts[i:i + chunk] for i in range(0, B, chunk)]:
            w = W[:, im] if len(im) else np.zeros((len(W), 0))
            tpc = np.cumsum(tp[None, :] * w, axis=1)
            fpc = np.cumsum((1 - tp)[None, :] * w, axis=1)
            npos = W @ g
            den = tpc + fpc
            prec = np.divide(tpc, den, out=np.zeros_like(tpc), where=den > 0)
            rec = np.divide(tpc, npos[:, None], out=np.zeros_like(tpc), where=npos[:, None] > 0)
            ap = voc_ap(rec, prec)
            ap = np.where(npos > 0, ap, np.nan)
            res.append(ap)
        point = res[0][0]
        boot = np.concatenate(res[1:])
        aps_b[c] = boot
        if np.isnan(point):
            out[c] = {"ap": None, "ci": None, "n_gt": int(g.sum())}
        else:
            lo, hi = np.nanpercentile(boot, [2.5, 97.5])
            out[c] = {"ap": float(point), "ci": [float(lo), float(hi)], "n_gt": int(g.sum())}
    have = [c for c in MAPPED if out[c]["ap"] is not None]
    m_point = float(np.mean([out[c]["ap"] for c in have])) if have else None
    m_boot = np.nanmean(np.stack([aps_b[c] for c in have]), axis=0) if have else np.array([np.nan])
    lo, hi = np.nanpercentile(m_boot, [2.5, 97.5])
    out["_mAP"] = {"map": m_point, "ci": [float(lo), float(hi)], "n_classes": len(have)}
    return out


def evaluate(images: list[dict], with_ap: bool = True) -> tuple[dict, list[dict]]:
    """images: danh sách {"name","source","group","gt","dets_op","dets_any"}. -> (metrics, per_box)"""
    metrics = {g: {} for g in GROUPS}
    per_box = []
    sc = {v: [score_image(im, v) for im in images] for v in VARIANTS}
    for v in VARIANTS:
        for i, (im, s) in enumerate(zip(images, sc[v])):
            for j, g in enumerate(im["gt"]):
                per_box.append({"img": im["name"], "variant": v, "cls": g["cls"], "difficult": g["difficult"],
                                "in_lane": g["in_lane"], "agn_op": int(s["agn_op"][j]), "cls_op": int(s["cls_op"][j]),
                                "agn_any": int(s["agn_any"][j])})
    for gname in GROUPS:
        sel = [i for i, im in enumerate(images) if gname == "all" or im["group"] == gname]
        n = len(sel)
        for v in VARIANTS:
            S = [sc[v][i] for i in sel]
            m = {"n_images": n, "n_gt": int(sum(len(s["diff"]) for s in S)),
                 "n_gt_inlane": int(sum(((~s["diff"]) & s["in_lane"]).sum() for s in S)),
                 "n_difficult_excluded": int(sum(s["diff"].sum() for s in S))}

            def rec(flag, lane_only, mapped_only=False):
                rows = []
                for s in S:
                    ok = ~s["diff"]
                    if lane_only:
                        ok = ok & s["in_lane"]
                    if mapped_only:
                        ok = ok & np.array([c in MAPPED for c in s["gcls"]], bool)
                    rows.append([int((s[flag] & ok).sum()), int(ok.sum())])
                return ratio_ci(np.array(rows).reshape(-1, 2))

            m["recall_inlane_agnostic"] = rec("agn_op", True)               # SỐ CHÍNH (khi group=non_coco)
            m["recall_inlane_classaware_mapped"] = rec("cls_op", True, True)
            m["recall_all_agnostic"] = rec("agn_op", False)
            m["recall_inlane_agnostic_anyscore"] = rec("agn_any", True)     # trần: bỏ ngưỡng 0,35
            # precision/recall ở ngưỡng vận hành, theo lớp ánh xạ (micro)
            pr = []
            for s in S:
                tp = sum(1 for (_, _, t) in s["tf_op"] if t == 1)
                fp = sum(1 for (_, _, t) in s["tf_op"] if t == 0)
                pr.append([tp, tp + fp])
            m["precision_op_classaware"] = ratio_ci(np.array(pr).reshape(-1, 2))
            m["precision_op_agnostic"] = ratio_ci(np.array(
                [[s["aprec_op"][0], s["aprec_op"][0] + s["aprec_op"][1]] for s in S]).reshape(-1, 2))
            m["recall_op_classaware_all_mapped"] = rec("cls_op", False, True)
            m["detections_per_image_op"] = float(np.mean([s["n_det_op"] for s in S])) if S else None
            # theo lớp
            pc = {}
            for c in OBSTACLE_CLASSES:
                row = {}
                for lane in (True, False):
                    r = []
                    for s in S:
                        ok = (~s["diff"]) & np.array([x == c for x in s["gcls"]], bool)
                        if lane:
                            ok = ok & s["in_lane"]
                        r.append([int((s["agn_op"] & ok).sum()), int(ok.sum())])
                    d = ratio_ci(np.array(r).reshape(-1, 2))
                    row["recall_inlane_agnostic" if lane else "recall_all_agnostic"] = d
                pc[c] = row
            # AP
            per_class = {}
            gt_cnt = {c: np.array([int(((~s["diff"]) & np.array([x == c for x in s["gcls"]], bool)).sum()) for s in S],
                                  dtype=float) for c in MAPPED}
            for c in MAPPED:
                rows = [(sc_, t, k) for k, s in enumerate(S) for (cc, sc_, t) in s["tf_any"] if cc == c]
                if rows:
                    rows.sort(key=lambda r: -r[0])
                    per_class[c] = (np.array([r[0] for r in rows]), np.array([r[1] for r in rows], dtype=float),
                                    np.array([r[2] for r in rows], dtype=int))
            ap = ap_boot(per_class, len(S), gt_cnt) if with_ap else {c: {"ap": None, "ci": None, "n_gt": 0} for c in MAPPED} | {"_mAP": {"map": None, "ci": [None, None], "n_classes": 0}}
            for c in MAPPED:
                pc[c]["ap"] = ap[c]
            m["per_class"] = pc
            m["mAP50_mapped"] = ap["_mAP"]
            # theo nguồn (chỉ in-lane agnostic)
            src = {}
            for so in ("voc", "self", "coco"):
                idx = [k for k, i in enumerate(sel) if images[i]["source"] == so]
                if idx:
                    rows = []
                    for k in idx:
                        s = S[k]; ok = (~s["diff"]) & s["in_lane"]
                        rows.append([int((s["agn_op"] & ok).sum()), int(ok.sum())])
                    src[so] = {"n_images": len(idx), **ratio_ci(np.array(rows))}
            m["recall_inlane_agnostic_by_source"] = src
            metrics[gname][v] = m
        # ghép đôi orig vs glass trên hộp GT in-lane agnostic
        a, b, imgidx = [], [], []
        for k, i in enumerate(sel):
            so, sg = sc["orig"][i], sc["glass"][i]
            ok = (~so["diff"]) & so["in_lane"]
            for j in np.where(ok)[0]:
                a.append(int(so["agn_op"][j])); b.append(int(sg["agn_op"][j])); imgidx.append(k)
        metrics[gname]["paired_glass_vs_orig_inlane"] = paired_cluster(a, b, imgidx, n)
    return metrics, per_box


def negative_control(images: list[dict]) -> dict:
    """Đối chứng âm: ghép detection của ảnh i với GT của ảnh i+1 (xoay vòng). Recall phải sụp về ~0 nếu bàn đo không tự khớp."""
    shifted = []
    for i, im in enumerate(images):
        o = images[(i + 1) % len(images)]
        shifted.append({**im, "dets_op": o["dets_op"], "dets_any": o["dets_any"]})
    m, _ = evaluate(shifted, with_ap=False)
    return {"expect": "thấp hơn rõ so với số thật (không về 0: vật lớn nằm giữa ảnh trùng IoU>=0,5 một phần do ngẫu nhiên — đây là mức 'chance')",
            "recall_inlane_agnostic_non_coco_glass": m["non_coco"]["glass"]["recall_inlane_agnostic"],
            "recall_inlane_agnostic_all_orig": m["all"]["orig"]["recall_inlane_agnostic"]}


def paired_cluster(a, b, img, n_img, B=1000, seed=0) -> dict:
    """Ghép đôi theo hộp GT (đếm bất đồng) nhưng CI của Δ bootstrap THEO ẢNH (hộp cùng ảnh không độc lập)."""
    if not a:
        return {"n": 0}
    base = common.paired(a, b)
    a, b, img = np.array(a, float), np.array(b, float), np.array(img)
    per = np.zeros((n_img, 3))
    np.add.at(per[:, 0], img, 1); np.add.at(per[:, 1], img, a); np.add.at(per[:, 2], img, b)
    d, lo, hi = common.bootstrap_ci(per, stat=lambda x: (x[:, 2].sum() - x[:, 1].sum()) / max(x[:, 0].sum(), 1), n=B, seed=seed)
    return {"n_boxes": base["n"], "orig_recall": base["mean_a"], "glass_recall": base["mean_b"], "delta": d,
            "delta_ci_by_image": [lo, hi], "orig_only": base["a_only"], "glass_only": base["b_only"]}


# ----------------------------------------------------------------------------- chạy model

def load_detector(imgsz: int) -> hazard.OnnxYolo:
    det = hazard.OnnxYolo(config.HAZARD_MODEL_PATH, imgsz)
    if det.provider != "CUDAExecutionProvider":
        raise SystemExit(f"detector chạy trên {det.provider}, không phải CUDA — dừng (không lùi CPU)")
    for _ in range(3):
        det.detect(np.zeros((240, 320, 3), dtype=np.uint8))
    return det


def input_is_static() -> tuple[bool, list]:
    import onnxruntime as ort
    s = ort.InferenceSession(config.HAZARD_MODEL_PATH, providers=["CPUExecutionProvider"])
    shape = s.get_inputs()[0].shape
    return all(isinstance(x, int) for x in shape[2:]), shape


def run_model(names: list[str], imgsz: int) -> tuple[list[dict], dict, list[float]]:
    det = load_detector(imgsz)
    images, lat, mism, skipped = [], [], 0, {}
    pre_glass = []
    t0 = time.time()
    for n, name in enumerate(names):
        ann = parse_ann(os.path.join(ANN_DIR, os.path.splitext(name)[0] + ".xml"))
        for k, v in ann["skipped"].items():
            skipped[k] = skipped.get(k, 0) + v
        bgr = cv2.imread(os.path.join(IMG_DIR, name))
        assert bgr is not None, name
        h, w = bgr.shape[:2]
        size_mismatch = abs(w / h - ann["W"] / ann["H"]) > 0.01
        variants = {"orig": bgr, "glass": to_glass(bgr)}
        rec = {"name": name, "source": source_of(name), "group": group_of(name), "gt": ann["gt"],
               "size_mismatch": bool(size_mismatch), "dets_op": {}, "dets_any": {}}
        for v, img in variants.items():
            config.HAZARD_MIN_SCORE = OP_SCORE
            dop = det.detect(img)
            config.HAZARD_MIN_SCORE = AP_SCORE
            dany = det.detect(img)
            config.HAZARD_MIN_SCORE = OP_SCORE
            if {(d.kind, round(d.score, 4)) for d in dop} != \
               {(d.kind, round(d.score, 4)) for d in dany if d.score >= OP_SCORE}:
                mism += 1
            rec["dets_op"][v] = [fmt_det(d) for d in dop]
            rec["dets_any"][v] = [fmt_det(d) for d in dany]
        pre_glass.append(variants["glass"])
        images.append(rec)
        if (n + 1) % 200 == 0:
            print(f"  [{n + 1}/{len(names)}] {time.time() - t0:.0f}s", flush=True)
    # độ trễ: detect() mỗi ảnh glass ở ngưỡng vận hành, warm-up 20
    config.HAZARD_MIN_SCORE = OP_SCORE
    for k in range(20):
        det.detect(pre_glass[k % len(pre_glass)])
    for img in pre_glass:
        t = time.perf_counter()
        det.detect(img)
        lat.append((time.perf_counter() - t) * 1000)
    info = {"op_vs_any_mismatch_images": mism, "skipped_gt_names": skipped, "provider": det.provider}
    return images, info, lat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--rescore", default=None, help="chấm lại từ JSON đã lưu, không gọi model")
    ap.add_argument("--imgsz", default="320", help="vd 320 hoặc 320,416,640 (chỉ có tác dụng nếu ONNX đầu vào động)")
    args = ap.parse_args()

    if args.rescore:
        data = json.load(open(args.rescore, encoding="utf-8"))
        res = data["imgsz"]
        for k, blk in res.items():
            blk["metrics"], _ = evaluate(blk["per_sample"])
        path = common.write_result("hazard", "detect_rescore", data, args.out)
        print("ghi", path)
        return

    static, shape = input_is_static()
    sizes = [int(x) for x in args.imgsz.split(",")]
    if static:
        extra = [s for s in sizes if s != 320]
        sizes = [320]
        note = f"ONNX đầu vào tĩnh {shape}: chỉ 320" + (f" (bỏ qua {extra})" if extra else "")
    else:
        note = f"ONNX đầu vào động {shape}: chạy {sizes}"
    print(note)
    names = list_images(args.limit)
    n_files = len(glob.glob(os.path.join(IMG_DIR, "*.jpg")))
    cfg = {"limit": args.limit, "n_images": len(names), "n_files_in_dir": n_files, "imgsz": sizes, "static_input": static,
           "onnx_input_shape": shape, "op_score": OP_SCORE, "ap_score": AP_SCORE, "iou": IOU, "lane_x": LANE_X,
           "lane_area": LANE_AREA, "glass": {"width": GLASS_W, "jpeg_q": GLASS_Q}, "model": config.HAZARD_MODEL_PATH,
           "nms_iou": 0.45, "note": note, "split": SPLIT, "classes_json": CLASSES_JSON, "mapped_classes": MAPPED}
    out = {"meta": None, "imgsz": {}}
    t0 = time.time()
    for s in sizes:
        print(f"imgsz {s}: {len(names)} ảnh", flush=True)
        images, info, lat = run_model(names, s)
        metrics, per_box = evaluate(images)
        out["imgsz"][str(s)] = {"metrics": metrics, "latency": {"detect_glass": common.latency_summary(lat)},
                                "info": info, "per_sample": images, "negative_control": negative_control(images)}
    out["meta"] = common.run_meta(cfg)
    out["meta"]["elapsed_s"] = round(time.time() - t0, 1)
    path = common.write_result("hazard", "detect" + ("" if not args.limit else f"_limit{args.limit}"), out, args.out)
    json.load(open(path, encoding="utf-8"))  # đọc lại: NFS từng cắt file âm thầm
    print("ghi", path, os.path.getsize(path), "bytes")
    m = out["imgsz"][str(sizes[0])]["metrics"]["non_coco"]["glass"]
    print("non_coco glass recall in-lane:", m["recall_inlane_agnostic"]["value"], "mAP:", m["mAP50_mapped"]["map"])


if __name__ == "__main__":
    main()
