from pathlib import Path

import httpx

BASE_URL = "https://api.visioncare-host.uk/process"
IMAGE_PATH = "Screenshot 2026-05-28 202503.png"
AUDIO_PATH = "Recording2.wav"
OUTPUT_WAV = "saved_response3.wav"

files = {
    "image": (Path(IMAGE_PATH).name, open(IMAGE_PATH, "rb"), "image/png"),
    "audio": (Path(AUDIO_PATH).name, open(AUDIO_PATH, "rb"), "audio/wav"),
}

response = httpx.post(BASE_URL, files=files, timeout=300)
response.raise_for_status()

Path(OUTPUT_WAV).write_bytes(response.content)

print("status:", response.status_code)
print("content-type:", response.headers.get("content-type"))
print("bytes:", len(response.content))
print("saved to:", OUTPUT_WAV)
