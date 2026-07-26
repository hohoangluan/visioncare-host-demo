import io
import wave

from pipeline import stt


def _make_wav(seconds=0.2, sample_rate=16000):
    frames = b"\x00\x00" * int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)
    return buf.getvalue()


def test_transcribe_returns_str(monkeypatch):
    monkeypatch.setattr(
        stt, "_load_asr", lambda: (lambda inputs: {"text": "đọc chữ giúp tôi"})
    )
    out = stt.transcribe(_make_wav())
    assert isinstance(out, str)
    assert len(out) > 0
