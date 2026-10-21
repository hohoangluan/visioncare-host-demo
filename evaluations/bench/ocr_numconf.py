"""Độ tin cậy CHỮ SỐ (2026-10-21): xác suất token các chữ số Gemma sinh ra có tách được số đọc đúng và số đọc sai không?

Nếu tách được thì làn đọc chữ có một núm vặn τ: chữ số nào có xác suất < τ thì không nói con số như sự thật mà báo
"chưa chắc, đưa lại gần" — không tốn thêm lượt gọi. Ở đây chỉ ĐO tín hiệu (AUROC) và quét τ trên tập DEV:
  - SROIE train (120 hoá đơn, seed 0) × {tổng tiền, ngày} — cùng mẫu với `ocr_sroie --split dev`;
  - ViTextVQA dev: 200 câu có đáp án chứa số (seed 0).
Gọi `llm.complete_raw` không stream, cùng prompt "hỏi về chữ" và cùng ảnh 1600 px như `ocr_sroie`/`ocr_vitextvqa`.

    python -m bench.ocr_numconf [--limit N]
"""

import argparse
import asyncio
import json
import math
import os
import re
import time

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402
from bench import ocr_sroie, ocr_vitextvqa  # noqa: E402

TASK = "ocr_numconf"
TAUS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99)


def digit_conf(choice: dict) -> float | None:
    """Xác suất NHỎ NHẤT trong các token có chữ số (None nếu câu trả lời không có chữ số)."""
    items = (choice.get("logprobs") or {}).get("content") or []
    ps = [math.exp(it["logprob"]) for it in items if re.search(r"\d", it.get("token", "")) and it.get("logprob") is not None]
    return min(ps) if ps else None


def auroc(pos: list[float], neg: list[float]) -> float | None:
    """P(điểm của ca ĐÚNG > điểm của ca SAI); hoà = ½."""
    if not pos or not neg:
        return None
    p, n = np.array(pos)[:, None], np.array(neg)[None, :]
    return float(((p > n) + 0.5 * (p == n)).mean())


async def ask(jpeg: bytes, question: str) -> dict:
    import config
    from models import llm
    from pipeline.image_buffer import resize_jpeg
    image = resize_jpeg(jpeg, config.LLM_OCR_IMAGE_MAX_SIDE, 90)
    t = time.monotonic()
    for attempt in range(3):
        try:
            choice = await llm.complete_raw([llm.user_message(L.ask_prompt(question), image)], max_tokens=120,
                                            temperature=0.0, logprobs=True, top_logprobs=1)
            return {"text": (choice["message"].get("content") or "").strip(), "conf": digit_conf(choice),
                    "ms": 1000 * (time.monotonic() - t)}
        except Exception as exc:  # noqa: BLE001
            err = repr(exc)
            await asyncio.sleep(1 + attempt)
    return {"error": err}


async def run(args):
    import pandas as pd
    cache = L.Cache(TASK, L.cfg_hash({"task": TASK, "ask": L.ASK_TEMPLATE_FOR_HASH(), "v": 1}),
                    name="cache.jsonl" if args.split == "dev" else "cache_test.jsonl")
    jobs = []
    if args.split == "dev":
        df = pd.read_parquet(ocr_sroie.PARQUET.replace("test-", "train-")).sample(n=120, random_state=0)
    else:  # test: đủ 361 hoá đơn SROIE test, ViTextVQA test
        df = pd.read_parquet(ocr_sroie.PARQUET)
    for _, r in df.iterrows():
        ent = r["entities"]
        for kind, q in (("total", ocr_sroie.Q_TOTAL), ("date", ocr_sroie.Q_DATE)):
            gt = ocr_sroie.parse_total(ent.get("total", "")) if kind == "total" else ocr_sroie.parse_date(ent.get("date", ""))
            if gt is not None:
                jobs.append({"key": f"sroie|{r['key']}|{kind}", "src": "sroie", "kind": kind, "q": q, "gt": gt,
                             "jpeg": lambda b=r["image"]["bytes"]: L.to_jpeg(b)})
    d = json.load(open(os.path.join(ocr_vitextvqa.DIR, f"{args.split}.json"), encoding="utf-8"))
    fn = {im["id"]: im["filename"] for im in d["images"]}
    groups = {}
    for a in d["annotations"]:
        groups.setdefault((a["image_id"], a["question"]), set()).update(a["answers"])
    num = [{"image_id": i, "question": q, "answers": sorted(a)} for (i, q), a in sorted(groups.items())
           if any(L.digit_tokens(ocr_vitextvqa.canon(x)) for x in a)]
    for it in common.sample(num, 200, seed=0):
        path = os.path.join(ocr_vitextvqa.DIR, "images", fn[it["image_id"]])
        jobs.append({"key": f"vtq|{it['image_id']}|{it['question']}", "src": "vitextvqa", "q": it["question"],
                     "gt": it["answers"], "jpeg": lambda p=path: L.to_jpeg(open(p, "rb").read())})
    if args.limit:
        jobs = jobs[: args.limit]
    per = []
    for i, j in enumerate(jobs):
        hit = cache.get(j["key"])
        if hit is None:
            hit = await ask(j["jpeg"](), j["q"])
            if "error" not in hit:
                cache.put(j["key"], hit)
        if "error" in hit:
            per.append({"key": j["key"], "error": hit["error"]})
            continue
        if j["src"] == "sroie":
            label, _ = ocr_sroie.classify(j["kind"], hit["text"], j["gt"])
            wrong, right = label == "wrong", label == "correct"
        else:
            s = ocr_vitextvqa.score(hit["text"], j["gt"])
            wrong, right = bool(s["fabricated_number"]), bool(s["contains"]) and not s["fabricated_number"]
        per.append({"key": j["key"], "src": j["src"], "text": hit["text"], "conf": hit["conf"], "ms": hit["ms"],
                    "wrong": wrong, "right": right})
        if (i + 1) % 50 == 0:
            print(f"[{i + 1}/{len(jobs)}]", flush=True)
    out = {}
    for src in ("sroie", "vitextvqa", "all"):
        rows = [x for x in per if not x.get("error") and (src == "all" or x["src"] == src) and x["conf"] is not None]
        pos = [x["conf"] for x in rows if x["right"]]
        neg = [x["conf"] for x in rows if x["wrong"]]
        sweep = []
        for tau in TAUS:
            spoken = [x for x in rows if x["conf"] >= tau]
            sweep.append({"tau": tau, "wrong_spoken": sum(x["wrong"] for x in spoken) / len(rows) if rows else None,
                          "right_spoken": sum(x["right"] for x in spoken) / len(rows) if rows else None,
                          "hedged": 1 - len(spoken) / len(rows) if rows else None,
                          "wrong_caught": sum(x["wrong"] and x["conf"] < tau for x in rows) / max(1, len(neg))})
        out[src] = {"n_with_digits": len(rows), "n_right": len(pos), "n_wrong": len(neg), "auroc": auroc(pos, neg),
                    "base_wrong": len(neg) / len(rows) if rows else None, "sweep": sweep}
    lat = common.latency_summary([x["ms"] for x in per if not x.get("error")])
    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "split": args.split}),
               "result": out, "latency_total": lat, "n_errors": sum(1 for x in per if x.get("error")), "per_sample": per}
    path = common.write_result(TASK, args.split, payload, None)
    print(path)
    for src, r in out.items():
        print(f"== {src}: n={r['n_with_digits']} đúng {r['n_right']} sai {r['n_wrong']} AUROC {r['auroc']}")
        for s in r["sweep"]:
            print(f"  tau {s['tau']:<5} nói sai {100 * s['wrong_spoken']:5.1f} %  nói đúng {100 * s['right_spoken']:5.1f} %  "
                  f"rào 'chưa chắc' {100 * s['hedged']:5.1f} %  bắt được {100 * s['wrong_caught']:5.1f} % ca sai")
    print("latency", lat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    L.new_loop_run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
