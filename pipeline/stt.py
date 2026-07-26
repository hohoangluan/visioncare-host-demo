import io
import wave
from functools import lru_cache

import numpy as np

import config


@lru_cache(maxsize=1)
def _load_asr():
    import torch
    from transformers import pipeline

    use_cuda = torch.cuda.is_available()
    # fp16 trên GPU: giảm ~50% VRAM cho whisper-medium (~1.5GB thay vì ~3GB) -
    # quan trọng vì GPU 4GB còn phải chia cho OCR + TTS chạy cùng lúc.
    return pipeline(
        "automatic-speech-recognition",
        model=config.STT_MODEL_DIR,
        device=0 if use_cuda else -1,
        torch_dtype=torch.float16 if use_cuda else torch.float32,
    )


def _decode_wav(audio: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(audio), "rb") as w:
        channels = w.getnchannels()
        sample_rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        # Whisper cần mono; audio stereo/đa kênh bị đọc raw thẳng sẽ ra
        # mảng interleaved sai độ dài -> gộp về mono bằng cách lấy trung bình.
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def transcribe(audio: bytes) -> str:
    """Audio WAV -> câu lệnh tiếng Việt (PhoWhisper).

    Ép sẵn language="vi", task="transcribe": app chỉ nhận lệnh tiếng Việt,
    nên bỏ qua bước tự nhận diện ngôn ngữ của Whisper (chạy thêm 1 forward
    pass tốn thời gian mà kết quả luôn là "vi").
    """
    samples, sample_rate = _decode_wav(audio)
    asr = _load_asr()
    result = asr(
        {"raw": samples, "sampling_rate": sample_rate},
        generate_kwargs={"language": "vi", "task": "transcribe"},
    )
    return result["text"].strip()
