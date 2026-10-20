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


# ── beam + hotword (config.STT_DECODING) ────────────────────────────────────


class _BiasRecognizer(_FakeRecognizer):
    """Ghi lại hotword truyền vào create_stream (sherpa: chuỗi, mỗi cụm một dòng)."""

    def __init__(self):
        super().__init__("NHẮN CHO MẸ")
        self.hotwords = "unset"

    def create_stream(self, hotwords=None):
        self.hotwords = hotwords
        return super().create_stream()


def _fresh_asr(monkeypatch, **cfg):
    for key, value in cfg.items():
        monkeypatch.setattr(stt.config, key, value)
    stt._load_asr.cache_clear()
    captured = {}

    import sherpa_onnx

    def fake(cls, **kw):
        captured.update(kw)
        return "RECOGNIZER"

    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, "from_transducer", classmethod(fake))
    return captured


def test_default_decoding_is_beam_with_command_hotwords(monkeypatch, tmp_path):
    monkeypatch.setattr(stt.config, "_CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(stt, "_bpe_vocab", lambda model_dir: str(tmp_path / "bpe.vocab"))
    captured = _fresh_asr(monkeypatch, STT_DECODING="modified_beam_search", STT_HOTWORDS=True,
                          STT_HOTWORDS_FILE="")
    try:
        assert stt._load_asr() == "RECOGNIZER"
        assert captured["decoding_method"] == "modified_beam_search"
        assert captured["modeling_unit"] == "bpe"
        assert captured["max_active_paths"] == stt.config.STT_BEAM_PATHS
        lines = open(captured["hotwords_file"], encoding="utf-8").read().split("\n")
        assert "NHẮN CHO" in lines and "BẬT CẢNH BÁO" in lines and "MẸ" in lines
        assert stt._biasing is True
    finally:
        stt._load_asr.cache_clear()


def test_greedy_config_sends_no_hotword_args(monkeypatch):
    captured = _fresh_asr(monkeypatch, STT_DECODING="greedy_search")
    try:
        stt._load_asr()
        assert captured["decoding_method"] == "greedy_search"
        assert "hotwords_file" not in captured and "modeling_unit" not in captured
        assert stt._biasing is False
    finally:
        stt._load_asr.cache_clear()


def test_missing_bpe_vocab_falls_back_to_greedy(monkeypatch):
    """Thiếu sentencepiece/bpe.model: vẫn nghe được (greedy), không hỏng lúc khởi động."""
    monkeypatch.setattr(stt, "_bpe_vocab", lambda model_dir: None)
    captured = _fresh_asr(monkeypatch, STT_DECODING="modified_beam_search")
    try:
        stt._load_asr()
        assert captured["decoding_method"] == "greedy_search"
        assert stt._biasing is False
    finally:
        stt._load_asr.cache_clear()


def test_user_hotwords_are_sanitized_and_capped():
    stt.set_user_hotwords(["mẹ", "Anh Nam", "anh nam", "bà ngoại!!", "", "a b c d e", "số 1", None] + [f"tên{c}" for c in "abcdefghijkl"])
    try:
        got = stt.user_hotwords()
        assert got[:3] == ("MẸ", "ANH NAM", "BÀ NGOẠI")
        assert "A B C D E" not in got  # quá 4 từ
        assert all(not any(ch.isdigit() for ch in w) for w in got)
        assert len(got) <= 10
    finally:
        stt.set_user_hotwords(())


def test_decode_samples_passes_user_hotwords_only_when_biasing(monkeypatch):
    rec = _BiasRecognizer()
    monkeypatch.setattr(stt, "_load_asr", lambda: rec)
    monkeypatch.setattr(stt.config, "STT_USER_HOTWORDS", True)
    samples = np.zeros(1600, dtype=np.float32)

    monkeypatch.setattr(stt, "_biasing", True)
    stt.decode_samples(samples, ("ANH NAM", "MẸ"))
    assert rec.hotwords == "ANH NAM\nMẸ"

    stt.decode_samples(samples, ())
    assert rec.hotwords is None

    monkeypatch.setattr(stt, "_biasing", False)  # greedy: create_stream(hotwords=...) không có nghĩa
    stt.decode_samples(samples, ("ANH NAM",))
    assert rec.hotwords is None

    monkeypatch.setattr(stt, "_biasing", True)
    monkeypatch.setattr(stt.config, "STT_USER_HOTWORDS", False)
    stt.decode_samples(samples, ("ANH NAM",))
    assert rec.hotwords is None


def test_transcribe_uses_registered_user_hotwords(monkeypatch):
    rec = _BiasRecognizer()
    monkeypatch.setattr(stt, "_load_asr", lambda: rec)
    monkeypatch.setattr(stt, "_biasing", True)
    monkeypatch.setattr(stt.config, "STT_USER_HOTWORDS", True)
    stt.set_user_hotwords(["chị Lan"])
    try:
        assert stt.transcribe(_make_wav()) == "Nhắn cho mẹ"
        assert rec.hotwords == "CHỊ LAN"
    finally:
        stt.set_user_hotwords(())


def test_streaming_transcriber_decodes_with_its_own_hotwords(monkeypatch):
    from pipeline.stt_stream import StreamingTranscriber

    seen = []
    monkeypatch.setattr(stt, "decode_samples", lambda samples, hotwords=None: seen.append(hotwords) or "MẸ")
    stt.set_user_hotwords(["bố"])
    try:
        t = StreamingTranscriber("audio/wav")
        stt.set_user_hotwords(["đổi sau khi lượt bắt đầu"])  # không ảnh hưởng lượt đang chạy
        t.feed(_make_wav(0.3)[:44] + b"\x00" * 0)  # header, không có mẫu
        t._chunks.append(np.zeros(1600, dtype=np.float32))
        t._n_samples = 1600
        assert t.final() == "Mẹ"
        assert seen == [("BỐ",)]
        explicit = StreamingTranscriber("audio/wav", hotwords=["MÁ"])
        explicit._chunks.append(np.zeros(1600, dtype=np.float32))
        explicit._n_samples = 1600
        explicit.final()
        assert seen[-1] == ("MÁ",)
    finally:
        stt.set_user_hotwords(())
