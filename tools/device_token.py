"""Quản lý token riêng của từng kính (Plan 2 / C0).

    python tools/device_token.py add <device_id> [--file PATH] [--force]
    python tools/device_token.py list [--file PATH]

`add` sinh token ngẫu nhiên 256 bit, IN ĐÚNG MỘT LẦN ra stdout (nạp vào firmware/.env của kính), chỉ ghi
sha256 hex vào file JSON `{"<device_id>": "<sha256 hex>"}` (mặc định `VISIONCARE_DEVICE_TOKENS` hoặc
`data/device_tokens.json`). Server không bao giờ giữ token gốc; mất token thì `add --force` để xoay.
Server tự nạp lại file khi mtime đổi (trong ~2 giây), không cần restart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402

DEFAULT_FILE = os.path.join("data", "device_tokens.json")


def _path(arg: str | None) -> str:
    path = arg or config.VISIONCARE_DEVICE_TOKENS or DEFAULT_FILE
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: không phải object JSON")
    return data


def _write(path: str, data: dict) -> None:
    """Ghi nguyên tử (tmp + rename) với quyền 0600: server đang đọc file này không bao giờ thấy file dở."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".device_tokens.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def add(device_id: str, path: str, force: bool = False) -> str:
    device_id = device_id.strip()
    if not device_id or len(device_id) > 64:
        raise SystemExit("device_id rỗng hoặc dài hơn 64 ký tự")
    data = _read(path)
    if device_id in data and not force:
        raise SystemExit(f"{device_id} đã có token ({path}); dùng --force để xoay token (token cũ mất hiệu lực)")
    token = secrets.token_urlsafe(32)
    data[device_id] = hashlib.sha256(token.encode()).hexdigest()
    _write(path, data)
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="sinh token cho một kính, in một lần")
    p_add.add_argument("device_id")
    p_add.add_argument("--force", action="store_true", help="xoay token của kính đã có")
    p_list = sub.add_parser("list", help="liệt kê device_id đã có token (không in hash)")
    for p in (p_add, p_list):
        p.add_argument("--file", default=None)
    args = parser.parse_args(argv)
    path = _path(args.file)
    if args.cmd == "add":
        token = add(args.device_id, path, args.force)
        print(f"device_id: {args.device_id}\nfile:      {path}", file=sys.stderr)
        print("token (chỉ hiện một lần):", file=sys.stderr)
        print(token)
    else:
        for device in sorted(_read(path)):
            print(device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
