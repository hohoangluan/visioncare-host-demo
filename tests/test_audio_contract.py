"""F8 — khoá ràng buộc audio CỨNG cho board (CONTRACTS.md mục 2.4).

Đây KHÔNG phải test hành vi mới. Năm test đầu chỉ KHOÁ LẠI năm điểm đã ĐÚNG
sẵn trong `app.py`/`pipeline/adpcm.py` hôm nay, để các task chạy song song
(refactor app.py, đổi pipeline TTS...) không âm thầm phá mất — vi phạm những
điều này thì board ra SNR **-11 dB** ("loa rè") mà KHÔNG có log nào báo, vì
board tin 4 byte đầu của thân, không tin header HTTP (xem
`docs/tasks/measurements/G10.md` mục 1(c)).

Test cuối (G11 — tỉ lệ nhả TTS) đo một thứ khác hẳn: không phải tính đúng của
định dạng, mà tốc độ SINH RA audio so với đồng hồ, quyết định lúc loa thật sự
kêu khi luồng không có `Content-Length` (README board §3.3). Đánh dấu
`@pytest.mark.perf` — cần model TTS thật (chậm, không xác định trên máy tải
cao) nên KHÔNG được chạy trong CI mặc định.
"""

import struct
import time
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app as app_module
import config
from app import app
from pipeline import adpcm, tts

client = TestClient(app)

# Đúng chuỗi board ESP32 thật gửi lên (`HUONG_DAN_SERVER.md` §1) — nó tự khai
# đọc được ADPCM.
_BOARD_ACCEPT = "audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav"


def _tone(seconds: float = 0.5, rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")


def _adpcm_wav_upload(samples: np.ndarray) -> bytes:
    """File ADPCM giống hệt thứ board gửi LÊN (không phải cái server trả về)."""
    blocks = adpcm.encode_blocks(samples.tobytes())
    return adpcm.wav_header(len(blocks), sample_count=samples.size) + blocks


def _files():
    return {
        "image": ("i.jpg", b"fake img", "image/jpeg"),
        "audio": ("a.wav", _adpcm_wav_upload(_tone(0.5)), "audio/wav"),
    }


@pytest.fixture
def board_response(tmp_path, monkeypatch):
    """Một lượt /process đi ĐÚNG đường board thật đi: Accept ADPCM.

    TTS bị thay bằng PCM giả (âm 440Hz) — test này khoá bố cục/định dạng của
    thân trả về, không khoá nội dung tiếng nói.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    pcm = _tone(1.0).tobytes()
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda chunks: iter([pcm])
    ):
        yield client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})


# ── 1. mono + 16kHz bắt buộc ────────────────────────────────────────────────


def test_adpcm_is_mono_16k(board_response):
    """CONTRACTS §2.4: mono BẮT BUỘC (ADPCM stereo board từ chối thẳng), 16000
    Hz BẮT BUỘC (khác đi board đổi sample rate I2S 2 lần mỗi lượt)."""
    h = board_response.headers
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-sample-rate"] == "16000" == str(adpcm.SAMPLE_RATE)

    body = board_response.content
    fmt_tag = struct.unpack_from("<H", body, 20)[0]
    n_channels = struct.unpack_from("<H", body, 22)[0]
    sample_rate = struct.unpack_from("<I", body, 24)[0]
    assert fmt_tag == adpcm.FORMAT_TAG
    assert n_channels == 1
    assert sample_rate == 16000

    # Giải mã thật: đúng công thức mono (1 mẫu/khung), không phải 2 kênh cài
    # răng lược vào cùng luồng nibble.
    payload = body[adpcm.WAV_HEADER_BYTES:]
    decoded = adpcm.decode_blocks(payload)
    n_blocks = len(payload) // adpcm.BLOCK_ALIGN
    assert decoded.size == n_blocks * adpcm.SAMPLES_PER_BLOCK


# ── 2. prelude 60 byte ra TRƯỚC mọi thứ khác ────────────────────────────────


def test_prelude_is_first_60_bytes():
    """Chunk đầu tiên mà `_stream_audio` nhả ra CHÍNH LÀ prelude — không có
    audio nào, kể cả câu chào, đi trước nó (app.py:557-558). Board đọc header
    WAV ngay trên luồng để cấu hình decoder; giữ nó lại chờ gom đệm là bắt
    board chờ trắng đúng quãng đó."""
    prelude = adpcm.wav_header(None)

    # Đặt đệm 2s: nếu prelude lỡ bị coi là audio và bị giữ lại chờ gom đệm,
    # mảnh đầu sẽ dính liền prelude + audio thay vì đúng 60 byte trần.
    with patch("pipeline.tts.synthesize_text_stream", lambda t: iter([_tone(2.0).tobytes()])):
        stream = app_module._stream_audio(
            iter(["xin chào"]), idx=1, started=time.monotonic(), processing=0.0,
            encode=tts.encode_adpcm, byte_rate=adpcm.BYTE_RATE, prelude=prelude,
        )
        first = next(stream)

    assert first == prelude
    assert len(first) == 60

    # Đối chiếu end-to-end qua /process thật: Starlette giữ đúng thứ tự
    # generator, nên 60 byte đầu của thân HTTP cũng phải khớp y hệt.
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda t: iter([_tone(0.5).tobytes()])
    ):
        response = client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})
    assert response.content[:60] == prelude


# ── 3. size = 0 hoặc 0xFFFFFFFF khi chưa biết độ dài, không bịa số ─────────


def test_prelude_size_field_when_length_unknown():
    """Đang stream, chưa biết tổng độ dài -> ghi `0` hoặc `0xFFFFFFFF`, KHÔNG
    phải một con số bịa ra (CONTRACTS §2.4)."""
    header = adpcm.wav_header(None)

    riff_size = struct.unpack_from("<I", header, 4)[0]
    fact_samples = struct.unpack_from("<I", header, 48)[0]
    data_size = struct.unpack_from("<I", header, 56)[0]

    assert riff_size in (0, 0xFFFFFFFF)
    assert fact_samples in (0, 0xFFFFFFFF)
    assert data_size in (0, 0xFFFFFFFF)
    # `wav_header` hiện chọn cụ thể 0xFFFFFFFF (không phải 0) — khoá luôn giá
    # trị thật, không chỉ tập hợp lệ, để đổi sang 0 ở nơi khác là một quyết
    # định tường minh chứ không phải lẫn lộn ngẫu nhiên giữa hai lựa chọn.
    assert riff_size == data_size == fact_samples == 0xFFFFFFFF


# ── 4. x-audio-format khớp tuyệt đối 4 byte đầu + fmt tag của thân ─────────


def test_x_audio_format_matches_body_magic(board_response, tmp_path, monkeypatch):
    """Board tin 4 byte đầu của THÂN, không tin header HTTP. Đi nhầm nhánh
    ADPCM/PCM -> SNR -11 dB, KHÔNG log nào báo (CONTRACTS §2.4) — đây là ca
    nguy hiểm nhất trong cả năm test này."""
    h = board_response.headers
    assert "ima_adpcm" in h["x-audio-format"]
    assert h["x-audio-encoding"] == "ima_adpcm"

    body = board_response.content
    assert body[:4] == b"RIFF"
    fmt_tag = struct.unpack_from("<H", body, 20)[0]
    assert fmt_tag == adpcm.FORMAT_TAG  # KHÔNG phải 0x0001 (PCM thường)

    # Đối chứng nhánh khác cũng phải tự khớp: MP3 khai `x-audio-encoding=mp3`
    # thì thân phải bắt đầu bằng frame-sync MP3 (0xFF), không phải RIFF/PCM.
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "mp3_stream")
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda t: iter([_tone(0.3).tobytes()])
    ):
        mp3_response = client.post("/process", files=_files())

    assert mp3_response.headers["x-audio-encoding"] == "mp3"
    assert mp3_response.content[:1] == b"\xff"  # frame sync MP3, không phải RIFF


# ── 5. board không bao giờ rơi vào nhánh "wav" gom trọn body ───────────────


def test_wav_format_never_for_board(tmp_path, monkeypatch):
    """`RESPONSE_FORMAT == "wav"` (app.py:467, nhánh app.py:836) gom trọn body
    rồi mới gửi -> KHÔNG được dùng cho board. `_negotiate` đọc đúng `Accept`
    board thật gửi lên phải luôn ra `adpcm_wav`, không bao giờ ra `"wav"`."""
    assert app_module._negotiate(_BOARD_ACCEPT) == "adpcm_wav"
    assert app_module._negotiate(_BOARD_ACCEPT) != "wav"

    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda t: iter([_tone(0.3).tobytes()])
    ):
        response = client.post("/process", files=_files(), headers={"Accept": _BOARD_ACCEPT})

    assert response.status_code == 200
    # Nhánh "wav" gom trọn rồi trả bằng `Response(content=...)` — luôn có
    # Content-Length (xem `test_wav_mode_sets_content_length` ở test_app.py).
    # Board đi đường stream thì KHÔNG được có header này; nếu nó xuất hiện,
    # `response_format` đã lỡ rơi vào nhánh gom trọn app.py:836.
    assert "content-length" not in response.headers


# ── G11 — tỉ lệ nhả TTS (CONTRACTS mục 6, dòng thứ hai) ────────────────────
#
# Repo này không có pytest.ini/pyproject.toml đăng ký marker nào (đã kiểm:
# `git log` không có commit nào tạo hai file đó) — pytest coi `perf` là một
# marker "lạ" nhưng KHÔNG tự loại nó khỏi lần chạy không có `-m`. Không có
# file đó trong danh sách "FILE BẠN ĐƯỢC SỬA" của T02 nên không tự thêm được
# (xem mục "Lệch với task file" ở báo cáo). Bù lại bằng cách tự đọc lại đúng
# biểu thức `-m` mà người chạy đã gõ NGAY TRONG THÂN test: không có "perf"
# trong đó thì tự skip — vừa đáp ứng "không chạy trong CI mặc định", vừa vẫn
# chạy thật khi gọi đúng `-m perf` như DoD yêu cầu.


def _skip_unless_perf_explicitly_requested(request) -> None:
    markexpr = request.config.getoption("-m", default="") or ""
    if "perf" not in markexpr:
        pytest.skip(
            "test perf (G11) — cần model TTS thật, chậm và không xác định "
            "trên máy tải cao. Chạy tường minh: "
            "pytest tests/test_audio_contract.py -m perf -q"
        )


# ~44 từ — mô phỏng một câu trả lời thật (vd. describe_space), đủ nhiều câu để
# thread nền của synthesize_text_stream có cơ hội sinh song song với lúc đẩy.
_PERF_ANSWER = (
    "Trước mặt bạn là một hành lang dài khoảng năm mét, sàn nhà bằng phẳng "
    "và không có vật cản nào ở giữa đường đi. Bên trái có một cái bàn gỗ nhỏ "
    "kê sát tường, bên phải là cửa sổ lớn đang mở, có ánh sáng chiếu vào."
)


@pytest.mark.perf
def test_tts_release_rate_at_least_1_30x(request):
    """README board §3.3: MCU so **giây tiếng đã nhận** với **giây đồng hồ**,
    không phải TTFB. Dưới 1.30x thì phải biết trước tổng độ dài để đệm 1500ms
    (ngưỡng 1.12x) — luồng ADPCM của server này KHÔNG có `Content-Length`, nên
    dưới 1.30x board sẽ ĐỢI NHẬN XONG HẾT rồi mới phát (đúng ô cuối bảng
    README). TTFB thấp không cứu được trường hợp này."""
    _skip_unless_perf_explicitly_requested(request)

    assert len(_PERF_ANSWER.split()) >= 40, "cần câu đủ dài để mô phỏng câu trả lời thật"

    # Trả trước chi phí nạp model — đo đúng tốc độ SINH, không tính giờ nạp.
    tts.clear_phrases()
    tts._load_tts()

    byte_rate = tts.OUTPUT_SAMPLE_RATE * 2  # PCM 16-bit mono 16kHz, CBR

    total_bytes = 0
    first_at: float | None = None
    last_at: float | None = None
    for chunk in tts.synthesize_text_stream(iter([_PERF_ANSWER])):
        now = time.monotonic()
        if first_at is None:
            first_at = now
        last_at = now
        total_bytes += len(chunk)

    assert first_at is not None and last_at is not None, "không sinh được byte audio nào"

    wall_elapsed = last_at - first_at
    audio_seconds = total_bytes / byte_rate
    ratio = audio_seconds / wall_elapsed if wall_elapsed > 0 else float("inf")

    # ASCII-only: console Windows (cp1252) crash ngay trên print() có dấu
    # tiếng Việt khi chạy với `-s` (`UnicodeEncodeError`, đã dính khi viết
    # test này) — giữ message đo lường bằng ASCII trần, tránh phụ thuộc encoding
    # của terminal người chạy.
    print(
        f"\nG11 measured: audio={audio_seconds:.3f}s "
        f"wall(first_chunk->last_chunk)={wall_elapsed:.3f}s ratio={ratio:.3f}x "
        f"(threshold >= 1.30x) -- ghi so nay vao docs/tasks/measurements/G11.md"
    )

    assert ratio >= 1.30, (
        f"ti le nha TTS {ratio:.3f}x < 1.30x - luong khong co Content-Length "
        f"nen board se DOI NHAN XONG HET audio roi moi phat (README SS3.3, o "
        f"cuoi bang). Xem docs/tasks/T02-chunked-end-tts-rate.md muc 6 cau 2: "
        f"flush tung cau ngay (re) hay sinh cau n+1 song song (dat hon)? "
        f"KHONG tu sua o day - de nguoi dung chot."
    )
