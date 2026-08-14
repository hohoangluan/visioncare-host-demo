"""Kiểm lại nhãn của bộ dữ liệu ý định bằng một vòng gán nhãn ĐỘC LẬP.

Chạy:
    python tools/verify_intent_dataset.py            # báo cáo, không sửa file
    python tools/verify_intent_dataset.py --apply    # gỡ câu bị nghi ra file riêng

Vì sao cần: `gen_intent_dataset.py` bảo Gemini "viết N câu thuộc nhãn X" rồi
tin luôn nhãn đó. Ở vòng sinh câu SÁT RANH GIỚI thì niềm tin này hỏng — đo trên
mẻ đầu, model được giao viết câu 'chat' nhưng đẻ ra "đọc nhãn giúp",
"đọc hộ nhãn chai nước" (rõ ràng là `ocr`), và câu 'space' nhưng đẻ ra
"ở đây có vật cản không" (rõ ràng là `hazard`).

Vòng này hỏi lại theo chiều ngược: đưa câu, KHÔNG nói nhãn đã gán, bắt chọn
trong 16 nhãn. Lệch nhau thì câu đó vào diện nghi. Một câu sai nhãn trong tập
eval còn tệ hơn trong tập train — nó làm sai chính con số dùng để quyết định.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import config  # noqa: E402
from models import vlm  # noqa: E402
from tools.gen_intent_dataset import LABELS, OUT_DIR  # noqa: E402

BATCH = 25

_SCHEMA = {
    "type": "object",
    "properties": {
        "nhan": {"type": "array", "items": {"type": "string", "enum": list(LABELS)}},
    },
    "required": ["nhan"],
}


def _prompt(batch: list[str]) -> str:
    desc = "\n".join(f"- {k}: {v}" for k, v in LABELS.items())
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
    return (
        "Đây là các câu lệnh thoại của người khiếm thị dùng kính hỗ trợ, đã được "
        "máy nhận dạng giọng nói ghi lại.\n\n"
        f"Với MỖI câu, chọn đúng một nhãn ý định trong danh sách:\n\n{desc}\n\n"
        "Chỉ đọc bản thân câu, đừng đoán theo thứ tự hay theo câu bên cạnh — "
        "các câu này không liên quan gì tới nhau.\n\n"
        f"Các câu:\n{numbered}\n\n"
        f"Trả JSON: trường 'nhan' là mảng đúng {len(batch)} nhãn, theo đúng thứ tự trên."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="gỡ câu bị nghi khỏi train/eval")
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    ap.add_argument("--splits", default="train,eval")
    args = ap.parse_args()

    suspect_path = OUT_DIR / "suspect.jsonl"
    all_suspect = []
    summary = Counter()

    for split in args.splits.split(","):
        path = OUT_DIR / f"{split}.jsonl"
        rows = [json.loads(line) for line in path.open(encoding="utf-8")]
        print(f"\n=== {split}.jsonl ({len(rows)} câu) ===", flush=True)

        verdicts: list[str | None] = []
        for i in range(0, len(rows), BATCH):
            batch = [r["text"] for r in rows[i:i + BATCH]]
            try:
                reply = vlm.generate_json(_prompt(batch), schema=_SCHEMA, model=args.model)
                got = reply.get("nhan") if isinstance(reply, dict) else None
            except Exception as exc:  # noqa: BLE001
                print(f"  lô {i}: LỖI {exc}", file=sys.stderr)
                got = None
            # Lệch độ dài nghĩa là không ghép được câu với nhãn -> bỏ cả lô,
            # đừng ghép lệch một ô rồi báo cả lô là sai nhãn.
            if not isinstance(got, list) or len(got) != len(batch):
                verdicts += [None] * len(batch)
            else:
                verdicts += [g if g in LABELS else None for g in got]
            print(f"  {min(i + BATCH, len(rows))}/{len(rows)}", end="\r", flush=True)

        suspect = [
            {"text": r["text"], "label": r["label"], "verify": v, "split": split}
            for r, v in zip(rows, verdicts)
            if v is not None and v != r["label"]
        ]
        checked = sum(1 for v in verdicts if v is not None)
        agree = checked - len(suspect)
        print(f"  kiểm được {checked}/{len(rows)} — khớp {agree} "
              f"({agree / max(checked, 1) * 100:.1f}%), nghi {len(suspect)}")

        for s in suspect:
            summary[(s["label"], s["verify"])] += 1
        all_suspect += suspect

        if args.apply and suspect:
            bad = {s["text"] for s in suspect}
            kept = [r for r in rows if r["text"] not in bad]
            with path.open("w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  -> giữ lại {len(kept)}, gỡ {len(rows) - len(kept)}")

    print(f"\nTổng nghi: {len(all_suspect)}")
    print("Cặp lệch nhiều nhất (nhãn đã gán -> nhãn kiểm lại):")
    for (a, b), n in summary.most_common(12):
        print(f"  {a:16s} -> {b:16s} {n}")

    with suspect_path.open("w", encoding="utf-8") as f:
        for s in all_suspect:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"\n-> {suspect_path}")
    if not args.apply:
        print("Chạy lại với --apply để gỡ chúng khỏi train/eval.")
    else:
        print("Đã gỡ. Câu bị gỡ vẫn nằm trong suspect.jsonl — SOÁT LẠI, vì vòng "
              "kiểm này cũng là model, nó sai được như vòng sinh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
