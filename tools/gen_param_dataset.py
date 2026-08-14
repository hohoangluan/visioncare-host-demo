"""Sinh dữ liệu cho các head tham số chạy cục bộ.

Chạy:
    python tools/gen_param_dataset.py
    python tools/gen_param_dataset.py --only chat_location

Ba head này giải quyết phần tham số mà SetFit LÀM ĐƯỢC, vì chúng là bài PHÂN
LOẠI chứ không phải trích chuỗi con:

    chat_location   needs_location  true/false
    chat_web        needs_web       true/false
    volume_direction  direction     up/down
    ride_confirm    confirm         true/false

Những tham số còn lại (`destination`, `contact_name`, `song`, `volume` dạng số,
`emergency_number`) là TRÍCH SPAN — tên riêng, địa danh, tên bài hát. Không head
phân loại nào làm được, và cũng là chỗ sai thì hậu quả thật (dẫn nhầm đường, gọi
nhầm người), nên chúng ở lại với Gemini.

Đầu ra: `data/intent/params_<task>.jsonl`, mỗi dòng `{"text", "label"}`.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import config  # noqa: E402
from models import vlm  # noqa: E402
from pipeline import stt  # noqa: E402
from tools.gen_intent_dataset import _REALISM  # noqa: E402

OUT_DIR = PROJ / "data" / "intent"

_SCHEMA = {
    "type": "object",
    "properties": {"cau": {"type": "array", "items": {"type": "string"}}},
    "required": ["cau"],
}

# task -> (nhãn, mô tả kiểu câu cần sinh cho nhãn đó)
TASKS: dict[str, dict[str, str]] = {
    "chat_location": {
        "true":
            "câu trò chuyện/hỏi đáp mà CÂU TRẢ LỜI PHỤ THUỘC người dùng đang "
            "đứng ở đâu. Gồm cả cách nói mang nghĩa 'chỗ tôi đang đứng' mà "
            "không đọc ra địa chỉ: gần nhất, gần đây, quanh đây, ở đây, lân "
            "cận, xung quanh. Ví dụ: 'nhà thuốc gần nhất ở đâu', 'quanh đây có "
            "quán ăn không', 'trời hôm nay thế nào', 'tôi đang ở đâu', "
            "'bao xa tới đó'",
        "false":
            "câu trò chuyện/hỏi đáp mà ở đâu cũng trả lời như nhau — kiến thức "
            "chung, tính toán, định nghĩa, kể chuyện, xã giao, hỏi giờ. "
            "Ví dụ: 'mấy giờ rồi', 'kể chuyện cười đi', 'một cân bằng bao nhiêu "
            "gam', 'ai viết truyện kiều'",
    },
    "chat_web": {
        "true":
            "câu hỏi mà câu trả lời ĐỔI THEO NGÀY và phải tra cứu mới biết — "
            "thời tiết, tin tức, tỉ số bóng đá, giá vàng, giá xăng, giờ mở cửa, "
            "sự kiện đang diễn ra, phim đang chiếu",
        "false":
            "câu hỏi trả lời được bằng kiến thức chung hoặc tính toán, không "
            "cần tra cứu gì mới — định nghĩa, lịch sử, cách làm, xã giao, than "
            "thở, kể chuyện, hoặc hỏi về chính cuộc trò chuyện này",
    },
    "volume_direction": {
        "up": "câu lệnh TĂNG âm lượng, vặn to lên, nghe không rõ muốn to hơn",
        "down": "câu lệnh GIẢM âm lượng, vặn nhỏ lại, thấy ồn quá muốn bé đi",
    },
    "ride_confirm": {
        "true":
            "câu XÁC NHẬN đồng ý đặt chuyến xe vừa được báo giá — đúng rồi, ừ, "
            "được, đặt đi, ok, chốt",
        "false":
            "câu HUỶ / từ chối chuyến xe vừa được báo giá — thôi, không đi nữa, "
            "huỷ đi, khỏi, bỏ",
    },
}


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r"[.,!?;:\"'’“”…()\[\]/\\-]+", " ", text)
    return stt._normalize(re.sub(r"\s+", " ", text).strip())


def _ask(task: str, label: str, desc: str, n: int, model: str) -> list[str]:
    prompt = (
        f"Viết {n} câu thoại tiếng Việt khác nhau, tất cả cùng thuộc loại sau:\n\n"
        f"  {desc}\n\n{_REALISM}\n"
        f"Trả JSON có trường 'cau' là mảng {n} chuỗi."
    )
    reply = vlm.generate_json(prompt, schema=_SCHEMA, model=model)
    rows = reply.get("cau") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"[{task}/{label}] Gemini trả sai schema: {reply!r}")
    return [r for r in rows if isinstance(r, str) and r.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-label", type=int, default=60)
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    args = ap.parse_args()

    targets = [t for t in args.only.split(",") if t] or list(TASKS)
    bad = [t for t in targets if t not in TASKS]
    if bad:
        print(f"Task không tồn tại: {bad}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for task in targets:
        pool: dict[str, str] = {}
        conflicts = 0
        for label, desc in TASKS[task].items():
            print(f"[{task}/{label}] xin {args.per_label} câu...", flush=True)
            try:
                rows = _ask(task, label, desc, args.per_label, args.model)
            except Exception as exc:  # noqa: BLE001
                print(f"  LỖI: {exc}", file=sys.stderr)
                continue
            for r in rows:
                key = _clean(r)
                if len(key) < 2:
                    continue
                # Cùng một câu bị gán hai nhãn ngược nhau là mâu thuẫn, bỏ cả
                # hai — giữ lại chỉ dạy head đúng thứ nó không học được.
                if key in pool and pool[key] != label:
                    pool.pop(key)
                    conflicts += 1
                elif key not in pool:
                    pool[key] = label
            print(f"  nhận {len(rows)}, tổng giữ {len(pool)}", flush=True)

        path = OUT_DIR / f"params_{task}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for text, label in sorted(pool.items()):
                f.write(json.dumps({"text": text, "label": label}, ensure_ascii=False) + "\n")
        counts = Counter(pool.values())
        extra = f", bỏ {conflicts} câu mâu thuẫn" if conflicts else ""
        print(f"-> {path}  ({len(pool)} câu: {dict(counts)}{extra})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
