"""C3 — thời gian tới câu nói đầu tiên của lượt đọc tiền: đường cũ (`ocr_live.spoken` stream) vs đọc tiền v2 (`final_router._money`).

Yêu cầu người dùng 2026-10-21: đọc tiền v2 KHÔNG được làm lượt đọc thành công chậm đi. Ghép đôi trên CÙNG ảnh test, gọi MỚI (không cache),
đổi thứ tự A/B theo ảnh để server nóng/lạnh không thiên vị một bên. Đo từ lúc gọi tới khi có câu nói đầu tiên (đường cũ: phần tử đầu của
luồng; v2: `Reply.speech[0]` có sẵn). Chỉ tính lượt v2 ĐỌC CHẮC cho số "lượt thành công"; lượt không chắc báo riêng (nói câu hướng dẫn).
`single_shot=True` để v2 không mở phiên live (không có WS trong bàn đo) — lượt chắc không đi qua nhánh đó nên không ảnh hưởng số chính.

Dùng: SEEVIA_VH_DIR=../vh-chot python -m bench.money_turn_latency [--n 60]
"""

import argparse
import asyncio
import time

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402
from bench import money_vnd  # noqa: E402


async def _first_old(jpeg: bytes) -> tuple[float, str]:
    from lanes import ocr_live
    t = time.perf_counter()
    it = ocr_live.spoken(jpeg, "money", "bench")
    first = await it.__anext__() if hasattr(it, "__anext__") else next(iter(it))
    return (time.perf_counter() - t) * 1000, first


async def _first_v2(jpeg: bytes) -> tuple[float, str, bool]:
    from handlers import read_money
    from pipeline import final_router
    ctx = final_router.TurnContext("bench", "bench", None, asyncio.get_running_loop())
    ctx.single_shot = True
    t = time.perf_counter()
    reply = await final_router._money(ctx, jpeg)
    ms = (time.perf_counter() - t) * 1000
    line = reply.speech[0]
    return ms, line, line not in read_money.STATIC_SPEECH


async def run(n: int) -> dict:
    items = money_vnd.pick_samples(None, "test")
    items = [it for it in items if it["gt"] != 0][:n]
    rows = []
    for i, it in enumerate(items):
        with open(it["path"], "rb") as f:
            jpeg = L.to_jpeg(f.read(), quality=90)
        if i % 2 == 0:
            old = await _first_old(jpeg); new = await _first_v2(jpeg)
        else:
            new = await _first_v2(jpeg); old = await _first_old(jpeg)
        rows.append({"key": it["key"], "old_ms": old[0], "v2_ms": new[0], "v2_sure": new[2], "v2_line": new[1]})
        print(f"[money_turn] {i + 1}/{len(items)} cũ {old[0]:.0f} ms · v2 {new[0]:.0f} ms {'chắc' if new[2] else 'hướng dẫn'}", flush=True)
    sure = [r for r in rows if r["v2_sure"]]
    d = np.array([r["v2_ms"] - r["old_ms"] for r in sure])
    out = {"n": len(rows), "n_v2_sure": len(sure),
           "sure_old": common.latency_summary([r["old_ms"] for r in sure]),
           "sure_v2": common.latency_summary([r["v2_ms"] for r in sure]),
           "sure_delta_ms": {"median": float(np.median(d)) if len(d) else None,
                             "ci": list(common.bootstrap_ci(d, stat=np.median)[1:]) if len(d) else None},
           "unsure_v2": common.latency_summary([r["v2_ms"] for r in rows if not r["v2_sure"]])}
    return {"summary": out, "per_sample": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args()
    res = asyncio.run(run(args.n))
    path = common.write_result("money_vnd", f"turn_latency_n{args.n}", {"meta": common.run_meta({"n": args.n}), **res})
    print("ghi", path)
    print(res["summary"])


if __name__ == "__main__":
    main()
