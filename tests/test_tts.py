import io
import threading
import time
import wave

import lameenc
import numpy as np
import pytest

import config
from pipeline import tts

A = "Cửa ở phía trước hướng mười hai giờ."
B = "Giữa đường có một cái ghế lệch trái."
C = "Đi thẳng rồi hơi chuyển sang phải."


class _FakeVieneu:
    def __init__(self, stream_chunks=None):
        self._stream_chunks = stream_chunks or []

    def infer(self, text, voice=None, style=None):
        return np.zeros(3200, dtype=np.float32)

    def infer_stream(self, text, voice=None, style=None):
        yield from self._stream_chunks


def _fake(monkeypatch, *chunks):
    monkeypatch.setattr(tts, "_load_tts", lambda: _FakeVieneu(list(chunks)))


def _samples(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<i2")


def test_synthesize_returns_valid_wav(monkeypatch):
    monkeypatch.setattr(tts, "_load_tts", lambda: _FakeVieneu())
    data = tts.synthesize("xin chào")
    assert isinstance(data, bytes)
    assert len(data) > 44  # lớn hơn header WAV
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == tts.SAMPLE_RATE
        assert w.getsampwidth() == 2


def test_stream_yields_one_bytes_chunk_per_model_chunk(monkeypatch):
    _fake(monkeypatch, np.zeros(300, dtype=np.float32), np.zeros(600, dtype=np.float32))
    chunks = list(tts.synthesize_stream("xin chào"))
    assert len(chunks) == 2
    assert all(isinstance(c, bytes) for c in chunks)


def test_stream_downsamples_48k_to_16k(monkeypatch):
    _fake(monkeypatch, np.zeros(300, dtype=np.float32))
    (chunk,) = list(tts.synthesize_stream("xin chào"))
    assert len(_samples(chunk)) == 100  # 300 mẫu 48kHz -> 100 mẫu 16kHz


def test_stream_output_is_int16_little_endian(monkeypatch):
    _fake(monkeypatch, np.full(3, 1.0, dtype=np.float32))
    (chunk,) = list(tts.synthesize_stream("xin chào"))
    assert chunk == b"\xff\x7f"  # 32767 little-endian


def test_stream_carries_leftover_samples_across_chunks(monkeypatch):
    # 4 và 5 đều không chia hết cho 3; tổng 9 mẫu phải ra đủ 3 mẫu 16kHz.
    _fake(monkeypatch, np.zeros(4, dtype=np.float32), np.zeros(5, dtype=np.float32))
    total = sum(len(_samples(c)) for c in tts.synthesize_stream("xin chào"))
    assert total == 3


def test_stream_filters_instead_of_dropping_samples(monkeypatch):
    # Tín hiệu xen kẽ ±1 (Nyquist ở 48kHz). Trung bình 3 mẫu phải triệt gần hết;
    # decimate trần (pcm[::3]) sẽ giữ nguyên biên độ đầy và lộ aliasing.
    alternating = np.array([1.0, -1.0] * 150, dtype=np.float32)
    _fake(monkeypatch, alternating)
    (chunk,) = list(tts.synthesize_stream("xin chào"))
    assert np.abs(_samples(chunk)).max() < 32767 // 2


def test_stream_clips_out_of_range_samples(monkeypatch):
    _fake(monkeypatch, np.full(3, 5.0, dtype=np.float32))
    (chunk,) = list(tts.synthesize_stream("xin chào"))
    assert _samples(chunk)[0] == 32767


def test_stream_skips_empty_model_chunks(monkeypatch):
    _fake(monkeypatch, np.zeros(0, dtype=np.float32), np.zeros(300, dtype=np.float32))
    chunks = list(tts.synthesize_stream("xin chào"))
    assert len(chunks) == 1
    assert len(_samples(chunks[0])) == 100


def test_output_sample_rate_is_16k():
    assert tts.OUTPUT_SAMPLE_RATE == 16000


def test_text_stream_synthesizes_each_sentence(monkeypatch):
    _fake(monkeypatch, np.zeros(300, dtype=np.float32))
    spoken = []

    def fake_synthesize_stream(text):
        spoken.append(text)
        yield b"\x00\x00"

    monkeypatch.setattr(tts, "synthesize_stream", fake_synthesize_stream)

    list(tts.synthesize_text_stream([A + " ", B]))

    assert spoken == [A, B]


def test_text_stream_speaks_first_sentence_before_gemini_finishes(monkeypatch):
    """Điểm cốt lõi: giọng nói bắt đầu trong lúc Gemini còn đang viết tiếp.

    Thread nền đọc trước Gemini là đúng ý đồ — đọc trước mới nuôi kịp TTS. Thứ
    phải giữ là mảnh PCM đầu ra trước khi Gemini viết xong, không phải số mảnh
    text đã đọc.
    """
    gemini_done = threading.Event()

    def slow_text():
        yield A + " "
        time.sleep(0.4)
        yield B + " "
        time.sleep(0.4)
        yield C
        gemini_done.set()

    monkeypatch.setattr(tts, "synthesize_stream", lambda text: iter([b"\x01\x02"]))

    stream = tts.synthesize_text_stream(slow_text())
    first = next(stream)

    assert first == b"\x01\x02"
    assert not gemini_done.is_set(), "phải có tiếng trước khi Gemini viết xong"


def test_text_stream_synthesizes_next_sentence_while_earlier_pcm_unread(monkeypatch):
    """Điểm cốt lõi chống khoảng dừng: câu sau đã tổng hợp trước khi câu trước
    phát hết, nên người nghe không gặp khoảng lặng giữa hai câu."""
    started = []

    def slow_tts(sentence):
        started.append(sentence)
        yield b"\x01\x02"
        time.sleep(0.05)
        yield b"\x03\x04"

    monkeypatch.setattr(tts, "synthesize_stream", slow_tts)

    stream = tts.synthesize_text_stream([A + " ", B])
    next(stream)  # mới lấy mảnh đầu của câu 1

    deadline = time.monotonic() + 2.0
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(started) == 2, "câu 2 chưa được tổng hợp trong lúc câu 1 chưa phát hết"


def test_text_stream_propagates_worker_error(monkeypatch):
    """Lỗi Gemini/TTS xảy ra ở thread nền vẫn phải nổi lên cho endpoint."""

    def boom(sentence):
        raise RuntimeError("TTS chết")
        yield  # pragma: no cover

    monkeypatch.setattr(tts, "synthesize_stream", boom)

    with pytest.raises(RuntimeError, match="TTS chết"):
        list(tts.synthesize_text_stream([A]))


def test_text_stream_stops_worker_when_consumer_leaves_early(monkeypatch):
    """Client ngắt giữa chừng: thread nền phải dừng, không chạy tiếp vô ích."""
    synthesized = []

    def counting(sentence):
        synthesized.append(sentence)
        yield b"\x01\x02"

    monkeypatch.setattr(tts, "synthesize_stream", counting)

    many = [f"{A[:-1]} số {i}. " for i in range(50)]
    stream = tts.synthesize_text_stream(many)
    next(stream)
    stream.close()

    time.sleep(0.2)
    assert len(synthesized) < 50, "thread nền vẫn chạy hết sau khi consumer bỏ đi"


def test_text_stream_passes_through_every_pcm_chunk(monkeypatch):
    # Tắt chỗ thở giữa hai câu để test này chỉ nói về một việc: không mảnh PCM
    # nào của model bị rơi. Quãng lặng có test riêng ở `test_speech_pacing.py`.
    monkeypatch.setattr(config, "SPEECH_SENTENCE_PAUSE_SECONDS", 0.0)
    monkeypatch.setattr(
        tts, "synthesize_stream", lambda text: iter([b"\x01\x02", b"\x03\x04"])
    )
    chunks = list(tts.synthesize_text_stream([A + " ", B]))
    assert chunks == [b"\x01\x02", b"\x03\x04"] * 2


class _FakeMp3Encoder:
    """Giả `lameenc.Encoder`: ghi lại cấu hình, `encode()` trả theo kịch bản."""

    def __init__(self, encode_returns=None, flush_returns=b"\xaa\xbb"):
        self.calls: list[str] = []
        self._encode_returns = list(encode_returns or [])
        self._flush_returns = flush_returns

    def set_in_sample_rate(self, rate):
        self.calls.append(f"rate={rate}")

    def set_channels(self, channels):
        self.calls.append(f"channels={channels}")

    def set_bit_rate(self, kbps):
        self.calls.append(f"bitrate={kbps}")

    def encode(self, pcm):
        if self._encode_returns:
            return self._encode_returns.pop(0)
        return b""

    def flush(self):
        return self._flush_returns


def test_encode_mp3_configures_16k_mono_32kbps(monkeypatch):
    fake = _FakeMp3Encoder()
    monkeypatch.setattr(lameenc, "Encoder", lambda: fake)

    list(tts.encode_mp3(iter([b"\x00\x00"])))

    assert fake.calls == ["rate=16000", "channels=1", "bitrate=32"]


def test_encode_mp3_skips_empty_encoder_output(monkeypatch):
    fake = _FakeMp3Encoder(encode_returns=[b"", b"\x01\x02", b""], flush_returns=b"")
    monkeypatch.setattr(lameenc, "Encoder", lambda: fake)

    chunks = list(tts.encode_mp3(iter([b"\x00\x00", b"\x00\x00", b"\x00\x00"])))

    assert chunks == [b"\x01\x02"]  # mảnh rỗng bị bỏ, không yield


def test_encode_mp3_yields_flush_tail_at_the_end(monkeypatch):
    fake = _FakeMp3Encoder(encode_returns=[b""], flush_returns=b"\xaa\xbb")
    monkeypatch.setattr(lameenc, "Encoder", lambda: fake)

    chunks = list(tts.encode_mp3(iter([b"\x00\x00"])))

    assert chunks == [b"\xaa\xbb"]  # phần đệm cuối trong encoder vẫn phải ra


def test_encode_mp3_real_encoder_produces_valid_mp3_frames():
    """Kiểm tích hợp với lameenc thật: đúng tham số gọi mới ra frame hợp lệ.

    Sync word MP3 là 11 bit 1 liên tiếp: byte đầu 0xFF, 3 bit cao byte kế
    cũng phải là 1 (>= 0xE0). Silence đủ dài (0.5s ở 16kHz) để chắc chắn
    encoder đã tích luỹ đủ ít nhất một frame trước khi flush.
    """
    silence = b"\x00\x00" * (16000 // 2)  # 0.5s PCM 16-bit mono im lặng
    mp3_bytes = b"".join(tts.encode_mp3(iter([silence])))

    assert len(mp3_bytes) > 0
    assert mp3_bytes[0] == 0xFF
    assert mp3_bytes[1] & 0xE0 == 0xE0
