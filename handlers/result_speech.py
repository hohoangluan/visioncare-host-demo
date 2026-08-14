"""Đổi kết quả cuối của một action thành câu nói tiếng Việt.

`202 Accepted` chỉ nói host đã nhận lệnh. Câu nói duy nhất người khiếm thị nghe
được phải phản ánh việc điện thoại có làm được hay không — "đang gọi cho Em iu"
khác hẳn "chưa gọi được, hãy bấm vào thông báo trên điện thoại", và trước đây cả
hai đều ra cùng một câu "đã gửi yêu cầu".
"""

_TIMEOUT_MESSAGE = "Điện thoại chưa phản hồi, vui lòng kiểm tra thông báo trên điện thoại."

# Mã lỗi nghiệp vụ -> câu nói. Mã không có ở đây rơi về câu chung của từng
# action, nên thiếu một mã mới không làm người dùng nghe mã lỗi thô.
_ERROR_SPEECH = {
    "GLASSES_DEVICE_NOT_LINKED": "Kính chưa được ghép nối với tài khoản nào.",
    "DELIVERY_FAILED": "Không kết nối được với điện thoại, vui lòng mở ứng dụng trên điện thoại.",
    "CONTACT_NOT_FOUND": "Không tìm thấy người này trong danh bạ.",
    "MULTIPLE_CONTACTS_FOUND": "Có nhiều người trùng tên trong danh bạ, vui lòng nói rõ hơn.",
    "CONTACT_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền đọc danh bạ.",
    "CALL_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền gọi điện.",
    "SMS_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền gửi tin nhắn.",
    "EMERGENCY_CONTACT_NOT_CONFIGURED": "Chưa cài số liên hệ khẩn cấp trên điện thoại.",
    "NO_ACTIVE_PLAYBACK": "Hiện không có bài hát nào đang phát, không cần dừng.",
    "SONG_NOT_FOUND": "Không tìm thấy bài hát này, vui lòng nói lại tên bài.",
    "PLAYBACK_STOP_FAILED": "Chưa dừng được nhạc, vui lòng thử lại.",
    "MUSIC_ACCOUNT_NOT_CONNECTED": "Chưa liên kết tài khoản nghe nhạc.",
    "SUBSCRIPTION_INACTIVE": "Gói nghe nhạc đã hết hạn.",
    "CURRENT_LOCATION_UNAVAILABLE": "Không lấy được vị trí hiện tại.",
    "LOCATION_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền vị trí.",
    # Không đoán hộ một địa điểm gần đúng: nói thẳng là không tìm thấy để người
    # dùng đọc lại tên, còn hơn đưa họ tới nhầm chỗ.
    "INVALID_DESTINATION": "Không tìm thấy địa điểm này. Vui lòng nói lại tên địa điểm.",
    "NAVIGATION_NOT_FOUND": "Hiện không có lộ trình nào đang chạy.",
    "NAVIGATION_ALREADY_STOPPED": "Chỉ đường đã dừng từ trước.",
    "QUOTE_NOT_FOUND": "Không tìm thấy báo giá chuyến đi.",
    "QUOTE_EXPIRED": "Báo giá chuyến đi đã hết hạn.",
    "NO_RIDE_AVAILABLE": "Hiện không có xe nào gần đây.",
    "RIDE_ACCOUNT_NOT_CONNECTED": "Chưa liên kết tài khoản đặt xe.",
}

# Câu nói khi action thất bại mà mã lỗi không có trong bảng trên.
_GENERIC_FAILURE = {
    "contact_call": "Chưa gọi được, vui lòng bấm vào thông báo trên điện thoại.",
    "emergency_call": "Chưa phát được cuộc gọi khẩn cấp, vui lòng bấm vào thông báo trên điện thoại.",
    "music_play": (
        "Đã mở ứng dụng nhạc nhưng chưa phát được. "
        "Vui lòng nhấn vào thông báo trên điện thoại rồi bấm nút phát."
    ),
    "music_stop": "Chưa dừng được nhạc, vui lòng thử lại.",
    "music_volume": "Chưa thay đổi được âm lượng, vui lòng thử lại.",
    "navigation_start": "Chưa bắt đầu được chỉ đường, vui lòng bấm vào thông báo trên điện thoại.",
    "navigation_stop": "Chưa dừng được chỉ đường.",
    "ride_quote": "Chưa mở được ứng dụng đặt xe, vui lòng bấm vào thông báo trên điện thoại.",
    "ride_confirm": "Chưa gửi được yêu cầu đặt xe, vui lòng bấm vào thông báo trên điện thoại.",
}


# Câu nhắc cho các action mở ứng dụng khác trên điện thoại. Chúng đi qua
# notification full-screen-intent: màn hình tắt thì Android tự mở, còn khi người
# dùng đang cầm máy thì hệ điều hành cố ý chỉ hiện heads-up để không cắt ngang —
# lúc đó phải chạm. Cuộc gọi không nằm trong nhóm này vì đi qua
# TelecomManager.placeCall, không phải mở activity.
_TAP_NOTIFICATION = "Nếu màn hình đang mở, vui lòng nhấn vào thông báo trên điện thoại."

# Câu báo thành công không phụ thuộc kết quả trả về. Tách thành hằng số thay vì
# viết thẳng trong `_success_speech` để `pipeline/phrases.py` dựng sẵn audio cho
# chúng — đây là những câu được nói nhiều nhất trong cả demo.
_NAV_OPENED = "Đã mở chỉ đường đi bộ."
# Bản ghép sẵn cho trường hợp không có địa chỉ. Hai câu này ngắn nên lúc chạy
# `_sentences()` gộp chúng lại thành MỘT câu; dựng sẵn từng câu rời thì khoá
# không bao giờ trùng, nên phải dựng đúng bản ghép mà người dùng thật sự nghe.
_NAV_OPENED_WITH_TAP = f"{_NAV_OPENED} {_TAP_NOTIFICATION}"
_NAV_STOPPED = "Đã dừng chỉ đường."
_MUSIC_STOPPED = "Đã dừng phát nhạc."
_VOLUME_CHANGED = "Đã thay đổi âm lượng."
_RIDE_CANCELLED = "Đã hủy chuyến xe."
_DONE = "Đã thực hiện xong."
# Action thất bại mà cả mã lỗi lẫn tên action đều không có câu riêng.
_UNSPECIFIED_FAILURE = "Chưa thực hiện được, vui lòng thử lại."

# Cố ý không đọc giá, loại xe hay thời gian chờ. Trên Grab thật, giá chỉ hiện
# sau khi người dùng xác nhận điểm đón, mà app không đi qua được bước xác nhận
# đó — nên mọi con số ở đây là ước lượng của server, đọc lên là nói một cái giá
# không ai cam kết.
_RIDE_APP_OPENED = (
    "Đã mở ứng dụng đặt xe. Vui lòng nhấn vào thông báo trên điện thoại, "
    "kiểm tra lại điểm đón và điểm đến trong ứng dụng rồi xác nhận để đặt xe."
)
_RIDE_REQUESTED = (
    "Đã gửi yêu cầu đặt xe. Vui lòng nhấn vào thông báo trên điện thoại và "
    "xác nhận điểm đón, điểm đến trong ứng dụng để hoàn tất."
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
    _TIMEOUT_MESSAGE,
    _TAP_NOTIFICATION,
    _NAV_OPENED_WITH_TAP,
    _NAV_STOPPED,
    _MUSIC_STOPPED,
    _VOLUME_CHANGED,
    _RIDE_CANCELLED,
    _RIDE_APP_OPENED,
    _RIDE_REQUESTED,
    _DONE,
    _UNSPECIFIED_FAILURE,
    *_ERROR_SPEECH.values(),
    *_GENERIC_FAILURE.values(),
)


def _success_speech(operation: str, result: dict) -> str:
    if operation == "contact_call":
        return f"Đang gọi cho {result.get('contact_name', 'người liên hệ')}."

    if operation == "emergency_call":
        sms = "đã gửi tin nhắn vị trí" if result.get("sms_sent") else "chưa gửi được tin nhắn vị trí"
        return f"Đang gọi khẩn cấp tới {result.get('contact', 'số đã cài')}, {sms}."

    if operation == "music_play":
        title = result.get("title") or "bài hát"
        artist = result.get("artist")
        if artist and artist != "Unknown":
            return f"Đã tìm được bài {title} của {artist}, đang phát."
        return f"Đã tìm được bài {title}, đang phát."

    if operation == "navigation_start":
        destination = result.get("destination") or {}
        address = destination.get("address") if isinstance(destination, dict) else None
        if not address:
            return _NAV_OPENED_WITH_TAP
        return f"Đã mở chỉ đường đi bộ đến {address}. {_TAP_NOTIFICATION}"

    if operation == "music_stop":
        return _MUSIC_STOPPED

    if operation == "music_volume":
        level = result.get("level")
        if isinstance(level, int):
            return f"Âm lượng hiện ở mức {level} phần trăm."
        return _VOLUME_CHANGED

    if operation == "navigation_stop":
        return _NAV_STOPPED

    if operation == "ride_quote":
        return _RIDE_APP_OPENED

    if operation == "ride_confirm":
        if result.get("ride_status") == "cancelled":
            return _RIDE_CANCELLED
        return _RIDE_REQUESTED

    return _DONE


def speak_result(operation: str, data: dict | None) -> str:
    """Câu nói cuối cùng cho một action, dựa trên trạng thái thật từ điện thoại.

    `data` là phần `data` của `GET /api/v1/requests/{id}`, hoặc `None` khi chờ
    hết giờ mà request vẫn `processing`.
    """
    if data is None:
        return _TIMEOUT_MESSAGE

    state = data.get("request_state")
    if state == "succeeded":
        result = data.get("result")
        return _success_speech(operation, result if isinstance(result, dict) else {})

    if state == "timed_out":
        return _TIMEOUT_MESSAGE

    error = data.get("error") or {}
    code = error.get("code", "")
    if code in _ERROR_SPEECH:
        return _ERROR_SPEECH[code]
    return _GENERIC_FAILURE.get(operation, _UNSPECIFIED_FAILURE)
