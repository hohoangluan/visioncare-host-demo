"""Kiểm khói ngay sau export: ONNX chạy được qua đúng `live.hazard.OnnxYolo` của VH, trên CUDA, đầu ra đúng số lớp,
và ra detection trên ảnh test. Thoát mã ≠ 0 nếu hỏng. Chạy bằng ~/.venvs/seevia từ evaluations/.

    HAZARD_CLASSES_JSON=train/classes_vh.json python train/check_onnx.py train/models/ft_s_320.onnx
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bench import common  # noqa: E402

common.setup()

import cv2  # noqa: E402

from live import hazard  # noqa: E402


def main() -> None:
    path = sys.argv[1]
    cj = os.environ.get("HAZARD_CLASSES_JSON")
    if cj:
        hazard._CLASSES = {int(k): tuple(v) for k, v in json.load(open(cj, encoding="utf-8")).items()}
    nc_expect = len(hazard._CLASSES) if cj else 80
    det = hazard.OnnxYolo(path, 320)
    out_shape = det._sess.get_outputs()[0].shape
    in_shape = det._sess.get_inputs()[0].shape
    errors = []
    if det.provider != "CUDAExecutionProvider":
        errors.append(f"provider {det.provider} (cần CUDA)")
    if out_shape[1] != 4 + nc_expect:
        errors.append(f"đầu ra {out_shape}, cần 4+{nc_expect}")
    if list(in_shape[2:]) != [320, 320]:
        errors.append(f"đầu vào {in_shape}, cần tĩnh 320")
    imgs = sorted(glob.glob(os.path.join(common.DATAS, "obstacle_dataset", "test", "img-test", "*.jpg")))[:50]
    kinds = {}
    for p in imgs:
        for d in det.detect(cv2.imread(p)):
            kinds[d.kind] = kinds.get(d.kind, 0) + 1
    if not kinds:
        errors.append("0 detection trên 50 ảnh test")
    print(json.dumps({"model": path, "provider": det.provider, "in": in_shape, "out": out_shape,
                      "detections_50_test_images": kinds, "errors": errors}, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
