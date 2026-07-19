import io
import wave
from unittest.mock import patch

from pipeline import router


def _is_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnchannels() == 1


def test_process_returns_wav():
    out = router.process(b"img", b"aud")
    assert isinstance(out, bytes)
    assert _is_wav(out)


def test_process_routes_to_detected_handler():
    with patch("pipeline.intent.detect", return_value="money") as mock_detect, \
         patch("handlers.read_money.handle") as mock_handler:
        from schemas import Result
        mock_handler.return_value = Result(speech="mệnh giá giả")
        router.process(b"img", b"aud")
        mock_detect.assert_called_once()
        mock_handler.assert_called_once()


def test_process_speaks_handler_result():
    from schemas import Result
    with patch("pipeline.intent.detect", return_value="ocr"), \
         patch("handlers.ocr.handle", return_value=Result(speech="nội dung đọc")), \
         patch("pipeline.tts.synthesize", return_value=b"WAVDATA") as mock_tts:
        out = router.process(b"img", b"aud")
        mock_tts.assert_called_once_with("nội dung đọc")
        assert out == b"WAVDATA"


def test_process_unknown_intent_falls_back_to_space():
    with patch("pipeline.intent.detect", return_value="khong-ton-tai"), \
         patch("handlers.describe_space.handle") as mock_space:
        from schemas import Result
        mock_space.return_value = Result(speech="miêu tả giả")
        router.process(b"img", b"aud")
        mock_space.assert_called_once()
