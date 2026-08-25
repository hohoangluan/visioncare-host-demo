"""Tải Depth Anything V2 small (ONNX) cho `hazard_watch` (T24/W4).

Chạy MỘT LẦN trên mỗi máy:

    python tools/fetch_depth_model.py

Kết quả: `models/od/depth_anything_v2_small.onnx` (~25 MB).

Vì sao cần model này khi đã có YOLO11n
---------------------------------------
YOLO11n biết đúng **80 lớp COCO** và **không có lớp "vật thể chung"**. Đo trên
ảnh thật: cột điện, tường, bậc thềm, cành cây thấp, cửa kính, hàng rào — không
cái nào nằm trong 80 lớp đó, nên không có box, nên hệ báo **`SAFE`** cho một
cây cột chắn ngay trước mặt. Đó là mù đúng thứ người khiếm thị hay va vào.

Câu hỏi thật của bài toán là *"có gì chắn đường tôi không"*, không phải *"cái
chắn đường tôi tên gì"*. Ước lượng độ sâu cho một giá trị khoảng cách **cho
từng pixel** — không cần danh sách lớp nào cả, nên nó bắt được cả vật vô danh.

Phân vai sau khi có cả hai:

    depth   tín hiệu CHÍNH  — "có chắn đường không"
    YOLO    tín hiệu PHỤ    — đặt tên cho vật (câu hỏi mở #5 của T24)

Nguồn tải
---------
`onnx-community/depth-anything-v2-small` trên HuggingFace — bản ONNX cộng đồng
export sẵn từ trọng số chính thức của Depth Anything V2 (giấy phép Apache-2.0
cho bản small).

Khác `fetch_hazard_model.py`: ở đó ta export tại chỗ bằng `ultralytics` vì nó
tự tải trọng số chính thức. Ở đây không có đường export chính thức nhẹ tương
đương, nên tải thẳng file ONNX — và **phải in ra sha256** để lần sau đối chiếu
được rằng vẫn đúng file đó.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
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


# Thử lần lượt: repo nào còn sống thì dùng. Danh sách chứ không phải một URL
# cứng vì repo cộng đồng có thể đổi tên nhánh/đường dẫn.
SOURCES = (
    "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
    "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_fp16.onnx",
    "https://huggingface.co/depth-anything/Depth-Anything-V2-Small/resolve/main/depth_anything_v2_vits.onnx",
)


def _download(url: str, out: Path) -> bool:
    print(f"Thử {url}")
    # Ghi ra file tạm rồi đổi tên: tải đứt giữa chừng không được để lại một
    # file .onnx cụt mà lần chạy sau tưởng là model hợp lệ.
    staging = out.with_suffix(".onnx.part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "visioncare/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with staging.open("wb") as handle:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {done / 1e6:.1f}/{total / 1e6:.1f} MB", end="")
        print()
    except Exception as exc:  # noqa: BLE001
        print(f"  hỏng: {exc}")
        staging.unlink(missing_ok=True)
        return False

    if staging.stat().st_size < 1_000_000:
        print(f"  file quá nhỏ ({staging.stat().st_size} B) — gần như chắc chắn là trang lỗi")
        staging.unlink(missing_ok=True)
        return False

    staging.replace(out)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=config.DEPTH_MODEL_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    if out.is_file() and not args.force:
        print(f"Đã có {out} ({out.stat().st_size / 1e6:.1f} MB). Dùng --force để tải lại.")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    if not any(_download(url, out) for url in SOURCES):
        print("\n🔴 Không tải được từ nguồn nào. Tải tay rồi đặt vào:")
        print(f"   {out}")
        return 1

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"✅ {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"   sha256 {digest}")

    # Kiểm ngay bằng chính đường production sẽ đi — không phải bằng thư viện
    # khác. Tải thành công mà onnxruntime không nạp được là ca có thật.
    from services.depth_detector import DepthObstacleDetector

    detector = DepthObstacleDetector(out)
    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "space_room.jpg"
    if fixture.is_file():
        boxes = detector.detect(fixture.read_bytes())
        print(f"\nThử trên {fixture.name}: {len(boxes)} vùng chắn đường")
        for box in boxes[:6]:
            print(
                f"  {box.label:<16} gần {box.confidence:.2f}  "
                f"[{box.x1:.2f},{box.y1:.2f} → {box.x2:.2f},{box.y2:.2f}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
