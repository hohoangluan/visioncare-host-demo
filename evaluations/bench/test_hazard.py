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


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
