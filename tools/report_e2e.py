"""Bảng báo cáo end-to-end: tốc độ TỪNG CHẶNG + độ chính xác, theo chức năng.

Khác `bench_e2e.py` và `measure_budget.py`, và cả ba đều cần:

    bench_e2e.py      đo từ NGOÀI  — headers / tiếng đầu / tổng / tỉ lệ nhả.
                                     Không biết bên trong server làm gì.
    measure_budget.py đọc trace    — TTFB theo intent, đối chiếu ngân sách G1.
                                     Không tự sinh lưu lượng.
    report_e2e.py     GHÉP hai cái — chạy đủ 16 chức năng, rồi ghép mỗi lượt
                                     với ĐÚNG dòng trace của nó bằng `turn_id`.

Ghép được là điều mới: từ đó một dòng bảng nói trọn một lượt —

    kính gửi ─► headers ─► [stt] ─► [intent] ─► [handler] ─► [action] ─► tiếng đầu ─► xong
                            ↑ đọc từ turn_trace          ↑ chờ điện thoại

và cột "đúng ý định" đối chiếu nhãn kỳ vọng với nhãn bộ phân loại thật sự chọn.

🔴 Chạy QUA TUNNEL, không qua 127.0.0.1
---------------------------------------
    python tools/report_e2e.py --host api.visioncare-host.uk --port 443

`127.0.0.1:8000` là một đường không tồn tại với board thật: thiếu TLS và thiếu
Cloudflare. Số đo trên đó không so sánh được với bất cứ thứ gì.

🔴 KHÔNG chạy khi không có app điện thoại
------------------------------------------
`contact_call`, `music_*`, `nav_*`, `ride_*` sẽ chờ TRỌN timeout 25-40 giây mỗi
lượt vì không máy nào trả `ActionResult`. Đó không phải hỏng — nó là con số
thật của ca "không có điện thoại", và cột `action` sẽ ghi đúng như vậy. Dùng
`--only` để bỏ nhóm đó khi chỉ muốn đo đường thuần server:

    python tools/report_e2e.py --host api.visioncare-host.uk --port 443 \
        --only ocr,find,money,space,hazard,chat,unknown
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 🔴 Windows: stdout mặc định là cp1252 và mọi dòng in ở đây đều có tiếng Việt.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from tools.bench_e2e import BOARD_ACCEPT, run_one, _ratio, _board_wait  # noqa: E402
from tools.make_board_audio import COMMANDS  # noqa: E402


# Nhãn intent mà mỗi câu lệnh PHẢI ra. Khoá là tên ca trong `COMMANDS`; giá trị
# là nhãn `schemas.Intent`. Hai cái trùng tên ở hầu hết ca, nhưng không phải
# tất cả — nên viết ra thay vì suy.
EXPECTED_INTENT: dict[str, str] = {
    "ocr": "ocr",
    "find": "find",
    "money": "money",
    "space": "space",
    # 🔴 ĐỔI 2026-08-25: "phía trước có gì nguy hiểm không" giờ BẬT CHẾ ĐỘ CANH
    # thay vì trả lời một câu. Bộ phân loại vẫn ra nhãn `hazard`; cái đổi là
    # định tuyến (xem pipeline/router.py).
    "hazard": "hazard",
    "chat": "chat",
    "nav_start": "nav_start",
    "nav_stop": "nav_stop",
    "contact_call": "contact_call",
    "emergency_call": "emergency_call",
    "ride_quote": "ride_quote",
    "ride_confirm": "ride_confirm",
    "music_play": "music_play",
    "music_stop": "music_stop",
    "music_volume": "music_volume",
    # Câu vô nghĩa: đúng hành vi là rơi về `chat`, KHÔNG phải một nhãn "unknown"
    # nào đó. Người dùng nói gì cũng phải được trả lời.
    "unknown": "chat",
}

# Chức năng có bàn giao việc sang điện thoại. Cột `action` chỉ có nghĩa ở đây.
HAS_ACTION = {
    "nav_start", "nav_stop", "contact_call", "emergency_call",
    "ride_quote", "ride_confirm", "music_play", "music_stop", "music_volume",
}

DEVICE_ID = "bench-report"


def _traces(base_url: str, limit: int = 200) -> dict[str, dict]:
    """Đọc sổ trace, khoá theo `turn_id`.

    Loopback-only theo thiết kế (`app.list_traces`) — nên tool này phải chạy
    TRÊN máy server, kể cả khi nó bắn lưu lượng qua tunnel.
    """
    url = f"{base_url.rstrip('/')}/internal/traces?limit={limit}"
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {config.VISIONCARE_CALLBACK_TOKEN}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    out: dict[str, dict] = {}
    for row in payload["data"]["traces"]:
        turn = row.get("turn_id")
        if turn:
            out[str(turn)] = row
    return out


def _fmt_ms(value) -> str:
    return "—" if value is None else f"{float(value):.0f}"


def _fmt_s(value) -> str:
    return "—" if value is None else f"{float(value) / 1000:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="api.visioncare-host.uk")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument(
        "--trace-url", default="http://127.0.0.1:8000",
        help="nơi đọc /internal/traces (loopback, KHÔNG qua tunnel)",
    )
    parser.add_argument("--only", default="", help="danh sách tên ca, phẩy ngăn cách")
    parser.add_argument(
        "--device", default=DEVICE_ID,
        help="🔴 Đặt `glasses-01` (kính ĐÃ GHÉP ĐÔI) để đo THẬT cột `action`. "
             "Làm thế nghĩa là bắn lệnh thật xuống điện thoại: `contact_call` "
             "gọi thật, `ride_confirm` ĐẶT XE THẬT, `emergency_call` gọi số "
             "liên hệ khẩn cấp đã cài. Mặc định là một device_id chưa ghép đôi "
             "nên mọi action hỏng sớm và an toàn.",
    )
    parser.add_argument("--gap", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=200.0)
    parser.add_argument(
        "--out", default=os.path.join("docs", "tasks", "measurements", "E2E.md")
    )
    args = parser.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(COMMANDS)

    # 🔴 `emergency_call` chạy CUỐI CÙNG, luôn luôn.
    #
    # Nó là thứ duy nhất trong bảng có thể gọi ra ngoài đời thật. Đặt cuối
    # nghĩa là mọi con số khác đã đo xong trước khi nó chạy — nếu phải dừng gấp
    # thì không mất cả phiên đo.
    if "emergency_call" in names:
        names = [n for n in names if n != "emergency_call"] + ["emergency_call"]

    rows: list[dict] = []
    for index, name in enumerate(names):
        turn_id = f"report-{name}-{uuid.uuid4().hex[:8]}"
        print(f"... {name}", flush=True)
        started = time.monotonic()
        result = run_one(
            args.host, args.port, name,
            timeout=args.timeout, accept=BOARD_ACCEPT,
            device_id=args.device, turn_id=turn_id,
        )
        rows.append({
            "name": name,
            "turn_id": turn_id,
            "result": result,
            "wall": time.monotonic() - started,
        })
        if index + 1 < len(names):
            time.sleep(args.gap)

    # Đọc trace SAU khi chạy hết: một lần gọi thay vì mỗi lượt một lần, và sổ
    # giữ 200 lượt nên 16 lượt vừa chạy chắc chắn còn nguyên.
    try:
        traces = _traces(args.trace_url)
    except (urllib.error.URLError, OSError) as exc:
        print(f"🔴 Không đọc được /internal/traces ({exc}). Bảng sẽ thiếu cột chặng.")
        traces = {}

    lines: list[str] = []
    lines.append("# E2E — tốc độ từng chặng và độ chính xác, theo chức năng")
    lines.append("")
    lines.append(f"Đo {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
                 f"thiết bị `{args.device}` · "
                 f"qua `{args.host}:{args.port}`"
                 + ("  🔴 **KHÔNG phải tunnel**" if args.port != 443 else " (tunnel + TLS)"))
    lines.append("")
    lines.append("## Cấu hình lúc đo")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| `RESPONSE_FORMAT` | `{config.RESPONSE_FORMAT}` |")
    lines.append(f"| `AUDIO_PREROLL_MODE` | `{config.AUDIO_PREROLL_MODE}` |")
    lines.append(f"| `AUDIO_PREROLL_SECONDS` | {config.AUDIO_PREROLL_SECONDS} |")
    lines.append(f"| `GEMINI_MODEL` | `{config.GEMINI_MODEL}` |")
    lines.append(f"| `GEMINI_INTENT_MODEL` | `{config.GEMINI_INTENT_MODEL}` |")
    lines.append(f"| `GEMINI_OCR_MODEL` | `{config.GEMINI_OCR_MODEL}` |")
    lines.append("")
    lines.append("## Bảng 1 — một lượt, từng chặng (mili giây)")
    lines.append("")
    lines.append(
        "`headers` là lúc server trả dòng trạng thái; `tiếng đầu` là byte AUDIO "
        "đầu tiên (thứ người dùng thật sự nghe thấy); `tổng` là lúc byte cuối "
        "tới. `stt`/`intent`/`handler`/`action` đọc từ `turn_trace` của chính "
        "lượt đó, ghép bằng `turn_id`."
    )
    lines.append("")
    lines.append(
        "| Chức năng | mã | headers | **tiếng đầu** | tổng | stt | intent | "
        "handler | action | audio | nhả | đệm board | ý định |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    ok_intent = 0
    counted_intent = 0
    for row in rows:
        name = row["name"]
        res = row["result"]
        trace = traces.get(row["turn_id"], {})

        if res.error:
            lines.append(
                f"| `{name}` | — | — | — | — | — | — | — | — | — | — | — | "
                f"🔴 {res.error} |"
            )
            continue

        got = trace.get("intent")
        want = EXPECTED_INTENT.get(name)
        if name == "emergency_call":
            # Không đi qua bộ phân loại (cổng từ khoá, bước 1 của router). Ghi
            # rõ ra thay vì để "—" trông như một phép đo hỏng.
            verdict = "✅ cổng từ khoá"
        elif got is not None and want is not None:
            counted_intent += 1
            correct = str(got) == want
            ok_intent += correct
            verdict = "✅" if correct else f"🔴 ra `{got}`"
        else:
            verdict = "—"

        ratio = _ratio(res)
        action = trace.get("action_ms")
        # 🔴 Phân biệt "điện thoại trả lời trong X ms" với "hết giờ ở X ms".
        #
        # Hai thứ đó ra CÙNG một con số trong cột này và có nghĩa ngược nhau.
        # Đo được 2026-08-25: mọi action đều ~2000 ms — đúng bằng
        # `VISIONCARE_FAST_ACTION_SECONDS`, tức app Android nhận `202 Accepted`
        # rồi KHÔNG trả `ActionResult` nào. Đọc bảng mà không có dấu này sẽ ra
        # kết luận "điện thoại phản hồi trong 2 giây, khá nhanh" — sai hoàn
        # toàn, thực tế là **không phản hồi**.
        if action is not None and not trace.get("action_ok"):
            action_cell = f"{float(action):.0f} 🔴hết giờ"
        else:
            action_cell = _fmt_ms(action)
        lines.append(
            f"| `{name}` | {res.status} | {res.t_headers * 1000:.0f} | "
            f"**{res.t_first_audio * 1000:.0f}** | {res.t_total * 1000:.0f} | "
            f"{_fmt_ms(trace.get('stt_ms'))} | {_fmt_ms(trace.get('intent_ms'))} | "
            f"{_fmt_ms(trace.get('handler_ms'))} | "
            f"{action_cell if name in HAS_ACTION else '·'} | "
            f"{res.audio_seconds:.2f}s | {ratio:.2f}× | {_board_wait(ratio)} | "
            f"{verdict} |"
        )

    lines.append("")
    lines.append("### Đọc bảng trên")
    lines.append("")
    lines.append(
        "**Cột `action`.** `·` = chức năng không bàn giao việc sang điện thoại. "
        "`—` = có bàn giao nhưng chặng đó không chạy tới nơi."
    )
    lines.append("")
    lines.append(
        "🔴 **`X 🔴hết giờ` nghĩa là app Android nhận `202 Accepted` rồi KHÔNG "
        "trả `ActionResult` nào trong `VISIONCARE_FAST_ACTION_SECONDS`.** Con "
        "số đó là ĐỘ DÀI CỬA SỔ CHỜ, không phải tốc độ điện thoại. Đọc nhầm nó "
        "thành 'điện thoại phản hồi trong 2 giây' là kết luận ngược hẳn với "
        "sự thật — thực tế là **không phản hồi**."
    )
    lines.append("")
    lines.append(
        "🔴 `—` ở đây gần như luôn có MỘT nguyên nhân: **kính chưa ghép đôi với "
        "điện thoại**. Server app trả `404 GLASSES_DEVICE_NOT_LINKED` ngay ở "
        "lời gọi đầu, nên `run_action()` hỏng trước khi kịp chờ `ActionResult` "
        "— `handler` vì thế chỉ vài chục ms và trông *nhanh*, trong khi thực "
        "tế chức năng đó **không chạy được**. Đừng đọc mấy dòng đó là 'đạt'."
    )
    lines.append("")
    lines.append(
        "Muốn đo thật cột này thì phải ghép đôi trước "
        "(`POST /internal/device/pair`) và có app Android chạy để trả "
        "`ActionResult`. Sổ ghép đôi nằm trong RAM nên **mất sau mỗi lần khởi "
        "động lại server** — xem câu hỏi còn mở #7."
    )
    lines.append("")
    lines.append(
        "**Cột `intent` của `emergency_call` là `—`, và đó là ĐÚNG.** Gọi cấp "
        "cứu đi qua cổng từ khoá ở bước 1 của router, **không** qua bộ phân "
        "loại ý định — spec mục 10: *không đi qua bất kỳ bước xác minh nào*. "
        "Một ngày nào đó dòng này có số ở cột `intent` thì nghĩa là ngoại lệ "
        "tuyệt đối đó đã bị gỡ mất."
    )
    lines.append("")

    # ── tổng hợp ──────────────────────────────────────────────────────────
    good = [r["result"] for r in rows if not r["result"].error]
    lines.append("## Bảng 2 — tổng hợp")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    if good:
        firsts = sorted(r.t_first_audio for r in good)
        lines.append(f"| Tiếng đầu, trung vị | **{statistics.median(firsts):.2f}s** |")
        lines.append(f"| Tiếng đầu, chậm nhất | {firsts[-1]:.2f}s |")
        lines.append(
            f"| Dưới 1 giây | {sum(1 for f in firsts if f < 1.0)}/{len(firsts)} |"
        )
        rates = sorted(_ratio(r) for r in good)
        lines.append(f"| Tỉ lệ nhả, thấp nhất | {rates[0]:.2f}× |")
        lines.append(
            f"| Số ca board phải chờ hết mới phát | "
            f"{sum(1 for x in rates if x < 1.12)}/{len(rates)} |"
        )
    if counted_intent:
        lines.append(
            f"| **Độ chính xác ý định** | **{ok_intent}/{counted_intent}** "
            f"({100.0 * ok_intent / counted_intent:.0f}%) |"
        )
    lines.append(f"| Số ca lỗi | {sum(1 for r in rows if r['result'].error)}/{len(rows)} |")
    lines.append("")
    lines.append("🔴 **Độ chính xác ở đây CHỈ là độ chính xác phân loại ý định** "
                 "trên 16 câu mẫu — không phải độ chính xác nội dung câu trả lời. "
                 "OCR đọc đúng chữ hay không, mô tả cảnh có đúng không, `hazard` "
                 "bắt được vật cản hay không: những thứ đó đo ở "
                 "`measurements/T24.md` và `measurements/H4.md`, không đo được "
                 "bằng một vòng bench.")

    text = "\n".join(lines) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print()
    print(text)
    print(f"Đã ghi {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
