"""Làn B: text detector + luật căn khung (§10).

Vòng căn khung chạy MỖI KHUNG nên không bao giờ gọi model lớn: chỉ dò hộp chữ
(PP-OCRv4 det mobile trên onnxruntime-gpu; thiếu file model thì bộ dò hình
thái OpenCV vài ms trên CPU), rồi luật thuần tính ra một cue hoặc lệnh chụp.

Hướng `look_*` là hướng QUAY ĐẦU: hộp chữ chạm mép trái nghĩa là chữ còn tràn
ra ngoài bên trái -> quay sang trái.
"""

import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

import config

logger = logging.getLogger("blind_assist")

Box = tuple[int, int, int, int]  # x0, y0, x1, y1

_EDGE_MARGIN = 0.02  # hộp cách mép dưới 2% khung = chạm mép
_OVERFLOW_FILL = 0.9  # chữ phủ > 90% cả hai chiều = tràn khung


def decode_gray(jpeg: bytes, max_side: int = 800) -> tuple[np.ndarray, int] | None:
    """JPEG -> (ảnh xám đã thu nhỏ, chiều rộng GỐC). Giải mã thẳng ở 1/2, 1/4."""
    buf = np.frombuffer(jpeg, dtype=np.uint8)
    full = cv2.imdecode(buf, cv2.IMREAD_REDUCED_GRAYSCALE_2)
    if full is None:
        return None
    width = full.shape[1] * 2
    if width <= max_side:
        full = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    while full.shape[1] > max_side:
        full = cv2.resize(full, (full.shape[1] // 2, full.shape[0] // 2), interpolation=cv2.INTER_AREA)
    return full, width


class MorphDetector:
    """Dò vùng chữ cổ điển: gradient hình thái -> Otsu -> nối ngang -> contour."""

    name = "morph"

    def detect(self, gray: np.ndarray) -> list[Box]:
        h, w = gray.shape
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        kw = max(9, w // 40)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1)))
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            x, y, bw_, bh = cv2.boundingRect(c)
            if bh < 5 or bw_ < 2 * bh or bh > h * 0.3:
                continue  # không giống một dòng chữ
            if cv2.contourArea(c) < 0.35 * bw_ * bh:
                continue
            boxes.append((x, y, x + bw_, y + bh))
        return boxes


class PPOCRDetector:
    """PP-OCRv4 det mobile (DB) qua onnxruntime-gpu — hộp theo từng dòng chữ.

    Tự hậu xử lý DB (ngưỡng bản đồ xác suất -> contour -> nở hộp) thay vì dùng
    gói rapidocr: gói đó kéo `onnxruntime` CPU, đè mất `onnxruntime-gpu`.
    """

    name = "ppocr-det"
    _MEAN = np.array([0.485, 0.456, 0.406], np.float32) * 255
    _STD = np.array([0.229, 0.224, 0.225], np.float32) * 255

    def __init__(self, path: str) -> None:
        from models import onnx_session

        self._sess = onnx_session.session(path, threads=4)
        self._input = self._sess.get_inputs()[0].name
        self.provider = self._sess.get_providers()[0]

    def detect(self, gray: np.ndarray) -> list[Box]:
        h, w = gray.shape
        # Cạnh là bội của 32 (yêu cầu của mạng DB); khung VGA giữ gần nguyên cỡ.
        nh, nw = max(32, int(round(h / 32)) * 32), max(32, int(round(w / 32)) * 32)
        img = cv2.resize(gray, (nw, nh)) if (nh, nw) != (h, w) else gray
        rgb = np.repeat(img[:, :, None], 3, axis=2).astype(np.float32)
        blob = ((rgb - self._MEAN) / self._STD).transpose(2, 0, 1)[None]
        prob = self._sess.run(None, {self._input: blob})[0][0, 0]
        mask = (prob > 0.3).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        sx, sy = w / nw, h / nh
        boxes = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            if bh < 3 or bw < 3 or float(prob[y:y + bh, x:x + bw].mean()) < 0.5:
                continue
            # DB co vùng chữ lại khi huấn luyện; nở ra ~ (unclip 1.5) để ra hộp dòng thật.
            pad = int(round(bh * 0.4))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(nw, x + bw + pad), min(nh, y + bh + pad)
            boxes.append((int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)))
        return boxes


@lru_cache(maxsize=1)
def detector():
    path = config.TEXT_DET_MODEL_PATH
    if config.TEXT_DETECTOR in ("auto", "ppocr") and path and os.path.exists(path):
        det = PPOCRDetector(path)
        for _ in range(3):  # warm-up: cuDNN dò thuật toán conv ở lượt đầu
            det.detect(np.zeros((480, 640), np.uint8))
        logger.info("Text detector: PP-OCR det trên %s", det.provider)
        return det
    if config.TEXT_DETECTOR == "ppocr":
        raise FileNotFoundError(path)
    logger.info("Không có PP-OCR det (%s) -> dùng bộ dò hình thái", path)
    return MorphDetector()


def sharpness(gray: np.ndarray, boxes: list[Box]) -> float:
    """Độ nét CHỈ trong vùng chữ (Laplacian trên cả ảnh vô dụng với camera này)."""
    if not boxes:
        return 0.0
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0
    return float(cv2.Laplacian(roi, cv2.CV_64F).var())


def assess(boxes: list[Box], frame_w: int, frame_h: int, scale_to_capture: float) -> str | None:
    """Vấn đề căn khung (id cue), hoặc `None` nếu khung đã đạt. Không xét độ nét.

    `scale_to_capture`: nhân chiều cao dòng trên khung này ra pixel trên ảnh
    chụp UXGA — ngưỡng tính bằng pixel ảnh chụp, đổi camera không đổi ngưỡng.
    """
    if not boxes:
        return "look_around"
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
    mx, my = frame_w * _EDGE_MARGIN, frame_h * _EDGE_MARGIN
    left, right = x0 <= mx, x1 >= frame_w - mx
    top, bottom = y0 <= my, y1 >= frame_h - my

    if (left and right and (x1 - x0) >= frame_w * _OVERFLOW_FILL) and (top or bottom):
        return "move_away"
    if left and right and top and bottom:
        return "move_away"
    if left and not right:
        return "look_left"
    if right and not left:
        return "look_right"
    if top and not bottom:
        return "look_up"
    if bottom and not top:
        return "look_down"

    heights = sorted(b[3] - b[1] for b in boxes)
    line_px = heights[len(heights) // 2] * scale_to_capture
    if line_px < config.OCR_MIN_LINE_PX:
        return "move_closer"
    return None


def assess_jpeg(jpeg: bytes) -> tuple[str | None, list[Box]]:
    """Một ảnh (vd. ảnh buffer UXGA) -> (vấn đề, hộp). Dùng cho đường đọc ngay."""
    decoded = decode_gray(jpeg)
    if decoded is None:
        return "look_around", []
    gray, width = decoded
    boxes = detector().detect(gray)
    h, w = gray.shape
    return assess(boxes, w, h, config.OCR_CAPTURE_WIDTH / w), boxes


@dataclass
class Action:
    kind: str  # "cue" | "capture"
    cue: str = ""


class Aligner:
    """Trạng thái căn khung của MỘT phiên: chống nói dồn, đếm khung đạt."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._last_problem: str | None = None
        self._streak = 0
        self._good = 0
        self._last_cue_at = -1e9
        self._last_look_around_at = -1e9
        self._best_sharpness = 0.0

    def step_gray(self, gray: np.ndarray, boxes: list[Box]) -> Action | None:
        h, w = gray.shape
        problem = assess(boxes, w, h, config.OCR_CAPTURE_WIDTH / w)
        if problem is None:
            sharp = sharpness(gray, boxes)
            self._best_sharpness = max(self._best_sharpness, sharp)
            # Mờ chỉ so tương đối trong phiên: dưới nửa khung nét nhất đã thấy.
            if sharp < 0.5 * self._best_sharpness:
                problem = "hold_still"
        return self._decide(problem)

    def _decide(self, problem: str | None) -> Action | None:
        now = self._clock()
        if problem is None:
            self._good += 1
            self._last_problem, self._streak = None, 0
            if self._good >= config.OCR_GOOD_FRAMES:
                return Action("capture")
            return None

        self._good = 0
        if problem == self._last_problem:
            self._streak += 1
        else:
            self._last_problem, self._streak = problem, 1
        if self._streak < 2:  # một vấn đề phải lặp 2 khung mới nói
            return None
        if now - self._last_cue_at < config.OCR_CUE_MIN_GAP_S:
            return None
        if problem == "look_around":
            if now - self._last_look_around_at < config.OCR_LOOK_AROUND_GAP_S:
                return None
            self._last_look_around_at = now
        self._last_cue_at = now
        return Action("cue", problem)
