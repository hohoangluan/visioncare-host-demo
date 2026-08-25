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
    CALL_ANSWER = "call_answer"
    CALL_REJECT = "call_reject"

    # Dịch vụ Đặt xe / Grab
    RIDE_QUOTE = "ride_quote"
    RIDE_CONFIRM = "ride_confirm"

    # Dịch vụ Âm nhạc & Âm lượng
    MUSIC_PLAY = "music_play"
    MUSIC_STOP = "music_stop"
    MUSIC_VOLUME = "music_volume"

    # Canh vật cản thời gian thực (T24/W1). KHÁC `HAZARD` ở trên:
    #   HAZARD              hỏi một lần, trả lời một lần, theo lượt bấm nút
    #   HAZARD_WATCH_START  bật một chế độ chạy liên tục cho tới khi tắt
    # Hai thứ chạy song song, không loại trừ nhau.
    HAZARD_WATCH_START = "hazard_watch_start"
    HAZARD_WATCH_STOP = "hazard_watch_stop"

