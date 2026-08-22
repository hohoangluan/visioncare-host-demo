from collections.abc import Iterator

from handlers import action_flow
from models import ocr
from pipeline import image_quality


OCR_CACHE_TTL_SECONDS = 300.0


def _remember(transcript: str) -> None:
    """T14/E2; T13 phải dùng lại helper state chung, không tạo cache thứ hai."""
    action_flow.remember_ocr(transcript)


def _no_text(params: dict) -> str:
    """Nối T15/H3/H5: đếm sentinel và tăng hướng dẫn theo attempt thật."""
    image_quality.record_no_text(None, None)
    attempt = int(params.get("_ocr_attempt") or 0) + 1
    guidance = ocr.prompts.guidance_for_attempt(attempt)
    pending = action_flow.set_pending(
        slot="ocr_retry",
        intent="ocr",
        known={"_ocr_attempt": attempt},
        question=guidance,
        kind="fill",
    )
    pending.attempt = attempt
    return guidance


def handle(
    image: bytes, command_text: str, params: dict | None = None
) -> Iterator[str]:
    """Đọc chữ trong ảnh. Mặc định dịch sang tiếng Việt.

    "nguyên văn" -> đọc thô, không dịch. "chuyên ngành" -> dịch nhưng giữ
    nguyên thuật ngữ chuyên ngành.
    """
    params = dict(params or {})
    cached = action_flow.get_last_ocr(OCR_CACHE_TTL_SECONDS)
    if params.get("ocr_followup") and cached is not None:
        return ocr.answer_followup_stream(cached["text"], command_text)

    raw = command_text.lower()
    if "nguyên văn" in raw:
        mode = ocr.Mode.RAW
    elif "chuyên ngành" in raw:
        mode = ocr.Mode.SPECIALIZED
    else:
        mode = ocr.Mode.NORMAL
    return ocr.read_stream(
        image,
        mode,
        command_text,
        on_complete=_remember,
        on_no_text=lambda: _no_text(params),
    )
