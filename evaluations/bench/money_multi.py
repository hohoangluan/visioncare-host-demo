"""C3 — đọc tiền: nhờ Gemma nhiều hơn khi ảnh khó (2026-10-21). python -m bench.money_multi [--split dev|test] [--limit N]

So trên CÙNG ảnh, gọi MỚI (không cache, để đo trễ thật), cấu hình production `read_money.choice_messages`:
  A  1 khung: chọn nhãn + xác suất (cấu hình đang chọn, τ quét).
  B  3 khung song song (khung i, i−3, i+3 của cùng video — kính truyền khung liên tục): điểm nhãn = trung bình xác suất
     các khung chọn nhãn đó; nói nếu điểm ≥ τ. Trễ = khung chậm nhất (asyncio.gather).
  C  tầng 2: khung i có xác suất < 0,995 thì gọi `look_closer` (Gemma ghi quan sát rồi chọn nhãn) — ĐÃ LOẠI 2026-10-21
     (dev: không đọc thêm được ca nào, trễ p90 768 ms), giữ ở đây để chạy lại được;
     nói nếu xác suất tầng 2 ≥ τ2. Trễ = tầng 1 (+ tầng 2 nếu leo thang).
Ghi results/money_vnd/<ts>_multi_<split>.json + bảng quét τ.
"""

import argparse
import asyncio
import os
import time

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402
from bench import money_vnd as M  # noqa: E402

TAUS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999)
DELTA = 3
TAU1 = 0.995  # ngưỡng tầng 1 đã chọn (bench.money_vnd --path choice, dev)


_LOOK_PROMPT = (
    "Ảnh tờ tiền này khó đọc (có thể nghiêng, nhoè, bị tay che). Hãy QUAN SÁT KỸ trước khi kết luận: "
    "con số in to, dòng chữ mệnh giá in trên tờ, chất liệu (polymer trong suốt hay giấy cotton), màu chủ đạo, "
    "hình in. Ghi quan sát vào trường quan_sat (tối đa 25 từ), rồi chọn nhãn. Không đủ dấu hiệu thì chọn "
    "\"không rõ\"."
)
_LOOK_SCHEMA = {
    "type": "object",
    "properties": {"quan_sat": {"type": "string", "maxLength": 160}, "nhan": {"type": "string", "enum": None}},
    "required": ["quan_sat", "nhan"],
}


async def look_closer(image: bytes) -> tuple[str, float | None, str]:
    """Tầng 2 cho ca xác suất thấp: Gemma ghi quan sát rồi mới chọn nhãn. -> (nhãn, xác suất nhãn, quan sát)."""
    import json
    from handlers import read_money as R
    from lanes import general
    from models import llm
    from models.llm.client import value_prob
    schema = {**_LOOK_SCHEMA, "properties": {**_LOOK_SCHEMA["properties"], "nhan": {"type": "string", "enum": R.CHOICES}}}
    choice = await llm.complete_raw(
        [{"role": "system", "content": general._VISION_SYSTEM}, llm.user_message(_LOOK_PROMPT, image)],
        max_tokens=120, temperature=0.0, logprobs=True, top_logprobs=1,
        response_format={"type": "json_schema", "json_schema": {"name": "money", "schema": schema}},
    )
    reply = json.loads(choice["message"].get("content") or "{}")
    label = reply.get("nhan")
    if label not in R.CHOICES:
        raise llm.LLMError(f"Gemma không trả đúng nhãn: {label!r}")
    return label, value_prob(choice, "nhan"), reply.get("quan_sat", "")


def label_prob(choice: dict, text: str, choices: list[str]) -> float | None:
    """Xác suất nhãn chuẩn hoá lại CHỈ trên các nhãn hợp lệ (top-20 token mỗi bước). ĐÃ LOẠI 2026-10-21:
    1 khung nói sai gấp đôi, 3 khung không lợi — giữ để chạy lại được (--renorm)."""
    import math
    items = (choice.get("logprobs") or {}).get("content")
    if not items:
        return None
    prefix, total = "", 0.0
    for it in items:
        if prefix == text:
            break
        alts = {a["token"]: a["logprob"] for a in it.get("top_logprobs") or [] if a.get("logprob") is not None}
        alts[it["token"]] = it["logprob"]
        ok = [lp for tok, lp in alts.items() if any(c.startswith(prefix + tok) for c in choices)]
        total += it["logprob"] - math.log(sum(math.exp(lp) for lp in ok))
        prefix += it["token"]
    return math.exp(total)


# Biến thể prompt (2026-10-21): phân tích ca sai test — gần như mọi ca nói sai/mâu thuẫn là con số bị CẮT ở mép khung,
# bị gập hoặc ngón tay che, Gemma đọc đúng phần nhìn thấy ("50000" của tờ 500.000) và rất chắc.
EDGE_RULE = (
    "\nCHỈ kết luận khi thấy TRỌN con số mệnh giá (không chạm mép ảnh, không bị ngón tay che, không bị gập) "
    "hoặc đọc được dòng chữ mệnh giá in trên tờ. Con số chạm mép, bị che hay bị gập thì có thể đã mất chữ số: "
    "chọn \"không rõ\"."
)


def messages_for(image: bytes, prompt: str):
    from handlers import read_money as R
    if prompt == "prod":
        return R.choice_messages(image)
    from lanes import general
    from models import llm
    text = f'{R._PROMPT}{EDGE_RULE}\n\nNgười dùng nói: "{R.CHOICE_QUESTION}"\nTrả đúng một nhãn.'
    return [{"role": "system", "content": general._VISION_SYSTEM}, llm.user_message(text, image)]


async def choose_both(messages: list[dict]):
    """(nhãn, xác suất chuẩn hoá, xác suất thô) trên CÙNG một lượt gọi."""
    from handlers import read_money as R
    from models.llm.client import prefix_prob
    text, choice = await R.choose_raw(messages, top_logprobs=20)
    return text, label_prob(choice, text, R.CHOICES), prefix_prob(choice, len(text))


def neighbours(path: str, offsets=(-DELTA, DELTA)) -> list[str]:
    import glob
    import re
    d = os.path.dirname(path)
    files = sorted(glob.glob(os.path.join(d, "*.png")), key=lambda p: int(re.search(r"_(\d+)\.png$", p).group(1)))
    i = files.index(path)
    return [files[min(len(files) - 1, max(0, i + o))] for o in offsets]


async def timed(coro):
    t = time.monotonic()
    try:
        out = await coro
        return out, 1000 * (time.monotonic() - t), None
    except Exception as exc:  # noqa: BLE001
        return None, 1000 * (time.monotonic() - t), repr(exc)


def jpeg(path: str) -> bytes:
    with open(path, "rb") as f:
        return L.to_jpeg(f.read(), quality=90)


async def run(args):
    from handlers import read_money as R
    items = M.pick_samples(args.limit, args.split)
    per = []
    for n, it in enumerate(items):
        offsets = (-DELTA, DELTA) if args.frames == 3 else (-DELTA, DELTA, -2 * DELTA, 2 * DELTA)
        paths = [it["path"], *neighbours(it["path"], offsets)]
        t = time.monotonic()
        frames = await asyncio.gather(*(timed(choose_both(messages_for(jpeg(p), args.prompt))) for p in paths))
        wall3 = 1000 * (time.monotonic() - t)
        # prob = xác suất dùng để quyết (thô hoặc chuẩn hoá theo --renorm); lưu cả hai để so ghép đôi trên CÙNG lượt gọi
        row = {"key": it["key"], "gt": it["gt"], "frames": [{"label": f[0][0] if f[0] else None,
                                                            "prob": (f[0][1] if args.renorm else f[0][2]) if f[0] else None,
                                                            "prob_norm": f[0][1] if f[0] else None, "prob_raw": f[0][2] if f[0] else None,
                                                            "ms": f[1], "error": f[2]} for f in frames], "wall3_ms": wall3}
        f0 = row["frames"][0]
        if not args.renorm and f0["label"] is not None and f0["label"] != R.NO_MONEY_LABEL and (f0["label"] not in R.LABELS or (f0["prob"] or 0) < TAU1):
            out, ms, err = await timed(look_closer(jpeg(it["path"])))
            row["stage2"] = {"label": out[0] if out else None, "prob": out[1] if out else None, "note": out[2] if out else None,
                             "ms": ms, "error": err}
        per.append(row)
        if (n + 1) % 30 == 0:
            print(f"[{n + 1}/{len(items)}]", flush=True)

    def outcome(gt, said):
        v = R.LABELS.get(said)
        return v is not None and v != gt, v == gt, v is None

    def table(decide, lat):
        rows = []
        for tau in TAUS:
            res = [(x["gt"], decide(x, tau)) for x in per if x["frames"][0]["error"] is None]
            money = [outcome(g, s) for g, s in res if g != 0]
            nom = [R.LABELS.get(s) is not None for g, s in res if g == 0]
            A = np.array(money, dtype=float)
            rows.append({"tau": tau, "wrong": L.ci_entry(A[:, 0]), "accuracy": L.ci_entry(A[:, 1]), "refusal": L.ci_entry(A[:, 2]),
                         "fabricate": float(np.mean(nom)) if nom else None, "latency": common.latency_summary(lat(tau))})
        return rows

    def single(x, tau):
        f = x["frames"][0]
        return R.say(f["label"], f["prob"], tau) if f["label"] else R.UNSURE

    def multi(x, tau):
        score = {}
        for f in x["frames"]:
            if f["label"] is not None:
                score[f["label"]] = score.get(f["label"], 0.0) + (f["prob"] or 0.0) / len(x["frames"])
        if not score:
            return R.UNSURE
        best = max(score, key=score.get)
        return R.say(best, score[best], tau)

    def confident(x, tau):
        return [f["label"] for f in x["frames"] if f["label"] in R.LABELS and (f["prob"] or 0) >= tau]

    def majority(x, tau):  # >= 2/3 khung chắc cùng nhãn, không khung nào chắc nhãn khác
        c = confident(x, tau)
        return c[0] if c and len(set(c)) == 1 and len(c) >= 2 else (R.NO_MONEY if x["frames"][0]["label"] == R.NO_MONEY_LABEL else R.UNSURE)

    def any_agree(x, tau):  # >= 1 khung chắc, không khung nào chắc nhãn khác = read_money.combine (production)
        return R.combine([(f["label"], f["prob"]) for f in x["frames"] if f["label"] is not None], tau)

    def cascade(x, tau):
        f = x["frames"][0]
        if "stage2" not in x:
            return R.say(f["label"], f["prob"], TAU1) if f["label"] else R.UNSURE
        s = x["stage2"]
        return R.say(s["label"], s["prob"], tau) if s["label"] else R.UNSURE

    ok = [x for x in per if x["frames"][0]["error"] is None]
    lat_single = lambda tau: [x["frames"][0]["ms"] for x in ok]  # noqa: E731
    lat_multi = lambda tau: [x["wall3_ms"] for x in ok]  # noqa: E731
    lat_casc = lambda tau: [x["frames"][0]["ms"] + (x["stage2"]["ms"] if "stage2" in x else 0) for x in ok]  # noqa: E731
    result = {"A_single": table(single, lat_single), "B_multi3": table(multi, lat_multi), "B2_majority3": table(majority, lat_multi),
              "B3_any_agree3": table(any_agree, lat_multi),
              "escalated_rate": float(np.mean(["stage2" in x for x in ok]))}
    payload = {"meta": common.run_meta({"task": "money_vnd", "bench": "money_multi", "split": args.split, "delta_frames": DELTA,
                                        "tau1": TAU1, "limit": args.limit, "renorm": args.renorm, "frames": args.frames, "prompt": args.prompt}),
               "result": result, "per_sample": per}
    path = common.write_result("money_vnd", f"multi{'' if args.frames == 3 else args.frames}{'_edge' if args.prompt == 'edge' else ''}{'_renorm' if args.renorm else ''}_{args.split}{'_limit%d' % args.limit if args.limit else ''}", payload, None)
    print(path, "leo thang tầng 2:", f"{100 * result['escalated_rate']:.1f} %")
    if not args.renorm:  # tầng 2 đã loại — lượt --renorm không gọi
        result["C_cascade"] = table(cascade, lat_casc)
    for name in result:
        if not isinstance(result[name], list):
            continue
        print("==", name)
        for r in result[name]:
            lat = r["latency"]
            print(f"  tau {r['tau']:<6} sai {100 * r['wrong']['value']:5.1f} %  đúng {100 * r['accuracy']['value']:5.1f} %  "
                  f"từ chối {100 * r['refusal']['value']:5.1f} %  trễ p50/p90 {lat['p50_ms']:.0f}/{lat['p90_ms']:.0f} ms")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--prompt", choices=["prod", "edge"], default="prod", help="edge = thêm luật 'thấy trọn con số mới kết luận'")
    ap.add_argument("--frames", type=int, choices=[3, 5], default=3, help="số khung: i, i±3 (và i±6 khi 5)")
    ap.add_argument("--renorm", action="store_true", help="quyết bằng xác suất chuẩn hoá trên 13 nhãn (read_money.label_prob)")
    L.new_loop_run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
