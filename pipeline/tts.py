import io
import wave


def synthesize(text: str) -> bytes:
    """Text tiếng Việt -> WAV bytes.

    Giai đoạn stub: sinh 0.2s im lặng (WAV mono 16kHz 16-bit hợp lệ)
    để MCU nhận file phát được. Độ dài không phụ thuộc `text`.
    """
    # TODO: nối TTS tiếng Việt thật, render `text` thành giọng nói.
    frames = b"\x00\x00" * 3200  # 0.2s @ 16000 Hz, 16-bit
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(frames)
    return buf.getvalue()
