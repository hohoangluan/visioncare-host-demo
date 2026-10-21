"""Làn C (predict): xếp mức nguy hiểm theo THỜI GIAN TỚI HÀNH LANG (TTE) thay vì diện tích hộp.

Mỗi detection -> (X, Z) mét (`hazard_geom`) -> track Kalman (`hazard_track`) -> dự đoán quỹ đạo từng bước 0,125 s:
bước đầu tiên vật ở trong hành lang (Z < danger_z, |X| < lane_half) là TTE. Người đi chậm hơn vật tới thì TTE dài, vật
đi sượt qua không cắt hành lang thì không bíp; vật mới hiện đã sát người thì báo ngay (urgent), khỏi chờ phiếu.

Bật bằng HAZARD_LOGIC=predict (`hazard.make_tracker`). Cùng chữ ký `assess` với `HazardTracker`.
"""

import math
from collections import deque
from dataclasses import dataclass

import config
from live import ego_motion, hazard, hazard_geom
from live.hazard_geom import Camera
from live.hazard_track import DT_DEFAULT, DT_MAX, TrackSet

_PITCH_N = 31          # số mẫu góc cúi gần nhất; góc cúi = trung vị (chịu được 50 % mẫu lệch như trẻ em)
_PITCH_LO = -0.02      # rad, kẹp bất đối xứng: cúi xuống thật hiếm, ngẩng/cúi lệch thì không để kéo Z ra xa
_PITCH_HI = 0.10
_BLUR_ALPHA = 0.1      # EMA độ nét của phiên
_BLUR_REL = 0.35       # nhoè <=> độ nét < 0,35 · EMA (tương đối, cảnh ít chi tiết không bị coi là nhoè)
_BLUR_MAX_RUN = 2      # tối đa chừng này khung nhoè liên tiếp bị chặn tạo track; khung kế luôn cho tạo
_BLUR_R_SCALE = 4.0    # ảnh nhoè: nhân R lên chừng này lần, không tạo track mới
_NEAR_LEVEL1_Z = 8.0   # không cắt hành lang mà gần hơn mức này (m) -> mức 1


@dataclass
class PredictParams:
    tte_l3_s: float = 1.5
    tte_l2_s: float = 3.0
    horizon_s: float = 3.0
    new_near_m: float = 3.0
    coast: int = 3
    sigma_k: float = 0.0
    v_conf_k: float = 0.0
    yaw_tau_s: float = 0.0
    q: float = 1.0
    l3_vote: int = 2
    bypass_vote: bool = True
    down_hold: int = 2
    release_s: float = 0.5
    danger_z_m: float = 2.0
    lane_half_m: float = 0.6

    @staticmethod
    def from_config() -> "PredictParams":
        return PredictParams(
            tte_l3_s=config.HAZARD_TTE_L3_S, tte_l2_s=config.HAZARD_TTE_L2_S, horizon_s=config.HAZARD_HORIZON_S,
            new_near_m=config.HAZARD_NEW_NEAR_M, coast=config.HAZARD_COAST_FRAMES, sigma_k=config.HAZARD_SIGMA_K,
            v_conf_k=config.HAZARD_V_CONF_K, yaw_tau_s=config.HAZARD_YAW_TAU_S,
            q=config.HAZARD_KF_Q, l3_vote=config.HAZARD_L3_VOTE, bypass_vote=config.HAZARD_NEW_BYPASS_VOTE == "1",
            down_hold=config.HAZARD_DOWN_HOLD, release_s=config.HAZARD_RELEASE_S, danger_z_m=config.HAZARD_DANGER_Z_M,
            lane_half_m=config.HAZARD_LANE_HALF_M,
        )


def _confident(v: float, var: float, k: float) -> float:
    """Phần vận tốc vượt k·σ: |v| − k·σ (giữ dấu), không âm. Vận tốc chưa chắc (track mới, đo nhiễu) co về 0."""
    return math.copysign(max(abs(v) - k * math.sqrt(max(var, 0.0)), 0.0), v)


def _tte(x: float, z: float, vx: float, vz: float, p: PredictParams, lane: float) -> float | None:
    """Bước 0,125 s đầu tiên (<= horizon) mà vật ở trong hành lang; None nếu không có. Giải kín, không lặp.

    Z_pred < danger và |X_pred| < lane là giao của hai khoảng thời gian mở; lấy bước lưới đầu tiên nằm trong giao.
    """
    lo, hi = 0.0, p.horizon_s + 1e-9
    if vz < -1e-9:
        lo = max(lo, (z - p.danger_z_m) / -vz)
    elif z >= p.danger_z_m:
        return None
    if abs(vx) < 1e-9:
        if abs(x) >= lane:
            return None
    else:
        a, b = (-lane - x) / vx, (lane - x) / vx
        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
    t = max(math.floor(lo / DT_DEFAULT + 1e-9) + 1, 1) * DT_DEFAULT  # mở: bước đầu tiên LỚN HƠN lo, từ bước 1
    return t if t < hi else None


class PredictTracker:
    """Từ detection mỗi khung (+ mốc thời gian, chuyển động đầu) -> mức nguy hiểm cao nhất, theo quỹ đạo dự đoán."""

    def __init__(self, params: PredictParams | None = None, cam: Camera | None = None) -> None:
        self.params = params or PredictParams.from_config()
        self.cam = cam or Camera.default()
        self.tracks = TrackSet(self.params.coast, self.params.q)
        self.pitch_rad = 0.0
        self._pitch_samples: deque[float] = deque(maxlen=_PITCH_N)
        self._blur_ema: float | None = None
        self._blur_run = 0  # số khung nhoè liên tiếp đã bị chặn tạo track
        self.yaw_rad = 0.0  # góc đầu lệch khỏi hướng thân (dương = cảnh trượt phải), tích phân rò
        self._t_yaw: float | None = None

    def _learn_pitch(self, detections: list[hazard.Detection]) -> None:
        for det in detections:
            s = hazard_geom.pitch_sample(det, self.cam)
            if s is not None and math.isfinite(s):
                self._pitch_samples.append(s)
        if self._pitch_samples:
            m = sorted(self._pitch_samples)
            self.pitch_rad = min(max(m[len(m) // 2], _PITCH_LO), _PITCH_HI)

    @staticmethod
    def _finite(det: hazard.Detection) -> bool:
        return all(math.isfinite(v) for v in det.box)

    def assess(
        self, detections: list[hazard.Detection], t: float | None = None, ego: "ego_motion.Ego | None" = None,
    ) -> hazard.Hazard:
        p, cam = self.params, self.cam
        n_in = len(detections)
        keep = [i for i, d in enumerate(detections) if self._finite(d)]  # box NaN/inf: bỏ qua, mức 0
        if len(keep) != n_in:
            detections = [detections[i] for i in keep]
        ests = [hazard_geom.estimate(d, cam, self.pitch_rad) for d in detections]
        rad = shift = 0.0
        r_scale, allow_new = 1.0, True
        if ego is not None:
            shift = ego.shift_x
            rad = shift * cam.w / cam.f_px  # góc: tỉ lệ bề rộng · w / f
            b = ego.blur
            if math.isfinite(b):
                self._blur_ema = b if self._blur_ema is None else self._blur_ema + _BLUR_ALPHA * (b - self._blur_ema)
                if b < _BLUR_REL * self._blur_ema:
                    r_scale = _BLUR_R_SCALE
                    if self._blur_run < _BLUR_MAX_RUN:
                        allow_new = False
                        self._blur_run += 1
                    else:
                        self._blur_run = 0  # khung thứ 3 liên tiếp: cho tạo track, đếm lại
                else:
                    self._blur_run = 0
        if p.yaw_tau_s > 0:
            dt = DT_DEFAULT if t is None or self._t_yaw is None else t - self._t_yaw
            if not 0.0 < dt <= DT_MAX:  # mốc lạ: coi như 1 khung; mất khung lâu: quên góc cũ
                self.yaw_rad, dt = (0.0, DT_DEFAULT) if dt > DT_MAX else (self.yaw_rad, DT_DEFAULT)
            self.yaw_rad = self.yaw_rad * math.exp(-dt / p.yaw_tau_s) + rad
            self._t_yaw = t
        tracks = self.tracks.update(detections, ests, t, ego_shift_rad=rad, box_shift_x=shift,
                                    r_scale=r_scale, allow_new=allow_new)
        if allow_new:  # khung nhoè cho Z sai, không dạy góc cúi từ nó
            self._learn_pitch(detections)

        lane = p.lane_half_m
        by_id: dict[int, tuple[int, bool]] = {}  # id track -> (mức, urgent)
        best, best_tr, urgent = 0, None, False
        for tr in tracks:
            x, z, vx, vz = tr.x.tolist()
            if self.yaw_rad:  # hệ đầu -> hệ thân (bậc 1 theo góc nhỏ)
                x, vx = x - z * self.yaw_rad, vx - vz * self.yaw_rad
            lane_x = lane + p.sigma_k * tr.sigma_x()
            new_near = tr.hits == 1 and tr.misses == 0 and 0 < p.new_near_m and z < p.new_near_m and abs(x) < lane
            if new_near:
                lvl, urg = 3, True
            elif z < p.danger_z_m and abs(x) < lane:
                lvl, urg = 3, False
            else:
                if p.v_conf_k > 0:
                    vx = _confident(vx, tr.P[2, 2], p.v_conf_k)
                    vz = _confident(vz, tr.P[3, 3], p.v_conf_k)
                tte = _tte(x, z, vx, vz, p, lane_x)
                if tte is not None and tte < p.tte_l3_s:
                    lvl = 3
                elif tte is not None and tte < p.tte_l2_s:
                    lvl = 2
                else:
                    lvl = 1 if z < _NEAR_LEVEL1_Z else 0
                urg = False
            by_id[tr.id] = (lvl, urg)
            urgent = urgent or urg
            if lvl > best:
                best, best_tr = lvl, tr
        levels = [by_id[tr.id][0] if tr is not None else 0 for tr in self.tracks.last_matched]
        if len(keep) != n_in:  # trả về đúng độ dài/thứ tự detection gốc
            full = [0] * n_in
            for i, lv in zip(keep, levels):
                full[i] = lv
            levels = full
        if best_tr is None:
            return hazard.Hazard(0, levels=levels)
        x = float(best_tr.x[0] - best_tr.x[1] * self.yaw_rad)
        direction = "left" if x < -lane else "right" if x > lane else "center"
        return hazard.Hazard(best, direction, best_tr.kind, levels, urgent)
