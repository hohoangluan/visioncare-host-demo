import io
import wave

import numpy as np

from pipeline import tts


class _FakeVieneu:
    def infer(self, text, voice=None, style=None):
        return np.zeros(3200, dtype=np.float32)


def test_synthesize_returns_valid_wav(monkeypatch):
    monkeypatch.setattr(tts, "_load_tts", lambda: _FakeVieneu())
    data = tts.synthesize("xin chào")
    assert isinstance(data, bytes)
    assert len(data) > 44  # lớn hơn header WAV
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == tts.SAMPLE_RATE
        assert w.getsampwidth() == 2
