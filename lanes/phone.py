"""Làn D — Phone Action (§12): trích tham số -> `run_action` -> app server -> FCM.

Giữ nguyên `handlers/*` và `run_action()` (callback, câu kết quả). Làn này chỉ
lo phần đầu: lấy tham số NHANH NHẤT có thể.

- Tham số là bài phân loại (`ride_confirm` đồng ý/huỷ, `music_volume` hướng,
  số khẩn cấp) -> luật trên mặt chữ, 0 ms.
- Tham số là chuỗi tự do (`destination`, `contact_name`, `song`) -> Gemma
  `generate_json`. Lượt này được khởi chạy SONG SONG với Clef cuối khi đoán sớm
  ra làn D (`pipeline/turn.py`), nên thời gian của nó nằm dưới thời gian Clef.
  Gemma lỗi thì rơi về luật cắt cụm sau động từ.
"""

import logging
import re
import threading
import time
import unicodedata
from collections.abc import Iterator

from pipeline import device_ctx
from handlers import music, navigation, phone, ride
from models import llm

logger = logging.getLogger("blind_assist")

HANDLERS = {
    # Gọi điện / khẩn cấp đi qua AB + cầu âm thanh (Plan 2); bản cũ (gọi bằng trình gọi của điện thoại)
    # còn là `phone.handle_contact` / `phone.handle_emergency` (khẩn cấp rơi về đó khi kính chưa có phiên/token riêng).
    "contact_call": phone.handle_contact_call,
    "emergency_call": phone.handle_emergency_call,
    # Nhắn tin qua AB (Plan 2 C7): gửi sau đọc lại + cửa sổ huỷ; đọc tin chưa đọc là thao tác chỉ-đọc.
    "message_send": phone.handle_message_send,
    "message_read": phone.handle_message_read,
    "nav_start": navigation.handle_start,
    "nav_stop": navigation.handle_stop,
    "ride_quote": ride.handle_quote,
    "ride_confirm": ride.handle_confirm,
    "music_play": music.handle_play,
    "music_stop": music.handle_stop,
    "music_volume": music.handle_volume,
}

# intent -> slot chuỗi tự do cần Gemma trích.
SLOT = {
    "contact_call": "contact_name",
    "message_send": "contact_name",
    "nav_start": "destination",
    "ride_quote": "destination",
    "music_play": "song",
}

# Slot phụ phải có trước khi chạy (hỏi bằng câu riêng, xem `route`): lời nhắn của `message_send`.
EXTRA_SLOT = {"message_send": "text"}

ASK_CUE = {
    "contact_call": "ask_contact_name",
    "nav_start": "ask_destination",
    "ride_quote": "ask_ride_destination",
    "music_play": "ask_song",
}

# Câu hỏi slot không có clip cue (thêm cue = sinh clip + tăng CUE_VERSION); đọc qua TTS, đã dựng sẵn (STATIC_SPEECH).
ASK_TEXT = {"message_send": "Bạn muốn nhắn cho ai?"}

_SLOT_DESC = {
    "contact_name": "người cần gọi hoặc nhận tin nhắn, đúng như người dùng nói: tên hoặc từ chỉ quan hệ (vd. "
                    "\"mẹ\", \"anh Nam\", \"người thân\", \"bác sĩ\")",
    "destination": "tên/địa chỉ điểm đến, đúng như người dùng nói, kể cả khi chung chung "
                   "(vd. \"địa chỉ này\", \"nhà\")",
    "text": "nội dung lời nhắn muốn gửi, đúng như người dùng nói, KHÔNG gồm phần \"nhắn cho X\"; "
            "để chuỗi rỗng nếu chưa nói nội dung (vd. \"nhắn tin cho mẹ\")",
    "song": "tên bài hát, ca sĩ hoặc thể loại nhạc, đúng như người dùng nói (vd. \"nhạc trữ tình\")",
}

_EXTRACT_PROMPT = (
    "Trích tham số từ câu lệnh thoại tiếng Việt của người khiếm thị.\n"
    "Trường cần trích: {fields}.\n"
    "Chỉ để chuỗi rỗng khi câu hoàn toàn không nhắc tới; cụm chung chung vẫn trích nguyên văn, "
    "KHÔNG tự bịa thêm.\n"
    "Câu lệnh: \"{text}\"\n"
    "Trả JSON."
)

# Cụm sau động từ — đường dự phòng khi Gemma hỏng.
_FALLBACK = {
    "contact_name": re.compile(r"gọi(?: điện)?(?: thoại)?(?: cho)?\s+(.+)", re.I),
    "destination": re.compile(r"(?:tới|đến|ra|vào|về|đi)\s+(.+)", re.I),
    "song": re.compile(r"(?:bài hát|bài|nhạc|nghe|phát|mở)\s+(.+)", re.I),
}
# "nhắn cho mẹ là tôi về muộn" -> (mẹ, tôi về muộn). Tên = 1 từ, hoặc từ chỉ quan hệ + 1 từ nếu từ sau không phải từ nối.
_KINSHIP = {"mẹ", "bố", "ba", "má", "cha", "chị", "anh", "em", "cô", "chú", "bác", "dì", "cậu", "mợ", "ông", "bà", "con"}
_NAME_STOP = {"là", "rằng", "ơi", "nhé", "nha", "về", "đang", "sắp", "hôm", "ngày", "tôi", "mai", "nay", "đã", "đừng",
              "hãy", "nói", "bảo", "rồi", "ở", "có", "không", "đi", "cho", "với"}
_MESSAGE_HEAD = re.compile(
    r"^nhanh cho\s+(.+)|(?:nhắn|gửi)(?: tin(?: nhắn)?| lời nhắn)?(?: nhắn)?(?: giúp| giùm)?(?: lại)?(?: cho| với)?\s+(.+)", re.I,
)
_TEXT_LEAD = re.compile(r"^(?:là|rằng|nói|bảo|:|rằng là)\s+", re.I)
_TAIL = re.compile(r"\s+(?:giúp tôi|giùm tôi|cho tôi|với|nhé|nha|đi|ngay|luôn)\s*$", re.I)


def extraction_prefix() -> list[dict]:
    """Phần đầu prompt trích tham số, để prewarm prefix cache."""
    return [llm.user_message(_EXTRACT_PROMPT.split("{fields}")[0])]


def _clean(value: str) -> str:
    value = value.strip().strip(".,!?\"'")
    while True:
        trimmed = _TAIL.sub("", value)
        if trimmed == value:
            return value
        value = trimmed


def _clean_text(value: str) -> str:
    """Lời nhắn giữ nguyên "nhé/đi/với" cuối câu (khác tên/địa chỉ): chỉ bỏ khoảng trắng và ngoặc kép."""
    return " ".join(value.split()).strip("\"'")


def fallback_slot(slot: str, text: str) -> str:
    match = _FALLBACK[slot].search(text or "")
    return _clean(match.group(1)) if match else ""


def fallback_message(text: str) -> dict:
    """Đường dự phòng khi Gemma hỏng: tách người nhận + lời nhắn theo mặt chữ; không chắc thì để trống (-> hỏi lại)."""
    match = _MESSAGE_HEAD.search(text or "")
    if not match:
        return {}
    words = (match.group(1) or match.group(2) or "").split()
    if not words:
        return {}
    take = 1
    if words[0].lower() in _KINSHIP and len(words) > 1 and words[1].lower() not in _NAME_STOP:
        take = 2
    name = _clean(" ".join(words[:take]))
    body = _TEXT_LEAD.sub("", " ".join(words[take:])).strip()
    return {k: v for k, v in (("contact_name", name), ("text", _clean_text(body))) if v}


async def extract(intent: str, text: str) -> dict:
    """Tham số cho `intent` từ bản ghi cuối."""
    params: dict = {}
    lowered = text.lower()
    if intent == "ride_confirm":
        params["confirm"] = not re.search(r"(?<!\w)(huỷ|hủy|không|thôi)(?!\w)", lowered)
    elif intent == "music_volume":
        if number := re.search(r"\d+", lowered):
            params["volume"] = max(0, min(100, int(number.group(0))))
        elif re.search(r"tăng|to lên|lớn lên|vặn to", lowered):
            params["direction"] = "up"
        elif re.search(r"giảm|nhỏ lại|nhỏ đi|bé lại|vặn nhỏ", lowered):
            params["direction"] = "down"
    elif intent == "emergency_call":
        if number := re.search(r"\b(11[345]|\d{3,11})\b", lowered):
            params["emergency_number"] = number.group(1)

    slot = SLOT.get(intent)
    if slot is None:
        return params

    slots = [slot, *([EXTRA_SLOT[intent]] if intent in EXTRA_SLOT else [])]
    started = time.monotonic()
    schema = {"type": "object", "properties": {k: {"type": "string"} for k in slots}, "required": slots}
    try:
        fields = "; ".join(f"{k} = {_SLOT_DESC[k]}" for k in slots)
        reply = await llm.generate_json(_EXTRACT_PROMPT.format(fields=fields, text=text), schema)
        values = {k: (_clean_text if k == "text" else _clean)(str(reply.get(k) or "")) for k in slots}
        source = "gemma"
    except llm.LLMError as exc:
        logger.warning("Gemma trích %s lỗi (%r), dùng luật", slots, exc)
        if intent == "message_send":
            values = {k: fallback_message(text).get(k, "") for k in slots}
        else:
            values = {slot: fallback_slot(slot, text)}
        source = "luật"
    params.update({k: v for k, v in values.items() if v})
    # Lời nhắn là nội dung riêng tư: chỉ log tên người, không log `text`.
    logger.info("làn D %s: %s (%s, %.2fs)", intent, {k: v for k, v in values.items() if k != "text"} |
                ({"text": bool(values["text"])} if "text" in values else {}), source, time.monotonic() - started)
    return params


# ── pending slot: "Bạn muốn đi đâu?" -> lượt sau nói thẳng tên điểm đến ────────

_PENDING: dict[str, tuple[str, str, float]] = {}  # device -> (intent, slot, lúc hỏi)
_PENDING_LOCK = threading.Lock()
_PENDING_TTL_S = 60.0


def set_pending(device: str, intent: str) -> None:
    with _PENDING_LOCK:
        _PENDING[device] = (intent, SLOT[intent], time.monotonic())


def take_pending(device: str) -> tuple[str, str] | None:
    with _PENDING_LOCK:
        item = _PENDING.pop(device, None)
    if item is None or time.monotonic() - item[2] > _PENDING_TTL_S:
        return None
    return item[0], item[1]


def speech(intent: str, text: str, params: dict) -> Iterator[str]:
    """Chạy handler cũ (đồng bộ, gọi app server) — được đọc trong thread TTS."""
    return HANDLERS[intent](None, text, params=params)


def run_background(intent: str, text: str, params: dict, deliver=None, skip_ack: bool = False) -> threading.Thread:
    """Chạy action ở nền; mỗi câu kết quả đưa cho `deliver` (vd. đọc qua WS).

    `skip_ack`: bỏ câu xác nhận đầu của `run_action` ("Đang gọi cho mẹ.") vì làn D đã đọc lại lệnh trước khi
    chạy; chỉ đọc phần kết quả (hoặc lỗi). Câu xác nhận nhận ra qua dấu `\n` (`action_flow._utterance`).
    """

    def worker() -> None:
        try:
            first = True
            for piece in speech(intent, text, params):
                is_ack = first and piece.endswith("\n")
                first = False
                if is_ack and skip_ack:
                    continue
                if deliver is not None and piece.strip():
                    deliver(piece.strip())
        except Exception:  # noqa: BLE001
            logger.exception("làn D nền %s lỗi", intent)

    return device_ctx.run_in_thread(worker, name=f"lane-d-{intent}")


# ── cổng an toàn làn D: đọc lại + hỏi xác nhận ───────────────────────────────

# Hành động có tác dụng phụ thật: đọc lại cho nghe rồi chờ cửa sổ huỷ mới chạy.
CONFIRM_INTENTS = {"contact_call", "emergency_call", "message_send", "ride_quote", "ride_confirm", "music_play",
                   "nav_start"}


def readback(intent: str, params: dict) -> str:
    """Câu đọc lại cố định trước khi thi hành."""
    if intent == "contact_call":
        return f"Đang gọi cho {params.get('contact_name', '')}."
    if intent == "message_send":
        return f"Nhắn cho {params.get('contact_name', '')}: {params.get('text', '')}."
    if intent == "emergency_call":
        # Khẩn cấp = gọi người thân đã cài trong app, không phải 115.
        return "Đang gọi người thân khẩn cấp, bấm nút để huỷ."
    if intent == "ride_quote":
        return f"Đang tìm xe đi {params.get('destination', '')}."
    if intent == "ride_confirm":
        return "Đang xác nhận chuyến xe." if params.get("confirm", True) else "Đang huỷ chuyến xe."
    if intent == "music_play":
        song = params.get("song")
        return f"Đang mở {song}." if song else "Đang mở nhạc."
    if intent == "nav_start":
        return f"Đang gửi chỉ đường tới {params.get('destination', '')} về điện thoại."
    raise KeyError(intent)


def ask_confirm(intent: str, params: dict) -> str:
    if intent == "contact_call":
        return f"Gọi cho {params.get('contact_name', '')} phải không?"
    if intent == "message_send":
        return f"Nhắn cho {params.get('contact_name', '')} phải không?"
    if intent == "emergency_call":
        return "Gọi người thân khẩn cấp phải không?"
    if intent == "ride_quote":
        return f"Đặt xe đi {params.get('destination', '')} phải không?"
    if intent == "ride_confirm":
        return "Xác nhận chuyến xe phải không?"
    if intent == "music_play":
        song = params.get("song")
        return f"Mở {song} phải không?" if song else "Mở nhạc phải không?"
    if intent == "nav_start":
        return f"Chỉ đường tới {params.get('destination', '')} phải không?"
    raise KeyError(intent)


_CONFIRM: dict[str, tuple[str, dict, float]] = {}  # device -> (intent, params, lúc hỏi)
_CONFIRM_TTL_S = 30.0
_YES_WORDS = {"đúng", "phải", "ừ", "ừm", "có", "ok", "đồng ý", "gọi đi", "được", "vâng", "dạ"}
_NO_WORDS = {"không", "thôi", "huỷ", "hủy", "sai"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def _pure(text: str, words: set[str]) -> bool:
    """Cả câu là lời đáp ngắn (<= 3 từ), mọi từ nằm trong danh sách (hoặc cụm "đồng ý"/"gọi đi").

    "có gì trước mặt" KHÔNG phải xác nhận: chỉ khớp đầu câu là bẫy khi người dùng hỏi tiếp.
    """
    norm = _norm(text)
    if not norm or len(norm.split()) > 3:
        return False
    rest = norm
    for phrase in sorted((w for w in words if " " in w), key=len, reverse=True):
        rest = rest.replace(phrase, " ")
    return all(w in words for w in rest.split())


def is_yes(text: str) -> bool:
    return _pure(text, _YES_WORDS)


def is_no(text: str) -> bool:
    return _pure(text, _NO_WORDS)


def set_pending_confirm(device: str, intent: str, params: dict) -> None:
    with _PENDING_LOCK:
        _CONFIRM[device] = (intent, params, time.monotonic())


def pending_question(device: str) -> str | None:
    """Câu đang chờ lượt sau trả lời ("Bạn muốn đi đâu?" / "... phải không?"), KHÔNG lấy ra. Chỉ để hiện debug."""
    from pipeline import cues  # nhập muộn cho gọn phụ thuộc; chỉ dùng cho khung debug

    now = time.monotonic()
    with _PENDING_LOCK:
        confirm, pending = _CONFIRM.get(device), _PENDING.get(device)
    if confirm is not None and now - confirm[2] <= _CONFIRM_TTL_S:
        try:
            return ask_confirm(confirm[0], confirm[1])
        except KeyError:
            return None
    if pending is not None and now - pending[2] <= _PENDING_TTL_S:
        return ASK_TEXT.get(pending[0]) or cues.fallback_text(ASK_CUE.get(pending[0], ""))
    with _PENDING_LOCK:
        body = _BODY.get(device)
    if body is not None and now - body[1] <= _BODY_TTL_S:
        return body_question(body[0])
    return None


def take_pending_confirm(device: str) -> tuple[str, dict] | None:
    with _PENDING_LOCK:
        item = _CONFIRM.pop(device, None)
    if item is None or time.monotonic() - item[2] > _CONFIRM_TTL_S:
        return None
    return item[0], item[1]


# ── gọi điện: hỏi lại người thân trùng tên / mời nhắn tin khi không nghe máy ─────────────────

_CHOICE: dict[str, tuple[str, list[str], float, dict]] = {}  # device -> (intent, candidates, lúc hỏi, tham số giữ lại)
_CHOICE_TTL_S = 30.0
_OFFER: dict[str, tuple[str, dict, float]] = {}  # device -> (intent, params, lúc đề nghị)
_OFFER_TTL_S = 60.0


def _fold(text: str) -> str:
    """Chữ thường, bỏ dấu và dấu câu: "Mẹ Lan" == "me lan" (STT hay rơi dấu)."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def set_pending_choice(device: str, intent: str, candidates: list[str], keep: dict | None = None) -> None:
    """`keep`: tham số đã có ngoài slot tên (vd. `text` của message_send) để lượt chọn người không làm mất lời nhắn."""
    with _PENDING_LOCK:
        _CHOICE[device] = (intent, list(candidates), time.monotonic(), dict(keep or {}))


def take_pending_choice_full(device: str) -> tuple[str, list[str], dict] | None:
    with _PENDING_LOCK:
        item = _CHOICE.pop(device, None)
    if item is None or time.monotonic() - item[2] > _CHOICE_TTL_S:
        return None
    return item[0], item[1], item[3]


def take_pending_choice(device: str) -> tuple[str, list[str]] | None:
    item = take_pending_choice_full(device)
    return None if item is None else (item[0], item[1])


def match_choice(candidates: list[str], text: str) -> str | None:
    """Câu trả lời "Bạn muốn gọi ai: A hay B?" -> đúng MỘT người trong `candidates`, không thì None (không gọi bừa)."""
    said = _fold(text)
    if len(said) < 2:
        return None
    hits = [c for c in candidates if _fold(c) and (_fold(c) in said or said in _fold(c))]
    return hits[0] if len(hits) == 1 else None


def set_pending_offer(device: str, intent: str, params: dict) -> None:
    with _PENDING_LOCK:
        _OFFER[device] = (intent, params, time.monotonic())


def take_pending_offer(device: str) -> tuple[str, dict] | None:
    with _PENDING_LOCK:
        item = _OFFER.pop(device, None)
    if item is None or time.monotonic() - item[2] > _OFFER_TTL_S:
        return None
    return item[0], item[1]


# ── nhắn tin: hỏi lời nhắn còn thiếu ("Bạn muốn nhắn gì cho mẹ?") ───────────────────────────

_BODY: dict[str, tuple[str, float]] = {}  # device -> (người nhận, lúc hỏi)
_BODY_TTL_S = 60.0


def body_question(name: str) -> str:
    return f"Bạn muốn nhắn gì cho {name}?"


def set_pending_body(device: str, contact_name: str) -> None:
    with _PENDING_LOCK:
        _BODY[device] = (contact_name, time.monotonic())


def take_pending_body(device: str) -> str | None:
    with _PENDING_LOCK:
        item = _BODY.pop(device, None)
    if item is None or time.monotonic() - item[1] > _BODY_TTL_S:
        return None
    return item[0]
