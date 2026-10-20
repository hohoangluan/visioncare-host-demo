"""Tin nhắn của người thân tới kính (Plan 2 C7): callback `POST /internal/messages` của AB + sổ "đã đọc".

AB đẩy tin tới qua callback (thử lại 1/2/5/10/30/60/300/900 s rồi bỏ) và giữ tin chưa đọc để VH lấy bù
(`GET messages/unread`) lúc kính vào phiên hoặc khi người dùng nói "đọc tin nhắn". Hai đường có thể gặp cùng một
tin, nên mọi nơi đọc tin cho kính đều qua `mark_spoken` — mỗi `message_id` chỉ được đọc một lần ở phía VH.

Hàng đợi (tin tới khi kính đang bận) nằm ở `DeviceSession`, không ở đây: nó gắn với vòng đời phiên.
Phiên chết thì hàng đợi mất, nhưng tin vẫn chưa đọc ở AB nên lần vào phiên sau được lấy lại.
"""

import collections
import logging
import threading


logger = logging.getLogger("blind_assist")

# Câu đọc tin (đúng nguyên văn spec): "{name} nhắn: {text}"
def speech(name: str, text: str) -> str:
    return f"{name or 'Người thân'} nhắn: {text}"


_SPOKEN_MAX = 512
_spoken: "collections.OrderedDict[str, None]" = collections.OrderedDict()
_lock = threading.Lock()

# Dedupe callback theo Idempotency-Key (AB gửi lại khi chưa thấy 2xx)
_seen: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
_SEEN_MAX = 512


def mark_spoken(message_id: str) -> bool:
    """True = lần đầu (được đọc); False = đã đọc rồi. Gọi NGAY trước khi đọc."""
    with _lock:
        if message_id in _spoken:
            return False
        _spoken[message_id] = None
        while len(_spoken) > _SPOKEN_MAX:
            _spoken.popitem(last=False)
        return True


def unmark_spoken(message_id: str) -> None:
    """Đọc bị huỷ giữa chừng (bấm nút/rớt phiên): trả tin về trạng thái chưa đọc để còn đọc lại."""
    with _lock:
        _spoken.pop(message_id, None)


def was_spoken(message_id: str) -> bool:
    with _lock:
        return message_id in _spoken


def reset() -> None:
    with _lock:
        _spoken.clear()
        _seen.clear()


async def handle_event(body: dict, idempotency_key: str = "") -> tuple[int, dict]:
    """`POST /internal/messages` (đã qua xác thực). Luôn 2xx nhanh: AB thử lại với mọi mã không phải 2xx và bỏ sau 8 lần.

    Kính không có phiên / chưa có token riêng -> không đọc, để chưa đọc ở AB (lấy bù lần vào phiên sau)."""
    from live import device_session

    message_id = str(body.get("message_id") or "")
    device = str(body.get("glasses_device_id") or "")
    key = idempotency_key or (f"message-{message_id}" if message_id else "")

    def ok(matched: bool) -> tuple[int, dict]:
        return 200, {"status": "ok", "data": {"message_id": message_id, "matched": matched}}

    if key and key in _seen:
        return 200, _seen[key]
    if body.get("event") != "message_received" or not message_id or not device:
        return 422, {"detail": "event=message_received, message_id, glasses_device_id bắt buộc"}
    text = str(body.get("text") or "").strip()
    session = device_session.session_for(device)
    if session is None or not session.per_device or not text:
        out = ok(False)
    else:
        session.enqueue_message(message_id, str(body.get("from_display_name") or ""), text)
        out = ok(True)
    if key:
        _seen[key] = out[1]
        while len(_seen) > _SEEN_MAX:
            _seen.popitem(last=False)
    return out
