"""Làn C: hazard detector + luật mức + chống làm phiền (§11).

Detector: YOLO nano COCO xuất ONNX (`tools/export_hazard_onnx.py`), chạy bằng
onnxruntime-gpu (CUDA), CPU dự phòng (`models/onnx_session.py`). Không kéo torch
vào runtime.

Mức: 0 Safe (không gửi) · 1 Danger · 2 High Danger · 3 Critical.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

import cv2
import numpy as np

import config

logger = logging.getLogger("blind_assist")

# COCO id -> (tên gửi kính, nhóm). Nhóm quyết trọng số: xe > người > vật tĩnh.
_CLASSES = {
    0: ("person", "person"),
    1: ("bicycle", "vehicle"),
    2: ("car", "vehicle"),
    3: ("motorbike", "vehicle"),
    5: ("bus", "vehicle"),
    7: ("truck", "vehicle"),
    16: ("dog", "person"),
    9: ("traffic_light", "static"),
    10: ("hydrant", "static"),
    11: ("stop_sign", "static"),
    12: ("parking_meter", "static"),
    13: ("bench", "static"),
    56: ("chair", "static"),
    58: ("plant", "static"),
}


def _load_classes(path: str) -> dict[int, tuple[str, str]]:
    """Bảng lớp của model fine-tune: file JSON {id: [kind, nhóm]} (evaluations/train/classes_vh.json)."""
    with open(path, encoding="utf-8") as f:
        return {int(i): (kind, group) for i, (kind, group) in json.load(f).items()}


if config.HAZARD_CLASSES_JSON:  # trống = COCO ở trên; có giá trị = bảng của model fine-tune
    _CLASSES = _load_classes(config.HAZARD_CLASSES_JSON)


@dataclass
class Detection:
    kind: str
    group: str
    score: float
    box: tuple[float, float, float, float]  # tỉ lệ [0,1]: x0, y0, x1, y1

    @property
    def area(self) -> float:
        return max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1])

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2


class OnnxYolo:
    """YOLOv8/11 ONNX của ultralytics: output (1, 4+80, N), chưa NMS."""

    def __init__(self, path: str, imgsz: int) -> None:
        from models import onnx_session

        self._sess = onnx_session.session(path, config.HAZARD_NUM_THREADS)
        self._input = self._sess.get_inputs()[0].name
        self.imgsz = imgsz
        self.provider = self._sess.get_providers()[0]

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        h, w = bgr.shape[:2]
        s = self.imgsz
        r = min(s / w, s / h)
        nw, nh = int(round(w * r)), int(round(h * r))
        canvas = np.full((s, s, 3), 114, dtype=np.uint8)
        top, left = (s - nh) // 2, (s - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = self._sess.run(None, {self._input: blob})[0][0].T  # (N, 84)

        scores = out[:, 4:]
        cls = scores.argmax(axis=1)
        conf = scores[np.arange(len(cls)), cls]
        keep = (conf >= config.HAZARD_MIN_SCORE) & np.isin(cls, list(_CLASSES))
        if not keep.any():
            return []
        boxes, conf, cls = out[keep, :4], conf[keep], cls[keep]
        xywh = [[float(cx - bw / 2), float(cy - bh / 2), float(bw), float(bh)] for cx, cy, bw, bh in boxes]
        idx = cv2.dnn.NMSBoxes(xywh, conf.tolist(), config.HAZARD_MIN_SCORE, 0.45)
        result = []
        for i in np.array(idx).reshape(-1):
            x, y, bw, bh = xywh[i]
            x0 = (x - left) / r / w; y0 = (y - top) / r / h
            x1 = (x + bw - left) / r / w; y1 = (y + bh - top) / r / h
            kind, group = _CLASSES[int(cls[i])]
            result.append(Detection(kind, group, float(conf[i]), (
                min(max(x0, 0.0), 1.0), min(max(y0, 0.0), 1.0),
                min(max(x1, 0.0), 1.0), min(max(y1, 0.0), 1.0),
            )))
        return result


@lru_cache(maxsize=1)
def detector() -> OnnxYolo | None:
    path = config.HAZARD_MODEL_PATH
    if not path or not os.path.exists(path):
        logger.warning("Không có hazard model (%s): làn C chạy không có detector", path)
        return None
    det = OnnxYolo(path, config.HAZARD_IMGSZ)
    for _ in range(3):  # warm-up: cuDNN dò thuật toán conv ở lượt đầu
        det.detect(np.zeros((240, 320, 3), dtype=np.uint8))
    logger.info("Hazard model %s trên %s", os.path.basename(path), det.provider)
    return det


def direction(cx: float) -> str:
    if cx < 1 / 3:
        return "left"
    if cx > 2 / 3:
        return "right"
    return "center"


def level_of(det: Detection, approaching: bool) -> int:
    """Luật mức bản đầu (chỉnh ở P3): lớp vật, diện tích hộp, vị trí, đang tới gần."""
    in_path = 0.3 <= det.cx <= 0.7
    a = det.area
    vehicle, person = det.group == "vehicle", det.group == "person"
    if in_path and (a > 0.35 or (vehicle and (a > 0.15 or (approaching and a > 0.08)))):
        return 3
    if in_path and ((vehicle and a > 0.04) or (person and a > 0.08) or a > 0.10):
        return 2
    if vehicle and approaching and a > 0.05:
        return 2
    if a > 0.02:
        return 1
    return 0


@dataclass
class Hazard:
    level: int
    dir: str = "center"
    kind: str = ""
    # Mức từng detection (cùng thứ tự đầu vào của `assess`), chỉ để hiện debug; không tham gia so sánh.
    levels: list[int] = field(default_factory=list, compare=False, repr=False)
    # Vật mới hiện đã sát người (HAZARD_LOGIC=predict): AntiAnnoy gửi mức 3 ngay, không chờ phiếu. Không tham gia so sánh.
    urgent: bool = field(default=False, compare=False)


class HazardTracker:
    """Từ danh sách detection mỗi khung -> mức nguy hiểm cao nhất của khung."""

    def __init__(self) -> None:
        self._prev: dict[tuple[str, str], float] = {}  # (kind, dir) -> diện tích khung trước

    def assess(self, detections: list[Detection], t: float | None = None, ego=None) -> Hazard:
        """`t` (mốc thời gian) và `ego` (chuyển động đầu) chỉ dành cho PredictTracker; luật diện tích bỏ qua."""
        best = Hazard(0)
        current: dict[tuple[str, str], float] = {}
        levels: list[int] = []
        for det in detections:
            key = (det.kind, direction(det.cx))
            prev = self._prev.get(key)
            approaching = prev is not None and det.area > prev * 1.15  # hộp lớn dần
            current[key] = max(current.get(key, 0.0), det.area)
            lvl = level_of(det, approaching)
            levels.append(lvl)
            if lvl > best.level:
                best = Hazard(lvl, key[1], det.kind)
        self._prev = current
        best.levels = levels
        return best


class AntiAnnoy:
    """Chống làm phiền (§11):
    - chỉ gửi khi mức TĂNG, hoặc nhắc lại mỗi 2 s khi mức >= 2;
    - mức phải giữ 2 khung liên tiếp mới gửi (trừ level 3: gửi ngay);
    - level 1 tối đa 1 lần / 5 s.

    Hai nút cho HAZARD_LOGIC=predict (mặc định giữ nguyên hành vi trên):
    - `l3_vote` = n: mức 3 chỉ gửi khi >= n trong 3 khung gần nhất là 3 (trừ `urgent` khi `bypass_vote`);
      chưa đủ phiếu thì xử lý như mức 2;
    - `down_hold` = n: `current` chỉ hạ khi mức thấp hơn giữ n khung liên tiếp (luật 2 khung ở trên đã là n = 2).
    """

    def __init__(self, clock=time.monotonic, l3_vote: int = 1, down_hold: int = 1, bypass_vote: bool = True,
                 release_s: float = 0.0) -> None:
        self._clock = clock
        self.l3_vote, self.down_hold, self.bypass_vote = l3_vote, down_hold, bypass_vote
        self.release_s = release_s
        self._low = 0                       # số khung liên tiếp có mức < 2
        self._rel_until: float | None = None  # đang nhả: tới mốc này thì dừng hẳn
        self._muted = False                 # đã nhả xong: im tới khi có mức >= 2
        self._recent: list[int] = []  # mức thô của 3 khung gần nhất
        self._frame_level = -1
        self._streak = 0
        self.current = 0
        self._last_sent = -1e9
        self._last_l1 = -1e9

    def step(self, level: int, urgent: bool = False) -> bool:
        now = self._clock()
        self._recent = (self._recent + [level])[-3:]
        if level == 3 and self.l3_vote > 1 and not (urgent and self.bypass_vote):
            if self._recent.count(3) < self.l3_vote:
                level = 2  # chưa đủ phiếu: chưa dám kêu mức 3
        if self.release_s > 0:
            done = self._release(level, now)
            if done is not None:
                return done
        if level == self._frame_level:
            self._streak += 1
        else:
            self._frame_level, self._streak = level, 1
        if not (level == 3 or self._streak >= 2):
            return False
        if level == 0:
            self.current = 0
            return False
        if level > self.current:
            if level == 1 and now - self._last_l1 < config.HAZARD_LEVEL1_GAP_S:
                self.current = 1
                return False
            self._send(level, now)
            return True
        if level >= 2 and level == self.current and now - self._last_sent >= config.HAZARD_REPEAT_S:
            self._send(level, now)
            return True
        if level < self.current and self._streak >= self.down_hold:
            self.current = level
        return False

    def _release(self, level: int, now: float) -> bool | None:
        """Đuôi nhả (release_s > 0): hết dấu hiệu nguy hiểm (mức < 2 giữ `down_hold` khung) thì kêu thêm release_s giây
        như mức cũ vẫn còn (một lần nhắc đến hạn vẫn gửi), rồi dừng hẳn, không nhắc 2 s nữa, tới khi có mức >= 2.
        Trả bool khi đã xử lý xong khung này, None khi để luồng thường chạy."""
        if level >= 2:
            self._low, self._rel_until, self._muted = 0, None, False  # nguy hiểm quay lại: huỷ nhả
            return None
        self._low += 1
        if self._muted:
            return False
        if self.current >= 2 and self._low >= self.down_hold:
            if self._rel_until is None:
                self._rel_until = now + self.release_s
            if now >= self._rel_until:
                self.current, self._rel_until, self._muted = 0, None, True
                return False
            if now - self._last_sent >= config.HAZARD_REPEAT_S:
                self._send(self.current, now)
                return True
            return False
        return None

    def _send(self, level: int, now: float) -> None:
        self.current, self._last_sent = level, now
        if level == 1:
            self._last_l1 = now


_warned_logic = False


def _logic() -> str:
    """HAZARD_LOGIC hợp lệ ("area"/"predict"); giá trị lạ -> cảnh báo một lần và chạy area."""
    global _warned_logic
    v = config.HAZARD_LOGIC
    if v in ("area", "predict"):
        return v
    if not _warned_logic:
        _warned_logic = True
        logger.warning("HAZARD_LOGIC=%r không hợp lệ (area|predict); chạy area", v)
    return "area"


def make_tracker():
    """HazardTracker (luật diện tích, mặc định) hoặc PredictTracker (HAZARD_LOGIC=predict)."""
    if _logic() == "predict":
        from live import hazard_predict
        return hazard_predict.PredictTracker(hazard_predict.PredictParams.from_config())
    return HazardTracker()


def make_anti(clock=time.monotonic) -> AntiAnnoy:
    """AntiAnnoy theo HAZARD_LOGIC: predict thì bật phiếu mức 3 và giữ khi hạ; area giữ y hệt bản cũ."""
    if _logic() == "predict":
        return AntiAnnoy(clock, l3_vote=config.HAZARD_L3_VOTE, down_hold=config.HAZARD_DOWN_HOLD,
                         bypass_vote=config.HAZARD_NEW_BYPASS_VOTE == "1", release_s=config.HAZARD_RELEASE_S)
    return AntiAnnoy(clock)
