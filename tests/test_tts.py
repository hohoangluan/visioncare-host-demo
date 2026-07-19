import io
import wave
from pipeline import tts


def test_synthesize_returns_valid_wav():
    data = tts.synthesize("xin chào")
    assert isinstance(data, bytes)
    assert len(data) > 44  # lớn hơn header WAV
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 16000
        assert w.getsampwidth() == 2
