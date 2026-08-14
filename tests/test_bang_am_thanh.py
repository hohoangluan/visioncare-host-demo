"""E2E: TTS sinh lệnh thoại -> STT nhận dạng -> intent -> handler (ảnh thật,
VLM/OCR thật) -> TTS đọc kết quả. Bao phủ đủ 5 case: ocr, find, money, space,
chat.

Dùng model + API thật (không mock) nên chậm và tốn quota Gemini. Cần:
- STT/TTS model đã tải cục bộ (models/stt/, cache vieneu).
- GEMINI_API_KEY hợp lệ trong models/.env.
Test nào cần Gemini sẽ tự skip nếu thiếu key (máy khác không có key vẫn
`pytest -v` được, không fail cứng).

QUOTA: gemini-2.5-flash free-tier chỉ 20 request/ngày, dùng chung với
production. File này cố tình giữ dưới 9 lệnh gọi Gemini thật cho HANDLER mỗi
lần chạy (xem comment "gọi Gemini thật" ở từng test) — đừng thêm test
real-call mới mà không kiểm tra lại ngân sách này. Con số này là 5 hồi OCR
còn đọc chữ bằng PaddleOCR cục bộ; giờ OCR cũng đi qua Gemini nên tốn thêm 1,
và intent `chat` tốn thêm 3 (1 câu hỏi giờ + 2 lượt kiểm trí nhớ hội thoại).

`pipeline/intent.detect()` giờ CŨNG gọi Gemini thật (phân loại bằng LLM thay
vì so khớp từ khóa cục bộ) — mỗi lần gọi `intent_mod.detect(...)` hoặc
`router.resolve_speech(...)` trong file này (kể cả Nhóm A bên dưới) tốn thêm
1 lệnh gọi Gemini ngoài ngân sách 9 lệnh handler ở trên. Tổng chi phí thật
của cả file cao hơn con số 9 nhiều — cân nhắc kỹ trước khi chạy nhiều lần
trong ngày.

Muốn thử model khác (ví dụ khi flash đã cạn quota) mà không đổi mặc định
production: chạy với biến môi trường `TEST_GEMINI_MODEL`, ví dụ:
    TEST_GEMINI_MODEL=gemini-2.5-flash-lite python -m pytest tests/test_bang_am_thanh.py -v

Ảnh test nằm ở tests/fixtures/ (gitignored — chứa ảnh thật có mặt người).
"""
import io
import os
import wave
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import config
from handlers import chat, describe_space, find_object, ocr, read_money
from pipeline import intent as intent_mod
from pipeline import router, stt, tts
from schemas import Intent

FIXTURES = Path(__file__).parent / "fixtures"
_TEST_MODEL = os.environ.get("TEST_GEMINI_MODEL")

pytestmark = pytest.mark.skipif(
    not config.GEMINI_API_KEY,
    reason="cần GEMINI_API_KEY thật để chạy handler qua Gemini",
)

# (id, câu lệnh thoại, intent kỳ vọng, ảnh thật tương ứng)
CASES = [
    ("ocr", "Đọc chữ trong ảnh giúp tôi", Intent.OCR, "ocr_screenshot.png"),
    ("find", "Gói bánh của tôi ở đâu", Intent.FIND, "find_snack.jpg"),
    ("money", "Tờ tiền này mệnh giá bao nhiêu", Intent.MONEY, "money_notes.jpg"),
    ("space", "Miêu tả không gian phía trước cho tôi", Intent.SPACE, "space_room.jpg"),
]
CASE_IDS = [c[0] for c in CASES]


@pytest.fixture(autouse=True)
def _maybe_override_gemini_model(monkeypatch):
    """TEST_GEMINI_MODEL cho phép thử model khác mà không đổi mặc định production."""
    if _TEST_MODEL:
        monkeypatch.setattr(config, "GEMINI_MODEL", _TEST_MODEL)


@pytest.fixture(scope="module")
def voice_models():
    """Tải STT/TTS 1 lần cho cả file thay vì mỗi test (~15-30s/lần)."""
    stt._load_asr()
    tts._load_tts()


def _image(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _is_valid_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1 and w.getnframes() > 0


# ── Nhóm A (STT/TTS thật + 1 lệnh gọi Gemini/case cho intent.detect) ──────
# Lệnh thoại tổng hợp có được nhận đúng intent qua vòng TTS -> STT -> intent?


@pytest.mark.parametrize("name,command_text,expected_intent,image_file", CASES, ids=CASE_IDS)
def test_tts_stt_roundtrip_detects_correct_intent(
    voice_models, name, command_text, expected_intent, image_file
):
    wav = tts.synthesize(command_text)
    assert _is_valid_wav(wav)

    recognized = stt.transcribe(wav)
    assert isinstance(recognized, str) and recognized

    detected = intent_mod.detect(recognized)
    assert detected == expected_intent, (
        f"STT nhận '{recognized}' từ câu gốc '{command_text}', "
        f"kỳ vọng intent '{expected_intent}' nhưng ra '{detected}'"
    )


@pytest.mark.parametrize(
    "command_text,expected_intent",
    [
        ("đọc nguyên văn giúp tôi", Intent.OCR),
        ("đọc chữ chuyên ngành giúp tôi", Intent.OCR),
        ("con mèo nhảy qua cái bàn", Intent.CHAT),  # lệnh không khớp -> trò chuyện
    ],
    ids=["ocr_raw_phrase", "ocr_specialized_phrase", "unrecognized_returns_chat"],
)
def test_tts_stt_roundtrip_edge_phrases(voice_models, command_text, expected_intent):
    """FLAKY CÓ CHỦ Ý: VieNeu sinh giọng bằng sampling nên audio lệnh khác nhau
    mỗi lần chạy; thỉnh thoảng STT nghe nhầm và test đỏ mà code không đổi gì.
    Đỏ một lần đơn lẻ ở đây không phải regression — chạy lại trước khi truy.
    Muốn hết hẳn thì phải ghim sampling của TTS (thêm tham số temperature vào
    `pipeline/tts.synthesize`) hoặc dùng file WAV lệnh thu sẵn làm fixture.
    """
    wav = tts.synthesize(command_text)
    recognized = stt.transcribe(wav)
    assert intent_mod.detect(recognized) == expected_intent, (
        f"STT nhận '{recognized}' từ câu gốc '{command_text}'"
    )


# ── Nhóm B (gọi Gemini thật — tối đa 6 lệnh gọi/lần chạy, xem quota ở trên) ─
# Gọi handler trực tiếp (không qua STT) để nội dung không phụ thuộc độ chính
# xác nhận dạng giọng nói khi kiểm tra format phản hồi.


def test_ocr_normal_mode_reads_and_translates_real_screenshot():
    """gọi Gemini thật (1): OCR NORMAL, một lượt gọi vừa đọc vừa dịch."""
    speech = "".join(ocr.handle(_image("ocr_screenshot.png"), "đọc chữ giúp tôi"))
    assert speech
    assert speech != "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."

    wav = tts.synthesize(speech)
    assert _is_valid_wav(wav)


def test_ocr_raw_mode_returns_untranslated_text():
    """gọi Gemini thật (2): RAW mode đọc nguyên văn, không dịch.

    Trước đây RAW miễn phí vì chạy PaddleOCR cục bộ. Giờ đọc chữ cũng qua
    Gemini nên case này ăn quota như các case khác.
    """
    speech = "".join(ocr.handle(_image("ocr_screenshot.png"), "đọc nguyên văn giúp tôi"))
    assert speech
    assert speech != "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."


def test_find_object_names_direction_and_distance():
    """gọi Gemini thật (3). Prompt find_object.py bắt buộc có hướng + khoảng cách."""
    speech = "".join(find_object.handle(_image("find_snack.jpg"), "gói bánh của tôi ở đâu"))
    assert speech

    lower = speech.lower()
    stated_direction = any(kw in lower for kw in ["giờ", "trái", "phải", "trước mặt"])
    # Vật đã trong tầm với thì nói "mét" là vô nghĩa — "trên tay bạn" mới là
    # câu định vị đúng. Chấp nhận cả hai, miễn người dùng biết vươn tay đi đâu.
    stated_distance = "mét" in lower or "tay" in lower

    assert stated_direction, f"thiếu hướng trong: {speech!r}"
    assert stated_distance, f"thiếu khoảng cách/tầm với trong: {speech!r}"
    assert "màu" not in lower, f"không được mô tả màu sắc: {speech!r}"


def test_read_money_states_denomination_or_explicit_uncertainty():
    """gọi Gemini thật (4). Chỉ dùng VLM (không qua OCR); cấm mô tả màu, cấm đoán bừa."""
    speech = "".join(read_money.handle(_image("money_notes.jpg"), "mệnh giá tờ tiền này bao nhiêu"))
    assert speech

    speech_lower = speech.lower()
    stated_amount = any(kw in speech_lower for kw in ["nghìn", "trăm", "đồng"])
    stated_unsure = any(
        kw in speech_lower
        for kw in ["không xác định", "không rõ", "không thấy tiền", "không chắc"]
    )
    assert stated_amount or stated_unsure, f"phản hồi không đúng format: {speech!r}"
    assert "màu" not in speech_lower, f"không được mô tả màu sắc: {speech!r}"


def test_describe_space_returns_detailed_scene_description():
    """gọi Gemini thật (5). Prompt mô tả chi tiết khung cảnh, cho phép tả màu."""
    speech = "".join(describe_space.handle(_image("space_room.jpg"), "miêu tả không gian"))
    assert speech
    assert len(speech) < 800, "prompt yêu cầu 2-4 câu, không phải cả đoạn văn dài"


def test_full_pipeline_real_audio_end_to_end_ocr_case(voice_models):
    """gọi Gemini thật (6): audio thật (TTS) -> STT -> intent -> handler thật -> TTS.

    Chỉ chạy 1 case đại diện (ocr) để xác nhận toàn bộ dây chuyền nối đúng,
    tránh lặp lại 4 lần các case đã kiểm ở nhóm trên (tốn thêm quota).
    """
    name, command_text, _, image_file = CASES[0]
    wav_in = tts.synthesize(command_text)
    pieces = router.resolve_speech(_image(image_file), wav_in)

    chunks = list(tts.synthesize_text_stream(pieces))
    assert len(chunks) > 1, (
        "model thật phải sinh nhiều mảnh cho một câu trả lời, "
        f"nhưng chỉ ra {len(chunks)} — người dùng vẫn phải chờ tổng hợp xong"
    )

    pcm = b"".join(chunks)
    duration = len(pcm) / 2 / tts.OUTPUT_SAMPLE_RATE
    assert duration > 0.3, f"phản hồi audio quá ngắn ({duration:.2f}s) cho case '{name}'"


# ── Nhóm C: intent `chat` (gọi Gemini thật, 3 lượt) ───────────────────────
# Chat là nhánh duy nhất KHÔNG gửi ảnh, và là nhánh duy nhất có trạng thái
# (lịch sử hội thoại) — hai thứ đó chỉ lộ ra khi chạy thật.


_VI_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _vi_number(n: int) -> str:
    """Số 0-24 viết bằng chữ tiếng Việt. Đủ dùng cho giờ trong ngày."""
    if n < 10:
        return _VI_DIGITS[n]
    if n < 20:
        return "mười" if n == 10 else f"mười {'một' if n == 11 else _VI_DIGITS[n % 10]}"
    tens, unit = divmod(n, 10)
    if unit == 0:
        return f"{_VI_DIGITS[tens]} mươi"
    return f"{_VI_DIGITS[tens]} mươi {'mốt' if unit == 1 else _VI_DIGITS[unit]}"


def _hour_forms(now: datetime) -> set[str]:
    """Mọi cách Gemini có thể nói ra giờ `now`, đều kèm chữ "giờ" theo sau.

    Bốn biến thể vì model tự chọn: 24h hay 12h, chữ số hay chữ viết. Đo thật
    thấy nó trả "bốn giờ mười một phút chiều" — viết bằng chữ, và đó là dạng
    ĐÚNG cho TTS, nên test phải nhận chứ không được ép model viết chữ số.

    Nhận cả giờ kế tiếp vì prompt chốt giờ lúc gọi còn assert chạy sau đó:
    test khởi động đúng lúc 13:59 không được đỏ oan.
    """
    forms = set()
    for moment in (now, now + timedelta(hours=1)):
        for hour in (moment.hour, moment.hour % 12 or 12):
            forms.add(f"{hour} giờ")
            forms.add(f"{_vi_number(hour)} giờ")
    return forms


def test_chat_answers_time_question_from_real_audio(voice_models):
    """gọi Gemini thật (7): audio thật -> STT -> intent=chat -> Gemini -> TTS.

    Câu hỏi giờ là phép thử đúng chỗ nhất cho nhánh chat: Gemini không tự biết
    bây giờ là mấy giờ, nên câu trả lời chỉ đúng nếu `handlers/chat.py` thật sự
    nhét giờ máy chủ vào prompt. Mock không phát hiện được model có chịu dùng
    con số đó hay không.
    """
    chat.reset_history()
    asked_at = datetime.now()

    wav_in = tts.synthesize("Bây giờ là mấy giờ rồi")
    recognized = stt.transcribe(wav_in)
    assert intent_mod.detect(recognized) == Intent.CHAT, (
        f"STT nhận '{recognized}', lẽ ra phải rơi vào chat"
    )

    speech = "".join(router.resolve_speech(_image("space_room.jpg"), wav_in))
    assert speech

    lower_speech = speech.lower()
    assert any(form in lower_speech for form in _hour_forms(asked_at)), (
        f"câu trả lời không nói đúng giờ máy chủ ({asked_at:%H:%M}): {speech!r}"
    )
    # Câu này đi thẳng ra loa: ký hiệu chỉ đọc được bằng mắt là rác khi đọc lên.
    for symbol in ("*", "#", "- ", "•"):
        assert symbol not in speech, f"còn ký hiệu markdown {symbol!r} trong: {speech!r}"

    assert _is_valid_wav(tts.synthesize(speech))


def test_chat_follow_up_question_uses_previous_turn(voice_models):
    """gọi Gemini thật (8, 9): hai lượt audio liên tiếp, lượt sau thiếu chủ ngữ.

    "Ở đó có bao nhiêu người" chỉ trả lời được nếu lượt trước còn trong lịch
    sử. Đây là thứ phân biệt chatbot thật với 2 lần hỏi rời rạc.
    """
    chat.reset_history()
    image = _image("space_room.jpg")

    first = "".join(router.resolve_speech(image, tts.synthesize("Thủ đô của Việt Nam là thành phố nào")))
    assert "hà nội" in first.lower(), f"lượt 1 trả lời sai: {first!r}"

    follow_up_wav = tts.synthesize("Thành phố đó có bao nhiêu người sinh sống")
    recognized = stt.transcribe(follow_up_wav)
    assert intent_mod.detect(recognized) == Intent.CHAT, (
        f"STT nhận '{recognized}', lẽ ra phải rơi vào chat"
    )

    second = "".join(router.resolve_speech(image, follow_up_wav))
    assert second

    lower = second.lower()
    knows_context = "hà nội" in lower or "triệu" in lower or "người" in lower
    assert knows_context, (
        f"lượt 2 không bám được ngữ cảnh lượt 1 ({first!r}): {second!r}"
    )
