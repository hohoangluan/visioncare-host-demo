"""C1b — sinh chuỗi hộp 8 fps từ camera pin-hole (PLAN Gói H). Không gọi model; chỉ hình học + nhiễu theo seed.

Camera: ảnh 320x240, HFOV 66°, cao 1,6 m, nhìn thẳng. Vật đứng trên mặt đất: hộp chiếu từ đáy (chạm đất) và đỉnh vật,
cắt theo biên ảnh. Trục: Z = khoảng cách phía trước (m), X = lệch ngang (phải dương). Người dùng đi dọc +Z.

Nhãn đúng (hình học): t_danger = khung đầu tiên có Z < DANGER_Z (2 m) VÀ |X| < LANE_HALF (0,6 m). Không có t_danger = an toàn.
Mỗi kịch bản dừng khi Z < STOP_Z (0,5 m) hoặc hết quỹ đạo.
"""

import math
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


@dataclass
class Camera:
    w: int = IMG_W
    h: int = IMG_H
    hfov_deg: float = HFOV_DEG
    height: float = CAM_H

    @property
    def f(self) -> float:
        return (self.w / 2) / math.tan(math.radians(self.hfov_deg / 2))

    def project(self, X: float, Z: float, obj_h: float, obj_w: float):
        """Hộp chuẩn hoá [0,1] đã cắt biên; None nếu ngoài ảnh/quá nhỏ."""
        if Z <= 0.05:
            return None
        f = self.f
        x0 = self.w / 2 + f * (X - obj_w / 2) / Z
        x1 = self.w / 2 + f * (X + obj_w / 2) / Z
        y_bot = self.h / 2 + f * self.height / Z
        y_top = self.h / 2 + f * (self.height - obj_h) / Z
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
    Z: list = field(repr=False)
    X: list = field(repr=False)

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


def generate(type_name: str, seed: int, cam: Camera | None = None) -> Scenario:
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
    return Scenario(type_name, seed, td is not None, td, frames, Zs, Xs)


def generate_all(n_seeds: int = 50, types: list[str] | None = None) -> list[Scenario]:
    return [generate(t, s) for t, _, _ in TYPES if types is None or t in types for s in range(n_seeds)]
