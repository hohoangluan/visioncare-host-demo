"""Độ trễ ghép đôi `space` vs `ask` trên CÙNG ảnh, gọi MỚI (không cache), xen kẽ trong cùng một lúc.

Số trễ trong JSON của vqa_vizwiz là của lúc mẫu được gọi lần đầu (cache giữ nguyên) — hai prompt chạy hai ngày khác
nhau thì không so được vì LLM ở xa (llm.uit.edu.vn) dao động theo tải. Ở đây mỗi ảnh gọi cả hai prompt liền nhau,
thứ tự đảo ngẫu nhiên (seed 0). Báo TTFT (mảnh nói đầu ra khỏi `general.answer`) và tổng.

    SEEVIA_VH_DIR=<worktree có intent ask> python -m bench.vqa_latency_ab [--n 60]
"""

import argparse
import json
import os
import random

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402

VZ = os.path.join(common.DATAS, "vizwiz")


async def run(args):
    import config
    from lanes import general
    from pipeline.image_buffer import resize_jpeg

    allv = json.load(open(os.path.join(VZ, "vqa", "val.json"), encoding="utf-8"))
    items = common.sample(allv, 300, seed=0)[: args.n]
    tr = json.load(open(os.path.join(common.RESULTS, "vqa_vizwiz", "questions_vi.json"), encoding="utf-8"))
    rng = random.Random(0)
    lat = {"space": {"ttft": [], "total": []}, "ask": {"ttft": [], "total": []}}
    words = {"space": [], "ask": []}
    for i, it in enumerate(items):
        with open(os.path.join(VZ, "val", it["image"]), "rb") as f:
            img = resize_jpeg(L.to_jpeg(f.read(), quality=90), config.LLM_IMAGE_MAX_SIDE)
        order = ["space", "ask"] if rng.random() < 0.5 else ["ask", "space"]
        for intent in order:
            r = await L.timed_stream(lambda intent=intent: general.answer(intent, tr[it["image"]], img))
            if "error" in r:
                print(i, intent, "lỗi", r["error"], flush=True)
                continue
            lat[intent]["ttft"].append(r["ttft_ms"])
            lat[intent]["total"].append(r["total_ms"])
            words[intent].append(len(r["text"].split()))
        print(f"[{i + 1}/{len(items)}]", flush=True)
    out = {k: {m: common.latency_summary(v) for m, v in d.items()} for k, d in lat.items()}
    paired = {}
    n = min(len(lat["space"]["ttft"]), len(lat["ask"]["ttft"]))
    for m in ("ttft", "total"):
        d = np.array(lat["ask"][m][:n]) - np.array(lat["space"][m][:n])
        v, lo, hi = common.bootstrap_ci(d)
        paired[m] = {"delta_mean_ms": v, "ci": [lo, hi], "n": n}
    payload = {"meta": common.run_meta({"task": "vqa_latency_ab", "n": args.n, "llm": config.LLM_MODEL}),
               "latency": out, "paired_delta_ask_minus_space": paired,
               "words_mean": {k: float(np.mean(v)) for k, v in words.items()}}
    path = common.write_result("vqa_vizwiz", "latency_ab", payload, None)
    print(path)
    print(json.dumps({"latency": out, "paired": paired, "words": payload["words_mean"]}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    L.new_loop_run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
