"""Gemma 4 26B-A4B (vLLM, API tương thích OpenAI) — thay Gemini cho voice server v2.

Gọi thẳng bằng httpx thay vì SDK `openai`: cần kiểm soát hai thứ SDK giấu đi —
pool kết nối nóng (`models/net.py`) và việc chuyển đường LAN <-> UIT ngay khi một
đường chết, không chờ hết timeout mặc định 10 phút của SDK.

Thinking luôn tắt (`enable_thinking: False`): phần suy nghĩ nằm trong `content`
trước câu trả lời, tức là người dùng phải chờ nó sinh xong mới nghe được chữ đầu.
"""

import asyncio
import base64
import json
import logging
import re
import time
from collections.abc import AsyncIterator

import httpx

import config
from models import net

logger = logging.getLogger("blind_assist")


class LLMError(Exception):
    """Mọi đường tới Gemma đều hỏng, hoặc response không dùng được."""


_client = net.LoopClient(lambda: net.async_client(
    connect_timeout=config.LLM_CONNECT_TIMEOUT_S,
    timeout=config.LLM_TIMEOUT_S,
    ca_bundle=config.LLM_CA_BUNDLE,
))
# Thứ tự đường thử. `warm()` xếp lại theo độ trễ đo được; lỗi thì đẩy xuống cuối.
_order: list[str] = list(config.LLM_BASE_URLS)
_ping_task: asyncio.Task | None = None


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}


def image_part(jpeg: bytes) -> dict:
    data = base64.b64encode(jpeg).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}


def user_message(text: str, image: bytes | None = None) -> dict:
    if image is None:
        return {"role": "user", "content": text}
    # Ảnh trước chữ: phần đầu prompt (system + ảnh) giống hệt giữa lượt prewarm
    # và lượt thật, nên prefix cache của vLLM ăn được trọn phần ảnh.
    return {"role": "user", "content": [image_part(image), {"type": "text", "text": text}]}


def _body(messages: list[dict], max_tokens: int, stream: bool, **extra) -> dict:
    return {
        "model": config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": extra.pop("temperature", 0.3),
        "stream": stream,
        "chat_template_kwargs": {"enable_thinking": False},
        **extra,
    }


def _demote(base: str) -> None:
    if base in _order and len(_order) > 1:
        _order.remove(base)
        _order.append(base)
        logger.warning("Gemma %s lỗi, chuyển sang %s", base, _order[0])


_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.RemoteProtocolError)


async def stream_chat(
    messages: list[dict], max_tokens: int | None = None, **extra,
) -> AsyncIterator[str]:
    """Sinh text theo mảnh (SSE). Chuyển đường chỉ khi CHƯA nhận được mảnh nào."""
    body = _body(messages, max_tokens or config.LLM_MAX_TOKENS, True, **extra)
    last_exc: Exception | None = None
    for base in list(_order):
        started = time.monotonic()
        produced = False
        try:
            async with _client.get().stream(
                "POST", f"{base}/chat/completions", json=body, headers=_headers(),
            ) as resp:
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise LLMError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        if not produced:
                            logger.info("Gemma token đầu %.2fs (%s)", time.monotonic() - started, base)
                        produced = True
                        yield delta
            return
        except asyncio.CancelledError:
            raise
        except (LLMError, httpx.HTTPError) as exc:
            if produced:
                raise LLMError(f"Gemma đứt giữa chừng: {exc!r}") from exc
            last_exc = exc
            _demote(base)
    raise LLMError(f"Không gọi được Gemma: {last_exc!r}")


async def complete(messages: list[dict], max_tokens: int | None = None, **extra) -> str:
    body = _body(messages, max_tokens or config.LLM_MAX_TOKENS, False, **extra)
    last_exc: Exception | None = None
    for base in list(_order):
        try:
            resp = await _client.get().post(
                f"{base}/chat/completions", json=body, headers=_headers(),
            )
            if resp.status_code >= 500 or resp.status_code == 429:
                raise LLMError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
        except asyncio.CancelledError:
            raise
        except (LLMError, httpx.HTTPError, KeyError, ValueError) as exc:
            last_exc = exc
            if isinstance(exc, (LLMError, *_RETRYABLE)):
                _demote(base)
    raise LLMError(f"Không gọi được Gemma: {last_exc!r}")


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


async def generate_json(prompt: str, schema: dict, max_tokens: int = 120) -> dict:
    """Trích JSON theo schema (structured output của vLLM)."""
    text = await complete(
        [user_message(prompt)], max_tokens=max_tokens, temperature=0.0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "params", "schema": schema},
        },
    )
    match = _JSON_BLOCK.search(text)
    if not match:
        raise LLMError(f"Gemma không trả JSON: {text[:200]!r}")
    try:
        return json.loads(match.group(0))
    except ValueError as exc:
        raise LLMError(f"JSON hỏng: {text[:200]!r}") from exc


async def prewarm(messages: list[dict]) -> None:
    """Nạp prefix vào KV cache của vLLM (`max_tokens=1`), bỏ qua mọi lỗi."""
    try:
        await complete(messages, max_tokens=1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("prewarm Gemma lỗi: %r", exc)


async def _probe(base: str) -> float:
    started = time.monotonic()
    resp = await _client.get().get(f"{base}/models", headers=_headers(), timeout=2.0)
    resp.raise_for_status()
    return time.monotonic() - started


async def _ping() -> None:
    await _probe(_order[0])


async def warm() -> None:
    """Đo mọi đường, xếp đường nhanh nhất lên đầu, giữ kết nối nóng."""
    global _ping_task
    bases = list(_order)
    results = await asyncio.gather(*(_probe(b) for b in bases), return_exceptions=True)
    timed = sorted((r, b) for r, b in zip(results, bases) if isinstance(r, float))
    dead = [b for r, b in zip(results, bases) if not isinstance(r, float)]
    _order[:] = [b for _, b in timed] + dead
    for r, b in zip(results, bases):
        logger.info("Gemma %s: %s", b, f"{r * 1000:.0f} ms" if isinstance(r, float) else f"lỗi {r!r}")
    if not timed:
        logger.warning("Không đường nào tới Gemma sống")
        return
    await prewarm([user_message("ok")])
    if _ping_task is None:
        _ping_task = asyncio.get_running_loop().create_task(net.keep_warm("gemma", _ping))


async def close() -> None:
    global _ping_task
    if _ping_task is not None:
        _ping_task.cancel()
        _ping_task = None
    await _client.aclose()
