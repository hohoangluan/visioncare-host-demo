"""Bộ đếm request Gemma (Task 16): đỉnh đồng thời đúng, khoá theo kính, trả về 0 khi xong."""

import asyncio

import httpx

from models.llm import client
from pipeline import device_ctx


class _Fake:
    def __init__(self, gate: asyncio.Event) -> None:
        self._c = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))
        self._gate = gate

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        await self._gate.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    def get(self):
        return self._c


def test_inflight_peak_and_per_device(monkeypatch):
    async def main():
        gate = asyncio.Event()
        monkeypatch.setattr(client, "_client", _Fake(gate))
        client.reset_stats()

        async def call(dev: str):
            with device_ctx.use(dev):
                return await client.complete([client.user_message("hi")])

        tasks = [asyncio.create_task(call(d)) for d in ("a", "a", "b")]
        await asyncio.sleep(0.05)
        assert client.stats()["inflight"] == 3
        gate.set()
        assert await asyncio.gather(*tasks) == ["ok"] * 3
        return client.stats()

    s = asyncio.run(main())
    assert s["inflight"] == 0 and s["max_inflight"] == 3 and s["total"] == 3
    assert s["per_device"] == {"a": 2, "b": 1}


def test_inflight_released_on_error(monkeypatch):
    async def boom(request):
        return httpx.Response(500)

    async def main():
        monkeypatch.setattr(client, "_client", type("F", (), {"get": lambda self: httpx.AsyncClient(
            transport=httpx.MockTransport(boom))})())
        client.reset_stats()
        try:
            await client.complete([client.user_message("hi")])
        except client.LLMError:
            pass

    asyncio.run(main())
    assert client.stats()["inflight"] == 0


def test_pending_action_runs_in_its_device_context():
    """Timer chạy ở thread mới: lệnh chờ phải thấy đúng kính đã đặt lệnh, không phải kính mặc định."""
    import threading

    from pipeline import pending_action

    seen, done = [], threading.Event()
    pending_action.schedule("kinh-B", 0.0, lambda: (seen.append(device_ctx.current.get()), done.set()), "t")
    assert done.wait(2) and seen == ["kinh-B"]
