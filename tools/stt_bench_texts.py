"""Bộ câu cho bàn đo STT câu lệnh (`tools/bench_stt_cmd.py`).

Hai nguồn:
- câu gold dev/test (`data/intent/gold_*.jsonl`, bản `clean`, mỗi nhóm một câu);
- câu lệnh BỔ SUNG sinh theo mẫu cho đúng các lệnh kính hay nghe: gọi / nhắn / đọc tin /
  khẩn cấp / bật-tắt cảnh báo / dẫn đường, kèm tên người thân (kiểu `care_links`), và
  câu CHAT gần từ vựng lệnh ("nhanh lên mẹ ơi", "cảnh sát đứng ở ngã tư") để đo hotword
  có chèn bừa từ lệnh hay không.

Sinh tất định (seed cố định theo văn bản) rồi chia dev/test theo băm văn bản, nên chạy lại
ra đúng cùng một bộ.
"""

import json
import random
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Người thân kiểu care_links: quan hệ trần và "quan hệ + tên".
NAMES = [
    "mẹ", "bố", "ba", "má", "vợ", "chồng", "anh Nam", "chị Lan", "em Hoa", "bà ngoại",
    "ông nội", "cô Mai", "chú Hùng", "con gái", "bác Tâm", "anh Hùng", "chị Hà", "dì Ba",
    "thằng Tuấn", "em Linh",
]
MESSAGES = [
    "tôi về muộn", "mình đang đợi ở cổng", "tôi đã đến nơi rồi", "chiều nay đón giúp tôi",
    "đừng lo tôi vẫn ổn", "nhớ mang thuốc cho tôi", "tối nay tôi ăn cơm ở nhà",
    "tôi sắp tới ga rồi", "mai gặp nhau lúc tám giờ",
]
PLACES = ["bệnh viện", "chợ bến thành", "trạm xe buýt", "nhà ga", "siêu thị", "công viên", "nhà thuốc"]

CALL = ["Gọi cho {n}", "Gọi điện cho {n}", "Gọi điện thoại cho {n} giúp tôi", "Cho tôi gọi cho {n}",
        "Kính ơi gọi điện cho {n}"]
SEND = ["Nhắn cho {n} là {m}", "Nhắn tin cho {n} là {m}", "Nhắn với {n} {m}",
        "Gửi tin nhắn cho {n} {m}", "Nhắn giúp tôi cho {n} {m}", "Nhắn lại cho {n} là {m}"]
READ = ["{n} có nhắn gì không", "Đọc tin nhắn của {n}", "Có tin nhắn mới không", "Kiểm tra tin nhắn giúp tôi",
        "Xem có lời nhắn nào không"]
EMERGENCY = ["Cấp cứu", "Khẩn cấp", "Gọi cấp cứu giúp tôi", "Cứu tôi với", "Tôi cần cấp cứu",
             "Tôi bị ngã cần giúp đỡ khẩn cấp", "Gọi khẩn cấp ngay", "Cứu với tôi bị đau tim"]
ALERT_ON = ["Bật cảnh báo vật cản", "Mở cảnh báo", "Bật cảnh báo chướng ngại", "Hãy bật cảnh báo vật cản cho tôi",
            "Bật cảnh báo đi"]
ALERT_OFF = ["Tắt cảnh báo", "Tắt cảnh báo vật cản", "Dừng cảnh báo", "Ngừng cảnh báo vật cản đi",
             "Tắt chức năng cảnh báo"]
NAV_START = ["Dẫn đường về nhà", "Dẫn đường tới {p}", "Chỉ đường đến {p}", "Dẫn tôi tới {p}", "Đưa tôi đến {p}"]
NAV_STOP = ["Dừng dẫn đường", "Tắt chỉ đường", "Dừng chỉ đường", "Tắt dẫn đường đi"]

# Chat gần từ vựng lệnh (nhãn chat, KHÔNG có cụm lệnh): tên người thân, "nhanh/nhắc/cảnh/vật...".
CHAT = [
    "Nhanh lên mẹ ơi kẻo trễ", "Nhắc tôi uống thuốc lúc tám giờ", "Cảnh sát đang đứng ở ngã tư",
    "Vật dụng này làm bằng gì", "Con mèo của mẹ tôi rất ngoan", "Bố tôi thích uống trà buổi sáng",
    "Chị Lan hôm nay đi chợ sớm", "Mùa này cảnh đẹp lắm", "Thời tiết hôm nay thế nào",
    "Kể cho tôi nghe một câu chuyện cười", "Hôm nay là ngày bao nhiêu", "Em Hoa học giỏi lắm",
    "Anh Nam vừa đi làm về", "Ông nội tôi hay đi dạo công viên", "Bà ngoại nấu canh chua rất ngon",
    "Chồng tôi đang đợi ở nhà", "Con gái tôi mới học xong", "Chú Hùng sửa xe rất giỏi",
    "Tôi thấy hơi mệt hôm nay", "Cái cảnh này đẹp quá", "Nhanh quá tôi không theo kịp",
    "Cô Mai dạy tôi nấu ăn", "Trời nắng nóng quá", "Xe buýt hôm nay đông người",
    "Tôi muốn nghe một chuyện vui", "Má tôi hay kể chuyện ngày xưa", "Vợ tôi làm việc ở bệnh viện",
    "Hôm qua tôi đi chợ mua cá", "Bác Tâm là bác sĩ ở trạm xá", "Dì Ba mới về quê hôm qua",
    "Thằng Tuấn đá bóng giỏi lắm", "Nhắc lại giúp tôi tên bài hát",
]


def _h(text: str) -> int:
    return zlib.crc32(text.encode("utf-8"))


def extra_rows() -> list[dict]:
    rng = random.Random(20261020)
    rows: list[dict] = []

    def add(text, label, **params):
        rows.append({"text": text, "label": label, "params": params, "src": "extra"})

    def sample(pool, k):
        return rng.sample(pool, min(k, len(pool)))

    for n in sample(NAMES, 14):
        add(rng.choice(CALL).format(n=n), "contact_call", contact_name=n.lower())
    for n in sample(NAMES, 20):
        add(rng.choice(SEND).format(n=n, m=rng.choice(MESSAGES)), "message_send", contact_name=n.lower())
    for t in READ:
        add(t.format(n=rng.choice(NAMES)), "message_read")
    for t in EMERGENCY:
        add(t, "emergency_call")
    for t in ALERT_ON:
        add(t, "alert_on")
    for t in ALERT_OFF:
        add(t, "alert_off")
    for t in NAV_START:
        add(t.format(p=rng.choice(PLACES)), "nav_start")
    for t in NAV_STOP:
        add(t, "nav_stop")
    for t in CHAT:
        add(t, "chat")
    seen, out = set(), []
    for r in rows:
        if r["text"].lower() not in seen:
            seen.add(r["text"].lower())
            out.append(r)
    return out


def load_gold(split: str) -> list[dict]:
    rows = [json.loads(l) for l in (ROOT / "data/intent" / f"gold_{split}.jsonl").read_text().splitlines() if l.strip()]
    out, seen = [], set()
    for r in rows:
        if r["variant"] != "clean" or r["group"] in seen:
            continue
        seen.add(r["group"])
        out.append({"text": r["source_text"], "label": r["label"], "params": r.get("params") or {},
                    "device": r.get("device") or {}, "src": f"gold_{split}"})
    return out


def all_texts() -> list[dict]:
    """Danh sách {text, label, params, device, src, split}; extra chia dev/test theo băm văn bản."""
    out = []
    for split in ("dev", "test"):
        for r in load_gold(split):
            out.append({**r, "split": split})
    gold_seen = {r["text"].lower() for r in out}
    for r in extra_rows():
        if r["text"].lower() in gold_seen:
            continue
        out.append({**r, "device": {}, "split": "dev" if _h(r["text"]) % 2 == 0 else "test"})
    return out


if __name__ == "__main__":
    import collections
    t = all_texts()
    print(len(t), collections.Counter((r["split"], r["src"]) for r in t))
