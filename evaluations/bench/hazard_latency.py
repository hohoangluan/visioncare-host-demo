"""C1c — Vật cản: độ trễ đường nóng phía server (METRICS.md §C1c).

Chuỗi thật của `lanes.nav_live.run` cho mỗi khung: decode JPEG q15 -> [`EgoMeter.measure` khi HAZARD_LOGIC=predict] ->
`OnnxYolo.detect` -> `assess` của tracker theo `hazard.make_tracker()` -> `AntiAnnoy.step` (`hazard.make_anti()`).
VH cũ chưa có make_tracker/make_anti thì dùng HazardTracker/AntiAnnoy như trước. Đo từng chặng (decode / detect / assess / step) + tổng, và lượt thứ hai gọi thẳng
`nav_live.process_frame` + `step` (đường code thật) để đối chiếu.
Ảnh: Obstacle-Dataset test thu QVGA (rộng 320, giữ tỉ lệ) + JPEG q15 như kính gửi. Khung đưa vào theo thứ tự cố định seed,
một tracker xuyên suốt (như một phiên). Không đo mạng/kính/Cloudflare (đo sau bằng tools/e2e_full.py).
Ngân sách: server p90 <= 10 ms (spec); mọi thay đổi thuật toán không được làm p90 tăng > 5 ms.

Dùng: python -m bench.hazard_latency [--limit N] [--out DIR]
"""

import argparse
import json
import os
import time

import numpy as np

from bench import common

common.setup()

import cv2  # noqa: E402

import config  # noqa: E402
from bench import hazard_detect as hd  # noqa: E402  (đã setup; dùng lại list_images/glass_jpeg)
from lanes import nav_live  # noqa: E402
from live import hazard  # noqa: E402

BUDGET_SERVER_P90_MS = 10.0
WARMUP = 20
DT = 0.125  # mốc thời gian giả 8 fps cho Kalman của predict (đo trễ, không đo đúng/sai)


def _make():
    tracker = hazard.make_tracker() if hasattr(hazard, "make_tracker") else hazard.HazardTracker()
    anti = hazard.make_anti() if hasattr(hazard, "make_anti") else hazard.AntiAnnoy()
    meter = None
    if getattr(config, "HAZARD_LOGIC", "area") == "predict":
        from live import ego_motion
        meter = ego_motion.EgoMeter()
    return tracker, anti, meter


def _step(anti, hz) -> None:
    lvl = hz.level if hz.level >= config.HAZARD_MIN_LEVEL else 0
    if getattr(hz, "urgent", False):
        anti.step(lvl, urgent=True)
    else:
        anti.step(lvl)


def run(names: list[str], imgsz: int) -> dict:
    det = hd.load_detector(imgsz)
    config.HAZARD_MIN_SCORE = hd.OP_SCORE
    jpegs = []
    for n in names:
        bgr = cv2.imread(os.path.join(hd.IMG_DIR, n))
        jpegs.append(hd.glass_jpeg(bgr))
    order = common.sample(list(range(len(jpegs))), None)
    order = list(np.random.default_rng(0).permutation(len(jpegs)))
    stages = {"decode": [], "ego": [], "detect": [], "assess": [], "step": [], "total": []}
    tracker, anti, meter = _make()
    predict = meter is not None
    for k in range(WARMUP):  # warm-up, không tính
        b = nav_live._decode(jpegs[order[k % len(order)]]); det.detect(b)
    for n, i in enumerate(order):
        t0 = time.perf_counter()
        bgr = nav_live._decode(jpegs[i])
        t1 = time.perf_counter()
        ego = meter.measure(bgr) if predict else None
        t1b = time.perf_counter()
        dets = det.detect(bgr)
        t2 = time.perf_counter()
        hz = tracker.assess(dets, n * DT, ego) if predict else tracker.assess(dets)
        t3 = time.perf_counter()
        _step(anti, hz)
        t4 = time.perf_counter()
        for key, (a, b) in zip(("decode", "ego", "detect", "assess", "step", "total"),
                               ((t0, t1), (t1, t1b), (t1b, t2), (t2, t3), (t3, t4), (t0, t4))):
            stages[key].append((b - a) * 1000)
    # đối chiếu: đường code thật nav_live.process_frame + step
    tracker, anti, meter = _make()
    chain = []
    for n, i in enumerate(order):
        t = time.perf_counter()
        if predict:
            res, _, _ = nav_live.process_frame(det, tracker, jpegs[i], n * DT, meter)
        else:
            res, _, _ = nav_live.process_frame(det, tracker, jpegs[i])
        _step(anti, res)
        chain.append((time.perf_counter() - t) * 1000)
    lat = {k: common.latency_summary(v) for k, v in stages.items()}
    lat["process_frame_plus_step"] = common.latency_summary(chain)
    # assess/step cỡ µs: latency_summary làm tròn 0,01 ms -> thêm bản µs
    lat["hazard_logic"] = getattr(config, "HAZARD_LOGIC", "area")
    for k in ("ego", "assess", "step"):
        p = np.percentile(np.array(stages[k]) * 1000, [50, 90, 99])
        lat[k + "_us"] = {"p50_us": round(float(p[0]), 1), "p90_us": round(float(p[1]), 1), "p99_us": round(float(p[2]), 1)}
    lat["jpeg_bytes_mean"] = float(np.mean([len(j) for j in jpegs]))
    p90 = lat["total"]["p90_ms"]
    return {"latency": lat, "n_frames": len(order), "budget": {"server_p90_ms": BUDGET_SERVER_P90_MS,
            "total_p90_ms": p90, "within_budget": bool(p90 <= BUDGET_SERVER_P90_MS)}, "provider": det.provider}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--imgsz", default="320")
    args = ap.parse_args()
    static, shape = hd.input_is_static()
    sizes = [320] if static else [int(x) for x in args.imgsz.split(",")]
    names = hd.list_images(args.limit)
    cfg = {"limit": args.limit, "n_images": len(names), "imgsz": sizes, "static_input": static, "onnx_input_shape": shape,
           "note": "ONNX đầu vào tĩnh: chỉ 320" if static else "ONNX động: " + str(sizes),
           "glass": {"width": hd.GLASS_W, "jpeg_q": hd.GLASS_Q}, "hazard_num_threads": config.HAZARD_NUM_THREADS}
    out = {"meta": None, "by_imgsz": {}}
    for s in sizes:
        print(f"imgsz {s}: {len(names)} khung", flush=True)
        out["by_imgsz"][str(s)] = run(names, s)
    out["meta"] = common.run_meta(cfg)
    path = common.write_result("hazard", "latency" + ("" if not args.limit else f"_limit{args.limit}"), out, args.out)
    json.load(open(path, encoding="utf-8"))
    print("ghi", path)
    r = out["by_imgsz"][str(sizes[0])]
    print({k: r["latency"][k] for k in ("decode", "ego", "detect", "assess", "step", "total")}, r["budget"])


if __name__ == "__main__":
    main()
