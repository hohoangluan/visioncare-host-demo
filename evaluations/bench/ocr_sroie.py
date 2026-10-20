"""C2b — OCR 'hỏi về chữ': số tiền và ngày trên SROIE test (METRICS.md C2b). python -m bench.ocr_sroie [--limit N]

Mỗi hoá đơn 2 câu hỏi tiếng Việt; đường chạy = `ocr_live.spoken(jpeg, "ask", ...)` với prompt `llm_common.ask_prompt`
(VH chưa có đường production riêng cho 'hỏi về chữ' — xem results/llm_NOTES.md).
Phân loại mỗi câu: đúng / nói sai / từ chối / không phân tích được.
"""

import argparse
import os
import re

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402

TASK = "ocr_sroie"
PARQUET = os.path.join(common.DATAS, "sroie", "data", "test-00000-of-00001.parquet")
Q_TOTAL = "Tổng số tiền phải trả trên hoá đơn này là bao nhiêu?"
Q_DATE = "Hoá đơn này ghi ngày nào?"

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
          "oct": 10, "nov": 11, "dec": 12}


# ------------------------------------------------------------ chuẩn hoá giá trị


def to_float(tok: str) -> float | None:
    """'1,234.50' / '1.234,50' / '193.00' / '193' / '1.234' (nhóm 3 chữ số, đầu <= 3 chữ số => phân nghìn)."""
    tok = tok.strip().rstrip(".,")
    if not tok:
        return None
    if "," in tok and "." in tok:
        tok = tok.replace(".", "").replace(",", ".") if tok.rfind(",") > tok.rfind(".") else tok.replace(",", "")
    elif "," in tok or "." in tok:
        sep = "," if "," in tok else "."
        parts = tok.split(sep)
        if len(parts) > 2 or (len(parts[-1]) == 3 and 1 <= len(parts[0]) <= 3 and parts[0] != "0"):
            tok = "".join(parts)
        else:
            tok = tok.replace(sep, ".")
    try:
        return float(tok)
    except ValueError:
        return None


_NUM_TOK = re.compile(r"\d[\d.,]*")


def parse_total(text: str) -> float | None:
    """Số ĐẦU TIÊN trong câu trả lời (phương pháp ghi trong NOTES)."""
    m = _NUM_TOK.search(text or "")
    return to_float(m.group(0)) if m else None


def _year(y: str) -> int:
    v = int(y)
    return v + 2000 if v < 100 else v


def parse_date(text: str) -> tuple[int, int, int] | None:
    """(ngày, tháng, năm) từ nhiều định dạng: dd/mm/yy(yy) (sep / . - hoặc cách), yyyy-mm-dd, dd MON yy(yy),
    'ngày D tháng M năm Y'. Mơ hồ ngày/tháng: hoá đơn Malaysia dùng d/m/y nên đọc theo d/m/y."""
    s = (text or "").lower()
    m = re.search(r"ng[àa]y\s*(\d{1,2})\s*th[áa]ng\s*(\d{1,2})\s*n[ăa]m\s*(\d{2,4})", s)
    if m:
        return int(m[1]), int(m[2]), _year(m[3])
    m = re.search(r"(?<!\d)(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})(?!\d)", s)
    if m:
        return int(m[3]), int(m[2]), int(m[1])
    m = re.search(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})(?!\d)", s)
    if m:
        d, mo = int(m[1]), int(m[2])
        if mo > 12 >= d:
            d, mo = mo, d
        return d, mo, _year(m[3])
    m = re.search(r"(?<!\d)(\d{1,2})[\s\-/.,]*([a-z]{3,9})[\s\-/.,]*(\d{4}|\d{2})(?!\d)", s)
    if m and m[2][:3] in MONTHS:
        return int(m[1]), MONTHS[m[2][:3]], _year(m[3])
    return None


def classify(kind: str, out_text: str, gt) -> tuple[str, object]:
    """-> (nhãn, giá trị đã parse). Nhãn: correct / wrong / refused / unparsed."""
    val = parse_total(out_text) if kind == "total" else parse_date(out_text)
    if val is None:
        return ("refused" if L.is_refusal(out_text) else "unparsed"), None
    ok = abs(val - gt) <= 0.005 if kind == "total" else val == gt
    return ("correct" if ok else "wrong"), val


# ------------------------------------------------------------ chạy


async def run(args):
    import pandas as pd
    import config
    from models.ocr import prompts

    cfg_parts = {"task": TASK, "ask_template": L.ASK_TEMPLATE_FOR_HASH(), "common": prompts._COMMON}
    cache = L.Cache(TASK, L.cfg_hash(cfg_parts))
    df = pd.read_parquet(PARQUET)
    if args.limit:
        df = df.iloc[: args.limit]
    rows = []
    for _, r in df.iterrows():
        ent = r["entities"]
        gt_date, gt_total = parse_date(ent.get("date", "")), parse_total(ent.get("total", ""))
        rows.append({"key": r["key"], "jpeg": L.to_jpeg(r["image"]["bytes"]), "date_raw": ent.get("date"),
                     "total_raw": ent.get("total"), "gt_date": gt_date, "gt_total": gt_total})
    jobs = [(r, "total", Q_TOTAL) for r in rows] + [(r, "date", Q_DATE) for r in rows]
    # xen kẽ theo hoá đơn cho dễ theo dõi: total, date của cùng ảnh liền nhau
    jobs = [j for pair in zip(jobs[: len(rows)], jobs[len(rows):]) for j in pair]

    res = await L.run_items(jobs, lambda j: f"{j[0]['key']}:{j[1]}",
                            lambda j: L.ask_spoken(j[0]["jpeg"], j[2]), cache, TASK)

    per, ttft, total_ms = [], [], []
    for r, kind, q in jobs:
        out = res[f"{r['key']}:{kind}"]
        gt = r["gt_total"] if kind == "total" else r["gt_date"]
        row = {"key": r["key"], "field": kind, "question": q, "gt_raw": r["total_raw"] if kind == "total" else r["date_raw"],
               "gt_norm": gt, "output": out["text"], "ttft_ms": out.get("ttft_ms"), "total_ms": out.get("total_ms"),
               "error": out.get("error"), "cached": out["cached"]}
        if "error" not in out:
            row["label"], row["parsed"] = classify(kind, out["text"], gt) if gt is not None else ("gt_unparsed", None)
            ttft.append(out["ttft_ms"])
            total_ms.append(out["total_ms"])
        per.append(row)

    metrics = {}
    for kind in ("total", "date"):
        sel = [x for x in per if x["field"] == kind and not x["error"] and x["label"] != "gt_unparsed"]
        if not sel:
            continue
        lab = lambda name: np.array([x["label"] == name for x in sel], dtype=float)  # noqa: E731
        metrics[f"{kind}_em"] = L.ci_entry(lab("correct"))
        metrics[f"{kind}_wrong_rate"] = L.ci_entry(lab("wrong"))
        metrics[f"{kind}_refusal_rate"] = L.ci_entry(lab("refused"))
        metrics[f"{kind}_unparsed_rate"] = L.ci_entry(lab("unparsed"))
        metrics[f"{kind}_wrong_given_answered"] = L.ci_entry(
            np.stack([lab("wrong"), lab("wrong") + lab("correct")], 1), L.ratio_stat)
    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "cfg_hash": cache.cfg, "questions": [Q_TOTAL, Q_DATE],
                                        "ask_template": L.ASK_TEMPLATE_FOR_HASH(), "llm_max_tokens": 1024, "temperature": 0.0,
                                        "first_sentence_max_words": config.FIRST_SENTENCE_MAX_WORDS,
                                        "method": "total = số đầu tiên trong câu trả lời, so ±0,005; date = ngày đầu tiên parse được, so (d,m,y)"}),
               "metrics": metrics, "n_receipts": len(rows), "n_errors": sum(1 for x in per if x["error"]),
               "n_gt_unparsed": sum(1 for x in per if x.get("label") == "gt_unparsed"),
               "latency": {"ttft": common.latency_summary(ttft), "total": common.latency_summary(total_ms)},
               "per_sample": per}
    path = common.write_result(TASK, f"ask_spoken{'_limit%d' % args.limit if args.limit else ''}", payload, args.out)
    print(path)
    for k, v in metrics.items():
        print(f"{k}: {v['value']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}] n={v['n']}")
    print("latency", payload["latency"])
    for x in per:
        print(x["key"], x["field"], x.get("label"), repr(x["output"]), "GT", x["gt_raw"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="chỉ N hoá đơn đầu (2 câu/hoá đơn)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    L.new_loop_run(run(args))


if __name__ == "__main__":
    main()
