"""Clef (`@cf/cloudflare/clef-flash`): intent cuối + `ocr_mode` + `needs_web` trong MỘT lượt.

Clef trả xác suất cho tối đa 64 câu hỏi trong cùng một request và không sinh
token nào, nên hỏi thêm `ocr_mode`/`needs_web` không tốn thêm độ trễ — gộp vào
đây thay vì gọi Gemma thêm một lượt để hỏi "có cần tra mạng không".

Schema: `data/clef/*.schema.json`, cách gọi: `docs/LLM_PROVIDER.md`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import config
from models import net

logger = logging.getLogger("blind_assist")

# Nhãn của Final Router (§8). `alert_on`/`alert_off` là "bật/tắt cảnh báo" làn C.
LABELS: dict[str, str] = {
    "chat": "hỏi đáp, trò chuyện, hỏi giờ, thời tiết, tin tức, hỏi mình đang ở đâu, "
            "hỏi một nơi nào đó Ở ĐÂU/chỗ nào (chỉ hỏi vị trí, không nhờ dẫn), "
            "nói chuyện về việc gọi/nhắn cho ai đó mà không ra lệnh, hoặc câu không thuộc nhóm nào khác",
    "space": "hỏi phía trước/xung quanh CÓ GÌ, tả khung cảnh",
    "hazard": "hỏi/kiểm tra MỘT LẦN phía trước có AN TOÀN không, có vật cản/chướng ngại vật không "
              "(không phải bật chế độ cảnh báo liên tục)",
    "ocr": "đọc chữ, đọc sách/giấy tờ/nhãn, tóm tắt nội dung văn bản, đọc lại nội dung vừa đọc",
    "money": "hỏi mệnh giá tờ tiền đang cầm",
    "find": "tìm một đồ vật cụ thể trong tầm tay",
    "nav_start": "nhờ dẫn đường / chỉ đường đi bộ tới một địa điểm CỤ THỂ (phải có điểm đến; "
                 "chỉ hỏi 'X ở đâu' thì là chat)",
    "nav_stop": "dừng chỉ đường",
    "alert_on": "bật chế độ cảnh báo vật cản liên tục khi đi đường (câu có 'bật'/'mở', không có điểm đến)",
    "alert_off": "tắt cảnh báo vật cản",
    "contact_call": "gọi điện cho một người trong danh bạ",
    "message_send": "nhắn tin / gửi lời nhắn cho người thân (ra lệnh nhắn ngay; kể chuyện đã nhắn thì là chat)",
    "message_read": "đọc / nghe tin nhắn mới, hỏi có ai nhắn gì không",
    "emergency_call": "gọi cấp cứu, khẩn cấp, SOS, cứu tôi",
    "ride_quote": "đặt xe, gọi Grab đi đâu đó",
    "ride_confirm": "xác nhận hoặc huỷ chuyến xe vừa báo giá",
    "music_play": "phát nhạc, mở bài hát, nghe nhạc",
    "music_stop": "tắt nhạc, dừng nhạc",
    "music_volume": "tăng/giảm/chỉnh âm lượng",
    "ask": "hỏi MỘT điều cụ thể về vật đang cầm hoặc thứ camera đang thấy: cái này là gì, màu gì, vị gì, "
           "hãng nào, hạn dùng ngày nào, trên đó ghi gì, màn hình đang báo gì "
           "(hỏi một vật NẰM Ở ĐÂU, hướng nào là find)",
}

_OCR_MODES = {
    "read": "đọc to nguyên văn chữ",
    "summarize": "tóm tắt nội dung văn bản",
    "reread": "đọc lại nội dung vừa đọc lần trước, không cần chụp mới",
    "raw": "đọc nguyên văn, giữ ngôn ngữ gốc, không dịch",
    "specialized": "đọc văn bản chuyên ngành (hợp đồng, toa thuốc, hướng dẫn sử dụng), giữ nguyên thuật ngữ",
}


@dataclass
class ClefResult:
    intent: str
    confidence: float
    ocr_mode: str = "read"
    needs_web: bool = False
    seconds: float = 0.0
    source: str = "clef"  # "gemma" | "clef"
    # False: không đo được xác suất nhãn (Gemma không trả logprobs). `confidence` khi đó chỉ để định tuyến
    # làn; cổng làn D (`final_router._trusted`) coi như CHƯA đủ tin cậy -> hỏi lại.
    confidence_known: bool = True


_client = net.LoopClient(
    lambda: net.async_client(connect_timeout=config.CLEF_TIMEOUT_S, timeout=5.0)
)
_ping_task: asyncio.Task | None = None


def available() -> bool:
    return bool(config.CLOUDFLARE_API_TOKEN and config.CLOUDFLARE_ACCOUNT_ID)


def _url() -> str:
    return (
        f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}"
        f"/ai/run/{config.CLEF_MODEL_ID}"
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}"}


def _get_client():
    return _client.get()


def _state(text: str, device: dict | None) -> dict:
    device = device or {}
    return {
        "câu_lệnh_của_người_khiếm_thị": text,
        "bối_cảnh_thiết_bị": {
            "đang_phát_nhạc": bool(device.get("music_playing")),
            "đang_chỉ_đường": bool(device.get("navigating")),
            "đang_bật_cảnh_báo_vật_cản": bool(device.get("alerting")),
            "chuyến_xe_chờ_xác_nhận": bool(device.get("ride_quote_pending")),
        },
    }


def _questions() -> dict:
    return {
        "intent": {
            "type": "choice",
            "instructions": (
                "Người khiếm thị đeo kính hỗ trợ vừa nói câu lệnh này. Họ muốn gì? "
                "Câu tắt/dừng nói trống không thì dựa vào bối cảnh thiết bị."
            ),
            "criteria": LABELS,
        },
        "ocr_mode": {
            "type": "choice",
            "instructions": "Nếu là yêu cầu về chữ/văn bản: muốn đọc, tóm tắt hay đọc lại?",
            "criteria": _OCR_MODES,
        },
        "needs_web": {
            "type": "noul",
            "instructions": (
                "Trả lời câu này có cần tra cứu thông tin MỚI trên mạng không "
                "(thời tiết, tin tức, giá cả, tỉ số, giờ mở cửa, sự kiện)?"
            ),
        },
    }


async def classify(text: str, device: dict | None = None) -> ClefResult | None:
    """Gọi Clef. `None` khi thiếu key, lỗi, hoặc quá `CLEF_TIMEOUT_S`."""
    if not available() or not text.strip():
        return None
    started = time.monotonic()
    payload = {"model": config.CLEF_MODEL, "state": _state(text, device), "questions": _questions()}
    try:
        resp = await asyncio.wait_for(
            _get_client().post(_url(), json=payload, headers=_headers()),
            timeout=config.CLEF_TIMEOUT_S,
        )
        resp.raise_for_status()
        answers = resp.json()["result"]["answers"]
        intent = answers["intent"]
        mode = answers.get("ocr_mode") or {}
        web = answers.get("needs_web") or {}
        result = ClefResult(
            intent=intent["choice"],
            confidence=float(intent.get("confidence", 0.0)),
            ocr_mode=mode.get("choice", "read"),
            needs_web=float(web.get("noul", 0.0)) >= 0.5,
            seconds=time.monotonic() - started,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - Clef lỗi thì router tự xử
        logger.warning("Clef lỗi sau %.2fs: %r", time.monotonic() - started, exc)
        return None
    if result.intent not in LABELS:
        return None
    logger.info(
        "Clef '%s' -> %s (conf=%.2f mode=%s web=%s) %.2fs",
        text, result.intent, result.confidence, result.ocr_mode, result.needs_web, result.seconds,
    )
    return result


async def _ping() -> None:
    await _get_client().get(
        "https://api.cloudflare.com/client/v4/user/tokens/verify", headers=_headers(),
    )


async def warm() -> None:
    """Bắt tay TLS trước và giữ kết nối nóng (lượt Clef đầu khỏi gánh ~0,2 s)."""
    global _ping_task
    if not available():
        logger.warning("Thiếu CLOUDFLARE_API_TOKEN/ACCOUNT_ID: intent chỉ còn luật từ khoá")
        return
    await classify("xin chào")
    if _ping_task is None:
        _ping_task = asyncio.get_running_loop().create_task(net.keep_warm("clef", _ping))


async def close() -> None:
    global _ping_task
    if _ping_task is not None:
        _ping_task.cancel()
        _ping_task = None
    await _client.aclose()
