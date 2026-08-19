"""Bổ sung câu vào bộ dữ liệu ý định — KHÔNG ghi đè phần đã có.

Chạy:
    python tools/augment_intent_dataset.py --dry-run     # xem sẽ thêm gì
    python tools/augment_intent_dataset.py
    python tools/augment_intent_dataset.py --only chat

Khác `gen_intent_dataset.py` ở đúng một điểm, và đó là lý do file này tồn tại:
`gen_intent_dataset.py` dựng `train.jsonl`/`eval.jsonl` LẠI TỪ ĐẦU từ những nhãn
nó vừa sinh. Chạy nó với `--only chat` là xoá sạch 15 nhãn còn lại, và mất luôn
phần đã soát tay. File này đọc bộ hiện có vào rồi chỉ THÊM, nên dùng được để vá
từng lỗ hổng mà không đụng tới phần đang tốt.

Chống trùng ba lớp: trùng trong cùng mẻ, trùng với bộ đã có, và trùng câu nhưng
KHÁC nhãn (mâu thuẫn — bỏ cả câu mới, giữ nguyên câu cũ đã soát).

CHIẾN LƯỢC PHỦ: mỗi nhãn chia thành nhiều CHỦ ĐỀ nhỏ, xin riêng từng chủ đề.
Xin 200 câu `chat` trong một lượt thì model trả về 200 biến thể của hai ba kiểu
nói mà nó nghĩ tới đầu tiên — đo được ở mẻ trước: 52 câu `chat` mà KHÔNG câu nào
là câu chào. Chia chủ đề là ép nó đi hết bề rộng thay vì đào sâu một chỗ.
"""
import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import config  # noqa: E402
from models import vlm  # noqa: E402
from schemas import Intent  # noqa: E402
from tools.gen_intent_dataset import (  # noqa: E402
    LABELS, _REALISM, _SCHEMA, _clean, _is_unaccented,
)

OUT_DIR = PROJ / "data" / "intent"

# `_REALISM` của `gen_intent_dataset.py` cấm thẳng việc chào hỏi thiết bị:
# "KHÔNG xưng hô, KHÔNG gọi tên thiết bị... Người ta bảo máy làm việc, không
# chào hỏi máy". Đúng cho 15 nhãn ra lệnh, nhưng nó CHỐNG LẠI chủ đề chào hỏi.
#
# Đo được hậu quả: mẻ đầu xin 45 câu chào, nhận về 41 câu giữ lại mà gần như
# không câu nào là câu chào — model bị hai chỉ thị ngược nhau nên nghe theo cái
# cấm. Nên chủ đề xã giao phải có khối luật riêng, không vá bằng cách nhét thêm
# một dòng ngoại lệ vào cuối prompt.
_REALISM_SOCIAL = """\
Người nói là NGƯỜI KHIẾM THỊ đeo kính hỗ trợ có trợ lý giọng nói. Đây là lúc họ
BẮT CHUYỆN hoặc KẾT THÚC trò chuyện với trợ lý — không phải lúc ra lệnh.

BẮT BUỘC:

1. Đây LÀ câu chào / câu xã giao. Cứ viết đúng như vậy.
2. Rất ngắn. Chủ yếu 1-5 chữ. "xin chào", "chào buổi sáng", "alo", "ê",
   "có nghe không", "cảm ơn nhé", "thôi nhé".
3. KHÔNG gọi tên thiết bị ("kính ơi", "trợ lý ơi") — người ta không đặt tên cho
   nó. Cũng KHÔNG xưng hô kiểu bác/cháu/con/tui.

CHỖ CẦN ĐA DẠNG:
Cùng một việc chào thì nói được bằng bao nhiêu kiểu. Trộn: chào trang trọng,
chào cụt lủn, gọi thử xem máy còn nghe không, chào theo buổi trong ngày, hỏi
thăm, câu mở đầu ngập ngừng.

TUYỆT ĐỐI KHÔNG dùng dấu câu, không viết hoa, không emoji — đây là văn bản do
máy nhận dạng giọng nói ghi ra. Không đánh số, không giải thích.
Không câu nào lặp cấu trúc của câu khác.

BẮT BUỘC VIẾT ĐỦ DẤU TIẾNG VIỆT: "xin chào", KHÔNG PHẢI "xin chao".
"""

_REALISM_BLOCKS = {"command": _REALISM, "social": _REALISM_SOCIAL}

# nhãn -> [(tên chủ đề, mô tả, số câu xin, khối realism)]
#
# `chat` được chia nhỏ nhất vì nó là nhãn "mọi thứ còn lại": ranh giới của nó
# là ranh giới của 15 nhãn kia cộng lại, nên nó cần bề rộng chứ không cần chiều
# sâu. Nhóm `chào hỏi` đứng đầu vì bộ hiện tại có ĐÚNG 0 câu chào — đo thật:
# "xin chào" ra `unknown` conf 0.398, tức mọi câu chào đều rơi xuống Gemini.
#
# MÔ TẢ CHỦ ĐỀ PHẢI NÓI RÕ CÁI KHÔNG THUỘC VỀ NÓ. Mẻ đầu để mô tả mở
# ("hỏi về chính cái kính", "câu nối tiếp") và model trôi sang ra lệnh cho thiết
# bị — "bật đèn lên", "chụp ảnh đi", "chuyển bài khác", "báo thức sáu giờ" đều
# về nhãn `chat`. Train trên đó là dạy model gọi mọi lệnh thiết bị là `chat`.
THEMES: dict[str, list[tuple[str, str, int, str]]] = {
    Intent.CHAT: [
        ("chào hỏi",
         "câu CHÀO HỎI và mở đầu trò chuyện: xin chào, chào buổi sáng, alo, "
         "ê, có đó không, có nghe không, dậy chưa, khoẻ không. Gồm cả câu chào "
         "cụt lủn một hai chữ", 45, "social"),
        ("kết thúc",
         "câu CẢM ƠN, TẠM BIỆT, kết thúc trò chuyện: cảm ơn nhé, thôi vậy đủ "
         "rồi, chào tạm biệt, hẹn gặp lại, ngủ ngon", 30, "social"),
        ("giờ và ngày",
         "hỏi GIỜ, ngày, thứ, tháng, mùa: mấy giờ rồi, hôm nay thứ mấy, còn "
         "bao lâu nữa tới trưa, sắp tết chưa", 30, "command"),
        ("thời tiết",
         "hỏi THỜI TIẾT: trời thế nào, có mưa không, nóng không, nhiệt độ bao "
         "nhiêu, mai trời ra sao, có nắng không", 30, "command"),
        ("tin tức",
         "hỏi TIN TỨC, thời sự, giá cả, tỉ số, sự kiện đang diễn ra — nhưng "
         "KHÔNG chỉ vào vật nào trước mặt: tin gì mới, giá vàng bao nhiêu, "
         "đội nào thắng, có gì hot không", 30, "command"),
        ("kiến thức chung",
         "hỏi KIẾN THỨC CHUNG, định nghĩa, tính toán, cách làm: một cân bằng "
         "bao nhiêu gam, ai viết truyện kiều, nước sôi ở bao nhiêu độ, "
         "hai mươi nhân ba là mấy", 35, "command"),
        ("quanh đây",
         "hỏi ĐỊA ĐIỂM quanh chỗ đang đứng, KHÔNG phải nhờ chỉ đường và KHÔNG "
         "phải đặt xe — chỉ hỏi cho biết: quán ăn nào gần đây không, nhà thuốc "
         "gần nhất ở đâu, đây là đường nào, tôi đang ở khu nào", 35, "command"),
        ("than thở",
         "THAN THỞ, cảm thán, nói về trạng thái cơ thể và tâm trạng: mệt quá, "
         "đói bụng ghê, buồn ngủ rồi, chán quá, nóng nực, đau lưng quá", 30, "command"),
        ("giải trí",
         "nhờ KỂ CHUYỆN, đọc thơ, đố vui, nói chuyện cho đỡ buồn: kể chuyện "
         "cười đi, đọc bài thơ nào đó, đố tôi câu gì đi. "
         "TUYỆT ĐỐI KHÔNG viết câu bảo MỞ NHẠC hay chuyển bài — đó là nhãn khác",
         30, "command"),
        ("về thiết bị",
         "HỎI về chính cái kính: còn bao nhiêu pin, làm được những gì, có nghe "
         "rõ không, vừa nãy nói gì, nhắc lại câu vừa rồi. "
         "PHẢI LÀ CÂU HỎI hoặc câu nhờ nhắc lại. TUYỆT ĐỐI KHÔNG viết lệnh điều "
         "khiển thiết bị (bật đèn, chụp ảnh, bật định vị, báo thức, kết nối, "
         "đổi chế độ) — những thứ đó KHÔNG thuộc nhãn này",
         30, "command"),
        ("nối tiếp",
         "câu NỐI TIẾP một câu trả lời vừa nghe, hỏi thêm cho rõ: còn cái kia "
         "thì sao, tại sao lại thế, kể tiếp đi, nói rõ hơn coi, vậy còn gì nữa, "
         "cái đó nghĩa là sao. "
         "PHẢI đủ chữ để đoán ra là đang hỏi thêm — ít nhất 3 chữ. TUYỆT ĐỐI "
         "KHÔNG viết mảnh vụn một hai chữ kiểu 'bên trái', 'cái vạch', "
         "'chậm lại' — những thứ đó không đọc ra ý gì và thuộc nhãn khác",
         30, "command"),
    ],
    Intent.MUSIC_VOLUME: [
        ("tăng giảm",
         "chỉnh ÂM LƯỢNG nhạc — cả tăng lẫn giảm, nói đủ kiểu: to lên chút, "
         "nhỏ lại đi, vặn to, bé quá nghe không rõ, ồn quá, chỉnh lên bảy mươi",
         45, "command"),
    ],
    Intent.RIDE_CONFIRM: [
        ("chốt huỷ",
         "XÁC NHẬN hoặc HUỶ chuyến xe vừa được báo giá — cả hai chiều: ừ đặt "
         "đi, ok chốt, đồng ý, thôi khỏi, huỷ đi, không đi nữa, để lát nữa",
         45, "command"),
    ],
}

# Vòng ranh giới có TRỌNG ĐIỂM, khác vòng ranh giới chung của
# `gen_intent_dataset.py`: chỉ nhắm những cặp đã ĐO ĐƯỢC là đang lẫn.
#
# `chat` <-> `ocr` đứng đầu vì vừa tìm ra 4 câu bị gán sai đúng trên trục này —
# chữ "đọc" mang hai nghĩa (đọc chữ trên vật trước mặt / đọc nội dung lấy từ
# mạng) và bộ dữ liệu cũ không dạy model tách chúng ra.
FOCUS_BOUNDARIES: list[tuple[str, str, str, int]] = [
    (Intent.CHAT, Intent.OCR,
     "chữ 'đọc' có hai nghĩa. ocr = đọc chữ in trên MỘT VẬT CỤ THỂ trước mặt, "
     "câu luôn chỉ vào vật đó ('đọc nhãn NÀY', 'trên hộp ghi gì', 'đọc tờ giấy "
     "trước mặt'). chat = nhờ đọc NỘI DUNG lấy từ mạng hoặc từ kiến thức, không "
     "có vật nào trước mặt ('đọc tin tức mới nhất', 'đọc báo đi', 'đọc tin thể "
     "thao'). Viết cả hai bên thật sát nhau", 40),
    # Cặp này thêm SAU khi mẻ đầu làm hỏng `find`: chủ đề "quanh đây" của `chat`
    # dạy model rằng mẫu "X ở đâu" thuộc `chat`, và "Gói bánh của tôi ở đâu"
    # (vốn là `find`, đo bằng test roundtrip TTS->STT) rơi theo. Cùng một mặt
    # chữ, khác nhau ở chỗ X là ĐỒ VẬT trong tầm tay hay ĐỊA ĐIỂM ngoài đời.
    (Intent.CHAT, Intent.FIND,
     "cả hai đều hay nói dạng 'X ở đâu'. find = X là ĐỒ VẬT cụ thể trong tầm "
     "tay, thường là đồ của chính người dùng ('gói bánh của tôi ở đâu', 'cái "
     "điều khiển đâu rồi', 'ly nước để đâu'). chat = X là ĐỊA ĐIỂM ngoài đời, "
     "một cơ sở hay dịch vụ ('nhà thuốc gần nhất ở đâu', 'quanh đây có quán ăn "
     "không', 'bến xe buýt chỗ nào'). Viết cả hai bên cùng dùng mẫu 'ở đâu'",
     40),
    (Intent.CHAT, Intent.NAV_START,
     "chat = HỎI CHO BIẾT một địa điểm ở đâu, gần không ('nhà thuốc gần nhất ở "
     "đâu', 'quanh đây có quán ăn không'). nav_start = nhờ CHỈ ĐƯỜNG, bắt đầu "
     "dẫn đi ('chỉ đường tới nhà thuốc', 'dẫn tôi ra chợ')", 32),
    (Intent.CHAT, Intent.MUSIC_PLAY,
     "chat = nói CHUYỆN về nhạc, hỏi thông tin về bài/ca sĩ mà không bảo mở "
     "('bài này ai hát', 'nhạc gì thế'). music_play = bảo MỞ nhạc, gồm cả câu "
     "chỉ có tên ca sĩ khi đang được hỏi muốn nghe của ai", 32),
    (Intent.CHAT, Intent.SPACE,
     "chat = hỏi chuyện chung, hỏi vị trí mình đang ở khu nào ('tôi đang ở "
     "đâu', 'đây là quận nào'). space = hỏi TRƯỚC MẶT CÓ GÌ, tả khung cảnh "
     "nhìn thấy qua camera ('trước mặt có gì', 'phòng này thế nào')", 32),
]


def _ask(prompt: str, model: str, tries: int = 4) -> list[str]:
    """Một lượt xin câu, có thử lại. Hết lượt vẫn hỏng thì trả rỗng, không chết.

    Quota Gemini tính theo phút: một mẻ đủ nhãn là vài chục lượt gọi, gặp 429 ở
    giữa là chuyện thường. Bỏ cả mẻ vì một lượt hỏng thì tốn lại từ đầu.
    """
    for attempt in range(tries):
        try:
            reply = vlm.generate_json(prompt, schema=_SCHEMA, model=model)
        except Exception as exc:  # noqa: BLE001
            wait = 6.0 * (attempt + 1)
            print(f"     lỗi ({str(exc)[:60]}), chờ {wait:.0f}s thử lại", flush=True)
            time.sleep(wait)
            continue
        rows = reply.get("cau") if isinstance(reply, dict) else None
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, str) and r.strip()]
    return []


def _theme_prompt(label: str, desc: str, n: int, realism: str) -> str:
    return (
        f"Viết {n} câu thoại tiếng Việt khác nhau, tất cả cùng thuộc loại sau:\n\n"
        f"  {desc}\n\n{_REALISM_BLOCKS[realism]}\n"
        f"Trả về JSON có trường 'cau' là mảng {n} chuỗi."
    )


# ── Cổng kiểm nhãn độc lập ───────────────────────────────────────────────
#
# VÌ SAO BẮT BUỘC: vòng sinh bảo model "viết N câu thuộc nhãn X" rồi tin luôn
# nhãn X. Niềm tin đó hỏng thật — mẻ đầu của chính file này, chủ đề "về thiết
# bị" của nhãn `chat`, đẻ ra "bật đèn lên", "chụp ảnh đi", "bật định vị"; chủ đề
# "nối tiếp" đẻ ra "bên trái", "cái vạch". Không có cổng này thì 605 câu vào
# thẳng bộ dữ liệu.
#
# Vòng kiểm hỏi NGƯỢC chiều: đưa câu, KHÔNG nói nhãn đã gán, bắt chọn 1 trong 16
# nhãn. Lệch nhau thì bỏ câu. Đây là chỗ đánh đổi recall lấy độ sạch — và đánh
# đổi đúng hướng, vì câu sai nhãn không chỉ vô dụng mà còn dạy ngược.
_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "nhan": {"type": "array", "items": {"type": "string", "enum": list(LABELS)}},
    },
    "required": ["nhan"],
}
_VERIFY_BATCH = 25


def _verify_prompt(batch: list[str]) -> str:
    desc = "\n".join(f"- {k}: {v}" for k, v in LABELS.items())
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
    return (
        "Đây là các câu lệnh thoại của người khiếm thị dùng kính hỗ trợ, đã được "
        "máy nhận dạng giọng nói ghi lại.\n\n"
        f"Với MỖI câu, chọn đúng một nhãn ý định trong danh sách:\n\n{desc}\n\n"
        "Chỉ đọc bản thân câu, đừng đoán theo thứ tự hay theo câu bên cạnh — "
        "các câu này không liên quan gì tới nhau.\n\n"
        f"Các câu:\n{numbered}\n\n"
        f"Trả JSON: trường 'nhan' là mảng đúng {len(batch)} nhãn, đúng thứ tự trên."
    )


def _verify(fresh: dict[str, str], model: str, gap: float) -> tuple[dict[str, str], list]:
    """Giữ lại những câu mà vòng gán nhãn độc lập ĐỒNG Ý. Trả (giữ, bỏ)."""
    items = sorted(fresh.items())
    kept: dict[str, str] = {}
    rejected: list[tuple[str, str, str]] = []

    for start in range(0, len(items), _VERIFY_BATCH):
        chunk = items[start:start + _VERIFY_BATCH]
        texts = [t for t, _ in chunk]
        print(f"[kiểm] câu {start + 1}-{start + len(chunk)}/{len(items)}...", flush=True)
        try:
            reply = vlm.generate_json(_verify_prompt(texts), schema=_VERIFY_SCHEMA, model=model)
        except Exception as exc:  # noqa: BLE001
            print(f"     lỗi ({str(exc)[:60]}) — GIỮ NGUYÊN cả lô, sẽ phải soát tay",
                  file=sys.stderr)
            kept.update(dict(chunk))
            time.sleep(gap * 2)
            continue
        votes = reply.get("nhan") if isinstance(reply, dict) else None
        if not isinstance(votes, list) or len(votes) != len(chunk):
            print("     trả sai số lượng nhãn — GIỮ NGUYÊN cả lô", file=sys.stderr)
            kept.update(dict(chunk))
            time.sleep(gap)
            continue
        for (text, label), vote in zip(chunk, votes):
            if vote == label:
                kept[text] = label
            else:
                rejected.append((text, label, vote))
        time.sleep(gap)

    return kept, rejected


def _boundary_prompt(a: str, b: str, note: str, n: int) -> str:
    return (
        f"Hai ý định này hay bị lẫn: '{a}' và '{b}'.\n\n  {note}.\n\n"
        f"Viết {n} câu thoại nằm SÁT ranh giới — câu mà nghe thoáng qua dễ xếp "
        f"nhầm sang bên kia, nhưng đọc kỹ vẫn xác định được. Chia đôi, một nửa "
        f"thuộc '{a}', một nửa thuộc '{b}'.\n\n{_REALISM}\n"
        f"Trả về JSON: 'cau' là mảng {n} chuỗi dạng \"<nhãn>\\t<câu>\", "
        f"nhãn chỉ được là '{a}' hoặc '{b}'."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="chỉ vá vài nhãn, cách nhau bởi dấu phẩy")
    ap.add_argument("--skip-boundaries", action="store_true")
    # Vá riêng một ranh giới bị hỏng mà không sinh lại toàn bộ chủ đề: thêm một
    # cặp vào `FOCUS_BOUNDARIES` rồi chạy cờ này là đủ.
    ap.add_argument("--only-boundaries", default="",
                    help="chỉ chạy vòng ranh giới, lọc theo tên nhãn (vd. 'find')")
    ap.add_argument("--skip-verify", action="store_true",
                    help="bỏ vòng kiểm nhãn độc lập (KHÔNG nên — xem `_verify`)")
    ap.add_argument("--eval-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=20260816)
    ap.add_argument("--gap", type=float, default=3.0, help="giây nghỉ giữa hai lượt gọi")
    ap.add_argument("--dry-run", action="store_true", help="in ra, không ghi file")
    # Bước này cần model VIẾT ĐA DẠNG, không cần nhanh — ngược tiêu chí chọn
    # model lúc chạy thật.
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    args = ap.parse_args()

    # ── Bộ hiện có: vừa để chống trùng, vừa là thứ tuyệt đối không được đụng ──
    existing: dict[str, str] = {}
    for split in ("train", "eval"):
        for line in (OUT_DIR / f"{split}.jsonl").open(encoding="utf-8"):
            row = json.loads(line)
            existing[_clean(row["text"])] = row["label"]
    print(f"Bộ hiện có: {len(existing)} câu / {len(set(existing.values()))} nhãn\n")

    targets = [x for x in args.only.split(",") if x] or list(THEMES)

    fresh: dict[str, str] = {}
    stats = {"trùng bộ cũ": 0, "mâu thuẫn nhãn": 0, "trùng trong mẻ": 0, "tuột dấu": 0}

    def add(text: str, label: str) -> bool:
        key = _clean(text)
        if len(key) < 2:
            return False
        if _is_unaccented(key, label):
            stats["tuột dấu"] += 1
            return False
        old = existing.get(key)
        if old is not None:
            # Câu cũ đã qua soát tay, luôn thắng. Chỉ đếm để biết mẻ này trùng
            # bao nhiêu — trùng nhiều nghĩa là chủ đề đã bão hoà, xin thêm vô ích.
            stats["mâu thuẫn nhãn" if old != label else "trùng bộ cũ"] += 1
            return False
        if key in fresh:
            if fresh[key] != label:
                stats["mâu thuẫn nhãn"] += 1
                fresh.pop(key)
            else:
                stats["trùng trong mẻ"] += 1
            return False
        fresh[key] = label
        return True

    if not args.only_boundaries:
        for label in targets:
            for theme, desc, n, realism in THEMES.get(label, []):
                print(f"[{label} / {theme}] xin {n} câu...", flush=True)
                rows = _ask(_theme_prompt(label, desc, n, realism), args.model)
                kept = sum(add(r, label) for r in rows)
                print(f"     nhận {len(rows)}, giữ {kept}", flush=True)
                time.sleep(args.gap)

    if args.only_boundaries or (not args.skip_boundaries and not args.only):
        wanted = {x for x in args.only_boundaries.split(",") if x}
        for a, b, note, n in FOCUS_BOUNDARIES:
            if wanted and not (wanted & {a, b}):
                continue
            print(f"[ranh giới] {a} <-> {b}, xin {n} câu...", flush=True)
            rows = _ask(_boundary_prompt(a, b, note, n), args.model)
            kept = 0
            for r in rows:
                lab, _, text = r.partition("\t")
                if lab.strip() in (a, b):
                    kept += add(text, lab.strip())
            print(f"     nhận {len(rows)}, giữ {kept}", flush=True)
            time.sleep(args.gap)

    if not fresh:
        print("\nKhông thêm được câu nào.", file=sys.stderr)
        return 1

    if not args.skip_verify:
        print(f"\n{'=' * 60}\nKiểm nhãn độc lập {len(fresh)} câu mới\n")
        before = len(fresh)
        fresh, rejected = _verify(fresh, args.model, args.gap)
        print(f"\nGiữ {len(fresh)}/{before}, bỏ {len(rejected)} câu vòng kiểm không đồng ý")
        if rejected:
            by_pair = Counter((gán, vote) for _, gán, vote in rejected)
            print("\nBỏ nhiều nhất (gán -> vòng kiểm nói là):")
            for (gán, vote), n in by_pair.most_common(10):
                print(f"  {gán:16s} -> {vote:16s} {n:3d}")
            path = OUT_DIR / "rejected.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for text, gán, vote in rejected:
                    f.write(json.dumps(
                        {"text": text, "label": gán, "verify": vote}, ensure_ascii=False
                    ) + "\n")
            print(f"\nCâu bị bỏ ghi ra {path} — soát lại, có câu là vòng kiểm sai.")
        if not fresh:
            print("\nVòng kiểm bỏ hết.", file=sys.stderr)
            return 1

    print(f"\n{'=' * 60}")
    print(f"Câu MỚI giữ lại: {len(fresh)}")
    for key, val in stats.items():
        print(f"  bỏ vì {key}: {val}")
    print("\nSố câu mới mỗi nhãn:")
    counts = Counter(fresh.values())
    for label, n in counts.most_common():
        print(f"  {label:16s} +{n:4d}  (cũ {sum(1 for v in existing.values() if v == label):4d})")

    if args.dry_run:
        print("\n--dry-run: không ghi file. 40 câu mẫu:")
        for text, label in list(sorted(fresh.items()))[:40]:
            print(f"  {label:16s} {text}")
        return 0

    # Chia phân tầng theo nhãn rồi NỐI vào file, giữ nguyên thứ tự phần cũ.
    rng = random.Random(args.seed)
    by_label: dict[str, list[str]] = {}
    for text, label in sorted(fresh.items()):
        by_label.setdefault(label, []).append(text)

    add_to = {"train": [], "eval": []}
    for label, texts in sorted(by_label.items()):
        rng.shuffle(texts)
        cut = max(1, round(len(texts) * args.eval_frac))
        add_to["eval"] += [{"text": t, "label": label} for t in texts[:cut]]
        add_to["train"] += [{"text": t, "label": label} for t in texts[cut:]]

    for split, rows in add_to.items():
        rng.shuffle(rows)
        path = OUT_DIR / f"{split}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        total = sum(1 for _ in path.open(encoding="utf-8"))
        print(f"-> {path}  +{len(rows)} câu (tổng {total})")

    print("\nSOÁT LẠI BẰNG MẮT trước khi huấn luyện.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
