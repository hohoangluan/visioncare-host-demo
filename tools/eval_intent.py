"""Bộ đo intent trên tập gold (`data/intent/gold_*.jsonl`).

Chạy (từ thư mục VH):
    python -m tools.eval_intent --gold data/intent/gold_dev.jsonl --backend gemma --params \
        --out results/baseline_gemma_dev.jsonl
    python -m tools.eval_intent --gold ... --backend gemma --out results/b.jsonl \
        --baseline results/baseline_gemma_dev.jsonl     # so ghép đôi (McNemar)

Vì sao có `discordant`: tập gold nhỏ (SE độ chính xác ~3-4 điểm), chênh lệch
trung bình che mất quy mô thật. So A/B phải đếm số câu BẤT ĐỒNG (A đúng B sai và
ngược lại) rồi kiểm định nhị thức, không đọc hai con số acc đứng riêng.

`action_fp` (hành động sai) là chỉ số quan trọng nhất cho người khiếm thị: đoán
vào làn D (gọi điện/nhạc/xe — có tác dụng phụ) mà sai nhãn hoặc sai tham số.
"""

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))


def _lane(intent: str | None) -> str:
    from pipeline.intent_early import LANE
    return LANE.get(intent or "", "A")


def _norm(value: str) -> str:
    from lanes import phone
    value = re.sub(r"[^\w\s]", " ", str(value).lower())
    return phone._clean(" ".join(value.split()))


def params_match(gold: dict, pred: dict) -> bool:
    """Mỗi tham số gold phải có ở pred; bằng nhau hoặc một bên chứa bên kia (sau chuẩn hoá)."""
    for key, g in (gold or {}).items():
        p = (pred or {}).get(key)
        if p is None:
            return False
        if isinstance(g, str) and isinstance(p, str):
            g, p = _norm(g), _norm(p)
            if not (g == p or (g and p and (g in p or p in g))):
                return False
        elif g != p:
            return False
    return True


def is_action_fp(gold: str, pred: str | None, gold_params: dict, pred_params: dict | None) -> bool:
    if pred is None or _lane(pred) != "D":
        return False
    if pred != gold:
        return True
    return not params_match(gold_params, pred_params or {})


def _snr(variant: str) -> int | None:
    m = re.search(r"snr(\d+)", variant or "")
    return int(m.group(1)) if m else None


def _included(row: dict, min_snr: int) -> bool:
    snr = _snr(row.get("variant", ""))
    return snr is None or snr >= min_snr


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(math.ceil(q * len(ordered))) - 1)]


def summarize(rows: list[dict], min_snr: int = 10, gate: float | None = None) -> dict:
    """Tóm tắt. Chỉ giữ dòng `clean` và STT có SNR >= `min_snr`.

    `gate`: câu làn D có confidence < gate coi là "hỏi lại" — không phải FP.
    """
    rows = [r for r in rows if _included(r, min_snr)]
    n = len(rows) or 1
    ok = sum(r["pred"] == r["gold"] for r in rows)
    by_variant: dict[str, list[bool]] = defaultdict(list)
    by_group: dict[str, list[bool]] = defaultdict(list)
    confusion: dict[str, Counter] = defaultdict(Counter)
    fp_rows, asked, lane_d = [], 0, 0
    for r in rows:
        right = r["pred"] == r["gold"]
        by_variant[r.get("variant", "")].append(right)
        by_group[r.get("group", r["id"])].append(right)
        if not right:
            confusion[r["gold"]][r["pred"] or "None"] += 1
        if _lane(r["pred"]) == "D":
            lane_d += 1
            if gate is not None and (r.get("confidence") or 0.0) < gate:
                asked += 1
                continue
        if r.get("action_fp"):
            fp_rows.append(r["id"])
    secs = [r["seconds"] * 1000 for r in rows if r.get("seconds") is not None]
    return {
        "acc": ok / n,
        "acc_by_variant": {k: sum(v) / len(v) for k, v in by_variant.items()},
        "acc_by_group_all_variants": sum(all(v) for v in by_group.values()) / max(1, len(by_group)),
        "p50_ms": _pct(secs, 0.5),
        "p90_ms": _pct(secs, 0.9),
        "confusion": {g: dict(c) for g, c in confusion.items()},
        "action_fp": len(fp_rows),
        "action_fp_rows": fp_rows,
        "ask_rate": asked / lane_d if lane_d else 0.0,
    }


def discordant(a: list[dict], b: list[dict]) -> dict:
    """McNemar chính xác: ghép theo id, nhị thức hai phía trên các cặp bất đồng."""
    bm = {r["id"]: r for r in b}
    a_only = b_only = 0
    for r in a:
        o = bm.get(r["id"])
        if o is None:
            continue
        ra, rb = r["pred"] == r["gold"], o["pred"] == o["gold"]
        a_only += ra and not rb
        b_only += rb and not ra
    n = a_only + b_only
    if n == 0:
        return {"a_only": 0, "b_only": 0, "p_value": 1.0}
    k = min(a_only, b_only)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return {"a_only": a_only, "b_only": b_only, "p_value": p}


async def _predict(row: dict, backend: str, with_params: bool) -> dict:
    from lanes import phone
    from models import clef
    from pipeline import intent_classifier
    from pipeline.intent_early import keyword_rule

    text, started = row["text"], time.monotonic()
    pred = mode = None
    web, conf = False, 0.0
    if backend == "keyword":
        hit = keyword_rule(text)
        pred, mode, conf = (hit[0], hit[1], 1.0) if hit else ("chat", "read", 0.0)
    else:
        fn = clef.classify if backend == "clef" else intent_classifier.classify
        res = await fn(text, row.get("device"))
        if res is not None:
            pred, mode, web, conf = res.intent, res.ocr_mode, res.needs_web, res.confidence
    seconds = time.monotonic() - started
    params = None
    if with_params and pred is not None:
        params = await phone.extract(pred, text)
    return {
        "id": row["id"], "group": row.get("group"), "variant": row.get("variant"),
        "gold": row["label"], "pred": pred, "ocr_mode_pred": mode, "needs_web_pred": web,
        "confidence": conf, "seconds": seconds, "params_pred": params,
        "action_fp": is_action_fp(row["label"], pred, row.get("params") or {}, params),
    }


async def run(gold: list[dict], backend: str, with_params: bool, concurrency: int) -> list[dict]:
    import config
    config.INTENT_BACKEND = {"gemma": "gemma", "clef": "clef"}.get(backend, config.INTENT_BACKEND)
    sem = asyncio.Semaphore(concurrency)

    async def one(row):
        async with sem:
            return await _predict(row, backend, with_params)

    return await asyncio.gather(*(one(r) for r in gold))


def print_report(summary: dict, top: int = 15) -> None:
    print(f"acc={summary['acc']:.3f}  p50={summary['p50_ms']:.0f}ms  p90={summary['p90_ms']:.0f}ms  "
          f"action_fp={summary['action_fp']}  ask_rate={summary['ask_rate']:.3f}  "
          f"acc_group_all_variants={summary['acc_by_group_all_variants']:.3f}")
    for k, v in summary["acc_by_variant"].items():
        print(f"  {k}: {v:.3f}")
    pairs = Counter({(g, p): n for g, c in summary["confusion"].items() for p, n in c.items()})
    print(f"top {top} cặp nhầm (gold -> pred):")
    for (g, p), n in pairs.most_common(top):
        print(f"  {n:3d}  {g} -> {p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--backend", choices=["gemma", "clef", "keyword"], default="gemma")
    ap.add_argument("--params", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--baseline")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--min-snr", type=int, default=10)
    ap.add_argument("--gate", type=float)
    args = ap.parse_args()
    gold = [json.loads(l) for l in Path(args.gold).read_text().splitlines() if l.strip()]
    rows = asyncio.run(run(gold, args.backend, args.params, args.concurrency))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print_report(summarize(rows, args.min_snr, args.gate))
    if args.baseline:
        base = [json.loads(l) for l in Path(args.baseline).read_text().splitlines() if l.strip()]
        print("so với baseline (a=mới, b=baseline):", discordant(rows, base))


if __name__ == "__main__":
    main()
