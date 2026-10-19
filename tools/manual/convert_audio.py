"""Đổi một file âm thanh (m4a, mp3...) sang WAV bằng ffmpeg.

Dùng: python tools/manual/convert_audio.py input.m4a [output.wav]
ffmpeg lấy từ PATH, hoặc đặt FFMPEG_PATH trong .env.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

input_file = Path(sys.argv[1])
output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else input_file.with_suffix(".wav")

if not input_file.exists():
    print(f"Không tìm thấy file: {input_file}")
    sys.exit(1)

ffmpeg_path = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
if not ffmpeg_path:
    print("Không tìm thấy ffmpeg. Cài ffmpeg vào PATH hoặc đặt FFMPEG_PATH.")
    sys.exit(1)

print(f"Đang chuyển đổi {input_file} sang {output_file}...")
subprocess.run(
    [ffmpeg_path, "-y", "-i", str(input_file), "-vn", str(output_file)],
    check=True,
)
print(f"Đã chuyển xong: {output_file}")
