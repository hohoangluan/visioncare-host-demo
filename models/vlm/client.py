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


def _guess_mime(image: bytes) -> str:
    if image[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def generate(prompt: str, image: bytes | None = None) -> str:
    """Gọi Gemini với prompt text, kèm ảnh nếu có. Raise VLMError khi lỗi."""
    contents: list = [prompt]
    if image is not None:
        from google.genai import types

        contents.append(types.Part.from_bytes(data=image, mime_type=_guess_mime(image)))

    try:
        response = _get_client().models.generate_content(
            model=config.GEMINI_MODEL, contents=contents
        )
    except Exception as exc:  # noqa: BLE001 - propagate as VLMError, không nuốt lỗi
        raise VLMError(f"Gemini API lỗi: {exc}") from exc

    text = getattr(response, "text", None)
    if not text:
        raise VLMError("Gemini trả về response rỗng")
    return text.strip()
