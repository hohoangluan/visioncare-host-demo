import os
import subprocess
import sys
from pathlib import Path

input_file = Path("Recording(2).m4a")
output_file = Path("Recording2.wav")

if not input_file.exists():
    print(f"Không tìm thấy file: {input_file}")
    sys.exit(1)

ffmpeg_path = r"C:\Users\Ho Hoang Luan\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"

if not os.path.exists(ffmpeg_path):
    print("Không tìm thấy ffmpeg tại đường dẫn mặc định.")
    print("Vui lòng cài ffmpeg hoặc sửa biến ffmpeg_path trong file này.")
    sys.exit(1)

print(f"Đang chuyển đổi {input_file} sang {output_file}...")
subprocess.run(
    [ffmpeg_path, "-y", "-i", str(input_file), "-vn", str(output_file)],
    check=True,
)
print(f"Đã chuyển xong: {output_file}")