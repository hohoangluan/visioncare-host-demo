"""T24/W4 — phát hiện vật cản bằng ĐỘ SÂU, không bằng nhận dạng lớp.

Vì sao file này tồn tại cạnh `hazard_detector.py`
--------------------------------------------------
YOLO11n biết đúng **80 lớp COCO** và **không có lớp "vật thể chung"**. Đo trên
ảnh thật (2026-08-24): cột điện, tường, bậc thềm, cành cây thấp, cửa kính,
hàng rào — không cái nào nằm trong 80 lớp đó, nên không có box nào, nên hệ báo
**`SAFE`** cho một cây cột chắn ngay trước mặt.

Đó vi phạm chính nguyên tắc viết trong `hazard_risk.py`: `SAFE` nghĩa là "đã
nhìn và thấy an toàn", không phải "chưa nhìn được".

Câu hỏi thật của bài toán là *"có gì chắn đường tôi không"*, không phải *"cái
chắn đường tôi tên gì"*. Bản đồ độ sâu cho một giá trị **cho từng pixel** nên
bắt được cả vật vô danh — đó là lý do nó là tín hiệu CHÍNH, còn YOLO tụt
xuống vai phụ (đặt tên cho vật, phục vụ câu hỏi mở #5 của T24).

🔴 Bài học đắt nhất của module này: "gần" KHÔNG phải "chắn đường"
-----------------------------------------------------------------
Bản đầu tiên chấm điểm bằng một ngưỡng tuyệt đối trên bản đồ disparity đã
chuẩn hoá: `depth >= 0.62` thì coi là vật cản. Trên 4 ảnh fixture nó trông
hợp lý. Đo trên 25 ảnh THẬT (2026-08-24, `tools/eval_hazard.py`):

    bắt được 8/8 ảnh có vật chắn        ✅
    báo oan  11/11 ảnh đường trống      🔴 kêu HIGH cho con đường quê trống trơn

Nó không phát hiện vật cản. **Nó phát hiện mặt đất.** Chuẩn hoá theo từng
khung ⟹ thứ gần nhất trong khung luôn được đẩy về 1.0, mà thứ gần nhất trong
mọi khung ảnh chụp khi đi bộ chính là mặt đất ngay dưới chân.

Một chế độ canh vật cản kêu ở mọi bước chân còn tệ hơn không có: người dùng
tắt nó đi sau buổi sáng đầu tiên, và lúc đó tỉ lệ bỏ sót là 100%.

Hai tín hiệu thay cho một ngưỡng
---------------------------------
Bản này hỏi hai câu khác nhau, vì hai loại vật cản để lại hai dấu vết khác
hẳn nhau trong bản đồ độ sâu:

**S1 — gần hơn PHẦN CÒN LẠI CỦA CHÍNH DÒNG ĐÓ** (`_relative_regions`)
    Nền của mỗi dòng là trung vị disparity của chính dòng đó. Đường trống:
    cả dòng bằng nhau ⟹ không còn gì. Cây cột: cột hẹp hơn dòng nên nó vọt
    lên trên trung vị ⟹ lộ ra. Bắt cột, trụ chắn, người, biển báo.

    Đo được (dải giữa 34% chiều rộng, biên 0.16):
        đường trống  diện tích vượt = 0.000
        cột điện sát = 0.124

**S2 — KHÔNG NHÌN THẤY ĐƯỢC GÌ Ở XA** (`_blocked_view`)
    S1 mù với vật choán hết chiều ngang — tường, bậc thềm, cánh cửa — vì
    chính vật đó trở thành trung vị của dòng, và phép trừ triệt tiêu nó.
    Câu hỏi thứ hai: điểm XA NHẤT nhìn thấy được trong hành lang giữa nằm ở
    đâu? Đường thoáng thì có điểm tụ ở rất xa (disparity ≈ 0). Tường cách 3 m
    thì chỗ xa nhất nhìn được chính là bức tường đó.

Ba chỗ dễ sai, ghi trước khi ai đó sửa
---------------------------------------
1. 🔴 **Depth Anything trả `disparity`, KHÔNG phải khoảng cách.** Giá trị
   **CÀNG LỚN = CÀNG GẦN**, ngược trực giác. Đảo dấu ở đây thì hệ cảnh báo
   bầu trời và bỏ qua bức tường — và không có exception nào để lần ra.
2. **Chuẩn hoá theo TỪNG KHUNG.** Model trả giá trị tương đối, thang thay đổi
   theo cảnh. Đó là lý do mọi ngưỡng ở đây đều là **tương đối** (so với dòng,
   so với điểm xa nhất), không có ngưỡng tuyệt đối nào trên giá trị thô.
3. **Bỏ dải trên của khung.** Trần nhà và bầu trời luôn "xa", nhưng mép trên
   khung cũng hay dính vật thể treo. Chỉ xét từ `DEPTH_SKY_CUTOFF` xuống —
   phần người đi bộ thật sự đâm vào.

🔴 CÒN YẾU — đo được, chưa sửa
-------------------------------
Sau khi đổi sang hai tín hiệu (bảng đầy đủ ở `docs/tasks/measurements/T24.md`):

    bắt được  5/8      báo oan  2/11

Ba ca bỏ sót đều CÙNG MỘT LOẠI: **bậc thềm và khung cửa ở cự ly gần**
(`Pedestrian_passage`, `Staircase_Chavunda`, `EFTA doorway`). Chúng choán hết
chiều ngang nên S1 không thấy, mà vẫn còn nhìn xuyên qua được nên S2 cũng
không thấy. Bậc thềm là thứ người khiếm thị vấp nhiều nhất, nên đây là lỗ
hổng phải vá, không phải hạn chế chấp nhận được.

Hướng đã nghĩ, chưa thi công: bậc thềm để lại một dấu vết riêng — disparity
theo dòng đi lên thành **bậc thang** thay vì trơn. Cần đo trên khung thật của
camera board trước, vì độ cao đặt camera đổi hẳn hình dạng profile đó.
"""

from __future__ import annotations

from pathlib import Path
import logging
import threading

import numpy as np

import config
from services.hazard_risk import Box

log = logging.getLogger("blind_assist.hazard")

# Bỏ 25% trên cùng của khung. Trần/bầu trời nằm ở đó và chúng không bao giờ là
# thứ người đi bộ đâm vào; giữ lại thì mọi khung trong nhà đều có một vùng
# "gần" là cái trần.
DEPTH_SKY_CUTOFF = 0.25


def _confidence(ratio: float) -> float:
    """Đưa một tỉ lệ bất kỳ về khoảng [0, 1] mà `hazard_risk` chờ đợi.

    Kẹp chứ không co giãn: vượt quá mức "đầy" thì vẫn là 1.0. Một cây cột cách
    nửa mét và một cây cột cách mười phân đều là "dừng lại ngay" — chia thêm
    mức ở trên đó không đổi được việc gì người dùng phải làm.
    """
    return float(min(1.0, max(0.0, ratio)))


class DepthObstacleDetector:
    """Bản đồ độ sâu → các vùng "gần và chắn đường", đóng gói thành `Box`.

    Trả về cùng kiểu `Box` với `YoloOnnxDetector` nên `RiskEngine` không cần
    biết nó đang nói chuyện với detector nào — `hazard_risk.Detector` là một
    `Protocol` đúng vì lý do này.
    """

    def __init__(self, model_path: str | Path, input_size: int | None = None) -> None:
        import onnxruntime

        self._path = Path(model_path)
        if not self._path.is_file():
            raise FileNotFoundError(f"Không thấy model độ sâu: {self._path}")

        self._input_size = input_size or config.DEPTH_INPUT_SIZE

        # 🔴 KHOÁ KÍCH THƯỚC ĐẦU VÀO — đây là tối ưu lớn nhất của cả module,
        # và nó KHÔNG đổi một bit nào của kết quả.
        #
        # Model khai báo `height`/`width` động. Với hình dạng động, ORT không
        # gấp hằng số được nhánh **nội suy position-embedding của DINOv2**:
        # bảng pos-embed gốc là lưới 37×37 và phải nội suy bicubic về lưới
        # patch h/14 × w/14. Nhánh đó phụ thuộc DUY NHẤT vào kích thước ảnh —
        # không phụ thuộc nội dung ảnh — nên nó cho ra đúng một tensor, mọi
        # khung hình, mãi mãi. Vậy mà nó được tính lại mỗi khung.
        #
        # Đo trên máy này (i5-12500H, CPU, input 308, profile theo node):
        #
        #     node `/Resize` (nội suy pos-embed)   63.5 ms  ← 39% CẢ LẦN CHẠY
        #     toàn bộ 48 MatMul của 12 block ViT   46.2 ms
        #
        # Một phép nội suy bảng tra cứu tốn hơn cả thân transformer. Khoá kích
        # thước xong, ORT gấp nó thành hằng số lúc nạp phiên:
        #
        #     động (như cũ)   177 ms p50
        #     khoá 308        107 ms p50   ← nhanh hơn 40%
        #
        # Đánh đổi: phiên này chỉ chạy đúng cỡ `self._input_size`. `depth_map()`
        # luôn resize về đúng cỡ đó nên ràng buộc được giữ ngay trong lớp này.
        #
        # 🔴 Dùng `free_dimension_override` chứ KHÔNG sửa file .onnx: bản
        # `optimized_model_filepath` mà ORT ghi ra có tối ưu riêng theo CPU của
        # máy dựng (NchwcTransformer), đem sang máy khác là sai âm thầm.
        options = onnxruntime.SessionOptions()
        options.graph_optimization_level = (
            onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        for name, value in (
            ("batch_size", 1),
            ("height", self._input_size),
            ("width", self._input_size),
        ):
            options.add_free_dimension_override_by_name(name, value)

        self._session = onnxruntime.InferenceSession(
            str(self._path), options, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._session.get_inputs()[0].name
        self._lock = threading.Lock()

        log.info(
            "Đã nạp detector độ sâu: %s (khoá đầu vào %d×%d)",
            self._path.name, self._input_size, self._input_size,
        )

    # ------------------------------------------------------------------ suy luận

    def depth_map(self, jpeg: bytes) -> np.ndarray | None:
        """Bản đồ disparity đã chuẩn hoá 0-1 (1 = gần nhất), hoặc None."""
        import cv2

        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            log.warning("Khung hazard không giải mã được (%d byte)", len(jpeg))
            return None

        size = self._input_size
        # Resize thẳng (KHÔNG letterbox): ta chỉ cần bản đồ tương đối theo
        # vùng, và méo tỉ lệ không đổi thứ tự "gần hơn/xa hơn" giữa các vùng.
        # Khác hẳn YOLO, nơi méo tỉ lệ làm sai diện tích box.
        blob = cv2.resize(image, (size, size), interpolation=cv2.INTER_CUBIC)
        blob = cv2.cvtColor(blob, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        # Chuẩn hoá ImageNet — Depth Anything huấn luyện với nó.
        blob = (blob - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
            [0.229, 0.224, 0.225], np.float32
        )
        blob = np.transpose(blob, (2, 0, 1))[None]

        with self._lock:
            outputs = self._session.run(None, {self._input_name: blob})

        depth = np.squeeze(outputs[0]).astype(np.float32)
        if depth.ndim != 2:
            log.error("Model độ sâu trả hình dạng lạ: %s", np.shape(outputs[0]))
            return None

        # 🔴 Chuẩn hoá theo TỪNG KHUNG. Model trả giá trị tương đối và thang
        # của nó đổi theo cảnh — ngưỡng tuyệt đối trên đầu ra thô là ngưỡng
        # trôi theo độ sáng căn phòng.
        low, high = float(depth.min()), float(depth.max())
        if high - low < 1e-6:
            return np.zeros_like(depth)
        return (depth - low) / (high - low)

    # ------------------------------------------------- S1: gần hơn chính dòng đó

    def _relative_regions(self, depth: np.ndarray) -> list[Box]:
        """Vùng gần hơn hẳn phần còn lại của DÒNG chứa nó.

        Nền của mỗi dòng là trung vị disparity của chính dòng đó — không phải
        một hằng số, cũng không phải một mặt phẳng khớp được bằng đường thẳng.
        Đã thử khớp mặt đất bằng hàm bậc nhất theo số dòng và nó KHÔNG tách
        được gì (`blocked` trung vị 0.255 vs `clear` 0.250): profile độ sâu
        của mặt đất trong bản đồ *tương đối* của Depth Anything cong rõ rệt,
        không tuyến tính. Trung vị từng dòng không giả định hình dạng nào cả,
        nên nó đúng với cả đường dốc, cầu thang, và sàn nhà phẳng.
        """
        import cv2

        height, width = depth.shape

        baseline = np.median(depth, axis=1)
        excess = depth - baseline[:, None]

        near = (excess >= config.DEPTH_EXCESS_MARGIN).astype(np.uint8)

        # Bỏ dải trên: trần nhà / bầu trời không phải thứ người đi bộ đâm vào.
        near[: int(height * DEPTH_SKY_CUTOFF), :] = 0

        # Chỉ xét hành lang giữa. Đây là chỗ chặn phần lớn báo oan: hành lang
        # hẹp và lối đi có lan can đều có tường/lan can SÁT hai bên, và chúng
        # vượt trung vị dòng rất mạnh — nhưng chúng nằm bên cạnh người dùng,
        # không chắn bước chân. Đo được: bỏ ràng buộc này thì "hành lang trống"
        # và "lối đi sân bay có lan can kính" đều kêu.
        margin = (1.0 - config.DEPTH_CORRIDOR_WIDTH) / 2.0
        near[:, : int(width * margin)] = 0
        near[:, int(width * (1.0 - margin)) :] = 0

        # Đóng lỗ nhỏ rồi bỏ đốm lẻ: bản đồ độ sâu lỗ chỗ ở mép vật, và một
        # vùng thủng lỗ chỗ sẽ bị tách thành chục "vật cản" tí hon.
        kernel = np.ones((5, 5), np.uint8)
        near = cv2.morphologyEx(near, cv2.MORPH_CLOSE, kernel)
        near = cv2.morphologyEx(near, cv2.MORPH_OPEN, kernel)

        count, labels, stats, _ = cv2.connectedComponentsWithStats(near, connectivity=8)

        frame_area = float(height * width)
        boxes: list[Box] = []
        for index in range(1, count):  # 0 là nền
            x, y, w, h, area = stats[index]
            if area / frame_area < config.DEPTH_MIN_REGION_AREA:
                continue

            # Độ "gần" = mức VƯỢT trung bình của chính vùng đó, không phải
            # disparity thô. Box của một vật nghiêng chứa nhiều nền, và nền thì
            # đúng bằng trung vị dòng nên nó đóng góp 0 — đó là điều ta muốn.
            patch = excess[y : y + h, x : x + w]
            region = patch[labels[y : y + h, x : x + w] == index]
            lead = float(region.mean()) if region.size else 0.0

            boxes.append(
                Box(
                    # Không có tên: đó là ĐIỂM MẠNH của đường này, không phải
                    # thiếu sót. `hazard_risk` không dùng nhãn để chấm điểm —
                    # một cái cột và một con người chắn đường đều là vật cản.
                    label="obstacle",
                    confidence=_confidence(lead / max(config.DEPTH_EXCESS_FULL, 1e-6)),
                    x1=x / width,
                    y1=y / height,
                    x2=(x + w) / width,
                    y2=(y + h) / height,
                )
            )
        return boxes

    # ----------------------------------------- S2: không nhìn thấy được gì ở xa

    def _blocked_view(self, depth: np.ndarray) -> Box | None:
        """Tường / bậc thềm / cánh cửa choán hết chiều ngang phía trước.

        S1 mù hoàn toàn với loại này: vật choán cả dòng thì CHÍNH NÓ là trung
        vị của dòng, và phép trừ triệt tiêu nó về 0. Câu hỏi khác hẳn ở đây:
        *điểm xa nhất mà ta còn nhìn thấy được trong hành lang giữa nằm ở đâu?*

        Đường thoáng luôn có một điểm tụ ở rất xa (disparity ≈ 0). Bức tường
        cách ba mét thì chỗ xa nhất nhìn được chính là bức tường đó, nên giá
        trị này không xuống thấp được nữa.
        """
        height, width = depth.shape
        margin = (1.0 - config.DEPTH_CORRIDOR_WIDTH) / 2.0
        corridor = depth[:, int(width * margin) : int(width * (1.0 - margin))]
        profile = np.median(corridor, axis=1)

        # Bỏ cả hai đầu: dải trên là trần/trời, dải dưới cùng là mặt đất ngay
        # dưới mũi chân — nó LUÔN gần, ở mọi khung hình, nên để lại thì
        # `far` không bao giờ xuống thấp và mọi cảnh đều "bị chắn".
        band = profile[int(height * DEPTH_SKY_CUTOFF) : int(height * 0.85)]
        if band.size == 0:
            return None

        far = float(band.min())
        if far < config.DEPTH_BLOCKED_VIEW:
            return None

        # Box phủ trọn hành lang từ dòng xa nhất xuống đáy khung: ta biết CÓ
        # cái gì đó chắn ngang, nhưng không khoanh được rìa của nó — và giả vờ
        # khoanh chính xác sẽ làm `hazard_risk` chấm sai diện tích.
        row = int(np.argmin(band)) + int(height * DEPTH_SKY_CUTOFF)
        return Box(
            label="obstacle",
            confidence=_confidence(far / max(config.DEPTH_BLOCKED_FULL, 1e-6)),
            x1=margin,
            y1=row / height,
            x2=1.0 - margin,
            y2=1.0,
        )

    def detect(self, jpeg: bytes) -> list[Box]:
        depth = self.depth_map(jpeg)
        if depth is None:
            return []

        boxes = self._relative_regions(depth)
        blocked = self._blocked_view(depth)
        if blocked is not None:
            boxes.append(blocked)

        # Gần nhất lên đầu — `score_boxes()` lấy max nên thứ tự không đổi kết
        # quả, nhưng nó đổi thứ mà log in ra đầu tiên khi chẩn đoán.
        boxes.sort(key=lambda b: b.confidence, reverse=True)
        return boxes


class CombinedDetector:
    """Độ sâu là chính, YOLO là phụ — gộp kết quả của cả hai.

    Vì sao gộp chứ không chọn một:
      - **độ sâu** trả lời "có chắn đường không" cho MỌI vật, kể cả vô danh;
      - **YOLO** trả lời "vật đó là gì", và tên gọi là thứ duy nhất cho phép
        nói một từ ở mức HIGH (câu hỏi mở #5 của T24).

    Vùng độ sâu nào trùng nhiều với một box YOLO thì **mượn nhãn** của box đó.
    Vùng không trùng ai vẫn giữ nhãn `obstacle` — và đó chính là những vùng
    YOLO một mình sẽ bỏ sót hoàn toàn.
    """

    def __init__(self, depth: DepthObstacleDetector, yolo=None) -> None:
        self._depth = depth
        self._yolo = yolo

    def detect(self, jpeg: bytes) -> list[Box]:
        boxes = self._depth.detect(jpeg)
        if self._yolo is None or not boxes:
            return boxes

        try:
            named = self._yolo.detect(jpeg)
        except Exception:  # noqa: BLE001
            # YOLO hỏng thì mất TÊN, không mất CẢNH BÁO. Đường độ sâu vẫn
            # nguyên vẹn, nên đừng để lỗi của tầng phụ kéo sập tầng chính.
            log.exception("Tầng đặt tên (YOLO) hỏng — vẫn cảnh báo bằng độ sâu")
            return boxes

        return [self._with_label(box, named) for box in boxes]

    @staticmethod
    def _with_label(box: Box, named: list[Box]) -> Box:
        best_label, best_overlap = box.label, 0.0
        for candidate in named:
            overlap_x = max(0.0, min(box.x2, candidate.x2) - max(box.x1, candidate.x1))
            overlap_y = max(0.0, min(box.y2, candidate.y2) - max(box.y1, candidate.y1))
            overlap = overlap_x * overlap_y
            if box.area <= 0:
                continue
            ratio = overlap / box.area
            if ratio > best_overlap and ratio >= 0.35:
                best_label, best_overlap = candidate.label, ratio

        if best_label == box.label:
            return box
        return Box(
            label=best_label,
            confidence=box.confidence,
            x1=box.x1,
            y1=box.y1,
            x2=box.x2,
            y2=box.y2,
        )


def load_default(yolo=None):
    """Nạp detector tốt nhất máy này có.

    Thứ tự ưu tiên, và nó phản ánh đúng mức độ tin cậy:

        depth + YOLO   đầy đủ — bắt mọi vật, và gọi tên được vật quen
        depth          bắt mọi vật, không gọi tên
        YOLO           🔴 CHỈ bắt 80 lớp COCO — mù với cột/tường/bậc thềm
        None           `hazard_watch` từ chối bật

    Trả `None` chứ không ném: thiếu model là trạng thái **hợp lệ**, và
    `handlers/hazard_watch.py` biến nó thành một câu nói được cho người dùng.
    """
    path = Path(config.DEPTH_MODEL_PATH)
    if not path.is_file():
        log.warning(
            "Chưa có model độ sâu ở %s — chỉ còn YOLO, tức MÙ với cột/tường/"
            "bậc thềm. Tải bằng: python tools/fetch_depth_model.py",
            path,
        )
        return yolo

    try:
        depth = DepthObstacleDetector(path)
    except Exception:  # noqa: BLE001
        log.exception("Không nạp được model độ sâu %s", path)
        return yolo

    return CombinedDetector(depth, yolo)
