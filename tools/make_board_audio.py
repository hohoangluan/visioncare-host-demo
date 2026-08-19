"""Dựng bộ audio thử ĐÚNG định dạng board gửi lên: WAV IMA ADPCM 16 kHz mono.

Không có bản thu thật cho đủ 15 intent (`test_bang_am_thanh/` đang rỗng), nên
đọc câu lệnh bằng chính TTS của server rồi nén sang ADPCM. Không thay được bản
thu người thật cho việc đánh giá độ chính xác STT, nhưng cho việc ĐO TỐC ĐỘ thì
đủ: mỗi lượt đo vẫn đi trọn STT -> phân loại -> handler -> TTS -> ADPCM.

Chạy:  python tools/make_board_audio.py
Ra:    tools/board_audio/<intent>.wav  (+ in ra STT nghe lại được gì)
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import adpcm, stt, tts  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "board_audio")

# Một câu cho mỗi intent, viết như người dùng thật nói.
# Chọn câu mà STT nghe lại ĐÚNG (cột cuối khi chạy file này). Không phải để
# làm đẹp số liệu: nghe nhầm là request rơi sang intent khác, và lúc đó bảng đo
# ghi thời gian của một chức năng hoàn toàn khác dưới cái tên này. Ví dụ "Tắt
# nhạc." bị nghe thành "Cách nhạc" -> `unknown`, đo ra 0.9s mà tưởng là
# `music_stop`.
COMMANDS: dict[str, str] = {
    "ocr": "Đọc giúp tôi tài liệu này.",
    "find": "Giúp tôi tìm gói bánh.",
    "money": "Tờ tiền này là bao nhiêu?",
    "space": "Mô tả xung quanh tôi.",
    "hazard": "Phía trước có gì nguy hiểm không?",
    "chat": "Kể cho tôi một câu chuyện cười.",
    "nav_start": "Chỉ đường đến chợ Bến Thành.",
    "nav_stop": "Dừng chỉ đường lại.",
    "contact_call": "Gọi cho Nguyễn Văn A.",
    "emergency_call": "Gọi cấp cứu khẩn cấp.",
    "ride_quote": "Đặt xe đi đại học bách khoa.",
    "ride_confirm": "Xác nhận đặt xe.",
    "music_play": "Mở bài Nơi này có anh.",
    "music_stop": "Dừng phát nhạc.",
    "music_volume": "Tăng âm lượng.",
    # Không phải intent: câu vô nghĩa, để đo nhánh `unknown`.
    "unknown": "Bờ rào xanh lét quả nhiên.",
}


def _pcm16k(text: str) -> bytes:
    """Đọc `text` thành PCM 16-bit 16 kHz mono, cùng đường mà server dùng."""
    return b"".join(tts.synthesize_stream(text))


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    tts._load_tts()
    stt._load_asr()

    print(f"{'intent':<16} {'giây':>6} {'KB':>7}  nghe lại được")
    print("-" * 78)

    for name, text in COMMANDS.items():
        pcm = _pcm16k(text)
        samples = len(pcm) // 2

        blocks = adpcm.encode_blocks(pcm)
        wav = adpcm.wav_header(len(blocks), sample_count=samples) + blocks

        path = os.path.join(OUT_DIR, f"{name}.wav")
        with open(path, "wb") as f:
            f.write(wav)

        # Đọc lại bằng đúng đường STT của server: nếu chỗ này ra rác thì mọi số
        # đo end-to-end phía sau đều đo nhầm nhánh `unknown`.
        heard = stt.transcribe(wav)
        seconds = samples / adpcm.SAMPLE_RATE
        print(f"{name:<16} {seconds:>6.2f} {len(wav)/1024:>7.1f}  {heard!r}")


if __name__ == "__main__":
    main()
