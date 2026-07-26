"""E2E: TTS sinh lệnh thoại -> STT nhận dạng -> intent -> handler (ảnh thật,
VLM/OCR thật) -> TTS đọc kết quả. Bao phủ đủ 4 case: ocr, find, money, space.

Dùng model + API thật (không mock) nên chậm và tốn quota Gemini. Cần:
- STT/TTS model đã tải cục bộ (models/stt/, cache vieneu).
- GEMINI_API_KEY hợp lệ trong models/.env.
Test nào cần Gemini sẽ tự skip nếu thiếu key (máy khác không có key vẫn
`pytest -v` được, không fail cứng).

QUOTA: gemini-2.5-flash free-tier chỉ 20 request/ngày, dùng chung với
production. File này cố tình giữ dưới 5 lệnh gọi Gemini thật mỗi lần chạy
(xem comment "gọi Gemini thật" ở từng test) — đừng thêm test real-call mới
mà không kiểm tra lại ngân sách này. Muốn thử model khác (ví dụ khi flash đã
cạn quota) mà không đổi mặc định production: chạy với biến môi trường
`TEST_GEMINI_MODEL`, ví dụ:
    TEST_GEMINI_MODEL=gemini-2.5-flash-lite python -m pytest tests/test_bang_am_thanh.py -v

Ảnh test nằm ở tests/fixtures/ (gitignored — chứa ảnh thật có mặt người).
"""
import io
import os
import wave
from pathlib import Path

import pytest

import config
from handlers import describe_space, find_object, ocr, read_money
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


def _wav_duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / w.getframerate()


# ── Nhóm A (miễn phí — chỉ STT/TTS thật, không gọi Gemini) ────────────────
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
        ("con mèo nhảy qua cái bàn", Intent.UNKNOWN),  # lệnh không khớp -> hỏi lại
    ],
    ids=["ocr_raw_phrase", "ocr_specialized_phrase", "unrecognized_returns_unknown"],
)
def test_tts_stt_roundtrip_edge_phrases(voice_models, command_text, expected_intent):
    wav = tts.synthesize(command_text)
    recognized = stt.transcribe(wav)
    assert intent_mod.detect(recognized) == expected_intent, (
        f"STT nhận '{recognized}' từ câu gốc '{command_text}'"
    )


# ── Nhóm B (gọi Gemini thật — tối đa 5 lệnh gọi/lần chạy, xem quota ở trên) ─
# Gọi handler trực tiếp (không qua STT) để nội dung không phụ thuộc độ chính
# xác nhận dạng giọng nói khi kiểm tra format phản hồi.


def test_ocr_normal_mode_reads_and_translates_real_screenshot():
    """gọi Gemini thật (1): OCR NORMAL -> vlm.generate_text dịch."""
    result = ocr.handle(_image("ocr_screenshot.png"), "đọc chữ giúp tôi")
    assert result.speech
    assert result.speech != "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."

    wav = tts.synthesize(result.speech)
    assert _is_valid_wav(wav)


def test_ocr_raw_mode_returns_untranslated_text():
    """Miễn phí: RAW mode bỏ qua Gemini, chỉ chạy PaddleOCR cục bộ."""
    result = ocr.handle(_image("ocr_screenshot.png"), "đọc nguyên văn giúp tôi")
    assert result.speech
    assert result.speech != "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."


def test_find_object_names_direction_and_distance():
    """gọi Gemini thật (2). Prompt find_object.py bắt buộc có hướng + khoảng cách."""
    result = find_object.handle(_image("find_snack.jpg"), "gói bánh của tôi ở đâu")
    assert result.speech
    assert "mét" in result.speech.lower(), f"thiếu khoảng cách trong: {result.speech!r}"
    assert "màu" not in result.speech.lower(), f"không được mô tả màu sắc: {result.speech!r}"


def test_read_money_states_denomination_or_explicit_uncertainty():
    """gọi Gemini thật (3). Chỉ dùng VLM (không qua OCR); cấm mô tả màu, cấm đoán bừa."""
    result = read_money.handle(_image("money_notes.jpg"), "mệnh giá tờ tiền này bao nhiêu")
    assert result.speech

    speech_lower = result.speech.lower()
    stated_amount = any(kw in speech_lower for kw in ["nghìn", "trăm", "đồng"])
    stated_unsure = any(
        kw in speech_lower
        for kw in ["không xác định", "không rõ", "không thấy tiền", "không chắc"]
    )
    assert stated_amount or stated_unsure, f"phản hồi không đúng format: {result.speech!r}"
    assert "màu" not in speech_lower, f"không được mô tả màu sắc: {result.speech!r}"


def test_describe_space_returns_short_sentence_without_visual_details():
    """gọi Gemini thật (4). Prompt cấm mô tả màu sắc/chi tiết thị giác."""
    result = describe_space.handle(_image("space_room.jpg"), "miêu tả không gian")
    assert result.speech
    assert len(result.speech) < 400, "prompt yêu cầu 1-2 câu ngắn gọn"
    assert "màu" not in result.speech.lower(), f"không được mô tả màu sắc: {result.speech!r}"


def test_full_pipeline_real_audio_end_to_end_ocr_case(voice_models):
    """gọi Gemini thật (5): audio thật (TTS) -> STT -> intent -> handler thật -> TTS.

    Chỉ chạy 1 case đại diện (ocr) để xác nhận toàn bộ dây chuyền nối đúng,
    tránh lặp lại 4 lần các case đã kiểm ở nhóm trên (tốn thêm quota).
    """
    name, command_text, _, image_file = CASES[0]
    wav_in = tts.synthesize(command_text)
    wav_out = router.process(_image(image_file), wav_in)

    assert _is_valid_wav(wav_out)
    duration = _wav_duration(wav_out)
    assert duration > 0.3, f"phản hồi audio quá ngắn ({duration:.2f}s) cho case '{name}'"
