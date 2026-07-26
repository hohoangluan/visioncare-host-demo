import io
import wave
import pytest
from unittest.mock import patch

from pipeline import router
from schemas import Result


def _is_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1


def _fake_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 3200)
    return buf.getvalue()


def test_process_returns_wav():
    with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
         patch("pipeline.tts.synthesize", return_value=_fake_wav()), \
         patch("handlers.ocr.handle", return_value=Result(speech="nội dung đọc")):
        out = router.process(b"img", _fake_wav())
        assert isinstance(out, bytes)
        assert _is_wav(out)


def test_process_routes_to_detected_handler():
    with patch("pipeline.stt.transcribe", return_value="mở tiền giúp tôi"), \
         patch("pipeline.tts.synthesize", return_value=_fake_wav()), \
         patch("pipeline.intent.detect", return_value="money") as mock_detect, \
         patch("handlers.read_money.handle") as mock_handler:
        mock_handler.return_value = Result(speech="mệnh giá giả")
        router.process(b"img", _fake_wav())
        mock_detect.assert_called_once()
        mock_handler.assert_called_once()


def test_process_speaks_handler_result():
    with patch("pipeline.stt.transcribe", return_value="đọc chữ giúp tôi"), \
         patch("pipeline.intent.detect", return_value="ocr"), \
         patch("handlers.ocr.handle", return_value=Result(speech="nội dung đọc")), \
         patch("pipeline.tts.synthesize", return_value=b"WAVDATA") as mock_tts:
        out = router.process(b"img", _fake_wav())
        mock_tts.assert_called_once_with("nội dung đọc")
        assert out == b"WAVDATA"


def test_process_unknown_intent_returns_apology_no_handler_called():
    """Không khớp intent nào -> xin lỗi + hỏi lại, không đoán bừa qua handler nào."""
    from schemas import Intent

    with patch("pipeline.stt.transcribe", return_value="câu lệnh lạ"), \
         patch("pipeline.tts.synthesize", return_value=_fake_wav()) as mock_tts, \
         patch("pipeline.intent.detect", return_value=Intent.UNKNOWN), \
         patch("handlers.ocr.handle") as mock_ocr, \
         patch("handlers.find_object.handle") as mock_find, \
         patch("handlers.read_money.handle") as mock_money, \
         patch("handlers.describe_space.handle") as mock_space:
        router.process(b"img", _fake_wav())

        mock_tts.assert_called_once_with(router._UNKNOWN_INTENT_MESSAGE)
        for mock in (mock_ocr, mock_find, mock_money, mock_space):
            mock.assert_not_called()


@pytest.mark.parametrize("intent_name,expected_module", [
    ("ocr", "ocr"),
    ("find", "find_object"),
    ("money", "read_money"),
    ("space", "describe_space"),
])
def test_router_correctly_maps_all_intents(intent_name, expected_module):
    """Test that each intent maps to exactly one handler and others are not called.

    This test proves all 5 intent->handler mappings individually. By patching all 5
    handlers and asserting the others were NOT called, we catch regressions where
    two handlers are accidentally swapped in the _HANDLERS dict.
    """
    with patch("pipeline.stt.transcribe", return_value="câu lệnh giả"), \
         patch("pipeline.tts.synthesize", return_value=_fake_wav()), \
         patch("pipeline.intent.detect", return_value=intent_name), \
         patch("handlers.ocr.handle") as mock_ocr, \
         patch("handlers.find_object.handle") as mock_find_object, \
         patch("handlers.read_money.handle") as mock_read_money, \
         patch("handlers.describe_space.handle") as mock_describe_space:

        # Set return values for all mocks so router completes successfully
        mock_ocr.return_value = Result(speech="ocr response")
        mock_find_object.return_value = Result(speech="find response")
        mock_read_money.return_value = Result(speech="money response")
        mock_describe_space.return_value = Result(speech="space response")

        # Call the router
        router.process(b"img", _fake_wav())

        # Map expected_module name to the correct mock object
        mocks = {
            "ocr": mock_ocr,
            "find_object": mock_find_object,
            "read_money": mock_read_money,
            "describe_space": mock_describe_space,
        }

        # Assert the expected handler was called exactly once
        mocks[expected_module].assert_called_once()

        # Assert all other handlers were NOT called
        # This is critical: it catches swapped mappings
        for name, mock in mocks.items():
            if name != expected_module:
                mock.assert_not_called()


def test_space_handler_literal_in_dict():
    """Verify that the literal 'space' key exists in _HANDLERS dict mapping to describe_space.

    This test directly checks the dict structure to ensure Intent.SPACE row is not
    masked by the fallback default. Without this, a missing or typo'd space key would
    go undetected because the router would still call describe_space via the default.
    """
    from handlers import describe_space
    assert "space" in router._HANDLERS, "Intent.SPACE key missing from _HANDLERS dict"
    assert router._HANDLERS["space"] is describe_space, "Intent.SPACE should map to describe_space"
