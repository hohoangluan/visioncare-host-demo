import glob
import io
import logging
import os
import re
import wave

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response

import config
from models import ocr as ocr_model
from pipeline import router, stt, tts

logger = logging.getLogger("blind_assist")

app = FastAPI(title="Blind-Assist Audio Server")


def _next_debug_index() -> int:
    """Số thứ tự kế tiếp, dựa trên request*.wav đã có trong STORAGE_DIR."""
    os.makedirs(config.STORAGE_DIR, exist_ok=True)
    indices = [
        int(m.group(1))
        for f in glob.glob(os.path.join(config.STORAGE_DIR, "request*.wav"))
        if (m := re.match(r"request(\d+)\.wav$", os.path.basename(f)))
    ]
    return max(indices, default=0) + 1


def _save_debug_audio(name: str, audio_bytes: bytes) -> None:
    path = os.path.join(config.STORAGE_DIR, name)
    with open(path, "wb") as f:
        f.write(audio_bytes)


def _image_extension(image_bytes: bytes) -> str:
    if image_bytes[:2] == b"\xff\xd8":
        return "jpg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "jpg"


def _save_debug_image(idx: int, image_bytes: bytes) -> None:
    ext = _image_extension(image_bytes)
    path = os.path.join(config.STORAGE_DIR, f"request{idx}.{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)


def _dummy_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)  # 0.1s im lặng
    return buf.getvalue()


def _dummy_image() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 64), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@app.on_event("startup")
def preload_models() -> None:
    """Load ASR, TTS, and OCR models, và chạy thử mỗi model 1 lần.

    Lần infer đầu tiên của mỗi model (STT/TTS/OCR) tốn thêm thời gian khởi
    tạo (warm-up kernel, dựng batch engine...) so với các lần sau. Trả
    trước chi phí đó ở đây để request thật đầu tiên của người dùng không
    phải gánh thêm warm-up này — bấm gửi post là có kết quả ngay.

    Thứ tự load STT/TTS (torch) trước, OCR (paddle) sau phải giữ nguyên:
    đảo ngược làm paddle giành DLL search path của Windows trước, khiến
    import torch phía sau lỗi "shm.dll" không load được.
    """
    stt._load_asr()
    stt.transcribe(_dummy_wav())
    tts._load_tts()
    tts.synthesize("Khởi động")
    ocr_model.engine._get_ocr()
    ocr_model.engine.extract_text(_dummy_image())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
def process(
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Process one image/audio command and always answer with playable WAV.

    Sync def (không async): FastAPI chạy nó trong threadpool riêng thay vì
    trên event loop chính, nên STT/OCR/gọi Gemini/TTS của một request không
    chặn các request khác đang xử lý song song.
    """
    if image is None or audio is None:
        return Response(
            content=tts.synthesize("Thiếu ảnh hoặc âm thanh"),
            media_type="audio/wav",
        )

    idx = _next_debug_index()

    try:
        image_bytes = image.file.read()
        audio_bytes = audio.file.read()
        _save_debug_audio(f"request{idx}.wav", audio_bytes)
        _save_debug_image(idx, image_bytes)
        wav = router.process(image_bytes, audio_bytes)
    except Exception:  # noqa: BLE001 - MCU must receive audio, never a JSON error.
        logger.exception("process() request%d thất bại", idx)
        wav = tts.synthesize("Có lỗi xảy ra, vui lòng thử lại")

    _save_debug_audio(f"response{idx}.wav", wav)
    return Response(content=wav, media_type="audio/wav")
