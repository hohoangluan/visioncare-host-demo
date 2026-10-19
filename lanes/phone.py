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
from collections.abc import Iterator

from pipeline import device_ctx
from handlers import music, navigation, phone, ride
from models import llm

logger = logging.getLogger("blind_assist")

HANDLERS = {
    "contact_call": phone.handle_contact,
    "emergency_call": phone.handle_emergency,
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
    "nav_start": "destination",
    "ride_quote": "destination",
    "music_play": "song",
}

ASK_CUE = {
    "contact_call": "ask_contact_name",
    "nav_start": "ask_destination",
    "ride_quote": "ask_ride_destination",
    "music_play": "ask_song",
}

_SLOT_DESC = {
    "contact_name": "tên người cần gọi, đúng như người dùng nói (vd. \"mẹ\", \"anh Nam\")",
    "destination": "tên/địa chỉ điểm đến, đúng như người dùng nói",
    "song": "tên bài hát và/hoặc ca sĩ, đúng như người dùng nói",
}

_EXTRACT_PROMPT = (
    "Trích tham số từ câu lệnh thoại tiếng Việt của người khiếm thị.\n"
    "Trường cần trích: {slot} = {desc}.\n"
    "Câu không nói ra thì để chuỗi rỗng, KHÔNG đoán.\n"
    "Câu lệnh: \"{text}\"\n"
    "Trả JSON."
)

# Cụm sau động từ — đường dự phòng khi Gemma hỏng.
_FALLBACK = {
    "contact_name": re.compile(r"gọi(?: điện)?(?: thoại)?(?: cho)?\s+(.+)", re.I),
    "destination": re.compile(r"(?:tới|đến|ra|vào|về|đi)\s+(.+)", re.I),
    "song": re.compile(r"(?:bài hát|bài|nhạc|nghe|phát|mở)\s+(.+)", re.I),
}
_TAIL = re.compile(r"\s+(?:giúp tôi|giùm tôi|cho tôi|với|nhé|nha|đi|ngay|luôn)\s*$", re.I)


def extraction_prefix() -> list[dict]:
    """Phần đầu prompt trích tham số, để prewarm prefix cache."""
    return [llm.user_message(_EXTRACT_PROMPT.split("{slot}")[0])]


def _clean(value: str) -> str:
    value = value.strip().strip(".,!?\"'")
    while True:
        trimmed = _TAIL.sub("", value)
        if trimmed == value:
            return value
        value = trimmed


def fallback_slot(slot: str, text: str) -> str:
    match = _FALLBACK[slot].search(text or "")
    return _clean(match.group(1)) if match else ""


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

    started = time.monotonic()
    schema = {"type": "object", "properties": {slot: {"type": "string"}}, "required": [slot]}
    try:
        reply = await llm.generate_json(
            _EXTRACT_PROMPT.format(slot=slot, desc=_SLOT_DESC[slot], text=text), schema,
        )
        value = _clean(str(reply.get(slot) or ""))
        source = "gemma"
    except llm.LLMError as exc:
        logger.warning("Gemma trích %s lỗi (%r), dùng luật", slot, exc)
        value, source = fallback_slot(slot, text), "luật"
    if value:
        params[slot] = value
    logger.info("làn D %s: %s=%r (%s, %.2fs)", intent, slot, value, source, time.monotonic() - started)
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


def run_background(intent: str, text: str, params: dict, deliver=None) -> threading.Thread:
    """Chạy action ở nền; mỗi câu kết quả đưa cho `deliver` (vd. đọc qua WS)."""

    def worker() -> None:
        try:
            for piece in speech(intent, text, params):
                if deliver is not None and piece.strip():
                    deliver(piece.strip())
        except Exception:  # noqa: BLE001
            logger.exception("làn D nền %s lỗi", intent)

    return device_ctx.run_in_thread(worker, name=f"lane-d-{intent}")
