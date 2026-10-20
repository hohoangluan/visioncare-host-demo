"""C2a — OCR đọc nguyên văn trên VinText test (METRICS.md C2a). Chạy từ evaluations/: python -m bench.ocr_vintext [--limit N]

Đường production: `lanes.ocr_live.spoken(jpeg, "raw", "bench")` (read_image + câu đầu cắt <= 8 từ).
Chấm: số sai/bỏ sót (multiset chuỗi chữ số), BoW P/R/F1 (multiset từ), CER (GT sắp trên->dưới, trái->phải), từ chối.
"""

import argparse
import glob
import os
import re
from collections import Counter

import numpy as np

from bench import common

common.setup(gpu=False)  # LLM xa: không cần GPU

from bench import llm_common as L  # noqa: E402

TASK = "ocr_vintext"
VT = os.path.join(common.DATAS, "vintext", "vietnamese")


def parse_gt(path: str) -> list[dict]:
    """`x1,y1,...,x4,y4,TEXT` (TEXT có thể chứa dấu phẩy). Bỏ hộp `###`."""
    boxes = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            parts = line.rstrip("\n").split(",", 8)
            if len(parts) < 9:
                continue
            text = parts[8].strip()
            if not text or text == "###":
                continue
            try:
                xy = [float(v) for v in parts[:8]]
            except ValueError:
                continue
            xs, ys = xy[0::2], xy[1::2]
            boxes.append({"cx": sum(xs) / 4, "cy": sum(ys) / 4, "h": max(ys) - min(ys), "text": text})
    return boxes


def order_boxes(boxes: list[dict]) -> list[dict]:
    """Gom dòng theo cy (lệch < 0,5 chiều cao hộp đầu dòng), mỗi dòng theo cx."""
    lines: list[list[dict]] = []
    for b in sorted(boxes, key=lambda b: b["cy"]):
        if lines and abs(b["cy"] - lines[-1][0]["cy"]) <= 0.5 * max(lines[-1][0]["h"], 1):
            lines[-1].append(b)
        else:
            lines.append([b])
    return [b for ln in lines for b in sorted(ln, key=lambda b: b["cx"])]


def score(out_text: str, gt_boxes: list[dict]) -> dict:
    gt_ordered = " ".join(b["text"] for b in order_boxes(gt_boxes))
    refused = L.is_refusal(out_text, maxlen=80)
    hyp = "" if refused else out_text
    gw, ow = Counter(L.words(gt_ordered)), Counter(L.words(hyp))
    inter = sum((gw & ow).values())
    p = inter / sum(ow.values()) if sum(ow.values()) else float("nan")
    r = inter / sum(gw.values()) if sum(gw.values()) else float("nan")
    f1 = 2 * p * r / (p + r) if p == p and r == r and (p + r) > 0 else (0.0 if sum(gw.values()) else float("nan"))
    g_norm, h_norm = L.strip_punct(gt_ordered), L.strip_punct(hyp)
    cer = L.lev(g_norm, h_norm) / len(g_norm) if g_norm else float("nan")
    gn, on = Counter(L.digit_tokens(gt_ordered)), Counter(L.digit_tokens(hyp))
    wrong = sum((on - gn).values())  # số trong đầu ra không có (đủ lần) trong GT
    # Biến thể khoan dung với GT tách hộp ("0","2" vs đầu ra "02"): số "sai" mà vẫn là đoạn liền của dãy chữ số GT thì tha.
    gt_digits = "".join(re.findall(r"\d", gt_ordered))
    wrong_len = sum(1 for tok in (on - gn).elements() if tok not in gt_digits)
    missed = sum((gn - on).values())
    return {"refused": bool(refused), "bow_p": p, "bow_r": r, "bow_f1": f1, "cer": cer,
            "num_out": sum(on.values()), "num_wrong": wrong, "num_wrong_lenient": wrong_len, "num_gt": sum(gn.values()), "num_missed": missed,
            "gt_text": gt_ordered}


async def run(args):
    import config
    from models.ocr import prompts
    cfg_parts = {"task": TASK, "prompt": prompts._RAW, "mode": "raw"}
    cache = L.Cache(TASK, L.cfg_hash(cfg_parts))
    imgs = sorted(glob.glob(os.path.join(VT, "test_image", "im*.jpg")))
    if args.limit:
        imgs = imgs[: args.limit]
    gts = {}
    for p in imgs:
        n = re.search(r"im(\d+)\.jpg", p).group(1)
        gts[os.path.basename(p)] = parse_gt(os.path.join(VT, "labels", f"gt_{n}.txt"))

    from lanes import ocr_live

    def factory(p):
        with open(p, "rb") as f:
            jpeg = f.read()
        return ocr_live.spoken(jpeg, "raw", "bench")

    res = await L.run_items(imgs, os.path.basename, factory, cache, TASK)

    per, ttft, total = [], [], []
    for p in imgs:
        name = os.path.basename(p)
        r = res[name]
        row = {"image": name, "n_gt_boxes": len(gts[name]), "output": r["text"], "ttft_ms": r.get("ttft_ms"),
               "total_ms": r.get("total_ms"), "error": r.get("error"), "cached": r["cached"]}
        if "error" not in r:
            row.update(score(r["text"], gts[name]))
            ttft.append(r["ttft_ms"])
            total.append(r["total_ms"])
        per.append(row)
    ok = [x for x in per if not x["error"] and x["gt_text"].strip()]
    arr = lambda k: np.array([x[k] for x in ok], dtype=float)  # noqa: E731
    metrics = {
        "num_wrong_rate": L.ci_entry(np.stack([arr("num_wrong"), arr("num_out")], 1), L.ratio_stat) if ok else None,
        "num_wrong_rate_lenient": L.ci_entry(np.stack([arr("num_wrong_lenient"), arr("num_out")], 1), L.ratio_stat) if ok else None,
        "num_missed_rate": L.ci_entry(np.stack([arr("num_missed"), arr("num_gt")], 1), L.ratio_stat) if ok else None,
        "img_with_wrong_number": L.ci_entry((arr("num_wrong") > 0).astype(float)) if ok else None,
        "bow_precision": L.ci_entry(arr("bow_p"), np.nanmean) if ok else None,
        "bow_recall": L.ci_entry(arr("bow_r"), np.nanmean) if ok else None,
        "bow_f1": L.ci_entry(arr("bow_f1"), np.nanmean) if ok else None,
        "cer": L.ci_entry(arr("cer"), np.nanmean) if ok else None,
        "refusal_rate": L.ci_entry(arr("refused")) if ok else None,
    }
    nonref = [x for x in ok if not x["refused"]]
    if nonref:
        metrics["cer_nonrefused"] = L.ci_entry(np.array([x["cer"] for x in nonref]), np.nanmean)
    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "cfg_hash": cache.cfg, **cfg_parts,
                                        "llm_max_tokens": 1024, "temperature": 0.0, "first_sentence_max_words": config.FIRST_SENTENCE_MAX_WORDS}),
               "metrics": metrics, "n_images": len(imgs), "n_scored": len(ok), "n_errors": sum(1 for x in per if x["error"]),
               "latency": {"ttft": common.latency_summary(ttft), "total": common.latency_summary(total)},
               "per_sample": per}
    path = common.write_result(TASK, f"raw_spoken{'_limit%d' % args.limit if args.limit else ''}", payload, args.out)
    print(path)
    for k, v in metrics.items():
        if v:
            print(f"{k}: {v['value']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}] n={v['n']}")
    print("latency", payload["latency"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="chỉ N ảnh đầu (chạy thử)")
    ap.add_argument("--out", default=None, help="thư mục ghi JSON (mặc định results/ocr_vintext)")
    args = ap.parse_args()
    L.new_loop_run(run(args))


if __name__ == "__main__":
    main()
