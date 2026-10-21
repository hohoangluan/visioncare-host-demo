"""Làn C (predict): ước lượng khoảng cách và lệch ngang của vật từ MỘT hộp QVGA, camera đơn, không IMU.

Hai nguồn độc lập, gộp theo nghịch đảo phương sai khi cả hai hợp lệ:
- height: Z = f·H/h_px với H = chiều cao điển hình của lớp (sai số tương đối theo lớp);
- ground: đáy hộp chạm mặt đất, Z = cam_h·f / (y_đáy − cy + f·tan(cúi)) — không cần biết lớp.
Hộp chạm mép ảnh thì nguồn đó mất tin cậy. Đáy chạm mép dưới (camera cao 1,6 m chỉ thấy đất từ ~3,3 m) thì KHÔNG có
Z từ một khung: `estimate` trả source="clipped", z_m=NaN; TrackSet lấy Z = Z_track_trước · w_trước / w_nay (bề rộng
không bị mép dưới cắt), track mới thì dùng `z_width` từ bảng bề rộng lớp.

Toạ độ: X ngang (dương = bên phải), Z phía trước, mét, gốc là camera.
"""

import math
from dataclasses import dataclass
from functools import cached_property

import config
from live import hazard

# Chiều cao điển hình (m) của từng `kind` (COCO của hazard._CLASSES + evaluations/train/classes_vh.json).
CLASS_HEIGHT_M: dict[str, float] = {
    "person": 1.65,               # người lớn Việt Nam đứng
    "dog": 0.5,                   # chó cỡ trung, tới vai
    "bicycle": 1.1,               # xe đạp có người ngồi nhìn từ sau/trước: tới đầu
    "motorbike": 1.2,             # xe máy tính cả người ngồi (đa số ảnh có người lái)
    "tricycle": 1.3,              # xe ba bánh/xích lô: mái che thấp
    "car": 1.5,                   # sedan/SUV nhỏ, bỏ qua xe cao
    "bus": 3.0,                   # xe buýt/khách
    "truck": 3.0,                 # xe tải
    "pole": 1.0,                  # cột bị khung cắt thường xuyên -> chiều cao không đáng tin (σ lớn)
    "warning_column": 1.0,        # trụ cảnh báo, cao 0,6-1,2 m tuỳ loại (σ lớn)
    "reflective_cone": 0.7,       # cọc tiêu giao thông chuẩn 70 cm
    "spherical_roadblock": 0.6,   # bi chặn xe hình cầu trước vỉa hè
    "ashcan": 0.9,                # thùng rác công cộng
    "bench": 0.45,                # ghế đá: tính mặt ghế (lưng ghế bị che/cắt)
    "chair": 0.85,                # ghế có lưng
    "plant": 0.8,                 # chậu cây ven đường (σ lớn: kích thước rất khác nhau)
    "hydrant": 0.7,               # trụ cứu hoả (nhãn COCO)
    "fire_hydrant": 0.7,          # trụ cứu hoả (nhãn classes_vh)
    "stop_sign": 2.2,             # biển báo treo trên cột: tính tới đỉnh biển
    "traffic_light": 3.0,         # đèn giao thông trên trụ
    "parking_meter": 1.2,         # cột thu phí đỗ xe
}

# Lớp KHÔNG có chiều cao điển hình (cột phố cao ~1-8 m): không cho Z theo chiều cao, chỉ mặt đất + tỉ lệ bề rộng.
NO_HEIGHT_KINDS = frozenset({"pole", "warning_column", "traffic_light", "stop_sign", "plant", "parking_meter"})

# Bề rộng điển hình (m) của từng `kind`, chỉ để định Z cho track MỚI có đáy hộp bị cắt (σ = 0,4·Z).
CLASS_WIDTH_M: dict[str, float] = {
    "person": 0.5,                # vai người lớn nhìn thẳng
    "dog": 0.35,                  # chó cỡ trung nhìn trước/sau
    "bicycle": 0.6,               # xe đạp nhìn trước/sau: tay lái + người
    "motorbike": 0.8,             # xe máy nhìn trước/sau tính cả người ngồi
    "tricycle": 1.1,              # xe ba bánh/xích lô
    "car": 1.8,                   # thân xe con
    "bus": 2.5,                   # xe buýt/khách
    "truck": 2.4,                 # xe tải
    "pole": 0.15,                 # cột đèn/cột điện đường kính ~15 cm
    "warning_column": 0.2,        # trụ cảnh báo
    "reflective_cone": 0.3,       # đế cọc tiêu
    "spherical_roadblock": 0.5,   # bi chặn đường kính ~50 cm
    "ashcan": 0.5,                # thùng rác công cộng
    "bench": 1.5,                 # ghế đá dài
    "chair": 0.5,                 # ghế có lưng
    "plant": 0.6,                 # chậu cây
    "hydrant": 0.3,               # trụ cứu hoả (nhãn COCO)
    "fire_hydrant": 0.3,          # trụ cứu hoả (nhãn classes_vh)
    "stop_sign": 0.75,            # biển báo tròn/bát giác
    "traffic_light": 0.4,         # hộp đèn giao thông
    "parking_meter": 0.25,        # cột thu phí đỗ xe
}
_UNKNOWN_W = 0.5      # lớp ngoài bảng bề rộng

# Sai số tương đối của chiều cao lớp. Mặc định 0,15; cột/cây/biển có kích thước rất khác nhau nên 0,5.
CLASS_HEIGHT_REL_SIGMA: dict[str, float] = {
    "pole": 0.5, "warning_column": 0.5, "plant": 0.5, "stop_sign": 0.5, "traffic_light": 0.5,
}
_REL_SIGMA_DEFAULT = 0.15
_EDGE = 0.01          # cạnh hộp cách mép ảnh <= mức này (tỉ lệ) coi như bị cắt
_CLIP_Z_MARGIN = 1.15  # chừa 15% sai số độ cao camera/góc cúi khi chặn Z của hộp cắt đáy
_WIDTH_REL = 0.4     # σ_Z của Z theo bề rộng danh nghĩa
_PITCH_MIN_Z = 3.0    # mẫu góc cúi chỉ lấy khi Z theo chiều cao >= mức này (gần quá thì sai số lớp phóng đại)
_GROUND_REL = 0.03    # σ_Z = Z²·0,03/cam_h (≈ ±4 px sai số đáy hộp ở QVGA)
_GROUND_MIN_PX = 2.0  # đáy phải nằm dưới đường chân trời ít nhất ngần này px
_Z_MAX = 60.0
_LAT_VAR = 4.0        # hộp chạm mép bên: phương sai X ×4 (cạnh trong + bề rộng lớp kém tin hơn tâm)
_LAT_VAR_BOTH = 25.0  # cắt cả hai bên: vật choán hết bề ngang, X = 0 với phương sai rất lớn
_UNKNOWN_H = 1.0      # lớp ngoài bảng: chỉ dùng khi phải rơi về nguồn width


@dataclass(frozen=True)
class Camera:
    """Camera danh nghĩa: ảnh w×h, góc nhìn ngang, độ cao so với mặt đất."""

    w: int
    h: int
    hfov_deg: float
    height_m: float

    @cached_property  # gọi mỗi detection mỗi khung: tính một lần
    def f_px(self) -> float:
        return (self.w / 2) / math.tan(math.radians(self.hfov_deg / 2))

    @staticmethod
    def default() -> "Camera":
        return Camera(320, 240, config.HAZARD_CAM_HFOV_DEG, config.HAZARD_CAM_HEIGHT_M)


@dataclass
class Estimate:
    z_m: float
    x_m: float
    z_sigma: float
    source: str  # "height" | "ground" | "fused" | "width" | "clipped"
    # "clipped" (đáy hộp chạm mép dưới): z_m = x_m = z_sigma = NaN, "Z cần track". `bearing` = X/Z (tan góc ngang),
    # `z_width` = Z theo bề rộng danh nghĩa của lớp (dùng khi track mới, σ = 0,4·Z).
    bearing: float = 0.0
    z_width: float = math.nan
    # Hộp chạm mép trái/phải: tâm hộp sai (vật bị cắt). X lấy từ CẠNH TRONG: X = lat_bearing·Z + lat_off_m
    # (lat_off_m = ∓ nửa bề rộng lớp); phương sai X nhân x_var_scale. lat_bearing = NaN: hộp không bị cắt ngang.
    lat_bearing: float = math.nan
    lat_off_m: float = 0.0
    x_var_scale: float = 1.0
    z_max: float = math.nan


def _height_z(det: hazard.Detection, cam: Camera, h_px: float) -> tuple[float, float] | None:
    """(Z, σ) theo chiều cao lớp; None nếu lớp lạ hoặc hộp bị cắt trên/dưới."""
    H = CLASS_HEIGHT_M.get(det.kind)
    if H is None or det.kind in NO_HEIGHT_KINDS or det.box[1] <= _EDGE or det.box[3] >= 1 - _EDGE or h_px <= 1.0:
        return None
    z = cam.f_px * H / h_px
    return z, CLASS_HEIGHT_REL_SIGMA.get(det.kind, _REL_SIGMA_DEFAULT) * z


def _ground_z(cam: Camera, y_bot: float, pitch_rad: float) -> tuple[float, float] | None:
    """(Z, σ) theo đáy hộp chạm đất; None nếu đáy chạm mép dưới hoặc chưa dưới đường chân trời."""
    if y_bot >= cam.h * (1 - _EDGE):
        return None
    d = y_bot - cam.h / 2 + cam.f_px * math.tan(pitch_rad)
    if d < _GROUND_MIN_PX:
        return None
    z = min(cam.height_m * cam.f_px / d, _Z_MAX)
    return z, z * z * _GROUND_REL / cam.height_m


def _lateral(det: hazard.Detection, cam: Camera) -> tuple[float, float, float]:
    """(lat_bearing, lat_off_m, x_var_scale) theo cạnh trong khi hộp chạm mép trái/phải; NaN nếu không chạm."""
    x0, _, x1, _ = det.box
    left, right = x0 <= _EDGE, x1 >= 1 - _EDGE
    half = CLASS_WIDTH_M.get(det.kind, _UNKNOWN_W) / 2
    if left and right:
        return 0.0, 0.0, _LAT_VAR_BOTH
    if right:  # thấy cạnh trái của vật; tâm = cạnh trái + nửa bề rộng (ra phía ngoài = bên phải)
        return (x0 * cam.w - cam.w / 2) / cam.f_px, half, _LAT_VAR
    if left:
        return (x1 * cam.w - cam.w / 2) / cam.f_px, -half, _LAT_VAR
    return math.nan, 0.0, 1.0


def estimate(det: hazard.Detection, cam: Camera, pitch_rad: float = 0.0) -> Estimate:
    """Hộp -> (Z, X, σ_Z). `pitch_rad` > 0 = ảnh trượt lên (camera ngẩng); chỉ nguồn ground phụ thuộc nó."""
    x0, y0, x1, y1 = det.box
    y_top, y_bot = y0 * cam.h, y1 * cam.h
    cx_px = (x0 + x1) / 2 * cam.w
    height = _height_z(det, cam, y_bot - y_top)
    ground = _ground_z(cam, y_bot, pitch_rad)
    if height and ground:
        wh, wg = 1 / height[1] ** 2, 1 / ground[1] ** 2
        z, sigma, source = (height[0] * wh + ground[0] * wg) / (wh + wg), (wh + wg) ** -0.5, "fused"
    elif height:
        (z, sigma), source = height, "height"
    elif ground:
        (z, sigma), source = ground, "ground"
    elif y_bot >= cam.h * (1 - _EDGE):
        w_px = max((x1 - x0) * cam.w, 1.0)
        zw = min(cam.f_px * CLASS_WIDTH_M.get(det.kind, _UNKNOWN_W) / w_px, _Z_MAX)
        # Đáy bị cắt => chân vật dưới hàng ảnh cuối => vật gần hơn mặt đất thấy được gần nhất (pitch đã kẹp ±0,1 rad nên d > 0)
        d = cam.h / 2 + cam.f_px * math.tan(pitch_rad)
        z_max = cam.height_m * cam.f_px / d * _CLIP_Z_MARGIN
        zw = min(zw, z_max)
        bearing = (cx_px - cam.w / 2) / cam.f_px
        lb, lo, lv = _lateral(det, cam)
        return Estimate(math.nan, math.nan, math.nan, "clipped", bearing, zw, lb, lo, lv, z_max)
    else:  # không nguồn nào hợp lệ (vd. đáy trên đường chân trời, lớp lạ): dùng bề rộng, rộng chuẩn = 0,5·H
        w_px = max((x1 - x0) * cam.w, 1.0)
        w_m = CLASS_WIDTH_M.get(det.kind, _UNKNOWN_W) if det.kind in NO_HEIGHT_KINDS else 0.5 * CLASS_HEIGHT_M.get(det.kind, _UNKNOWN_H)
        z = min(cam.f_px * w_m / w_px, _Z_MAX)
        sigma, source = z * _WIDTH_REL, "width"
    lb, lo, lv = _lateral(det, cam)
    x = (cx_px - cam.w / 2) * z / cam.f_px if math.isnan(lb) else lb * z + lo
    return Estimate(z, x, sigma, source, (cx_px - cam.w / 2) / cam.f_px, math.nan, lb, lo, lv)


def pitch_sample(det: hazard.Detection, cam: Camera) -> float | None:
    """Một mẫu góc cúi (rad) khi hộp có cả nguồn height lẫn ground: tìm góc làm hai Z khớp nhau.

    Z_height không phụ thuộc góc, nên tan(p) = cam_h/Z_h − (y_đáy − cy)/f. Chỉ lấy lớp có σ chiều cao nhỏ
    và Z_h đủ xa; còn lại None.
    """
    if CLASS_HEIGHT_REL_SIGMA.get(det.kind, _REL_SIGMA_DEFAULT) > _REL_SIGMA_DEFAULT:
        return None
    y_bot = det.box[3] * cam.h
    height = _height_z(det, cam, (det.box[3] - det.box[1]) * cam.h)
    if height is None or height[0] < _PITCH_MIN_Z or y_bot >= cam.h * (1 - _EDGE):
        return None
    return math.atan(cam.height_m / height[0] - (y_bot - cam.h / 2) / cam.f_px)
