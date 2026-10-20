"""C1b — Vật cản: logic mức + cảnh báo (`HazardTracker` + `AntiAnnoy`) trên kịch bản tổng hợp (METRICS.md §C1b).

Mô phỏng ĐÚNG đường nóng `lanes.nav_live.run`: mỗi khung `HazardTracker.assess(dets)` -> mức; mức < HAZARD_MIN_LEVEL coi
như 0; `AntiAnnoy.step(mức)` trả True = "bíp" gửi kính. Đồng hồ AntiAnnoy giả theo khung (125 ms/khung).
Chỉ đo baseline (không biến thể — PLAN, bổ sung 2026-10-20).

Metric: tỉ lệ kịp thời (bíp mức>=2 đầu tiên trước t_danger >= 1,5 s), lead time p50/p90, tỉ lệ trượt, báo nhầm/phút trên
kịch bản an toàn, số lần gửi / đổi mức; µs/khung của assess+step; trễ thuật toán (khung chờ xác nhận x 125 ms).
Kèm đối chứng: dương (xe máy lao thẳng có bíp), âm (vật xa đứng yên không bíp), và hai đường ống phá hoại (chết / luôn mức 3).

Dùng: python -m bench.hazard_logic [--seeds 50] [--out DIR]
"""

import argparse
import json
import time

import numpy as np

from bench import common

common.setup(gpu=False)  # thuần CPU, không đụng GPU

import config  # noqa: E402
from bench import hazard_scenarios as hs  # noqa: E402
from live import hazard  # noqa: E402

LEAD_REQUIRED_S = 1.5
MIN_LEVEL = lambda: config.HAZARD_MIN_LEVEL  # noqa: E731  (đọc lúc chạy: theo cấu hình VH)


class BaselinePipeline:
    """Đúng cặp production: HazardTracker + AntiAnnoy với đồng hồ giả."""

    name = "baseline"

    def __init__(self) -> None:
        self.t = [0.0]
        self.tracker = hazard.HazardTracker()
        self.anti = hazard.AntiAnnoy(clock=lambda: self.t[0])

    def frame(self, k: int, dets) -> tuple[hazard.Hazard, bool]:
        self.t[0] = k * hs.DT
        hz = self.tracker.assess(dets)
        sent = self.anti.step(hz.level if hz.level >= MIN_LEVEL() else 0)
        return hz, bool(sent)


class DeadPipeline(BaselinePipeline):
    """Đối chứng phá hoại 1: không bao giờ cảnh báo -> kịp thời phải = 0."""
    name = "control_dead"

    def frame(self, k, dets):
        return hazard.Hazard(0), False


class AlwaysCriticalPipeline(BaselinePipeline):
    """Đối chứng phá hoại 2: luôn mức 3 -> bíp ở mọi kịch bản an toàn (báo nhầm phải > 0, kịp thời cao)."""
    name = "control_always3"

    def frame(self, k, dets):
        self.t[0] = k * hs.DT
        hz = hazard.Hazard(3, "center", "x")
        return hz, bool(self.anti.step(3))


def simulate(scn: hs.Scenario, make=BaselinePipeline) -> dict:
    pipe = make()
    levels, beeps, step_us = [], [], []
    for k, dets in enumerate(scn.frames):
        t = time.perf_counter()
        hz, sent = pipe.frame(k, dets)
        step_us.append((time.perf_counter() - t) * 1e6)
        levels.append(hz.level)
        if sent:
            beeps.append((k, hz.level))
    return {"type": scn.type, "seed": scn.seed, "positive": scn.positive, "t_danger_frame": scn.t_danger_frame,
            "n_frames": scn.n_frames, "minutes": scn.minutes, "levels": "".join(str(l) for l in levels),
            "beeps": beeps, "_us": step_us}


def algo_delay_frames(rec: dict) -> int | None:
    """Số khung từ đầu đoạn liên tiếp mức >= MIN_LEVEL (chứa bíp đầu tiên) đến khung bíp đó. None nếu không bíp."""
    if not rec["beeps"]:
        return None
    kb = rec["beeps"][0][0]
    lv = rec["levels"]
    j = kb
    while j > 0 and int(lv[j - 1]) >= MIN_LEVEL():
        j -= 1
    return kb - j


def score(rec: dict) -> dict:
    """Từ một bản ghi mô phỏng -> các số của kịch bản (chấm lại được từ per_sample, không cần mô phỏng)."""
    beeps = rec["beeps"]
    td = rec["t_danger_frame"]
    out = {"n_sent": len(beeps),
           "n_sent_level_changes": int(sum(1 for a, b in zip(beeps, beeps[1:]) if a[1] != b[1])),
           "n_frame_level_changes": int(sum(1 for a, b in zip(rec["levels"], rec["levels"][1:]) if a != b))}
    if td is not None:
        first = next((k for k, lvl in beeps if lvl >= 2 and k < td), None)
        out["miss"] = int(first is None)
        out["lead_s"] = None if first is None else (td - first) * hs.DT
        out["timely"] = int(first is not None and (td - first) * hs.DT >= LEAD_REQUIRED_S)
    d = algo_delay_frames(rec)
    out["algo_delay_ms"] = None if d is None else d * hs.DT * 1000
    return out


def _ratio(x: np.ndarray) -> float:
    return float(x[:, 0].sum() / x[:, 1].sum()) if x[:, 1].sum() > 0 else float("nan")


def ci(vals, stat=np.mean) -> dict:
    v, lo, hi = common.bootstrap_ci(np.asarray(vals, dtype=float), stat=stat)
    return {"value": v, "ci": [lo, hi], "n": len(vals)}


def summarize(recs: list[dict]) -> dict:
    """Metric gộp + theo loại kịch bản. CI bootstrap THEO KỊCH BẢN."""
    sc = [score(r) for r in recs]

    def block(idx_pos, idx_safe):
        b = {}
        if idx_pos:
            timely = [sc[i]["timely"] for i in idx_pos]
            miss = [sc[i]["miss"] for i in idx_pos]
            lead = [sc[i]["lead_s"] for i in idx_pos if sc[i]["lead_s"] is not None]
            b["n_positive"] = len(idx_pos)
            b["timely_rate"] = ci(timely)
            b["miss_rate"] = ci(miss)
            b["late_rate"] = {"value": 1 - float(np.mean(timely)) - float(np.mean(miss))}
            if lead:
                b["lead_time_s"] = {"p50": float(np.percentile(lead, 50)), "p90": float(np.percentile(lead, 90)),
                                    "p50_ci": ci(lead, np.median)["ci"], "n_with_beep": len(lead)}
            else:
                b["lead_time_s"] = None
        if idx_safe:
            arr = np.array([[sc[i]["n_sent"], recs[i]["minutes"]] for i in idx_safe])
            b["n_safe"] = len(idx_safe)
            b["false_alarms_per_min"] = {**dict(zip(("value", "lo", "hi"), common.bootstrap_ci(arr, stat=_ratio))),
                                         "total_beeps": int(arr[:, 0].sum()), "total_minutes": float(arr[:, 1].sum())}
            b["false_alarms_per_min"]["ci"] = [b["false_alarms_per_min"].pop("lo"), b["false_alarms_per_min"].pop("hi")]
            b["safe_scenarios_with_beep"] = ci([int(sc[i]["n_sent"] > 0) for i in idx_safe])
        idx_all = idx_pos + idx_safe
        b["sent_per_scenario"] = ci([sc[i]["n_sent"] for i in idx_all])
        b["sent_level_changes_per_scenario"] = ci([sc[i]["n_sent_level_changes"] for i in idx_all])
        b["frame_level_changes_per_scenario"] = ci([sc[i]["n_frame_level_changes"] for i in idx_all])
        return b

    pos = [i for i, r in enumerate(recs) if r["positive"]]
    safe = [i for i, r in enumerate(recs) if not r["positive"]]
    res = {"overall": block(pos, safe), "by_type": {}}
    for t in dict.fromkeys(r["type"] for r in recs):
        ix = [i for i, r in enumerate(recs) if r["type"] == t]
        res["by_type"][t] = block([i for i in ix if recs[i]["positive"]], [i for i in ix if not recs[i]["positive"]])
        res["by_type"][t]["label"] = "positive" if recs[ix[0]]["positive"] else "safe"
    delays = [s["algo_delay_ms"] for s in sc if s["algo_delay_ms"] is not None]
    res["algo_delay_ms"] = common.latency_summary(delays)
    return res


def run_controls(n_seeds: int) -> dict:
    """Đối chứng dương/âm (không gian lận): kết quả phải đúng kỳ vọng, nếu không bench hỏng."""
    c = {}
    pos = [hs.generate("motorbike_charge", s) for s in range(n_seeds)]
    neg = [hs.generate("far_static_person", s) for s in range(n_seeds)] + [hs.generate("far_static_car", s) for s in range(n_seeds)]
    r = [simulate(s) for s in pos]
    c["positive_control_motorbike_charge"] = {
        "expect": "baseline có bíp trước t_danger ở >= 90% seed", "n": len(r),
        "beep_before_danger_rate": float(np.mean([1 - score(x)["miss"] for x in r])),
        "pass": bool(np.mean([1 - score(x)["miss"] for x in r]) >= 0.9)}
    r = [simulate(s) for s in neg]
    c["negative_control_far_static"] = {"expect": "0 bíp", "n": len(r), "total_beeps": int(sum(len(x["beeps"]) for x in r)),
                                        "pass": bool(sum(len(x["beeps"]) for x in r) == 0)}
    allpos = [s for s in hs.generate_all(n_seeds) if s.positive]
    allsafe = [s for s in hs.generate_all(n_seeds) if not s.positive]
    dead = [score(simulate(s, DeadPipeline)) for s in allpos]
    c["sabotage_dead_pipeline"] = {"expect": "kịp thời = 0", "timely": float(np.mean([d["timely"] for d in dead])),
                                   "pass": bool(all(d["timely"] == 0 for d in dead))}
    a3 = [simulate(s, AlwaysCriticalPipeline) for s in allsafe]
    c["sabotage_always_level3"] = {"expect": "mọi kịch bản an toàn bị bíp", "safe_with_beep": float(np.mean([len(x["beeps"]) > 0 for x in a3])),
                                   "pass": bool(all(len(x["beeps"]) > 0 for x in a3))}
    c["all_pass"] = all(v["pass"] for v in c.values() if isinstance(v, dict))
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--out", default=None)
    ap.add_argument("--types", default=None, help="danh sách loại, cách nhau dấu phẩy (chạy thử)")
    args = ap.parse_args()
    types = args.types.split(",") if args.types else None
    scns = hs.generate_all(args.seeds, types)
    print(f"{len(scns)} kịch bản ({args.seeds} seed x {len(scns) // max(args.seeds, 1)} loại)", flush=True)
    recs = [simulate(s) for s in scns]
    us = np.concatenate([r["_us"] for r in recs])
    for r in recs:
        del r["_us"]
    metrics = summarize(recs)
    controls = run_controls(min(args.seeds, 50))
    cam = hs.Camera()
    cfg = {"seeds": args.seeds, "types": [t[0] for t in hs.TYPES] if types is None else types, "fps": hs.FPS,
           "camera": {"w": hs.IMG_W, "h": hs.IMG_H, "hfov_deg": hs.HFOV_DEG, "height_m": hs.CAM_H, "f_px": cam.f},
           "danger": {"z_m": hs.DANGER_Z, "lane_half_m": hs.LANE_HALF}, "lead_required_s": LEAD_REQUIRED_S,
           "min_box_px": hs.MIN_BOX_PX, "shake": {"size": hs.SHAKE_SIZE, "pos_of_box": hs.SHAKE_POS},
           "flicker_p": hs.FLICKER_P, "score_range": hs.SCORE_RANGE, "objects": hs.OBJECTS,
           "hazard_min_level": config.HAZARD_MIN_LEVEL, "hazard_repeat_s": config.HAZARD_REPEAT_S,
           "hazard_level1_gap_s": config.HAZARD_LEVEL1_GAP_S, "objects_note": "cột=parking_meter, ghế=bench (kind tĩnh COCO gần nhất)"}
    p = np.percentile(us, [50, 90, 99])
    out = {"meta": common.run_meta(cfg), "metrics": metrics, "controls": controls,
           "latency": {"assess_step_per_frame_us": {"n": int(len(us)), "p50_us": round(float(p[0]), 2), "p90_us": round(float(p[1]), 2),
                                                    "p99_us": round(float(p[2]), 2), "mean_us": round(float(us.mean()), 2)},
                       "algo_delay_ms": metrics["algo_delay_ms"], "cpu_only": True},
           "per_sample": recs}
    path = common.write_result("hazard", "logic" + ("" if args.seeds == 50 and not types else f"_s{args.seeds}"), out, args.out)
    json.load(open(path, encoding="utf-8"))
    print("ghi", path)
    o = metrics["overall"]
    print("kịp thời", o["timely_rate"], "\nbáo nhầm/phút", o["false_alarms_per_min"], "\nđối chứng", {k: v["pass"] for k, v in controls.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
