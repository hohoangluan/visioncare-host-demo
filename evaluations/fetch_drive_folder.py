"""Tải mọi file trong một thư mục Google Drive công khai (không cần tài khoản/API key).

gdown chỉ lấy 50 file/thư mục; trang `embeddedfolderview` liệt kê đủ, rồi tải từng file qua
`drive.usercontent.google.com`. Chạy lại được: file đã có (kích thước > 0) thì bỏ qua.

    python3 fetch_drive_folder.py <folder_id> <thư_mục_đích> [--workers 8]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LIST_URL = "https://drive.google.com/embeddedfolderview?id={}"
FILE_URL = "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
ENTRY = re.compile(
    r'href="https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)/[^"]*".*?flip-entry-title">([^<]+)<', re.S
)


def list_folder(folder_id: str) -> list[tuple[str, str]]:
    page = urllib.request.urlopen(LIST_URL.format(folder_id), timeout=60).read().decode("utf-8", "replace")
    return [(fid, html.unescape(name).strip()) for fid, name in ENTRY.findall(page)]


def fetch(fid: str, dest: Path, tries: int = 6) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(FILE_URL.format(fid), timeout=120) as r:
                data = r.read()
            if data[:15].lower().startswith(b"<!doctype html"):  # trang lỗi/quota thay vì file
                raise IOError("nhận về HTML thay vì file")
            tmp.write_bytes(data)
            tmp.rename(dest)
            return True
        except Exception as exc:  # mạng chập chờn / Drive giới hạn tốc độ
            wait = 5 * 2 ** attempt
            print(f"thử lại {dest.name} sau {wait}s: {exc}", file=sys.stderr)
            time.sleep(wait)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder_id")
    ap.add_argument("dest")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    entries = list_folder(args.folder_id)
    print(f"{dest.name}: {len(entries)} file trong thư mục Drive", flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        ok = list(pool.map(lambda e: fetch(e[0], dest / Path(e[1]).name), entries))
    failed = [name for (_, name), good in zip(entries, ok) if not good]
    print(f"{dest.name}: xong {len(entries) - len(failed)}/{len(entries)}", flush=True)
    if failed:
        print(f"{dest.name}: LỖI {len(failed)} file, ví dụ {failed[:5]} — chạy lại để tải tiếp", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
