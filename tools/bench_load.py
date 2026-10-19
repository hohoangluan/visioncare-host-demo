"""Bench tải đồng thời: N kính giả, mỗi kính một `WS /v2/session` (Task 16).

Mỗi kính chạy M lượt cách nhau 2-5 s (sau khi lượt trước trả lời xong), luồng chọn theo
`--mix`. Dùng lại `one_turn_ws` của `bench_live.py` nên số đo cùng định nghĩa: nhả nút -> khối
audio đầu, `starve` = tổng ms đứt tiếng nếu loa phát ngay khi có byte đầu.

    V2_DEBUG_STATS=1 ... uvicorn app:app --port 18894      # server bật endpoint đếm Gemma
    python tools/bench_load.py --base http://127.0.0.1:18894 --glasses 4 --turns 6 \
        --mix chat:4,space:2,ocr:2,call:1,nav:1 --street tools/street.jpg --out /tmp/load4.json

Tên luồng -> câu lệnh của bench_live: chat, space, ocr, call (= "Gọi cho mẹ"), nav (= "Bật cảnh báo
vật cản"). `max_inflight` đọc từ `GET /v2/debug/stats` (chỉ có khi server đặt V2_DEBUG_STATS=1).
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import bench_live  # noqa: E402

FLOWS = {"chat": "chat", "space": "space", "ocr": "ocr", "call": "contact", "nav": "alert"}
TURN_TIMEOUT_S = 60.0


def parse_mix(text: str) -> list[str]:
    out: list[str] = []
    for part in text.split(","):
        name, _, weight = part.partition(":")
        name = name.strip()
        if name not in FLOWS:
            raise SystemExit(f"luồng lạ {name!r}; có: {', '.join(FLOWS)}")
        out += [name] * int(weight or 1)
    return out


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q / 100 * (len(s) - 1))))]


async def glasses(idx: int, args, pool: list[str], audio: dict, images: dict, rows: list[dict]) -> None:
    import websockets

    rng = random.Random(args.seed * 1000 + idx)
    seq = [rng.choice(pool) for _ in range(args.turns)]
    device = f"bench-load-{idx}"
    await asyncio.sleep(rng.uniform(0, args.gap_min))  # lệch pha, không bấm nút cùng một nhịp
    ws = await websockets.connect(args.base.replace("http", "ws", 1) + "/v2/session", max_size=None)
    try:
        await ws.send(json.dumps({"t": "hello", "device": device, "cue_version": 2, "fw": "bench-load",
                                  "accept": "audio/wav;codec=ima_adpcm",
                                  "token": os.environ.get("VISIONCARE_DEVICE_CLIENT_TOKEN", "")}))
        hello = json.loads(await ws.recv())
        if hello.get("t") != "hello_ok":
            rows.append({"flow": "-", "glasses": idx, "error": f"hello: {hello}"})
            return
        for flow in seq:
            name = FLOWS[flow]
            row = {"flow": flow, "glasses": idx}
            try:
                r = await asyncio.wait_for(
                    bench_live.one_turn_ws(ws, name, audio[name], images[name]), TURN_TIMEOUT_S)
                row.update(first_audio_ms=r["first_audio_ms"], headers_ms=r["headers_ms"],
                           total_ms=r["total_ms"], starve_ms=r["starve_ms"], cue=r["x-cue"], live=r["x-live"])
            except Exception as exc:  # noqa: BLE001 - lỗi là một kết quả của bench
                row["error"] = repr(exc)[:200]
                rows.append(row)
                break  # socket có thể đã hỏng; không đoán tiếp
            rows.append(row)
            await asyncio.sleep(rng.uniform(args.gap_min, args.gap_max))
    finally:
        await ws.close()


async def stats(http: httpx.AsyncClient, base: str, reset: bool) -> dict | None:
    try:
        r = await http.get(f"{base}/v2/debug/stats", params={"reset": int(reset)}, headers=bench_live._auth())
        return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    except httpx.HTTPError as exc:
        return {"error": repr(exc)}


def summarize(rows: list[dict]) -> dict:
    out = {}
    for flow in sorted({r["flow"] for r in rows}):
        rs = [r for r in rows if r["flow"] == flow]
        ok = [r for r in rs if "error" not in r]
        fa = [r["first_audio_ms"] for r in ok if r["first_audio_ms"] is not None]
        st = [r["starve_ms"] for r in ok]
        hd = [r["headers_ms"] for r in ok]  # khung `reply` (cue/live): luồng chỉ-cue (nav) không có audio
        out[flow] = {
            "n": len(rs), "errors": len(rs) - len(ok), "no_audio": len(ok) - len(fa),
            "p50": pct(fa, 50), "p90": pct(fa, 90), "max": max(fa) if fa else None,
            "reply_p50": pct(hd, 50), "reply_p90": pct(hd, 90),
            "starve_p90": pct(st, 90), "starve_max": max(st) if st else None,
        }
    return out


def print_table(n: int, turns: int, mix: str, wall: float, summary: dict, gemma: dict | None, errors: list) -> None:
    print(f"N={n} turns={turns} mix={mix} wall={wall:.0f}s at={time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'flow':6s} {'n':>3s} {'err':>3s} {'noaud':>5s} {'p50':>6s} {'p90':>6s} {'max':>6s} "
          f"{'rep50':>6s} {'rep90':>6s} {'starve90':>8s} {'starveMax':>9s}")
    f = lambda v: "-" if v is None else f"{v:.0f}"  # noqa: E731
    for flow, s in summary.items():
        print(f"{flow:6s} {s['n']:3d} {s['errors']:3d} {s['no_audio']:5d} {f(s['p50']):>6s} {f(s['p90']):>6s} "
              f"{f(s['max']):>6s} {f(s['reply_p50']):>6s} {f(s['reply_p90']):>6s} "
              f"{f(s['starve_p90']):>8s} {f(s['starve_max']):>9s}")
    print("gemma:", json.dumps(gemma, ensure_ascii=False))
    for r in errors:
        print("ERROR:", r)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18894")
    ap.add_argument("--glasses", type=int, default=1)
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--mix", default="chat:4,space:2,ocr:2,call:1,nav:1")
    ap.add_argument("--gap-min", type=float, default=2.0)
    ap.add_argument("--gap-max", type=float, default=5.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--street", help="ảnh đường phố cho space/nav (trang giấy trắng bị chặn 'ảnh quá sáng')")
    ap.add_argument("--cache", default=os.path.join(ROOT, "tools", "board_audio", "v2"))
    ap.add_argument("--out", help="ghi kết quả JSON")
    ap.add_argument("--resummarize", help="chỉ in lại bảng từ file JSON đã ghi, không chạy")
    args = ap.parse_args()
    if args.resummarize:
        saved = json.load(open(args.resummarize))
        print_table(saved["args"]["glasses"], saved["args"]["turns"], saved["args"]["mix"], saved["wall_s"],
                    summarize(saved["rows"]), saved["gemma"], [r for r in saved["rows"] if "error" in r])
        return

    pool = parse_mix(args.mix)
    text_image = bench_live._text_image()
    scene = open(args.street, "rb").read() if args.street else text_image
    audio, images = {}, {}
    for flow in set(pool):
        name = FLOWS[flow]
        audio[name] = bench_live._command_audio(name, bench_live.COMMANDS[name], args.cache)
        images[name] = text_image if name == "ocr" else scene

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=10) as http:
        before = await stats(http, args.base, reset=True)
        t0 = time.time()
        await asyncio.gather(*(glasses(i, args, pool, audio, images, rows) for i in range(args.glasses)))
        wall = time.time() - t0
        after = await stats(http, args.base, reset=False)

    summary = summarize(rows)
    errors = [r for r in rows if "error" in r]
    print_table(args.glasses, args.turns, args.mix, wall, summary, after, errors)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"args": vars(args), "wall_s": wall, "summary": summary, "gemma": after,
                       "gemma_before": before, "rows": rows}, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
