"""Nối text sinh bất đồng bộ (Gemma, httpx async) với TTS chạy trong thread.

`tts.synthesize_text_stream` đọc text trong thread nền của nó, còn Gemma stream
trên event loop. `sync_iter` cho thread đó kéo từng mảnh từ loop; `adpcm_stream`
làm chiều ngược lại cho WebSocket: TTS + nén ADPCM ở thread, khối ra loop.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Iterable, Iterator

from pipeline import device_ctx, tts

_DONE = object()


def sync_iter(agen: AsyncIterator[str], loop: asyncio.AbstractEventLoop) -> Iterator[str]:
    """Async generator -> iterator đồng bộ, dùng được từ thread KHÁC loop."""
    async def step():
        return await agen.__anext__()

    try:
        while True:
            try:
                item = asyncio.run_coroutine_threadsafe(step(), loop).result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        # Người đọc bỏ dở (kính ngắt kết nối): đóng luôn stream Gemma.
        if not loop.is_closed():
            asyncio.run_coroutine_threadsafe(agen.aclose(), loop)


async def adpcm_stream(text: Iterable[str]) -> AsyncIterator[bytes]:
    """Text (iterable đồng bộ) -> khối ADPCM 256 byte, TTS chạy ở thread."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def worker() -> None:
        try:
            for chunk in tts.encode_adpcm(tts.synthesize_text_stream(text)):
                if stop.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except BaseException as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    thread = device_ctx.run_in_thread(worker, name="ws-tts")
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()
