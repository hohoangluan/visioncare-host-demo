from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response

from pipeline import router, tts

app = FastAPI(title="Blind-Assist Audio Server")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
async def process(
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """Process one image/audio command and always answer with playable WAV."""
    if image is None or audio is None:
        return Response(
            content=tts.synthesize("Thiếu ảnh hoặc âm thanh"),
            media_type="audio/wav",
        )

    try:
        image_bytes = await image.read()
        audio_bytes = await audio.read()
        wav = router.process(image_bytes, audio_bytes)
    except Exception:  # noqa: BLE001 - MCU must receive audio, never a JSON error.
        wav = tts.synthesize("Có lỗi xảy ra, vui lòng thử lại")

    return Response(content=wav, media_type="audio/wav")
