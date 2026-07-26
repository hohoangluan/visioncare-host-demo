from .client import VLMError, generate

__all__ = ["VLMError", "generate", "generate_text"]


def generate_text(prompt: str) -> str:
    """Text-in/text-out qua Gemini. Không đính kèm ảnh."""
    return generate(prompt)
