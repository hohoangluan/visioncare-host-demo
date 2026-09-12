"""T21/G1 — đo bảng ngân sách độ trễ thật, ghi ra `measurements/G1.md`.

Vì sao là một script chạy tay chứ không phải một test
-----------------------------------------------------
Máy CI chậm hơn máy dev, và `p95` của một lượt có gọi Gemini phụ thuộc **mạng**
chứ không phụ thuộc code. Đặt ngưỡng tuyệt đối vào CI thì nó đỏ ngẫu nhiên,
và một test đỏ ngẫu nhiên sẽ bị tắt trong vòng một tuần — sau đó không còn ai
phát hiện hồi quy độ trễ nữa. Phân công (T21 mục 6 câu 3):

  * `tests/test_latency_budget.py` — có deadline / không treo / trace đủ trường
  * script này — bảng số, chạy tay, trên máy chuẩn, ghi kèm ngày và cấu hình

Đọc số ở đâu ra
---------------
Không tự bấm giờ lại: script đọc thẳng `services.turn_trace.traces`, tức đúng
những con số production đã ghi. Đo bằng một đường riêng là đo một thứ khác với
thứ người dùng gặp.

🔴 Số chỉ có giá trị khi đo trên bản `API_USE_TLS 1` (T21/F10). Bản TLS=0 là
một cấu hình **không được phép phát hành**, nên chốt ngân sách trên nó là chốt
trên một thứ sắp bị vứt. Script ghi cấu hình đo được vào file kết quả để
không ai đọc nhầm một bảng cũ.

    # đo trên lưu lượng thật: bấm nút vài chục lượt rồi
    python tools/measure_budget.py --from-server http://127.0.0.1:8000

    # hoặc đo tại chỗ trong tiến trình này (không cần server chạy)
    python tools/measure_budget.py --replay
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from services import turn_trace  # noqa: E402

# Nguồn sự thật của bảng nằm trong test, không nhân bản ở đây: hai bảng số sẽ
# lệch nhau đúng vào ngày ai đó sửa một bên.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from test_latency_budget import BUDGET_MS, ROUTER_BUDGET_MS  # noqa: E402

# 🔴 Windows: stdout mặc định là cp1252, và MỌI dòng in của tool này đều có
# tiếng Việt. Không có ba dòng dưới thì tool chạy XONG việc rồi chết ở lệnh
# `print` cuối — nhìn từ ngoài giống hệt "tool hỏng", trong khi file đã ghi.
# Đã dính thật với `publish_firmware.py` (bản đã phát hành, chỉ crash lúc in).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")



def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _collect_local() -> list[dict[str, object]]:
    return [trace.as_dict() for trace in turn_trace.traces.recent()]


def _collect_remote(base_url: str) -> list[dict[str, object]]:
    url = f"{base_url.rstrip('/')}/internal/traces"
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"]["traces"]


def _report(rows: list[dict[str, object]]) -> str:
    by_intent: dict[str, list[float]] = defaultdict(list)
    rates: list[float] = []

    for row in rows:
        ttfb = row.get("ttfb_ms")
        intent = row.get("intent")
        if ttfb is not None and intent:
            by_intent[str(intent)].append(float(ttfb))
        rate = row.get("release_rate")
        if rate is not None:
            rates.append(float(rate))

    lines: list[str] = []
    lines.append("# G1 — bảng ngân sách độ trễ, số đo thật")
    lines.append("")
    lines.append(f"Ngày đo: {date.today().isoformat()}")
    lines.append(f"Số lượt góp vào bảng: **{len(rows)}**")
    lines.append("")
    lines.append("## Cấu hình lúc đo")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| `RESPONSE_FORMAT` | `{config.RESPONSE_FORMAT}` |")
    lines.append(f"| `AUDIO_PREROLL_MODE` | `{config.AUDIO_PREROLL_MODE}` |")
    lines.append(f"| `AUDIO_PREROLL_SECONDS` | {config.AUDIO_PREROLL_SECONDS} |")
    lines.append(f"| `GEMINI_MODEL` | `{config.GEMINI_MODEL}` |")
    lines.append(f"| `GEMINI_OCR_MODEL` | `{config.GEMINI_OCR_MODEL}` |")
    lines.append(f"| `INTENT_LOCAL_ENABLED` | {config.INTENT_LOCAL_ENABLED} |")
    lines.append("")
    lines.append(
        "🔴 **`API_USE_TLS` phía firmware KHÔNG đọc được từ đây** — nó là hằng "
        "biên dịch trong `app_config.h`. Ghi tay vào đây bản board đang chạy, "
        "và nếu là `0` thì bảng dưới **không dùng để chốt ngân sách được** "
        "(T21/F10)."
    )
    lines.append("")
    lines.append("## Dòng 1 — TTFB theo intent")
    lines.append("")
    lines.append("| Intent | Ngân sách | p50 | p95 | n | Đạt? |")
    lines.append("|---|---|---|---|---|---|")

    for intent in sorted(BUDGET_MS):
        budget = BUDGET_MS[intent]
        samples = by_intent.get(intent, [])
        if not samples:
            lines.append(f"| `{intent}` | {budget} ms | — | — | 0 | **chưa đo** |")
            continue
        p50 = _percentile(samples, 0.50)
        p95 = _percentile(samples, 0.95)
        verdict = "✅" if p95 <= budget else "🔴 VƯỢT"
        lines.append(
            f"| `{intent}` | {budget} ms | {p50:.0f} ms | {p95:.0f} ms | "
            f"{len(samples)} | {verdict} |"
        )

    lines.append("")
    lines.append("Ba đường của router (xử lý trước khi phân loại intent):")
    lines.append("")
    for name, budget in ROUTER_BUDGET_MS.items():
        lines.append(f"- `{name}` — ngân sách {budget} ms — **chưa tách được khỏi trace**")
    lines.append("")
    lines.append("## Dòng 2 — tỉ lệ nhả TTS (G11)")
    lines.append("")
    lines.append(
        "Đo `(giây tiếng)/(giây đồng hồ)` từ mảnh ĐẦU tới mảnh CUỐI. Dưới "
        f"{config.AUDIO_MIN_RELEASE_RATE}× thì board đợi nhận xong hết mới phát — "
        "TTFB đạt mà người dùng vẫn không nghe thấy gì sớm."
    )
    lines.append("")
    if rates:
        p50 = _percentile(rates, 0.50)
        p05 = _percentile(rates, 0.05)
        verdict = "✅" if p05 >= config.AUDIO_MIN_RELEASE_RATE else "🔴 VƯỢT"
        lines.append(f"| Ngưỡng | p50 | p05 (ca xấu) | n | Đạt? |")
        lines.append("|---|---|---|---|---|")
        lines.append(
            f"| ≥ {config.AUDIO_MIN_RELEASE_RATE}× | {p50:.2f}× | {p05:.2f}× | "
            f"{len(rates)} | {verdict} |"
        )
    else:
        lines.append("**Chưa đo** — không lượt nào trong sổ trace có `release_rate`.")

    lines.append("")
    lines.append("## Dòng nào chưa đo thì vì sao")
    lines.append("")
    lines.append(
        "Intent ghi `chưa đo` là intent chưa có lượt nào chạy qua trong sổ trace "
        "(200 lượt gần nhất). Không phải lỗi — chỉ nghĩa là chưa ai bấm nút cho "
        "đường đó. **Đừng điền số của intent khác vào** (AGENT_RULES mục A9)."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-server", help="đọc trace qua GET /internal/traces")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "docs/tasks/measurements/G1.md"),
    )
    args = parser.parse_args()

    rows = _collect_remote(args.from_server) if args.from_server else _collect_local()
    if not rows:
        print("Sổ trace rỗng — chưa có lượt nào để đo.")
        print("Chạy server, bấm nút vài chục lượt, rồi:")
        print("  python tools/measure_budget.py --from-server http://127.0.0.1:8000")
        return 1

    report = _report(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nĐã ghi {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
