"""Gọi /process trên server thật, lưu audio và in các mốc thời gian.

In cả tốc độ tải thật (KB/s). Đây là con số quyết định MCU có nghe mượt được
khi bật chế độ stream hay không: PCM 16 kHz 16-bit cần **32 KB/s liên tục**.
Dưới mức đó thì stream chắc chắn ngắt quãng, phải dùng WAV trọn gói.
"""
import time
import wave
from pathlib import Path

import httpx

BASE_URL = "https://api.visioncare-host.uk/process"
IMAGE_PATH = "Screenshot 2026-05-28 202503.png"
AUDIO_PATH = "Recording2.wav"
OUTPUT_WAV = "saved_response3.wav"
SAMPLE_RATE = 16000

files = {
    "image": (Path(IMAGE_PATH).name, open(IMAGE_PATH, "rb"), "image/png"),
    "audio": (Path(AUDIO_PATH).name, open(AUDIO_PATH, "rb"), "audio/wav"),
}

started = time.monotonic()
first_chunk_at = None
chunks = []

with httpx.stream("POST", BASE_URL, files=files, timeout=300) as response:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    for chunk in response.iter_bytes():
        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - started
        chunks.append(chunk)

body = b"".join(chunks)
elapsed = time.monotonic() - started
download_time = elapsed - first_chunk_at

if body[:4] == b"RIFF":
    # Chế độ "wav": server đã bọc header sẵn, ghi thẳng ra file.
    Path(OUTPUT_WAV).write_bytes(body)
    with wave.open(OUTPUT_WAV, "rb") as w:
        audio_seconds = w.getnframes() / w.getframerate()
else:
    # Chế độ "pcm_stream": PCM trần, phải bọc header mới phát được bằng player.
    with wave.open(OUTPUT_WAV, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(body)
    audio_seconds = len(body) / 2 / SAMPLE_RATE

print("status:", response.status_code)
print("content-type:", content_type)
print("bytes:", len(body))
print(f"byte đầu về sau : {first_chunk_at:.2f}s")
print(f"tổng thời gian  : {elapsed:.2f}s")
print(f"độ dài audio    : {audio_seconds:.2f}s")
if download_time > 0:
    speed = len(body) / download_time / 1024
    print(f"tốc độ tải      : {speed:.1f} KB/s  (cần >= 32 KB/s để stream mượt)")
    if speed < 32:
        print("  -> đường truyền KHÔNG đủ cho chế độ stream, phải dùng RESPONSE_FORMAT=wav")
print("saved to:", OUTPUT_WAV)
