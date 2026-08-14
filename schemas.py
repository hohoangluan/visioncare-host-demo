class Intent:
    OCR = "ocr"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"
    HAZARD = "hazard"
    CHAT = "chat"  # không khớp luật nào -> trò chuyện tự do với Gemini
    UNKNOWN = "unknown"  # không nghe ra chữ nào -> hỏi lại thay vì đoán

    # Dịch vụ Vị trí & Điều hướng
    NAV_START = "nav_start"
    NAV_STOP = "nav_stop"

    # Dịch vụ Gọi điện & Khẩn cấp
    CONTACT_CALL = "contact_call"
    EMERGENCY_CALL = "emergency_call"

    # Dịch vụ Đặt xe / Grab
    RIDE_QUOTE = "ride_quote"
    RIDE_CONFIRM = "ride_confirm"

    # Dịch vụ Âm nhạc & Âm lượng
    MUSIC_PLAY = "music_play"
    MUSIC_STOP = "music_stop"
    MUSIC_VOLUME = "music_volume"

