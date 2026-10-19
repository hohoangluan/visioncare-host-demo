"""Dựng tập gold ý định cho voice server v2 (spec §4.1) — công cụ OFFLINE.

Chạy từng bước, mỗi bước ghi file trung gian vào `data/intent/gold_work/` nên
chạy lại không tốn quota sol:

    python -m tools.intent_gold.build --stage relabel     # sol gán lại nhãn mọi câu nguồn
    python -m tools.intent_gold.build --stage generate    # sol sinh ~600 câu mới theo "ô"
    python -m tools.intent_gold.build --stage adjudicate  # Gemma + đối chiếu + sol phân xử
    python -m tools.intent_gold.build --stage variants    # TTS -> nhiễu -> Zipformer
    python -m tools.intent_gold.build --stage split       # chia dev/test, ghi 4 file đầu ra
    python -m tools.intent_gold.build --stage all

Thứ tự `all` khác thứ tự liệt kê trong kế hoạch ở một điểm có chủ ý: `adjudicate`
chạy TRƯỚC `variants`. Biến thể STT mang nhãn của câu gốc, nên chỉ có nghĩa khi
nhãn đã chốt; làm ngược lại là tốn TTS cho cả những câu cuối cùng bị loại.

Quy ước:
- sol được gọi qua `tools.intent_gold.sol` (9router), tối đa 6 luồng song song.
- Quy mô cố ý NHỎ (200–300 dòng gộp biến thể, "đủ sài" theo yêu cầu 2026-10-19): ~165 câu
  nguồn phân tầng + ~40 câu sol sinh cho các ca dễ nhầm + biến thể STT ở MỘT mức SNR
  (10 dB) cho ~50 câu sạch. Hằng số ở `SOURCE_*`, `GEN_QUOTA`, `VARIANT_N`.
- Không bước nào tự đoán nhãn khi sol/Gemma bất đồng mà phân xử vẫn mơ hồ: câu đó
  vào `gold_review.jsonl` cho người duyệt (≤ 60), không vào dev/test.
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # VH
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.clef.client import LABELS  # noqa: E402
from tools.intent_gold import sol  # noqa: E402

DATA = ROOT / "data" / "intent"
SEED = 2026
TEST_RATIO = 0.4
REVIEW_CAP = 20

# Nhãn thuộc làn D (Phone Action) = HANDLERS trong `lanes/phone.py`. Sai ở đây là
# sai hành động thật (gọi nhầm người, đặt nhầm xe), nên review ưu tiên các nhãn này.
LANE_D = frozenset({
    "contact_call", "emergency_call", "nav_start", "nav_stop", "ride_quote",
    "ride_confirm", "music_play", "music_stop", "music_volume",
})
OCR_MODES = ("read", "summarize", "reread", "raw", "specialized")
VARIANTS = ("clean", "stt_snr20", "stt_snr10", "stt_snr5")
DEVICE_KEYS = ("music_playing", "navigating", "alerting", "ride_quote_pending")
PARAM_KEYS = ("contact_name", "destination", "song")

# ── Schema ───────────────────────────────────────────────────────────────

_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": ["string", "null"]} for k in PARAM_KEYS},
    "required": list(PARAM_KEYS),
    "additionalProperties": False,
}
_DEVICE_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "boolean"} for k in DEVICE_KEYS},
    "required": list(DEVICE_KEYS),
    "additionalProperties": False,
}
_LABEL_FIELDS = {
    "label": {"type": "string", "enum": list(LABELS)},
    "ocr_mode": {"type": "string", "enum": list(OCR_MODES)},
    "needs_web": {"type": "boolean"},
    "params": _PARAMS_SCHEMA,
}
RELABEL_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, **_LABEL_FIELDS,
                       "reason": {"type": "string"}},
        "required": ["id", *_LABEL_FIELDS, "reason"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}
ADJUDICATE_SCHEMA = {
    "type": "object",
    "properties": {**_LABEL_FIELDS, "uncertain": {"type": "boolean"},
                   "reason": {"type": "string"}},
    "required": [*_LABEL_FIELDS, "uncertain", "reason"],
    "additionalProperties": False,
}
GENERATE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "device": _DEVICE_SCHEMA,
                       **_LABEL_FIELDS},
        "required": ["text", "device", *_LABEL_FIELDS],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}

# ── Prompt ───────────────────────────────────────────────────────────────

_OCR_MODE_DOC = {
    "read": "đọc to chữ trong ảnh (mặc định cho mọi câu không phải ocr)",
    "summarize": "tóm tắt nội dung văn bản",
    "reread": "đọc lại nội dung vừa đọc lần trước, không chụp mới",
    "raw": "đọc nguyên văn, không dịch/chỉnh",
    "specialized": "văn bản chuyên ngành: thuốc, hợp đồng, kỹ thuật",
}


def label_guide() -> str:
    """Định nghĩa 17 nhãn + `ocr_mode` + `needs_web` + tham số + bối cảnh thiết bị."""
    labels = "\n".join(f"- {k}: {v}" for k, v in LABELS.items())
    modes = "\n".join(f"- {k}: {v}" for k, v in _OCR_MODE_DOC.items())
    return (
        "Bạn là người gán nhãn cho câu lệnh thoại của người khiếm thị đeo kính hỗ trợ. "
        "Câu là BẢN GHI STT: không dấu câu, có thể cụt (nhả nút sớm), có từ đệm, "
        "đôi khi nhận sai chữ. Gán ĐÚNG MỘT nhãn theo ý người nói với KÍNH.\n\n"
        f"Các nhãn:\n{labels}\n\n"
        "Quy tắc:\n"
        "- Câu KHÔNG phải lệnh cho kính (kể chuyện, nói với người khác như \"hôm qua tôi "
        "gọi cho mẹ rồi\", câu cụt không rõ ý, vô nghĩa, ngoài phạm vi) -> chat.\n"
        "- Chỉ gán nhãn hành động (contact_call, nav_start, ride_quote, music_play...) khi "
        "người nói đang YÊU CẦU kính làm việc đó ngay.\n"
        "- Câu tắt/dừng nói trống không (\"tắt đi\", \"dừng lại\") thì dựa vào bối cảnh thiết "
        "bị: đang phát nhạc -> music_stop; đang chỉ đường -> nav_stop; đang bật cảnh báo "
        "-> alert_off. Nếu bối cảnh không nêu rõ việc nào thì chat.\n"
        "- ride_confirm chỉ khi có chuyến xe đang chờ xác nhận hoặc câu nói rõ là đồng ý/huỷ "
        "chuyến xe.\n"
        f"- ocr_mode (chỉ có nghĩa khi nhãn là ocr, các nhãn khác để \"read\"):\n{modes}\n"
        "- needs_web = true nếu trả lời cần tra thông tin MỚI trên mạng (thời tiết, tin "
        "tức, giá vàng, tỉ số, giờ mở cửa, sự kiện); nhãn khác chat thì false.\n"
        "- params (làn D): contact_name khi contact_call; destination khi nav_start hoặc "
        "ride_quote; song khi music_play. Trích ĐÚNG chữ người nói, không sửa; "
        "không có thì null. Các nhãn khác: cả ba là null.\n"
        "- reason: một câu ngắn tiếng Việt."
    )


def _device_text(device: dict) -> str:
    def on(key):
        return "có" if device.get(key) else "không"
    return (f"đang phát nhạc={on('music_playing')}, đang chỉ đường={on('navigating')}, "
            f"đang bật cảnh báo vật cản={on('alerting')}, "
            f"chuyến xe chờ xác nhận={on('ride_quote_pending')}")


# ── Tiện ích dữ liệu ─────────────────────────────────────────────────────

def norm(text: str) -> str:
    """Chuẩn hoá để so trùng: NFC, chữ thường, bỏ dấu câu, gộp khoảng trắng."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stt_style(text: str) -> str:
    """Cùng dạng với đầu ra Zipformer (`pipeline.stt._normalize`): hoa chữ đầu, còn lại thường."""
    text = re.sub(r"\s+", " ", text).strip().strip(".,!?;:…")
    return text[:1].upper() + text[1:].lower() if text else ""


def make_id(text: str, device: dict) -> str:
    bits = "".join("1" if device.get(k) else "0" for k in DEVICE_KEYS)
    return "q" + hashlib.sha1(f"{norm(text)}|{bits}".encode()).hexdigest()[:10]


def clean_device(device: dict | None) -> dict:
    device = device or {}
    return {k: bool(device.get(k)) for k in DEVICE_KEYS}


def clean_params(params: dict | None) -> dict:
    return {k: v.strip() for k, v in (params or {}).items()
            if k in PARAM_KEYS and isinstance(v, str) and v.strip()}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # dòng dở do bị ngắt giữa chừng; bước chạy lại sẽ làm lại
    return out


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Ghi rồi đọc lại để chắc file không bị cắt (NFS quota từng cắt file âm thầm)."""
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    if tmp.stat().st_size != len(payload.encode("utf-8")):
        raise OSError(f"{tmp}: ghi bị cắt (quota?)")
    os.replace(tmp, path)


def write_json(path: Path, obj) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    if tmp.stat().st_size != len(payload.encode("utf-8")):
        raise OSError(f"{tmp}: ghi bị cắt (quota?)")
    os.replace(tmp, path)


# ── Nguồn câu ────────────────────────────────────────────────────────────

# Nhãn mà bản thân nhãn đã hàm ý bối cảnh thiết bị (chuyến xe chờ, đang chỉ đường...).
# Gán sẵn bối cảnh đó cho câu nguồn để sol thấy câu trong tình huống thật của nó;
# câu tắt/dừng trống không thì KHÔNG dùng cách này mà nhân ba (expand_bare_stops).
_CONTEXT_OF_LABEL = {
    "ride_confirm": "ride_quote_pending", "nav_stop": "navigating",
    "alert_off": "alerting", "music_stop": "music_playing", "music_volume": "music_playing",
}
_BARE_STOP = re.compile(
    r"^(tắt|dừng|ngừng|thôi|stop)( (đi|lại|đi nhé|nhé|đi nha|nha|giùm|giúp|với|ngay|luôn|cái))*$"
)
_CONTEXTS = ("music_playing", "navigating", "alerting")


def is_bare_stop(text: str) -> bool:
    return bool(_BARE_STOP.match(norm(text)))


def expand_bare_stops(items: list[dict]) -> list[dict]:
    """Câu tắt/dừng trống không -> 3 bản theo bối cảnh (nhạc / chỉ đường / cảnh báo).

    Nhãn đúng của "tắt đi" PHỤ THUỘC bối cảnh, nên mỗi bản là một câu gốc riêng
    (id, group riêng); nhãn cũ bị bỏ vì nó gắn với một bối cảnh chưa biết.
    """
    out = []
    for item in items:
        if not is_bare_stop(item["text"]):
            out.append(item)
            continue
        for ctx in _CONTEXTS:
            device = {k: k == ctx for k in DEVICE_KEYS}
            new_id = make_id(item["text"], device)
            out.append({**item, "id": new_id, "group": new_id, "device": device,
                        "old": None})
    return out


def load_sources() -> tuple[list[dict], dict]:
    """eval/train/suspect/rejected -> danh sách câu đã bỏ trùng theo văn bản chuẩn hoá."""
    items, seen, stats = [], {}, {}
    for origin in ("eval", "train", "suspect", "rejected"):
        rows = read_jsonl(DATA / f"{origin}.jsonl")
        stats[origin] = {"rows": len(rows), "duplicates": 0}
        for row in rows:
            key = norm(row["text"])
            if not key:
                continue
            old = row.get("label") if row.get("label") in LABELS else None
            hints = [h for h in (row.get("label"), row.get("verify")) if h in LABELS]
            if key in seen:
                stats[origin]["duplicates"] += 1
                seen[key]["hints"] = sorted(set(seen[key]["hints"]) | set(hints))
                if origin in ("suspect", "rejected"):
                    # Câu bị nghi nhãn cũ: giữ dấu này để thống kê thấy nó đáng ngờ.
                    seen[key]["origin"] = origin
                continue
            device = clean_device(None)
            if old in _CONTEXT_OF_LABEL:
                device[_CONTEXT_OF_LABEL[old]] = True
            item_id = make_id(row["text"], device)
            item = {"id": item_id, "group": item_id, "text": row["text"].strip(),
                    "device": device, "old": old, "hints": sorted(set(hints)),
                    "origin": origin}
            seen[key] = item
            items.append(item)
    before = len(items)
    items = expand_bare_stops(items)
    stats["bare_stop_expanded_to"] = len(items) - before
    stats["unique_source_items"] = len(items)
    return items, stats


# ── Chọn mẫu nhỏ ─────────────────────────────────────────────────────────

SOURCE_PER_LABEL = 9      # mỗi nhãn (trừ chat) lấy cho đủ ngần này, tính cả câu suspect/rejected
SOURCE_CHAT = 28          # chat là nhãn tràn lan; nén lại để không chiếm mẫu
SOURCE_REJECTED = 10      # trong 20 câu rejected
VARIANT_N = 50            # số câu sạch có biến thể STT
_ORIGIN_RANK = {"suspect": 0, "rejected": 0, "eval": 1, "train": 2}


def select_sources(items: list[dict], seed: int = SEED) -> list[dict]:
    """Mẫu phân tầng theo nhãn cũ: eval trước, train sau; chat ≤ 50.

    Luôn giữ: câu tắt/dừng trống không (đã nhân theo bối cảnh), câu suspect (nhãn cũ bị
    nghi) và một phần rejected — đây là chỗ nhãn cũ bất đồng nên đáng đo nhất.
    """
    rng = random.Random(seed)
    chosen = [i for i in items if i["old"] is None and is_bare_stop(i["text"])]
    chosen += [i for i in items if i["origin"] == "suspect"]
    rejected = sorted((i for i in items if i["origin"] == "rejected"), key=lambda i: i["id"])
    chosen += rejected[:SOURCE_REJECTED]
    taken = {i["id"] for i in chosen}

    pool: dict[str, list[dict]] = {}
    for item in sorted(items, key=lambda i: i["id"]):
        if item["id"] not in taken and item["old"]:
            pool.setdefault(item["old"], []).append(item)
    have: dict[str, int] = {}
    for item in chosen:
        if item["old"]:
            have[item["old"]] = have.get(item["old"], 0) + 1
    for label in sorted(pool):
        rng.shuffle(pool[label])
        pool[label].sort(key=lambda i: _ORIGIN_RANK[i["origin"]])  # sort ổn định: eval trước
        want = (SOURCE_CHAT if label == "chat" else SOURCE_PER_LABEL) - have.get(label, 0)
        chosen += pool[label][:max(0, want)]
    return chosen


def select_for_variants(accepted: list[tuple[dict, dict]], n: int = VARIANT_N,
                        seed: int = SEED) -> list[dict]:
    """~n câu sạch cho biến thể STT, xoay vòng giữa các nhãn để mỗi nhãn đều có mặt."""
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = {}
    for item, decision in sorted(accepted, key=lambda p: p[0]["id"]):
        by_label.setdefault(decision["label"], []).append(item)
    for members in by_label.values():
        rng.shuffle(members)
    out: list[dict] = []
    while len(out) < n and any(by_label.values()):
        for label in sorted(by_label):
            if by_label[label] and len(out) < n:
                out.append(by_label[label].pop())
    return out


# ── sol: gán lại nhãn ────────────────────────────────────────────────────

def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def relabel(items: list[dict], work: Path, batch: int = 8) -> dict:
    """sol (high) gán nhãn đầy đủ cho từng câu, theo lô; kết quả cache theo id."""
    cache_path = work / "relabel.jsonl"
    done = {r["id"] for r in read_jsonl(cache_path)}
    system = label_guide()
    stats = {"asked": 0, "missing": 0}
    for round_no in range(3):
        todo = [i for i in items if i["id"] not in done]
        if not todo:
            break
        size = batch if round_no == 0 else 1  # lô nào hỏng thì hỏi lẻ từng câu
        groups = list(_chunks(todo, size))
        jobs = [(system, json.dumps(
            [{"id": i["id"], "text": i["text"], "bối_cảnh": _device_text(i["device"])}
             for i in grp], ensure_ascii=False)
            + "\nGán nhãn cho TỪNG câu trên. Trả {\"items\": [...]} đủ mọi id.",
            RELABEL_SCHEMA) for grp in groups]
        replies = sol.ask_many(jobs, effort="high")
        fails = sum(r is None for r in replies)
        if fails > max(3, 0.3 * len(replies)):
            raise sol.SolError(f"relabel: {fails}/{len(replies)} lô hỏng — dừng, nghi router/quota")
        for grp, reply in zip(groups, replies):
            if reply is None:
                continue
            want = {i["id"] for i in grp}
            rows = []
            for r in reply["items"]:
                if r["id"] in want and r["id"] not in done:
                    rows.append({"id": r["id"], "label": r["label"],
                                 "ocr_mode": r["ocr_mode"], "needs_web": r["needs_web"],
                                 "params": clean_params(r["params"]), "reason": r["reason"]})
                    done.add(r["id"])
            append_jsonl(cache_path, rows)
            stats["asked"] += len(grp)
    stats["missing"] = sum(1 for i in items if i["id"] not in done)
    return stats


# ── sol: sinh câu mới ────────────────────────────────────────────────────

_GEN_STYLE = (
    "Viết như BẢN GHI STT tiếng Việt: không dấu câu, chữ hoa chỉ ở đầu câu, chữ thường "
    "còn lại (kể cả tên riêng). Mỗi câu một ý, ngắn 2-14 từ trừ khi ô yêu cầu khác. "
    "Mọi câu trong lô phải KHÁC NHAU rõ rệt về từ ngữ, không lặp khuôn. Gán đầy đủ nhãn, "
    "ocr_mode, needs_web, params và bối cảnh thiết bị (device) đúng với từng câu; "
    "device để false hết trừ khi câu phụ thuộc bối cảnh."
)

GEN_CELLS: list[tuple[str, str]] = [
    ("pair_chat_ocr", "Cặp dễ nhầm chat↔ocr: một nửa là lệnh đọc/tóm tắt chữ (ocr), một nửa "
     "là câu hỏi/trò chuyện về sách, chữ, đọc, báo chí nhưng KHÔNG nhờ kính đọc (chat)."),
    ("pair_chat_space", "Cặp dễ nhầm chat↔space: một nửa hỏi phía trước/xung quanh có gì "
     "(space), một nửa là hỏi đáp thường về không gian, địa danh, kiến thức (chat)."),
    ("pair_chat_hazard", "Cặp dễ nhầm chat↔hazard: một nửa hỏi phía trước có an toàn/vật cản "
     "không (hazard), một nửa nói chuyện về an toàn, nguy hiểm nói chung (chat)."),
    ("pair_chat_nav_start", "Cặp dễ nhầm chat↔nav_start: một nửa nhờ dẫn đường tới địa điểm "
     "(nav_start, điền destination), một nửa hỏi về địa điểm/đường xá/khoảng cách mà KHÔNG "
     "nhờ dẫn (chat)."),
    ("pair_chat_music_play", "Cặp dễ nhầm chat↔music_play: một nửa nhờ phát nhạc/bài hát "
     "(music_play, điền song), một nửa hỏi về nhạc, ca sĩ, bài hát mà không nhờ phát (chat)."),
    ("notcmd_call", "Câu có \"gọi\" nhưng KHÔNG phải lệnh gọi điện: kể chuyện đã gọi, "
     "\"gọi\" nghĩa là tên gọi, nói với người bên cạnh. Xen khoảng 1/4 lệnh gọi thật "
     "(contact_call, điền contact_name) làm đối chứng."),
    ("notcmd_goto_read", "Câu có \"đi tới\"/\"đến\"/\"đọc\" nhưng KHÔNG phải lệnh với kính "
     "(kể chuyện, hỏi thông tin, nói với người khác). Xen khoảng 1/4 lệnh thật "
     "(nav_start hoặc ocr) làm đối chứng."),
    ("dialect_bac", "Phương ngữ Bắc, đủ các nhãn (chat, space, ocr, nav_start, "
     "contact_call, music_play, money, find, hazard...)."),
    ("dialect_trung", "Phương ngữ Trung (mô, rứa, tê, răng, chi...), đủ các nhãn."),
    ("dialect_nam", "Phương ngữ Nam (hổng, dzậy, nè, nghen, tui...), đủ các nhãn."),
    ("truncated_a", "Câu CỤT do nhả nút sớm: mất phần đuôi hoặc phần đầu (\"cho tôi đọc\", "
     "\"đường tới\", \"gọi cho\"). Câu thiếu thông tin thì nhãn là chat; câu cụt vẫn đủ ý "
     "thì nhãn theo ý."),
    ("truncated_b", "Câu cụt/lắp bắp/lặp từ do nút nhả sớm hoặc nói vấp (\"tôi tôi muốn\", "
     "\"phía trước\", \"bật\"). Phần lớn chat (không đủ ý), một số vẫn đủ ý."),
    ("outofscope", "Câu ngoài phạm vi của kính (nhờ nấu ăn, chuyển tiền, đặt vé máy bay, mở "
     "đèn nhà...) và câu vô nghĩa/nói mớ/ho/tiếng ồn bị STT ra chữ — nhãn chat."),
    ("outofscope_b", "Câu trò chuyện xã giao, cảm thán, chào hỏi, cảm ơn, hỏi về chính chiếc "
     "kính (pin, tên, cách dùng) — nhãn chat; xen vài câu gần giống lệnh."),
    ("filler_a", "Lệnh thật (đủ nhãn: ocr, space, find, money, nav_start, contact_call, "
     "music_play...) có CHÊM từ đệm: \"ờ\", \"à mà\", \"ừm\", \"thì\", \"cho tôi hỏi\"."),
    ("filler_b", "Lệnh thật có chêm từ đệm VÀ nói sửa giữa chừng (\"gọi cho ờ à không gọi cho "
     "bố\"): nhãn theo ý cuối cùng, params theo ý cuối cùng."),
    ("web_chat", "Câu hỏi chat CẦN tra web: thời tiết, tỉ số, giá vàng, giá xăng, tin tức, "
     "giờ mở cửa, lịch chiếu phim, sự kiện (needs_web = true). Xen 1/3 câu chat KHÔNG cần tra "
     "web (kiến thức tĩnh, toán, định nghĩa) có needs_web = false."),
    ("web_chat_b", "Như ô trước nhưng cách hỏi đời thường, dài 8-16 từ, nhiều cách diễn đạt "
     "về thời tiết, tỉ số bóng đá, giá cả, thời sự; xen chat không cần web."),
    ("device_context", "Câu tắt/dừng/to-nhỏ/xác nhận phụ thuộc bối cảnh thiết bị: \"tắt đi\", "
     "\"dừng\", \"nhỏ thôi\", \"ừ đồng ý\", \"huỷ đi\" — đặt device phù hợp (đang phát nhạc / "
     "đang chỉ đường / đang bật cảnh báo / có chuyến xe chờ) và gán nhãn đúng theo bối cảnh "
     "(music_stop, nav_stop, alert_off, music_volume, ride_confirm)."),
    ("lane_d_params", "Lệnh làn D có tham số, đa dạng cách nói: contact_call (tên người: mẹ, "
     "anh Nam, bác sĩ Hà), nav_start (điểm đến), ride_quote (đặt xe tới đâu), music_play "
     "(bài/ca sĩ). Điền params đúng chữ người nói."),
]


# Chỉ các ô "ca dễ nhầm" được dùng (quy mô nhỏ): số câu giữ lại mỗi ô. `alert_cmds` thêm
# vì eval/train KHÔNG có câu alert_on/alert_off nào mà nhãn đó phải có mặt trong gold.
GEN_QUOTA = {
    "pair_chat_ocr": 4, "pair_chat_space": 4, "pair_chat_hazard": 4,
    "pair_chat_nav_start": 4, "pair_chat_music_play": 4,
    "notcmd_call": 4, "notcmd_goto_read": 4, "device_context": 6, "alert_cmds": 8,
}
GEN_CELLS.append((
    "alert_cmds", "Lệnh bật/tắt cảnh báo vật cản khi đi đường: một nửa alert_on (bật cảnh "
    "báo, báo vật cản cho tôi), một nửa alert_off (tắt cảnh báo, thôi đừng báo nữa; device "
    "alerting=true). Xen 2 câu chat nhắc tới cảnh báo mà không ra lệnh."))


def generate(work: Path, per_cell: int | None = None, cells: int | None = None) -> dict:
    """sol (low) sinh câu mới theo từng "ô" trong `GEN_QUOTA`, cache theo ô.

    Mỗi ô xin dư `quota + 4` câu vì sau khi bỏ trùng/không hợp lệ chỉ giữ `quota` câu.
    """
    cache_path = work / "gen_raw.jsonl"
    done = {r["cell"] for r in read_jsonl(cache_path)}
    active = [c for c in GEN_CELLS if c[0] in GEN_QUOTA][:cells]
    todo = [c for c in active if c[0] not in done]
    system = label_guide() + "\n\n" + _GEN_STYLE
    jobs = [(system, f"Ô: {name}\n{desc}\nSinh đúng {per_cell or GEN_QUOTA[name] + 4} câu mới.",
             GENERATE_SCHEMA) for name, desc in todo]
    replies = sol.ask_many(jobs, effort="low")
    fails = sum(r is None for r in replies)
    if jobs and fails > max(2, 0.3 * len(jobs)):
        raise sol.SolError(f"generate: {fails}/{len(jobs)} ô hỏng — dừng, nghi router/quota")
    for (name, _), reply in zip(todo, replies):
        if reply is not None:
            append_jsonl(cache_path, [{"cell": name, "items": reply["items"]}])
    return {"cells_done": len({r["cell"] for r in read_jsonl(cache_path)} & set(GEN_QUOTA)),
            "cells_total": len(active),
            "cells_failed": fails}


def build_gen_items(work: Path, source_items: list[dict]) -> tuple[list[dict], dict]:
    """gen_raw -> câu hợp lệ, bỏ trùng với nguồn và với nhau; ghi `gen_items.jsonl`."""
    seen = {(norm(i["text"]), tuple(sorted(i["device"].items()))) for i in source_items}
    seen_text = {norm(i["text"]) for i in source_items}
    items, per_cell, dropped = [], {}, {"duplicate": 0, "invalid": 0}
    for entry in read_jsonl(work / "gen_raw.jsonl"):
        if entry["cell"] not in GEN_QUOTA:
            continue
        for row in entry["items"]:
            if per_cell.get(entry["cell"], 0) >= GEN_QUOTA[entry["cell"]]:
                break
            text = stt_style(row.get("text", ""))
            device = clean_device(row.get("device"))
            if not norm(text) or row.get("label") not in LABELS:
                dropped["invalid"] += 1
                continue
            key = (norm(text), tuple(sorted(device.items())))
            # Bỏ cả khi chỉ trùng chữ với câu nguồn không-phụ-thuộc-bối-cảnh.
            if key in seen or (norm(text) in seen_text and not any(device.values())):
                dropped["duplicate"] += 1
                continue
            seen.add(key)
            seen_text.add(norm(text))
            item_id = make_id(text, device)
            items.append({"id": item_id, "group": item_id, "text": text, "device": device,
                          "old": row["label"], "hints": [], "origin": "sol_gen",
                          "cell": entry["cell"]})
            per_cell[entry["cell"]] = per_cell.get(entry["cell"], 0) + 1
    write_jsonl(work / "gen_items.jsonl", items)
    return items, {"items": len(items), "per_cell": per_cell, **{f"dropped_{k}": v
                                                                  for k, v in dropped.items()}}


# ── Đồng thuận nhãn ──────────────────────────────────────────────────────

def consensus(item: dict) -> dict:
    """Nhãn cũ (nếu có) + sol + Gemma khớp -> `agree`; lệch -> sol phân xử.

    `item`: {"old": nhãn|None, "sol": {label, ocr_mode, needs_web, params, reason},
    "gemma": {label,...}|None, "text", "device", "hints"?}. Gemma hỏng hết lần thử
    (None) thì chỉ cần cũ = sol. Phân xử hỏng hoặc `uncertain` -> `uncertain`: công
    cụ không tự quyết, câu đi vào hàng chờ duyệt của người.
    """
    first = item["sol"]
    votes = [v for v in (item.get("old"), first["label"],
                         (item.get("gemma") or {}).get("label")) if v]
    if len(set(votes)) == 1:
        return {"status": "agree", "label": first["label"], "ocr_mode": first["ocr_mode"],
                "needs_web": first["needs_web"], "params": clean_params(first["params"]),
                "reason": first.get("reason", "")}

    candidates = {"nhãn cũ (có thể sai)": item.get("old"),
                  f"sol lượt đầu (lý do: {first.get('reason', '')})": first["label"],
                  "Gemma hiện tại": (item.get("gemma") or {}).get("label")}
    lines = [f"- {src}: {lab}" for src, lab in candidates.items() if lab]
    for hint in item.get("hints", []):
        if hint not in votes:
            lines.append(f"- gợi ý khác trong dữ liệu cũ: {hint}")
    system = label_guide() + (
        "\n\nLượt này là PHÂN XỬ: các nguồn bất đồng về nhãn. Xem xét từng ứng viên, chọn "
        "nhãn đúng nhất với ý người nói. Đặt uncertain=true nếu một người nghe cẩn thận "
        "cũng không thể chắc nhãn nào đúng (câu mơ hồ thật, thiếu ngữ cảnh) — ĐỪNG đoán.")
    user = (f"Câu: \"{item['text']}\"\nBối cảnh thiết bị: {_device_text(item['device'])}\n"
            "Các nhãn ứng viên:\n" + "\n".join(lines))
    try:
        reply = sol.ask_json(system, user, ADJUDICATE_SCHEMA, effort="high")
    except sol.SolError:
        reply = None
    if not reply or reply.get("uncertain") or reply.get("label") not in LABELS:
        best = (reply or {}).get("label") if (reply or {}).get("label") in LABELS else first["label"]
        return {"status": "uncertain", "label": best,
                "ocr_mode": (reply or first)["ocr_mode"],
                "needs_web": (reply or first)["needs_web"],
                "params": clean_params((reply or first)["params"]),
                "reason": (reply or {}).get("reason", "phân xử thất bại"),
                "candidates": sorted({v for v in [*votes, *item.get("hints", [])] if v})}
    return {"status": "sol_adjudicated", "label": reply["label"],
            "ocr_mode": reply["ocr_mode"], "needs_web": reply["needs_web"],
            "params": clean_params(reply["params"]), "reason": reply["reason"]}


def run_gemma(items: list[dict], work: Path, concurrency: int = 8) -> dict:
    """Gemma hiện tại (`pipeline.intent_classifier.classify`) trên câu sạch; cache theo id."""
    cache_path = work / "gemma.jsonl"
    done = {r["id"] for r in read_jsonl(cache_path)}
    todo = [i for i in items if i["id"] not in done]
    if not todo:
        return {"asked": 0, "failed": 0}

    import config
    config.INTENT_BACKEND = "gemma"        # không rơi sang Clef: ta muốn đo đúng Gemma
    config.INTENT_LLM_TIMEOUT_S = 6.0      # công cụ offline, không cần giữ ngưỡng 0,8 s
    from pipeline import intent_classifier

    async def one(sem, item):
        async with sem:
            for _ in range(3):
                res = await intent_classifier.classify(item["text"], item["device"])
                if res is not None:
                    return {"id": item["id"], "gemma": {
                        "label": res.intent, "ocr_mode": res.ocr_mode,
                        "needs_web": res.needs_web}}
                await asyncio.sleep(1.0)
            return {"id": item["id"], "gemma": None}

    async def main():
        sem = asyncio.Semaphore(concurrency)
        return await asyncio.gather(*(one(sem, i) for i in todo))

    rows = asyncio.run(main())
    append_jsonl(cache_path, rows)
    return {"asked": len(todo), "failed": sum(r["gemma"] is None for r in rows)}


def adjudicate(items: list[dict], work: Path) -> dict:
    """Gemma -> đối chiếu -> sol phân xử các ca lệch. Cache theo id trong adjudicate.jsonl."""
    gemma_stats = run_gemma(items, work)
    sol_by_id = {r["id"]: r for r in read_jsonl(work / "relabel.jsonl")}
    gemma_by_id = {r["id"]: r["gemma"] for r in read_jsonl(work / "gemma.jsonl")}
    cache_path = work / "adjudicate.jsonl"
    done = {r["id"] for r in read_jsonl(cache_path)}
    todo = [i for i in items if i["id"] not in done and i["id"] in sol_by_id]

    def one(item):
        return {"id": item["id"], **consensus({
            "text": item["text"], "device": item["device"], "old": item.get("old"),
            "hints": item.get("hints", []), "sol": sol_by_id[item["id"]],
            "gemma": gemma_by_id.get(item["id"])})}

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for row in pool.map(one, todo):
            results.append(row)
            if len(results) % 25 == 0:
                append_jsonl(cache_path, results[-25:])
        append_jsonl(cache_path, results[len(results) // 25 * 25:])
    by_status = {}
    for r in read_jsonl(cache_path):
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"gemma": gemma_stats, "by_status": by_status,
            "no_sol_label": sum(1 for i in items if i["id"] not in sol_by_id)}


# ── Chia dev/test, hàng chờ duyệt ────────────────────────────────────────

def split_groups(rows: list[dict], seed: int = SEED,
                 test_ratio: float = TEST_RATIO) -> tuple[list[dict], list[dict]]:
    """Tách theo `group` (mọi biến thể của một câu cùng một phía), phân tầng theo nhãn.

    Mỗi nhãn có ≥ 2 group thì có ≥ 1 group ở mỗi phía. Sai số làm tròn của từng nhãn
    được dồn sang nhãn kế tiếp để tỉ lệ test toàn cục bám sát `test_ratio`. Kết quả
    chỉ phụ thuộc `seed` và tập `group`, không phụ thuộc thứ tự dòng đầu vào.
    """
    by_group: dict[str, list[dict]] = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row)
    by_label: dict[str, list[str]] = {}
    for group, members in by_group.items():
        clean = next((m for m in members if m["variant"] == "clean"), members[0])
        by_label.setdefault(clean["label"], []).append(group)

    rng = random.Random(seed)
    test_groups: set[str] = set()
    carry = 0.0
    for label in sorted(by_label):
        groups = sorted(by_label[label])
        rng.shuffle(groups)
        want = test_ratio * len(groups) + carry
        n_test = int(round(want))
        if len(groups) >= 2:
            n_test = min(max(n_test, 1), len(groups) - 1)
        else:
            n_test = 0  # nhãn chỉ có 1 group: giữ ở dev để còn chỉnh prompt
        carry = want - n_test
        test_groups.update(groups[:n_test])

    dev = [r for r in rows if r["group"] not in test_groups]
    test = [r for r in rows if r["group"] in test_groups]
    return dev, test


def _is_lane_d(row: dict) -> bool:
    return row.get("label") in LANE_D or any(c in LANE_D for c in row.get("candidates", []))


def cap_review(rows: list[dict], cap: int = REVIEW_CAP) -> tuple[list[dict], list[dict]]:
    """Giữ tối đa `cap` câu bất định, ưu tiên làn D; phần dư trả về để đếm vào log."""
    ordered = sorted(rows, key=lambda r: (not _is_lane_d(r),
                                          hashlib.sha1(r["id"].encode()).hexdigest()))
    return ordered[:cap], ordered[cap:]


def make_row(item: dict, decision: dict, variant: str, text: str) -> dict:
    return {
        "id": f"{item['group']}:{variant}", "group": item["group"], "text": text,
        "source_text": item["text"], "variant": variant, "device": item["device"],
        "label": decision["label"], "ocr_mode": decision["ocr_mode"],
        "needs_web": decision["needs_web"], "params": decision["params"],
        "label_source": "agree" if decision["status"] == "agree" else "sol_adjudicated",
        "origin": item["origin"],
    }


# ── Biến thể STT ─────────────────────────────────────────────────────────

def pick_gpus(n: int) -> list[str]:
    """n GPU ít bộ nhớ dùng nhất (GPU chung 8×2080 Ti); không bao giờ lùi về CPU."""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True).stdout
    used = sorted((int(m), i.strip()) for i, m in
                  (line.split(",") for line in out.strip().splitlines()))
    return [i for _, i in used[:n]]


def run_variants(items: list[dict], work: Path, workers: int) -> dict:
    """Chạy `workers` tiến trình TTS song song (mỗi cái một GPU), chờ xong rồi gộp."""
    texts = sorted({i["text"] for i in items})
    (work / "variant_texts.json").write_text(json.dumps(texts, ensure_ascii=False),
                                             encoding="utf-8")
    gpus = pick_gpus(workers)
    procs = []
    for k in range(workers):
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpus[k % len(gpus)]}
        cmd = [sys.executable, "-m", "tools.intent_gold.build", "--stage", "variants-shard",
               "--shard", f"{k}/{workers}", "--work-dir", str(work)]
        log = open(work / f"variants_shard{k}.log", "a")
        procs.append(subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=log))
    codes = [p.wait() for p in procs]
    if any(codes):
        raise RuntimeError(f"tiến trình variants lỗi, mã thoát {codes} (xem variants_shard*.log)")
    return {"workers": workers, "gpus": gpus[:workers]}


def load_variant_cache(work: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for path in sorted(work.glob("variants.shard*.jsonl")):
        for row in read_jsonl(path):
            cache[row["text"]] = row
    return cache


def variant_rows(item: dict, decision: dict, cache: dict) -> tuple[list[dict], int]:
    """Biến thể STT của một câu (bỏ bản ghi rỗng); trả (dòng, số bị bỏ)."""
    rows, empty = [], 0
    entry = cache.get(item["text"], {}).get("stt", {})
    for variant in VARIANTS[1:]:
        transcript = (entry.get(variant) or "").strip()
        if transcript:
            rows.append(make_row(item, decision, variant, transcript))
        elif variant in entry:
            empty += 1
    return rows, empty


# ── Điều phối ────────────────────────────────────────────────────────────

class Stats:
    """Số liệu từng bước, cộng dồn qua các lần chạy lại để log phản ánh cả quá trình."""

    def __init__(self, work: Path):
        self.path = work / "stage_stats.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def record(self, stage: str, info: dict, started: float, calls_before: int) -> None:
        prev = self.data.get(stage, {})
        self.data[stage] = {
            **info,
            "seconds": round(prev.get("seconds", 0) + time.time() - started, 1),
            "sol_calls": prev.get("sol_calls", 0) + sol.STATS["calls"] - calls_before,
        }
        write_json(self.path, self.data)


def all_items(work: Path) -> list[dict]:
    items, _ = load_sources()
    return items + read_jsonl(work / "gen_items.jsonl")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", required=True, choices=[
        "relabel", "generate", "variants", "variants-shard", "adjudicate", "split", "all"])
    ap.add_argument("--work-dir", default=str(DATA / "gold_work"))
    ap.add_argument("--out-dir", default=str(DATA))
    ap.add_argument("--shard", default="0/1", help="k/n, chỉ cho variants-shard")
    ap.add_argument("--tts-workers", type=int, default=1)
    ap.add_argument("--gen-per-cell", type=int, default=None)
    ap.add_argument("--gen-cells", type=int, default=None)
    args = ap.parse_args(argv)

    work, out = Path(args.work_dir), Path(args.out_dir)
    work.mkdir(parents=True, exist_ok=True)

    if args.stage == "variants-shard":
        from tools.intent_gold import stt_variants
        k, n = map(int, args.shard.split("/"))
        texts = json.loads((work / "variant_texts.json").read_text(encoding="utf-8"))
        return stt_variants.run_shard(texts, k, n, work / f"variants.shard{k}.jsonl")

    stats = Stats(work)
    stages = (["relabel", "generate", "relabel", "adjudicate", "variants", "split"]
              if args.stage == "all" else [args.stage])

    def items_now():
        """Mẫu nhỏ đã chọn: câu nguồn phân tầng + câu sol sinh."""
        items = all_items(work)
        src = select_sources([i for i in items if i["origin"] != "sol_gen"])
        return src + [i for i in items if i["origin"] == "sol_gen"]

    for stage in stages:
        started, calls = time.time(), sol.STATS["calls"]
        print(f"[{time.strftime('%H:%M:%S')}] stage {stage}", flush=True)
        if stage == "relabel":
            items = items_now()
            info = relabel(items, work)
            _, src_stats = load_sources()
            info["sources"] = src_stats
            info["selected"] = _count_origin(items)
        elif stage == "generate":
            info = generate(work, args.gen_per_cell, args.gen_cells)
            info["built"] = build_gen_items(work, load_sources()[0])[1]
        elif stage == "adjudicate":
            items = items_now()
            info = adjudicate(items, work)
        elif stage == "variants":
            accepted = _accepted(items_now(), work)
            chosen = select_for_variants(accepted)
            info = run_variants(chosen, work, args.tts_workers)
            info["sentences"] = len({i["text"] for i in chosen})
        elif stage == "split":
            info = split(items_now(), work, out, stats)
        stats.record(stage, info, started, calls)
        print(json.dumps(info, ensure_ascii=False)[:600], flush=True)


def _count_origin(items: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for i in items:
        counts[i["origin"]] = counts.get(i["origin"], 0) + 1
    return counts


def _accepted(items: list[dict], work: Path) -> list[tuple[dict, dict]]:
    decisions = {r["id"]: r for r in read_jsonl(work / "adjudicate.jsonl")}
    return [(i, decisions[i["id"]]) for i in items
            if decisions.get(i["id"], {}).get("status") in ("agree", "sol_adjudicated")]


def split(items: list[dict], work: Path, out: Path, stats: Stats) -> dict:
    decisions = {r["id"]: r for r in read_jsonl(work / "adjudicate.jsonl")}
    cache = load_variant_cache(work)
    rows, review, empty = [], [], 0
    for item in items:
        decision = decisions.get(item["id"])
        if decision is None:
            continue
        if decision["status"] == "uncertain":
            review.append({**make_row(item, decision, "clean", item["text"]),
                           "uncertain": True, "candidates": decision.get("candidates", []),
                           "reason": decision.get("reason", "")})
            continue
        rows.append(make_row(item, decision, "clean", item["text"]))
        extra, dropped = variant_rows(item, decision, cache)
        rows.extend(extra)
        empty += dropped

    dev, test = split_groups(rows)
    kept, dropped_review = cap_review(review)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "gold_dev.jsonl", dev)
    write_jsonl(out / "gold_test.jsonl", test)
    write_jsonl(out / "gold_review.jsonl", kept)

    def per_label(part):
        counts: dict[str, int] = {}
        for r in part:
            if r["variant"] == "clean":
                counts[r["label"]] = counts.get(r["label"], 0) + 1
        return counts

    total_clean = per_label(dev + test)
    log = {
        "stages": stats.data,
        # Lượt chạy đầy đủ (1.441 câu nguồn + 597 câu sinh) bị dừng khi chuyển sang quy mô
        # nhỏ; cache relabel của nó được tái dùng nên số lượt sol đã tiêu nằm riêng ở đây.
        "aborted_full_run": (json.loads((work / "aborted_run_stats.json").read_text())
                             if (work / "aborted_run_stats.json").exists() else None),
        "rows": {"dev": len(dev), "test": len(test), "total": len(dev) + len(test),
                 "clean_groups": sum(total_clean.values()),
                 "by_variant": {v: sum(r["variant"] == v for r in dev + test) for v in VARIANTS},
                 "by_origin_clean": _count(dev + test, "origin"),
                 "by_label_source_clean": _count(dev + test, "label_source"),
                 "groups_per_label": dict(sorted(total_clean.items())),
                 "stt_variants_dropped_empty": empty},
        "review": {"uncertain": len(review), "kept": len(kept), "dropped": len(dropped_review),
                   "kept_lane_d": sum(_is_lane_d(r) for r in kept)},
        "sol_calls_total": sum(s.get("sol_calls", 0) for s in stats.data.values()),
        "seconds_total": round(sum(s.get("seconds", 0) for s in stats.data.values()), 1),
    }
    write_json(out / "gold_build_log.json", log)
    return {"dev": len(dev), "test": len(test), "review_kept": len(kept),
            "review_dropped": len(dropped_review)}


def _count(rows: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        if r["variant"] == "clean":
            counts[r[key]] = counts.get(r[key], 0) + 1
    return counts


if __name__ == "__main__":
    main()
