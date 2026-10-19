"""Bộ phân loại intent của voice server v2: Gemma UIT trước, Clef dự phòng.

Đo 2026-10-19 trên `data/intent/eval.jsonl` (358 câu), cùng bộ nhãn:
    Clef (Cloudflare)  đúng 82,4%  lỗi/timeout 7  p50 486 ms  p90 668 ms
    Gemma UIT          đúng 89,4%  lỗi/timeout 0  p50 161 ms  p90 191 ms
Clef chậm vì MẠNG: riêng một lượt tới api.cloudflare.com không chạy model đã
423 ms, còn Gemma UIT cách 15 ms.

Phần đầu prompt cố định (danh sách nhãn) để prefix cache của vLLM giữ sẵn; bối
cảnh thiết bị và câu lệnh đứng cuối.
"""

import asyncio
import logging
import time

import config
from models import clef, llm
from models.clef import LABELS, ClefResult

logger = logging.getLogger("blind_assist")

_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(LABELS)},
        "ocr_mode": {"type": "string", "enum": ["read", "summarize", "reread"]},
        "needs_web": {"type": "boolean"},
    },
    "required": ["intent", "ocr_mode", "needs_web"],
}

_PREFIX = (
    "Phân loại câu lệnh thoại của người khiếm thị đeo kính hỗ trợ vào ĐÚNG MỘT nhãn.\n"
    + "\n".join(f"{k}: {v}" for k, v in LABELS.items())
    + "\n\nThêm hai trường:\n"
    "ocr_mode: với yêu cầu về chữ — read (đọc), summarize (tóm tắt), reread (đọc lại "
    "nội dung vừa đọc); câu khác để read.\n"
    "needs_web: true nếu trả lời cần tra thông tin MỚI (thời tiết, tin tức, giá cả, tỉ "
    "số, giờ mở cửa, sự kiện).\n"
    "Câu tắt/dừng nói trống không (\"tắt đi\", \"dừng lại\") thì dựa vào bối cảnh thiết bị.\n"
)


def _context(device: dict | None) -> str:
    d = device or {}

    def on(key: str) -> str:
        return "có" if d.get(key) else "không"

    return (
        f"\nBối cảnh thiết bị: đang phát nhạc={on('music_playing')}, đang chỉ đường="
        f"{on('navigating')}, đang bật cảnh báo vật cản={on('alerting')}, chuyến xe chờ "
        f"xác nhận={on('ride_quote_pending')}.\n"
    )


def available() -> bool:
    return bool(config.LLM_BASE_URLS) or clef.available()


def prefix_messages() -> list[dict]:
    """Phần đầu prompt, để prewarm prefix cache lúc khởi động."""
    return [llm.user_message(_PREFIX)]


async def _gemma(text: str, device: dict | None) -> ClefResult | None:
    started = time.monotonic()
    prompt = _PREFIX + _context(device) + f'Câu lệnh: "{text}"\nTrả JSON.'
    try:
        reply = await asyncio.wait_for(
            llm.generate_json(prompt, _SCHEMA, max_tokens=40), config.INTENT_LLM_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemma phân loại lỗi sau %.2fs: %r", time.monotonic() - started, exc)
        return None
    intent = reply.get("intent")
    if intent not in LABELS:
        return None
    mode = reply.get("ocr_mode")
    result = ClefResult(
        intent=intent, confidence=1.0,
        ocr_mode=mode if mode in ("read", "summarize", "reread") else "read",
        needs_web=bool(reply.get("needs_web")), seconds=time.monotonic() - started,
    )
    logger.info(
        "Gemma intent '%s' -> %s (mode=%s web=%s) %.2fs",
        text, result.intent, result.ocr_mode, result.needs_web, result.seconds,
    )
    return result


async def classify(text: str, device: dict | None = None) -> ClefResult | None:
    """Gemma; lỗi/quá hạn thì Clef (nếu có key). `None` khi cả hai hỏng."""
    if not text.strip():
        return None
    if config.INTENT_BACKEND != "clef":
        result = await _gemma(text, device)
        if result is not None or config.INTENT_BACKEND == "gemma":
            return result
    return await clef.classify(text, device)
