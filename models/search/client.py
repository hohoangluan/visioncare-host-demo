"""SerpAPI (Google) cho làn A (§9): trần `SEARCH_TIMEOUT_S`, top 5. Lỗi/quá hạn -> `None`.

Thay Google Programmable Search (2026-10-19): SerpAPI trả cả `answer_box`
(thời tiết, tỉ số, tỷ giá) và `knowledge_graph`; hai khối này đứng đầu danh sách
vì chính là câu trả lời, còn `organic_results` chỉ là nguồn phụ.
"""

import asyncio
import logging
import time

import config
from models import net

logger = logging.getLogger("blind_assist")
# httpx ghi URL đầy đủ (kèm `api_key`) ở INFO: luôn giữ WARNING, dù ai cấu hình root logger.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

_URL = "https://serpapi.com/search.json"
_client = net.LoopClient(lambda: net.async_client(connect_timeout=1.0, timeout=config.SEARCH_TIMEOUT_S))


def available() -> bool:
    return bool(config.SERPAPI_API_KEY)


def _answer_box(box: dict) -> dict | None:
    """Thời tiết/tỉ số/tỷ giá có field riêng; còn lại lấy `answer`/`snippet`."""
    title = box.get("title") or box.get("type") or "Kết quả nhanh"
    if box.get("type") == "weather_result":
        parts = [f"{box.get('location', '')}".strip(), f"{box.get('temperature', '')}°{box.get('unit', 'C')}",
                 box.get("weather", ""), f"mưa {box['precipitation']}" if box.get("precipitation") else "",
                 f"độ ẩm {box['humidity']}" if box.get("humidity") else ""]
        return {"title": "Thời tiết", "snippet": ", ".join(p for p in parts if p)}
    snippet = box.get("answer") or box.get("result") or box.get("snippet") or box.get("contents", {}).get("table")
    if not snippet:
        return None
    return {"title": str(title), "snippet": str(snippet)}


def _knowledge_graph(kg: dict) -> dict | None:
    snippet = kg.get("description")
    if not snippet:
        return None
    return {"title": kg.get("title", ""), "snippet": snippet}


def parse(data: dict, num: int = 5) -> list[dict]:
    rows: list[dict] = []
    for key, fn in (("answer_box", _answer_box), ("knowledge_graph", _knowledge_graph)):
        row = fn(data[key]) if isinstance(data.get(key), dict) else None
        if row:
            rows.append(row)
    for item in data.get("organic_results", []):
        rows.append({"title": item.get("title", ""), "snippet": item.get("snippet", "")})
    return rows[:num]


async def search(query: str, num: int = 5) -> list[dict] | None:
    if not available():
        return None
    started = time.monotonic()
    params = {
        "engine": "google", "q": query, "hl": "vi", "gl": "vn", "google_domain": "google.com.vn",
        "num": num, "api_key": config.SERPAPI_API_KEY,
    }
    try:
        resp = await asyncio.wait_for(_client.get().get(_URL, params=params), config.SEARCH_TIMEOUT_S)
        resp.raise_for_status()
        rows = parse(resp.json(), num)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001  (không in params: có khoá)
        logger.warning("web_search lỗi sau %.2fs: %s", time.monotonic() - started, type(exc).__name__)
        return None
    logger.info("web_search '%s': %d kết quả, %.2fs", query, len(rows), time.monotonic() - started)
    return rows
