"""Bộ phân loại intent của voice server v2: Gemma UIT trước, Clef dự phòng.

Đo 2026-10-19 trên `data/intent/eval.jsonl` (358 câu), cùng bộ nhãn:
    Clef (Cloudflare)  đúng 82,4%  lỗi/timeout 7  p50 486 ms  p90 668 ms
    Gemma UIT          đúng 89,4%  lỗi/timeout 0  p50 161 ms  p90 191 ms
Clef chậm vì MẠNG: riêng một lượt tới api.cloudflare.com không chạy model đã
423 ms, còn Gemma UIT cách 15 ms.

Đo lại 2026-10-19 trên gold (concurrency 1), sau chỉnh prompt (Task 4): dev acc 0,894 -> 0,956,
p50 263 -> 265 ms, p90 269 -> 273 ms; test 0,888 -> 0,963, p50 264 -> 267 ms (docs/benchmarks/INTENT_GOLD.md).

Task 4d (2026-10-19): `config.INTENT_AUX=rules` bỏ lượt nhãn phụ, ocr_mode/needs_web bằng luật từ
khoá: chat/ocr p50 120 -> 60 ms, p90 chung 128 -> 81 ms (docs/benchmarks/INTENT_GOLD.md).

Confidence của đường Gemma = xác suất nhãn từ logprobs (UIT trả logprobs cả khi
dùng structured output, kiểm 2026-10-19), không còn hằng 1.0.

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
        "ocr_mode": {"type": "string", "enum": ["read", "summarize", "reread", "raw", "specialized"]},
        "needs_web": {"type": "boolean"},
    },
    "required": ["intent", "ocr_mode", "needs_web"],
}

_OCR_MODES = ("read", "summarize", "reread", "raw", "specialized")

# Đầu ra dạng nhãn (Task 4c): intent là MỘT lựa chọn trong LABELS (~4 token thay vì ~24 của JSON
# ba trường, decode ~8 ms/token). `ocr_mode` / `needs_web` chỉ có nghĩa với ocr / chat nên chỉ hỏi
# thêm một lượt nhãn ngắn khi đúng intent đó (hỏi gộp một lượt song song thì Gemma gần như không
# bao giờ trả "web": 0/10 so với 10/10 của JSON, đo 2026-10-19).
_WEB_TAIL = "Trường needs_web của câu này là true (web) hay false (no_web)? Trả web hoặc no_web."
_MODE_TAIL = "Trả ocr_mode (read/summarize/reread/raw/specialized)."

_PREFIX = (
    "Phân loại câu lệnh thoại của người khiếm thị đeo kính hỗ trợ vào ĐÚNG MỘT nhãn.\n"
    + "\n".join(f"{k}: {v}" for k, v in LABELS.items())
    + "\n\nThêm hai trường:\n"
    "ocr_mode: với yêu cầu về chữ — read (đọc), summarize (tóm tắt), reread (đọc lại "
    "nội dung vừa đọc), raw (đọc nguyên văn từng chữ, không chỉnh), specialized (giấy tờ "
    "chuyên ngành: đơn thuốc, hoá đơn, hợp đồng); câu khác để read.\n"
    "needs_web: true nếu trả lời cần tra thông tin MỚI (thời tiết, tin tức, giá cả, tỉ "
    "số, giờ mở cửa, sự kiện).\n"
    "Câu tắt/dừng nói trống không (\"tắt đi\", \"dừng lại\", \"tắt ngay\") thì dựa vào bối cảnh "
    "thiết bị: đang chỉ đường -> nav_stop, đang phát nhạc -> music_stop, đang cảnh báo -> alert_off.\n"
    "Ví dụ:\n"
    "\"Siêu thị gần nhất ở đâu\" -> chat (chỉ hỏi vị trí). \"Chỉ đường tới siêu thị\" -> nav_start.\n"
    "\"Quét xem phía trước có vật cản không\" -> hazard. \"Bật cảnh báo vật cản\" -> alert_on.\n"
    "\"Gọi nhanh cho bố\" -> contact_call. \"Tìm giúp cái thẻ xe\" -> find.\n"
    "\"Nhắn cho mẹ là tôi về muộn\" -> message_send. \"Mẹ có nhắn gì không\" -> message_read. "
    "\"Hôm qua tôi nhắn cho mẹ rồi\" -> chat.\n"
    "\"Kể nghe chuyện ma\" -> chat.\n"
)


_warned_no_logprobs = False


def _context(device: dict | None) -> str:
    d = device or {}

    def on(key: str) -> str:
        return "có" if d.get(key) else "không"

    # Câu tắt/dừng trống không: nói thẳng đích theo trạng thái (đo 2026-10-19: chỉ ghi "đang
    # chỉ đường=có" thì "Tắt ngay" vẫn bị đoán music_stop dù không có nhạc).
    stops = [
        label for key, label in (
            ("navigating", "nav_stop"), ("music_playing", "music_stop"), ("alerting", "alert_off"),
        ) if d.get(key)
    ]
    hint = f"Câu tắt/dừng trống không ở đây = {stops[0]}.\n" if len(stops) == 1 else ""
    return (
        f"\nBối cảnh thiết bị: đang phát nhạc={on('music_playing')}, đang chỉ đường="
        f"{on('navigating')}, đang bật cảnh báo vật cản={on('alerting')}, chuyến xe chờ "
        f"xác nhận={on('ride_quote_pending')}.\n{hint}"
    )


def available() -> bool:
    return bool(config.LLM_BASE_URLS) or clef.available()


def prefix_messages() -> list[dict]:
    """Phần đầu prompt, để prewarm prefix cache lúc khởi động."""
    return [llm.user_message(_PREFIX)]


async def _choice_reply(text: str, device: dict | None) -> dict:
    base = _PREFIX + _context(device) + f'Câu lệnh: "{text}"\n'
    intent, prob = await llm.generate_choice(base + "Trả nhãn.", list(LABELS))
    mode, web = "read", False
    if config.INTENT_AUX == "rules":
        # Bỏ lượt phụ khỏi đường chờ (Task 4d): ocr_mode / needs_web từ luật từ khoá.
        from pipeline import intent_early  # nhập muộn: intent_early nhập module này

        if intent == "ocr":
            rule = intent_early.keyword_rule(text)
            mode = rule[1] if rule is not None and rule[0] == "ocr" else "read"
        elif intent == "chat":
            web = intent_early.needs_web_rule(text)
    elif intent == "ocr":
        mode, _ = await llm.generate_choice(base + _MODE_TAIL, list(_OCR_MODES))
    elif intent == "chat":
        answer, _ = await llm.generate_choice(base + _WEB_TAIL, ["web", "no_web"])
        web = answer == "web"
    return {"intent": intent, "ocr_mode": mode, "needs_web": web, "_label_prob": prob}


async def _json_reply(text: str, device: dict | None, started: float) -> dict | None:
    prompt = _PREFIX + _context(device) + f'Câu lệnh: "{text}"\nTrả JSON.'
    try:
        return await asyncio.wait_for(
            llm.generate_json(prompt, _SCHEMA, max_tokens=40, logprobs=True),
            config.INTENT_LLM_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemma phân loại lỗi sau %.2fs: %r", time.monotonic() - started, exc)
        return None


async def _gemma(text: str, device: dict | None) -> ClefResult | None:
    started = time.monotonic()
    if config.INTENT_FORMAT == "choice":
        try:
            reply = await asyncio.wait_for(_choice_reply(text, device), config.INTENT_LLM_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except llm.LLMError as exc:  # server không hiểu structured_outputs -> JSON như cũ
            logger.warning("Gemma nhãn lỗi (%r), dùng JSON", exc)
            reply = await _json_reply(text, device, started)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemma phân loại lỗi sau %.2fs: %r", time.monotonic() - started, exc)
            return None
    else:
        reply = await _json_reply(text, device, started)
    if reply is None:
        return None
    intent = reply.get("intent")
    if intent not in LABELS:
        return None
    mode = reply.get("ocr_mode")
    prob = reply.get("_label_prob")
    global _warned_no_logprobs
    known = prob is not None
    if not known:
        # Fail closed cho làn D: không có xác suất nhãn thì KHÔNG được coi là chắc chắn. Định tuyến làn vẫn
        # dùng 1.0 (làn A/B/C chạy như thường), còn cổng làn D thấy `confidence_known=False` và hỏi lại.
        if not _warned_no_logprobs:
            _warned_no_logprobs = True
            logger.warning("Gemma không trả logprobs: lệnh làn D sẽ hỏi lại (không đo được độ tin cậy)")
        prob = 1.0
    result = ClefResult(
        intent=intent, confidence=prob, confidence_known=known,
        ocr_mode=mode if mode in _OCR_MODES else "read",
        needs_web=bool(reply.get("needs_web")), seconds=time.monotonic() - started,
        source="gemma",
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

