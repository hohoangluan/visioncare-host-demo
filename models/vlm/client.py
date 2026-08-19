import json
from collections.abc import Iterator

import config


class VLMError(Exception):
    """Lỗi khi gọi Gemini API hoặc response không dùng được."""


_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def warm() -> None:
    """Dựng client và bắt tay TLS trước cho cả VLM Vision và Intent models cùng lúc."""
    import concurrent.futures
    import logging

    log = logging.getLogger("blind_assist")
    dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x10\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"

    def _warm_vlm():
        try:
            from google.genai import types
            parts = ["ok", types.Part.from_bytes(data=dummy_jpeg, mime_type="image/jpeg")]
            stream = _get_client().models.generate_content_stream(
                model=config.GEMINI_MODEL, contents=parts
            )
            for _ in stream:
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Không warm được Gemini VLM: %s", exc)

    def _warm_intent():
        try:
            stream = _get_client().models.generate_content_stream(
                model=config.GEMINI_INTENT_MODEL, contents=["ok"]
            )
            for _ in stream:
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Không warm được Gemini Intent: %s", exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_warm_vlm)
        f2 = executor.submit(_warm_intent)
        concurrent.futures.wait([f1, f2], timeout=10.0)


def _guess_mime(image: bytes) -> str:
    if image[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _generation_config(search: bool = False):
    """Cấu hình cho một lần gọi Gemini.

    Thinking budget: chỉ đè khi `config.GEMINI_THINKING_BUDGET` >= 0. Mặc định
    (-1) để nguyên mặc định của model — đo thấy tắt thinking không nhanh hơn,
    nên đè bừa chỉ mất khả năng suy luận mà không đổi lấy giây nào. Xem số đo
    trong `config.py`.

    `search=True` bật Google Search grounding. Không có nó thì model chỉ biết
    tới thời điểm huấn luyện, và câu hỏi thời sự/thời tiết bị trả lời bằng thứ
    model tự bịa — đã gặp thật: hỏi "hôm nay trời thế nào" nhận được "trời đang
    có nắng nhẹ" cho một nơi model không hề biết.
    """
    override_thinking = config.GEMINI_THINKING_BUDGET >= 0
    if not search and not override_thinking:
        return None

    from google.genai import types

    kwargs = {}
    if override_thinking:
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=config.GEMINI_THINKING_BUDGET
        )
    if search:
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

    return types.GenerateContentConfig(**kwargs)


def _build_contents(prompt: str, image: bytes | None) -> list:
    contents: list = [prompt]
    if image is not None:
        from google.genai import types

        contents.append(types.Part.from_bytes(data=image, mime_type=_guess_mime(image)))
    return contents


def generate_stream(
    prompt: str, image: bytes | None = None, search: bool = False
) -> Iterator[str]:
    """Như `generate()` nhưng trả từng mảnh text ngay khi Gemini sinh ra.

    Đây là chỗ tiết kiệm giây nhiều nhất của cả pipeline: câu đầu tiên đi
    tổng hợp giọng nói trong lúc Gemini còn đang viết phần sau, thay vì đợi
    model viết xong cả đoạn.

    `search=True` cho model tra Google trước khi trả lời (thời tiết, tin tức).
    Đổi lại mảnh đầu tới chậm hơn vì phải chờ vòng tra cứu.
    """
    contents = _build_contents(prompt, image)
    got_text = False

    try:
        stream = _get_client().models.generate_content_stream(
            # Lượt có tra Google phải chạy trên model còn hạn mức grounding —
            # xem `config.GEMINI_SEARCH_MODEL`.
            model=config.GEMINI_SEARCH_MODEL if search else config.GEMINI_MODEL,
            contents=contents,
            config=_generation_config(search=search),
        )
        for part in stream:
            text = getattr(part, "text", None)
            if not text:
                continue  # Gemini chèn part rỗng; đẩy xuống TTS là gọi model vô ích
            got_text = True
            yield text
    except Exception as exc:  # noqa: BLE001 - propagate as VLMError, không nuốt lỗi
        raise VLMError(f"Gemini API lỗi: {exc}") from exc

    if not got_text:
        raise VLMError("Gemini trả về response rỗng")


def generate_json(
    prompt: str,
    image: bytes | None = None,
    schema: dict | None = None,
    model: str | None = None,
) -> dict:
    """Gọi Gemini và ép trả JSON đúng `schema`. Raise VLMError khi lỗi.

    Không streaming: dùng cho chỗ cần đọc trọn câu trả lời rồi mới quyết định
    (ví dụ kiểm bằng chứng trước khi đọc mệnh giá tiền), nên chẳng có gì để
    phát sớm. Schema ép model khai ra từng trường thay vì viết văn xuôi, để
    code kiểm được thay vì phải tin.

    `model` để gọi trên model khác mặc định. Bước phân loại ý định dùng model
    nhẹ hơn vì nó nằm nối tiếp trước cả handler — xem `config.GEMINI_INTENT_MODEL`.
    """
    from google.genai import types

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema
    )
    if config.GEMINI_THINKING_BUDGET >= 0:
        cfg.thinking_config = types.ThinkingConfig(
            thinking_budget=config.GEMINI_THINKING_BUDGET
        )

    try:
        response = _get_client().models.generate_content(
            model=model or config.GEMINI_MODEL,
            contents=_build_contents(prompt, image),
            config=cfg,
        )
    except Exception as exc:  # noqa: BLE001 - propagate as VLMError, không nuốt lỗi
        raise VLMError(f"Gemini API lỗi: {exc}") from exc

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise VLMError("Gemini trả về response rỗng")

    try:
        return json.loads(text)
    except ValueError as exc:
        raise VLMError(f"Gemini trả JSON không đọc được: {text[:200]}") from exc
