import io
import wave
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


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


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_process_returns_wav():
    response = client.post("/process", files=_files())
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 44


def test_process_missing_image_still_returns_wav():
    files = {"audio": ("a.wav", _wav_bytes(), "audio/wav")}
    response = client.post("/process", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_process_missing_audio_still_returns_wav():
    files = {"image": ("i.jpg", b"fake img", "image/jpeg")}
    response = client.post("/process", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_process_pipeline_error_still_returns_wav():
    with patch("pipeline.router.process", side_effect=RuntimeError("boom")):
        response = client.post("/process", files=_files())
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 44
