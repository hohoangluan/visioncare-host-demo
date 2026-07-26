import io
import wave
from functools import lru_cache

import numpy as np

import config

# VieNeu-TTS v3 Turbo outputs 48 kHz mono float32 audio.
SAMPLE_RATE = 48000


@lru_cache(maxsize=1)
def _load_tts():
    from vieneu import Vieneu

    # ONNX/CPU backend của TTS đã đủ nhanh (~1-3s/câu) và nhẹ. Ép device="cpu"
    # để không tranh VRAM/CUDA context với STT (GPU 4GB, chỉ đủ chỗ thoải mái
    # cho một model torch lớn chạy GPU cùng lúc).
    return Vieneu(device="cpu")


def synthesize(text: str) -> bytes:
    """Text tiếng Việt -> WAV bytes (VieNeu-TTS v3 Turbo, giọng nữ)."""
    tts = _load_tts()
    audio = tts.infer(text, voice=config.TTS_VOICE, style=config.TTS_STYLE)

    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
