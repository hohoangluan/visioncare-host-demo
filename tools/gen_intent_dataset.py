"""Sinh bộ câu huấn luyện cho bộ phân loại ý định (SetFit).

Chạy:
    python tools/gen_intent_dataset.py            # sinh đủ 16 nhãn + vòng ranh giới
    python tools/gen_intent_dataset.py --only ocr,chat
    python tools/gen_intent_dataset.py --per-class 60

Tốn quota Gemini: ~16 lệnh gọi cho vòng chính + ~8 cho vòng ranh giới. Kết quả
ghi vào `data/intent/*.jsonl` và ĐƯỢC commit — đây là dữ liệu, không phải cache.

Vì sao sinh bằng model thay vì tự viết tay: 16 nhãn × 40 câu là 640 câu, viết
tay thì người viết sẽ vô thức lặp lại một kiểu nói của chính mình. Chỗ cần
người là BƯỚC SOÁT LẠI sau khi sinh, không phải bước gõ.
"""
import argparse
import json
from collections import Counter
import random
import re
import sys
import unicodedata
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import config  # noqa: E402
from models import vlm  # noqa: E402
from pipeline import stt  # noqa: E402
from schemas import Intent  # noqa: E402

OUT_DIR = PROJ / "data" / "intent"

# Mô tả từng nhãn — GIỮ ĐỒNG BỘ với `_PROMPT_TEMPLATE` trong pipeline/intent.py.
# Lệch nhau nghĩa là classifier được huấn luyện trên một định nghĩa khác với
# định nghĩa mà phần còn lại của hệ thống đang dùng.
LABELS: dict[str, str] = {
    Intent.OCR: "muốn đọc to chữ/văn bản in trong ảnh — sách, giấy tờ, nhãn "
                "sản phẩm, hạn sử dụng, tin nhắn viết tay, biển hiệu",
    Intent.FIND: "muốn tìm một đồ vật cụ thể ở đâu trong phòng, hoặc hỏi hướng "
                 "đi ngắn để với tới đồ vật đó",
    Intent.MONEY: "muốn biết mệnh giá tờ tiền đang cầm trên tay",
    Intent.SPACE: "muốn biết không gian phía trước/xung quanh có những gì — "
                  "mô tả khung cảnh, có ai không, phòng thế nào",
    Intent.HAZARD: "muốn biết phía trước có an toàn để bước tiếp không, có vật "
                   "cản gì cần tránh không",
    Intent.NAV_START: "muốn bắt đầu chỉ đường / điều hướng đi bộ ngoài trời tới "
                      "một địa điểm cụ thể",
    Intent.NAV_STOP: "muốn dừng / tắt chỉ đường đang chạy",
    Intent.CONTACT_CALL: "muốn gọi điện cho một người trong danh bạ",
    Intent.EMERGENCY_CALL: "muốn gọi cấp cứu, gọi khẩn cấp, hoặc phát tín hiệu SOS",
    Intent.RIDE_QUOTE: "muốn đặt xe / gọi Grab / hỏi giá một chuyến xe đi đâu đó",
    Intent.RIDE_CONFIRM: "muốn xác nhận hoặc huỷ chuyến xe vừa được báo giá",
    Intent.MUSIC_PLAY: "muốn phát nhạc / mở một bài hát / nghe một ca sĩ. Bao "
                       "gồm cả câu trả lời cho câu hỏi 'bạn muốn nghe của ai?' "
                       "— chỉ một cái tên ca sĩ, hoặc 'bài nào cũng được'",
    Intent.MUSIC_STOP: "muốn tắt nhạc, dừng phát nhạc",
    Intent.MUSIC_VOLUME: "muốn tăng/giảm/chỉnh âm lượng",
    # Nhãn MẶC ĐỊNH, không phải một nhãn ngang hàng: mọi câu không thuộc 14 nhãn
    # trên đều về đây, kể cả câu bộ nhận dạng giọng nói nghe nhầm thành chuỗi từ
    # rời rạc. Nhãn `unknown` cũ đã bỏ — xem `_LABELS` trong `pipeline/intent.py`.
    Intent.CHAT: "MỌI thứ không thuộc các nhãn trên — trò chuyện tự do, hỏi đáp "
                 "thường ngày, chào hỏi, tạm biệt, hỏi giờ, hỏi thời tiết, hỏi "
                 "mình đang ở đâu, than thở, nhờ kể chuyện. Gồm cả câu cụt, sai "
                 "ngữ pháp, hoặc nghe không ra nghĩa gì",
}

# Yêu cầu chung về độ thật của câu. Đây là phần quyết định chất lượng bộ dữ
# liệu — bỏ nó đi thì model sinh ra 40 biến thể lịch sự của cùng một câu.
#
# ĐÃ SỬA sau vòng sinh đầu: vòng đó bảo model đa dạng hoá cả cách xưng hô
# ("cháu ơi coi dùm bác", "kính ơi", tôi/tui/bác/con/cháu). Sai trục. Người
# dùng ra lệnh cho thiết bị thì không xưng hô, và cũng không có ngần ấy kiểu
# gọi — cho vào chỉ dạy classifier phân biệt thứ nó sẽ không bao giờ gặp, mà
# lấy mất chỗ của trục đa dạng THẬT SỰ có ích: cùng một việc thì diễn đạt được
# bằng bao nhiêu cách khác nhau.
_REALISM = """\
Người nói là NGƯỜI KHIẾM THỊ đeo kính hỗ trợ, RA LỆNH cho thiết bị bằng giọng
nói. Đây là câu lệnh, không phải câu nói chuyện với người.

BẮT BUỘC:

1. KHÔNG xưng hô, KHÔNG gọi tên thiết bị. Không "kính ơi", không "cháu ơi",
   không "bác", "con", "tui", "cậu", "mày". Không "ạ" cuối câu.
   Người ta bảo máy làm việc, không chào hỏi máy.
2. Ngắn. Chủ yếu 2-8 chữ. Rất ít câu quá 10 chữ.
3. Đi thẳng vào việc, thường bắt đầu bằng động từ: "đọc chữ này", "tắt nhạc",
   "gọi cho mẹ", "còn bao xa".

CHỖ CẦN ĐA DẠNG — và chỉ chỗ này:
Cùng MỘT việc thì nói được bằng bao nhiêu kiểu khác nhau. Đổi động từ, đổi
cách hỏi, đổi cái được nhắc tới, nói thẳng hoặc nói vòng. Ví dụ cùng ý "đọc
chữ": "đọc chữ này", "cái này ghi gì", "trên hộp viết gì", "đọc nhãn", "chữ gì
đây", "xem hạn sử dụng", "đọc nội dung", "có chữ gì không".

ĐƯỢC PHÉP nhưng THƯA THỚT (dưới một phần tư số câu, đừng câu nào cũng có):

4. Tiểu từ cuối câu: "đi", "với", "nhé", "cái", "coi", "xem".
5. Từ đệm đầu câu khi người ta ngập ngừng: "à", "ừm", "ờ", "cái này".
6. Từ vựng vùng miền NẰM TRONG chính việc cần làm: coi-xem, chi-gì, mô-đâu,
   răng-sao, bao lăm-bao nhiêu. Không phải trong cách xưng hô.
7. Câu thiếu chủ ngữ, sai ngữ pháp, nói cụt.

TUYỆT ĐỐI KHÔNG dùng dấu câu, không viết hoa, không emoji — đây là văn bản do
máy nhận dạng giọng nói ghi ra. Không đánh số, không giải thích.
Không câu nào lặp cấu trúc của câu khác.

BẮT BUỘC VIẾT ĐỦ DẤU TIẾNG VIỆT: "gọi cấp cứu", KHÔNG PHẢI "goi cap cuu".
Bộ nhận dạng giọng nói luôn trả về chữ có dấu, nên câu không dấu là câu sẽ
không bao giờ xuất hiện lúc chạy thật.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "cau": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cau"],
}


def _prompt_for(label: str, desc: str, n: int) -> str:
    extra = ""
    if label == Intent.CHAT:
        extra = (
            "\nRIÊNG nhãn này: đây là nhãn MẶC ĐỊNH, nhận mọi câu không thuộc 14 "
            "nhãn kia. Cho vào nhiều câu ngắn, cụt, sai ngữ pháp — 'mấy giờ rồi', "
            "'nóng quá', 'buồn ngủ ghê', 'ê'.\n"
            "Trộn đủ: chào hỏi, tạm biệt, cảm ơn, hỏi giờ, hỏi thời tiết, hỏi tin "
            "tức, hỏi kiến thức chung, hỏi mình đang ở đâu, than thở, nhờ kể "
            "chuyện, hỏi về chính cái kính.\n"
            "Cho vào KHOẢNG MỘT PHẦN MƯỜI số câu là thứ mà bộ nhận dạng giọng nói "
            "phun ra khi nghe phải tiếng ồn hoặc người nói lí nhí: chuỗi âm tiết "
            "tiếng Việt có thật nhưng ghép lại không thành ý — 'ờ à ừm', "
            "'xe xe xe xe', 'lô ca ta xi mà', 'ba bốn ơ kìa'. Chúng cũng thuộc "
            "nhãn này: trợ lý sẽ tự nói là chưa hiểu, chứ không có nhãn riêng.\n"
        )
    if label in (Intent.NAV_START, Intent.RIDE_QUOTE):
        extra = (
            "\nDùng địa danh Việt Nam có thật và đa dạng: chợ Bến Thành, bệnh "
            "viện Bạch Mai, ngã tư Hàng Xanh, bưu điện phường, nhà thờ Đức Bà, "
            "số 15 Lê Lợi, nhà con gái tôi, quán cà phê đầu ngõ...\n"
        )
    if label == Intent.MUSIC_PLAY:
        extra = (
            "\nDùng tên bài hát và ca sĩ Việt Nam có thật, trộn nhiều thế hệ "
            "(nhạc trẻ, bolero, nhạc cách mạng, nhạc trịnh). Nhớ cho vào vài câu "
            "chỉ có mỗi tên ca sĩ, và vài câu kiểu 'bài nào cũng được', 'cứ phát đi'.\n"
        )
    if label == Intent.CONTACT_CALL:
        # Ở nhãn này, quan hệ họ hàng là TÊN NGƯỜI ĐƯỢC GỌI (tham số
        # `contact_name`), không phải cách người dùng tự xưng — nên vẫn cần đa
        # dạng, khác với luật cấm xưng hô ở trên.
        extra = (
            "\nTên người được gọi: trộn tên riêng Việt Nam có thật với cách gọi "
            "theo quan hệ — mẹ, má, vợ, chồng, con gái, anh hai, chú Bảy, "
            "bác sĩ Hằng. Đây là tên người trong danh bạ, không phải cách người "
            "dùng tự xưng.\n"
        )

    return (
        f"Viết {n} câu lệnh thoại tiếng Việt khác nhau, tất cả cùng thuộc MỘT ý "
        f"định duy nhất sau đây:\n\n"
        f"  {label}: {desc}\n\n"
        f"{_REALISM}{extra}\n"
        f"Trả về JSON có trường 'cau' là mảng {n} chuỗi."
    )


# Các cặp nhãn dễ lẫn nhau. Sinh riêng một vòng câu SÁT RANH GIỚI cho từng cặp:
# đây là chỗ classifier sẽ sai, và cũng là chỗ vài chục câu có giá trị hơn vài
# trăm câu dễ.
BOUNDARIES = [
    (Intent.SPACE, Intent.HAZARD,
     "một bên là hỏi 'phía trước có GÌ' (mô tả khung cảnh), bên kia là hỏi "
     "'phía trước có AN TOÀN không' (vật cản, nguy hiểm)"),
    (Intent.FIND, Intent.SPACE,
     "một bên là tìm MỘT đồ vật cụ thể, bên kia là mô tả CẢ khung cảnh"),
    (Intent.NAV_START, Intent.RIDE_QUOTE,
     "một bên là tự ĐI BỘ có người chỉ đường, bên kia là ĐẶT XE chở đi"),
    (Intent.MUSIC_PLAY, Intent.CHAT,
     "một bên là bảo mở nhạc, bên kia là nói CHUYỆN về nhạc/ca sĩ mà không bảo mở"),
    (Intent.MUSIC_VOLUME, Intent.MUSIC_STOP,
     "một bên là giảm âm lượng (nhạc vẫn chạy), bên kia là tắt hẳn"),
    (Intent.EMERGENCY_CALL, Intent.CONTACT_CALL,
     "một bên là gọi cấp cứu/khẩn cấp, bên kia là gọi một người quen"),
    (Intent.OCR, Intent.FIND,
     "một bên là ĐỌC CHỮ trên vật, bên kia là TÌM ra vật đó nằm đâu"),
]


def _boundary_prompt(a: str, b: str, note: str, n: int) -> str:
    return (
        f"Hai ý định này hay bị lẫn với nhau: '{a}' và '{b}' — {note}.\n\n"
        f"  {a}: {LABELS[a]}\n"
        f"  {b}: {LABELS[b]}\n\n"
        f"Viết {n} câu lệnh thoại nằm SÁT ranh giới giữa hai bên — câu mà nghe "
        f"thoáng qua dễ xếp nhầm sang bên kia, nhưng đọc kỹ thì vẫn xác định "
        f"được. Chia đôi, một nửa thuộc '{a}', một nửa thuộc '{b}'.\n\n"
        f"{_REALISM}\n"
        f"Trả về JSON: trường 'cau' là mảng {n} chuỗi dạng \"<nhãn>\\t<câu>\", "
        f"nhãn chỉ được là '{a}' hoặc '{b}'."
    )


def _clean(text: str) -> str:
    """Đưa câu về đúng hình dạng mà `stt.transcribe()` sẽ trả ra lúc chạy thật.

    Huấn luyện trên tiếng Việt gõ tay có dấu câu rồi đem chạy trên đầu ra STT
    (không dấu câu, chữ hoa đã hạ) là tự tạo lệch miền ngay từ đầu.
    """
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r"[.,!?;:\"'’“”…()\[\]/\\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return stt._normalize(text)


# Âm tiết tiếng Việt vốn không mang dấu — có thật trong câu đúng chính tả, nên
# không được tính là bằng chứng mất dấu.
_BARE_OK = re.compile(r"^[a-z]+$")


def _is_unaccented(text: str, label: str) -> bool:
    """Câu bị Gemini viết tuột dấu ("goi cap cuu") -> loại.

    Đây là chốt chặn xác định, không phải lời dặn trong prompt. Mẻ đầu đã dặn rõ
    mà nhãn `emergency_call` vẫn về 35/55 câu không dấu — nhãn quan trọng nhất
    lại là nhãn hỏng nặng nhất. STT luôn trả chữ có dấu, nên câu không dấu là
    câu không bao giờ gặp lúc chạy thật: giữ lại chỉ làm loãng lớp đó.

    KHÔNG còn miễn cho nhãn nào. Trước đây `unknown` được miễn vì chuỗi âm tiết
    vô nghĩa ("lô ca ta xi", "ta ta ta") không dấu là chuyện thường. Nhãn đó đã
    bỏ và những câu ấy về `chat`, nên miễn cả `chat` là mở toang cửa cho câu
    tuột dấu ở nhãn đông nhất. Đổi lại phải dặn trong prompt là viết chúng có
    dấu ("lô ca ta xi mà"), và STT thật cũng trả chữ có dấu nên thế mới đúng.
    """
    words = [w for w in text.lower().split() if w.isalpha()]
    if len(words) < 3:
        return False
    # Đủ dài mà không chữ nào có dấu -> gần như chắc chắn là bị tuột dấu.
    return all(_BARE_OK.match(w) and w.isascii() for w in words)


def _ask(prompt: str, n: int, model: str) -> list[str]:
    reply = vlm.generate_json(prompt, schema=_SCHEMA, model=model)
    rows = reply.get("cau") if isinstance(reply, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"Gemini trả về không đúng schema: {reply!r}")
    return [r for r in rows if isinstance(r, str) and r.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=40)
    ap.add_argument("--per-boundary", type=int, default=16)
    ap.add_argument("--only", default="", help="chỉ sinh vài nhãn, cách nhau bởi dấu phẩy")
    ap.add_argument("--eval-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--skip-boundaries", action="store_true")
    # Bước này cần model VIẾT ĐA DẠNG, không cần nhanh — ngược hẳn với tiêu chí
    # chọn `GEMINI_INTENT_MODEL` lúc chạy thật. Model lite sinh ra 40 câu na ná
    # nhau. Nhưng để mặc định theo config để không tự ý đốt quota của model to.
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    args = ap.parse_args()

    targets = [x for x in args.only.split(",") if x] or list(LABELS)
    unknown_label = [t for t in targets if t not in LABELS]
    if unknown_label:
        print(f"Nhãn không tồn tại: {unknown_label}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # (câu đã chuẩn hoá) -> nhãn. Trùng câu giữa hai nhãn là mâu thuẫn nhãn,
    # giữ lại cả hai sẽ dạy classifier đúng cái nó không thể học được.
    pool: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []

    dropped_bare: list[tuple[str, str]] = []

    def add(text: str, label: str) -> None:
        key = _clean(text)
        if len(key) < 2:
            return
        if _is_unaccented(key, label):
            dropped_bare.append((label, key))
            return
        old = pool.get(key)
        if old is None:
            pool[key] = label
        elif old != label:
            conflicts.append((key, old, label))
            pool.pop(key, None)

    for label in targets:
        print(f"[{label}] xin {args.per_class} câu...", flush=True)
        try:
            rows = _ask(_prompt_for(label, LABELS[label], args.per_class), args.per_class, args.model)
        except Exception as exc:  # noqa: BLE001 - báo rồi đi tiếp, đừng mất cả mẻ
            print(f"  LỖI: {exc}", file=sys.stderr)
            continue
        before = len(pool)
        for r in rows:
            add(r, label)
        print(f"  nhận {len(rows)}, giữ {len(pool) - before}", flush=True)

    if not args.skip_boundaries and not args.only:
        for a, b, note in BOUNDARIES:
            print(f"[ranh giới] {a} <-> {b}...", flush=True)
            try:
                rows = _ask(_boundary_prompt(a, b, note, args.per_boundary), args.per_boundary, args.model)
            except Exception as exc:  # noqa: BLE001
                print(f"  LỖI: {exc}", file=sys.stderr)
                continue
            kept = 0
            for r in rows:
                if "\t" not in r:
                    continue
                lab, _, text = r.partition("\t")
                lab = lab.strip()
                if lab in (a, b):
                    before = len(pool)
                    add(text, lab)
                    kept += len(pool) - before
            print(f"  nhận {len(rows)}, giữ {kept}", flush=True)

    if dropped_bare:
        n_by = Counter(lab for lab, _ in dropped_bare)
        print(f"\nBỏ {len(dropped_bare)} câu bị viết tuột dấu: "
              f"{', '.join(f'{k}={v}' for k, v in n_by.most_common())}")

    if conflicts:
        print(f"\nBỏ {len(conflicts)} câu bị gán 2 nhãn khác nhau:")
        for text, a, b in conflicts[:10]:
            print(f"  {a} vs {b}: {text}")

    rows = sorted(pool.items())
    rng = random.Random(args.seed)
    rng.shuffle(rows)

    # Chia phân tầng: mỗi nhãn phải có mặt ở cả train lẫn eval, nếu không thì
    # điểm eval không nói được gì về nhãn bị thiếu.
    by_label: dict[str, list[str]] = {}
    for text, label in rows:
        by_label.setdefault(label, []).append(text)

    train, evalset = [], []
    for label, texts in sorted(by_label.items()):
        cut = max(1, round(len(texts) * args.eval_frac))
        evalset += [{"text": t, "label": label} for t in texts[:cut]]
        train += [{"text": t, "label": label} for t in texts[cut:]]
    rng.shuffle(train)
    rng.shuffle(evalset)

    for name, data in (("train", train), ("eval", evalset)):
        p = OUT_DIR / f"{name}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for row in data:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"-> {p}  ({len(data)} câu)")

    print("\nSố câu mỗi nhãn (train + eval):")
    for label in sorted(by_label):
        n = len(by_label[label])
        flag = "  <-- ÍT" if n < 20 else ""
        print(f"  {label:16s} {n:4d}{flag}")
    print(f"\nTổng {len(rows)} câu / {len(by_label)} nhãn")
    print("\nSOÁT LẠI BẰNG MẮT trước khi huấn luyện — model sinh ra không phải "
          "lúc nào cũng đúng nhãn nó được giao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
