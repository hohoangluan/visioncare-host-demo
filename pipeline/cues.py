"""Bảng cue: câu cố định phát từ flash kính thay vì qua TTS (§4 nguyên tắc 4, §13).

Server chỉ gửi mã (`X-Cue: a,b` hoặc `{"t":"cue","id":...}`); kính phát clip đã
nằm sẵn trong flash nên tiếng ra sau đúng một chuyến mạng, không chờ tổng hợp.

Kính cũ không khai `X-Cue-Version` (hoặc khai bản thấp hơn) thì không có clip:
`fallback_text()` đổi cue thành câu nói, và câu đó đã dựng sẵn qua
`pipeline/phrases.py` (nằm trong `STATIC_SPEECH`) nên vẫn phát ngay.

Đổi chữ của một cue là đổi clip trong flash -> phải tăng `CUE_VERSION` và sinh
lại clip bằng `tools/make_cue_clips.py`.
"""

CUE_VERSION = 2

# id -> câu nói (cũng là chữ dùng để sinh clip). `None` = âm thanh, không phải lời.
CUES: dict[str, str | None] = {
    # chung
    "received": None,  # tiếng "tíc" khi nhả nút
    "system_busy": "Hệ thống đang bận, bạn vui lòng thử lại sau giây lát.",
    "no_speech": "Xin lỗi, tôi không nghe rõ, vui lòng nói lại.",
    "no_image": "Không nhận được ảnh từ kính, vui lòng thử lại.",
    # làn D: hỏi slot còn thiếu
    "ask_destination": "Bạn muốn đi đâu?",
    "ask_contact_name": "Bạn muốn gọi cho ai?",
    "ask_song": "Bạn muốn nghe bài hát nào?",
    "ask_ride_destination": "Bạn muốn đặt xe đi đâu?",
    "phone_pending": "Điện thoại vẫn đang thực hiện, tôi sẽ báo khi có kết quả.",
    "emergency_started": "Đang kích hoạt cuộc gọi khẩn cấp.",
    # làn B
    "ocr_start": "Đưa sách ra trước mặt.",
    "look_left": "Quay sang trái.",
    "look_right": "Quay sang phải.",
    "look_up": "Ngẩng lên.",
    "look_down": "Cúi xuống.",
    "look_around": "Chưa thấy chữ, quay đầu chậm.",
    "move_closer": "Lại gần hơn.",
    "move_away": "Lùi ra xa.",
    "hold_still": "Giữ yên.",
    "shutter": None,
    "ocr_no_text": "Không thấy chữ nào đọc được.",
    "ocr_nothing_to_reread": "Chưa có nội dung nào để đọc lại.",
    # làn C
    "hazard_1": None,
    "hazard_2": None,
    "hazard_3": None,
    "dir_left": "Bên trái.",
    "dir_center": "Phía trước.",
    "dir_right": "Bên phải.",
    "stop_now": "Dừng lại.",
    "nav_alert_on": "Đã bật cảnh báo.",
    "nav_alert_off": "Đã tắt cảnh báo.",
}

# Cue có lời -> chữ; cue chỉ là âm thanh thì không nói gì khi rơi về TTS.
STATIC_SPEECH: tuple[str, ...] = tuple(text for text in CUES.values() if text)


def fallback_text(cue_id: str) -> str | None:
    """Câu nói thay cho cue khi kính không có clip trong flash."""
    return CUES.get(cue_id)


def supported(cue_version: str | None) -> bool:
    """Kính có đủ clip của bảng cue này không."""
    try:
        return int(cue_version or "0") >= CUE_VERSION
    except ValueError:
        return False
