import inspect
import io
import logging
import re
import time
import wave
from unittest.mock import patch

import numpy as np
import pytest

from fastapi import UploadFile
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse
from PIL import Image

import app as app_module
import config
from app import app, _stream_audio
from app import process as process_endpoint
from pipeline import tts


client = TestClient(app)


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\\x00\\x00" * 100)
    return buf.getvalue()


def _files():
    return {
        "image": ("i.jpg", b"fake img", "image/jpeg"),
        "audio": ("a.wav", _wav_bytes(), "audio/wav"),
    }


@pytest.fixture
def stream_mode(monkeypatch):
    """Kiểm hành vi PCM stream trần. Mặc định production giờ là mp3_stream."""
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "pcm_stream")


@pytest.fixture
def mp3_mode(monkeypatch):
    """Kiểm hành vi MP3 stream (mặc định production)."""
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "mp3_stream")


def _fake_pcm_stream(text_chunks):
    yield b"\x01\x02" * 100
    yield b"\x03\x04" * 100


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_preloads_models(monkeypatch):
    """Warm-up phải chạy đúng đường TTS mà /process dùng: đường stream.

    Hâm nóng `synthesize()` không hâm nóng phiên giải mã theo frame của
    `infer_stream()`, nên request thật đầu tiên vẫn phải gánh warm-up.
    """
    # Tắt dựng sẵn câu nói: nó cũng gọi `synthesize_stream`, nên để bật thì
    # `warmed` phụ thuộc vào việc cache trên đĩa đang có sẵn những câu nào —
    # test sẽ đỗ hay trượt tuỳ máy. Phần đó có test riêng ở `test_phrases.py`.
    monkeypatch.setattr(config, "TTS_PRERENDER", False)
    warmed = []

    def fake_stream(text):
        warmed.append(text)
        yield b"\x00\x00"

    with patch("pipeline.stt._load_asr") as mock_load_asr, patch(
        "pipeline.stt.transcribe"
    ) as mock_transcribe, patch("pipeline.tts._load_tts") as mock_load_tts, patch(
        "pipeline.tts.synthesize_stream", fake_stream
    ):
        with TestClient(app):
            pass

    mock_load_asr.assert_called_once()
    mock_transcribe.assert_called_once()
    mock_load_tts.assert_called_once()
    assert warmed == ["Khởi động"]  # generator phải được tiêu thụ, không chỉ tạo


def test_startup_does_not_load_any_local_ocr_model():
    """OCR chạy qua Gemini: không còn model OCR cục bộ nào phải nạp lúc khởi động."""
    import app as app_module

    source = inspect.getsource(app_module.preload_models)
    assert "ocr" not in source.lower()


def test_process_streams_raw_pcm_without_wav_header(stream_mode):
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content[:4] != b"RIFF"  # PCM trần, MCU không phải bỏ header
    assert response.content == b"\x01\x02" * 100 + b"\x03\x04" * 100


def test_stream_headers_carry_everything_client_needs(stream_mode, monkeypatch):
    """MCU cấu hình I2S và tính buffer chỉ từ header, không phải hardcode.

    Tách thành từng header số riêng thay vì bắt firmware parse chuỗi ghép —
    trên MCU, `atoi` một header là xong, tách chuỗi là thêm chỗ để sai.
    """
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 2.0)

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    h = response.headers
    assert h["x-audio-sample-rate"] == "16000"
    assert h["x-audio-bits"] == "16"
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-encoding"] == "pcm_s16le"
    # Byte/giây: MCU nhân trực tiếp ra kích thước buffer, không phải tự tính.
    assert h["x-audio-byte-rate"] == "32000"
    # Số giây audio đã nằm sẵn trong mảnh đầu -> MCU phát ngay, không chờ thêm.
    assert h["x-audio-preroll-seconds"] == "2.0"


def test_preroll_header_follows_config(stream_mode, monkeypatch):
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 3.5)

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert response.headers["x-audio-preroll-seconds"] == "3.5"


def test_process_declares_pcm_format_in_header(stream_mode):
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert response.headers["x-audio-format"] == "pcm_s16le;rate=16000;channels=1"


def test_process_returns_streaming_response_not_buffered_body(stream_mode):
    """Response phải là StreamingResponse chạy trên generator.

    Starlette gửi từng mảnh generator ra socket ngay khi lấy được, nên đây là
    thứ quyết định MCU nghe sớm hay phải chờ. (Kiểm qua TestClient không được:
    nó gom cả body rồi mới trả, che mất tính tuần tự.)
    """
    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = process_endpoint(image=None, audio=None)

    assert isinstance(response, StreamingResponse)
    # Starlette bọc sync generator bằng iterate_in_threadpool -> TTS chạy ở
    # threadpool, không chặn event loop của các request song song.
    assert inspect.isasyncgen(response.body_iterator)


def test_stream_pcm_yields_each_chunk_before_synthesizing_the_next(tmp_path, monkeypatch):
    """Điểm cốt lõi: mảnh đầu rời server khi TTS chưa tổng hợp phần còn lại.

    Tắt đệm ở đây để kiểm riêng cơ chế chuyển tiếp; chính sách đệm có test
    riêng (`test_holds_back_until_preroll_is_ready`).
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    synthesized = []

    def counting_stream(text_chunks):
        for i in range(3):
            synthesized.append(i)
            yield bytes([i]) * 2

    with patch("pipeline.tts.synthesize_text_stream", counting_stream):
        stream = _stream_audio(iter(["xin chào"]), 1, time.monotonic(), 0.0)
        first = next(stream)
        synthesized_when_first_ready = list(synthesized)
        rest = list(stream)

    assert first == b"\x00\x00"
    assert synthesized_when_first_ready == [0]  # mảnh 1 và 2 chưa tổng hợp
    assert rest == [b"\x01\x01", b"\x02\x02"]


def test_process_speaks_text_from_router(stream_mode):
    with patch("pipeline.router.resolve_speech", return_value=iter(["nội dung ", "đọc"])), patch(
        "pipeline.tts.synthesize_text_stream", side_effect=_fake_pcm_stream
    ) as mock_stream:
        client.post("/process", files=_files())

    spoken = "".join(mock_stream.call_args.args[0])
    assert spoken == f"{app_module._RECEIVED_MESSAGE}\nnội dung đọc"


def test_process_speaks_received_message_before_running_anything(stream_mode):
    """Câu chào phải ra TRƯỚC khi STT/Gemini chạy, không phải sau.

    Đây là toàn bộ lý do nó tồn tại: người khiếm thị bấm gửi xong không có gì để
    nhìn, im lặng vài giây đầu không phân biệt được với "gửi hụt, bấm lại đi".
    Kéo `resolve_speech` trước rồi mới nói thì câu chào tới sau đúng quãng im
    lặng mà nó sinh ra để xoá.
    """
    order = []

    def slow_resolve(image, audio, opening_seconds=0.0):
        order.append("resolve")
        yield "kết quả"

    def recording_tts(text_chunks):
        for chunk in text_chunks:
            order.append(chunk)
            yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech", slow_resolve), patch(
        "pipeline.tts.synthesize_text_stream", recording_tts
    ):
        client.post("/process", files=_files())

    assert order[0] == f"{app_module._RECEIVED_MESSAGE}\n"
    assert order[1] == "resolve"


def test_process_missing_image_still_streams_pcm(stream_mode):
    files = {"audio": ("a.wav", _wav_bytes(), "audio/wav")}
    with patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert len(response.content) > 0


def test_process_missing_audio_still_streams_pcm(stream_mode):
    files = {"image": ("i.jpg", b"fake img", "image/jpeg")}
    with patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert len(response.content) > 0


def test_process_pipeline_error_still_streams_error_speech(stream_mode):
    spoken = []

    def capture(text_chunks):
        spoken.append("".join(text_chunks))
        yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech", side_effect=RuntimeError("boom")), patch(
        "pipeline.tts.synthesize_text_stream", capture
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert len(response.content) > 0
    assert spoken == ["Có lỗi xảy ra, vui lòng thử lại"]


def test_process_streams_error_speech_when_gemini_fails_on_first_piece(stream_mode):
    """Gemini 503 nổ lúc kéo mảnh text đầu — vẫn phải đổi thành câu báo lỗi.

    Với Gemini streaming, lệnh gọi API chỉ thật sự chạy khi có người kéo mảnh
    đầu. Nếu endpoint trả StreamingResponse trước khi kéo, lỗi nổ sau khi
    header 200 đã gửi và MCU chỉ nhận được im lặng.
    """
    spoken = []

    def failing_text(image, audio):
        raise RuntimeError("503 UNAVAILABLE")
        yield  # pragma: no cover - để hàm này là generator, giống router thật

    def capture(text_chunks):
        spoken.append("".join(text_chunks))
        yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech", failing_text), patch(
        "pipeline.tts.synthesize_text_stream", capture
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert len(response.content) > 0
    assert spoken == ["Có lỗi xảy ra, vui lòng thử lại"]


def test_wav_mode_returns_complete_playable_file(tmp_path, monkeypatch):
    """Chế độ WAV trọn gói: gửi một lần, có header, phát được bằng player.

    Dùng khi đường truyền tới MCU không tải nổi 32 KB/s liên tục mà PCM stream
    đòi hỏi — thà chờ lâu còn hơn nghe ngắt quãng.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "wav")

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    with wave.open(io.BytesIO(response.content), "rb") as w:
        assert w.getframerate() == tts.OUTPUT_SAMPLE_RATE
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 200


def test_wav_mode_sets_content_length(tmp_path, monkeypatch):
    """MCU biết trước tổng số byte -> cấp phát/ghi thẻ nhớ được, không đoán mò."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "wav")

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert int(response.headers["content-length"]) == len(response.content)


def test_wav_mode_still_speaks_errors(tmp_path, monkeypatch):
    """Chưa gửi byte nào khi lỗi nổ -> vẫn đổi được thành câu báo lỗi."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "wav")
    spoken = []

    def capture(text_chunks):
        spoken.append("".join(text_chunks))
        yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech", side_effect=RuntimeError("boom")), patch(
        "pipeline.tts.synthesize_text_stream", capture
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"
    assert spoken == ["Có lỗi xảy ra, vui lòng thử lại"]


def test_stream_mode_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "pcm_stream")

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        response = client.post("/process", files=_files())

    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content[:4] != b"RIFF"


def _pcm_seconds(n: float) -> bytes:
    return b"\x00\x00" * int(n * tts.OUTPUT_SAMPLE_RATE)


def test_holds_back_until_preroll_is_ready(tmp_path, monkeypatch):
    """Gửi sớm quá thì MCU đuổi kịp server và hụt tiếng giữa câu.

    Gom sẵn một quãng rồi mới gửi byte đầu -> server luôn đi trước người nghe,
    MCU cứ đọc socket là có dữ liệu, không cần ring buffer lớn.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 2.0)

    def five_half_second_chunks(text_chunks):
        for _ in range(5):
            yield _pcm_seconds(0.5)

    with patch("pipeline.tts.synthesize_text_stream", five_half_second_chunks):
        stream = _stream_audio(iter(["xin chào"]), 1, time.monotonic(), 0.0)
        first = next(stream)

    seconds = len(first) / 2 / tts.OUTPUT_SAMPLE_RATE
    assert seconds >= 2.0, f"mảnh đầu chỉ có {seconds:.2f}s, chưa đủ đệm"


def test_preroll_does_not_wait_for_the_whole_answer(tmp_path, monkeypatch):
    """Đệm là để mượt, không phải quay về gửi trọn gói."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 1.0)
    synthesized = []

    def counting(text_chunks):
        for i in range(10):
            synthesized.append(i)
            yield _pcm_seconds(0.5)

    with patch("pipeline.tts.synthesize_text_stream", counting):
        stream = _stream_audio(iter(["xin chào"]), 1, time.monotonic(), 0.0)
        next(stream)

    assert len(synthesized) == 2, f"đã tổng hợp {len(synthesized)}/10 mảnh trước khi gửi"


def test_short_answer_shorter_than_preroll_still_sent(tmp_path, monkeypatch):
    """Câu báo lỗi ngắn hơn mức đệm vẫn phải phát ra, không được nuốt."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 5.0)

    with patch("pipeline.tts.synthesize_text_stream", lambda t: iter([_pcm_seconds(0.5)])):
        chunks = list(_stream_audio(iter(["lỗi"]), 1, time.monotonic(), 0.0))

    assert b"".join(chunks) == _pcm_seconds(0.5)


def test_preroll_zero_sends_immediately(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)

    with patch("pipeline.tts.synthesize_text_stream", lambda t: iter([b"\x01\x02", b"\x03\x04"])):
        stream = _stream_audio(iter(["xin chào"]), 1, time.monotonic(), 0.0)
        assert next(stream) == b"\x01\x02"


def test_process_streams_error_speech_when_gemini_dies_before_any_audio():
    """Gemini rớt sau mảnh text đầu nhưng trước khi TTS kịp sinh byte nào.

    Đúng tình huống của request120: mất mạng giữa chừng, chưa mảnh text nào
    đủ thành câu. Nếu chỉ bọc try/except quanh mảnh TEXT đầu thì MCU nhận
    HTTP 200 rỗng — người khiếm thị không nghe gì và không biết tại sao.
    """
    spoken = []

    def dying_text(image, audio):
        yield "Trước mặt bạn"  # chưa có dấu chấm -> chưa thành câu, chưa có PCM
        raise RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")

    def fake_sentence_tts(sentence):
        spoken.append(sentence)
        yield b"\x01\x02" * 100

    # Không patch synthesize_text_stream: cần đúng hành vi gom câu thật thì
    # mới tái hiện được "có text rồi nhưng chưa ra byte audio nào".
    with patch("pipeline.router.resolve_speech", dying_text), patch(
        "pipeline.tts.synthesize_stream", fake_sentence_tts
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert len(response.content) > 0, "MCU nhận 200 rỗng, không nghe được gì"
    assert spoken[-1] == "Có lỗi xảy ra, vui lòng thử lại"


def test_stream_pcm_reraises_error_raised_before_first_chunk(tmp_path, monkeypatch):
    """Chưa gửi byte nào thì lỗi phải nổi lên để endpoint đổi thành câu báo lỗi."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    def failing_before_audio(text_chunks):
        raise RuntimeError("chết trước khi ra byte nào")
        yield  # pragma: no cover - để hàm này là generator

    with patch("pipeline.tts.synthesize_text_stream", failing_before_audio):
        stream = _stream_audio(iter(["xin chào"]), 1, time.monotonic(), 0.0)
        with pytest.raises(RuntimeError):
            next(stream)


def test_process_does_not_drain_gemini_before_streaming(stream_mode, tmp_path, monkeypatch):
    """Chỉ kéo đủ để bắt lỗi sớm, không gom hết rồi mới phát.

    Tắt đệm để kiểm riêng điểm này — có đệm thì lượng kéo do số giây audio
    quyết định, không còn là 1 mảnh.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    pulled = []

    def counting_text(image, audio):
        for piece in ["một. ", "hai. ", "ba."]:
            pulled.append(piece)
            yield piece

    def one_sentence_then_stop(text_chunks):
        """Mô phỏng TTS: đọc text tới khi đủ một câu rồi trả PCM."""
        for text in text_chunks:
            if text.strip().endswith("."):
                yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech", counting_text), patch(
        "pipeline.tts.synthesize_text_stream", one_sentence_then_stop
    ):
        process_endpoint(
            image=UploadFile(file=io.BytesIO(b"fake img"), filename="i.jpg"),
            audio=UploadFile(file=io.BytesIO(_wav_bytes()), filename="a.wav"),
        )

    # Byte đầu tới từ câu chào (đứng trước `resolve_speech`), nên lúc đó chưa
    # kéo mảnh nào của Gemini. Điều cần giữ là "không gom hết 3 mảnh rồi mới
    # phát" — kéo hết mới là hỏng.
    assert pulled == [], f"đã kéo {len(pulled)} mảnh trước khi stream"


def _logged_seconds(caplog, field: str) -> float:
    match = re.search(rf"{field}=([\d.]+)s", caplog.text)
    assert match, f"không thấy '{field}=' trong log:\n{caplog.text}"
    return float(match.group(1))


def test_process_logs_time_to_first_byte_and_total(stream_mode, caplog, tmp_path, monkeypatch):
    """Đo được lúc MCU nghe tiếng đầu tiên, tách khỏi lúc câu nói kết thúc."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)

    def slow_stream(text_chunks):
        time.sleep(0.2)
        yield b"\x00\x00"
        time.sleep(0.3)
        yield b"\x00\x00"

    with caplog.at_level(logging.INFO, logger="blind_assist"):
        with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
            "pipeline.tts.synthesize_text_stream", slow_stream
        ):
            client.post("/process", files=_files())

    ttfb = _logged_seconds(caplog, "ttfb")
    total = _logged_seconds(caplog, "tổng")
    assert 0.2 <= ttfb < 0.5, "ttfb phải tính tới mảnh đầu, không phải mảnh cuối"
    assert total >= 0.5
    assert total > ttfb


def test_process_logs_time_spent_before_streaming_starts(stream_mode, caplog, tmp_path, monkeypatch):
    """Tách phần STT/OCR/Gemini ra khỏi phần TTS để biết chỗ nào tốn giây."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    def slow_resolve(image, audio, opening_seconds=0.0):
        time.sleep(0.2)
        return "xin chào"

    with caplog.at_level(logging.INFO, logger="blind_assist"):
        with patch("pipeline.router.resolve_speech", slow_resolve), patch(
            "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
        ):
            client.post("/process", files=_files())

    assert _logged_seconds(caplog, "xử lý") >= 0.2


def test_process_logs_audio_duration(stream_mode, caplog, tmp_path, monkeypatch):
    """Độ dài audio so với tổng thời gian cho biết MCU có bị hụt tiếng không."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    def one_second_of_audio(text_chunks):
        yield b"\x00\x00" * tts.OUTPUT_SAMPLE_RATE

    with caplog.at_level(logging.INFO, logger="blind_assist"):
        with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
            "pipeline.tts.synthesize_text_stream", one_second_of_audio
        ):
            client.post("/process", files=_files())

    assert _logged_seconds(caplog, "audio") == 1.0


def test_process_saves_streamed_audio_as_wav_for_debug(stream_mode, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", _fake_pcm_stream
    ):
        client.post("/process", files=_files())

    saved = list(tmp_path.glob("response*.wav"))
    assert len(saved) == 1
    with wave.open(str(saved[0]), "rb") as w:
        assert w.getframerate() == tts.OUTPUT_SAMPLE_RATE
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 200  # 400 byte PCM / 2 byte mỗi mẫu


def test_process_error_midstream_appends_error_speech(stream_mode, monkeypatch):
    """Byte đã gửi đi thì không rút header lại được, nhưng vẫn nói được câu báo lỗi.

    Dừng ngang thì người khiếm thị nghe cụt giữa câu rồi im — không phân biệt
    được với "đã nói xong". Nối câu báo lỗi vào cuối mới cho họ biết là hỏng.

    Tắt đệm để mảnh đầu thật sự đã rời server trước khi lỗi nổ — có đệm thì
    lỗi rơi vào tình huống khác, xem test ngay dưới.
    """
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    spoken = []

    def failing_stream(text_chunks):
        spoken.append("".join(text_chunks))
        yield b"\x01\x02" * 100
        raise RuntimeError("TTS chết giữa chừng")

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", failing_stream
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert spoken[-1] == "Có lỗi xảy ra, vui lòng thử lại"
    # Lượt cứu cũng dùng đúng `failing_stream` nên nó chết lần hai; điều cần
    # kiểm là server không thử vòng thứ ba và không trả 500.
    assert response.content == b"\x01\x02" * 200


def test_mp3_stream_is_the_default_response_format():
    assert config.RESPONSE_FORMAT == "mp3_stream"


def test_process_mp3_stream_sets_content_type_and_headers(mp3_mode, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda t: iter([_pcm_seconds(0.3)])
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    h = response.headers
    assert h["x-audio-encoding"] == "mp3"
    assert h["x-audio-sample-rate"] == "16000"
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-byte-rate"] == str(tts.MP3_BYTE_RATE)
    assert h["x-audio-format"] == "mp3;bitrate=32kbps;rate=16000;channels=1"
    assert "x-audio-bits" not in h  # không áp dụng cho dữ liệu đã nén
    assert response.content[:1] == b"\xff"  # frame sync MP3, không phải PCM/RIFF


def test_process_mp3_stream_saves_debug_file_as_mp3(mp3_mode, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", lambda t: iter([_pcm_seconds(0.3)])
    ):
        client.post("/process", files=_files())

    assert list(tmp_path.glob("response*.mp3")), "phải lưu response*.mp3, không phải .wav"
    assert not list(tmp_path.glob("response*.wav"))


def test_process_mp3_stream_preroll_uses_mp3_byte_rate(mp3_mode, tmp_path, monkeypatch):
    """Đệm MP3 tính theo byte-rate nén (4000 B/s), không theo byte-rate PCM."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 1.0)

    with patch(
        "pipeline.tts.synthesize_text_stream",
        lambda t: iter([_pcm_seconds(2.0)]),  # nhiều hơn preroll để không bị nuốt hết vào 1 mảnh do hết stream
    ):
        stream = _stream_audio(
            iter(["xin chào"]), 1, time.monotonic(), 0.0,
            encode=tts.encode_mp3, byte_rate=tts.MP3_BYTE_RATE,
        )
        first = next(stream)

    assert len(first) >= tts.MP3_BYTE_RATE * 1.0, "mảnh đầu chưa đủ 1s đệm theo byte-rate MP3"


def test_error_during_preroll_speaks_error_instead_of_a_blip(tmp_path, monkeypatch):
    """Lỗi trước khi đệm đầy: audio đang giữ chưa gửi, nên vẫn đổi được.

    Người dùng nghe câu báo lỗi thay vì một mẩu 0.006 giây rồi im bặt.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 2.0)
    spoken = []

    def dies_during_preroll(text_chunks):
        text = "".join(text_chunks)
        spoken.append(text)
        yield b"\x01\x02" * 100  # 0.006s, còn xa mức đệm 2s
        if len(spoken) == 1:
            raise RuntimeError("TTS chết giữa chừng")

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), patch(
        "pipeline.tts.synthesize_text_stream", dies_during_preroll
    ):
        response = client.post("/process", files=_files())

    assert response.status_code == 200
    assert spoken[-1] == "Có lỗi xảy ra, vui lòng thử lại"
    assert len(response.content) > 0


def _flat_jpeg(color: int) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((100, 100), color, dtype=np.uint8), mode="L").save(
        buf, format="JPEG"
    )
    return buf.getvalue()


def test_process_passes_bad_image_through_to_the_router(stream_mode, tmp_path, monkeypatch):
    """`app.py` KHÔNG được tự chặn theo chất lượng ảnh.

    Ở đây chưa biết người dùng hỏi gì, mà cùng một tấm ảnh tối có thể là vô dụng
    ("đọc chữ giùm tôi") hoặc hoàn toàn không liên quan ("gọi cho mẹ"). Quyết
    định đó thuộc về `pipeline/router.py`, sau khi đã có intent.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    files = {
        "image": ("i.jpg", _flat_jpeg(10), "image/jpeg"),
        "audio": ("a.wav", _wav_bytes(), "audio/wav"),
    }

    with patch(
        "pipeline.router.resolve_speech", return_value=iter(["đang gọi"])
    ) as mock_resolve, patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=files)

    assert response.status_code == 200
    mock_resolve.assert_called_once()


def test_process_works_without_any_image(stream_mode, tmp_path, monkeypatch):
    """Ảnh không còn bắt buộc: "gọi cho mẹ" hay "kể chuyện cười" không cần ảnh nào."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    files = {"audio": ("a.wav", _wav_bytes(), "audio/wav")}

    with patch(
        "pipeline.router.resolve_speech", return_value=iter(["đang gọi cho mẹ"])
    ) as mock_resolve, patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=files)

    assert response.status_code == 200
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args[0][0] is None


def test_process_needs_audio(tmp_path, monkeypatch):
    """Audio thì vẫn bắt buộc — đó là câu lệnh, thiếu nó là không có gì để làm."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    files = {"image": ("i.jpg", _flat_jpeg(120), "image/jpeg")}
    spoken = []

    def capture(text_chunks):
        spoken.append("".join(text_chunks))
        yield b"\x01\x02" * 100

    with patch("pipeline.router.resolve_speech") as mock_resolve, patch(
        "pipeline.tts.synthesize_stream", capture
    ):
        client.post("/process", files=files)

    mock_resolve.assert_not_called()
    assert spoken == ["Không nhận được âm thanh, vui lòng nói lại."]


def test_process_calls_router_normally_when_image_quality_is_fine(
    stream_mode, tmp_path, monkeypatch
):
    """Ảnh không decode được (như 'fake img' ở test khác) hoặc đạt chuẩn vẫn đi tiếp bình thường."""
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    rng = np.random.default_rng(0)
    normal = np.clip(rng.normal(120, 60, (100, 100)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(normal, mode="L").save(buf, format="JPEG")
    files = {
        "image": ("i.jpg", buf.getvalue(), "image/jpeg"),
        "audio": ("a.wav", _wav_bytes(), "audio/wav"),
    }

    with patch(
        "pipeline.router.resolve_speech", return_value=iter(["xin chào"])
    ) as mock_resolve, patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=files)

    assert response.status_code == 200
    mock_resolve.assert_called_once()
