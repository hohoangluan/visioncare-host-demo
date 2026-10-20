"""Dựng tập YOLO cho fine-tune vật cản (PLAN_cai-tien-ai V3). Chạy bằng ~/.venvs/yolo (cần ultralytics).

- 15 lớp Obstacle-Dataset lấy từ ann-{train,val} (VOC xml, chỉ <object><name>, chuẩn hoá theo <size>).
- 5 lớp COCO SeeVia đang cảnh báo mà Obstacle không có (chair, bench, plant, traffic_light, parking_meter):
  NHÃN GIẢ từ YOLO11m COCO (conf >= 0,5, imgsz 640), bỏ hộp trùng IoU >= 0,5 với hộp GT — để fine-tune không làm quên các lớp này.
- Chống rò: bỏ khỏi train/val mọi ảnh trùng ảnh test (md5 giống, hoặc dHash 64 bit lệch <= 4 bit).
- Ra: train/obstacle_yolo/{images,labels}/{train,val} (ảnh là symlink), obstacle.yaml, classes_vh.json (id -> [kind, nhóm] cho VH),
  dedup.json (thống kê + danh sách bỏ).

    ~/.venvs/yolo/bin/python train/build_dataset.py
"""

import glob
import hashlib
import json
import os
import xml.etree.ElementTree as ET

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
DATA = os.path.join(EVAL, "datas", "obstacle_dataset")
OUT = os.path.join(HERE, "obstacle_yolo")

OBSTACLE = ["stop_sign", "person", "bicycle", "bus", "truck", "car", "motorbike", "reflective_cone",
            "ashcan", "warning_column", "spherical_roadblock", "pole", "dog", "tricycle", "fire_hydrant"]
EXTRA_COCO = {56: "chair", 13: "bench", 58: "plant", 9: "traffic_light", 12: "parking_meter"}  # COCO id -> kind VH
NAMES = OBSTACLE + list(EXTRA_COCO.values())
GROUP = {"person": "person", "dog": "person", "bicycle": "vehicle", "car": "vehicle", "motorbike": "vehicle",
         "bus": "vehicle", "truck": "vehicle", "tricycle": "vehicle"}  # còn lại: static (giống nhóm VH)
PSEUDO_CONF, PSEUDO_IOU, DHASH_MAX = 0.5, 0.5, 4
GLASS_W, GLASS_Q = 320, (15, 30)  # kính gửi QVGA JPEG q15 (bench C1a dùng q15) -> train thêm bản suy giảm này
IMG_EXT = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")


def images(split: str) -> list[str]:
    d = os.path.join(DATA, split, f"img-{split}")
    return sorted(p for p in glob.glob(os.path.join(d, "*")) if p.endswith(IMG_EXT))


def md5(path: str) -> str:
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def dhash(path: str) -> int | None:
    g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None
    s = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (s[:, 1:] > s[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def gt_boxes(split: str, img_path: str) -> list[tuple[int, list[float]]]:
    xml = os.path.join(DATA, split, f"ann-{split}", os.path.splitext(os.path.basename(img_path))[0] + ".xml")
    if not os.path.exists(xml):
        return []
    root = ET.parse(xml).getroot()
    W, H = float(root.findtext("size/width")), float(root.findtext("size/height"))
    out = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        if name not in OBSTACLE:
            continue
        bb = obj.find("bndbox")
        x0, y0, x1, y1 = (float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax"))
        box = [max(0.0, x0 / W), max(0.0, y0 / H), min(1.0, x1 / W), min(1.0, y1 / H)]
        if box[2] > box[0] and box[3] > box[1]:
            out.append((OBSTACLE.index(name), box))
    return out


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def main() -> None:
    from ultralytics import YOLO

    test = images("test")
    assert len(test) == 1583, f"test {len(test)} ảnh, cần 1583"
    t_md5 = {md5(p) for p in test}
    t_hash = np.array([h for h in (dhash(p) for p in test) if h is not None], dtype=np.uint64)

    def near_test(p: str) -> bool:
        if md5(p) in t_md5:
            return True
        h = dhash(p)
        if h is None:
            return True  # ảnh hỏng: bỏ luôn
        x = np.bitwise_xor(t_hash, np.uint64(h))
        dist = np.array([bin(int(v)).count("1") for v in x])
        return bool((dist <= DHASH_MAX).any())

    pseudo_model = YOLO(os.path.join(HERE, "weights", "yolo11m.pt"))
    stats = {"dhash_max_bits": DHASH_MAX, "pseudo_conf": PSEUDO_CONF, "splits": {}}
    for split in ("train", "val"):
        imgs = images(split)
        kept, dropped = [], []
        for p in imgs:
            (dropped if near_test(p) else kept).append(p)
        idir, ldir = os.path.join(OUT, "images", split), os.path.join(OUT, "labels", split)
        os.makedirs(idir, exist_ok=True); os.makedirs(ldir, exist_ok=True)
        n_gt = {c: 0 for c in NAMES}
        n_pseudo_skip_overlap = n_glass = 0
        rng = np.random.default_rng(0)
        for k in range(0, len(kept), 64):
            chunk = kept[k:k + 64]
            preds = pseudo_model.predict(chunk, imgsz=640, conf=PSEUDO_CONF, classes=list(EXTRA_COCO), device=0,
                                         verbose=False)
            for p, r in zip(chunk, preds):
                boxes = gt_boxes(split, p)
                for c, _ in boxes:
                    n_gt[NAMES[c]] += 1
                if r.boxes is not None and len(r.boxes):
                    for cid, xyxyn in zip(r.boxes.cls.tolist(), r.boxes.xyxyn.tolist()):
                        if any(iou(xyxyn, b) >= PSEUDO_IOU for _, b in boxes):
                            n_pseudo_skip_overlap += 1
                            continue
                        c = NAMES.index(EXTRA_COCO[int(cid)])
                        boxes.append((c, xyxyn))
                        n_gt[NAMES[c]] += 1
                name = os.path.basename(p)
                link = os.path.join(idir, name)
                if not os.path.lexists(link):
                    os.symlink(p, link)
                lines = []
                for c, b in boxes:
                    cx, cy, w, h = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1]
                    lines.append(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
                stem = os.path.splitext(name)[0]
                with open(os.path.join(ldir, stem + ".txt"), "w") as f:
                    f.writelines(lines)
                if split == "train":  # bản "như kính gửi" (rộng 320 + JPEG q15–30), cùng nhãn chuẩn hoá — chỉ train, val giữ nguyên
                    bgr = cv2.imread(p)
                    if bgr is not None:
                        h0, w0 = bgr.shape[:2]
                        small = cv2.resize(bgr, (GLASS_W, max(1, round(h0 * GLASS_W / w0))), interpolation=cv2.INTER_AREA)
                        q = int(rng.integers(GLASS_Q[0], GLASS_Q[1] + 1))
                        cv2.imwrite(os.path.join(idir, stem + "_glass.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, q])
                        with open(os.path.join(ldir, stem + "_glass.txt"), "w") as f:
                            f.writelines(lines)
                        n_glass += 1
            print(f"{split}: {min(k + 64, len(kept))}/{len(kept)}", flush=True)
        stats["splits"][split] = {"images": len(imgs), "kept": len(kept), "dropped_near_test": len(dropped),
                                  "dropped_names": [os.path.basename(p) for p in dropped],
                                  "boxes_per_class": n_gt, "pseudo_skipped_overlap_gt": n_pseudo_skip_overlap,
                                  "glass_copies": n_glass, "glass_jpeg_q": list(GLASS_Q)}
        print(split, {k: v for k, v in stats["splits"][split].items() if k != "dropped_names"}, flush=True)

    with open(os.path.join(HERE, "obstacle.yaml"), "w") as f:
        f.write(f"path: {OUT}\ntrain: images/train\nval: images/val\nnames:\n")
        for i, n in enumerate(NAMES):
            f.write(f"  {i}: {n}\n")
    json.dump({str(i): [n, GROUP.get(n, "static")] for i, n in enumerate(NAMES)},
              open(os.path.join(HERE, "classes_vh.json"), "w"), indent=1)
    json.dump(stats, open(os.path.join(HERE, "dedup.json"), "w"), indent=1)
    print("xong", OUT)


if __name__ == "__main__":
    main()
