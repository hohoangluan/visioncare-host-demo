"""So prompt phân loại ý định bản DÀI với bản NGẮN: độ chính xác và độ trễ.

Chạy:
    python tools/bench_intent_prompt.py                 # 3 câu/nhãn = 48 câu
    python tools/bench_intent_prompt.py --per-label 5
    python tools/bench_intent_prompt.py --only-latency  # chỉ đo giờ, 6 câu

Rút prompt là đánh đổi: ít token thì nhanh hơn, nhưng mỗi luật bị cắt là một
kiểu câu bị phân loại sai. Script này bắt phải TRẢ SỐ cho cả hai vế thay vì
đoán, và dùng chính `data/intent/eval.jsonl` — bộ câu đã gán nhãn — làm bài
kiểm, nên "sai" ở đây là sai thật chứ không phải khác ý người đọc.

Tốn quota: 2 lệnh gọi Gemini cho mỗi câu (một bản dài, một bản ngắn).
"""
import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import config  # noqa: E402
from models import vlm  # noqa: E402
from pipeline import intent as intent_mod  # noqa: E402

LATENCY_PROBES = [
    "Đọc chữ trong ảnh giúp tôi",
    "Gọi điện cho mẹ",
    "Mở bài hát nơi này có anh",
    "Chỉ đường cho tôi tới chợ bến thành",
    "Hôm nay thời tiết thế nào",
    "Tăng âm lượng lên",
]


def _ask(template: str, text: str, state: dict | None,
         tries: int = 6, backoff: float = 4.0) -> tuple[str | None, float]:
    """Một lượt phân loại. Trả `(nhãn, giây)`; `nhãn=None` khi thử hết vẫn hỏng.

    THỬ LẠI, không bỏ mẫu. Lần chạy đầu bỏ mẫu khi gặp lỗi và mất 32/48 câu vì
    hết quota — còn lại 15 mẫu, đủ ít để chênh lệch "1.4 điểm" chỉ là đúng một
    câu. Một bài đo mà phần lớn mẫu biến mất thì không nói lên gì, mà lại trông
    y như một bài đo bình thường.

    Chỉ tính giờ ở lần gọi THÀNH CÔNG, không cộng thời gian chờ giữa các lần thử.
    """
    prompt = intent_mod._context_block(state) + template.format(command_text=text)
    for attempt in range(tries):
        started = time.perf_counter()
        try:
            reply = vlm.generate_json(
                prompt, schema=intent_mod._SCHEMA, model=config.GEMINI_INTENT_MODEL
            )
            elapsed = time.perf_counter() - started
            if isinstance(reply, dict) and reply.get("intent"):
                return reply["intent"], elapsed
        except Exception:  # noqa: BLE001
            pass
        time.sleep(backoff * (attempt + 1))
    return None, 0.0


def _sample(per_label: int, seed: int) -> list[dict]:
    rows = [json.loads(line) for line in
            (PROJ / "data" / "intent" / "eval.jsonl").open(encoding="utf-8")]
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    rng = random.Random(seed)
    out = []
    for label in sorted(by):
        pool = by[label]
        out += rng.sample(pool, min(per_label, len(pool)))
    rng.shuffle(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-label", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only-latency", action="store_true")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    variants = {
        "DÀI ": intent_mod._PROMPT_TEMPLATE_LONG,
        "NGẮN": intent_mod._PROMPT_TEMPLATE,
    }
    for name, tpl in variants.items():
        size = len(intent_mod._context_block({}) + tpl.format(command_text="x"))
        print(f"{name}: {size} ký tự, ~{size / 3.5:.0f} token")

    if not args.only_latency:
        rows = _sample(args.per_label, args.seed)
        print(f"\nĐộ chính xác trên {len(rows)} câu của eval.jsonl:", flush=True)
        results = {}
        for name, tpl in variants.items():
            ok = skipped = 0
            wrong = Counter()
            times = []
            for i, r in enumerate(rows):
                got, el = _ask(tpl, r["text"], None)
                times.append(el)
                if got is None:
                    skipped += 1
                elif got == r["label"]:
                    ok += 1
                else:
                    wrong[(r["label"], got)] += 1
                print(f"  {name} {i + 1}/{len(rows)}", end="\r", flush=True)
                time.sleep(0.4)
            checked = len(rows) - skipped
            acc = ok / checked * 100 if checked else 0.0
            results[name] = (acc, checked, wrong, times)
            print(f"  {name}: {acc:5.1f}%  ({ok}/{checked}"
                  f"{f', MẤT {skipped}' if skipped else ''})")
            for (gold, got), n in wrong.most_common(5):
                print(f"        {gold} -> {got}  ×{n}")

        a, b = results["DÀI "][0], results["NGẮN"][0]
        n_a, n_b = results["DÀI "][1], results["NGẮN"][1]
        print(f"\n  chênh lệch: {b - a:+.1f} điểm")

        # Một câu trong n mẫu đáng 100/n điểm. Chênh lệch nhỏ hơn ngần ấy thì
        # không phân biệt được với việc đổi đúng một câu, tức là chưa nói lên gì.
        smallest = 100 / min(n_a, n_b) if min(n_a, n_b) else 999
        # `<=` chứ không `<`: chênh lệch ĐÚNG BẰNG một câu cũng là không phân
        # biệt được. Lần chạy đầu ra -2.1 với n=48 (một câu = 2.08 điểm) và lọt
        # qua cửa `<` vì sai số dấu phẩy động — đúng cái nó sinh ra để chặn.
        if abs(b - a) <= smallest + 1e-9:
            print(f"  -> KHÔNG KẾT LUẬN ĐƯỢC: 1 câu đã đáng {smallest:.1f} điểm "
                  f"(n={min(n_a, n_b)}). Cần nhiều mẫu hơn.")
        if min(n_a, n_b) < len(rows) * 0.9:
            print("  -> CẢNH BÁO: mất quá nhiều mẫu, số trên không tin được.")

    print(f"\nĐộ trễ ({len(LATENCY_PROBES)} câu × {args.repeats} lần):", flush=True)
    for name, tpl in variants.items():
        times = []
        for _ in range(args.repeats):
            for probe in LATENCY_PROBES:
                got, el = _ask(tpl, probe, None)
                if got is not None:
                    times.append(el)
                time.sleep(0.4)
        if times:
            print(f"  {name}: median {statistics.median(times):.2f}s  "
                  f"min {min(times):.2f}s  max {max(times):.2f}s  (n={len(times)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
