"""Google Programmable Search cho làn A (§9): ≤ 3 s, top 5. Lỗi/quá hạn -> `None`."""

import asyncio
import logging
import time

import config
from models import net

logger = logging.getLogger("blind_assist")

_URL = "https://www.googleapis.com/customsearch/v1"
_client = net.LoopClient(lambda: net.async_client(connect_timeout=1.0, timeout=config.SEARCH_TIMEOUT_S))


def available() -> bool:
    return bool(config.GOOGLE_SEARCH_API_KEY and config.GOOGLE_SEARCH_CX)


async def search(query: str, num: int = 5) -> list[dict] | None:
    if not available():
        return None
    started = time.monotonic()
    params = {
        "key": config.GOOGLE_SEARCH_API_KEY, "cx": config.GOOGLE_SEARCH_CX,
        "q": query, "num": num, "hl": "vi", "gl": "vn",
    }
    try:
        resp = await asyncio.wait_for(_client.get().get(_URL, params=params), config.SEARCH_TIMEOUT_S)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search lỗi sau %.2fs: %r", time.monotonic() - started, exc)
        return None
    logger.info("web_search '%s': %d kết quả, %.2fs", query, len(items), time.monotonic() - started)
    return [
        {"title": i.get("title", ""), "snippet": i.get("snippet", ""), "link": i.get("link", "")}
        for i in items[:num]
    ]
