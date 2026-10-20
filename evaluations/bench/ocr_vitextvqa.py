"""C2c — OCR hỏi đáp tiếng Việt trên ViTextVQA test (METRICS.md C2c). python -m bench.ocr_vitextvqa [--limit N]

Mẫu: 300 câu hỏi (nhóm theo (image_id, question); nhiều dòng annotation cùng câu hỏi = nhiều đáp án chấp nhận được,
lấy max qua các đáp án) bằng `sample(seed=0)`. Chạy `ocr_live.spoken(jpeg, "ask", ...)` + `llm_common.ask_prompt`.
Metric bài gốc (arXiv 2404.10652 mục 5.4): EM, F1 theo token; thêm 'đáp án nằm trong câu trả lời', bịa số, từ chối.
"""

import argparse
import json
import os
import re
from collections import Counter, defaultdict

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402

TASK = "ocr_vitextvqa"
DIR = os.path.join(common.DATAS, "vitextvqa")


def load_questions() -> list[dict]:
    d = json.load(open(os.path.join(DIR, "test.json"), encoding="utf-8"))
    fn = {im["id"]: im["filename"] for im in d["images"]}
    groups: dict[tuple, list[str]] = defaultdict(list)
    for a in d["annotations"]:
        groups[(a["image_id"], a["question"])].extend(a["answers"])
    items = [{"image_id": iid, "filename": fn[iid], "question": q, "answers": sorted(set(ans))}
             for (iid, q), ans in sorted(groups.items())]
    return items


_DIGIT_SEP = re.compile(r"(?<=\d)\s*[.,]\s*(?=\d)")


def canon(s: str) -> str:
    """Nối chữ số qua dấu . hoặc , ("0938 . 938 . 616" và "0938.938.616" -> "0938938616"): nhãn ViTextVQA đã tách token
    có khoảng trắng quanh dấu, còn LLM viết liền — bỏ dấu phân nghìn/phân nhóm ở cả hai phía cho công bằng."""
    return _DIGIT_SEP.sub("", s or "")


def f1_tokens(pred: str, gold: str) -> float:
    p, g = L.words(canon(pred)), L.words(canon(gold))
    if not p or not g:
        return float(p == g)
    common_n = sum((Counter(p) & Counter(g)).values())
    if common_n == 0:
        return 0.0
    pr, rc = common_n / len(p), common_n / len(g)
    return 2 * pr * rc / (pr + rc)


def contains(pred: str, gold: str) -> bool:
    g = L.strip_punct(canon(gold))
    return bool(g) and f" {g} " in f" {L.strip_punct(canon(pred))} "


def score(pred: str, golds: list[str]) -> dict:
    refused = L.is_refusal(pred)
    ps = L.strip_punct(canon(pred))
    em = max(float(ps == L.strip_punct(canon(g))) for g in golds)
    f1 = max(f1_tokens(pred, g) for g in golds)
    inc = max(float(contains(pred, g)) for g in golds)
    gold_digits = {t for g in golds for t in L.digit_tokens(canon(g))}
    pred_digits = set(L.digit_tokens(canon(pred)))
    gt_has_num = bool(gold_digits)
    # bịa số: GT có số, câu trả lời nêu ít nhất một chuỗi số KHÔNG nằm trong số của GT (và không phải từ chối)
    fabricated = float(gt_has_num and not refused and bool(pred_digits - gold_digits))
    return {"em": em, "f1": f1, "contains": inc, "refused": float(refused), "gt_has_number": gt_has_num,
            "fabricated_number": fabricated}


async def run(args):
    import config
    from models.ocr import prompts
    cfg_parts = {"task": TASK, "ask_template": L.ASK_TEMPLATE_FOR_HASH(), "common": prompts._COMMON}
    cache = L.Cache(TASK, L.cfg_hash(cfg_parts))
    allq = load_questions()
    items = common.sample(allq, 300, seed=0)
    if args.limit:
        items = items[: args.limit]

    def key(it):
        return f"{it['image_id']}|{it['question']}"

    def factory(it):
        with open(os.path.join(DIR, "images", it["filename"]), "rb") as f:
            jpeg = L.to_jpeg(f.read())
        return L.ask_spoken(jpeg, it["question"])

    res = await L.run_items(items, key, factory, cache, TASK)
    per, ttft, total = [], [], []
    for it in items:
        r = res[key(it)]
        row = {**it, "output": r["text"], "ttft_ms": r.get("ttft_ms"), "total_ms": r.get("total_ms"),
               "error": r.get("error"), "cached": r["cached"]}
        if "error" not in r:
            row.update(score(r["text"], it["answers"]))
            ttft.append(r["ttft_ms"])
            total.append(r["total_ms"])
        per.append(row)
    ok = [x for x in per if not x["error"]]
    A = lambda rows, k: np.array([x[k] for x in rows], dtype=float)  # noqa: E731
    metrics = {}
    if ok:
        metrics = {"em": L.ci_entry(A(ok, "em")), "f1": L.ci_entry(A(ok, "f1")),
                   "answer_contained": L.ci_entry(A(ok, "contains")), "refusal_rate": L.ci_entry(A(ok, "refused"))}
        withnum = [x for x in ok if x["gt_has_number"]]
        if withnum:
            metrics["fabricated_number_when_gt_has_number"] = L.ci_entry(A(withnum, "fabricated_number"))
    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "cfg_hash": cache.cfg, "sample": 300, "seed": 0,
                                        "n_question_groups_total": len(allq), "ask_template": L.ASK_TEMPLATE_FOR_HASH(),
                                        "llm_max_tokens": 1024, "temperature": 0.0,
                                        "first_sentence_max_words": config.FIRST_SENTENCE_MAX_WORDS}),
               "metrics": metrics, "n_questions": len(items), "n_errors": sum(1 for x in per if x["error"]),
               "latency": {"ttft": common.latency_summary(ttft), "total": common.latency_summary(total)},
               "per_sample": per}
    path = common.write_result(TASK, f"ask_spoken{'_limit%d' % args.limit if args.limit else ''}", payload, args.out)
    print(path)
    for k, v in metrics.items():
        print(f"{k}: {v['value']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}] n={v['n']}")
    print("latency", payload["latency"])
    for x in per:
        print(x["filename"], x["question"], "|", x["answers"], "|", repr(x["output"]), x.get("em"), x.get("f1"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="chỉ N câu đầu của mẫu 300")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    L.new_loop_run(run(args))


if __name__ == "__main__":
    main()
