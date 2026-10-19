"""Gemma 4 26B-A4B (vLLM, API tương thích OpenAI) — thay Gemini cho voice server v2.

Gọi thẳng bằng httpx thay vì SDK `openai`: cần kiểm soát hai thứ SDK giấu đi —
pool kết nối nóng (`models/net.py`) và việc chuyển đường LAN <-> UIT ngay khi một
đường chết, không chờ hết timeout mặc định 10 phút của SDK.

Thinking luôn tắt (`enable_thinking: False`): phần suy nghĩ nằm trong `content`
trước câu trả lời, tức là người dùng phải chờ nó sinh xong mới nghe được chữ đầu.
"""

import asyncio
import base64
import contextlib
import json
import logging
import math
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


# Đếm request Gemma đang bay (Task 16): bench tải cần biết đỉnh đồng thời và tổng mỗi lượt.
# `per_device` khoá theo `device_ctx.current` nên hai kính không lẫn số; đọc qua `stats()`.
_inflight = 0
_max_inflight = 0
_total = 0
_per_device: dict[str, int] = {}


@contextlib.contextmanager
def _track():
    global _inflight, _max_inflight, _total
    from pipeline import device_ctx

    _inflight += 1
    _total += 1
    _max_inflight = max(_max_inflight, _inflight)
    dev = device_ctx.current.get()
    _per_device[dev] = _per_device.get(dev, 0) + 1
    try:
        yield
    finally:
        _inflight -= 1


@contextlib.asynccontextmanager
async def _track_async():
    with _track():
        yield


def stats() -> dict:
    return {"inflight": _inflight, "max_inflight": _max_inflight, "total": _total,
            "per_device": dict(_per_device)}


def reset_stats() -> None:
    global _max_inflight, _total
    _max_inflight, _total = _inflight, 0
    _per_device.clear()


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
            async with _track_async(), _client.get().stream(
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


async def complete_raw(messages: list[dict], max_tokens: int | None = None, **extra) -> dict:
    """Như `complete` nhưng trả nguyên `choices[0]` (có `logprobs` nếu yêu cầu)."""
    body = _body(messages, max_tokens or config.LLM_MAX_TOKENS, False, **extra)
    last_exc: Exception | None = None
    for base in list(_order):
        try:
            with _track():
                resp = await _client.get().post(
                    f"{base}/chat/completions", json=body, headers=_headers(),
                )
            if resp.status_code >= 500 or resp.status_code == 429:
                raise LLMError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()["choices"][0]
        except asyncio.CancelledError:
            raise
        except (LLMError, httpx.HTTPError, KeyError, ValueError) as exc:
            last_exc = exc
            if isinstance(exc, (LLMError, *_RETRYABLE)):
                _demote(base)
    raise LLMError(f"Không gọi được Gemma: {last_exc!r}")


async def complete(messages: list[dict], max_tokens: int | None = None, **extra) -> str:
    choice = await complete_raw(messages, max_tokens, **extra)
    return choice["message"]["content"] or ""


def value_prob(choice: dict, key: str) -> float | None:
    """Xác suất của giá trị chuỗi trường `key` = tích exp(logprob) các token phủ lên
    đoạn giá trị đó (ghép theo offset ký tự, vì tokenizer cắt "music_play" thành
    "music" + "_" + "play"). `None` khi server không trả logprobs hoặc không dò
    được vị trí giá trị."""
    items = (choice.get("logprobs") or {}).get("content")
    if not items:
        return None
    content = choice["message"].get("content") or ""
    m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % re.escape(key), content)
    if not m or m.start(1) == m.end(1):
        return None
    lo, hi = m.span(1)
    pos, total, hit = 0, 0.0, False
    for it in items:
        end = pos + len(it.get("token", ""))
        if pos < hi and end > lo:
            lp = it.get("logprob")
            if lp is None:
                return None
            total += lp
            hit = True
        pos = end
    return math.exp(total) if hit else None


def prefix_prob(choice: dict, upto: int) -> float | None:
    """Xác suất của `upto` ký tự đầu của câu trả lời = tích exp(logprob) các token phủ lên
    đoạn đó (token nằm vắt qua ranh giới được tính). Dùng cho nhãn ghép "intent/mode":
    độ tin cậy của intent không bị chia nhỏ bởi phần mode đứng sau."""
    items = (choice.get("logprobs") or {}).get("content")
    if not items or upto <= 0:
        return None
    pos, total, hit = 0, 0.0, False
    for it in items:
        if pos >= upto:
            break
        lp = it.get("logprob")
        if lp is None:
            return None
        total += lp
        hit = True
        pos += len(it.get("token", ""))
    return math.exp(total) if hit else None


async def generate_choice(prompt: str, choices: list[str], max_tokens: int = 8, sep: str = "/") -> tuple[str, float | None]:
    """Chọn MỘT chuỗi trong `choices` bằng `structured_outputs: {choice}` của vLLM.

    Trả (chuỗi, xác suất phần trước `sep` đầu tiên — tức nhãn chính, hoặc None khi không có
    logprobs). Đo 2026-10-19 trên llm.uit.edu.vn: chỉ khoá `structured_outputs` MỚI ép đúng tập
    chọn; `guided_choice` và `extra_body` bị server lờ đi (trả "Hello!" cho tập {alpha,beta}).
    Sinh ~4 token thay vì ~24 của JSON ba trường, nên nhanh hơn nhiều (decode ~8 ms/token).
    """
    choice = await complete_raw(
        [user_message(prompt)], max_tokens=max_tokens, temperature=0.0,
        logprobs=True, top_logprobs=1, structured_outputs={"choice": choices},
    )
    text = (choice["message"].get("content") or "").strip()
    if text not in choices:
        raise LLMError(f"Gemma không trả đúng nhãn: {text[:80]!r}")
    return text, prefix_prob(choice, text.index(sep) if sep in text else len(text))


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


async def generate_json(
    prompt: str, schema: dict, max_tokens: int = 120, logprobs: bool = False,
) -> dict:
    """Trích JSON theo schema (structured output của vLLM).

    `logprobs=True`: thêm khoá `_label_prob` = xác suất giá trị trường `intent`
    (hoặc None). Kiểm 2026-10-19: llm.uit.edu.vn TRẢ `logprobs.content[]` kèm
    structured output (json_schema) khi gửi `logprobs: true, top_logprobs: 1`.
    """
    extra = {"logprobs": True, "top_logprobs": 1} if logprobs else {}
    choice = await complete_raw(
        [user_message(prompt)], max_tokens=max_tokens, temperature=0.0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "params", "schema": schema},
        }, **extra,
    )
    text = choice["message"].get("content") or ""
    match = _JSON_BLOCK.search(text)
    if not match:
        raise LLMError(f"Gemma không trả JSON: {text[:200]!r}")
    try:
        out = json.loads(match.group(0))
    except ValueError as exc:
        raise LLMError(f"JSON hỏng: {text[:200]!r}") from exc
    if logprobs:
        out["_label_prob"] = value_prob(choice, "intent")
    return out


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
