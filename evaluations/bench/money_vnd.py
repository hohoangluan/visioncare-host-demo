"""C3 — đọc tiền VND trên vnd_kaggle (METRICS.md C3). python -m bench.money_vnd [--limit N] [--path general|ocr_spoken]

DỮ LIỆU CỘNG ĐỒNG (Kaggle), KHÔNG có bài báo/baseline — chỉ chứng minh đọc được, không chứng minh hiệu quả.
Mẫu: 30 ảnh/thư mục mệnh giá (11 mệnh giá + 000000 = không có tiền) trải đều theo chỉ số khung (sắp theo số trong tên file).
--path general (mặc định, theo PLAN/METRICS): `lanes.general.answer("money", "Đây là tờ tiền bao nhiêu?", ảnh 896 px)`.
--path ocr_spoken: `ocr_live.spoken(jpeg, "money", ...)` — đường THẬT của làn B trong pipeline/final_router.py (ảnh nguyên cỡ, không system prompt).
"""

import argparse
import glob
import os
import re
from collections import Counter

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402

TASK = "money_vnd"
ROOT = os.path.join(common.DATAS, "vnd_kaggle")
QUESTION = "Đây là tờ tiền bao nhiêu?"
DENOMS = [200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]
PER_DIR = 30

_WORD_VALUES = [  # dài trước ngắn (khớp tham lam)
    ("năm trăm nghìn", 500000), ("năm trăm ngàn", 500000), ("hai trăm nghìn", 200000), ("hai trăm ngàn", 200000),
    ("một trăm nghìn", 100000), ("một trăm ngàn", 100000), ("năm mươi nghìn", 50000), ("năm mươi ngàn", 50000),
    ("hai mươi nghìn", 20000), ("hai mươi ngàn", 20000), ("mười nghìn", 10000), ("mười ngàn", 10000),
    ("năm nghìn", 5000), ("năm ngàn", 5000), ("hai nghìn", 2000), ("hai ngàn", 2000), ("một nghìn", 1000),
    ("một ngàn", 1000), ("năm trăm đồng", 500), ("hai trăm đồng", 200),
]
_NUM_UNIT = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+)(?:\s*(nghìn|ngàn|nghin|k\b|triệu|đồng|vnd|vnđ|đ\b))?")
_NO_MONEY = re.compile(r"không\s+(?:có|thấy|nhìn\s+thấy)\s+(?:tờ|tiền|tờ\s+tiền)|chụp\s+lại|không\s+thấy\s+rõ\s+tiền")


def denominations(text: str) -> list[int]:
    """Mệnh giá (đồng) nêu trong câu trả lời, theo thứ tự xuất hiện, bỏ trùng liên tiếp.
    '50 nghìn đồng'->50000, '50.000'->50000, '200 đồng'->200, 'năm mươi nghìn'->50000. Số không phải mệnh giá hợp lệ bị bỏ."""
    t = L.nfc_lower(text)
    hits: list[tuple[int, int]] = []
    for m in _NUM_UNIT.finditer(t):
        raw, unit = m.group(1), m.group(2)
        n = int(re.sub(r"[.,]", "", raw)) if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw) else int(raw)
        if unit in ("nghìn", "ngàn", "nghin", "k"):
            v = n * 1000
        elif unit == "triệu":
            v = n * 1_000_000
        else:  # 'đồng'/không đơn vị: n < 1000 chỉ nhận 200/500 (tờ 200đ, 500đ), còn lại phải là mệnh giá đủ
            v = n
        if v in DENOMS:
            hits.append((m.start(), v))
    for phrase, v in _WORD_VALUES:
        for m in re.finditer(re.escape(phrase), t):
            hits.append((m.start(), v))
    out: list[int] = []
    for _, v in sorted(hits):
        if not out or out[-1] != v:
            out.append(v)
    return out


def classify(text: str, gt: int) -> dict:
    vals = denominations(text)
    first = vals[0] if vals else None
    if gt == 0:  # không có tiền: nêu bất kỳ mệnh giá nào = bịa
        label = "fabricated" if vals else ("refused" if (L.is_refusal(text) or _NO_MONEY.search(L.nfc_lower(text))) else "no_denom")
    elif not vals:
        label = "refused" if (L.is_refusal(text) or _NO_MONEY.search(L.nfc_lower(text))) else "unparsed"
    else:
        label = "correct" if set(vals) == {gt} else "wrong"
    return {"label": label, "values": vals, "first": first, "multi": len(set(vals)) > 1}


def pick_samples(limit: int | None) -> list[dict]:
    per_dir = {}
    for d in sorted(os.listdir(ROOT)):
        files = glob.glob(os.path.join(ROOT, d, "*.png"))
        files.sort(key=lambda p: int(re.search(r"_(\d+)\.png$", p).group(1)))
        idx = sorted(set(np.linspace(0, len(files) - 1, PER_DIR).round().astype(int)))
        per_dir[int(d)] = [files[i] for i in idx]
    items = []
    for i in range(PER_DIR):  # xen kẽ giữa các mệnh giá để --limit nhỏ vẫn chạm nhiều lớp
        for gt, files in per_dir.items():
            if i < len(files):
                items.append({"gt": gt, "path": files[i], "key": os.path.relpath(files[i], ROOT)})
    return items[:limit] if limit else items


async def run(args):
    import config
    from handlers import read_money
    from lanes import general, ocr_live
    from pipeline import image_quality
    from pipeline.image_buffer import resize_jpeg

    cfg_parts = {"task": TASK, "path": args.path, "prompt": read_money._PROMPT, "question": QUESTION,
                 "system": general._VISION_SYSTEM}
    cache = L.Cache(TASK, L.cfg_hash(cfg_parts), name=f"cache_{args.path}.jsonl")
    items = pick_samples(args.limit)
    for it in items:
        with open(it["path"], "rb") as f:
            it["jpeg"] = L.to_jpeg(f.read(), quality=90)

    def factory(it):
        if args.path == "ocr_spoken":
            return ocr_live.spoken(it["jpeg"], "money", "bench")
        return general.answer("money", QUESTION, resize_jpeg(it["jpeg"], config.LLM_IMAGE_MAX_SIDE))

    res = await L.run_items(items, lambda it: it["key"], factory, cache, TASK)

    per, ttft, total = [], [], []
    for it in items:
        r = res[it["key"]]
        row = {"key": it["key"], "gt": it["gt"], "output": r["text"], "ttft_ms": r.get("ttft_ms"),
               "total_ms": r.get("total_ms"), "error": r.get("error"), "cached": r["cached"],
               "gate_reason": image_quality.reject_reason("money", it["jpeg"])}
        if "error" not in r:
            row.update(classify(r["text"], it["gt"]))
            ttft.append(r["ttft_ms"])
            total.append(r["total_ms"])
        per.append(row)

    ok = [x for x in per if not x["error"]]
    money = [x for x in ok if x["gt"] != 0]
    nomoney = [x for x in ok if x["gt"] == 0]
    B = lambda rows, f: np.array([f(x) for x in rows], dtype=float)  # noqa: E731
    metrics = {}
    if money:
        metrics["read_wrong_rate"] = L.ci_entry(B(money, lambda x: x["label"] == "wrong"))
        metrics["accuracy"] = L.ci_entry(B(money, lambda x: x["label"] == "correct"))
        metrics["refusal_rate"] = L.ci_entry(B(money, lambda x: x["label"] == "refused"))
        metrics["unparsed_rate"] = L.ci_entry(B(money, lambda x: x["label"] == "unparsed"))
        metrics["wrong_given_answered"] = L.ci_entry(np.stack(
            [B(money, lambda x: x["label"] == "wrong"), B(money, lambda x: x["label"] in ("wrong", "correct"))], 1), L.ratio_stat)
        metrics["multi_value_rate"] = L.ci_entry(B(money, lambda x: x["multi"]))
        metrics["gate_reject_rate_money"] = L.ci_entry(B(money, lambda x: x["gate_reason"] is not None))
    if nomoney:
        metrics["fabricate_rate"] = L.ci_entry(B(nomoney, lambda x: x["label"] == "fabricated"))
    per_denom = {}
    for gt in sorted({x["gt"] for x in ok if x["gt"] != 0}):
        rows = [x for x in money if x["gt"] == gt]
        per_denom[str(gt)] = {"accuracy": L.ci_entry(B(rows, lambda x: x["label"] == "correct")),
                              "wrong": L.ci_entry(B(rows, lambda x: x["label"] == "wrong"))}
    confusion = {}  # hàng = GT, cột = mệnh giá đầu tiên được nêu | "none" | (lẫn nhiều giá trị = "multi")
    for x in ok:
        col = "multi" if x["multi"] else (str(x["first"]) if x["first"] else "none")
        confusion.setdefault(str(x["gt"]), Counter())[col] += 1
    confusion = {k: dict(v) for k, v in sorted(confusion.items(), key=lambda kv: int(kv[0]))}

    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "path": args.path, "cfg_hash": cache.cfg, "question": QUESTION,
                                        "per_dir": PER_DIR, "sampling": "trải đều theo chỉ số khung, không ngẫu nhiên",
                                        "llm_image": "PNG 192x144 -> JPEG q90 (cỡ gốc, không phóng to)"}),
               "metrics": metrics, "per_denomination": per_denom, "confusion": confusion,
               "n_images": len(items), "n_errors": sum(1 for x in per if x["error"]),
               "latency": {"ttft": common.latency_summary(ttft), "total": common.latency_summary(total)},
               "per_sample": per}
    path = common.write_result(TASK, f"{args.path}{'_limit%d' % args.limit if args.limit else ''}", payload, args.out)
    print(path)
    for k, v in metrics.items():
        print(f"{k}: {v['value']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}] n={v['n']}")
    print("latency", payload["latency"])
    for x in per:
        print(x["gt"], x.get("label"), x.get("values"), repr(x["output"]), "gate=", x["gate_reason"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="chỉ N ảnh đầu (xen kẽ giữa các mệnh giá)")
    ap.add_argument("--path", choices=["general", "ocr_spoken"], default="general")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    L.new_loop_run(run(args))


if __name__ == "__main__":
    main()
