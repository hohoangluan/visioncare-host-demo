"""Làn C (predict): đo chuyển động của chính camera giữa hai khung (quay đầu) và độ nhoè, không IMU.

Ảnh xám thu về 80×60, `cv2.phaseCorrelate` với khung trước cho độ trượt ngang của cả cảnh. Quay đầu làm mọi vật trượt
cùng một lượng; không bù thì vật đứng yên bị đọc thành đang đi ngang. Rẻ (< 1 ms), chạy trên khung QVGA đã giải mã.
"""

from dataclasses import dataclass

import cv2
import numpy as np

_W, _H = 80, 60
_MAX_SHIFT = 0.25      # tỉ lệ bề rộng; trượt lớn hơn là nhiễu hoặc cảnh đổi hẳn, không tin
_MIN_RESPONSE = 0.05   # độ tin cậy phaseCorrelate: dưới mức này (ảnh trống/tối) coi như không trượt


@dataclass(frozen=True)
class Ego:
    shift_x: float  # tỉ lệ bề rộng ảnh, dương = cảnh trượt sang phải
    blur: float     # phương sai Laplacian: càng thấp càng nhoè


class EgoMeter:
    def __init__(self) -> None:
        self._prev: np.ndarray | None = None
        self._window = cv2.createHanningWindow((_W, _H), cv2.CV_32F)  # bỏ hiệu ứng biên khi tương quan pha

    def measure(self, bgr: np.ndarray) -> Ego:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blur = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        small = cv2.resize(gray, (_W, _H), interpolation=cv2.INTER_AREA).astype(np.float32)
        shift = 0.0
        if self._prev is not None:
            (dx, _), response = cv2.phaseCorrelate(self._prev, small, self._window)
            if response >= _MIN_RESPONSE and abs(dx) / _W <= _MAX_SHIFT:
                shift = dx / _W
        self._prev = small
        return Ego(shift, blur)
