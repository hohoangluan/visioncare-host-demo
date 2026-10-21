"""Kiểm nhanh cho Gói H (không cần GPU/model): python -m pytest bench/test_hazard.py -q  (từ evaluations/)."""

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import hazard_detect as hd  # noqa: E402
from bench import hazard_logic as hl  # noqa: E402
from bench import hazard_scenarios as hs  # noqa: E402


def test_source_and_group():
    assert hd.source_of("000000000307.jpg") == "coco" and hd.group_of("000000000307.jpg") == "coco"
    assert hd.source_of("000123.jpg") == "voc" and hd.group_of("000123.jpg") == "non_coco"
    assert hd.source_of("1234567.jpg") == "self" and hd.group_of("12345678.jpg") == "non_coco"


def test_parse_ann_ignores_owner_and_foreign_names(tmp_path):
    x = """<annotation><owner><name>TW</name></owner><size><width>100</width><height>50</height></size>
    <object><name>car</name><difficult>0</difficult><bndbox><xmin>30</xmin><ymin>10</ymin><xmax>70</xmax><ymax>40</ymax></bndbox></object>
    <object><name>hand</name><difficult>0</difficult><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>5</xmax><ymax>5</ymax></bndbox></object>
    </annotation>"""
    p = tmp_path / "a.xml"; p.write_text(x)
    a = hd.parse_ann(str(p))
    assert [g["cls"] for g in a["gt"]] == ["car"] and a["skipped"] == {"hand": 1}
    g = a["gt"][0]
    assert g["box"] == [0.3, 0.2, 0.7, 0.8] and g["in_lane"]          # tâm x=0.5, diện tích 0.24


def test_voc_ap_known_value():
    # 2 GT, detection theo score: TP, FP, TP  -> rec [.5,.5,1] prec [1,.5,.667] -> AP = .5*1 + .5*(2/3)
    rec = np.array([0.5, 0.5, 1.0]); prec = np.array([1.0, 0.5, 2 / 3])
    assert abs(hd.voc_ap(rec, prec) - (0.5 + 0.5 * 2 / 3)) < 1e-9


def test_ap_boot_matches_naive():
    per = {"car": (np.array([.9, .8, .7]), np.array([1., 0., 1.]), np.array([0, 0, 1]))}
    gt = {c: np.zeros(2) for c in hd.MAPPED}; gt["car"] = np.array([1., 1.])
    r = hd.ap_boot(per, 2, gt, B=40)
    assert abs(r["car"]["ap"] - (0.5 + 0.5 * 2 / 3)) < 1e-9


def test_iou():
    a = np.array([[0, 0, 1, 1.]]); b = np.array([[0.5, 0, 1.5, 1.], [2, 2, 3, 3.]])
    m = hd.iou_matrix(a, b)
    assert abs(m[0, 0] - 1 / 3) < 1e-9 and m[0, 1] == 0


def test_camera_geometry():
    cam = hs.Camera()
    box = cam.project(0.0, 5.0, 1.7, 0.5)      # người cao 1,7 m, 5 m
    f = cam.f
    ph = (box[3] - box[1]) * hs.IMG_H
    assert abs(ph - f * 1.7 / 5.0) < 1e-6 and abs((box[0] + box[2]) / 2 - 0.5) < 1e-9
    assert abs(box[3] * hs.IMG_H - (hs.IMG_H / 2 + f * 1.6 / 5.0)) < 1e-6   # đáy chạm đất
    assert cam.project(0, 400.0, 1.7, 0.5) is None                          # quá nhỏ


def test_labels_and_controls():
    assert not hs.generate("far_static_car", 3).positive and not hs.generate("edge_static_car", 3).positive
    for s in range(10):
        assert not hs.generate("cross_person", s).positive and not hs.generate("cross_motorbike", s).positive
        sc = hs.generate("motorbike_charge", s)
        assert sc.positive and sc.Z[sc.t_danger_frame] < hs.DANGER_Z
        assert all(not (z < hs.DANGER_Z and abs(x) < hs.LANE_HALF) for z, x in zip(sc.Z[:sc.t_danger_frame], sc.X))
    assert hl.run_controls(10)["all_pass"]


def test_deterministic():
    a, b = hs.generate("walk_static_person+shake", 7), hs.generate("walk_static_person+shake", 7)
    assert [[d.box for d in f] for f in a.frames] == [[d.box for d in f] for f in b.frames]


# ---- Task 4: kịch bản Việt Nam + tách dev/test --------------------------------------------------------------------

def _hash_boxes(sc) -> str:
    """Cùng cách băm với lúc lưu fixture: sha256 trên các hộp đã làm tròn 12 chữ số."""
    import hashlib
    m = hashlib.sha256()
    for f in sc.frames:
        m.update(b"F")
        for d in f:
            m.update(repr(tuple(round(v, 12) for v in d.box)).encode())
    return m.hexdigest()


def test_legacy_split_bitwise():
    import json, pathlib
    fx = json.loads((pathlib.Path(__file__).parent / "fixtures" / "c1b_legacy_hash.json").read_text())
    assert len(fx) == 24 and len(hs.TYPES) == 24
    for t, _, _ in hs.TYPES:
        for s in (0, 1, 2):
            sc = hs.generate(t, s, "legacy")
            assert _hash_boxes(sc) == fx[t][str(s)], (t, s)
            assert sc.seed == s and sc.group == "legacy" and len(sc.times) == len(sc.ego) == sc.n_frames
    # chữ ký cũ generate(t, s) vẫn là legacy
    assert _hash_boxes(hs.generate("motorbike_charge", 1)) == fx["motorbike_charge"]["1"]


def test_dev_test_disjoint_and_wider():
    dev = hs.generate_all(4, ["walk_static_pole", "sudden_motorbike_alley"], "dev")
    tst = hs.generate_all(4, ["walk_static_pole", "sudden_motorbike_alley"], "test")
    sd, st = {s.seed for s in dev}, {s.seed for s in tst}
    assert sd and st and not (sd & st) and min(sd) >= 1000 and max(sd) < 2000 and min(st) >= 2000
    hd_ = [hs.generate("walk_static_pole", s, "dev").params["person_h"] for s in range(300)]
    ht_ = [hs.generate("walk_static_pole", s, "test").params["person_h"] for s in range(300)]
    assert np.std(ht_) > np.std(hd_)
    # tham số thật được lấy mẫu (khác danh nghĩa), logic vẫn dùng danh nghĩa
    assert len({round(hs.generate("walk_static_pole", s, "dev").params["cam_h"], 6) for s in range(5)}) > 1


def test_split_type_sets():
    new = ["sudden_person_behind_car", "sudden_motorbike_alley", "motorbike_swerve", "motorbike_wrong_way",
           "cross_cut_person", "parked_motorbike_row", "pass_by_person", "same_dir_person", "approach_then_stop"]
    assert all(n in hs.ALL_TYPES for n in new)
    for b in new + ["walk_static_person", "oncoming_person", "motorbike_charge", "far_static_car", "edge_static_person",
                    "cross_person"]:
        assert all(f"{b}+{n}" in hs.ALL_TYPES for n in ("gait", "yaw", "blur")), b
    assert len(hs.generate_all(1, None, "legacy")) == 24
    import pytest
    with pytest.raises(ValueError):
        hs.generate("pass_by_person", 0, "legacy")
    groups = {hs.generate(t, 0, "dev").group for t in new}
    assert groups == {"vn", "sudden", "control"}


def test_sudden_t_visible():
    for split in ("dev", "test"):
        for t in ("sudden_person_behind_car", "sudden_motorbike_alley",
                  "sudden_person_behind_car+blur", "sudden_motorbike_alley+yaw"):
            for s in range(25):
                sc = hs.generate(t, s, split)
                assert sc.group == "sudden" and sc.positive, (t, s, split)
                assert sc.t_visible_frame is not None and sc.t_visible_frame <= sc.t_danger_frame
                assert sc.times[sc.t_danger_frame] - sc.times[sc.t_visible_frame] <= 2.5, (t, s, split)


def test_safe_labels_hold():
    for t in ("parked_motorbike_row", "pass_by_person", "same_dir_person", "approach_then_stop"):
        for s in range(50):
            sc = hs.generate(t, s, "dev")
            assert not sc.positive and sc.t_danger_frame is None, (t, s)
            assert all(not (z < hs.DANGER_Z and abs(x) < hs.LANE_HALF) for z, x in zip(sc.Z, sc.X))
    # đối chứng âm: dừng ở Z = 3 m trong 10 s
    sc = hs.generate("approach_then_stop", 0, "dev")
    assert min(sc.Z) >= 3.0 - 1e-6 and sc.times[-1] - sc.times[[z < 3.0 + 1e-6 for z in sc.Z].index(True)] >= 9.5
    # các loại nguy hiểm đúng nhãn
    for t in ("sudden_person_behind_car", "sudden_motorbike_alley", "motorbike_swerve", "motorbike_wrong_way",
              "cross_cut_person"):
        assert all(hs.generate(t, s, "dev").positive for s in range(30)), t


def test_times_monotonic():
    for split in ("legacy", "dev", "test"):
        for t in ("walk_static_person", "motorbike_charge", "cross_person+shake"):
            sc = hs.generate(t, 3, split)
            assert len(sc.times) == len(sc.ego) == len(sc.frames) == len(sc.Z) == len(sc.X)
            assert all(b > a for a, b in zip(sc.times, sc.times[1:])), (t, split)
    dts = np.diff(hs.generate("same_dir_person", 0, "test").times)
    assert dts.min() >= 0.10 - 1e-9 and dts.std() > 0.01          # test: dt jitter + khung rớt
    assert np.allclose(np.diff(hs.generate("same_dir_person", 0, "dev").times), hs.DT)


def test_ego_and_motion_noise():
    sc = hs.generate("same_dir_person+yaw", 0, "dev")
    sx = np.cumsum([e[0] for e in sc.ego])                          # ego = trượt giữa khung; cộng dồn = lệch tuyệt đối
    assert sx.max() - sx.min() > 0.1                                # quay đầu thật ~ ±8 % bề rộng
    assert abs(np.array([e[0] for e in sc.ego])).max() < 0.06       # mỗi khung chỉ trượt vài % (không phải lệch tuyệt đối)
    plain = np.array([e[0] for e in hs.generate("same_dir_person", 0, "dev").ego])
    assert abs(plain).max() < 0.03 and 0.002 < plain.std() < 0.006  # không yaw: nhiễu đo N(0; 0,4 %)
    sb = hs.generate("same_dir_person+blur", 0, "dev")
    bl = np.array([e[1] for e in sb.ego])
    assert (bl < 30).any() and (bl >= 80).any()
    assert all(not f for f, e in zip(sb.frames, sb.ego) if e[1] < 30)   # khung nhoè mất hộp


# ---- Task 5: chấm điểm sudden, luật chọn, Pareto, baseline bỏ qua t/ego, báo cáo ----------------------------------
def _fake(td, tv, beeps, group="sudden"):
    n = 30
    return {"type": "x", "seed": 0, "positive": td is not None, "t_danger_frame": td, "n_frames": n, "minutes": 0.1,
            "levels": "0" * n, "beeps": beeps, "group": group, "t_visible_frame": tv}


def test_sudden_timely_definition():
    assert hl.score(_fake(14, 10, [(11, 3)]))["timely"] == 1
    assert hl.score(_fake(14, 10, [(13, 3)]))["timely"] == 0
    s = hl.score(_fake(10, 10, [(9, 3)]))
    assert s["impossible"] == 1 and hl.score(_fake(14, 10, [(11, 3)]))["impossible"] == 0
    s = hl.score(_fake(14, 10, [(11, 3)]))
    assert abs(s["max_lead_s"] - 4 * hs.DT) < 1e-9 and abs(s["reveal_delay_s"] - hs.DT) < 1e-9
    # loại impossible ra khỏi mẫu số của summarize
    recs = [_fake(14, 10, [(11, 3)]), _fake(10, 10, [])]
    assert hl.summarize(recs)["overall"]["n_positive"] == 1 and hl.summarize(recs)["overall"]["n_impossible"] == 1


def _st(timely, fa, sb=0.1, p90=100.0, delay=100.0, by=None):
    return {"timely": timely, "fa_per_min": fa, "safe_beep_pct": sb, "p90_us": p90, "algo_delay_ms": delay,
            "timely_by_type": by or {"a": timely}, "safe_beep_by_type": {"s": sb}}


def test_selection_rule():
    from bench import hazard_grid as hg
    base = _st(0.5, 0.5)
    a = {"config": "a", "stats": _st(0.9, 0.6)}              # kịp thời cao nhưng báo oan > baseline
    b = {"config": "b", "stats": _st(0.6, 0.4)}
    c = {"config": "c", "stats": _st(0.605, 0.3)}            # hoà trong 1 điểm, báo oan thấp hơn
    assert hg.select([a, b, c], base)[0]["config"] == "c"
    assert hg.select([a], base)[0] is None
    slow = {"config": "s", "stats": _st(0.9, 0.1, p90=2000.0)}
    worse = {"config": "w", "stats": _st(0.9, 0.1, by={"a": 0.4})}   # loại nguy hiểm giảm > 5 điểm
    assert hg.select([slow, worse], base)[0] is None
    g = hg.make_grid()
    assert len(g) == 648 and {c['release_s'] for c in g} == {0.25, 0.5} and {c['yaw_tau_s'] for c in g} == {0.0, 3.0}
    assert {c['v_conf_k'] for c in g} == {0.0, 0.5, 1.0}


def test_pareto_nondominated():
    from bench import hazard_grid as hg
    rng = np.random.default_rng(0)
    pts = [{"fa_per_min": float(a), "safe_beep_pct": float(b), "timely": float(c)} for a, b, c in rng.random((60, 3))]
    front = hg.pareto(pts)
    assert front and len(front) < len(pts)
    for p in front:
        for q in pts:
            assert not (q["fa_per_min"] <= p["fa_per_min"] and q["safe_beep_pct"] <= p["safe_beep_pct"]
                        and q["timely"] >= p["timely"] and q is not p
                        and (q["fa_per_min"] < p["fa_per_min"] or q["safe_beep_pct"] < p["safe_beep_pct"] or q["timely"] > p["timely"]))


def test_baseline_pipeline_ignores_extra():
    scn = hs.generate("motorbike_charge", 1, "dev")
    a = hl.simulate(scn)                                      # simulate đã truyền t/ego
    p = hl.BaselinePipeline()
    lv = "".join(str(p.frame(k, d)[0].level) for k, d in enumerate(scn.frames))
    assert a["levels"] == lv


def test_report_khong_dat_and_null():
    from bench import hazard_grid as hg
    base = _st(0.5, 0.5)
    pt = [{"fa_per_min": 0.5, "safe_beep_pct": 0.1, "timely": 0.5, "config": None, "baseline": True}]
    dev = {"configs": [], "baseline": base, "pareto": pt, "selected": None, "n_scenarios": 3}
    md = hg.render_report(dev, None)
    assert md.startswith("**KHÔNG CHỌN ĐƯỢC**") and "selected = null" in md
    test = {"violations": ["loại an toàn pass_by_person: % bíp 20 > baseline 5 + 5 điểm"], "per_type": {}, "false_alarms": [],
            "miss_causes": {}, "controls": {}, "latency": None,
            "summary_base": {"overall": {"false_alarms_per_min": {"value": 0.5}}, "by_group": {}},
            "summary_sel": {"overall": {"false_alarms_per_min": {"value": 0.6}}, "by_group": {}}}
    dev["selected"] = {"config": {"coast": 2}, "stats": _st(0.6, 0.6)}
    assert hg.render_report(dev, test).splitlines()[0].startswith("**KHÔNG ĐẠT**")


def test_nfs_probe_and_safe_write(tmp_path):
    from bench import hazard_grid as hg
    hg.nfs_probe(str(tmp_path))
    assert not list(tmp_path.glob(".probe_*"))
    p = hg.write_json(str(tmp_path / "x.json"), {"a": "é" * 70000})
    assert (tmp_path / "x.json").stat().st_size > 64 * 1024 and p


def _ctl(levels, beeps, n=40):
    return {"levels": levels.ljust(n, "0"), "beeps": beeps, "times": [k * 0.125 for k in range(n)]}


def test_control_approach_then_stop():
    # dừng ở khung 16 (t=2,0 s), settle tới t=3,0 s = khung 24. Bíp mức 3 ở khung 10 (trước dừng) là đúng.
    ok = hl.check_approach_stop(_ctl("0" * 10 + "3" * 6, [(10, 3)]), 16)
    assert ok["pass"] and ok["level3_before"] == 1 and ok["level3_after"] == 0
    bad = hl.check_approach_stop(_ctl("0" * 10 + "3" * 20, [(10, 3), (26, 3)]), 16)
    assert not bad["pass"] and bad["level3_after"] == 1 and bad["frames_level3_after"] > 0
    # chỉ mức khung còn 3 sau settle (chưa bíp) cũng fail
    assert not hl.check_approach_stop(_ctl("3" * 30, []), 16)["pass"]


def test_control_reverse_time():
    # chỉ đếm bíp mức >= 2 SAU khung k_ok (khung đầu có Z thật > 3 m)
    assert hl.check_reverse(_ctl("0", [(2, 3), (7, 2)]), 8)["pass"]          # bíp trước k_ok: bỏ qua
    bad = hl.check_reverse(_ctl("0", [(2, 3), (12, 2)]), 8)
    assert not bad["pass"] and bad["beeps_ge2_after_skip"] == 1
    assert hl.check_reverse(_ctl("0", [(20, 1)]), 8)["pass"]                 # mức 1 không tính
    assert hl.check_reverse(_ctl("0", [(8, 3)]), 8)["pass"]                  # đúng khung k_ok chưa tính (SAU khung)
    assert hl.reverse_ok_frame([1.0, 2.5, 3.0, 3.2, 5.0]) == 3 and hl.reverse_ok_frame([1.0, 2.0]) == 2
    scn = hs.generate("motorbike_charge", 1, "dev")
    r = hl.reverse_scenario(scn)
    assert all(b > a for a, b in zip(r.times, r.times[1:])) and r.n_frames == scn.n_frames and not r.positive
    assert r.ego[0][0] == -scn.ego[0][0] and r.ego[1][0] == -scn.ego[-1][0] and r.ego[-1][1] == scn.ego[0][1]
    assert r.Z[0] == scn.Z[-1] and hl.reverse_ok_frame(r.Z) < r.n_frames
    y = hs.generate("motorbike_charge+yaw", 1, "dev")                       # tổng trượt đảo = lệch tuyệt đối chạy ngược
    ry = hl.reverse_scenario(y)
    s_fwd, s_rev = np.cumsum([e[0] for e in y.ego]), np.cumsum([e[0] for e in ry.ego])
    assert abs((s_rev[-1] - s_rev[0]) + (s_fwd[-1] - s_fwd[0])) < 0.05


def test_control_group_excluded_from_false_alarms():
    from bench import hazard_grid as hg
    safe = dict(_fake(None, None, [(3, 3)], group="vn"), type="s", minutes=1.0)
    ctrl = dict(_fake(None, None, [(3, 3)] * 5, group="control"), type="approach_then_stop", minutes=1.0)
    st = hg.config_stats([dict(safe, _us=[1.0]), dict(ctrl, _us=[1.0])])
    assert st["fa_per_min"] == 1.0 and "approach_then_stop" not in st["safe_beep_by_type"] and st["safe_beep_pct"] == 1.0


def test_pole_kind_by_split():
    for split in ("dev", "test"):
        kinds = {d.kind for s in range(4) for f in hs.generate("walk_static_pole", s, split).frames for d in f}
        assert kinds == {"pole"}, split
        assert {d.group for s in range(4) for f in hs.generate("walk_static_pole", s, split).frames for d in f} == {"static"}
    kl = {d.kind for f in hs.generate("walk_static_pole", 0, "legacy").frames for d in f}
    assert kl == {"parking_meter"}


def test_sidestep_t_clear():
    for split in ("dev", "test"):
        for t in ("sidestep_avoid", "sidestep_avoid+gait", "sidestep_avoid+yaw"):
            for s in range(30):
                sc = hs.generate(t, s, split)
                assert sc.group == "release" and not sc.positive and sc.t_danger_frame is None, (t, s)
                k = sc.t_clear_frame
                assert k is not None and abs(sc.X[k]) > hs.LANE_HALF + 0.2
                assert all(abs(x) <= hs.LANE_HALF + 0.2 for x in sc.X[:k])
                assert 3.0 < sc.Z[k] < 5.5 + 1e-9 and sc.Z[0] <= 14.0 + 1e-9
    assert "sidestep_avoid" in hs.ALL_TYPES and "sidestep_avoid+gait" in hs.ALL_TYPES and "sidestep_avoid+yaw" in hs.ALL_TYPES
    # loại khác: t_clear là khung đã đi qua, hoặc None
    sc = hs.generate("cross_person", 0, "dev")
    assert sc.t_clear_frame is not None and abs(sc.X[sc.t_clear_frame]) > hs.LANE_HALF + 0.2
    assert hs.generate("walk_static_person", 0, "dev").t_clear_frame is None
    assert hs.t_clear([5, 4, 3], [0.0, 0.7, 0.9]) == 2 and hs.t_clear([5, 4], [2.0, 1.5]) is None


def test_tail_metric_fake_records():
    def rec(tc, beeps):
        n = 40
        return {"type": "x", "seed": 0, "positive": False, "t_danger_frame": None, "n_frames": n, "minutes": 0.1,
                "levels": "0" * n, "beeps": beeps, "group": "release", "t_visible_frame": None, "t_clear_frame": tc}
    assert abs(hl.score(rec(10, [(8, 3), (14, 2)]))["tail_after_clear_s"] - 4 * hs.DT) < 1e-9
    assert hl.score(rec(10, [(8, 3)]))["tail_after_clear_s"] == 0.0           # bíp cuối trước t_clear
    assert "tail_after_clear_s" not in hl.score(rec(10, []))                  # không bíp: không tính
    assert "tail_after_clear_s" not in hl.score(rec(None, [(8, 3)]))          # không có t_clear: không tính
    recs = [rec(10, [(10 + k, 2)]) for k in (0, 4, 8, 12, 16)]                # đuôi 0; 0,5; 1,0; 1,5; 2,0 s
    tb = hl.tail_block([hl.score(r) for r in recs])
    assert abs(tb["p50"] - 1.0) < 1e-9 and abs(tb["pct_over_1s"] - 0.4) < 1e-9 and tb["n"] == 5
    st = __import__("bench.hazard_grid", fromlist=["x"]).config_stats([dict(r, _us=[1.0]) for r in recs])
    assert st["fa_per_min"] == 0.0 and st["tail_p90_s"] > 1.0                 # release không vào báo oan
    from bench import hazard_grid as hg
    good, bad = {"config": "g", "stats": _st(0.9, 0.1)}, {"config": "b", "stats": dict(_st(0.95, 0.1), tail_p90_s=1.4)}
    assert hg.select([good, bad], _st(0.5, 0.5))[0]["config"] == "g"


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
