import asyncio
import logging
import math
from collections.abc import AsyncIterator, Iterator

import config
from models import llm, vlm
from models.llm.client import prefix_prob
from pipeline import image_quality
from pipeline.image_buffer import resize_jpeg

logger = logging.getLogger("blind_assist")

_PROMPT = (
    "Bạn đang hỗ trợ người khiếm thị nhận biết mệnh giá tiền mặt Việt Nam Đồng (VND) qua camera.\n"
    "Nhìn vào ảnh và trả lời ĐÚNG TRỌNG TÂM mệnh giá tiền mặt đọc được.\n\n"
    "QUY TẮC NGUYÊN TẮC:\n"
    "- Mở đầu ngay bằng mệnh giá, KHÔNG dùng các từ dẫn dắt hoặc từ thừa như: "
    "\"Đây là\", \"Ảnh chụp\", \"Trước mặt bạn là\", \"Trong hình có\", \"Tôi thấy\".\n"
    "- Nếu có 1 tờ: đọc trực tiếp mệnh giá (ví dụ: \"50 nghìn đồng\", \"500 nghìn đồng\", \"10 nghìn đồng\").\n"
    "- Nếu có nhiều tờ: liệt kê ngắn gọn từng mệnh giá (ví dụ: \"10 nghìn đồng và 50 nghìn đồng\").\n"
    "- KHÔNG mô tả màu sắc (người nghe không cảm nhận được màu).\n"
    "- Nếu ảnh quá mờ, bị che khuất, tối đen hoặc không thấy rõ tờ tiền nào, PHẢI nói thẳng: "
    "\"Không thấy rõ tiền, vui lòng chụp lại.\"\n"
    "- TUYỆT ĐỐI không đoán bừa khi không chắc chắn."
)


def handle(image: bytes, command_text: str) -> Iterator[str]:
    return vlm.generate_stream(_PROMPT, image=image)



# ── Chọn nhãn có xác suất (2026-10-21) ────────────────────────────────────────
# Đo trên vnd_kaggle: làn B (prompt tự do) đọc sai 10,9-11,2 %, gần như mọi ca sai là sai số chữ
# số 0 (5.000 <-> 50.000, 500.000 -> 50.000). Bản JSON "chép số + chữ rồi code đối chiếu" thua cả
# hai trục (trễ x3, model chép luôn dãy số khớp điều nó đoán). Ở đây Gemma CHỌN một nhãn trong
# tập cố định (structured choice, ~4 token, nhanh như cũ) và trả xác suất của nhãn; dưới ngưỡng
# MONEY_MIN_PROB thì từ chối. Lưới cấu hình + ngưỡng chọn trên dev: evaluations/bench/money_vnd.py --path choice.
DENOMS = (200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000)
UNSURE_LABEL, NO_MONEY_LABEL = "không rõ", "không có tiền"


def speak(value: int) -> str:
    return f"{value // 1000} nghìn đồng" if value >= 1000 else f"{value} đồng"


LABELS = {speak(d): d for d in DENOMS}
CHOICES = [*LABELS, UNSURE_LABEL, NO_MONEY_LABEL]

CHOICE_QUESTION = "Đây là tờ tiền bao nhiêu?"


def choice_messages(image: bytes) -> list[dict]:
    """Cấu hình thắng trên dev: system prompt làn A + prompt đọc tiền + câu hỏi, rồi chọn nhãn.
    (Bỏ system prompt: sai nhiều hơn; dặn "đếm kỹ chữ số 0": sai 43 % — đo 2026-10-21.)"""
    from lanes import general  # nhập muộn: lanes.general nhập module này
    text = f'{_PROMPT}\n\nNgười dùng nói: "{CHOICE_QUESTION}"\nTrả đúng một nhãn.'
    return [{"role": "system", "content": general._VISION_SYSTEM}, llm.user_message(text, image)]

NO_MONEY = "Không thấy tờ tiền nào. Bạn đưa tờ tiền ra trước kính, cách khoảng một gang tay."
UNSURE = "Chưa đọc rõ mệnh giá. Bạn lật mặt có số to về phía kính và giữ yên tay."


async def choose_raw(messages: list[dict], top_logprobs: int = 1) -> tuple[str, dict]:
    """(nhãn, choice gốc của server) — một lượt Gemma structured choice có logprobs."""
    choice = await llm.complete_raw(
        messages, max_tokens=12, temperature=0.0,
        logprobs=True, top_logprobs=top_logprobs, structured_outputs={"choice": CHOICES},
    )
    text = (choice["message"].get("content") or "").strip()
    if text not in CHOICES:
        raise llm.LLMError(f"Gemma không trả đúng nhãn: {text[:40]!r}")
    return text, choice


async def choose(messages: list[dict]) -> tuple[str, float | None]:
    """(nhãn, xác suất nhãn THÔ của server). Đã thử chuẩn hoá lại trên 13 nhãn hợp lệ (dev 2026-10-21):
    1 khung nói sai gấp đôi (3,6 -> 7,3 %) vì nhãn sai cũng "chắc" lên, 3 khung không lợi — giữ xác suất thô."""
    text, choice = await choose_raw(messages)
    return text, prefix_prob(choice, len(text))


# ── Đọc tiền v2 (2026-10-21): top-2 nhãn + câu hướng dẫn khi không chắc ───────────────────────
# Spec: docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md §3. Không tốn thêm lượt gọi model: top-2 lấy từ
# logprobs của chính lượt chọn nhãn, độ nét lấy từ ảnh đã có.
HOLD_STILL = "Giữ yên tay."
STEP_BACK = "Lùi ra xa một chút, để cả tờ tiền nằm giữa."
COME_CLOSER = "Đưa tờ tiền lại gần hơn một chút."
RETRY_FAILED = "Tôi vẫn chưa đọc chắc được tờ này."
STATIC_SPEECH = (HOLD_STILL, STEP_BACK, COME_CLOSER, RETRY_FAILED)

# Độ nét tính trên ảnh thu về cạnh dài này: đúng cỡ ảnh dev (vnd_kaggle 192x144) mà ngưỡng MONEY_BLUR_HINT được chọn.
# Laplacian phụ thuộc cỡ ảnh nên khung UXGA/VGA của kính phải thu nhỏ trước khi so với ngưỡng.
BLUR_REF_SIDE = 192
_TOP_LOGPROBS = 5  # nhánh x10 thường chỉ đứng hạng 3 ở token chữ số cuối (đo thật 2026-10-21), 2 là không đủ


def blur_score(jpeg: bytes) -> float | None:
    """Độ nét Laplacian bằng hàm production `image_quality.measure` trên ảnh cạnh dài `BLUR_REF_SIDE`; None nếu không giải mã được."""
    try:
        measured = image_quality.measure(resize_jpeg(jpeg, BLUR_REF_SIDE, 90))
    except Exception:  # noqa: BLE001 - JPEG hỏng/cắt dở: coi như không đo được
        return None
    return None if measured is None else measured[0]


def _x10(a: str, b: str) -> bool:
    """Hai nhãn mệnh giá lệch đúng x10 (50 nghìn <-> 500 nghìn, 200 đồng <-> 2 nghìn): số 0 bị cắt mép."""
    va, vb = LABELS.get(a), LABELS.get(b)
    return va is not None and vb is not None and max(va, vb) == 10 * min(va, vb)


def _label_for_prefix(prefix: str, top1: str) -> str | None:
    """Nhãn khác `top1` bắt đầu bằng `prefix` (nhánh model suýt chọn). Nhiều nhãn cùng tiền tố ("500" khớp "500 đồng" và
    "500 nghìn đồng") thì ưu tiên nhãn lệch x10 với top-1, rồi tới thứ tự trong CHOICES."""
    found = [c for c in CHOICES if c != top1 and c.startswith(prefix)]
    if not found:
        return None
    return next((c for c in found if _x10(top1, c)), found[0])


def top_labels(choice: dict, text: str) -> list[tuple[str, float | None]]:
    """[(nhãn đã chọn, xác suất), (nhãn thay thế mạnh nhất, xác suất tiền tố)] từ logprobs của lượt chọn nhãn.

    Nhãn thay thế = nhánh rẽ có xác suất lớn nhất: tại token thứ i, token khác `top_logprobs` ghép với phần đã chọn
    cho tiền tố của một nhãn khác trong CHOICES; xác suất = tích tới i-1 x xác suất token thay thế (cận dưới, phần đuôi
    nhãn không tính). Thiếu logprobs (hoặc không tính được xác suất) -> chỉ top-1 với xác suất None, để `hint` vẫn thấy "không rõ"; không có nhánh nào hợp lệ -> chỉ top-1.
    """
    items = (choice.get("logprobs") or {}).get("content")
    p1 = prefix_prob(choice, len(text))
    if not items or p1 is None:
        return [(text, p1)]
    top, best = [(text, p1)], None
    pos, cum = 0, 0.0
    for it in items:
        if pos >= len(text) or it.get("logprob") is None:
            break
        for alt in it.get("top_logprobs") or []:
            token, lp = alt.get("token", ""), alt.get("logprob")
            if token == it.get("token") or lp is None:
                continue
            label = _label_for_prefix(text[:pos] + token, text)
            if label is not None and (best is None or cum + lp > best[1]):
                best = (label, cum + lp)
        cum += it["logprob"]
        pos += len(it.get("token", ""))
    if best is not None:
        top.append((best[0], math.exp(best[1])))
    return top


def hint(top: list[tuple[str, float]], sharpness: float | None) -> str:
    """Câu nói khi không đọc chắc, đi từ trên xuống: mờ -> "Giữ yên tay."; "không rõ" hoặc hai nhãn đầu lệch x10
    (cắt mép) -> lùi ra xa; còn lại -> lại gần. Không đo được độ nét (None) thì bỏ qua luật mờ."""
    if sharpness is not None and sharpness < config.MONEY_BLUR_HINT:
        return HOLD_STILL
    if top and (top[0][0] == UNSURE_LABEL or (len(top) > 1 and _x10(top[0][0], top[1][0]))):
        return STEP_BACK
    return COME_CLOSER


async def choose_ranked(messages: list[dict]) -> tuple[str, float | None, list[tuple[str, float | None]]]:
    """Như `choose` (cùng nhãn, cùng xác suất thô) kèm top-2 nhãn để chọn câu hướng dẫn."""
    text, choice = await choose_raw(messages, top_logprobs=_TOP_LOGPROBS)
    return text, prefix_prob(choice, len(text)), top_labels(choice, text)


async def read_ranked(image: bytes, min_prob: float) -> tuple[str, list[tuple[str, float]] | None]:
    """Đọc MỘT khung: (câu nói như `combine`, top-2). Lỗi mạng/model -> (UNSURE, None): không có gì để hướng dẫn, và
    đọc lại cũng sẽ hỏng y vậy."""
    try:
        label, prob, top = await choose_ranked(choice_messages(image))
    except Exception as exc:  # noqa: BLE001
        logger.warning("đọc tiền: lỗi %r", exc)
        return UNSURE, None
    logger.info("đọc tiền: %s p=%s top=%s", label, prob, top)
    return combine([(label, prob)], min_prob), top


def say(label: str, prob: float | None, min_prob: float) -> str:
    """Câu nói cho nhãn: mệnh giá chỉ khi xác suất >= ngưỡng (không có xác suất = không chắc)."""
    return combine([(label, prob)], min_prob)


def combine(reads: list[tuple[str, float | None]], min_prob: float) -> str:
    """Gộp nhãn của nhiều khung (khung đầu = khung chính): nói mệnh giá khi có >= 1 khung chắc
    (xác suất >= ngưỡng) và KHÔNG khung nào chắc một mệnh giá khác. Đo dev 2026-10-21 (3 khung,
    ngưỡng 0,98): đúng 59 -> 75 %, sai <= 3 %; trung bình xác suất hay đòi đa số thì từ chối quá nhiều."""
    sure = {label for label, prob in reads if label in LABELS and prob is not None and prob >= min_prob}
    if len(sure) == 1:
        return sure.pop()
    if reads and reads[0][0] == NO_MONEY_LABEL and not sure:
        return NO_MONEY
    return UNSURE


async def read_choice(images: list[bytes]) -> AsyncIterator[str]:
    """Một lượt Gemma cho MỖI khung, chạy song song; 1 khung dùng ngưỡng MONEY_MIN_PROB, nhiều khung
    dùng MONEY_MULTI_MIN_PROB (thấp hơn vì đã có các khung khác chặn mâu thuẫn)."""
    results = await asyncio.gather(*(choose(choice_messages(img)) for img in images), return_exceptions=True)
    reads = [r for r in results if not isinstance(r, BaseException)]
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("đọc tiền: lỗi %r", r)
    logger.info("đọc tiền: %s", reads)
    yield combine(reads, config.MONEY_MIN_PROB if len(images) == 1 else config.MONEY_MULTI_MIN_PROB)

