"""Hợp đồng ADPCM với board ESP32 (xem `HUONG_DAN_SERVER.md`).

Các con số ở đây (60, 20, 0x0011, 256, 505, 8110) là hợp đồng với firmware, không
phải chi tiết cài đặt. Đổi một cái là board giải ra nhiễu trắng, mà nhiễu trắng
thì không có test nào khác bắt được.
"""

import io
import struct
import subprocess
import wave
from unittest.mock import patch

import numpy as np
import pytest

from fastapi.testclient import TestClient

import app as app_module
import config
from app import app
from pipeline import adpcm, stt, tts

client = TestClient(app)


def _tone(seconds: float = 1.0, rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")


def _pcm_wav(samples: np.ndarray, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def _adpcm_wav(samples: np.ndarray) -> bytes:
    """File giống hệt thứ board gửi lên: khối `fact` mang số mẫu THẬT.

    Khối cuối bị đệm cho tròn 256 byte nên dữ liệu dài hơn `fact` tới 504 mẫu —
    đó chính là chỗ bên giải mã phải cắt.
    """
    blocks = adpcm.encode_blocks(samples.tobytes())
    return adpcm.wav_header(len(blocks), sample_count=samples.size) + blocks


# ── Bố cục header, đúng từng offset board đọc ────────────────────────────


def test_wav_header_matches_board_contract():
    header = adpcm.wav_header(1024)

    assert len(header) == 60
    assert header[0:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert header[12:16] == b"fmt "
    # 20, không phải 16: ADPCM có thêm cbSize + wSamplesPerBlock.
    assert struct.unpack_from("<I", header, 16)[0] == 20
    assert struct.unpack_from("<H", header, 20)[0] == 0x0011  # WAVE_FORMAT_DVI_ADPCM
    assert struct.unpack_from("<H", header, 22)[0] == 1       # mono
    assert struct.unpack_from("<I", header, 24)[0] == 16000
    assert struct.unpack_from("<I", header, 28)[0] == 8110    # nAvgBytesPerSec
    assert struct.unpack_from("<H", header, 32)[0] == 256     # nBlockAlign
    assert struct.unpack_from("<H", header, 34)[0] == 4       # wBitsPerSample
    assert struct.unpack_from("<H", header, 36)[0] == 2       # cbSize
    assert struct.unpack_from("<H", header, 38)[0] == 505     # wSamplesPerBlock
    assert header[40:44] == b"fact"
    assert header[52:56] == b"data"


def test_streaming_header_declares_unknown_length():
    """Đang stream thì chưa biết tổng độ dài -> 0xFFFFFFFF, board tự phỏng đoán đệm."""
    header = adpcm.wav_header(None)

    assert struct.unpack_from("<I", header, 56)[0] == 0xFFFFFFFF  # cỡ khối data
    assert struct.unpack_from("<I", header, 48)[0] == 0xFFFFFFFF  # số mẫu ở `fact`


def test_block_holds_505_samples():
    assert adpcm.SAMPLES_PER_BLOCK == 505
    assert adpcm.samples_per_block(256) == 505


# ── Codec ────────────────────────────────────────────────────────────────


def test_encode_produces_whole_256_byte_blocks():
    blocks = adpcm.encode_blocks(_tone(1.0).tobytes())

    assert blocks
    assert len(blocks) % adpcm.BLOCK_ALIGN == 0


def test_roundtrip_keeps_the_signal():
    original = _tone(1.0)
    decoded, rate, channels = adpcm.decode_wav(_adpcm_wav(original))

    assert (rate, channels) == (16000, 1)
    n = min(decoded.size, original.size)
    err = decoded[:n].astype(float) - original[:n].astype(float)
    snr = 10 * np.log10((original[:n].astype(float) ** 2).mean() / (err ** 2).mean())
    # IMA 4-bit trên tín hiệu sạch cho ~20 dB trở lên; dưới ngưỡng này là codec
    # sai chứ không phải mất mát do nén.
    assert snr > 20, f"SNR chỉ {snr:.1f} dB"


def test_compresses_to_about_a_quarter():
    pcm = _tone(10.0).tobytes()
    blocks = adpcm.encode_blocks(pcm)

    # Board đo 320044 B -> 81212 B = 25.4%. Ta phải rơi vào cùng khoảng đó.
    assert 0.24 < len(blocks) / len(pcm) < 0.27


def test_streaming_encode_matches_one_shot():
    """Nối các lần `encode()` phải ra đúng luồng khối như nén một lần.

    Đây là điều kiện để chia mảnh theo nhịp TTS không làm rơi mẫu ở biên khối.
    """
    pcm = _tone(2.0).tobytes()
    encoder = adpcm.Encoder()
    chunked = b"".join(
        encoder.encode(pcm[i:i + 3333]) for i in range(0, len(pcm), 3333)
    ) + encoder.flush()

    assert chunked == adpcm.encode_blocks(pcm)


def test_streaming_encode_survives_an_odd_sized_chunk():
    """Mảnh lẻ byte không được ném lỗi: lúc đó header 200 đã gửi rồi."""
    pcm = _tone(0.5).tobytes()
    encoder = adpcm.Encoder()
    out = encoder.encode(pcm[:1001]) + encoder.encode(pcm[1001:]) + encoder.flush()

    assert out == adpcm.encode_blocks(pcm)


def test_decode_trims_the_padded_tail_using_fact():
    """Khối cuối được đệm cho tròn 256 byte; `fact` nói số mẫu THẬT.

    ffmpeg không cắt theo `fact` nên trả dư tới 504 mẫu — ta thì cắt.
    """
    original = _tone(1.0)  # 16000 mẫu, không chia hết cho 505
    decoded, _, _ = adpcm.decode_wav(_adpcm_wav(original))

    assert decoded.size == original.size


def test_decode_still_reads_plain_pcm_wav():
    """Đường cũ không được gãy: file test và nguồn khác vẫn là PCM 16-bit."""
    original = _tone(0.5)
    decoded, rate, channels = adpcm.decode_wav(_pcm_wav(original))

    assert (rate, channels) == (16000, 1)
    assert np.array_equal(decoded, original)


def test_rejects_stereo_adpcm():
    """ADPCM stereo cài răng nibble theo kênh; board cũng từ chối thẳng."""
    header = bytearray(adpcm.wav_header(256))
    struct.pack_into("<H", header, 22, 2)  # nChannels = 2

    with pytest.raises(ValueError, match="mono"):
        adpcm.decode_wav(bytes(header) + b"\x00" * 256)


# ── Đầu vào: STT phải đọc được file board gửi lên ────────────────────────


def test_stt_decodes_the_board_upload_format():
    """`wave` của Python ném `unknown format: 17` ở đúng chỗ này.

    Không có test này thì hỏng lại là mọi request thật rơi xuống câu báo lỗi,
    còn test suite vẫn xanh vì fixture toàn PCM.
    """
    samples, rate = stt._decode_wav(_adpcm_wav(_tone(0.5)))

    assert rate == 16000
    assert samples.size == 8000
    assert np.abs(samples).max() > 0.1  # có tín hiệu thật, không phải im lặng


def test_python_wave_module_really_cannot_read_it():
    """Ghim lý do phải tự viết parser, để đừng ai đưa `wave` quay lại."""
    with pytest.raises(wave.Error):
        wave.open(io.BytesIO(_adpcm_wav(_tone(0.2))), "rb")


# ── Đầu ra: endpoint /process ────────────────────────────────────────────


_BOARD_ACCEPT = "audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav"


@pytest.fixture
def fake_speech(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    pcm = _tone(1.0).tobytes()
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda chunks: iter([pcm])
    ):
        yield


def _files():
    return {
        "image": ("i.jpg", b"fake img", "image/jpeg"),
        "audio": ("a.wav", _adpcm_wav(_tone(0.5)), "audio/wav"),
    }


def test_board_accept_header_gets_adpcm(fake_speech):
    response = client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    body = response.content
    assert body[:4] == b"RIFF"
    assert struct.unpack_from("<H", body, 20)[0] == 0x0011
    assert struct.unpack_from("<H", body, 32)[0] == 256
    # Header ra trước, rồi tới các khối tròn 256 byte.
    assert (len(body) - 60) % adpcm.BLOCK_ALIGN == 0


def test_adpcm_response_headers_describe_the_decoder(fake_speech):
    response = client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})
    h = response.headers

    assert h["x-audio-format"] == "ima_adpcm;rate=16000;channels=1;block=256"
    assert h["x-audio-encoding"] == "ima_adpcm"
    assert h["x-audio-sample-rate"] == "16000"
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-bits"] == "4"
    assert h["x-audio-byte-rate"] == "8110"
    assert h["x-audio-block-align"] == "256"
    assert h["x-audio-samples-per-block"] == "505"


def test_adpcm_stream_sends_raw_blocks_without_a_riff_header(fake_speech, monkeypatch):
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "adpcm_stream")
    response = client.post("/process", files=_files())

    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content[:4] != b"RIFF"
    assert len(response.content) % adpcm.BLOCK_ALIGN == 0


def test_the_60_byte_header_leaves_before_any_audio(tmp_path, monkeypatch):
    """Board đọc header ngay trên luồng, nên nó không được nằm chờ gom đủ đệm.

    Đặt đệm 2 giây rồi kiểm mảnh ĐẦU TIÊN của generator: phải đúng 60 byte
    header, chứ không phải header dính liền 2 giây audio.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 2.0)

    chunks = list(app_module._stream_audio(
        ["xin chào"], idx=1, started=0.0, processing=0.0,
        encode=tts.encode_adpcm, byte_rate=adpcm.BYTE_RATE,
        prelude=adpcm.wav_header(None),
    ))

    assert len(chunks[0]) == 60
    assert chunks[0][:4] == b"RIFF"


def test_saved_debug_file_is_playable(fake_speech, tmp_path):
    """File trên đĩa phải mở được, không mang cỡ `data` giả của luồng stream."""
    client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})

    saved = tmp_path / "response1.wav"
    assert saved.exists()
    body = saved.read_bytes()
    assert struct.unpack_from("<I", body, 56)[0] == len(body) - 60
    decoded, rate, _ = adpcm.decode_wav(body)
    assert rate == 16000
    assert decoded.size > 0


# ── Đối chiếu với ffmpeg, thứ client dùng để kiểm ────────────────────────


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _has_ffmpeg(), reason="cần ffmpeg trong PATH")
def test_ffmpeg_decodes_our_output_bit_for_bit(tmp_path):
    """Client kiểm bằng ffmpeg/ffprobe, nên hai bên phải ra cùng một kết quả."""
    original = _tone(1.0)
    mine = tmp_path / "mine.wav"
    mine.write_bytes(_adpcm_wav(original))

    out = tmp_path / "out.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mine), "-c:a", "pcm_s16le", str(out)],
        check=True,
    )
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        ref = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")

    ours, _, _ = adpcm.decode_wav(mine.read_bytes())
    n = min(ref.size, ours.size)
    assert np.array_equal(ref[:n], ours[:n])


@pytest.mark.skipif(not _has_ffmpeg(), reason="cần ffmpeg trong PATH")
def test_we_decode_ffmpeg_output_bit_for_bit(tmp_path):
    """Chiều ngược lại: file board sinh ra cùng đường mã hoá với ffmpeg."""
    src = tmp_path / "src.wav"
    src.write_bytes(_pcm_wav(_tone(1.0)))
    enc = tmp_path / "enc.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ar", "16000", "-ac", "1",
         "-c:a", "adpcm_ima_wav", "-block_size", "256", str(enc)],
        check=True,
    )
    dec = tmp_path / "dec.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(enc), "-c:a", "pcm_s16le", str(dec)],
        check=True,
    )
    with wave.open(str(dec), "rb") as w:
        ref = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")

    ours, _, _ = adpcm.decode_wav(enc.read_bytes())
    n = min(ref.size, ours.size)
    assert np.array_equal(ref[:n], ours[:n])
