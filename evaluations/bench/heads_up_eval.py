"""C1d — chấm logic cảnh báo vật cản trên dữ liệu THẬT HEADS-UP [Haghighi et al., arXiv:2409.20324, 2024; Apache-2.0].

Camera ZED Mini gắn mũ (1280×720, 30 fps, f ≈ 700 px), người đeo đi bộ thật giữa người đi bộ thật. Hộp người là YOLOv8 + ByteTrack
của bộ dữ liệu (detector thật, nhiễu thật). Vị trí 3D (depth stereo) và tư thế camera (VIO) CHỈ dùng làm đáp án — logic không đọc.

Mô phỏng camera kính: cắt vùng giữa 66° HFOV, 4:3 (909×682 px quanh tâm quang học), chuẩn hoá hộp theo vùng cắt, lấy mẫu 8 fps
(khung gần mốc k/8 s nhất). Chỉ có NGƯỜI ĐI BỘ — không có xe máy, không có giao thông Việt Nam.

Đáp án (hệ thân = hướng ĐI của người đeo, từ vận tốc VIO cửa sổ 1 s; đứng yên thì theo hướng nhìn):
  vào lối = tâm người có 0 < Z < 2 m và |X| < 0,6 m (cùng định nghĩa C1b).
Chấm trên dòng liên tục:
  kịp thời = có bíp trong [t_vào − 5 s, t_vào − 1,5 s]; mẫu số chỉ gồm ca lộ diện (thấy trong vùng cắt) trước t_vào ≥ 1,5 s.
  báo oan = bíp mà không ai đang trong lối và không ai vào lối trong 5 s sau đó; tính thêm bản "bỏ ca suýt": người đi qua |X| < 1 m, Z < 2 m.
Đối chứng âm: bíp ngẫu nhiên cùng số lần (200 lần lặp) -> kịp thời ngẫu nhiên; logic thật phải vượt rõ.

Dùng (từ evaluations/, SEEVIA_VH_DIR=.../vh-od):
  python -m bench.heads_up_eval [--ego none|pose|image] [--out results/heads_up]
Không tinh chỉnh tham số trên bộ này: chỉ chấm cấu hình đã chọn trên bàn đo tổng hợp (kiểm độc lập).
"""

import argparse
import ast
import csv
import json
import math
import os
import time

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import hazard_logic as hl  # noqa: E402
from bench import hazard_scenarios as hs  # noqa: E402
from live import hazard  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datas", "heads_up")
SEQS = ("easy", "hard", "unconstrained")
SRC_FPS = 30.0
F_PX, CX, CY = 700.0, 612.0, 360.0               # khớp hồi quy tâm hộp ~ X/Z trên easy (r = 0,9993)
CROP_W = 2 * F_PX * math.tan(math.radians(hs.HFOV_DEG / 2))
CROP_H = CROP_W * 3 / 4
CROP = (CX - CROP_W / 2, CY - CROP_H / 2)
MIN_BOX = hs.MIN_BOX_PX * CROP_W / hs.IMG_W      # cùng ngưỡng "detector không thấy" của C1b, đổi sang px vùng cắt
DANGER_Z, LANE = hs.DANGER_Z, hs.LANE_HALF
LEAD_S, WARN_S = 1.5, 5.0
NEAR_X = 1.0
SHARP = 150.0                                     # blur danh nghĩa khi ego lấy từ tư thế (ảnh nét)

CANDIDATES = {  # cấu hình tốt nhất từng biến thể trên lưới dev tổng hợp vòng 2 (predict_grid_dev_20261021-1927.json)
    "V1": {"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": True, "coast": 3,
           "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0},
    "V2": {"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": True, "coast": 3,
           "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0},
}


def _rot(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def load(seq: str) -> dict:
    """Khung có tư thế -> (vị trí, R) và danh sách người {id, p_world, bbox}."""
    poses = {}
    with open(os.path.join(DATA, f"{seq}_camera_poses.csv")) as fh:
        for r in csv.DictReader(fh):
            poses[int(r["frame"].strip('"'))] = (np.array([float(r[k]) for k in ("x", "y", "z")]),
                                                 _rot([float(r[k]) for k in ("q1", "q2", "q3", "q4")]))
    objs = {}
    with open(os.path.join(DATA, f"{seq}_trajectory_raw.csv")) as fh:
        for r in csv.DictReader(fh):
            objs[int(r["frame"].strip('"'))] = ast.literal_eval(r["coordinates"])
    return {"poses": poses, "objs": objs}


def body_frames(d: dict) -> dict:
    """Mỗi khung: (gốc, hướng đi, hướng ngang, hướng xuống, tốc độ, góc đầu quanh trục đứng)."""
    fr = sorted(d["poses"])
    down = np.mean([d["poses"][f][1] @ np.array([0.0, 1.0, 0.0]) for f in fr[::10]], axis=0)
    down /= np.linalg.norm(down)
    hz = lambda v: v - np.dot(v, down) * down  # noqa: E731
    pos = np.array([d["poses"][f][0] for f in fr])
    ref = hz(d["poses"][fr[0]][1] @ np.array([0.0, 0.0, 1.0]))
    ref /= np.linalg.norm(ref)
    out = {}
    for i, f in enumerate(fr):
        j0, j1 = max(0, i - 15), min(len(fr) - 1, i + 15)
        v = hz(pos[j1] - pos[j0])
        spd = float(np.linalg.norm(v)) / max((fr[j1] - fr[j0]) / SRC_FPS, 1e-6)
        look = hz(d["poses"][f][1] @ np.array([0.0, 0.0, 1.0]))
        look /= np.linalg.norm(look)
        fwd = v / np.linalg.norm(v) if spd > 0.3 else look
        lat = np.cross(down, fwd)
        yaw = math.atan2(float(np.dot(np.cross(ref, look), down)), float(np.dot(ref, look)))
        out[f] = (pos[i], fwd, lat, down, spd, yaw)
    return out


def sample_frames(fr: list[int], fps: float = 1.0 / hs.DT) -> list[int]:
    """Khung nguồn gần mốc k/fps nhất (kính gửi ~8 fps)."""
    fs, t_end = [], fr[-1] / SRC_FPS
    have = set(fr)
    k = 0
    while k / fps <= t_end:
        f = int(round(k / fps * SRC_FPS))
        for c in (f, f - 1, f + 1, f - 2, f + 2):
            if c in have:
                fs.append(c)
                break
        k += 1
    return sorted(set(fs))


def crop_box(b):
    """bbox [x, y, w, h] px nguồn -> hộp chuẩn hoá trong vùng cắt kính, None nếu ngoài/quá nhỏ."""
    x0, y0 = max(b[0], CROP[0]), max(b[1], CROP[1])
    x1, y1 = min(b[0] + b[2], CROP[0] + CROP_W), min(b[1] + b[3], CROP[1] + CROP_H)
    if x1 - x0 < MIN_BOX or y1 - y0 < MIN_BOX:
        return None
    return ((x0 - CROP[0]) / CROP_W, (y0 - CROP[1]) / CROP_H, (x1 - CROP[0]) / CROP_W, (y1 - CROP[1]) / CROP_H)


def build(seq: str) -> dict:
    """Dòng khung 8 fps: hộp (đầu vào logic), toạ độ hệ thân (đáp án), góc đầu (cho ego 'pose')."""
    d = load(seq)
    bf = body_frames(d)
    fs = sample_frames(sorted(bf))
    frames, truth, yaw, times = [], [], [], []
    for f in fs:
        o, fwd, lat, down, spd, yw = bf[f]
        dets, gt = [], []
        for ob in d["objs"].get(f, []):
            p = np.array([ob["x"], ob["y"], ob["z"]]) - o
            p = p - np.dot(p, down) * down
            Z, X = float(np.dot(p, fwd)), float(np.dot(p, lat))
            box = crop_box(ob["bbox"])
            gt.append((ob["id"], Z, X, box is not None))
            if box is not None:
                dets.append(hazard.Detection("person", "person", 0.9, box))
        frames.append(dets)
        truth.append(gt)
        yaw.append(yw)
        times.append(f / SRC_FPS)
    return {"seq": seq, "frames": frames, "truth": truth, "yaw": yaw, "times": times}


def events(s: dict) -> list[dict]:
    """Mỗi track: lần đầu vào lối (sau khi đã ngoài lối) -> {id, t_in, t_seen, possible}."""
    ev, seen, inside = [], {}, set()
    for t, gt in zip(s["times"], s["truth"]):
        for tid, Z, X, vis in gt:
            if vis and tid not in seen:
                seen[tid] = t
            ins = 0 < Z < DANGER_Z and abs(X) < LANE
            if ins and tid not in inside:
                inside.add(tid)
                ts = seen.get(tid)
                ev.append({"id": tid, "t_in": t, "t_seen": ts, "possible": ts is not None and t - ts >= LEAD_S})
    return ev


def ego_stream(s: dict, mode: str):
    if mode == "none":
        return [None] * len(s["times"])
    if mode == "pose":   # yaw theo quy ước body_frames tăng thì cảnh trượt sang phải (kiểm: hồi quy Δu hộp ~ shift hệ số +1,07)
        y = np.unwrap(np.array(s["yaw"]))
        d = np.concatenate([[0.0], np.diff(y)])
        return [(float(a * F_PX / CROP_W), SHARP) for a in d]
    raise SystemExit(f"--ego {mode}: cần ảnh RGB (đợt 2), chưa nối")


def run(s: dict, make, ego) -> list[tuple[float, int]]:
    pipe = make()
    beeps = []
    for k, (dets, t, e) in enumerate(zip(s["frames"], s["times"], ego)):
        hz, sent = pipe.frame(k, dets, t, e)
        if sent:
            beeps.append((t, hz.level))
    return beeps


def score(s: dict, ev: list[dict], beeps: list[tuple[float, int]], rng=None, n_rand: int = 0) -> dict:
    bt = np.array([b[0] for b in beeps]) if beeps else np.zeros(0)
    pos = [e for e in ev if e["possible"]]

    def timely(times):
        return [bool(np.any((times >= e["t_in"] - WARN_S) & (times <= e["t_in"] - LEAD_S))) for e in pos]

    tl = timely(bt)
    ins_t = {round(t, 4) for t, gt in zip(s["times"], s["truth"]) for _, Z, X, _ in gt if 0 < Z < DANGER_Z and abs(X) < LANE}
    near_t = [t for t, gt in zip(s["times"], s["truth"]) for _, Z, X, _ in gt if 0 < Z < DANGER_Z and abs(X) < NEAR_X]
    t_in = np.array([e["t_in"] for e in ev]) if ev else np.zeros(0)
    near = np.array(near_t) if near_t else np.zeros(0)
    fa = fa_near = 0
    for t in bt:
        just = round(t, 4) in ins_t or bool(np.any((t_in >= t) & (t_in <= t + WARN_S)))
        if not just:
            fa += 1
            if not np.any((near >= t) & (near <= t + WARN_S)):
                fa_near += 1
    minutes = (s["times"][-1] - s["times"][0]) / 60.0
    out = {"n_events": len(ev), "n_possible": len(pos), "timely": int(sum(tl)), "n_beeps": int(len(bt)),
           "fa": fa, "fa_excl_near": fa_near, "minutes": minutes, "_timely_vec": tl}
    if rng is not None and n_rand and len(bt):
        t0, t1 = s["times"][0], s["times"][-1]
        out["rand_timely"] = float(np.mean([np.mean(timely(rng.uniform(t0, t1, len(bt)))) if pos else 0.0 for _ in range(n_rand)]))
    return out


def ci(vec, n=2000, seed=0) -> list[float]:
    v = np.asarray(vec, float)
    if not len(v):
        return [float("nan")] * 2
    r = np.random.default_rng(seed)
    m = [v[r.integers(0, len(v), len(v))].mean() for _ in range(n)]
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ego", default="pose", choices=["none", "pose", "image"])
    ap.add_argument("--out", default="results/heads_up")
    a = ap.parse_args(argv)
    from live import hazard_predict  # noqa: PLC0415
    rng = np.random.default_rng(0)
    makers = {"area": hl.BaselinePipeline}
    for name, cfg in CANDIDATES.items():
        p = hazard_predict.PredictParams(**{k: v for k, v in cfg.items() if k in hazard_predict.PredictParams.__dataclass_fields__})
        makers[name] = hl.predict_maker(p)
    res = {"meta": {"source": "HEADS-UP (Haghighi et al., arXiv:2409.20324, 2024)", "ego": a.ego, "crop_px": [CROP_W, CROP_H],
                    "f_px": F_PX, "fps": 1.0 / hs.DT, "candidates": CANDIDATES}, "by_seq": {}, "total": {}}
    tot = {m: {"timely_vec": [], "fa": 0, "fa_excl_near": 0, "minutes": 0.0, "n_beeps": 0, "rand": []} for m in makers}
    for seq in SEQS:
        t0 = time.time()
        s = build(seq)
        ev = events(s)
        ego = ego_stream(s, a.ego)
        res["by_seq"][seq] = {"n_frames": len(s["frames"]), "events": ev}
        for m, mk in makers.items():
            sc = score(s, ev, run(s, mk, ego if m != "area" else [None] * len(ego)), rng, 200)
            res["by_seq"][seq][m] = {k: v for k, v in sc.items() if not k.startswith("_")}
            tt = tot[m]
            tt["timely_vec"] += sc["_timely_vec"]
            tt["fa"] += sc["fa"]
            tt["fa_excl_near"] += sc["fa_excl_near"]
            tt["minutes"] += sc["minutes"]
            tt["n_beeps"] += sc["n_beeps"]
            if "rand_timely" in sc:
                tt["rand"].append((sc["rand_timely"], sc["n_possible"]))
            print(f"{seq:13s} {m:5s} ca vào lối {sc['n_events']} (có thể kịp {sc['n_possible']}) | kịp {sc['timely']} | bíp {sc['n_beeps']} | "
                  f"báo oan {sc['fa']} ({sc['fa'] / sc['minutes']:.2f}/phút; bỏ ca suýt {sc['fa_excl_near'] / sc['minutes']:.2f}) | "
                  f"ngẫu nhiên kịp {100 * sc.get('rand_timely', 0):.0f} %", flush=True)
        print(f"  ({time.time() - t0:.1f} s)", flush=True)
    for m, tt in tot.items():
        v = tt["timely_vec"]
        rw = sum(r * n for r, n in tt["rand"]) / max(sum(n for _, n in tt["rand"]), 1)
        res["total"][m] = {"timely": float(np.mean(v)) if v else None, "timely_ci": ci(v), "n_possible": len(v),
                           "fa_per_min": tt["fa"] / tt["minutes"], "fa_excl_near_per_min": tt["fa_excl_near"] / tt["minutes"],
                           "beeps_per_min": tt["n_beeps"] / tt["minutes"], "rand_timely": rw, "minutes": tt["minutes"]}
        r = res["total"][m]
        print(f"TỔNG {m:5s} kịp thời {100 * r['timely']:.1f} % [{100 * r['timely_ci'][0]:.0f}–{100 * r['timely_ci'][1]:.0f}] "
              f"(n={r['n_possible']}; bíp ngẫu nhiên cùng số lần {100 * rw:.1f} %) | báo oan {r['fa_per_min']:.2f}/phút "
              f"(bỏ ca suýt {r['fa_excl_near_per_min']:.2f}) | bíp {r['beeps_per_min']:.2f}/phút | {r['minutes']:.1f} phút")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"heads_up_{a.ego}_{time.strftime('%Y%m%d-%H%M')}.json")
    with open(path, "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=float)
    print("ghi", path)


if __name__ == "__main__":
    main()
