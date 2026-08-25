"""T24/W4 — detector YOLO11n ONNX cho `hazard_watch`.

Tách hẳn khỏi `services/hazard_risk.py` là **có chủ ý**, không phải chia file
cho gọn: luật chấm điểm (corridor / proximity / approach / hysteresis) là phần
dễ sai nhất và phải test được mọi lần, kể cả trên máy chưa tải model. File này
là thứ duy nhất biết tới ONNX; đổi sang model khác chỉ phải sửa ở đây.

Ba chỗ đã trả giá ở các dự án YOLO khác, ghi lại để khỏi dẫm lại:

1. **Letterbox, không resize thẳng.** Kéo 1280×720 thành 640×640 làm méo tỉ
   lệ; box trả về sẽ lệch và `proximity_score()` (đọc diện tích + mép dưới)
   nhận số sai một cách có hệ thống — sai theo hướng "vật cản trông xa hơn
   thực tế", đúng hướng nguy hiểm nhất.
2. **YOLO11 xuất `[1, 84, 8400]`, KHÔNG phải `[1, 8400, 84]`.** Đọc nhầm
   chiều thì mọi box đều hợp lệ về mặt số học và hoàn toàn vô nghĩa về nội
   dung — không có exception nào, chỉ có cảnh báo sai chỗ.
3. **Toạ độ ra là `cx, cy, w, h` theo pixel của ảnh 640, không phải `x1,y1,x2,y2`
   chuẩn hoá.** Phải đổi hệ *và* gỡ letterbox *và* chia cho kích thước gốc.
   `Box` của `hazard_risk` nhận toạ độ chuẩn hoá [0,1] — xem docstring ở đó.
"""

from __future__ import annotations

from pathlib import Path
import logging
import threading

import numpy as np

import config
from services.hazard_risk import Box

log = logging.getLogger("blind_assist.hazard")


# COCO 80 lớp. Chỉ giữ tên để log/đọc, luật chấm điểm KHÔNG dùng tới nhãn —
# một cái cột và một con người chắn đường đều là vật cản như nhau.
COCO_NAMES = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light "
    "fire_hydrant stop_sign parking_meter bench bird cat dog horse sheep cow "
    "elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee "
    "skis snowboard sports_ball kite baseball_bat baseball_glove skateboard "
    "surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana "
    "apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard "
    "cell_phone microwave oven toaster sink refrigerator book clock vase "
    "scissors teddy_bear hair_drier toothbrush"
).split()


class YoloOnnxDetector:
    """YOLO11n ONNX → danh sách `Box` toạ độ chuẩn hoá."""

    def __init__(self, model_path: str | Path, input_size: int = 640) -> None:
        import onnxruntime

        self._input_size = input_size
        self._path = Path(model_path)
        if not self._path.is_file():
            raise FileNotFoundError(f"Không thấy model: {self._path}")

        # CPU thôi. GPU của máy này (nếu có) đang dành cho STT/TTS, và tranh
        # nhau một GPU sẽ làm chậm đúng đường bấm nút mà người dùng đang chờ.
        self._session = onnxruntime.InferenceSession(
            str(self._path), providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name

        # ONNX Runtime an toàn thread cho `run()`, nhưng worker canh vật cản và
        # một lượt chẩn đoán tay có thể gọi cùng lúc — khoá cho chắc, chi phí
        # gần bằng 0 so với ~30 ms suy luận.
        self._lock = threading.Lock()

        log.info("Đã nạp detector vật cản: %s", self._path.name)

    # ---------------------------------------------------------------- tiền xử lý

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        """Thu nhỏ GIỮ tỉ lệ rồi đệm xám cho đủ khung vuông.

        Trả `(ảnh, tỉ lệ, đệm trái, đệm trên)` — ba số sau để gỡ letterbox lúc
        đổi toạ độ box về ảnh gốc.
        """
        h, w = image.shape[:2]
        size = self._input_size
        scale = min(size / w, size / h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))

        import cv2

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)  # 114 = xám của YOLO
        pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
        return canvas, scale, pad_x, pad_y

    # ---------------------------------------------------------------- suy luận

    def detect(self, jpeg: bytes) -> list[Box]:
        import cv2

        buffer = np.frombuffer(jpeg, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            # Khung hỏng thì trả rỗng, KHÔNG ném: một khung JPEG cụt giữa
            # đường truyền không được phép làm chết cả chế độ canh. Khung sau
            # tới trong nửa giây nữa.
            log.warning("Khung hazard không giải mã được (%d byte)", len(jpeg))
            return []

        original_h, original_w = image.shape[:2]
        canvas, scale, pad_x, pad_y = self._letterbox(image)

        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None]  # NCHW

        with self._lock:
            outputs = self._session.run(None, {self._input_name: blob})

        # 🔴 [1, 84, 8400] — 84 = 4 toạ độ + 80 điểm lớp, 8400 = số ô dự đoán.
        # Chuyển vị để mỗi hàng là một dự đoán.
        predictions = np.squeeze(outputs[0]).T  # -> [8400, 84]
        if predictions.ndim != 2 or predictions.shape[1] < 5:
            log.error("Model trả về hình dạng lạ: %s", np.shape(outputs[0]))
            return []

        scores = predictions[:, 4:]
        class_ids = np.argmax(scores, axis=1)
        confidences = scores[np.arange(len(scores)), class_ids]

        keep = confidences >= config.HAZARD_MIN_CONFIDENCE
        if not np.any(keep):
            return []

        boxes_cxcywh = predictions[keep, :4]
        confidences = confidences[keep]
        class_ids = class_ids[keep]

        # cx,cy,w,h (pixel của khung 640 đã letterbox) -> x,y,w,h góc trái trên
        xywh = np.empty_like(boxes_cxcywh)
        xywh[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        xywh[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        xywh[:, 2] = boxes_cxcywh[:, 2]
        xywh[:, 3] = boxes_cxcywh[:, 3]

        # NMS chạy trên toạ độ 640 — làm trước khi gỡ letterbox cho rẻ.
        indices = cv2.dnn.NMSBoxes(
            xywh.tolist(),
            confidences.tolist(),
            float(config.HAZARD_MIN_CONFIDENCE),
            float(config.HAZARD_NMS_IOU),
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        result: list[Box] = []
        for index in indices:
            x, y, w, h = xywh[index]
            # Gỡ đệm letterbox rồi đưa về ảnh gốc, cuối cùng chuẩn hoá [0,1].
            x1 = (x - pad_x) / scale / original_w
            y1 = (y - pad_y) / scale / original_h
            x2 = (x + w - pad_x) / scale / original_w
            y2 = (y + h - pad_y) / scale / original_h
            class_id = int(class_ids[index])
            result.append(
                Box(
                    label=COCO_NAMES[class_id] if class_id < len(COCO_NAMES) else str(class_id),
                    confidence=float(confidences[index]),
                    x1=float(np.clip(x1, 0.0, 1.0)),
                    y1=float(np.clip(y1, 0.0, 1.0)),
                    x2=float(np.clip(x2, 0.0, 1.0)),
                    y2=float(np.clip(y2, 0.0, 1.0)),
                )
            )
        return result


def load_default() -> YoloOnnxDetector | None:
    """Nạp model ở `config.HAZARD_MODEL_PATH`, hoặc `None` nếu chưa có.

    Trả `None` chứ không ném: thiếu model là một trạng thái **hợp lệ** của hệ
    (máy dev chưa tải, bản cài tối giản). `handlers/hazard_watch.py` biến nó
    thành một câu nói được cho người dùng — xem `risk_engine.available`.
    """
    path = Path(config.HAZARD_MODEL_PATH)
    if not path.is_file():
        log.info(
            "Chưa có model vật cản ở %s — chế độ cảnh báo vật cản sẽ từ chối bật. "
            "Tải bằng: python tools/fetch_hazard_model.py",
            path,
        )
        return None
    try:
        return YoloOnnxDetector(path)
    except Exception:  # noqa: BLE001
        # Model hỏng cũng là "không có model", không phải lý do để server chết.
        log.exception("Không nạp được model vật cản %s", path)
        return None
