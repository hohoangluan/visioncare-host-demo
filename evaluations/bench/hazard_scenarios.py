"""C1b — sinh chuỗi hộp 8 fps từ camera pin-hole (PLAN Gói H). Không gọi model; chỉ hình học + nhiễu theo seed.

Camera: ảnh 320x240, HFOV 66°, cao 1,6 m, nhìn thẳng. Vật đứng trên mặt đất: hộp chiếu từ đáy (chạm đất) và đỉnh vật,
cắt theo biên ảnh. Trục: Z = khoảng cách phía trước (m), X = lệch ngang (phải dương). Người dùng đi dọc +Z.

Nhãn đúng (hình học): t_danger = khung đầu tiên có Z < DANGER_Z (2 m) VÀ |X| < LANE_HALF (0,6 m). Không có t_danger = an toàn.
Mỗi kịch bản dừng khi Z < STOP_Z (0,5 m) hoặc hết quỹ đạo.

Ba split (Task 4): "legacy" = 24 loại cũ, camera/kích thước danh nghĩa, dt cố định, hộp y hệt bản cũ từng bit (đã khoá bằng
fixtures/c1b_legacy_hash.json). "dev"/"test" = thêm loại Việt Nam, lấy mẫu tham số THẬT (camera, chiều cao người, nhún bước,
quay đầu, nhoè, dt) — logic luôn dùng giá trị danh nghĩa nên sai lệch này là thứ bàn đo cần chịu được. test rộng hơn dev.
"""

import math
import os
import zlib
from dataclasses import dataclass, field

import numpy as np

import config  # noqa: F401  (VH, qua common.setup)
from live import hazard

FPS = 8
DT = 1.0 / FPS
IMG_W, IMG_H = 320, 240
HFOV_DEG = 66.0
CAM_H = 1.6
DANGER_Z = 2.0
LANE_HALF = 0.6
STOP_Z = 0.5
MIN_BOX_PX = 4          # detector nano ở 320 px không thấy hộp nhỏ hơn thế (giả định, đổi được)
SHAKE_SIZE, SHAKE_POS = 0.10, 0.05
FLICKER_P = 1 / 3
SCORE_RANGE = (0.4, 0.9)
MAX_FRAMES = 400

# tên -> (kind VH, cao m, rộng m). Cột/ghế đá không có trong COCO: dùng kind tĩnh gần nhất (parking_meter/bench) —
# bench C1b kiểm LOGIC với detector lý tưởng, không kiểm khả năng thấy vật (đó là việc của C1a).
OBJECTS = {
    "person": ("person", 1.7, 0.5),
    "motorbike": ("motorbike", 1.1, 0.8),
    "car": ("car", 1.5, 1.8),
    "pole": ("parking_meter", 3.0, 0.15),
    "bench": ("bench", 0.45, 1.5),
}
_GROUP = {v[0]: v[1] for v in hazard._CLASSES.values()}
_GROUP["pole"] = "static"       # dev/test: cột là kind "pole" (lớp của model fine-tune), không có trong COCO -> tự khai group
BAND = 0.2                      # biên ngoài hành lang để coi là đã thoát (t_clear_frame): |X| > LANE_HALF + BAND


@dataclass
class Camera:
    w: int = IMG_W
    h: int = IMG_H
    hfov_deg: float = HFOV_DEG
    height: float = CAM_H

    @property
    def f(self) -> float:
        return (self.w / 2) / math.tan(math.radians(self.hfov_deg / 2))

    def project(self, X: float, Z: float, obj_h: float, obj_w: float, dx: float = 0.0, dy: float = 0.0):
        """Hộp chuẩn hoá [0,1] đã cắt biên; None nếu ngoài ảnh/quá nhỏ. dx, dy (px) = camera quay/nhún (mặc định 0 = cũ)."""
        if Z <= 0.05:
            return None
        f = self.f
        x0 = self.w / 2 + f * (X - obj_w / 2) / Z + dx
        x1 = self.w / 2 + f * (X + obj_w / 2) / Z + dx
        y_bot = self.h / 2 + f * self.height / Z + dy
        y_top = self.h / 2 + f * (self.height - obj_h) / Z + dy
        pw, ph = x1 - x0, y_bot - y_top
        cx0, cx1 = min(max(x0, 0.0), self.w), min(max(x1, 0.0), self.w)
        cy0, cy1 = min(max(y_top, 0.0), self.h), min(max(y_bot, 0.0), self.h)
        if cx1 - cx0 < MIN_BOX_PX or cy1 - cy0 < MIN_BOX_PX:
            return None
        return (cx0 / self.w, cy0 / self.h, cx1 / self.w, cy1 / self.h)


# type -> mô tả. kind: 'approach' (nhiều tốc độ, vật trong lối) | 'cross' | 'far' | 'edge'
BASE = {
    "walk_static_person": dict(kind="approach", obj="person", closing=1.2, z0=(12, 18)),
    "walk_static_pole": dict(kind="approach", obj="pole", closing=1.2, z0=(12, 18)),
    "walk_static_car": dict(kind="approach", obj="car", closing=1.2, z0=(12, 18)),
    "walk_static_bench": dict(kind="approach", obj="bench", closing=1.2, z0=(12, 18)),
    "oncoming_person": dict(kind="approach", obj="person", closing=2.4, z0=(14, 22)),
    "motorbike_charge": dict(kind="approach", obj="motorbike", closing=4.0, z0=(22, 32)),
    "cross_person": dict(kind="cross", obj="person", lat=1.4, z=(6, 12)),
    "cross_motorbike": dict(kind="cross", obj="motorbike", lat=5.0, z=(6, 12)),
    "far_static_person": dict(kind="far", obj="person", closing=1.2, z0=(14, 30)),
    "far_static_car": dict(kind="far", obj="car", closing=1.2, z0=(14, 30)),
    "edge_static_person": dict(kind="edge", obj="person", closing=1.2, z0=(12, 18), lateral=1.5),
    "edge_static_car": dict(kind="edge", obj="car", closing=1.2, z0=(12, 18), lateral=1.5),
}
# (tên kịch bản, tên gốc, nhiễu)
TYPES: list[tuple[str, str, str]] = [(k, k, "") for k in BASE]
for _b in ("walk_static_person", "oncoming_person", "motorbike_charge", "far_static_car", "edge_static_person", "cross_person"):
    for _n in ("shake", "flicker"):
        TYPES.append((f"{_b}+{_n}", _b, _n))
TYPE_INDEX = {t[0]: i for i, t in enumerate(TYPES)}


@dataclass
class Scenario:
    type: str
    seed: int
    positive: bool                 # có t_danger
    t_danger_frame: int | None
    frames: list = field(repr=False)   # list[list[Detection]]
    Z: list = field(repr=False)        # Z, X của vật chính (vật đầu tiên) theo từng khung
    X: list = field(repr=False)
    t_visible_frame: int | None = None  # khung đầu tiên thấy vật chính (None = không bao giờ thấy)
    times: list = field(default_factory=list, repr=False)   # mốc thời gian (s) mỗi khung, tăng nghiêm ngặt
    ego: list = field(default_factory=list, repr=False)     # (shift_x đo được / bề rộng ảnh, blur) mỗi khung
    group: str = "legacy"              # "legacy" | "vn" | "sudden" | "control"
    split: str = "legacy"
    params: dict = field(default_factory=dict, repr=False)  # tham số THẬT đã lấy mẫu (logic không được biết)
    t_clear_frame: int | None = None   # khung đầu tiên vật đã thoát/đi qua (None = không áp dụng hoặc không xảy ra)

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def minutes(self) -> float:
        return self.n_frames * DT / 60.0


def _trajectory(spec: dict, rng: np.random.Generator):
    """-> (Z[k], X[k]) của tâm vật; dừng khi Z < STOP_Z. Cross/far: lấy mẫu lại đến khi nhãn 'an toàn' đúng."""
    kind = spec["kind"]
    for _ in range(200):
        Zs, Xs = [], []
        if kind == "approach":
            z0 = rng.uniform(*spec["z0"]); x = rng.uniform(-0.4, 0.4)
            k = 0
            while len(Zs) < MAX_FRAMES:
                z = z0 - spec["closing"] * k * DT
                if z < STOP_Z:
                    break
                Zs.append(z); Xs.append(x); k += 1
            return Zs, Xs
        if kind in ("far", "edge"):
            z0 = rng.uniform(*spec["z0"]); lat = spec.get("lateral", 0.0)
            x = rng.choice([-1, 1]) * lat if kind == "edge" else rng.uniform(-0.4, 0.4)
            stop = 8.0 if kind == "far" else STOP_Z
            k = 0
            while len(Zs) < MAX_FRAMES:
                z = z0 - spec["closing"] * k * DT
                if z < stop:
                    break
                Zs.append(z); Xs.append(x); k += 1
            return Zs, Xs
        if kind == "cross":
            zc = rng.uniform(*spec["z"]); x0 = rng.choice([-1, 1]) * rng.uniform(2.5, 4.0)
            v = spec["lat"]; user_v = 1.2
            k = 0
            while len(Zs) < MAX_FRAMES:
                z = zc - user_v * k * DT
                x = x0 - np.sign(x0) * v * k * DT
                if z < STOP_Z or (k > 0 and np.sign(x) != np.sign(x0) and abs(x) > 2.5):
                    break
                Zs.append(z); Xs.append(float(x)); k += 1
            if not any(z < DANGER_Z and abs(x) < LANE_HALF for z, x in zip(Zs, Xs)):
                return Zs, Xs
            continue
    raise RuntimeError("không sinh được kịch bản an toàn sau 200 lần")


def _generate_legacy(type_name: str, seed: int, cam: Camera | None = None) -> Scenario:
    """Bản cũ giữ nguyên chuỗi rng/phép tính (đừng đổi thứ tự lấy mẫu: hash fixture sẽ vỡ)."""
    cam = cam or Camera()
    _, base, noise = TYPES[TYPE_INDEX[type_name]]
    spec = BASE[base]
    rng = np.random.default_rng([TYPE_INDEX[type_name], seed])
    Zs, Xs = _trajectory(spec, rng)
    kind, oh, ow = OBJECTS[spec["obj"]]
    frames = []
    for z, x in zip(Zs, Xs):
        box = cam.project(x, z, oh, ow)
        dets = []
        if box is not None:
            if noise == "flicker" and rng.random() < FLICKER_P:
                box = None
        if box is not None:
            if noise == "shake":
                bw, bh = box[2] - box[0], box[3] - box[1]
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                bw *= 1 + rng.uniform(-SHAKE_SIZE, SHAKE_SIZE); bh *= 1 + rng.uniform(-SHAKE_SIZE, SHAKE_SIZE)
                cx += rng.uniform(-SHAKE_POS, SHAKE_POS) * bw; cy += rng.uniform(-SHAKE_POS, SHAKE_POS) * bh
                box = tuple(min(max(v, 0.0), 1.0) for v in (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
            score = float(rng.uniform(*SCORE_RANGE))
            dets.append(hazard.Detection(kind, _GROUP[kind], score, tuple(box)))
        frames.append(dets)
    td = next((k for k, (z, x) in enumerate(zip(Zs, Xs)) if z < DANGER_Z and abs(x) < LANE_HALF), None)
    times = [k * DT for k in range(len(frames))]
    tv = next((k for k, f in enumerate(frames) if f), None)
    # ego dùng rng riêng (không đụng chuỗi rng của hộp): không quay đầu nên shift đo = nhiễu đo, ảnh luôn nét
    erng = np.random.default_rng([TYPE_INDEX[type_name], seed, 7])
    ego = _ego_idle(erng, len(frames), SIGMA_MEAS["dev"])
    return Scenario(type_name, seed, td is not None, td, frames, Zs, Xs, tv, times, ego, "legacy", "legacy",
                    dict(person_h=1.7, cam_h=CAM_H, hfov=HFOV_DEG, pitch_deg=0.0),
                    t_clear(Zs, Xs) if base in CLEAR_BASES else None)




# ======================================================================================================================
# Task 4 — split dev/test + loại Việt Nam. Quỹ đạo dựng liên tục theo thời gian (lưới 10 ms) rồi lấy mẫu tại các mốc
# khung, nên dt tuỳ ý (test: dt thất thường + rớt khung) vẫn dùng chung một mô hình thế giới.
# ======================================================================================================================
GRID = 0.01
_TG = np.arange(0.0, MAX_FRAMES * DT, GRID)
USER_V = 1.2                      # m/s, người dùng đi bộ
SPLIT_SEED = {"legacy": 0, "dev": 1000, "test": 2000}
# nhiễu đo shift_x (tỉ lệ bề rộng ảnh) của ego_motion, mỗi cặp khung. Đo trên 400 ảnh thật Obstacle-Dataset (JPEG q15, đi tới + nhún + quay): σ 0,0010–0,0013.
# dev = 3× mức đo (thị sai 3D, vật chuyển động, rolling shutter chưa có trong phép đo), test = 2× dev. Bản cũ 0,01/0,02 là giả định chưa đo.
SIGMA_MEAS = {"dev": 0.004, "test": 0.008}
# Nhiễu detector đo trên YOLOv8 + ByteTrack thật của HEADS-UP (Haghighi et al., arXiv:2409.20324; bench/heads_up_eval.py, 8 fps,
# phần dư so với trung bình trượt 5 khung): tâm ngang σ_bền 11,3 % bề rộng hộp, chiều cao 2,3 %, bề rộng 4,4 % (đuôi dày -> Student-t 3);
# 8,7 % khung mất giữa track, chuỗi mất dài 1/2/3/4/≥5 khung = 51/23/12/9/41 lần. Áp cho MỌI kịch bản dev/test (legacy giữ nguyên).
# C1B_DET_NOISE=0 tắt (tái lập số vòng 2).
DET_NOISE = os.environ.get("C1B_DET_NOISE", "1") == "1"
DET_CX_SIG, DET_H_SIG, DET_W_SIG = 0.113, 0.023, 0.044
_T3_ROBUST = 1.134                                 # σ_bền (1,4826·MAD) của Student-t bậc 3
DET_GAP_LEN = (np.arange(1, 13), np.array([51, 23, 12, 9] + [41 / 8] * 8) / 136.0)
DET_GAP_P = 0.026                                  # p·E[độ dài] = m/(1−m), m = 8,7 %, E[độ dài] ≈ 3,65
SHARP_BLUR, MOTION_BLUR = (80.0, 200.0), (10.0, 25.0)
GAIT_HZ, YAW_HZ, BLUR_P = 2.0, 0.3, 0.25      # BLUR_P = xác suất một đỉnh nhún gây chuỗi nhoè
DROP_P = 0.05

# Tham số THẬT lấy mẫu theo split (bảng trong brief). Logic luôn dùng giá trị danh nghĩa.
_P = {
    "dev": dict(person_sd=0.08, child_p=0.0, cam_h=(1.50, 1.70), hfov=(64.0, 68.0), pitch=2.0,
                gait=(0.02, 0.05), yaw=0.08, blur_n=(2, 4), jitter=False),
    "test": dict(person_sd=0.10, child_p=0.10, cam_h=(1.45, 1.75), hfov=(62.0, 70.0), pitch=4.0,
                 gait=(0.03, 0.08), yaw=0.12, blur_n=(2, 6), jitter=True),
}

# loại mới -> group. Nhãn (nguy hiểm/an toàn) do hình học quyết định; `positive` chỉ là điều kiện dựng quỹ đạo.
NEW = {
    "sudden_person_behind_car": dict(group="sudden", positive=True),
    "sudden_motorbike_alley": dict(group="sudden", positive=True),
    "motorbike_swerve": dict(group="vn", positive=True),
    "motorbike_wrong_way": dict(group="vn", positive=True),
    "cross_cut_person": dict(group="vn", positive=True),
    "parked_motorbike_row": dict(group="vn", positive=False),
    "pass_by_person": dict(group="vn", positive=False),
    "same_dir_person": dict(group="vn", positive=False),
    "approach_then_stop": dict(group="control", positive=False),
    "sidestep_avoid": dict(group="release", positive=False),     # thêm SAU CÙNG để chỉ số loại cũ trong EXT_INDEX không đổi
}
CLEAR_BASES = ("pass_by_person", "cross_person", "cross_motorbike", "sidestep_avoid")   # loại có t_clear_frame
_NOISY_BASES = ["walk_static_person", "oncoming_person", "motorbike_charge", "far_static_car", "edge_static_person",
                "cross_person"] + [b for b in NEW if b != "sidestep_avoid"]
# sidestep_avoid + biến thể gait/yaw nối ở CUỐI: chỉ số (và seed rng) của mọi loại đã có giữ nguyên
ALL_TYPES: list[str] = ([t[0] for t in TYPES] + [b for b in NEW if b != "sidestep_avoid"]
                        + [f"{b}+{n}" for b in _NOISY_BASES for n in ("gait", "yaw", "blur")]
                        + ["sidestep_avoid"] + [f"sidestep_avoid+{n}" for n in ("gait", "yaw")])
EXT_INDEX = {t: i for i, t in enumerate(ALL_TYPES)}


@dataclass
class _Obj:
    key: str                       # khoá OBJECTS
    X: np.ndarray                  # theo lưới _TG
    Z: np.ndarray
    vis: np.ndarray                # False = bị che (chưa lộ), không ra hộp


def _obj(key, X, Z, vis=None) -> _Obj:
    X = np.full(len(_TG), float(X)) if np.isscalar(X) else np.asarray(X, float)
    return _Obj(key, X, np.asarray(Z, float), np.ones(len(_TG), bool) if vis is None else vis)


def _first(mask) -> int:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if idx.size else len(mask)


def _dwell(objs: list, end: int) -> float:
    """Tổng thời gian (s) có vật nào trong vùng nguy hiểm (Z < 2 m và |X| < 0,6 m, tâm vật)."""
    m = np.zeros(end, bool)
    for o in objs:
        m |= (o.Z[:end] < DANGER_Z) & (np.abs(o.X[:end]) < LANE_HALF)
    return float(m.sum()) * GRID


MIN_DWELL = 0.3     # nguy hiểm thật phải kéo dài >= 0,3 s (xe máy 4 m/s đi từ Z 2 xuống 0,5 m chỉ mất 0,375 s)
# test: hở giữa 2 khung có thể tới 0,4 s nên có khi nhãn lấy mẫu rơi mất -> _generate_ext dựng lại đến khi nhãn mẫu khớp


def _accept(objs, end, positive: bool) -> bool:
    d = _dwell(objs, end)
    return d >= MIN_DWELL if positive else d == 0.0


def _b_legacy(spec: dict, rng) -> tuple:
    """Loại cũ dựng theo thời gian liên tục (dùng cho dev/test; legacy vẫn đi đường cũ)."""
    kind = spec["kind"]
    for _ in range(200):
        if kind in ("approach", "far", "edge"):
            z0 = rng.uniform(*spec["z0"]); lat = spec.get("lateral", 0.0)
            x = rng.choice([-1, 1]) * lat if kind == "edge" else rng.uniform(-0.4, 0.4)
            Z = z0 - spec["closing"] * _TG
            objs = [_obj(spec["obj"], x, Z)]
            return objs, _first(Z < (8.0 if kind == "far" else STOP_Z))
        zc = rng.uniform(*spec["z"]); x0 = rng.choice([-1, 1]) * rng.uniform(2.5, 4.0)
        Z = zc - USER_V * _TG; X = x0 - np.sign(x0) * spec["lat"] * _TG
        end = _first((Z < STOP_Z) | ((_TG > 0) & (np.sign(X) != np.sign(x0)) & (np.abs(X) > 2.5)))
        objs = [_obj(spec["obj"], X, Z)]
        if _dwell(objs, end) == 0.0:
            return objs, end
    raise RuntimeError("không sinh được kịch bản an toàn sau 200 lần")


def _step_in(s, lateral0, speed, t0, xs):
    """Khoảng cách tới tâm lối giảm đều từ lateral0 với `speed` kể từ t0, dừng ở lệch xs (vật bước/lạng vào lối)."""
    u = np.maximum(lateral0 - speed * np.clip(_TG - t0, 0.0, None), 0.0)
    return s * u + xs * (1.0 - u / lateral0)


def _b_sudden_person(rng):
    s = rng.choice([-1, 1]); zr = rng.uniform(3.5, 4.5); th = rng.uniform(1.0, 2.5); xs = rng.uniform(-0.1, 0.1)
    Zp = zr + USER_V * (th - _TG)                       # Z = zr đúng lúc lộ ra (t = th)
    person = _obj("person", _step_in(s, 1.2, 0.8, th, xs), Zp, _TG >= th)
    car = _obj("car", s * 2.0, Zp - 1.0)                # xe che: đỗ sát lề, gần người dùng hơn người 1 m
    return [person, car], _first(Zp < STOP_Z)


def _b_sudden_bike(rng):
    s = rng.choice([-1, 1]); zr = rng.uniform(4.0, 6.0); th = rng.uniform(0.5, 2.0); xs = rng.uniform(-0.2, 0.2)
    Z = zr + 3.2 * (th - _TG)
    o = _obj("motorbike", _step_in(s, 2.5, 2.5, th, xs), Z, _TG >= th)
    return [o], _first(Z < STOP_Z)


def _b_swerve(rng):
    s = rng.choice([-1, 1]); z0 = rng.uniform(22, 32); zs = rng.uniform(8, 12); xf = rng.uniform(-0.15, 0.15)
    Z = z0 - 4.0 * _TG
    q = np.clip((_TG - (z0 - zs) / 4.0) / 1.0, 0.0, 1.0); sm = q * q * (3 - 2 * q)      # lạng vào lối trong 1 s
    return [_obj("motorbike", (1 - sm) * s * 1.5 + sm * xf, Z)], _first(Z < STOP_Z)


def _b_wrong_way(rng):
    z0 = rng.uniform(15, 25); x = rng.uniform(-0.4, 0.4)
    Z = z0 - (USER_V + 3.0) * _TG
    return [_obj("motorbike", x, Z)], _first(Z < STOP_Z)


def _b_cut(rng):
    s = rng.choice([-1, 1]); zc = rng.uniform(3, 4); v = rng.uniform(0.9, 1.5); ax = rng.uniform(2.0, 3.0)
    xs = rng.uniform(-0.3, 0.3); tc = ax / v
    Z = zc + USER_V * (tc - _TG)                        # Z = zc đúng lúc người cắt tới tâm lối, rồi đứng lại trong lối
    return [_obj("person", _step_in(s, ax, v, 0.0, xs), Z)], _first(Z < STOP_Z)


def _b_row(rng):
    n = int(rng.integers(4, 9)); s = rng.choice([-1, 1]); zf = rng.uniform(4, 8)
    z0 = zf + np.concatenate([[0.0], np.cumsum(rng.uniform(1.0, 1.5, n - 1))])
    xs = s * rng.uniform(0.9, 1.5, n)
    objs = [_obj("motorbike", xs[i], z0[i] - USER_V * _TG) for i in range(n)]
    return objs, _first(np.max([o.Z for o in objs], axis=0) < STOP_Z)


def _b_pass(rng):
    s = rng.choice([-1, 1]); x = s * rng.uniform(0.8, 1.2); z0 = rng.uniform(14, 22)
    Z = z0 - 2.4 * _TG
    return [_obj("person", x, Z)], _first(Z < STOP_Z)


def _b_same_dir(rng):
    z = rng.uniform(3, 5); x = rng.uniform(-0.3, 0.3); ph = rng.uniform(0, 2 * math.pi)
    Z = z + 0.1 * np.sin(2 * math.pi * 0.2 * _TG + ph)       # đi cùng tốc độ: Z gần như không đổi
    X = x + 0.05 * np.sin(2 * math.pi * 0.15 * _TG + ph)
    return [_obj("person", X, Z)], _first(_TG >= 30.0)


def _b_stop(rng):
    key = rng.choice(["person", "pole", "bench", "car"]); z0 = rng.uniform(8, 12); x = rng.uniform(-0.3, 0.3)
    Z = np.maximum(3.0, z0 - USER_V * _TG)
    return [_obj(str(key), x, Z)], _first(_TG > (z0 - 3.0) / USER_V + 10.0)


def _b_sidestep(rng):
    """Người dùng đi 1,2 m/s tới vật đứng yên trong lối; ở Z 4,5–5,5 m bước né sang bên 1,0–1,2 m trong 1,0 s rồi đi tiếp qua."""
    key = str(rng.choice(["person", "motorbike"])); z0 = rng.uniform(10, 14); x0 = rng.uniform(-0.2, 0.2)
    zs = rng.uniform(4.5, 5.5); d = rng.uniform(1.0, 1.2)
    sg = 1.0 if x0 >= 0 else -1.0                       # vật dịch ra xa tâm lối (người dùng né về phía ngược lại)
    Z = z0 - USER_V * _TG
    q = np.clip((_TG - (z0 - zs) / USER_V) / 1.0, 0.0, 1.0); sm = q * q * (3 - 2 * q)
    return [_obj(key, x0 + sg * d * sm, Z)], _first(Z < STOP_Z)


def t_clear(Z, X) -> int | None:
    """Khung đầu tiên vật đã đi qua: Z < 0,5 m, hoặc |X| > LANE_HALF + BAND sau khi từng ở trong LANE_HALF + BAND."""
    seen = False
    for k, (z, x) in enumerate(zip(Z, X)):
        if z < STOP_Z:
            return k
        if abs(x) < LANE_HALF + BAND:
            seen = True
        elif seen:
            return k
    return None


_BUILD = {"sudden_person_behind_car": _b_sudden_person, "sudden_motorbike_alley": _b_sudden_bike,
          "motorbike_swerve": _b_swerve, "motorbike_wrong_way": _b_wrong_way, "cross_cut_person": _b_cut,
          "parked_motorbike_row": _b_row, "pass_by_person": _b_pass, "same_dir_person": _b_same_dir,
          "approach_then_stop": _b_stop,
          "sidestep_avoid": _b_sidestep}


def _build(base: str, rng) -> tuple:
    if base in BASE:
        return _b_legacy(BASE[base], rng)
    for _ in range(200):
        objs, end = _BUILD[base](rng)
        if _accept(objs, end, NEW[base]["positive"]):
            return objs, end
    raise RuntimeError(f"không dựng được {base} đúng nhãn sau 200 lần")


def _ego_idle(rng, n: int, sigma: float) -> list:
    """Không quay đầu, ảnh nét: shift đo = N(0; sigma), blur trong dải nét."""
    return [(float(rng.normal(0.0, sigma)), float(rng.uniform(*SHARP_BLUR))) for _ in range(n)]


def _sample_times(rng, split: str, t_end: float) -> list:
    ts, k, t = [], 0, 0.0
    if not _P[split]["jitter"]:
        while k * DT <= t_end and len(ts) < MAX_FRAMES:
            ts.append(k * DT); k += 1
        return ts
    while t <= t_end and len(ts) < MAX_FRAMES:
        if not ts or rng.random() >= DROP_P:        # khung rớt: thời gian vẫn trôi nhưng không có khung
            ts.append(t)
        t += rng.uniform(0.10, 0.20)
    return ts


def _split_name(type_name: str) -> tuple:
    base, _, noise = type_name.partition("+")
    return base, noise


def _generate_ext(type_name: str, seed_idx: int, split: str, cam: Camera | None) -> Scenario:
    P = _P[split]
    base, noise = _split_name(type_name)
    seed = SPLIT_SEED[split] + seed_idx
    rng = np.random.default_rng([EXT_INDEX[type_name], seed])
    # --- tham số thật (logic không biết) ---
    if rng.random() < P["child_p"]:
        person_h = float(rng.normal(1.1, 0.05))
    else:
        person_h = float(rng.normal(1.65, P["person_sd"]))
    cam_h, hfov = float(rng.uniform(*P["cam_h"])), float(rng.uniform(*P["hfov"]))
    pitch = float(rng.uniform(-P["pitch"], P["pitch"]))
    cam = cam or Camera(hfov_deg=hfov, height=cam_h)
    dy_pitch = cam.f * math.tan(math.radians(pitch))          # camera cúi/ngửa lệch -> cả ảnh trượt dọc
    params = dict(person_h=person_h, cam_h=cam.height, hfov=cam.hfov_deg, pitch_deg=pitch)
    want = NEW[base]["positive"] if base in NEW else None
    for _ in range(50):             # loại mới: nhãn lấy mẫu phải khớp nhãn khai báo (xem MIN_DWELL)
        sc = _render_world(type_name, base, noise, seed, split, P, rng, cam, person_h, dy_pitch, params)
        if want is None or sc.positive == want:
            return sc
    raise RuntimeError(f"nhãn mẫu của {type_name} không khớp sau 50 lần")


def _det_noise(box, j: int, gap_left: dict, drng):
    """Hộp như detector thật: rung tâm/kích thước (Student-t 3) và chuỗi khung mất (Markov). None = khung này không thấy vật j."""
    if gap_left.get(j, 0) > 0:
        gap_left[j] -= 1
        return None
    if drng.random() < DET_GAP_P:
        gap_left[j] = int(drng.choice(DET_GAP_LEN[0], p=DET_GAP_LEN[1])) - 1
        return None
    bw, bh = box[2] - box[0], box[3] - box[1]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    t = drng.standard_t(3, 3) / _T3_ROBUST
    cx += DET_CX_SIG * t[0] * bw
    bw *= math.exp(DET_W_SIG * t[1])
    bh *= math.exp(DET_H_SIG * t[2])
    return tuple(min(max(v, 0.0), 1.0) for v in (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))


def _render_world(type_name, base, noise, seed, split, P, rng, cam, person_h, dy_pitch, params) -> Scenario:
    """Dựng thế giới + lấy mẫu mốc khung + chiếu hộp (có nhiễu chuyển động) cho một lần thử."""
    objs, end = _build(base, rng)
    ts = _sample_times(rng, split, float(_TG[max(end - 1, 0)]))
    sigma = SIGMA_MEAS[split]
    ay, a_size = P["gait"]
    ph_g, ph_y = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    legacy_noise = noise if noise in ("shake", "flicker") else ""
    frames, ego, Zp, Xp, td, tv = [], [], [], [], None, None
    blur_left, prev_peak = 0, 0
    drng = np.random.default_rng([zlib.crc32(type_name.encode()), seed, 11, len(ts)])   # nhiễu detector: rng riêng
    gap_left = {}
    sx_prev = None                                            # EgoMeter trả trượt GIỮA HAI KHUNG, không phải lệch tuyệt đối
    for k, t in enumerate(ts):
        gi = min(int(t / GRID), len(_TG) - 1)
        dx = dy = 0.0; scale = 1.0; sx_true = 0.0
        if noise == "gait":                                   # nhún bước 2 Hz: ảnh trượt dọc + vật phình/xẹp
            dy += ay * IMG_H * math.sin(2 * math.pi * GAIT_HZ * t + ph_g)
            scale = 1.0 + a_size * math.cos(2 * math.pi * GAIT_HZ * t + ph_g)
        if noise == "yaw":                                    # quay đầu 0,3 Hz: ảnh trượt ngang
            sx_true = P["yaw"] * math.sin(2 * math.pi * YAW_HZ * t + ph_y)
            dx = sx_true * IMG_W
        blurred = False
        if noise == "blur":                                   # mất khung ở đỉnh nhún (sin 2 Hz đạt max tại 2t = n + 1/4)
            pk = math.floor(GAIT_HZ * t + 0.75)
            if blur_left == 0 and pk != prev_peak and rng.random() < BLUR_P:
                blur_left = int(rng.integers(P["blur_n"][0], P["blur_n"][1] + 1))
            prev_peak = pk
            if blur_left > 0:
                blurred = True; blur_left -= 1
        d_true = 0.0 if sx_prev is None else sx_true - sx_prev
        sx_prev = sx_true
        ego.append((float(d_true + rng.normal(0.0, sigma)),
                    float(rng.uniform(*(MOTION_BLUR if blurred else SHARP_BLUR)))))
        dets, got_primary = [], False
        for j, o in enumerate(objs):
            z, x = float(np.interp(t, _TG, o.Z)), float(np.interp(t, _TG, o.X))
            if j == 0:
                Zp.append(z); Xp.append(x)
            if td is None and z < DANGER_Z and abs(x) < LANE_HALF:
                td = k                                         # nhãn theo hình học thật, kể cả vật đang bị che
            if blurred or not o.vis[gi]:
                continue
            kind, oh, ow = OBJECTS[o.key]
            if o.key == "person":
                oh = person_h
            if o.key == "pole":
                kind = "pole"                                  # dev/test: kind "pole" (legacy giữ parking_meter)
            box = cam.project(x, z, oh, ow, dx, dy + dy_pitch)
            if box is not None and legacy_noise == "flicker" and rng.random() < FLICKER_P:
                box = None
            if box is not None and (legacy_noise == "shake" or scale != 1.0):
                bw, bh = box[2] - box[0], box[3] - box[1]
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                if legacy_noise == "shake":
                    bw *= 1 + rng.uniform(-SHAKE_SIZE, SHAKE_SIZE); bh *= 1 + rng.uniform(-SHAKE_SIZE, SHAKE_SIZE)
                    cx += rng.uniform(-SHAKE_POS, SHAKE_POS) * bw; cy += rng.uniform(-SHAKE_POS, SHAKE_POS) * bh
                bw *= scale; bh *= scale
                box = tuple(min(max(v, 0.0), 1.0) for v in (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
            if box is not None and DET_NOISE and split in ("dev", "test"):
                box = _det_noise(box, j, gap_left, drng)
            if box is None:
                continue
            dets.append(hazard.Detection(kind, _GROUP.get(kind, "static"), float(rng.uniform(*SCORE_RANGE)), tuple(box)))
            got_primary = got_primary or j == 0
        if got_primary and tv is None:
            tv = k
        frames.append(dets)
    group = NEW[base]["group"] if base in NEW else "legacy"
    tc = t_clear(Zp, Xp) if base in CLEAR_BASES else None
    return Scenario(type_name, seed, td is not None, td, frames, Zp, Xp, tv, ts, ego, group, split, params, tc)


def generate(type_name: str, seed: int, split: str = "legacy", cam: Camera | None = None) -> Scenario:
    """Một kịch bản. split: legacy (seed s, 24 loại cũ, y hệt bản cũ) | dev (seed 1000+s) | test (seed 2000+s)."""
    if split == "legacy":
        if type_name not in TYPE_INDEX:
            raise ValueError(f"loại {type_name!r} không có trong split legacy (chỉ 24 loại cũ)")
        return _generate_legacy(type_name, seed, cam)
    if split not in _P:
        raise ValueError(f"split không hợp lệ: {split!r}")
    if type_name not in EXT_INDEX:
        raise ValueError(f"loại không biết: {type_name!r}")
    return _generate_ext(type_name, seed, split, cam)


def generate_all(n_seeds: int = 50, types: list[str] | None = None, split: str = "legacy") -> list[Scenario]:
    names = [t[0] for t in TYPES] if split == "legacy" else ALL_TYPES
    return [generate(t, s, split) for t in names if types is None or t in types for s in range(n_seeds)]
