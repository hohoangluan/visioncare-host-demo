"""Tải YOLO11n và export sang ONNX cho `hazard_watch` (T24/W4).

Chạy MỘT LẦN trên mỗi máy:

    python tools/fetch_hazard_model.py

Kết quả: `models/od/yolo11n.onnx` (~10 MB). Sau đó `hazard_watch` bật được.

Vì sao export tại chỗ thay vì chép sẵn một file .onnx vào repo:

1. **Kích thước.** 10 MB nhị phân trong git làm mọi lần clone nặng thêm, và
   nó không diff được — mỗi lần đổi model là thêm 10 MB nữa vào lịch sử.
2. **Phiên bản opset.** File .onnx phải khớp `onnxruntime` của máy chạy. Chép
   sẵn một file export từ máy khác là nguồn của loại lỗi "chạy trên máy tôi".
3. `ultralytics` tự tải trọng số từ nguồn chính thức và tự kiểm tra — không
   phải tin một file nhị phân lạ nằm trong repo.

`ultralytics` là **dependency chỉ để export**, không phải để chạy. Server
production chỉ cần `onnxruntime` + `opencv` (đã có sẵn) — xem
`services/hazard_detector.py`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

# 🔴 Windows: stdout mặc định là cp1252, và MỌI dòng in của tool này đều có
# tiếng Việt. Không có ba dòng dưới thì tool chạy XONG việc rồi chết ở lệnh
# `print` cuối — nhìn từ ngoài giống hệt "tool hỏng", trong khi file đã ghi.
# Đã dính thật với `publish_firmware.py` (bản đã phát hành, chỉ crash lúc in).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default="yolo11n.pt", help="trọng số nguồn (mặc định yolo11n.pt)"
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--out", default=config.HAZARD_MODEL_PATH)
    parser.add_argument("--force", action="store_true", help="export lại dù đã có")
    args = parser.parse_args()

    out = Path(args.out)
    if out.is_file() and not args.force:
        print(f"Đã có {out} ({out.stat().st_size / 1e6:.1f} MB). Dùng --force để làm lại.")
        return 0

    try:
        from ultralytics import YOLO
    except ImportError:
        print("Thiếu ultralytics. Cài bằng:")
        print("  .venv/Scripts/python.exe -m pip install ultralytics")
        print("\nNó chỉ cần cho bước export này; server chạy chỉ cần onnxruntime.")
        return 1

    print(f"Tải {args.model} rồi export ONNX (imgsz={args.imgsz})...")
    model = YOLO(args.model)
    exported = Path(
        model.export(format="onnx", imgsz=args.imgsz, opset=12, simplify=False)
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    # `move` chứ không `copy`: để lại một bản .onnx lạc ở thư mục gốc là để
    # lại đúng thứ mà lần chạy sau sẽ tưởng là model đang dùng.
    shutil.move(str(exported), str(out))
    print(f"✅ {out}  ({out.stat().st_size / 1e6:.1f} MB)")

    # Kiểm ngay bằng chính đường mà production sẽ đi — không phải bằng
    # ultralytics. Export thành công mà onnxruntime không nạp được là ca có
    # thật (lệch opset), và phát hiện nó ở đây rẻ hơn nhiều so với phát hiện
    # lúc người dùng bấm "bật cảnh báo vật cản".
    from services.hazard_detector import YoloOnnxDetector

    detector = YoloOnnxDetector(out, input_size=args.imgsz)
    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "space_room.jpg"
    if fixture.is_file():
        boxes = detector.detect(fixture.read_bytes())
        print(f"Thử trên {fixture.name}: nhận ra {len(boxes)} vật")
        for box in boxes[:8]:
            print(
                f"  {box.label:<14} {box.confidence:.2f}  "
                f"[{box.x1:.2f},{box.y1:.2f} → {box.x2:.2f},{box.y2:.2f}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
