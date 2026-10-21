"""HAZARD_LOGIC=predict: hình học ước lượng khoảng cách, track Kalman, xếp mức theo TTE."""

import importlib
import json
import math
import os

import numpy as np
import pytest

import config
from live import hazard
from live.hazard import Detection
from live import hazard_geom
from live.hazard_geom import Camera, CLASS_HEIGHT_M

CLASSES_VH = "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/evaluations/train/classes_vh.json"

CAM = Camera(320, 240, 66.0, 1.6)


def _proj(X, Z, H, W, cam=CAM, pitch=0.0, base=0.0):
    """Chiếu pin-hole giống `bench/hazard_scenarios.Camera.project` (hộp tỉ lệ, đã cắt biên).

    `base` = độ cao đáy vật so với mặt đất; `pitch` đúng quy ước của `hazard_geom` (dương = cảnh trượt lên).
    """
    f = cam.f_px
    x0 = cam.w / 2 + f * (X - W / 2) / Z
    x1 = cam.w / 2 + f * (X + W / 2) / Z
    y_bot = cam.h / 2 + f * ((cam.height_m - base) / Z - math.tan(pitch))
    y_top = cam.h / 2 + f * ((cam.height_m - base - H) / Z - math.tan(pitch))
    c = lambda v, hi: min(max(v, 0.0), hi)
    return (c(x0, cam.w) / cam.w, c(y_top, cam.h) / cam.h, c(x1, cam.w) / cam.w, c(y_bot, cam.h) / cam.h)


def _person(X, Z, pitch=0.0):
    return Detection("person", "person", 0.9, _proj(X, Z, 1.65, 0.5, pitch=pitch))


# ---- Task 1: hình học ----

# Z = 3 m không dùng được: cam cao 1,6 m, VFOV ~52° thì chân người ở Z < 3,3 m đã chạm mép dưới (xem test sau).
@pytest.mark.parametrize("Z", [4.0, 6.0, 10.0])
def test_estimate_height_source_recovers_distance(Z):
    e = hazard_geom.estimate(_person(0.3, Z), CAM)
    assert abs(e.z_m - Z) / Z < 0.05
    assert abs(e.x_m - 0.3) < 0.1


def test_estimate_bottom_clipped_is_near():
    e = hazard_geom.estimate(_person(0.0, 1.0), CAM)
    assert e.source == "clipped" and math.isnan(e.z_m) and e.z_width < 1.5  # Z cần track; z_width = Z theo bề rộng bảng
    assert e.source != "height"


def test_estimate_bottom_clipped_width_z_reasonable():
    for Z in (1.0, 2.0, 3.0):  # chân bị cắt: Z theo bề rộng bảng (người 0,5 m) phải sát Z thật
        e = hazard_geom.estimate(_person(0.0, Z), CAM)
        assert e.source == "clipped" and abs(e.z_width - Z) < 0.2


def test_clipped_bottom_and_side_new_track_not_far():
    det = Detection("person", "person", 0.9, _proj(1.3, 2.0, 1.7, 0.5))
    est = hazard_geom.estimate(det, CAM)
    assert est.source == "clipped"
    assert det.box[2] == 1.0 and det.box[3] == 1.0

    tracks = hazard_track.TrackSet(coast=3, q=1.0).update([det], [est], 0.0)
    z_lim = CAM.height_m * CAM.f_px / (CAM.h - CAM.h / 2)
    assert len(tracks) == 1
    assert 1.0 <= tracks[0].x[1] <= z_lim * 1.15


def test_clipped_width_ratio_capped():
    ts = hazard_track.TrackSet(coast=3, q=1.0)
    det, est = _obs(0.0, 6.0)
    tr, = ts.update([det], [est], 0.0)
    clipped = Detection("person", "person", 0.9, (0.49, 0.49, 0.51, 1.0))
    est = hazard_geom.estimate(clipped, CAM)
    assert est.source == "clipped"

    for k in range(1, 5):
        tracks = ts.update([clipped], [est], k * DT)
    assert len(tracks) == 1
    assert tracks[0].x[1] <= est.z_max


def test_estimate_unknown_kind_finite():
    det = Detection("xyz", "static", 0.5, _proj(0.0, 4.0, 1.0, 0.5))
    e = hazard_geom.estimate(det, CAM)
    assert math.isfinite(e.z_m) and abs(e.z_m - 4) < 1.0
    assert math.isfinite(e.z_sigma) and e.z_sigma > 0


def test_estimate_pitch_shifts_ground_only():
    ground = Detection("xyz", "static", 0.5, _proj(0.0, 4.0, 1.0, 0.5))  # lớp lạ: chỉ có nguồn ground
    a, b = hazard_geom.estimate(ground, CAM, 0.0), hazard_geom.estimate(ground, CAM, 0.03)
    assert a.source == b.source == "ground" and abs(a.z_m - b.z_m) > 0.05
    sign = Detection("person", "person", 0.9, _proj(0.0, 8.0, 1.65, 0.5, base=1.8))  # đáy trên đường chân trời (lớp có chiều cao)
    a, b = hazard_geom.estimate(sign, CAM, 0.0), hazard_geom.estimate(sign, CAM, 0.03)
    assert a.source == b.source == "height" and a.z_m == b.z_m


def test_classes_json_overrides_coco(monkeypatch):
    if not os.path.exists(CLASSES_VH):
        pytest.skip("không có classes_vh.json")
    try:
        monkeypatch.setattr(config, "HAZARD_CLASSES_JSON", CLASSES_VH)
        importlib.reload(hazard)
        assert hazard._CLASSES[11] == ("pole", "static")
        monkeypatch.setattr(config, "HAZARD_CLASSES_JSON", "")
        importlib.reload(hazard)
        assert hazard._CLASSES[0] == ("person", "person")
    finally:
        monkeypatch.undo()
        importlib.reload(hazard)


def test_class_table_covers_all_kinds():
    kinds = {k for k, _ in hazard._CLASSES.values()}
    if os.path.exists(CLASSES_VH):
        kinds |= {v[0] for v in json.load(open(CLASSES_VH)).values()}
    assert not kinds - set(CLASS_HEIGHT_M)
    assert set(hazard_geom.CLASS_HEIGHT_REL_SIGMA) <= set(CLASS_HEIGHT_M)


# ---- Task 2: track + Kalman ----

from live import hazard_track
from live.hazard_geom import Estimate

DT = 0.125


def _obs(X, Z):
    det = _person(X, Z)
    return det, hazard_geom.estimate(det, CAM)


def _step(ts, t, objs, **kw):
    pairs = [_obs(X, Z) for X, Z in objs]
    return ts.update([d for d, _ in pairs], [e for _, e in pairs], t, **kw)


def test_track_velocity_converges():
    ts = hazard_track.TrackSet(coast=3, q=1.0)
    for k in range(16):
        tracks = _step(ts, k * DT, [(0.0, 12.0 - 1.2 * k * DT)])
    assert len(tracks) == 1 and abs(tracks[0].x[3] + 1.2) < 0.3


def test_track_dt_nonpositive_safe():
    ts = hazard_track.TrackSet(coast=3, q=1.0)
    for t in (1.0, 1.0, 0.5, None, 0.5, 100.0):  # trùng, lùi, None, nhảy xa
        tracks = _step(ts, t, [(0.0, 8.0)])
        for tr in tracks:
            assert np.isfinite(tr.x).all() and np.isfinite(tr.P).all()
    assert len(tracks) == 1


def test_track_coast_then_drop():
    ts = hazard_track.TrackSet(coast=3, q=1.0)
    for k in range(5):
        tracks = _step(ts, k * DT, [(0.0, 12.0 - 2.0 * k * DT)])
    old_id = tracks[0].id
    assert abs(tracks[0].x[3]) > 0.5  # đã học được vận tốc
    for k in range(5, 9):
        tracks = _step(ts, k * DT, [])
        assert len(tracks) == (1 if k < 8 else 0)  # coast 3 khung rồi xoá ở khung mất thứ 4
    tracks = _step(ts, 9 * DT, [(0.0, 10.0)])
    assert len(tracks) == 1 and tracks[0].id != old_id
    assert abs(tracks[0].x[3]) < 1e-6 and tracks[0].hits == 1


def test_track_two_objects_keep_ids():
    ts = hazard_track.TrackSet(coast=3, q=1.0)
    ids = None
    for k in range(10):
        tracks = _step(ts, k * DT, [(-1.0, 12.0 - 1.2 * k * DT), (1.0, 12.0 - 1.2 * k * DT)])
        cur = {round(tr.x[0]): tr.id for tr in tracks}
        assert len(tracks) == 2
        ids = ids or cur
        assert cur == ids


def test_ego_shift_removed():
    def run(shift):
        ts = hazard_track.TrackSet(coast=3, q=1.0)
        det = Detection("person", "person", 0.9, (0.4, 0.2, 0.6, 0.8))
        for k in range(20):
            tr, = ts.update([det], [Estimate(5.0, 5 * 0.04 * k, 0.3, "height")], k * DT, ego_shift_rad=shift)
        return tr
    assert abs(run(0.04).x[2]) < 0.3
    assert abs(run(0.0).x[2]) > 1.0  # đối chứng âm: không bù thì vật đứng yên bị đọc thành đang trượt ngang


# ---- Task 3: xếp mức theo TTE, AntiAnnoy phiếu/hysteresis, ego ----

import time

import cv2

from lanes import nav_live
from live import ego_motion, hazard_predict


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _tracker(**kw):
    return hazard_predict.PredictTracker(hazard_predict.PredictParams(**kw), CAM)


def test_area_default_unchanged(monkeypatch):
    monkeypatch.setattr(config, "HAZARD_LOGIC", "area")
    assert type(hazard.make_tracker()) is hazard.HazardTracker
    assert hazard.make_anti().l3_vote == 1
    levels = [0, 1, 1, 2, 2, 2, 3, 2, 2, 0, 0, 3, 3, 1, 1, 2, 2, 0, 0, 1, 1]
    c_old, c_new = _Clock(), _Clock()
    old, new = hazard.AntiAnnoy(c_old), hazard.make_anti(c_new)
    got_old, got_new = [], []
    for lvl in levels:
        c_old.t = c_new.t = c_old.t + 0.9
        got_old.append(old.step(lvl))
        got_new.append(new.step(lvl))
    assert got_old == got_new and any(got_old)
    monkeypatch.setattr(config, "HAZARD_LOGIC", "predict")
    assert isinstance(hazard.make_tracker(), hazard_predict.PredictTracker) and hazard.make_anti().l3_vote == 2


def _walk(tracker, objs, closing, n=80, stop_z=1.5):
    """Người dùng đi `closing` m/s: Z mỗi vật giảm closing·t. objs = [(X0, Z0, vX)] -> [(Z thật, X thật, Hazard)]."""
    out = []
    for k in range(n):
        t = k * DT
        pos = [(x0 + vx * t, z0 - closing * t) for x0, z0, vx in objs]
        if min(z for _, z in pos) < stop_z:
            break
        out.append((pos, tracker.assess([_person(x, z) for x, z in pos], t)))
    return out


def test_predict_static_person_timely():
    run = _walk(_tracker(), [(0.0, 12.0, 0.0)], 1.2)
    first = next(pos[0][1] for pos, h in run if h.level >= 2)
    assert first >= 2 + 1.5 * 1.2  # bíp mức >= 2 sớm >= 1,5 s trước khi vào Z < 2


def test_predict_pass_by_no_level2():
    run = _walk(_tracker(), [(1.0, 14.0, 0.0)], 2.4, stop_z=1.6)
    assert len(run) > 30 and all(h.level < 2 for _, h in run)


def test_predict_crossing_dir_left():
    # người dùng đi 1,2 m/s, người kia đi ngang từ X = -3 sang phải 1,0 m/s: sẽ vào hành lang (X > -0,6) lúc Z ~ 3
    run = _walk(_tracker(), [(-3.0, 6.0, 1.0)], 1.2, stop_z=2.0)
    hits = [(pos[0], h) for pos, h in run if h.level >= 2]
    assert hits and hits[0][1].dir == "left" and hits[0][0][0] < -0.6  # báo khi còn ngoài hành lang, phía trái


def test_predict_new_near_urgent():
    h = _tracker().assess([_person(0.0, 2.5)], 0.0)
    assert h.level == 3 and h.urgent


def test_anti_l3_vote():
    a = hazard.AntiAnnoy(l3_vote=2)
    assert [a.step(3), a.step(0), a.step(0)] == [False, False, False]
    b = hazard.AntiAnnoy(l3_vote=2)
    assert [b.step(3), b.step(3)] == [False, True]
    c = hazard.AntiAnnoy(l3_vote=2)
    assert c.step(3, urgent=True) is True
    d = hazard.AntiAnnoy(l3_vote=2, bypass_vote=False)
    assert d.step(3, urgent=True) is False


def test_anti_down_hold():
    anti = hazard.AntiAnnoy(l3_vote=1, down_hold=2)
    assert anti.step(3) is True and anti.current == 3
    assert anti.step(2) is False and anti.current == 3  # 1 khung thấp hơn chưa hạ
    assert anti.step(3) is False and anti.current == 3  # trở lại 3: không gửi lại
    assert anti.step(2) is False and anti.step(2) is False and anti.current == 2  # giữ 2 khung -> hạ
    held = hazard.AntiAnnoy(down_hold=3)
    held.step(3); held.step(2); held.step(2)
    assert held.current == 3
    held.step(2)
    assert held.current == 2


def test_predict_crowded_frame_fast():
    tracker = _tracker()
    rng = np.random.default_rng(0)
    objs = [(float(rng.choice([-1, 1]) * rng.uniform(0.9, 1.5)), 10.0 + 1.0 * i) for i in range(20)]  # dãy xe đỗ 2 bên
    times, levels = [], []
    for k in range(200):  # người dùng đi 0,25 m/s dọc dãy xe: Z giảm dần, không xe nào vào |X| < 0,6
        dets = [Detection("motorbike", "vehicle", 0.9, _proj(x, z - 0.25 * k * DT, 1.2, 0.6)) for x, z in objs]
        t0 = time.perf_counter()
        h = tracker.assess(dets, k * DT)
        times.append(time.perf_counter() - t0)
        levels.append(h.level)
    # 2 ms vì máy dùng chung; ngân sách thật 1 ms do phép đo C1c + luật chọn của bench giữ
    assert float(np.percentile(times, 90)) < 2e-3
    assert max(levels) < 2


def test_ego_meter_shift_sign():
    rng = np.random.default_rng(1)
    img = cv2.GaussianBlur(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8), (3, 3), 0)
    meter = ego_motion.EgoMeter()
    first = meter.measure(img)
    assert first.shift_x == 0.0
    ego = meter.measure(np.roll(img, 16, axis=1))
    assert abs(ego.shift_x - 0.05) < 0.01
    assert ego.blur > ego_motion.EgoMeter().measure(cv2.GaussianBlur(img, (0, 0), 15)).blur


def test_process_frame_passes_time():
    seen = []

    class Det:
        def detect(self, bgr):
            return []

    class Tracker:
        def assess(self, dets, t=None, ego=None):
            seen.append((t, ego))
            return hazard.Hazard(0)

    ok, jpg = cv2.imencode(".jpg", np.zeros((240, 320, 3), np.uint8))
    nav_live.process_frame(Det(), Tracker(), jpg.tobytes(), 12.5)
    nav_live.process_frame(Det(), Tracker(), jpg.tobytes(), 13.0, ego_motion.EgoMeter())
    assert seen[0] == (12.5, None) and seen[1][0] == 13.0 and isinstance(seen[1][1], ego_motion.Ego)


def test_predict_no_ghost_after_vanish_and_bad_clock():
    tr = _tracker()
    for k in range(10):
        tr.assess([_person(0.0, 9.0 - 1.2 * k * DT)], k * DT)
    levels = [tr.assess([], (10 + k) * DT).level for k in range(6)]
    assert levels[-1] == 0  # sau coast khung không còn track ma
    h = tr.assess([_person(0.0, 8.0)], 20 * DT)
    assert h.level < 3 and not h.urgent
    for t in (20 * DT, 5.0, None, -1.0):  # mốc trùng/lùi/None: không NaN, không lỗi
        h = tr.assess([_person(0.0, 7.0)], t)
        assert 0 <= h.level <= 3


def test_pitch_estimate_converges():
    tr = _tracker()
    for k in range(40):  # người đi tới 12 -> 4,2 m, ảnh lệch góc cúi 0,03 rad
        tr.assess([_person(0.3, 12.0 - 0.2 * k, pitch=0.03)], k * DT)
    assert abs(tr.pitch_rad - 0.03) < 0.01


# ---- Fix round 1: đáy hộp bị cắt -> Z theo tỉ lệ bề rộng ----

def _pole(Z, X=0.0):
    return Detection("pole", "static", 0.9, _proj(X, Z, 3.0, 0.15))


def _approach_then_stop(z_stop, n_stop):
    tr = _tracker()
    zs = [8.0 - 1.2 * DT * k for k in range(int((8.0 - z_stop) / (1.2 * DT)) + 1)]
    out = []
    for k, z in enumerate(zs):
        out.append((z, tr.assess([_pole(z)], k * DT).level))
    k0 = len(zs)
    for k in range(n_stop):
        out.append((zs[-1], tr.assess([_pole(zs[-1])], (k0 + k) * DT).level))
    return tr, zs, out


def test_clipped_bottom_static_object_keeps_true_distance():
    tr, zs, out = _approach_then_stop(3.0, 40)
    assert abs(tr.tracks._tracks[0].x[1] - zs[-1]) < 0.4
    after = out[len(zs):]
    assert min(l for _, l in after[:8]) < 3


def test_clipped_bottom_approach_still_warns():
    tr, zs, out = _approach_then_stop(1.0, 0)
    first3 = next(z for z, l in out if l == 3)
    assert first3 >= 2.0


def test_new_track_clipped_uses_width_table():
    tr = _tracker()
    tr.assess([_person(0.0, 2.0)], 0.0)
    z = tr.tracks._tracks[0].x[1]
    assert math.isfinite(z) and abs(z - 2.0) < 0.8


# ---- Fix round 1: đuôi nhả ----

class _Clk:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def _run_anti(anti, clk, levels):
    sent = []
    for lv in levels:
        sent.append((clk.t, anti.step(lv)))
        clk.t += 0.125
    return sent


def test_release_tail_stops_after_tail():
    clk = _Clk()
    anti = hazard.AntiAnnoy(clk, down_hold=2, release_s=0.5)
    sent = _run_anti(anti, clk, [3, 3] + [0] * 60)
    assert sent[0][1] is True
    t_clear = 2 * 0.125 + 0.125  # khung 0 thứ 2 (down_hold = 2)
    assert not any(ok for t, ok in sent[2:] if t > t_clear + 0.5 + 0.125)
    assert anti.current == 0
    assert anti.step(3) is True  # nguy hiểm lại: gửi ngay như mức tăng mới


def test_release_cancelled_when_danger_returns():
    clk = _Clk()
    anti = hazard.AntiAnnoy(clk, down_hold=2, release_s=0.5)
    sent = _run_anti(anti, clk, [3, 3, 0, 0, 0, 3, 3, 3, 3])
    assert anti.current == 3 and not any(ok for _, ok in sent[5:])  # không bíp thừa
    sent = _run_anti(anti, clk, [0] * 6)
    assert anti.current == 0


def test_release_zero_is_old_behaviour():
    seq = [0, 1, 1, 2, 2, 3, 3, 2, 0, 0, 3, 0, 2, 2, 2, 2, 1, 1, 0, 0, 3, 3, 3]
    a, b = _Clk(), _Clk()
    old, new = hazard.AntiAnnoy(a), hazard.AntiAnnoy(b, release_s=0.0)
    assert [x for _, x in _run_anti(old, a, seq)] == [x for _, x in _run_anti(new, b, seq)]


@pytest.mark.parametrize("Z", [4.0, 6.0, 10.0])
def test_pole_distance_ignores_height_prior(Z):
    e = hazard_geom.estimate(_pole(Z), CAM)
    assert e.source == "ground" and abs(e.z_m - Z) / Z < 0.15


# ---- Fix round 3: hộp chạm mép bên ----

def _walk_by(X_of, Z_of, n, H=1.7, W=0.5):
    tr = _tracker()
    out = []
    for k in range(n):
        X, Z = X_of(k), Z_of(k)
        det = Detection("person", "person", 0.9, _proj(X, Z, H, W))
        h = tr.assess([det], k * DT)
        t = tr.tracks._tracks[0] if tr.tracks._tracks else None
        out.append((X, Z, h.level, None if t is None else t.x.copy()))
    return out


def test_lateral_clip_no_fake_inward_velocity():
    n = int((8.0 - 0.8) / (1.2 * DT)) + 1
    out = _walk_by(lambda k: 1.2, lambda k: 8.0 - 1.2 * DT * k, n)
    assert any(o[1] < 1.6 and _proj(1.2, o[1], 1.7, 0.5)[2] >= 0.99 for o in out)  # có khung bị cắt bên phải
    assert all(abs(o[3][2]) < 0.25 for o in out if o[3] is not None)
    assert all(o[2] < 2 for o in out)


def test_lateral_clip_real_entry_still_warns():
    n = 17  # người đi vào hành lang 1 m/s ngang, đồng thời tiến 1 m/s
    xs = lambda k: max(1.5 - 1.0 * DT * k, 0.0)
    zs = lambda k: 4.0 - 1.0 * DT * k
    out = _walk_by(xs, zs, n)
    first = next(i for i, o in enumerate(out) if o[2] >= 2)
    assert abs(out[first][0]) >= 0.6


# ---- Fix cuối: cổng nhoè tương đối, góc cúi trung vị, reset, NaN, HAZARD_LOGIC lạ ----

def test_low_texture_scene_still_creates_tracks():
    tr = _tracker()  # cảnh ít chi tiết: blur cố định 10 (dưới ngưỡng tuyệt đối cũ 30) vẫn phải có track
    ego = ego_motion.Ego(0.0, 10.0)
    lvls = {}
    for k in range(40):
        z = 8.0 - 0.15 * k
        if z < 2.5:
            break
        lvls[round(z, 2)] = tr.assess([_person(0.0, z)], k * DT, ego).level
    assert tr.tracks._tracks
    assert max(v for z, v in lvls.items() if z >= 3.8) >= 2


def test_blur_burst_blocks_at_most_two_frames():
    tr = _tracker()
    sharp, blur = ego_motion.Ego(0.0, 100.0), ego_motion.Ego(0.0, 5.0)
    for k in range(10):
        tr.assess([], k * DT, sharp)
    seen = []
    for k in range(10, 16):
        tr.assess([_person(0.0, 6.0)], k * DT, blur)
        seen.append(bool(tr.tracks._tracks))
    assert seen[:2] == [False, False] and seen[2] is True


def test_pitch_children_do_not_push_far():
    tr = _tracker()
    for k in range(60):
        z = 12.0 - 0.1 * k
        kid = Detection("person", "person", 0.9, _proj(-1.0, z, 1.15, 0.4))
        tr.assess([_person(0.8, z), kid] if k % 2 == 0 else [kid, kid, _person(0.8, z)], k * DT)
    assert tr.pitch_rad >= -0.02
    e = hazard_geom.estimate(_person(0.0, 4.0), CAM, tr.pitch_rad)
    assert e.z_m <= 4.0 * 1.05


def test_long_gap_resets_tracks():
    tr = _tracker()
    for k in range(5):
        tr.assess([_person(0.0, 6.0)], k * DT)
    assert tr.tracks._tracks
    tr.assess([], 5.0)
    assert not tr.tracks._tracks


def test_nan_box_ignored():
    tr = _tracker()
    bad = Detection("person", "person", 0.9, (float("nan"), 0.2, 0.6, 0.8))
    h = tr.assess([bad, _person(0.0, 6.0), Detection("person", "person", 0.9, (0.1, float("inf"), 0.3, 0.9))], 0.0)
    assert len(h.levels) == 3 and h.levels[0] == 0 and h.levels[2] == 0
    assert len(tr.tracks._tracks) == 1
    assert np.isfinite(tr.tracks._tracks[0].x).all()


def test_unknown_hazard_logic_warns_once_and_runs_area(monkeypatch, caplog):
    monkeypatch.setattr(config, "HAZARD_LOGIC", "bogus")
    monkeypatch.setattr(hazard, "_warned_logic", False)
    with caplog.at_level("WARNING", logger="blind_assist"):
        a, b = hazard.make_tracker(), hazard.make_tracker()
        hazard.make_anti()
    assert isinstance(a, hazard.HazardTracker) and isinstance(b, hazard.HazardTracker)
    assert sum("HAZARD_LOGIC" in r.message for r in caplog.records) == 1


def test_confident_velocity_shrinks_by_sigma():
    from live.hazard_predict import _confident
    assert _confident(-2.0, 0.25, 2.0) == pytest.approx(-1.0)        # |v| − 2·0,5
    assert _confident(0.3, 0.25, 2.0) == 0.0                         # chưa chắc: co về 0, không đổi dấu
    assert _confident(1.5, 0.0, 2.0) == 1.5 and _confident(-0.4, 9.0, 0.0) == -0.4


def test_v_conf_new_track_waits_but_fast_approach_still_warns():
    from live import hazard_predict
    # track mới (σ_v = 3 m/s): vận tốc đo nhiễu ở 2 khung đầu không được đẩy mức 2. σ_v của Kalman dừng ở ~0,6–0,9 m/s
    # (do q, không do sai số thật) nên K lớn làm muộn mọi ca tiến lại chậm: K = 2 báo người đứng yên ở 1,95 m
    tr = _tracker(v_conf_k=0.5)
    hs = [tr.assess([_person(0.0, 4.2 - 0.3 * k)], k * DT) for k in range(2)]
    assert all(h.level < 2 for h in hs)
    # người đứng yên giữa lối, người dùng đi 1,2 m/s: vẫn báo sớm >= 1,5 s
    run = _walk(_tracker(v_conf_k=0.5), [(0.0, 12.0, 0.0)], 1.2)
    first = next(pos[0][1] for pos, h in run if h.level >= 2)
    assert first >= 2 + 1.5 * 1.2
    assert hazard_predict.PredictParams().v_conf_k == 0.0
