"""Tính chỉ số cho bàn đo STT câu lệnh từ kết quả của `tools/bench_stt_cmd.py run`.

    python -m tools.bench_stt_report --cache DIR --base greedy --cfgs greedy beam4 hw1.5_4 ...

Chỉ số (mỗi ô = split dev/test x điều kiện clean/snr10):
- `key`   tỉ lệ câu ĐÚNG TỪ KHOÁ LỆNH: cụm động từ lệnh khớp luật `intent_early._RULES` trên câu gốc
          VÀ tên người thân (`params.contact_name`) đều xuất hiện nguyên vẹn trong bản ghi;
- `intent` độ chính xác intent cuối qua bộ phân loại HIỆN TẠI (Gemma UIT, như pipeline) trên bản ghi;
- `wer`   WER theo từ (chữ thường, bỏ dấu câu);
- `ins`   số câu mà bản ghi CHÈN một lệnh làn C/D (luật từ khoá) mà câu gốc không có
          (FP lệnh; câu chat/không lệnh), và số câu chat bị phân loại thành hành động làn D;
- đếm câu bất đồng với baseline: sửa đúng / làm sai (kèm kiểm định nhị thức hai phía).
"""

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.bench_stt_cmd import load_manifest  # noqa: E402
from tools.bench_stt_compare import edit_distance  # noqa: E402


def norm_words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", (text or "").lower())
    return re.sub(r"[^\w\s]", " ", text).split()


def norm_str(text: str) -> str:
    return " ".join(norm_words(text))


def contains(hyp: str, phrase: str) -> bool:
    return f" {norm_str(phrase)} " in f" {norm_str(hyp)} "


def rule_span(text: str):
    """(intent, cụm khớp) của luật từ khoá đầu tiên trên câu, hoặc None."""
    from pipeline.intent_early import _RULES

    lowered = (text or "").lower()
    for pattern, intent, _ in _RULES:
        m = pattern.search(lowered)
        if m:
            return intent, m.group(0)
    return None


def keys_of(row: dict) -> list[str]:
    keys = []
    hit = rule_span(row["text"])
    if hit and row["label"] != "chat":
        keys.append(hit[1])
    name = (row.get("params") or {}).get("contact_name")
    if name and row["label"] in ("contact_call", "message_send"):
        keys.append(name)
    return keys


def pipeline_text(hyp: str) -> str:
    from pipeline import stt

    return stt._normalize(hyp)


# ── phân loại intent có bộ nhớ đệm ────────────────────────────────────────

class IntentCache:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    @staticmethod
    def key(text: str, device: dict) -> str:
        return text + "|" + json.dumps(device or {}, sort_keys=True)

    async def fill(self, items: set[tuple[str, str]], concurrency: int = 6) -> None:
        from pipeline import intent_classifier

        todo = [(t, d) for t, d in items if self.key(t, json.loads(d)) not in self.data]
        sem = asyncio.Semaphore(concurrency)

        async def one(text, dev_json):
            async with sem:
                device = json.loads(dev_json)
                for attempt in range(3):
                    try:
                        res = await intent_classifier.classify(text, device)
                        break
                    except Exception:  # noqa: BLE001
                        res = None
                        await asyncio.sleep(1 + attempt)
                self.data[self.key(text, device)] = res.intent if res is not None else None

        await asyncio.gather(*(one(t, d) for t, d in todo))
        self.path.write_text(json.dumps(self.data, ensure_ascii=False))

    def get(self, text: str, device: dict):
        return self.data.get(self.key(text, device))


def load_results(cache: Path, cfg: str) -> dict[str, dict]:
    p = cache / "results" / f"{cfg}.jsonl"
    return {r["id"]: r for r in map(json.loads, p.read_text(encoding="utf-8").splitlines()) if r}


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(q * len(s)) - 1)]


def sign_p(a_only: int, b_only: int) -> float:
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--base", default="greedy")
    ap.add_argument("--cfgs", nargs="+", required=True)
    ap.add_argument("--json")
    ap.add_argument("--no-intent", action="store_true")
    args = ap.parse_args()
    cache = Path(args.cache)
    rows = load_manifest(cache, ("cmd", "vietmed"))
    by_id = {r["id"]: r for r in rows}
    cmd_rows = [r for r in rows if r["set"] == "cmd"]
    vm_rows = [r for r in rows if r["set"] == "vietmed"]
    results = {c: load_results(cache, c) for c in args.cfgs}
    ic = IntentCache(cache / "intent_cache.json")

    if not args.no_intent:
        items = set()
        for c in args.cfgs:
            for r in cmd_rows:
                h = results[c].get(r["id"])
                if h is not None:
                    items.add((pipeline_text(h["hyp"]), json.dumps(r.get("device") or {}, sort_keys=True)))
        for r in cmd_rows:  # trần: văn bản gốc
            items.add((r["text"], json.dumps(r.get("device") or {}, sort_keys=True)))
        asyncio.run(ic.fill(items))

    cells = [(s, c) for s in ("dev", "test") for c in ("clean", "snr10")]

    def per_row(cfg: str) -> dict[str, dict]:
        out = {}
        for r in cmd_rows:
            h = results[cfg].get(r["id"])
            if h is None:
                continue
            hyp = h["hyp"]
            ref_w, hyp_w = norm_words(r["text"]), norm_words(hyp)
            keys = keys_of(r)
            rec = {"split": r["split"], "cond": r["cond"], "label": r["label"],
                   "err": edit_distance(ref_w, hyp_w), "nref": len(ref_w), "ms": h["ms"],
                   "has_key": bool(keys), "key_ok": bool(keys) and all(contains(hyp, k) for k in keys),
                   "exact": ref_w == hyp_w}
            name = (r.get("params") or {}).get("contact_name")
            rec["has_name"] = bool(name and r["label"] in ("contact_call", "message_send"))
            rec["name_ok"] = rec["has_name"] and contains(hyp, name)
            ref_rule, hyp_rule = rule_span(r["text"]), rule_span(hyp)
            from pipeline.intent_early import LANE
            hr = hyp_rule[0] if hyp_rule else None
            rr = ref_rule[0] if ref_rule else None
            rec["ins"] = bool(hr and LANE.get(hr) in ("C", "D") and hr != rr)
            if not args.no_intent:
                pred = ic.get(pipeline_text(hyp), r.get("device") or {})
                rec["pred"] = pred
                rec["intent_ok"] = pred == r["label"]
                rec["chat_to_action"] = r["label"] == "chat" and LANE.get(pred or "", "A") == "D"
            out[r["id"]] = rec
        return out

    rep: dict = {}
    for cfg in args.cfgs:
        pr = per_row(cfg)
        rep[cfg] = {"rows": pr}
    base_rows = rep[args.base]["rows"] if args.base in rep else per_row(args.base)

    def fmt_pct(n, d):
        return f"{100 * n / d:5.1f}" if d else "  -  "

    print(f"\n## Bàn đo câu lệnh (n clip: {len(cmd_rows)}; tổng {sum(1 for r in cmd_rows if r['split'] == 'dev')} dev / "
          f"{sum(1 for r in cmd_rows if r['split'] == 'test')} test)\n")
    for metric, title in (("key", "Đúng từ khoá lệnh (%)"), ("name", "Đúng tên người thân (%)"),
                          ("intent", "Intent cuối đúng (%)"), ("wer", "WER (%)"), ("exact", "Câu đúng nguyên văn (%)")):
        print(f"### {title}\n")
        print("| cfg | " + " | ".join(f"{s}-{c}" for s, c in cells) + " |")
        print("|---|" + "---:|" * len(cells))
        for cfg in args.cfgs:
            cols = []
            for s, c in cells:
                sel = [x for x in rep[cfg]["rows"].values() if x["split"] == s and x["cond"] == c]
                if metric == "key":
                    sel = [x for x in sel if x["has_key"]]
                    cols.append(fmt_pct(sum(x["key_ok"] for x in sel), len(sel)))
                elif metric == "name":
                    sel = [x for x in sel if x["has_name"]]
                    cols.append(fmt_pct(sum(x["name_ok"] for x in sel), len(sel)))
                elif metric == "intent":
                    cols.append(fmt_pct(sum(x.get("intent_ok", False) for x in sel), len(sel)))
                elif metric == "wer":
                    cols.append(fmt_pct(sum(x["err"] for x in sel), sum(x["nref"] for x in sel)))
                else:
                    cols.append(fmt_pct(sum(x["exact"] for x in sel), len(sel)))
            print(f"| {cfg} | " + " | ".join(cols) + " |")
        print()
    # n mẫu số
    print("mẫu số: " + ", ".join(
        f"{s}-{c}: key {sum(1 for x in rep[args.cfgs[0]]['rows'].values() if x['split'] == s and x['cond'] == c and x['has_key'])}"
        f" / name {sum(1 for x in rep[args.cfgs[0]]['rows'].values() if x['split'] == s and x['cond'] == c and x['has_name'])}"
        f" / all {sum(1 for x in rep[args.cfgs[0]]['rows'].values() if x['split'] == s and x['cond'] == c)}"
        for s, c in cells) + "\n")

    print("### Chèn lệnh bừa (FP) và câu chat thành hành động\n")
    print("| cfg | ins_total | ins_chat | chat->action (Gemma) |")
    print("|---|---:|---:|---:|")
    for cfg in args.cfgs:
        v = rep[cfg]["rows"].values()
        print(f"| {cfg} | {sum(x['ins'] for x in v)} | {sum(x['ins'] for x in v if x['label'] == 'chat')} | "
              f"{sum(x.get('chat_to_action', False) for x in v)} |")
    print()

    print("### Bất đồng so với baseline (sửa đúng / làm sai), cộng cả 4 ô\n")
    print("| cfg | key +/- (p) | name +/- (p) | intent +/- (p) | exact +/- (p) |")
    print("|---|---|---|---|---|")
    for cfg in args.cfgs:
        if cfg == args.base:
            continue
        parts = []
        for field, need in (("key_ok", "has_key"), ("name_ok", "has_name"), ("intent_ok", None), ("exact", None)):
            fixed = broke = 0
            for i, x in rep[cfg]["rows"].items():
                b = base_rows.get(i)
                if b is None or (need and not x[need]):
                    continue
                fixed += bool(x.get(field)) and not b.get(field)
                broke += bool(b.get(field)) and not x.get(field)
            parts.append(f"+{fixed}/-{broke} (p={sign_p(fixed, broke):.3f})")
        print(f"| {cfg} | " + " | ".join(parts) + " |")
    print()

    print("### Bất đồng theo ô (key +/-, intent +/-) so với baseline\n")
    print("| cfg | " + " | ".join(f"{s}-{c}" for s, c in cells) + " |")
    print("|---|" + "---|" * len(cells))
    for cfg in args.cfgs:
        if cfg == args.base:
            continue
        cols = []
        for s, c in cells:
            kf = kb = inf = inb = 0
            for i, x in rep[cfg]["rows"].items():
                if x["split"] != s or x["cond"] != c:
                    continue
                b = base_rows.get(i)
                if b is None:
                    continue
                if x["has_key"]:
                    kf += x["key_ok"] and not b["key_ok"]
                    kb += b["key_ok"] and not x["key_ok"]
                inf += bool(x.get("intent_ok")) and not b.get("intent_ok")
                inb += bool(b.get("intent_ok")) and not x.get("intent_ok")
            cols.append(f"k +{kf}/-{kb}, i +{inf}/-{inb}")
        print(f"| {cfg} | " + " | ".join(cols) + " |")
    print()

    print("### Trễ giải mã lượt cuối (ms, min của các lần lặp, 1 luồng xử lý) và chi phí partial\n")
    print("| cfg | cmd p50 | cmd p90 | cmd mean | vietmed p50 | vietmed p90 | partial: số lượt giải | partial: tổng ms/câu |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cfg in args.cfgs:
        cm = [results[cfg][r["id"]]["ms"] for r in cmd_rows if r["id"] in results[cfg]]
        vm = [results[cfg][r["id"]]["ms"] for r in vm_rows if r["id"] in results[cfg]]
        pj = cache / "results" / f"{cfg}.partial.json"
        part = json.loads(pj.read_text()) if pj.exists() else []
        calls = statistics.mean(p["calls"] for p in part) if part else 0
        tot = statistics.mean(p["total_ms"] for p in part) if part else 0
        print(f"| {cfg} | {pct(cm, .5):.0f} | {pct(cm, .9):.0f} | {statistics.mean(cm) if cm else 0:.0f} | "
              f"{pct(vm, .5):.0f} | {pct(vm, .9):.0f} | {calls:.1f} | {tot:.0f} |")
    print()

    print(f"## VietMed (giọng thật, {len(vm_rows)} clip)\n")
    print("| cfg | WER % | Bắc | Trung | Nam | chèn từ-lệnh (cụm hotword có ở hyp, không có ở ref) | chèn lệnh làn C/D (luật) |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    from pipeline.intent_early import LANE
    from tools.bench_stt_cmd import COMMAND_HOTWORDS

    long_hw = [w.lower() for w in COMMAND_HOTWORDS if len(w.split()) >= 2]
    vm_detail = {}
    for cfg in args.cfgs:
        err = ref = 0
        grp = defaultdict(lambda: [0, 0])
        ins_hw = ins_rule = 0
        for r in vm_rows:
            h = results[cfg].get(r["id"])
            if h is None:
                continue
            rw, hw_ = norm_words(r["text"]), norm_words(h["hyp"])
            e = edit_distance(rw, hw_)
            err += e
            ref += len(rw)
            grp[r["accent"]][0] += e
            grp[r["accent"]][1] += len(rw)
            ins_hw += sum(1 for w in long_hw if contains(h["hyp"], w) and not contains(r["text"], w))
            hr = rule_span(h["hyp"])
            rr = rule_span(r["text"])
            ins_rule += bool(hr and LANE.get(hr[0]) in ("C", "D") and (not rr or rr[0] != hr[0]))
            vm_detail.setdefault(cfg, {})[r["id"]] = e
        gs = {k: 100 * v[0] / max(v[1], 1) for k, v in grp.items()}
        print(f"| {cfg} | {100 * err / max(ref, 1):.2f} | {gs.get('Bắc', 0):.1f} | {gs.get('Trung', 0):.1f} | "
              f"{gs.get('Nam', 0):.1f} | {ins_hw} | {ins_rule} |")
    print()
    base_vm = vm_detail.get(args.base)
    if base_vm:
        print("### VietMed: số clip sửa đúng / làm sai (số lỗi từ giảm/tăng) so với baseline\n")
        for cfg in args.cfgs:
            if cfg == args.base:
                continue
            better = sum(1 for i, e in vm_detail[cfg].items() if e < base_vm[i])
            worse = sum(1 for i, e in vm_detail[cfg].items() if e > base_vm[i])
            print(f"- {cfg}: {better} clip tốt hơn, {worse} clip tệ hơn (p={sign_p(better, worse):.3f}), "
                  f"Δlỗi từ = {sum(vm_detail[cfg].values()) - sum(base_vm.values()):+d}")
        print()
    if args.json:
        slim = {c: {"rows": v["rows"]} for c, v in rep.items()}
        Path(args.json).write_text(json.dumps(slim, ensure_ascii=False))


if __name__ == "__main__":
    main()
