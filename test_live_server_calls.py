import json
import logging
import sys
import urllib.request
import urllib.error

# Fix Windows console encoding for UTF-8 Vietnamese characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
from services import visioncare_client
from handlers import navigation, phone, ride, music

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_live")

# Live server credentials
config.VISIONCARE_CLIENT_TOKEN = "f23ChvjGZt_WYrY-A8eJAyxO5LVEF_TGujmE7F_gRAY"
config.VISIONCARE_DEVICE_ID = "glasses-123"
visioncare_client.reset_client()

DEVICE_CLIENT_TOKEN = "_W7kNZRwdQC9jawhJr7ji_TJ6JzUI5igkHQrE6oAQKE"


def test_health():
    url = f"{config.VISIONCARE_HOST_URL}/health/live"
    req = urllib.request.Request(url, headers={"User-Agent": "VisionCare-Glasses/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[HEALTH CHECK] GET {url} -> {resp.status}: {data}")
            return resp.status == 200
    except Exception as exc:
        print(f"[HEALTH CHECK FAILED] {exc}")
        return False


def pair_glasses():
    url = f"{config.VISIONCARE_HOST_URL}/api/v1/device/glasses/link"
    payload = json.dumps({"user_id": "user-100", "device_id": config.VISIONCARE_DEVICE_ID}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {DEVICE_CLIENT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "VisionCare-Glasses/1.0",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[GLASSES PAIRING] POST {url} -> {resp.status}: {data}")
            return True
    except Exception as exc:
        print(f"[GLASSES PAIRING FAILED] {exc}")
        return False


def test_live_calls():
    print(f"\n=== STARTING LIVE API CALLS TO HOST {config.VISIONCARE_HOST_URL}/ ===")
    
    test_cases = [
        ("Navigation Start", lambda: list(navigation.handle_start(b"", "chỉ đường đến Bưu điện Thành phố", {"destination": "Bưu điện Thành phố Hồ Chí Minh"}))),
        ("Navigation Stop", lambda: list(navigation.handle_stop(b"", "dừng chỉ đường", {}))),
        ("Contact Call", lambda: list(phone.handle_contact(b"", "gọi cho Nguyễn Văn A", {"contact_name": "Nguyễn Văn A"}))),
        ("Emergency Call", lambda: list(phone.handle_emergency(b"", "gọi cấp cứu khẩn cấp", {}))),
        ("Ride Quote", lambda: list(ride.handle_quote(b"", "đặt xe đi Bách Khoa", {"destination": "Đại học Bách Khoa TP.HCM"}))),
        ("Ride Confirm", lambda: list(ride.handle_confirm(b"", "xác nhận đặt xe", {"confirm": True}))),
        ("Music Play", lambda: list(music.handle_play(b"", "mở bài hát Nơi này có anh", {"song": "Nơi này có anh - Sơn Tùng M-TP"}))),
        ("Music Volume", lambda: list(music.handle_volume(b"", "tăng âm lượng", {"direction": "up"}))),
        ("Music Stop", lambda: list(music.handle_stop(b"", "tắt nhạc", {}))),
    ]

    results = []
    for name, fn in test_cases:
        print(f"\n--- Testing: {name} ---")
        try:
            output_pieces = fn()
            speech_output = "".join(output_pieces)
            print(f"Result Speech Output: '{speech_output}'")
            results.append((name, "SUCCESS", speech_output))
        except Exception as exc:
            print(f"Result Error: {exc}")
            results.append((name, "ERROR", str(exc)))

    print("\n" + "="*70)
    print("LIVE INTEGRATION TEST SUMMARY:")
    for name, status, res in results:
        print(f"  [{status}] {name:20s} -> {res}")
    print("="*70)


if __name__ == "__main__":
    health_ok = test_health()
    paired_ok = pair_glasses()
    test_live_calls()
