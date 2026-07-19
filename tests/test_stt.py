from pipeline import stt


def test_transcribe_returns_str():
    out = stt.transcribe(b"fake wav bytes")
    assert isinstance(out, str)
    assert len(out) > 0
