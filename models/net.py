"""HTTP client dùng chung cho Clef/Gemma/Search: giữ kết nối nóng.

Mỗi lần bắt tay TLS mới tới Cloudflare/UIT tốn 100-300 ms, và httpx mặc định
đóng kết nối rảnh sau 5 s — tức gần như MỌI lượt bấm nút đều phải bắt tay lại.
Ở đây: giữ kết nối rảnh tới 5 phút, và một vòng nền gõ nhẹ mỗi 30 s để
proxy/CDN không cắt kết nối trước.
"""

import asyncio
import logging
import os
import ssl

import httpx

logger = logging.getLogger("blind_assist")

_KEEPALIVE_EXPIRY_S = 300.0
KEEPALIVE_PING_S = 30.0


def ssl_context(ca_bundle: str | None = None) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ca_bundle and os.path.exists(ca_bundle):
        ctx.load_verify_locations(ca_bundle)
    return ctx


def async_client(
    *, connect_timeout: float = 1.0, timeout: float = 30.0, ca_bundle: str | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        limits=httpx.Limits(
            max_connections=32, max_keepalive_connections=16,
            keepalive_expiry=_KEEPALIVE_EXPIRY_S,
        ),
        verify=ssl_context(ca_bundle),
    )


async def keep_warm(name: str, ping, interval: float = KEEPALIVE_PING_S) -> None:
    """Gọi `ping()` (coroutine) đều đặn cho tới khi task bị huỷ."""
    while True:
        await asyncio.sleep(interval)
        try:
            await ping()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("keep-warm %s lỗi: %s", name, exc)


class LoopClient:
    """Một `AsyncClient` cho mỗi event loop.

    Client httpx gắn với loop đã tạo ra nó; dùng lại trên loop khác (test, hay
    server khởi động lại loop) là lỗi "Event loop is closed". Đổi loop thì dựng
    client mới, còn trong một loop thì luôn dùng lại cùng một pool kết nối.
    """

    def __init__(self, factory) -> None:
        self._factory = factory
        self._loop = None
        self._client: httpx.AsyncClient | None = None

    def get(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is not loop:
            self._client, self._loop = self._factory(), loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._loop is asyncio.get_running_loop():
            await self._client.aclose()
        self._client = self._loop = None
