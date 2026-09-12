"""Tải bộ ảnh THẬT để kiểm thử `hazard_watch` (T24/W4).

Vì sao cần tool này
-------------------
`tests/fixtures/` chỉ có 4 ảnh và cả 4 đều là cảnh chụp đồ vật trên bàn —
chúng sinh ra cho `find_object`/`read_money`/`ocr`, không phải cho câu hỏi
*"có gì chắn đường tôi không"*. Chỉnh `DEPTH_NEAR_THRESHOLD` trên 4 ảnh đó là
chỉnh một ngưỡng đi bộ bằng ảnh chụp cái bàn.

Tool này kéo ảnh từ Wikimedia Commons (giấy phép tự do, không cần khoá) theo
hai nhóm ĐỐI LẬP:

    blocked/   cột, trụ chắn, bậc thềm, tường, cửa kính — phải kêu
    clear/     vỉa hè trống, hành lang trống, đường thoáng — phải im

🔴 Kết quả tìm kiếm của Commons **nhiễu**. Tool này chỉ TẢI, không dán nhãn
tin được: ảnh "vỉa hè trống" hay dính một bức tường sát bên. Phải mở từng ảnh
xem rồi mới chốt nhãn — `tests/data/hazard/labels.json` là nhãn người xác
nhận, và nó mới là thứ bộ đo dùng.

Dùng:
    python tools/fetch_hazard_testset.py           # tải theo mặc định
    python tools/fetch_hazard_testset.py --per 6   # nhiều ảnh mỗi từ khoá hơn
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 🔴 Windows: stdout mặc định là cp1252, và MỌI dòng in của tool này đều có
# tiếng Việt. Không có ba dòng dưới thì tool chạy XONG việc rồi chết ở lệnh
# `print` cuối — nhìn từ ngoài giống hệt "tool hỏng", trong khi file đã ghi.
# Đã dính thật với `publish_firmware.py` (bản đã phát hành, chỉ crash lúc in).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


API = "https://commons.wikimedia.org/w/api.php"
UA = "VisionCare-HazardTestset/1.0 (glasses for blind users; research)"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "data" / "hazard"

# Từ khoá chọn theo thứ người khiếm thị THẬT SỰ va vào, không theo 80 lớp COCO.
# Cột điện / trụ chắn / bậc thềm / cửa kính đều KHÔNG nằm trong COCO — đó
# chính là lý do đường độ sâu tồn tại.
QUERIES = {
    "blocked": [
        "utility pole sidewalk",
        "bollard pedestrian street",
        "staircase steps entrance",
        "brick wall alley",
        "glass door entrance building",
        "tree trunk park path",
        "construction barrier sidewalk",
        "fence gate path",
    ],
    "clear": [
        "empty sidewalk street",
        "empty corridor hallway",
        "empty pedestrian street",
        "park path trees",
        "open road countryside",
        "airport terminal walkway",
    ],
}


def search(term: str, limit: int) -> list[tuple[str, str]]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}",
        "gsrlimit": str(limit),
        "gsrnamespace": "6",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "640",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    found = []
    for page in payload.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        thumb = info.get("thumburl")
        if thumb:
            found.append((page["title"], thumb))
    return found


def download(url: str, dest: Path) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    # Commons trả 429 khá sớm khi tải liên tiếp. Lùi dần rồi thử lại — bỏ ảnh
    # vì một lần 429 làm bộ đo thủng lỗ chỗ theo cách khó nhận ra sau này.
    data = b""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                print(f"   bo qua ({exc})")
                return False
            time.sleep(2 ** attempt)
    if len(data) < 5_000:
        print("   bo qua (anh qua nho)")
        return False
    dest.write_bytes(data)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per", type=int, default=4, help="số ảnh mỗi từ khoá")
    args = parser.parse_args()

    manifest: dict[str, dict] = {}
    manifest_path = OUT / "sources.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text("utf-8"))

    total = 0
    for group, terms in QUERIES.items():
        folder = OUT / group
        folder.mkdir(parents=True, exist_ok=True)
        for term in terms:
            print(f"[{group}] {term}")
            try:
                hits = search(term, args.per)
            except Exception as exc:  # noqa: BLE001
                print(f"   tìm hỏng: {exc}")
                continue

            for title, url in hits:
                stem = title.removeprefix("File:").rsplit(".", 1)[0]
                stem = "".join(c if c.isalnum() else "_" for c in stem)[:48]
                suffix = ".jpg" if ".jp" in url.lower() else ".png"
                dest = folder / f"{stem}{suffix}"
                if dest.is_file():
                    continue
                if download(url, dest):
                    total += 1
                    manifest[f"{group}/{dest.name}"] = {
                        "title": title,
                        "url": url,
                        "query": term,
                        # 🔴 nhãn GỢI Ý theo nhóm tìm kiếm, CHƯA ai xem.
                        # `labels.json` mới là nhãn tin được.
                        "suggested": group,
                    }
                    print(f"   + {dest.name}")
                # 🔴 Commons chặn 429 rất sớm. 1.0 s vẫn ăn 429 ở phần lớn
                # ảnh (đo 2026-08-24: 12/56 tải được). 2.5 s thì qua.
                time.sleep(2.5)

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    print(f"\nTải xong {total} ảnh mới → {OUT}")
    print("🔴 Nhãn trong sources.json chỉ là GỢI Ý theo từ khoá. Mở ảnh xem rồi")
    print("   ghi nhãn thật vào tests/data/hazard/labels.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
