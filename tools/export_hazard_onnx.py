"""Xuất YOLO nano COCO sang ONNX cho làn C (`live/hazard.py`).

Chỉ chạy một lần trên máy dev (cần `ultralytics`, kéo theo torch); server chỉ
cần onnxruntime để chạy file kết quả.

    uv pip install ultralytics onnx onnxslim
    python tools/export_hazard_onnx.py            # -> models/hazard/yolo11n.onnx
    python tools/export_hazard_onnx.py --imgsz 416 --weights yolov8n.pt
"""

import argparse
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", default="yolo11n.pt")
    parser.add_argument("--imgsz", type=int, default=320)
    args = parser.parse_args()

    from ultralytics import YOLO

    out_dir = os.path.join(ROOT, "models", "hazard")
    os.makedirs(out_dir, exist_ok=True)
    model = YOLO(args.weights)
    path = model.export(format="onnx", imgsz=args.imgsz, simplify=True, dynamic=False)
    target = os.path.join(out_dir, os.path.splitext(os.path.basename(args.weights))[0] + ".onnx")
    shutil.move(path, target)
    print(f"đã xuất {target} ({os.path.getsize(target) / 1e6:.1f} MB), imgsz={args.imgsz}")


if __name__ == "__main__":
    main()
