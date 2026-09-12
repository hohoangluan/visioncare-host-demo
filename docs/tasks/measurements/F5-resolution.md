# F5 — độ phân giải ảnh, đo trên camera thật

Sinh bằng `python tools/bench_resolution.py --report`. Thời gian đẩy quy đổi ở **24.3 KB/s** — tốc độ board đo được với gói 512 B + NoDelay, đúng cách `/process` ghi lên socket.

🔴 Cột kết quả chức năng là để NGƯỜI đối chiếu với cảnh thật. Tool không biết câu trả lời đúng là gì.

## Cảnh `thu-nghiem`

| tầng | pixel | JPEG | đẩy @24.3 KB/s | chụp | độ nét | độ sáng |
|---|---|---|---|---|---|---|
| VGA | 640x480 | 21,153 B | 850 ms | 946 ms | 156.0 | 121.0 |
| SVGA | 800x600 | 30,503 B | 1,226 ms | 1,044 ms | 151.8 | 119.9 |
| XGA | 1024x768 | 43,020 B | 1,729 ms | 524 ms | 80.8 | 127.5 |
| HD | 1280x720 | 47,892 B | 1,925 ms | 1,179 ms | 67.0 | 112.5 |
| SXGA | 1280x1024 | 63,964 B | 2,571 ms | 643 ms | 53.9 | 127.1 |
| UXGA | 1600x1200 | 90,792 B | 3,649 ms | 796 ms | 55.2 | 125.3 |

