import io
import wave

import numpy as np

from pipeline import stt


def _make_wav(seconds=0.2, sample_rate=16000, channels=1):
    frames = b"\x00\x00" * int(seconds * sample_rate) * channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)
    return buf.getvalue()


class _FakeStream:
    def __init__(self, text):
        self.result = type("R", (), {"text": text})()
        self.accepted = None

    def accept_waveform(self, sample_rate, samples):
        self.accepted = (sample_rate, samples)


class _FakeRecognizer:
    def __init__(self, text="ĐỌC CHỮ GIÚP TÔI"):
        self.text = text
        self.stream = None

    def create_stream(self):
        self.stream = _FakeStream(self.text)
        return self.stream

    def decode_stream(self, stream):
        pass


def test_transcribe_returns_str(monkeypatch):
    monkeypatch.setattr(stt, "_load_asr", lambda: _FakeRecognizer())
    out = stt.transcribe(_make_wav())
    assert isinstance(out, str)
    assert len(out) > 0


def test_transcribe_normalizes_uppercase_model_output(monkeypatch):
    """Zipformer trả CHỮ HOA; câu này đi vào prompt intent và ô tìm kiếm của host."""
    monkeypatch.setattr(stt, "_load_asr", lambda: _FakeRecognizer("MỞ BÀI HÁT SƠN TÙNG"))
    assert stt.transcribe(_make_wav()) == "Mở bài hát sơn tùng"


def test_transcribe_on_empty_result_returns_empty(monkeypatch):
    """Im lặng/nhiễu -> chuỗi rỗng, để router rơi vào nhánh `unknown`."""
    monkeypatch.setattr(stt, "_load_asr", lambda: _FakeRecognizer("   "))
    assert stt.transcribe(_make_wav()) == ""


def test_transcribe_feeds_16k_mono_to_recognizer(monkeypatch):
    """sherpa-onnx không tự resample: audio 44.1kHz phải được hạ về 16k trước."""
    recognizer = _FakeRecognizer()
    monkeypatch.setattr(stt, "_load_asr", lambda: recognizer)
    stt.transcribe(_make_wav(seconds=0.5, sample_rate=44100))

    sample_rate, samples = recognizer.stream.accepted
    assert sample_rate == 16000
    assert samples.ndim == 1
    # 0.5s @ 16kHz ~ 8000 mẫu (nội suy tuyến tính có thể lệch 1 mẫu).
    assert abs(len(samples) - 8000) <= 1


def test_decode_wav_mixes_multichannel_to_mono():
    samples, sample_rate = stt._decode_wav(_make_wav(channels=2))
    assert sample_rate == 16000
    assert samples.ndim == 1


def test_resample_keeps_16k_audio_untouched():
    samples = np.linspace(-1, 1, 1600, dtype=np.float32)
    out = stt._resample(samples, 16000)
    assert out is samples
