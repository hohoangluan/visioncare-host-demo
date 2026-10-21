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
TAIL_LIMIT_S = 1.0      # còn bíp sau t_clear + 1,0 s = kêu thừa
SUDDEN_MAX_FRAMES = 2   # nhóm đột ngột: bíp trong <= 2 khung kể từ lúc lộ diện
MIN_LEVEL = lambda: config.HAZARD_MIN_LEVEL  # noqa: E731  (đọc lúc chạy: theo cấu hình VH)


class BaselinePipeline:
    """Đúng cặp production: HazardTracker + AntiAnnoy với đồng hồ giả."""

    name = "baseline"

    def __init__(self) -> None:
        self.t = [0.0]
        self.tracker = hazard.HazardTracker()
        self.anti = hazard.AntiAnnoy(clock=lambda: self.t[0])

    def frame(self, k: int, dets, t=None, ego=None) -> tuple[hazard.Hazard, bool]:
        # t/ego chỉ để chung giao diện với PredictPipeline: logic cũ KHÔNG dùng (đồng hồ giả theo khung như cũ)
        self.t[0] = k * hs.DT
        hz = self.tracker.assess(dets)
        sent = self.anti.step(hz.level if hz.level >= MIN_LEVEL() else 0)
        return hz, bool(sent)


class DeadPipeline(BaselinePipeline):
    """Đối chứng phá hoại 1: không bao giờ cảnh báo -> kịp thời phải = 0."""
    name = "control_dead"

    def frame(self, k, dets, t=None, ego=None):
        return hazard.Hazard(0), False


class AlwaysCriticalPipeline(BaselinePipeline):
    """Đối chứng phá hoại 2: luôn mức 3 -> bíp ở mọi kịch bản an toàn (báo nhầm phải > 0, kịp thời cao)."""
    name = "control_always3"

    def frame(self, k, dets, t=None, ego=None):
        self.t[0] = k * hs.DT
        hz = hazard.Hazard(3, "center", "x")
        return hz, bool(self.anti.step(3))


class PredictPipeline:
    """HAZARD_LOGIC=predict: PredictTracker + AntiAnnoy(l3_vote, down_hold, bypass_vote). Đồng hồ AntiAnnoy = mốc thời gian
    thật của khung (scn.times[k]); ego (shift, blur) lấy từ scn.ego[k] như ego_motion.measure trả ở server."""

    name = "predict"

    def __init__(self, params) -> None:
        from live import hazard_predict  # noqa: PLC0415  (chỉ có ở nhánh od-du-doan)
        self.params = params
        self.t = [0.0]
        self.tracker = hazard_predict.PredictTracker(params)
        kw = {} if getattr(params, "release_s", None) is None else {"release_s": params.release_s}   # đuôi nhả (VH mới có)
        self.anti = hazard.AntiAnnoy(clock=lambda: self.t[0], l3_vote=params.l3_vote, down_hold=params.down_hold,
                                     bypass_vote=params.bypass_vote, **kw)

    def frame(self, k: int, dets, t=None, ego=None) -> tuple[hazard.Hazard, bool]:
        from live import ego_motion  # noqa: PLC0415
        self.t[0] = k * hs.DT if t is None else t
        e = None if ego is None else ego_motion.Ego(shift_x=float(ego[0]), blur=float(ego[1]))
        hz = self.tracker.assess(dets, self.t[0], e)
        sent = self.anti.step(hz.level if hz.level >= MIN_LEVEL() else 0, urgent=bool(getattr(hz, "urgent", False)))
        return hz, bool(sent)


def predict_maker(params):
    """Nhà máy cho simulate(): mỗi kịch bản một PredictPipeline mới."""
    return lambda: PredictPipeline(params)


def simulate(scn: hs.Scenario, make=BaselinePipeline) -> dict:
    pipe = make()
    levels, beeps, step_us = [], [], []
    bdir, bz, bx = [], [], []                      # hướng gửi kính + Z, X thật của vật chính tại khung bíp
    times = list(scn.times) if scn.times else [k * hs.DT for k in range(scn.n_frames)]
    for k, dets in enumerate(scn.frames):
        ego = scn.ego[k] if scn.ego else None
        t = time.perf_counter()
        hz, sent = pipe.frame(k, dets, times[k], ego)
        step_us.append((time.perf_counter() - t) * 1e6)
        levels.append(hz.level)
        if sent:
            beeps.append((k, hz.level))
            bdir.append(hz.dir)
            bz.append(float(scn.Z[k]) if k < len(scn.Z) else None)
            bx.append(float(scn.X[k]) if k < len(scn.X) else None)
    return {"type": scn.type, "seed": scn.seed, "positive": scn.positive, "t_danger_frame": scn.t_danger_frame,
            "n_frames": scn.n_frames, "minutes": scn.minutes, "levels": "".join(str(l) for l in levels),
            "beeps": beeps, "group": scn.group, "t_visible_frame": scn.t_visible_frame,
            "times": [round(float(x), 4) for x in times], "t_clear_frame": scn.t_clear_frame, "beep_dir": bdir,
            "beep_z": bz, "beep_x": bx, "_us": step_us}


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


def _tt(rec: dict, k: int) -> float:
    """Mốc thời gian (s) của khung k; bản ghi cũ không có `times` thì dùng 125 ms/khung."""
    tm = rec.get("times")
    return float(tm[k]) if tm else k * hs.DT


def dir_truth(x: float | None) -> str | None:
    """Phía vật theo hình học (cùng quy ước kính): ngoài hành lang trái/phải, trong hành lang = center."""
    if x is None:
        return None
    return "left" if x < -hs.LANE_HALF else "right" if x > hs.LANE_HALF else "center"


def score(rec: dict) -> dict:
    """Từ một bản ghi mô phỏng -> các số của kịch bản (chấm lại được từ per_sample, không cần mô phỏng).
    Nhóm "sudden": kịp thời = bíp mức>=2 trước t_danger VÀ <= 2 khung kể từ khung đầu thấy vật (spec 5.4)."""
    beeps = rec["beeps"]
    td = rec["t_danger_frame"]
    out = {"n_sent": len(beeps),
           "n_sent_level_changes": int(sum(1 for a, b in zip(beeps, beeps[1:]) if a[1] != b[1])),
           "n_frame_level_changes": int(sum(1 for a, b in zip(rec["levels"], rec["levels"][1:]) if a != b))}
    if td is not None:
        first = next((k for k, lvl in beeps if lvl >= 2 and k < td), None)
        out["miss"] = int(first is None)
        out["lead_s"] = None if first is None else _tt(rec, td) - _tt(rec, first)
        out["timely"] = int(first is not None and out["lead_s"] >= LEAD_REQUIRED_S)
        tv = rec.get("t_visible_frame")
        if rec.get("group") == "sudden" and tv is not None:
            out["max_lead_s"] = _tt(rec, td) - _tt(rec, tv)
            out["impossible"] = int(td - tv < 1)               # lead tối đa < 1 khung: loại khỏi mẫu số
            out["reveal_delay_s"] = None if first is None else _tt(rec, first) - _tt(rec, tv)
            out["timely_sudden"] = int(first is not None and (first - tv) <= SUDDEN_MAX_FRAMES)
            out["timely"] = out["timely_sudden"]               # nhóm sudden dùng định nghĩa này
        # hướng: bíp mức>=2 đầu tiên (trước t_danger) khớp phía vật theo hình học
        if first is not None and rec.get("beep_dir"):
            j = next(i for i, (k, _) in enumerate(beeps) if k == first)
            tr = dir_truth(rec["beep_x"][j])
            out["dir_correct"] = None if tr is None else int(rec["beep_dir"][j] == tr)
    tc = rec.get("t_clear_frame")
    if tc is not None and beeps:                   # kêu thừa sau khi thoát: bíp cuối trước t_clear -> 0
        out["tail_after_clear_s"] = max(0.0, _tt(rec, beeps[-1][0]) - _tt(rec, tc))
    d = algo_delay_frames(rec)
    out["algo_delay_ms"] = None if d is None else d * hs.DT * 1000
    return out


def tail_block(scores: list[dict]) -> dict | None:
    """Đuôi bíp sau t_clear: p50/p90 (s) và % kịch bản còn bíp sau t_clear + TAIL_LIMIT_S; chỉ kịch bản có t_clear và có bíp."""
    v = [s["tail_after_clear_s"] for s in scores if s.get("tail_after_clear_s") is not None]
    if not v:
        return None
    return {"p50": float(np.percentile(v, 50)), "p90": float(np.percentile(v, 90)), "n": len(v),
            "pct_over_1s": float(np.mean([x > TAIL_LIMIT_S for x in v]))}


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
        n_imp = sum(1 for i in idx_pos if sc[i].get("impossible"))
        idx_pos = [i for i in idx_pos if not sc[i].get("impossible")]   # "không thể cảnh báo": ra khỏi mẫu số
        if n_imp:
            b["n_impossible"] = n_imp
        if idx_pos:
            timely = [sc[i]["timely"] for i in idx_pos]
            miss = [sc[i]["miss"] for i in idx_pos]
            lead = [sc[i]["lead_s"] for i in idx_pos if sc[i]["lead_s"] is not None]
            b["n_positive"] = len(idx_pos)
            b["timely_rate"] = ci(timely)
            b["miss_rate"] = ci(miss)
            dc = [sc[i]["dir_correct"] for i in idx_pos if sc[i].get("dir_correct") is not None]
            b["dir_correct_rate"] = ci(dc) if dc else None
            rd = [sc[i]["reveal_delay_s"] for i in idx_pos if sc[i].get("reveal_delay_s") is not None]
            if rd:
                b["reveal_delay_s"] = {"p50": float(np.percentile(rd, 50)), "p90": float(np.percentile(rd, 90)), "n": len(rd)}
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
        tb = tail_block([sc[i] for i in idx_all])
        if tb:
            b["tail_after_clear_s"] = tb
        return b

    pos = [i for i, r in enumerate(recs) if r["positive"]]
    safe = [i for i, r in enumerate(recs) if not r["positive"] and r.get("group") not in ("control", "release")]   # control/release chỉ chẩn đoán
    res = {"overall": block(pos, safe), "by_type": {}}
    tb = tail_block(sc)                                  # đuôi tính trên MỌI kịch bản có t_clear (kể cả group release)
    if tb:
        res["overall"]["tail_after_clear_s"] = tb
    for t in dict.fromkeys(r["type"] for r in recs):
        ix = [i for i, r in enumerate(recs) if r["type"] == t]
        res["by_type"][t] = block([i for i in ix if recs[i]["positive"]], [i for i in ix if not recs[i]["positive"]])
        res["by_type"][t]["label"] = "positive" if recs[ix[0]]["positive"] else "safe"
    res["by_group"] = {}
    for g in dict.fromkeys(r.get("group", "legacy") for r in recs):
        ix = [i for i, r in enumerate(recs) if r.get("group", "legacy") == g]
        res["by_group"][g] = block([i for i in ix if recs[i]["positive"]], [i for i in ix if not recs[i]["positive"]])
    delays = [s["algo_delay_ms"] for s in sc if s["algo_delay_ms"] is not None]
    res["algo_delay_ms"] = common.latency_summary(delays)
    return res


def run_controls(n_seeds: int, predict_params=None) -> dict:
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
    if predict_params is not None:
        c.update(run_predict_controls(predict_params, min(n_seeds, 10)))
    c["all_pass"] = all(v.get("pass", True) for v in c.values() if isinstance(v, dict))
    return c


SHUFFLE_TYPES = ["motorbike_charge", "oncoming_person", "cross_person", "motorbike_swerve", "sudden_motorbike_alley"]
APPROACH_BASES = ("walk_static_", "oncoming_person", "motorbike_charge")   # vật tiến về người dùng (và biến thể nhiễu)
SETTLE_S = 1.0          # approach_then_stop: sau khi người dùng dừng, cho 1,0 s ổn định
REVERSE_FAR_M = hs.DANGER_Z + 1.0   # reverse_time: chỉ đếm bíp SAU khung đầu tiên mà Z thật > mốc này (3 m)


def shuffle_scenario(scn: hs.Scenario, seed: int = 0) -> hs.Scenario:
    """Xáo thứ tự khung (hộp + ego đi cùng nhau), giữ nguyên mốc thời gian -> chỉ là số chẩn đoán, không pass/fail."""
    import copy
    perm = np.random.default_rng([seed, scn.seed, 11]).permutation(scn.n_frames)
    out = copy.copy(scn)
    out.frames = [scn.frames[i] for i in perm]
    out.ego = [scn.ego[i] for i in perm] if scn.ego else scn.ego
    return out


def reverse_scenario(scn: hs.Scenario) -> hs.Scenario:
    """Đảo thời gian: khung đảo thứ tự, mốc thời gian dựng lại vẫn tăng, trượt ego đảo dấu và lệch một khung (vật đang lùi xa)."""
    import copy
    out = copy.copy(scn)
    n = scn.n_frames
    tm = list(scn.times) if scn.times else [k * hs.DT for k in range(n)]
    out.frames = scn.frames[::-1]
    out.Z, out.X = list(scn.Z)[::-1], list(scn.X)[::-1]      # Z/X thật cũng đảo (bíp ghi Z thật, dùng chấm đối chứng)
    out.t_clear_frame = None
    # ego là trượt giữa hai khung d_k = s_k − s_{k−1}: đảo thời gian thì d'_j = −d_{n−j} (j >= 1), khung đầu lấy −d_0 (chỉ là nhiễu)
    out.ego = [(-scn.ego[(n - j) % n][0], scn.ego[n - 1 - j][1]) for j in range(n)] if scn.ego else scn.ego
    out.times = [tm[0] + tm[-1] - tm[n - 1 - i] for i in range(n)]
    out.positive, out.t_danger_frame, out.t_visible_frame = False, None, None
    return out


def check_approach_stop(rec: dict, stop_k: int, settle_s: float = SETTLE_S) -> dict:
    """approach_then_stop: bíp mức 3 trước khi dừng là ĐÚNG (không biết người sẽ dừng); từ stop+settle_s đến hết phải
    0 bíp mức 3 VÀ mức từng khung < 3. Báo riêng trước / sau."""
    tm = rec["times"]
    t_ok = tm[stop_k] + settle_s
    b3 = [k for k, lv in rec["beeps"] if lv == 3]
    after = [k for k in b3 if tm[k] >= t_ok]
    lv_after = [i for i, ch in enumerate(rec["levels"]) if tm[i] >= t_ok and int(ch) >= 3]
    return {"level3_before": len(b3) - len(after), "level3_after": len(after), "frames_level3_after": len(lv_after),
            "pass": not after and not lv_after}


def reverse_ok_frame(Z) -> int:
    """Khung đầu tiên mà Z thật > DANGER_Z + 1,0 m (len(Z) nếu không có -> không đếm bíp nào)."""
    return next((i for i, z in enumerate(Z) if z > REVERSE_FAR_M), len(Z))


def check_reverse(rec: dict, k_ok: int) -> dict:
    """reverse_time: chỉ đếm bíp mức >= 2 SAU khung k_ok (vật đã lùi xa quá DANGER_Z + 1 m); pass = 0 bíp."""
    n = sum(1 for k, lv in rec["beeps"] if lv >= 2 and k > k_ok)
    return {"beeps_ge2_after_skip": n, "pass": n == 0}


def run_predict_controls(params, n_seeds: int) -> dict:
    """Đối chứng riêng cho predict (dev): approach_then_stop (sau dừng + 1 s không mức 3), reverse_time (vật lùi xa, sau khi Z > 3 m
    không bíp mức >= 2). Xáo khung chỉ là số chẩn đoán."""
    c = {}
    mk = predict_maker(params)
    stops = []
    for s in range(max(n_seeds, 1)):
        scn = hs.generate("approach_then_stop", s, "dev")
        zmin = min(scn.Z)
        stop_k = next(i for i, z in enumerate(scn.Z) if z <= zmin + 1e-6)     # khung đầu tiên chạm điểm dừng
        stops.append(check_approach_stop(simulate(scn, mk), stop_k))
    c["approach_then_stop"] = {
        "expect": f"từ stop+{SETTLE_S:g} s: 0 bíp mức 3 và mức khung < 3", "n": len(stops),
        "level3_before_stop": int(sum(x["level3_before"] for x in stops)),
        "level3_after_settle": int(sum(x["level3_after"] for x in stops)),
        "frames_level3_after_settle": int(sum(x["frames_level3_after"] for x in stops)),
        "pass": bool(all(x["pass"] for x in stops))}
    names = [t for t in hs.ALL_TYPES if t.startswith(APPROACH_BASES)]
    rev = []
    for t in names:
        for s in range(n_seeds):
            scn = hs.generate(t, s, "dev")
            if scn.positive:
                rs = reverse_scenario(scn)
                rev.append(check_reverse(simulate(rs, mk), reverse_ok_frame(rs.Z)))
    cnt = int(sum(x["beeps_ge2_after_skip"] for x in rev))
    c["reverse_time"] = {"expect": f"vật lùi xa: 0 bíp mức >= 2 sau khung đầu có Z > {REVERSE_FAR_M:g} m", "n": len(rev),
                         "beeps_ge2_after_skip": cnt, "n_fail_scenarios": int(sum(1 for x in rev if not x["pass"])),
                         "pass": bool(rev and cnt == 0)}
    dng = [x for x in (hs.generate(t, s, "dev") for t in SHUFFLE_TYPES for s in range(n_seeds)) if x.positive]

    def timely(scns):
        sc = [score(simulate(x, mk)) for x in scns]
        v = [d["timely"] for d in sc if not d.get("impossible")]
        return float(np.mean(v)) if v else float("nan")

    c["diag_shuffle_frames"] = {"expect": "chẩn đoán, không pass/fail", "n": len(dng), "timely_original": timely(dng),
                                "timely_shuffled": timely([shuffle_scenario(x) for x in dng]), "pass": True}
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
