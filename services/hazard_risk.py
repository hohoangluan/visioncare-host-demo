"""T24/W4 — máy chấm mức nguy hiểm cho `hazard_watch`.

Thiết kế tham khảo `github.com/LuanLuKim/OD_module`: giữ phần suy luận
(corridor / proximity / approach + hysteresis), đổi phần vận chuyển (không
tách microservice, không UDP) và cách phát cảnh báo (tông cục bộ trên board,
không TTS) cho khớp ràng buộc thật của hệ này.

Bốn quyết định, mỗi cái trả giá cho một cách hỏng
-------------------------------------------------

1. **Detector là một giao diện cắm được, không phải `import onnxruntime`.**
   Máy này chưa có file YOLO11n nào (`models/` không có thư mục `od/`). Viết
   thẳng vào ONNX nghĩa là toàn bộ luật chấm điểm bên dưới **không test được**
   cho tới ngày ai đó tải model về. Tách ra thì luật chấm điểm — phần dễ sai
   nhất — có test chạy mọi lần.

2. **Fail-closed: không có detector thì `hazard_watch` KHÔNG bật.**
   Một chế độ cảnh báo vật cản im lặng còn tệ hơn không có chế độ đó: người
   dùng tin nó đang canh và đi nhanh hơn. Xem `HazardWatchUnavailable`.

3. **Ba tầng LOW/MEDIUM/HIGH chứ không hai** (khác OD_module gốc) để khớp
   tông tăng dần của W6. Ngưỡng cắt dưới đây là **điểm khởi đầu suy ra từ
   ngưỡng gốc 0.70/0.55, CHƯA ĐO trên dữ liệu thật** — AGENT_RULES mục A9.

4. **Hysteresis bất đối xứng: tăng mức phát NGAY, giảm mức phải đợi.**
   Vật cản thì lên mức ngay (chậm một nhịp là vấp), nhưng hạ mức phải trễ —
   không thì một khung hình trượt detector làm tiếng cảnh báo tắt phụt giữa
   lúc người dùng đang bước tới đúng cái cột đó.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
import threading
import time

import config


class HazardWatchUnavailable(RuntimeError):
    """Không có detector nên không bật canh vật cản được.

    Ném ra thay vì trả về SAFE: SAFE nghĩa là "đã nhìn và thấy an toàn", còn
    đây là "chưa nhìn được". Trộn hai thứ đó là hứa với người dùng một thứ
    không tồn tại.
    """


@dataclass(frozen=True)
class Box:
    """Một vật phát hiện được, toạ độ CHUẨN HOÁ về [0, 1] theo khung hình.

    Chuẩn hoá ở biên của detector chứ không ở đây: luật chấm điểm bên dưới
    không được biết khung hình bao nhiêu pixel, nếu không thì đổi độ phân giải
    camera (F5 phân tầng ảnh) là mọi ngưỡng lệch hết mà không ai để ý.
    """

    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def bottom(self) -> float:
        return self.y2


class Detector(Protocol):
    """Bất cứ thứ gì biến một khung JPEG thành danh sách `Box`."""

    def detect(self, jpeg: bytes) -> list[Box]: ...


# ─── ba máy chấm điểm, giữ nguyên từ OD_module ────────────────────────────


def corridor_score(box: Box) -> float:
    """Vật có nằm trên đường đi không — hành lang giữa 20%–80% bề ngang.

    Vật ở rìa khung hình thì người dùng đi qua bên cạnh nó, không đâm vào.
    Bỏ qua chiều này thì mọi cái cây ven đường đều kêu inh ỏi và người dùng
    tắt chế độ này trong ngày đầu.
    """
    left, right = config.HAZARD_CORRIDOR_LEFT, config.HAZARD_CORRIDOR_RIGHT
    center = box.center_x
    if left <= center <= right:
        return 1.0
    # Ra ngoài hành lang thì tắt dần chứ không tắt phụt: một vật đang đi vào
    # hành lang cần được lên mức TRƯỚC khi nó vào hẳn.
    distance = left - center if center < left else center - right
    return max(0.0, 1.0 - distance / max(left, 1e-6))


def proximity_score(box: Box) -> float:
    """Vật gần tới đâu — suy từ diện tích box và mép dưới của nó.

    Camera đơn không đo được khoảng cách. Hai đại lượng thay thế: box **to**
    nghĩa là gần, và mép dưới **thấp** trong khung nghĩa là gần chân người
    (mặt đất ở gần chiếu vào phần dưới khung hình).
    """
    area_part = min(1.0, box.area / config.HAZARD_AREA_FULL)
    bottom_part = min(1.0, max(0.0, box.bottom))
    return (
        config.HAZARD_AREA_WEIGHT * area_part
        + config.HAZARD_BOTTOM_WEIGHT * bottom_part
    )


class ApproachEngine:
    """Vật đang tiến lại gần hay đang lùi ra — độ dốc diện tích box theo thời gian.

    Một cái cột đứng yên khi ta đứng yên thì không nguy hiểm; đúng cái cột đó
    khi ta đang đi tới thì có. Chỉ nhìn một khung hình thì không phân biệt
    được hai ca đó.
    """

    def __init__(self, window: int = 5) -> None:
        self._window = window
        self._history: dict[str, list[tuple[float, float]]] = {}

    def observe(self, key: str, area: float, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        samples = self._history.setdefault(key, [])
        samples.append((now, area))
        if len(samples) > self._window:
            del samples[: len(samples) - self._window]

        if len(samples) < 2:
            return 0.0

        first_time, first_area = samples[0]
        last_time, last_area = samples[-1]
        span = last_time - first_time
        if span <= 0:
            return 0.0

        # Độ dốc chuẩn hoá theo chính diện tích: một vật nhỏ to lên gấp đôi
        # đáng lo bằng một vật to to lên gấp đôi.
        slope = (last_area - first_area) / span
        return max(0.0, min(1.0, slope / max(first_area, 1e-6)))

    def forget(self, key: str) -> None:
        self._history.pop(key, None)


# ─── mức + hysteresis ─────────────────────────────────────────────────────

LEVELS = ("SAFE", "LOW", "MEDIUM", "HIGH")


def level_for(score: float) -> str:
    if score >= config.HAZARD_ENTER_HIGH:
        return "HIGH"
    if score >= config.HAZARD_ENTER_MEDIUM:
        return "MEDIUM"
    if score >= config.HAZARD_ENTER_LOW:
        return "LOW"
    return "SAFE"


@dataclass
class _DeviceRisk:
    level: str = "SAFE"
    level_since: float = field(default_factory=time.monotonic)
    last_score: float = 0.0
    approach: ApproachEngine = field(default_factory=ApproachEngine)


class RiskEngine:
    """Chấm một khung hình thành một mức, có hysteresis, theo từng thiết bị."""

    def __init__(self, detector: Detector | None = None) -> None:
        self._detector = detector
        self._lock = threading.Lock()
        self._devices: dict[str, _DeviceRisk] = {}

    @property
    def available(self) -> bool:
        return self._detector is not None

    def set_detector(self, detector: Detector | None) -> None:
        self._detector = detector

    def score_boxes(self, device_id: str, boxes: list[Box], now: float | None = None) -> float:
        """Điểm nguy hiểm cao nhất trong khung, 0.0–1.0.

        Lấy MAX chứ không phải trung bình: một vật cản chắn đường giữa mười
        vật vô hại vẫn là một vật cản chắn đường. Trung bình sẽ pha loãng đúng
        cái duy nhất đáng báo.
        """
        with self._lock:
            state = self._devices.setdefault(device_id, _DeviceRisk())
            approach = state.approach

        best = 0.0
        for index, box in enumerate(boxes):
            if box.confidence < config.HAZARD_MIN_CONFIDENCE:
                continue
            key = f"{device_id}:{box.label}:{index}"
            score = (
                config.HAZARD_CORRIDOR_WEIGHT * corridor_score(box)
                + config.HAZARD_PROXIMITY_WEIGHT * proximity_score(box)
                + config.HAZARD_APPROACH_WEIGHT * approach.observe(key, box.area, now)
            )
            best = max(best, min(1.0, score))
        return best

    def update(self, device_id: str, score: float, now: float | None = None) -> tuple[str, bool]:
        """Áp hysteresis. Trả `(mức hiện tại, mức có ĐỔI không)`.

        Chỉ khi `đổi` là True mới được gửi `hazard_level` xuống board (W3) —
        gửi mỗi khung hình sẽ dìm chết hàng đợi SSE có 8 chỗ và đẩy văng cả
        `call_incoming`.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            state = self._devices.setdefault(device_id, _DeviceRisk())
            state.last_score = score
            proposed = level_for(score)
            current = state.level

            if LEVELS.index(proposed) > LEVELS.index(current):
                # Lên mức: NGAY, không cooldown. Chậm một nhịp là vấp.
                state.level = proposed
                state.level_since = now
                return proposed, True

            if LEVELS.index(proposed) < LEVELS.index(current):
                # Xuống mức: phải giữ đủ lâu. Một khung hình trượt detector
                # không được phép tắt tiếng cảnh báo giữa lúc đang bước tới.
                if (now - state.level_since) * 1000 < config.HAZARD_COOLDOWN_MS:
                    return current, False
                state.level = proposed
                state.level_since = now
                return proposed, True

            return current, False

    def evaluate(self, device_id: str, jpeg: bytes, now: float | None = None) -> tuple[str, bool]:
        """Cả đường: khung hình → box → điểm → mức."""
        if self._detector is None:
            raise HazardWatchUnavailable(
                "Chưa có model nhận diện vật cản. Xem docs/tasks/T24-hazard-watch.md."
            )
        boxes = self._detector.detect(jpeg)
        return self.update(device_id, self.score_boxes(device_id, boxes, now), now)

    def reset(self, device_id: str | None = None) -> None:
        with self._lock:
            if device_id is None:
                self._devices.clear()
            else:
                self._devices.pop(device_id, None)

    def current_level(self, device_id: str) -> str:
        with self._lock:
            state = self._devices.get(device_id)
            return state.level if state else "SAFE"


risk_engine = RiskEngine()
