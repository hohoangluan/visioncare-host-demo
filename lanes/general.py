"""Làn A — General AI (§9): Gemma (+ ảnh buffer, + web_search khi cần) -> TTS.

Thứ tự message cố định để prefix cache của vLLM ăn được: system đứng đầu, ảnh
đứng trước chữ. Lượt prewarm (`prefix_messages`) gửi đúng phần đầu đó với
`max_tokens=1`, nên lượt thật chỉ còn phải prefill phần câu lệnh.
"""

import logging
import re
import time
from collections.abc import AsyncIterator

import config
from handlers import chat, describe_hazard, describe_space, find_object, read_money
from models import llm

logger = logging.getLogger("blind_assist")

VISION_INTENTS = frozenset({"space", "hazard", "find", "money"})

_VISION_SYSTEM = (
    "Bạn hỗ trợ người khiếm thị qua camera gắn trên kính. Câu trả lời sẽ được "
    "ĐỌC THÀNH TIẾNG: thuần văn nói tiếng Việt, không markdown, không dấu sao, "
    "không emoji. Câu đầu tiên thật ngắn và vào thẳng trọng tâm."
)

_SEARCH_BLOCK = (
    "Kết quả tra cứu Google vừa lấy (chỉ dùng những gì có ở đây cho thông tin "
    "thay đổi theo ngày; không có thì nói thẳng là chưa tra được):\n{results}\n\n"
)


def _vision_task(intent: str, text: str) -> str:
    if intent == "space":
        return describe_space._PROMPT
    if intent == "hazard":
        return describe_hazard._PROMPT
    if intent == "money":
        return read_money._PROMPT
    return find_object._PROMPT.format(command_text=text)


def _chat_system() -> str:
    return chat._SYSTEM_PROMPT.format(
        now=chat._now_text(), search="", location=chat._location_text(),
    )


def _history() -> list[dict]:
    messages = []
    for user, reply in chat._recent_turns():
        messages += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
    return messages


def prefix_messages(intent: str, image: bytes | None) -> list[dict]:
    """Phần đầu prompt dùng chung giữa prewarm và lượt thật."""
    if intent in VISION_INTENTS and image is not None:
        return [{"role": "system", "content": _VISION_SYSTEM}, llm.user_message("", image)]
    return [{"role": "system", "content": _chat_system()}, *_history()]


def messages(intent: str, text: str, image: bytes | None = None,
             search: list[dict] | None = None) -> list[dict]:
    if intent in VISION_INTENTS and image is not None:
        return [
            {"role": "system", "content": _VISION_SYSTEM},
            llm.user_message(f'{_vision_task(intent, text)}\n\nNgười dùng nói: "{text}"', image),
        ]
    user = text
    if search is not None:
        results = "\n".join(f"- {r['title']}: {r['snippet']}" for r in search) or "(không có kết quả)"
        user = _SEARCH_BLOCK.format(results=results) + f'Người dùng hỏi: "{text}"'
    return [{"role": "system", "content": _chat_system()}, *_history(), {"role": "user", "content": user}]


_MARKUP = re.compile(r"[*#`_]+")
_CUT = re.compile(r"[.,;:!?…](?=\s)")


def _first_cut(text: str, max_words: int) -> int | None:
    """Vị trí cắt câu TTS đầu: dấu câu đầu tiên sau >= 2 từ, hoặc hết `max_words` từ."""
    for match in _CUT.finditer(text):
        if len(text[:match.start()].split()) >= 2:
            return match.end()
    words = list(re.finditer(r"\S+", text))
    # Từ thứ max_words chỉ chắc đã trọn khi đã có khoảng trắng theo sau nó.
    if len(words) > max_words:
        return words[max_words - 1].end()
    return None


async def short_first_sentence(chunks: AsyncIterator[str], max_words: int | None = None) -> AsyncIterator[str]:
    """Tách câu đầu (<= 8 từ) kèm "\\n" để TTS đọc ngay, phần sau đi nguyên."""
    max_words = max_words or config.FIRST_SENTENCE_MAX_WORDS
    buffer, first_done = "", False
    async for chunk in chunks:
        chunk = _MARKUP.sub("", chunk)
        if first_done:
            yield chunk
            continue
        buffer += chunk
        cut = _first_cut(buffer, max_words)
        if cut is not None:
            first_done = True
            yield buffer[:cut].strip() + "\n"
            rest = buffer[cut:].lstrip()
            if rest:
                yield rest
    if not first_done and buffer.strip():
        yield buffer.strip() + "\n"


async def answer(intent: str, text: str, image: bytes | None = None,
                 search: list[dict] | None = None) -> AsyncIterator[str]:
    started = time.monotonic()
    reply: list[str] = []
    stream = llm.stream_chat(messages(intent, text, image, search))
    async for piece in short_first_sentence(stream):
        reply.append(piece)
        yield piece
    full = "".join(reply).strip()
    logger.info("làn A %s xong %.2fs: %s", intent, time.monotonic() - started, full[:120])
    if intent == "chat" and full:
        chat._HISTORY.append((text, full, time.monotonic()))
