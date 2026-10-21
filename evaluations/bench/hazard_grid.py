"""C1b — lưới tham số HAZARD_LOGIC=predict + luật chọn chốt trước (spec §6) + Pareto + báo cáo HAZARD_PREDICT.md (spec §7).

  dev : chạy 216 cấu hình song song (CPU, <= 8 tiến trình) trên seed DEV, áp luật chọn, ghi
        results/hazard/predict_grid_dev_<ts>.json (mọi cấu hình + Pareto + cấu hình chọn hoặc null).
  test: chỉ nhận --config (cấu hình đã chọn trên dev) + baseline, chạy MỘT lần trên seed TEST, ghi kết quả và
        reports/HAZARD_PREDICT.md. Không chỉnh gì sau khi xem test.

Dùng (từ evaluations/, SEEVIA_VH_DIR=.../vh-od):
  python -m bench.hazard_grid --split dev [--seeds 50] [--procs 8] [--types a,b] [--report PATH]
  python -m bench.hazard_grid --split test --config cfg.json [--dev-grid predict_grid_dev_*.json]
"""

import argparse
import datetime as _dt
import glob
import itertools
import json
import multiprocessing as mp
import os

import numpy as np

from bench import common

common.setup(gpu=False)  # thuần CPU, không đụng GPU

from bench import hazard_logic as hl  # noqa: E402
from bench import hazard_scenarios as hs  # noqa: E402

# ---- Lưới vòng 2 (648 = 3·2·3·1·3·1·2 · 3 v_conf_k · 2 yaw_tau_s); vòng 1 là 324 cấu hình, v_conf_k = yaw_tau_s = 0 -----------------------------------------------------------------------------
GRID = {
    "tte_l3_s": [1.0, 1.5, 2.0],
    "tte_l2_s": [2.5, 3.5],
    "new_near_m": [0.0, 3.0, 4.0],
    "sigma_k": [0.0],                              # vòng 2: bỏ 1,0 (lưới 10 seed: báo oan ×3, vi phạm nhiều nhất)
    "vote": [(1, True), (2, True), (2, False)],     # (l3_vote, bypass_vote); (1, -) bypass vô nghĩa nên để True
    "coast": [3],                                   # bỏ coast=2 để lưới không phình 648 khi thêm release_s
    "release_s": [0.25, 0.5],                       # đuôi nhả của AntiAnnoy; vòng 2 bỏ 1,0 (hoà với 0,25/0,5, kêu dai hơn)
    "v_conf_k": [0.0, 0.5, 1.0],                    # vòng 2 (2026-10-21 tối): chỉ tin phần vận tốc vượt k·σ_v; 0 = vòng 1
    "yaw_tau_s": [0.0, 3.0],                        # vòng 2: xét hành lang theo hướng THÂN (tích phân rò góc đầu); 0 = hướng đầu
}
FIXED = {"q": 1.0, "down_hold": 2}

# ---- Luật chọn (spec §6) ----------------------------------------------------------------------------------------
P90_BUDGET_US = 1000.0     # assess + step p90 <= 1 ms/khung
SAFE_TYPE_TOL = 0.05       # loại an toàn: % bíp không vượt baseline quá 5 điểm
TIMELY_TOL = 0.05          # loại nguy hiểm: kịp thời không giảm quá 5 điểm
TAIL_P90_MAX_S = 1.0       # ràng buộc thêm (chốt trước): đuôi bíp sau khi thoát nguy hiểm p90 <= 1,0 s trên dev
TIE_TOL = 0.01             # hoà trong 1 điểm kịp thời -> báo oan thấp hơn, rồi trễ thấp hơn
EPS = 1e-12
MAX_PROCS = 24            # máy dùng chung 40 nhân: chừa phần còn lại cho người khác
NFS_PROBE_BYTES = 5 * 1024 * 1024
BIG_FILE = 64 * 1024


def make_grid() -> list[dict]:
    """Mọi cấu hình của lưới; horizon_s = max(3,0; tte_l2_s)."""
    out = []
    for l3, l2, nn, sk, (vote, byp), co, rel, vk, yt in itertools.product(GRID["tte_l3_s"], GRID["tte_l2_s"], GRID["new_near_m"],
                                                                      GRID["sigma_k"], GRID["vote"], GRID["coast"],
                                                                      GRID["release_s"], GRID["v_conf_k"], GRID["yaw_tau_s"]):
        out.append({"tte_l3_s": l3, "tte_l2_s": l2, "new_near_m": nn, "sigma_k": sk, "l3_vote": vote,
                    "bypass_vote": byp, "coast": co, "release_s": rel, "v_conf_k": vk, "yaw_tau_s": yt, **FIXED, "horizon_s": max(3.0, l2)})
    return out


def to_params(cfg: dict):
    from live.hazard_predict import PredictParams  # noqa: PLC0415
    if "release_s" in cfg and "release_s" not in PredictParams.__dataclass_fields__:
        raise RuntimeError("VH chưa có PredictParams.release_s (đuôi nhả) — BLOCKED, không bỏ lặng lẽ")
    return PredictParams(**{k: v for k, v in cfg.items() if k in PredictParams.__dataclass_fields__})


# ---- Số liệu gọn của một cấu hình --------------------------------------------------------------------------------
def config_stats(recs: list[dict]) -> dict:
    """Gọn đủ cho luật chọn: kịp thời / % an toàn có bíp theo loại, báo oan/phút gộp, trễ. Loại `impossible` ra khỏi mẫu số."""
    sc = [hl.score(r) for r in recs]
    tim: dict[str, list] = {}
    sbeep: dict[str, list] = {}
    n_beep = minutes = 0.0
    for r, s in zip(recs, sc):
        if r["positive"]:
            if not s.get("impossible"):
                tim.setdefault(r["type"], []).append(s["timely"])
        elif r.get("group") not in ("control", "release"):   # control (approach_then_stop...) và release (sidestep) không vào báo oan
            sbeep.setdefault(r["type"], []).append(int(s["n_sent"] > 0))
            n_beep += s["n_sent"]
            minutes += r["minutes"]
    all_safe = [x for v in sbeep.values() for x in v]
    us = np.concatenate([r["_us"] for r in recs]) if recs and "_us" in recs[0] else np.array([0.0])
    dl = [s["algo_delay_ms"] for s in sc if s["algo_delay_ms"] is not None]
    tb = hl.tail_block(sc)
    tail_by = {}
    for t in dict.fromkeys(r["type"] for r in recs):
        b = hl.tail_block([s for r, s in zip(recs, sc) if r["type"] == t])
        if b:
            tail_by[t] = b
    t_by = {t: float(np.mean(v)) for t, v in tim.items()}
    return {"timely": float(np.mean(list(t_by.values()))) if t_by else float("nan"), "timely_by_type": t_by,
            "fa_per_min": float(n_beep / minutes) if minutes > 0 else 0.0,
            "safe_beep_pct": float(np.mean(all_safe)) if all_safe else 0.0,
            "safe_beep_by_type": {t: float(np.mean(v)) for t, v in sbeep.items()},
            "algo_delay_ms": float(np.mean(dl)) if dl else 0.0, "p90_us": float(np.percentile(us, 90)),
            "tail_p90_s": tb["p90"] if tb else None, "tail_p50_s": tb["p50"] if tb else None,
            "tail_pct_over_1s": tb["pct_over_1s"] if tb else None, "tail_by_type": tail_by, "n_scenarios": len(recs)}


def violations(st: dict, base: dict) -> list[str]:
    """Danh sách điều vi phạm ràng buộc 1–3 (rỗng = thoả). Dùng chung cho chọn trên dev và kiểm trên test (không kèm p90)."""
    v = []
    if st["fa_per_min"] > base["fa_per_min"] + EPS:
        v.append(f"báo oan/phút {st['fa_per_min']:.4f} > baseline {base['fa_per_min']:.4f}")
    if st["safe_beep_pct"] > base["safe_beep_pct"] + EPS:
        v.append(f"% an toàn có bíp {100 * st['safe_beep_pct']:.2f} > baseline {100 * base['safe_beep_pct']:.2f}")
    for t, x in st["safe_beep_by_type"].items():
        b = base["safe_beep_by_type"].get(t, 0.0)
        if x > b + SAFE_TYPE_TOL + EPS:
            v.append(f"loại an toàn {t}: % bíp {100 * x:.1f} > baseline {100 * b:.1f} + 5 điểm")
    for t, x in st["timely_by_type"].items():
        b = base["timely_by_type"].get(t)
        if b is not None and x < b - TIMELY_TOL - EPS:
            v.append(f"loại nguy hiểm {t}: kịp thời {100 * x:.1f} < baseline {100 * b:.1f} - 5 điểm")
    return v


def select(cfgs: list[dict], base: dict) -> tuple[dict | None, list[list[str]]]:
    """Luật chọn spec §6. cfgs = [{"config", "stats"}]. Trả (cấu hình chọn | None, vi phạm của từng cấu hình)."""
    viol = []
    for c in cfgs:
        v = violations(c["stats"], base)
        if c["stats"]["p90_us"] > P90_BUDGET_US:
            v.append(f"assess+step p90 {c['stats']['p90_us']:.0f} µs > 1000 µs")
        tp = c["stats"].get("tail_p90_s")
        if tp is not None and tp > TAIL_P90_MAX_S + EPS:
            v.append(f"đuôi bíp sau thoát p90 {tp:.2f} s > {TAIL_P90_MAX_S:g} s")
        viol.append(v)
    ok = [c for c, v in zip(cfgs, viol) if not v]
    if not ok:
        return None, viol                              # luật 5: không cấu hình nào thoả -> không chọn
    best = max(c["stats"]["timely"] for c in ok)
    tied = [c for c in ok if c["stats"]["timely"] >= best - TIE_TOL - EPS]
    return min(tied, key=lambda c: (c["stats"]["fa_per_min"], c["stats"]["algo_delay_ms"])), viol


def pareto(points: list[dict]) -> list[dict]:
    """Không bị trội: tối thiểu (fa_per_min, safe_beep_pct), tối đa timely. points: dict có 3 khoá đó."""
    def dom(a, b):  # a trội b
        le = a["fa_per_min"] <= b["fa_per_min"] and a["safe_beep_pct"] <= b["safe_beep_pct"] and a["timely"] >= b["timely"]
        lt = a["fa_per_min"] < b["fa_per_min"] or a["safe_beep_pct"] < b["safe_beep_pct"] or a["timely"] > b["timely"]
        return le and lt
    return [p for i, p in enumerate(points) if not any(dom(q, p) for j, q in enumerate(points) if j != i)]


# ---- Chạy mô phỏng song song (fork: kịch bản dùng chung qua bộ nhớ cha) ----------------------------------------------
_SC: list = []
_CFG = None


def _sim_one(i: int) -> dict:
    mk = hl.BaselinePipeline if _CFG is None else hl.predict_maker(to_params(_CFG))
    return hl.simulate(_SC[i], mk)


def sim_many(scns: list, cfg: dict | None, procs: int) -> list[dict]:
    """Mô phỏng mọi kịch bản với cấu hình `cfg` (None = baseline). Giữ `_us` để tính trễ."""
    global _SC, _CFG
    _SC, _CFG = scns, cfg
    if procs <= 1:
        return [_sim_one(i) for i in range(len(scns))]
    with mp.get_context("fork").Pool(min(procs, MAX_PROCS)) as pool:
        return pool.map(_sim_one, range(len(scns)), chunksize=16)


def _eval_cfg(i: int) -> dict:
    global _CFG
    cfg = _GRID[i]
    _CFG = cfg
    mk = hl.predict_maker(to_params(cfg))
    return {"config": cfg, "stats": config_stats([hl.simulate(s, mk) for s in _SC])}


_GRID: list = []


# ---- Ghi file an toàn trên NFS ---------------------------------------------------------------------------------
def nfs_probe(d: str) -> None:
    """NFS quota từng cắt âm thầm file lớn: ghi thử 5 MB + fsync, kiểm kích thước, xoá."""
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f".probe_{os.getpid()}")
    try:
        with open(p, "wb") as f:
            f.write(b"\0" * NFS_PROBE_BYTES)
            f.flush()
            os.fsync(f.fileno())
        got = os.path.getsize(p)
    finally:
        if os.path.exists(p):
            os.remove(p)
    if got != NFS_PROBE_BYTES:
        raise OSError(f"NFS probe: ghi {NFS_PROBE_BYTES} B nhưng đọc lại {got} B — quota/ghi cắt, dừng")


def write_text(path: str, text: str) -> str:
    data = text.encode("utf-8")
    d = os.path.dirname(os.path.abspath(path))
    if len(data) > BIG_FILE:
        nfs_probe(d)
    os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if os.path.getsize(path) != len(data):
        raise OSError(f"ghi {path} bị cắt: {os.path.getsize(path)} / {len(data)} B")
    return path


def write_json(path: str, payload: dict) -> str:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=1, default=float))
    json.load(open(path, encoding="utf-8"))            # đọc lại: phải là JSON hợp lệ
    return path


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M")


# ---- Phân tích trượt / báo oan (cho báo cáo) ------------------------------------------------------------------
def miss_cause(rec: dict, s: dict) -> str:
    """Nguyên nhân thô của ca không kịp thời (từ bản ghi, không đoán thêm)."""
    td = rec["t_danger_frame"]
    if rec.get("group") == "sudden" and s.get("reveal_delay_s") is not None and s.get("timely") == 0 and s["miss"] == 0:
        return "lộ diện rồi bíp quá 2 khung"
    if s["miss"] == 0:
        return "bíp mức >= 2 nhưng lead < 1,5 s"
    if any(k >= td and lv >= 2 for k, lv in rec["beeps"]):
        return "chỉ bíp sau t_danger"
    if any(k < td for k, _ in rec["beeps"]):
        return "chỉ bíp mức 1 trước t_danger"
    return "không bíp"


def false_alarm_cases(recs: list[dict], limit: int = 25) -> list[dict]:
    out = []
    for r in recs:
        if r["positive"] or not r["beeps"]:
            continue
        k, lv = r["beeps"][0]
        tv = r.get("t_visible_frame")
        why = ("vật mới xuất hiện gần (new_near / bỏ phiếu)" if tv is not None and k - tv <= 2
               else "quỹ đạo ngoại suy cắt hành lang (TTE)")
        out.append({"type": r["type"], "seed": r["seed"], "level": lv, "Z": r["beep_z"][0] if r.get("beep_z") else None,
                    "X": r["beep_x"][0] if r.get("beep_x") else None, "why": why, "n_beeps": len(r["beeps"])})
    return out[:limit] if limit else out


def paired_types(base_recs: list[dict], sel_recs: list[dict]) -> dict:
    """Bảng theo loại: baseline vs chọn, CI, bắt thêm / mất ghép đôi theo kịch bản (cùng chỉ số)."""
    mb, ms = hl.summarize(base_recs), hl.summarize(sel_recs)
    rows = {}
    sb = [hl.score(r) for r in base_recs]
    ss = [hl.score(r) for r in sel_recs]
    for t, b in mb["by_type"].items():
        s = ms["by_type"][t]
        row = {"label": b["label"], "base": b, "sel": s}
        if b["label"] == "positive":
            ix = [i for i, r in enumerate(base_recs) if r["type"] == t and not sb[i].get("impossible")]
            row["gained"] = int(sum(1 for i in ix if ss[i]["timely"] and not sb[i]["timely"]))
            row["lost"] = int(sum(1 for i in ix if sb[i]["timely"] and not ss[i]["timely"]))
        else:
            ix = [i for i, r in enumerate(base_recs) if r["type"] == t]
            row["gained"] = int(sum(1 for i in ix if ss[i]["n_sent"] == 0 and sb[i]["n_sent"] > 0))   # bớt báo oan
            row["lost"] = int(sum(1 for i in ix if ss[i]["n_sent"] > 0 and sb[i]["n_sent"] == 0))    # thêm báo oan
        rows[t] = row
    return {"rows": rows, "summary_base": mb, "summary_sel": ms}


# ---- Báo cáo -----------------------------------------------------------------------------------------------------
def _pc(x: dict | None, d: int = 1) -> str:
    if not x or x.get("value") is None or x["value"] != x["value"]:
        return "—"
    return f"{100 * x['value']:.{d}f} % [{100 * x['ci'][0]:.{d}f}–{100 * x['ci'][1]:.{d}f}]"


def _f(x, d=2) -> str:
    return "—" if x is None or x != x else f"{x:.{d}f}"


def render_report(dev: dict, test: dict | None) -> str:
    """HAZARD_PREDICT.md. dev = nội dung file lưới dev; test = kết quả chạy test (None nếu chưa có / không chọn được)."""
    L = []
    sel = dev.get("selected")
    viol = (test or {}).get("violations") or []
    if viol:                                         # dòng đầu tiên: KHÔNG ĐẠT (spec §6)
        L.append("**KHÔNG ĐẠT** — cấu hình chọn vi phạm ràng buộc báo oan trên test: " + "; ".join(viol))
        L.append("")
    elif sel is None:
        L.append("**KHÔNG CHỌN ĐƯỢC** cấu hình nào thoả ràng buộc trên dev (selected=null) — xem đường đánh đổi bên dưới để quyết.")
        L.append("")
    L += ["# Vật cản: dự đoán quỹ đạo (HAZARD_LOGIC=predict) — C1b", "",
          f"Sinh bởi `bench/hazard_grid.py` ({_dt.datetime.now():%Y-%m-%d %H:%M}). Dev = seed 1000+, test = seed 2000+, "
          "kịch bản tổng hợp; luật chọn chốt trước (spec §6).", "", "## 1. Tóm tắt", ""]
    b = dev["baseline"]
    L.append(f"- Lưới dev: {len(dev['configs'])} cấu hình, {dev.get('n_scenarios', '?')} kịch bản/cấu hình. Baseline dev: kịp thời "
             f"{100 * b['timely']:.1f} %, báo oan {b['fa_per_min']:.3f}/phút, {100 * b['safe_beep_pct']:.1f} % kịch bản an toàn có bíp.")
    if sel is None:
        L.append("- **selected = null**: không cấu hình nào thoả ràng buộc 1–3 (báo oan, trễ, không tệ đi).")
    else:
        st = sel["stats"]
        L.append(f"- Cấu hình chọn (dev): `{json.dumps(sel['config'], ensure_ascii=False)}` — kịp thời {100 * st['timely']:.1f} %, báo oan "
                 f"{st['fa_per_min']:.3f}/phút, {100 * st['safe_beep_pct']:.1f} % an toàn có bíp, p90 {st['p90_us']:.0f} µs.")
    if test:
        ob, os_ = test["summary_base"]["overall"], test["summary_sel"]["overall"]
        L.append(f"- Test (một lần): kịp thời baseline {_pc(ob.get('timely_rate'))} -> chọn {_pc(os_.get('timely_rate'))}; báo oan/phút "
                 f"{_f(ob['false_alarms_per_min']['value'], 3)} -> {_f(os_['false_alarms_per_min']['value'], 3)}.")
    elif sel is not None:
        L.append("- Chưa chạy test.")
    L += ["", "## 2. Bảng theo loại (test; baseline vs chọn)", ""]
    if test:
        L += ["| Loại | Nhãn | Baseline | Chọn | Bắt thêm / mất |", "|---|---|---|---|---|"]
        for t, r in test["per_type"].items():
            if r["label"] == "positive":
                bb, ss = _pc(r["base"].get("timely_rate")), _pc(r["sel"].get("timely_rate"))
                gl = f"+{r['gained']} / −{r['lost']}"
            else:
                bb = f"{_f(r['base'].get('false_alarms_per_min', {}).get('value'), 3)}/phút; {_pc(r['base'].get('safe_scenarios_with_beep'))} bíp"
                ss = f"{_f(r['sel'].get('false_alarms_per_min', {}).get('value'), 3)}/phút; {_pc(r['sel'].get('safe_scenarios_with_beep'))} bíp"
                gl = f"bớt {r['gained']} / thêm {r['lost']} kịch bản báo oan"
            L.append(f"| {t} | {'nguy hiểm (kịp thời)' if r['label'] == 'positive' else 'an toàn'} | {bb} | {ss} | {gl} |")
        L += ["", "Theo nhóm (kịp thời, `dir` đúng phía):", ""]
        for g, bl in test["summary_sel"]["by_group"].items():
            if "timely_rate" in bl:
                bg = test["summary_base"]["by_group"][g]
                L.append(f"- {g}: kịp thời {_pc(bg.get('timely_rate'))} -> {_pc(bl['timely_rate'])}; dir đúng {_pc(bl.get('dir_correct_rate'))}"
                         + (f"; không thể cảnh báo: {bl['n_impossible']}" if bl.get("n_impossible") else "")
                         + (f"; trễ lộ diện->bíp p50/p90 {bl['reveal_delay_s']['p50']:.2f}/{bl['reveal_delay_s']['p90']:.2f} s"
                            if bl.get("reveal_delay_s") else ""))
    else:
        L.append("(chưa có test)")
    L += ["", "## 3. Pareto dev (báo oan/phút, % an toàn có bíp, kịp thời)", "",
          "| | cấu hình | báo oan/phút | % an toàn bíp | kịp thời |", "|---|---|---|---|---|"]
    groups: dict = {}                                # điểm trùng hệt nhau gộp một dòng (đánh dấu chọn / baseline giữ lại)
    for p in dev["pareto"]:
        key = (round(p["fa_per_min"], 6), round(p["safe_beep_pct"], 6), round(p["timely"], 6))
        g = groups.setdefault(key, {"p": p, "n": 0, "sel": False, "base": False})
        g["n"] += 1
        g["sel"] |= bool(p.get("selected"))
        g["base"] |= bool(p.get("baseline"))
        if p.get("selected") or p.get("baseline"):
            g["p"] = p
    for g in groups.values():
        p = g["p"]
        tag = "BASELINE" if g["base"] else ("CHỌN" if g["sel"] else "")
        L.append(f"| {tag} | `{json.dumps(p['config'], ensure_ascii=False) if p.get('config') else 'logic cũ'}`"
                 f"{' (+' + str(g['n'] - 1) + ' cấu hình cùng điểm)' if g['n'] > 1 else ''} | {p['fa_per_min']:.3f} | "
                 f"{100 * p['safe_beep_pct']:.1f} | {100 * p['timely']:.1f} |")
    L += ["", "Đọc: đi từ điểm này sang điểm kia là 'nới báo oan lên X lần/phút thì được thêm Y điểm kịp thời'.", "",
          "## 4. Ca báo oan còn lại (test, cấu hình chọn)", ""]
    fa = (test or {}).get("false_alarms") or []
    L += ([f"- {c['type']} seed {c['seed']}: mức {c['level']}, Z={_f(c['Z'])} m, X={_f(c['X'])} m — {c['why']}" for c in fa]
          or ["(không có / chưa chạy test)"])
    L += ["", "## 5. Ca trượt / muộn còn lại (test, theo nguyên nhân)", ""]
    ms = (test or {}).get("miss_causes") or {}
    for t, d in ms.items():
        L.append(f"- {t}: " + ", ".join(f"{k} ×{v}" for k, v in d.items()))
    if not ms:
        L.append("(không có / chưa chạy test)")
    L += ["", "## 6. Đối chứng", ""]
    for k, v in ((test or {}).get("controls") or {}).items():
        if isinstance(v, dict):
            L.append(f"- {k}: {('DIAG' if 'diag' in k else 'PASS' if v['pass'] else 'FAIL')} — {v.get('expect', '')}")
    L += ["", "## 7. Kêu thừa sau khi thoát nguy hiểm", "",
          "Người dùng muốn: thoát nguy hiểm thì kêu thêm chút rồi dừng. Đuôi = (khung bíp cuối − t_clear) trên kịch bản có t_clear và có bíp "
          "(0 nếu bíp cuối trước t_clear); 'còn bíp' = còn bíp sau t_clear + 1,0 s. Ràng buộc chọn: p90 <= "
          f"{TAIL_P90_MAX_S:g} s trên dev.", ""]
    if test:
        L += ["| Loại | Baseline p50 / p90 (s) | Chọn p50 / p90 (s) | Chọn: % còn bíp sau +1 s | n |", "|---|---|---|---|---|"]
        for t, r in test["per_type"].items():
            tb, ts = r["base"].get("tail_after_clear_s"), r["sel"].get("tail_after_clear_s")
            if tb or ts:
                f2 = lambda x: "—" if not x else f"{x['p50']:.2f} / {x['p90']:.2f}"  # noqa: E731
                pct = "—" if not ts else f"{100 * ts['pct_over_1s']:.1f} %"
                L.append(f"| {t} | {f2(tb)} | {f2(ts)} | {pct} | {(ts or tb)['n']} |")
    else:
        L.append("(chưa có test)")
    L += ["", "## 8. Trễ", ""]
    lat = (test or {}).get("latency")
    if lat:
        L.append(f"- assess+step p90 (CPU): baseline {lat['base_p90_us']:.0f} µs, chọn {lat['sel_p90_us']:.0f} µs (ngân sách 1000 µs).")
        L.append(f"- Trễ thuật toán trung bình: baseline {lat['base_algo_delay_ms']:.0f} ms, chọn {lat['sel_algo_delay_ms']:.0f} ms.")
    L.append("- Đo dịch chuyển/nhoè (<= 2 ms) và tổng chuỗi server (<= 10 ms): `bench/hazard_latency.py` (C1c), không đo ở đây.")
    L += ["", "## 9. Giới hạn", "",
          "- Dữ liệu tổng hợp (bộ sinh tự viết); bàn đo kiểm LOGIC với detector lý tưởng, không kiểm khả năng thấy vật (C1a).",
          "- Vật không có lớp trong bảng chiều cao: Z suy từ đáy hộp, kém chính xác hơn.",
          "- Giả định camera nhìn thẳng; góc cúi chỉ học dần, không có IMU.",
          "- Con số không chuyển thẳng sang đường phố thật; cần chạy lại trên clip thật trước khi bật mặc định.",
          "- Đo trễ trong lưới chạy song song 8 tiến trình trên máy dùng chung nên p90 có thể cao hơn thực tế."]
    return "\n".join(L) + "\n"


# ---- Chạy ------------------------------------------------------------------------------------------------------
def run_dev(args) -> dict:
    global _SC, _GRID
    types = args.types.split(",") if args.types else None
    scns = hs.generate_all(args.seeds, types, "dev")
    _SC = scns
    print(f"dev: {len(scns)} kịch bản", flush=True)
    base = config_stats([hl.simulate(s) for s in scns])
    _GRID = make_grid()
    print(f"lưới {len(_GRID)} cấu hình, {args.procs} tiến trình", flush=True)
    if args.procs <= 1:
        res = [_eval_cfg(i) for i in range(len(_GRID))]
    else:
        with mp.get_context("fork").Pool(min(args.procs, MAX_PROCS)) as pool:
            res = []
            for n, r in enumerate(pool.imap(_eval_cfg, range(len(_GRID)), chunksize=1), 1):
                res.append(r)
                if n % 12 == 0 or n == len(_GRID):
                    print(f"  {n}/{len(_GRID)}", flush=True)
    chosen, viol = select(res, base)
    for r, v in zip(res, viol):
        r["violations"] = v
    pts = [{"fa_per_min": r["stats"]["fa_per_min"], "safe_beep_pct": r["stats"]["safe_beep_pct"], "timely": r["stats"]["timely"],
            "config": r["config"]} for r in res]
    pts.append({"fa_per_min": base["fa_per_min"], "safe_beep_pct": base["safe_beep_pct"], "timely": base["timely"],
                "config": None, "baseline": True})
    front = pareto(pts)
    for p in front:
        p["selected"] = bool(chosen and p["config"] == chosen["config"])
    return {"meta": common.run_meta({"split": "dev", "seeds": args.seeds, "types": types, "grid": {k: [list(x) if isinstance(x, tuple) else x for x in v] for k, v in GRID.items()},
                                     "fixed": FIXED, "rule": {"p90_us": P90_BUDGET_US, "tail_p90_max_s": TAIL_P90_MAX_S, "safe_type_tol": SAFE_TYPE_TOL,
                                                              "timely_tol": TIMELY_TOL, "tie_tol": TIE_TOL}}),
            "n_scenarios": len(scns), "baseline": base, "configs": res, "pareto": front, "selected": chosen,
            "n_pass": sum(1 for v in viol if not v)}


def run_test(args, dev: dict) -> dict:
    cfg = args.cfg
    types = args.types.split(",") if args.types else None
    scns = hs.generate_all(args.seeds, types, "test")
    print(f"test: {len(scns)} kịch bản (chạy MỘT lần)", flush=True)
    brec = sim_many(scns, None, args.procs)
    srec = sim_many(scns, cfg, args.procs)
    bst, sst = config_stats([dict(r) for r in brec]), config_stats([dict(r) for r in srec])
    viol = violations(sst, bst)
    for r in brec + srec:
        r.pop("_us", None)
    pt = paired_types(brec, srec)
    causes: dict = {}
    for r in srec:
        if r["positive"]:
            s = hl.score(r)
            if s.get("impossible") or s["timely"]:
                continue
            causes.setdefault(r["type"], {}).setdefault(miss_cause(r, s), 0)
            causes[r["type"]][miss_cause(r, s)] += 1
    ctr = hl.run_controls(min(args.seeds, 50), to_params(cfg))
    return {"meta": common.run_meta({"split": "test", "seeds": args.seeds, "config": cfg}), "config": cfg,
            "base_stats": bst, "sel_stats": sst, "violations": viol, "per_type": pt["rows"],
            "summary_base": pt["summary_base"], "summary_sel": pt["summary_sel"], "false_alarms": false_alarm_cases(srec),
            "miss_causes": causes, "controls": ctr,
            "latency": {"base_p90_us": bst["p90_us"], "sel_p90_us": sst["p90_us"], "base_algo_delay_ms": bst["algo_delay_ms"],
                        "sel_algo_delay_ms": sst["algo_delay_ms"], "cpu_only": True}}


def _load_cfg(s: str) -> dict:
    d = json.load(open(s, encoding="utf-8")) if os.path.exists(s) else json.loads(s)
    if "selected" in d and isinstance(d["selected"], dict):
        d = d["selected"].get("config", d["selected"])
    elif "config" in d and isinstance(d["config"], dict):
        d = d["config"]
    return d


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--config", default=None, help="test: JSON cấu hình đã chọn (đường dẫn hoặc chuỗi JSON)")
    ap.add_argument("--dev-grid", default=None, help="test: file lưới dev để vẽ Pareto trong báo cáo (mặc định: mới nhất)")
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--types", default=None, help="danh sách loại cách nhau dấu phẩy (chạy thử)")
    ap.add_argument("--out", default=None, help="thư mục kết quả (mặc định results/hazard)")
    ap.add_argument("--report", default=None, help="đường dẫn HAZARD_PREDICT.md (mặc định reports/; chạy thử thì không ghi)")
    args = ap.parse_args(argv)
    out_dir = args.out or os.path.join(common.RESULTS, "hazard")
    partial = bool(args.types) or args.seeds < 50
    report = args.report or (None if partial else os.path.join(common.REPORTS, "HAZARD_PREDICT.md"))
    if args.split == "dev":
        dev = run_dev(args)
        path = write_json(os.path.join(out_dir, f"predict_grid_dev_{_ts()}.json"), dev)
        print("ghi", path)
        sel = dev["selected"]
        print("selected =", "null" if sel is None else json.dumps(sel["config"], ensure_ascii=False),
              f"| {dev['n_pass']}/{len(dev['configs'])} cấu hình thoả | Pareto {len(dev['pareto'])} điểm")
        if report and sel is None:
            print("ghi", write_text(report, render_report(dev, None)))
        return
    if not args.config:
        ap.error("--split test chỉ nhận --config (cấu hình đã chọn trên dev)")
    args.cfg = _load_cfg(args.config)
    dg = args.dev_grid or next(iter(sorted(glob.glob(os.path.join(out_dir, "predict_grid_dev_*.json")), key=os.path.getmtime)[::-1]), None)
    if not dg:
        ap.error("không thấy predict_grid_dev_*.json; truyền --dev-grid")
    dev = json.load(open(dg, encoding="utf-8"))
    test = run_test(args, dev)
    path = write_json(os.path.join(out_dir, f"predict_test_{_ts()}.json"), test)
    print("ghi", path)
    print("KHÔNG ĐẠT:" if test["violations"] else "đạt ràng buộc báo oan", test["violations"])
    if report:
        print("ghi", write_text(report, render_report(dev, test)))


if __name__ == "__main__":
    main()
