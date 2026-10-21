"""Làn C (predict): gán detection qua các khung thành track và lọc Kalman (X, Z, vX, vZ) theo mốc thời gian thật.

Vận tốc không đổi, nhiễu quá trình dạng gia tốc trắng. Đo (X, Z) có R chéo nên hai trục tách rời nhau:
mỗi trục là một bộ lọc 2 trạng thái (vị trí, vận tốc) tính bằng số thực thuần Python (nhanh hơn numpy cho
ma trận 2×2, phần ngân sách 1 ms/khung). `x` và `P` vẫn giữ dạng 4 / 4×4 theo thứ tự [X, Z, vX, vZ].
"""

import math
from dataclasses import dataclass

import numpy as np

from live import hazard
from live.hazard_geom import Estimate

DT_DEFAULT = 0.125     # 8 fps; dùng khi mốc thời gian thiếu / trùng / lùi / nhảy quá xa
DT_MAX = 1.0
IOU_MIN = 0.2          # ngưỡng gán track <-> detection (hộp dự đoán = hộp cũ)
X_REL_SIGMA = 0.1      # σ_X đo = 0,1·Z (cùng góc ngang, Z càng xa X càng lệch)
_EDGE_X = 0.01        # hộp cách mép trái/phải <= mức này (tỉ lệ) = bị cắt ngang
V_SIGMA_NEW = 3.0      # m/s: vận tốc ban đầu của track mới chưa biết gì


@dataclass
class Track:
    id: int
    kind: str
    group: str
    box: tuple
    x: np.ndarray  # [X, Z, vX, vZ]
    P: np.ndarray  # 4x4
    hits: int = 1
    misses: int = 0
    age: int = 1
    anchor_z: float = float('nan')  # Z đo thô lần cuối KHÔNG bị cắt đáy (neo cho tỉ lệ bề rộng)
    anchor_w: float = float('nan')  # bề rộng hộp (tỉ lệ) lúc đó

    def predict_xz(self, t_ahead: float) -> tuple[float, float]:
        return float(self.x[0] + self.x[2] * t_ahead), float(self.x[1] + self.x[3] * t_ahead)

    def sigma_x(self) -> float:
        return float(max(self.P[0, 0], 0.0) ** 0.5)


def _axis(x: np.ndarray, P: np.ndarray, i: int, dt: float, q: float, meas: float | None, r: float) -> None:
    """Một trục (i=0: X/vX, i=1: Z/vZ): dự đoán dt giây rồi (nếu có đo) cập nhật. Ghi thẳng vào x, P."""
    j = i + 2
    p, v = float(x[i]), float(x[j])
    a, b, d = float(P[i, i]), float(P[i, j]), float(P[j, j])
    p += dt * v
    a, b, d = a + 2 * dt * b + dt * dt * d + q * dt ** 3 / 3, b + dt * d + q * dt * dt / 2, d + q * dt
    if meas is not None:
        s = a + r
        y = meas - p
        p, v = p + a / s * y, v + b / s * y
        a, b, d = a - a * a / s, b - a * b / s, d - b * b / s
    x[i], x[j] = p, v
    P[i, i], P[i, j], P[j, i], P[j, j] = a, b, b, d


class TrackSet:
    def __init__(self, coast: int, q: float) -> None:
        self.coast, self.q = coast, q
        self._tracks: list[Track] = []
        self._next_id = 1
        self._t_prev: float | None = None
        self.last_matched: list[Track | None] = []  # theo thứ tự detection của lần update gần nhất; None = không có track

    def reset(self) -> None:
        self._tracks, self._t_prev, self.last_matched = [], None, []

    def _dt(self, t: float | None) -> float:
        prev, self._t_prev = self._t_prev, t
        if t is None or prev is None or not (0.0 < t - prev <= DT_MAX):  # mốc trùng/lùi/None/nhảy: coi như 1 khung
            return DT_DEFAULT
        return t - prev

    def update(
        self, dets: list[hazard.Detection], ests: list[Estimate], t: float | None,
        ego_shift_rad: float = 0.0, box_shift_x: float = 0.0, r_scale: float = 1.0, allow_new: bool = True,
    ) -> list[Track]:
        """Cập nhật track bằng các detection của một khung, trả mọi track còn sống (đang thấy + đang coast).

        `ego_shift_rad`: góc cảnh trượt sang phải do quay đầu (dương = X đo của vật đứng yên tăng); mỗi track được
        dời X thêm Z·rad vào hệ camera mới trước khi dự đoán nên vận tốc ước lượng là của vật, không của đầu.
        `box_shift_x`: cùng độ trượt ấy theo tỉ lệ bề rộng ảnh, để gán IoU không rớt khi quay nhanh.
        `r_scale`: nhân R (ảnh nhoè thì đo kém tin). `allow_new=False`: không tạo track từ khung này.
        """
        if t is not None and self._t_prev is not None and t - self._t_prev > DT_MAX:
            self.reset()  # mất khung lâu: track cũ không còn đáng tin
        dt = self._dt(t)
        tracks = old = self._tracks
        for tr in tracks:
            if ego_shift_rad:
                tr.x[0] += tr.x[1] * ego_shift_rad
        pairs = self._match(tracks, dets, box_shift_x)
        matched_det: set[int] = set()
        for ti, di in pairs:
            tr, det, est = tracks[ti], dets[di], ests[di]
            if est.source == "clipped":
                zm = self._width_ratio_z(tr, det)
                if zm is not None and math.isfinite(est.z_max):
                    zm = min(zm, est.z_max)
                if zm is None:  # Z không quan sát được: chỉ dự đoán Z, X vẫn lấy từ góc ngang
                    _axis(tr.x, tr.P, 1, dt, self.q, None, 0.0)
                    zp = max(float(tr.x[1]), 0.3)
                    _axis(tr.x, tr.P, 0, dt, self.q, self._x_at(est, zp), (X_REL_SIGMA * zp) ** 2 * r_scale * est.x_var_scale)
                else:
                    _axis(tr.x, tr.P, 1, dt, self.q, zm, (0.1 * zm) ** 2 * r_scale)
                    _axis(tr.x, tr.P, 0, dt, self.q, self._x_at(est, zm), (X_REL_SIGMA * zm) ** 2 * r_scale * est.x_var_scale)
            else:
                z_sigma = max(est.z_sigma, 1e-3)
                _axis(tr.x, tr.P, 0, dt, self.q, est.x_m, (X_REL_SIGMA * est.z_m) ** 2 * r_scale * est.x_var_scale)
                _axis(tr.x, tr.P, 1, dt, self.q, est.z_m, z_sigma ** 2 * r_scale)
                self._set_anchor(tr, est.z_m, det.box)
            tr.box, tr.kind, tr.hits, tr.misses = det.box, det.kind, tr.hits + 1, 0
            matched_det.add(di)
        matched_tr = {ti for ti, _ in pairs}
        for ti, tr in enumerate(tracks):
            tr.age += 1
            if ti not in matched_tr:
                _axis(tr.x, tr.P, 0, dt, self.q, None, 0.0)
                _axis(tr.x, tr.P, 1, dt, self.q, None, 0.0)
                tr.misses += 1
        self._tracks = tracks = [tr for tr in tracks if tr.misses <= self.coast
                                 and np.isfinite(tr.x).all() and np.isfinite(tr.P).all()]
        by_det: list[Track | None] = [None] * len(dets)
        for ti, di in pairs:
            by_det[di] = old[ti]
        if allow_new:
            for di, (det, est) in enumerate(zip(dets, ests)):
                if di not in matched_det:
                    by_det[di] = self._new(det, est)
                    tracks.append(by_det[di])
        self.last_matched = by_det
        return list(tracks)

    @staticmethod
    def _x_at(est: Estimate, z: float) -> float:
        """X đo tại độ sâu z: theo cạnh trong nếu hộp bị cắt ngang, còn lại theo tâm hộp."""
        return est.bearing * z if est.lat_bearing != est.lat_bearing else est.lat_bearing * z + est.lat_off_m

    @staticmethod
    def _set_anchor(tr: Track, z: float, box: tuple) -> None:
        if box[0] > _EDGE_X and box[2] < 1 - _EDGE_X and box[2] - box[0] > 1e-4:
            tr.anchor_z, tr.anchor_w = z, box[2] - box[0]

    @staticmethod
    def _width_ratio_z(tr: Track, det: hazard.Detection) -> float | None:
        """Đáy hộp bị cắt: Z = Z_neo · w_neo / w_nay (bề rộng không bị mép dưới cắt). Neo = Z đo thô lần cuối chưa
        bị cắt (hoặc Z theo bảng bề rộng của track mới), KHÔNG phải Z đã lọc: Z lọc đang mang độ trễ vận tốc, dùng nó
        làm gốc thì phép đo tương đối tự nhắc lại sai số của chính bộ lọc và vật đã dừng vẫn bị kéo lại gần.
        None nếu hộp nay chạm mép trái/phải, chưa có neo, hoặc bề rộng suy biến."""
        n0, n1 = det.box[0], det.box[2]
        if not (tr.anchor_w > 0) or n0 <= _EDGE_X or n1 >= 1 - _EDGE_X or n1 - n0 <= 1e-4:
            return None
        return min(max(tr.anchor_z * tr.anchor_w / (n1 - n0), 0.3), 60.0)

    def _new(self, det: hazard.Detection, est: Estimate) -> Track:
        if est.source == "clipped":  # Z theo bề rộng danh nghĩa của lớp, σ = 0,4·Z
            z = est.z_width
            est = Estimate(z, self._x_at(est, z), 0.4 * z, "width", est.bearing, x_var_scale=est.x_var_scale)
        x = np.array([est.x_m, est.z_m, 0.0, 0.0])
        P = np.diag([(X_REL_SIGMA * est.z_m) ** 2, max(est.z_sigma, 1e-3) ** 2, V_SIGMA_NEW ** 2, V_SIGMA_NEW ** 2])
        tr = Track(self._next_id, det.kind, det.group, det.box, x, P)
        self._next_id += 1
        self._set_anchor(tr, est.z_m, det.box)
        return tr

    @staticmethod
    def _match(tracks: list[Track], dets: list[hazard.Detection], box_shift_x: float) -> list[tuple[int, int]]:
        """Gán tham lam theo IoU giảm dần, cùng nhóm, IoU >= IOU_MIN. -> [(chỉ số track, chỉ số detection)]."""
        if not tracks or not dets:
            return []
        tb = np.array([tr.box for tr in tracks], dtype=np.float64)
        db = np.array([d.box for d in dets], dtype=np.float64)
        if box_shift_x:
            tb[:, [0, 2]] += box_shift_x
        iw = np.minimum(tb[:, None, 2], db[None, :, 2]) - np.maximum(tb[:, None, 0], db[None, :, 0])
        ih = np.minimum(tb[:, None, 3], db[None, :, 3]) - np.maximum(tb[:, None, 1], db[None, :, 1])
        inter = np.clip(iw, 0, None) * np.clip(ih, 0, None)
        area_t = (tb[:, 2] - tb[:, 0]) * (tb[:, 3] - tb[:, 1])
        area_d = (db[:, 2] - db[:, 0]) * (db[:, 3] - db[:, 1])
        union = area_t[:, None] + area_d[None, :] - inter
        iou = np.where(union > 1e-12, inter / np.maximum(union, 1e-12), 0.0)
        rows, cols = np.nonzero(iou >= IOU_MIN)
        order = sorted(zip(iou[rows, cols].tolist(), rows.tolist(), cols.tolist()), reverse=True)
        pairs, used_t, used_d = [], set(), set()
        for _, i, j in order:
            if i in used_t or j in used_d or tracks[i].group != dets[j].group:
                continue
            used_t.add(i); used_d.add(j)
            pairs.append((i, j))
        return pairs
