"""Xuất ONNX tĩnh 320 (giống VH tools/export_hazard_onnx.py) cho model COCO hoặc model fine-tune. Chạy bằng ~/.venvs/yolo.

    python train/export_onnx.py --weights train/weights/yolo11s.pt --out train/models/coco_s_320.onnx
"""

import argparse
import os
import shutil


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--imgsz", type=int, default=320)
    a = ap.parse_args()
    from ultralytics import YOLO

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    model = YOLO(a.weights)
    # YOLO26 mặc định end-to-end (không NMS, đầu ra (1,300,6)); VH `OnnxYolo` đọc (1,4+nc,N) rồi tự NMS
    # -> tắt end2end để xuất nhánh one-to-many (đã huấn luyện cùng), khỏi sửa VH. YOLO11 không có cờ này.
    flipped = 0
    for m in model.model.modules():
        if getattr(m, "end2end", False):
            m.end2end = False
            flipped += 1
    if flipped:
        print(f"tắt end2end ở {flipped} module (YOLO26) -> đầu ra kiểu YOLO11, NMS ở VH")
    path = model.export(format="onnx", imgsz=a.imgsz, simplify=True, dynamic=False)
    shutil.copy(path, a.out)
    print(f"đã xuất {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB), imgsz={a.imgsz}")


if __name__ == "__main__":
    main()
