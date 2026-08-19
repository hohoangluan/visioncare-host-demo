import json
import logging
import sys
import time
from pathlib import Path

# Fix Windows console encoding for UTF-8 Vietnamese characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
import config
from pipeline import tts
from services import visioncare_client
from handlers import navigation, phone, ride, music

logging.basicConfig(level=logging.WARNING)

config.VISIONCARE_CLIENT_TOKEN = "f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY"
config.VISIONCARE_DEVICE_ID = "glasses-123"
visioncare_client.reset_client()


def benchmark_ai_features():
    print("=" * 80)
    print("1. ĐO ĐỘ TRỄ AI FEATURES (TTFB - TIME TO FIRST AUDIO CHUNK TRẢ VỀ CHO KÍNH)")
    print("=" * 80)

    ai_cases = [
        ("Chat (Trò chuyện / Hỏi giờ)", None, "Bây giờ là mấy giờ rồi"),
        ("OCR (Đọc chữ)", "tests/fixtures/ocr_screenshot.png", "Đọc chữ trong ảnh giúp tôi"),
        ("Miêu tả không gian (Space)", "tests/fixtures/space_room.jpg", "Miêu tả không gian phía trước cho tôi"),
        ("Tìm đồ vật (Find Object)", "tests/fixtures/find_snack.jpg", "Gói bánh của tôi ở đâu"),
        ("Đọc tiền (Read Money)", "tests/fixtures/money_notes.jpg", "Tờ tiền này mệnh giá bao nhiêu"),
    ]

    for name, img_path, text in ai_cases:
        wav_in = tts.synthesize(text)
        files = {"audio": ("cmd.wav", wav_in, "audio/wav")}
        if img_path and Path(img_path).exists():
            files["image"] = (Path(img_path).name, Path(img_path).read_bytes(), "image/jpeg")

        t0 = time.monotonic()
        ttfb = None
        chunks = []

        with httpx.stream("POST", "http://127.0.0.1:8000/process", files=files, timeout=60) as resp:
            for chunk in resp.iter_bytes():
                if ttfb is None:
                    ttfb = time.monotonic() - t0
                chunks.append(chunk)

        t_total = time.monotonic() - t0
        body = b"".join(chunks)
        audio_dur = len(body) / 2 / 16000 if len(body) > 0 else 0.0

        print(f"[{name}]")
        print(f"  -> TTFB (Gói âm thanh đầu tiên về kính): {ttfb:.3f} s  ({ttfb * 1000:.0f} ms)")
        print(f"  -> Tổng thời gian xử lý toàn bộ response: {t_total:.3f} s")
        print(f"  -> Độ dài âm thanh câu trả lời:           {audio_dur:.2f} s")
        print(f"  -> Dung lượng gói dữ liệu audio:          {len(body):,} bytes")
        print("-" * 80)


def benchmark_phone_actions():
    print("\n" + "=" * 80)
    print("2. ĐO ĐỘ TRỄ THAO TÁC ĐIỆN THOẠI (PHONE ACTION HANDLERS & COMPLETION NOTIFICATION)")
    print("=" * 80)

    # (Tên action, hàm handler, kwargs)
    action_cases = [
        ("Dẫn đường (Navigation Start)", lambda: navigation.handle_start(b"", "chỉ đường đến Bưu điện", {"destination": "Bưu điện TP.HCM"})),
        ("Gọi điện thoại (Contact Call)", lambda: phone.handle_contact(b"", "gọi cho Nguyễn Văn A", {"contact_name": "Nguyễn Văn A"})),
        ("Gọi cấp cứu (Emergency Call)", lambda: phone.handle_emergency(b"", "gọi cấp cứu", {})),
        ("Báo giá xe (Ride Quote)", lambda: ride.handle_quote(b"", "đặt xe đi Bách Khoa", {"destination": "Đại học Bách Khoa TP.HCM"})),
        ("Xác nhận đặt xe (Ride Confirm)", lambda: ride.handle_confirm(b"", "xác nhận đặt xe", {"confirm": True})),
        ("Phát nhạc (Music Play)", lambda: music.handle_play(b"", "mở bài Nơi này có anh", {"song": "Nơi này có anh - Sơn Tùng M-TP"})),
        ("Chỉnh âm lượng (Music Volume)", lambda: music.handle_volume(b"", "tăng âm lượng", {"direction": "up"})),
        ("Dừng nhạc (Music Stop)", lambda: music.handle_stop(b"", "tắt nhạc", {})),
    ]

    for name, handler_fn in action_cases:
        t0 = time.monotonic()
        gen = handler_fn()
        
        # Mảnh 1: Thông báo xác nhận ngay tức thì cho người dùng nghe (ví dụ "Đang mở chỉ đường...")
        t_first = None
        first_speech = ""
        second_speech = ""

        try:
            first_speech = next(gen)
            t_first = time.monotonic() - t0
        except StopIteration:
            pass

        # Mảnh 2: Chờ thực hiện action trên điện thoại / poll kết quả hoàn thành từ Host
        try:
            for piece in gen:
                second_speech += piece
        except Exception as exc:
            second_speech = f"[Error: {exc}]"

        t_total = time.monotonic() - t0

        print(f"[{name}]")
        print(f"  -> Thời gian thông báo câu chữ đầu tiên (First Notice): {t_first:.3f} s  ({t_first * 1000:.0f} ms)" if t_first is not None else "  -> Không có câu chữ đầu")
        print(f"  -> Trấn an ban đầu: {first_speech.strip()!r}")
        print(f"  -> Tổng thời gian tới khi hoàn tất & thông báo kết quả: {t_total:.3f} s")
        print(f"  -> Kết quả/Thông báo cuối: {second_speech.strip()!r}")
        print("-" * 80)


if __name__ == "__main__":
    benchmark_ai_features()
    benchmark_phone_actions()
