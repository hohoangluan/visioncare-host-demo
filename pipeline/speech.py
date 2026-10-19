"""Nối text sinh bất đồng bộ (Gemma, httpx async) với TTS chạy trong thread.

`tts.synthesize_text_stream` đọc text trong thread nền của nó, còn Gemma stream
trên event loop. `sync_iter` cho thread đó kéo từng mảnh từ loop; `adpcm_stream`
làm chiều ngược lại cho WebSocket: TTS + nén ADPCM ở thread, khối ra loop.
"""

import asyncio
import concurrent.futures
import threading
from collections.abc import AsyncIterator, Iterable, Iterator

from pipeline import device_ctx, tts

_DONE = object()


class SyncIter:
    """Async generator -> iterator đồng bộ, dùng được từ thread KHÁC loop.

    Có thêm `abort()` (gọi từ bất kỳ thread nào): kính ngắt kết nối khi Gemma đang
    nghĩ giữa chừng thì thread TTS đang chặn trong `.result()` chờ mảnh text kế —
    không ai đóng generator được cho tới khi mảnh đó tới. `abort` huỷ luôn bước
    `__anext__` đang bay (=> `llm.stream_chat` nhận CancelledError, httpx đóng
    stream) và làm iterator kết thúc êm, nên TTS dừng ngay thay vì chờ Gemma.
    """

    def __init__(self, agen: AsyncIterator[str], loop: asyncio.AbstractEventLoop) -> None:
        self._agen = agen
        self._loop = loop
        self._task: asyncio.Task | None = None
        self._aborted = threading.Event()
        self._finished = False

    def __iter__(self) -> "SyncIter":
        return self

    async def _step(self) -> str:
        self._task = asyncio.current_task()
        try:
            return await self._agen.__anext__()
        finally:
            self._task = None

    def __next__(self) -> str:
        if self._aborted.is_set() or self._finished:
            raise StopIteration
        try:
            return asyncio.run_coroutine_threadsafe(self._step(), self._loop).result()
        except StopAsyncIteration:
            self._finished = True
            raise StopIteration from None
        except concurrent.futures.CancelledError:
            # Bước bị `abort` huỷ giữa chừng.
            self._finished = True
            raise StopIteration from None

    async def _shutdown(self, cancel_step: bool) -> None:
        task = self._task
        if cancel_step and task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await self._agen.aclose()
        except RuntimeError:  # đang chạy dở trên task khác: task kia sẽ tự đóng
            pass

    def _schedule_shutdown(self, cancel_step: bool) -> None:
        if not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._shutdown(cancel_step), self._loop)

    def abort(self) -> None:
        if not self._aborted.is_set():
            self._aborted.set()
            self._schedule_shutdown(cancel_step=True)

    def close(self) -> None:
        # Người đọc bỏ dở (kính ngắt kết nối): đóng luôn stream Gemma.
        if not self._aborted.is_set():
            self._aborted.set()
            self._schedule_shutdown(cancel_step=False)


def sync_iter(agen: AsyncIterator[str], loop: asyncio.AbstractEventLoop) -> SyncIter:
    return SyncIter(agen, loop)


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
