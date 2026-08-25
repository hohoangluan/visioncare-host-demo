"""Phát hành một bản firmware cho OTA kéo qua internet (T25).

Chép file `.bin` vào `config.FIRMWARE_DIR` rồi ghi `latest.json` trỏ vào nó.
Chỉ sau bước ghi `latest.json` thì kính mới nhìn thấy bản mới — xem nguyên tắc
fail-closed ở đầu `services/firmware.py`.

    # phát hành bản vừa dựng
    python tools/publish_firmware.py \
        --bin "C:/.../your-eyes-esp32-firmware.ino.bin" \
        --version 2026.08.24-ota2

    # xem đang phát hành bản nào
    python tools/publish_firmware.py --show

    # quay về bản cũ (file đã có sẵn trong thư mục)
    python tools/publish_firmware.py --rollback 2026.08.24-ota1

Sau khi phát hành, kính tự bắt được ở vòng hỏi định kỳ (6 giờ). Muốn nó nạp
NGAY thì gọi thêm:

    curl -X POST http://127.0.0.1:8000/internal/firmware/push \
         -H "Authorization: Bearer $VISIONCARE_CALLBACK_TOKEN" \
         -H "Content-Type: application/json" -d '{"device_id":"glasses-01"}'
"""

from __future__ import annotations

import argparse
import hashlib
import json
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



def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pointer_path(root: Path) -> Path:
    return root / "latest.json"


def show(root: Path) -> int:
    pointer = _pointer_path(root)
    if not pointer.is_file():
        print(f"Chưa phát hành gì. ({pointer} không tồn tại)")
        print("Kính hỏi manifest sẽ nhận {'update': false, 'reason': 'NO_RELEASE'}.")
        return 0

    data = json.loads(pointer.read_text(encoding="utf-8"))
    binary = root / str(data.get("file", ""))
    print(f"Đang phát hành : {data.get('version')}")
    print(f"File           : {binary}  ({'CÓ' if binary.is_file() else '🔴 THIẾU'})")
    if binary.is_file():
        print(f"Kích thước     : {binary.stat().st_size} byte")
        print(f"sha256         : {_sha256(binary)}")
    print("\nCác bản có trong thư mục:")
    for item in sorted(root.glob("*.bin")):
        print(f"  {item.name}  ({item.stat().st_size} byte)")
    return 0


def publish(root: Path, source: Path, version: str) -> int:
    if not source.is_file():
        print(f"🔴 Không thấy file: {source}")
        return 1
    if not version:
        print("🔴 Thiếu --version")
        return 1

    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{version}.bin"

    # Ghi ra file tạm rồi đổi tên: một kính đang tải giữa chừng không bao giờ
    # đọc phải file viết dở.
    staging = target.with_suffix(".bin.part")
    shutil.copyfile(source, staging)
    staging.replace(target)

    digest = _sha256(target)
    _pointer_path(root).write_text(
        json.dumps(
            {"version": version, "file": target.name, "sha256": digest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"✅ Đã phát hành {version}")
    print(f"   {target}  ({target.stat().st_size} byte)")
    print(f"   sha256 {digest}")
    print("\n🔴 Kiểm lại FW_VERSION trong app_config.h của firmware có ĐÚNG bằng")
    print(f"   \"{version}\" không. Lệch nhau thì kính vừa nạp xong sẽ báo bản khác")
    print("   với bản đang phát hành, và nó sẽ nạp lại vô hạn mỗi 6 giờ.")
    return 0


def rollback(root: Path, version: str) -> int:
    target = root / f"{version}.bin"
    if not target.is_file():
        print(f"🔴 Không có bản {version} trong {root}")
        return 1
    _pointer_path(root).write_text(
        json.dumps(
            {"version": version, "file": target.name, "sha256": _sha256(target)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"✅ Đã quay về {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=config.FIRMWARE_DIR, help="thư mục firmware")
    parser.add_argument("--bin", help="file .bin vừa dựng")
    parser.add_argument("--version", help="tên phiên bản, phải khớp FW_VERSION của firmware")
    parser.add_argument("--show", action="store_true", help="xem đang phát hành bản nào")
    parser.add_argument("--rollback", help="quay về một bản đã có trong thư mục")
    args = parser.parse_args()

    root = Path(args.dir)
    if args.show:
        return show(root)
    if args.rollback:
        return rollback(root, args.rollback)
    if args.bin:
        return publish(root, Path(args.bin), args.version or "")
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
