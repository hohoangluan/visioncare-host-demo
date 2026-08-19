import io
import logging
import re
import time
import wave
import pytest
from unittest.mock import patch

from pipeline import router
from schemas import Intent


def _logged_seconds(caplog, field: str) -> float:
    match = re.search(rf"{field}=([\d.]+)s", caplog.text)
    assert match, f"không thấy '{field}=' trong log:\n{caplog.text}"
    return float(match.group(1))


def _fake_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 3200)
    return buf.getvalue()


def _dark_jpeg() -> bytes:
    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((100, 100), 8, dtype=np.uint8), mode="L").save(buf, "JPEG")
    return buf.getvalue()


@pytest.mark.parametrize(
    "intent,handler",
    [
        (Intent.CONTACT_CALL, "handlers.contact_call.handle"),
        (Intent.MUSIC_PLAY, "handlers.music_play.handle"),
        (Intent.CHAT, "handlers.chat.handle"),
    ],
)
def test_bad_image_does_not_block_intents_that_ignore_it(intent, handler):
    """Lỗi gốc: ảnh tối/phẳng chặn cả "gọi cho mẹ", dù handler gọi điện không
    hề mở ảnh ra xem. Cổng lọc phải chạy SAU khi biết intent."""
    with patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"), \
         patch("pipeline.intent.detect_with_params", return_value=(intent, {})), \
         patch(handler, return_value=iter(["đang chạy"])):
        assert list(router.resolve_speech(_dark_jpeg(), _fake_wav())) == ["đang chạy"]


def test_bad_image_still_blocks_intents_that_read_it():
    with patch("pipeline.stt.transcribe", return_value="tờ này bao nhiêu"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.MONEY, {})), \
         patch("handlers.read_money.handle") as mock_handle:
        spoken = list(router.resolve_speech(_dark_jpeg(), _fake_wav()))

    mock_handle.assert_not_called()
    assert spoken == ["Ảnh quá tối, vui lòng ra chỗ đủ sáng và chụp lại."]


def test_missing_image_only_matters_for_intents_that_need_one():
    with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})), \
         patch("handlers.ocr.handle") as mock_handle:
        spoken = list(router.resolve_speech(None, _fake_wav()))

    mock_handle.assert_not_called()
    assert spoken == ["Không nhận được ảnh từ kính, vui lòng thử lại."]


def test_no_image_needed_for_a_phone_action():
    with patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.CONTACT_CALL, {})), \
         patch("handlers.contact_call.handle", return_value=iter(["đang gọi"])):
        assert list(router.resolve_speech(None, _fake_wav())) == ["đang gọi"]


def test_gibberish_goes_to_chat_instead_of_a_canned_refusal():
    """Câu nghe ra chữ mà không ra nghĩa giờ về `chat`, không còn nhãn riêng.

    Gemini đọc được nguyên văn nên nó phán "có hiểu được không" chính xác hơn bộ
    phân loại, và nói được câu sát tình huống thay vì đọc một câu soạn sẵn. Ràng
    buộc không-bịa nằm trong `_SYSTEM_PROMPT` của `handlers/chat.py`.
    """
    with patch("pipeline.stt.transcribe", return_value="lô ca ta xi mà"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})), \
         patch("handlers.chat.handle", return_value=iter(["Tôi chưa hiểu ý bạn."])):
        assert list(router.resolve_speech(b"img", _fake_wav())) == ["Tôi chưa hiểu ý bạn."]


def test_silence_gets_the_did_not_hear_message():
    """Không nghe ra chữ nào là chuyện khác hẳn nghe ra chữ mà khó hiểu: cách
    sửa là nói TO HƠN / gần mic hơn, và chưa có gì để đưa cho Gemini đọc cả."""
    with patch("pipeline.stt.transcribe", return_value="  "), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.UNKNOWN, {})):
        assert list(router.resolve_speech(b"img", _fake_wav())) == [
            router._NO_SPEECH_MESSAGE
        ]


def test_classifier_outage_does_not_blame_the_user():
    """Gemini timeout cũng ra nhãn `unknown`. Nói "tôi chưa hiểu bạn muốn gì"
    lúc đó là đổ lỗi cho người dùng về một việc họ không làm sai."""
    with patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"), \
         patch(
             "pipeline.intent.detect_with_params",
             return_value=(Intent.UNKNOWN, {"classify_failed": True}),
         ):
        assert list(router.resolve_speech(b"img", _fake_wav())) == [
            router._CLASSIFY_FAILED_MESSAGE
        ]


def test_resolve_speech_returns_text_not_audio():
    with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})), \
         patch("handlers.ocr.handle", return_value=iter(["nội dung ", "đọc"])):
        out = router.resolve_speech(b"img", _fake_wav())
        assert list(out) == ["nội dung ", "đọc"]


def test_resolve_speech_passes_pieces_through_lazily():
    """Router không được gom hết Gemini rồi mới trả — mất sạch cái lợi streaming."""
    pulled = []

    def handle(image, command_text):
        for piece in ["một ", "hai ", "ba"]:
            pulled.append(piece)
            yield piece

    with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})), \
         patch("handlers.ocr.handle", handle):
        stream = router.resolve_speech(b"img", _fake_wav())
        first = next(stream)

    assert first == "một "
    assert pulled == ["một "]


def test_resolve_speech_logs_stt_and_handler_time_separately(caplog):
    """STT chạy cục bộ, handler gọi mạng ra Gemini — tách ra mới biết tối ưu chỗ nào."""

    def slow_transcribe(audio):
        time.sleep(0.2)
        return "đọc chữ giúp tôi"

    def slow_handle(image, command_text):
        time.sleep(0.3)
        yield "nội dung đọc"

    with caplog.at_level(logging.INFO, logger="blind_assist"):
        with patch("pipeline.stt.transcribe", slow_transcribe), \
             patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})), \
             patch("handlers.ocr.handle", slow_handle):
            list(router.resolve_speech(b"img", _fake_wav()))

    assert 0.2 <= _logged_seconds(caplog, "stt") < 0.3
    assert _logged_seconds(caplog, "handler") >= 0.3


def test_resolve_speech_logs_recognized_command(caplog):
    """Log câu STT nghe được: sai intent thì đây là chỗ đầu tiên cần nhìn."""
    with caplog.at_level(logging.INFO, logger="blind_assist"):
        with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
             patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})), \
             patch("handlers.ocr.handle", return_value=iter(["nội dung ", "đọc"])):
            list(router.resolve_speech(b"img", _fake_wav()))

    assert "đọc chữ giúp tôi" in caplog.text
    assert "ocr" in caplog.text


def test_resolve_speech_routes_to_detected_handler():
    with patch("pipeline.stt.transcribe", return_value="mở tiền giúp tôi"), \
         patch("pipeline.intent.detect_with_params", return_value=("money", {})) as mock_detect, \
         patch("handlers.read_money.handle") as mock_handler:
        mock_handler.return_value = iter(["mệnh giá giả"])
        list(router.resolve_speech(b"img", _fake_wav()))
        mock_detect.assert_called_once()
        mock_handler.assert_called_once()


def test_resolve_speech_unknown_intent_returns_apology_no_handler_called():
    """Không nghe ra chữ nào -> xin nói lại, không đoán bừa qua handler nào."""
    from schemas import Intent

    with patch("pipeline.stt.transcribe", return_value=""), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.UNKNOWN, {})), \
         patch("handlers.ocr.handle") as mock_ocr, \
         patch("handlers.find_object.handle") as mock_find, \
         patch("handlers.read_money.handle") as mock_money, \
         patch("handlers.describe_space.handle") as mock_space, \
         patch("handlers.describe_hazard.handle") as mock_hazard, \
         patch("handlers.chat.handle") as mock_chat:
        out = "".join(router.resolve_speech(b"img", _fake_wav()))

        assert out == router._NO_SPEECH_MESSAGE
        for mock in (mock_ocr, mock_find, mock_money, mock_space, mock_hazard, mock_chat):
            mock.assert_not_called()


def test_resolve_speech_routes_unmatched_command_to_chat():
    """Câu không khớp intent nào (LLM trả chat) đi thẳng sang chat."""
    with patch("pipeline.stt.transcribe", return_value="bây giờ là mấy giờ rồi"), \
         patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})), \
         patch("handlers.chat.handle", return_value=iter(["Bây giờ là 14 giờ."])) as mock_chat:
        out = "".join(router.resolve_speech(b"img", _fake_wav()))

        assert out == "Bây giờ là 14 giờ."
        mock_chat.assert_called_once()


@pytest.mark.parametrize("intent_name,expected_module", [
    ("ocr", "ocr"),
    ("find", "find_object"),
    ("money", "read_money"),
    ("space", "describe_space"),
    ("hazard", "describe_hazard"),
    ("chat", "chat"),
    ("nav_start", "nav_start"),
    ("nav_stop", "nav_stop"),
    ("contact_call", "contact_call"),
    ("emergency_call", "emergency_call"),
    ("ride_quote", "ride_quote"),
    ("ride_confirm", "ride_confirm"),
    ("music_play", "music_play"),
    ("music_stop", "music_stop"),
    ("music_volume", "music_volume"),
])
def test_router_correctly_maps_all_intents(intent_name, expected_module):
    with patch("pipeline.stt.transcribe", return_value="câu lệnh giả"), \
         patch("pipeline.intent.detect_with_params", return_value=(intent_name, {})), \
         patch("handlers.ocr.handle") as mock_ocr, \
         patch("handlers.find_object.handle") as mock_find_object, \
         patch("handlers.read_money.handle") as mock_read_money, \
         patch("handlers.describe_space.handle") as mock_describe_space, \
         patch("handlers.describe_hazard.handle") as mock_describe_hazard, \
         patch("handlers.chat.handle") as mock_chat, \
         patch("handlers.nav_start.handle") as mock_nav_start, \
         patch("handlers.nav_stop.handle") as mock_nav_stop, \
         patch("handlers.contact_call.handle") as mock_contact_call, \
         patch("handlers.emergency_call.handle") as mock_emergency_call, \
         patch("handlers.ride_quote.handle") as mock_ride_quote, \
         patch("handlers.ride_confirm.handle") as mock_ride_confirm, \
         patch("handlers.music_play.handle") as mock_music_play, \
         patch("handlers.music_stop.handle") as mock_music_stop, \
         patch("handlers.music_volume.handle") as mock_music_volume:

        mocks = {
            "ocr": mock_ocr,
            "find_object": mock_find_object,
            "read_money": mock_read_money,
            "describe_space": mock_describe_space,
            "describe_hazard": mock_describe_hazard,
            "chat": mock_chat,
            "nav_start": mock_nav_start,
            "nav_stop": mock_nav_stop,
            "contact_call": mock_contact_call,
            "emergency_call": mock_emergency_call,
            "ride_quote": mock_ride_quote,
            "ride_confirm": mock_ride_confirm,
            "music_play": mock_music_play,
            "music_stop": mock_music_stop,
            "music_volume": mock_music_volume,
        }

        for m in mocks.values():
            m.return_value = iter(["ok"])

        list(router.resolve_speech(b"img", _fake_wav()))

        mocks[expected_module].assert_called_once()
        for name, mock in mocks.items():
            if name != expected_module:
                mock.assert_not_called()
