"""Đổi kết quả cuối của một action thành câu nói tiếng Việt.

`202 Accepted` chỉ nói host đã nhận lệnh. Câu nói duy nhất người khiếm thị nghe
được phải phản ánh việc điện thoại có làm được hay không — "đang gọi cho Em iu"
khác hẳn "chưa gọi được, hãy bấm vào thông báo trên điện thoại", và trước đây cả
hai đều ra cùng một câu "đã gửi yêu cầu".
"""

from dataclasses import dataclass

_TIMEOUT_MESSAGE = "Điện thoại chưa phản hồi, vui lòng kiểm tra thông báo trên điện thoại."

# Mã lỗi nghiệp vụ -> câu nói. Mã không có ở đây rơi về câu chung của từng
# action, nên thiếu một mã mới không làm người dùng nghe mã lỗi thô.
#
# T20 (docs/tasks/measurements/P7-error-matrix.md, CONTRACTS.md mục 5.5) đối
# chiếu bảng này với mã app thật sự phát (`tests/fixtures/app_error_codes.txt`)
# và xoá 7 dòng MỒ CÔI — server có câu nhưng không nơi nào (app Android, server
# app 8001) từng phát mã đó lúc chạy, chỉ có tên trong tài liệu:
#   NAVIGATION_NOT_FOUND · NAVIGATION_ALREADY_STOPPED · QUOTE_NOT_FOUND
#   QUOTE_EXPIRED · NO_ACTIVE_PLAYBACK · MUSIC_ACCOUNT_NOT_CONNECTED
#   SMS_PERMISSION_DENIED
# và xoá GLASSES_DEVICE_NOT_LINKED — mã này CÓ nguồn thật (`errors.py:161`,
# server app) nhưng đi bằng HTTP 404 của chính lời gọi POST, không nằm trong
# `error.code` của operation, nên dòng ở đây chưa từng được tra tới. Bắt đúng
# chỗ là ở `handlers/action_flow.py:245-251` (VisionCareAPIError) — NGOÀI PHẠM
# VI file được sửa của T20, xem docs/tasks/reports/T20.md mục "Lệch với task
# file".
#
# 8 mã cuối bảng là T20 THÊM MỚI: app đã phát (fixture xác nhận) nhưng trước
# đây rơi vào `_GENERIC_FAILURE`/`_UNSPECIFIED_FAILURE` — câu chung, không nói
# người dùng phải làm gì.
_ERROR_SPEECH = {
    "DELIVERY_FAILED": "Không kết nối được với điện thoại, vui lòng mở ứng dụng trên điện thoại.",
    "CONTACT_NOT_FOUND": "Không tìm thấy người này trong danh bạ.",
    "MULTIPLE_CONTACTS_FOUND": "Có nhiều người trùng tên trong danh bạ, vui lòng nói rõ hơn.",
    "CONTACT_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền đọc danh bạ.",
    "CALL_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền gọi điện.",
    "EMERGENCY_CONTACT_NOT_CONFIGURED": "Chưa cài số liên hệ khẩn cấp trên điện thoại.",
    "SONG_NOT_FOUND": "Không tìm thấy bài hát này, vui lòng nói lại tên bài.",
    "PLAYBACK_STOP_FAILED": "Chưa dừng được nhạc, vui lòng thử lại.",
    # Không nói "hết hạn": đo trên máy thật, mã này về khi tài khoản là gói MIỄN
    # PHÍ, chứ không phải gói trả phí vừa hết hạn. Ứng dụng nhạc mở lên bình
    # thường nhưng từ chối nạp đúng bài được yêu cầu, vì gói miễn phí không cho
    # phép phát một bài chỉ định. Nói "hết hạn" khiến người dùng đi gia hạn một thứ họ
    # chưa từng mua; nói rõ nguyên nhân thì họ biết phải nâng cấp.
    "SUBSCRIPTION_INACTIVE": (
        "Tài khoản nghe nhạc đang dùng gói miễn phí nên không phát được bài chỉ định. "
        "Cần nâng cấp gói trả phí để nghe đúng bài."
    ),
    "CURRENT_LOCATION_UNAVAILABLE": "Không lấy được vị trí hiện tại.",
    "LOCATION_PERMISSION_DENIED": "Ứng dụng chưa được cấp quyền vị trí.",
    # Không đoán hộ một địa điểm gần đúng: nói thẳng là không tìm thấy để người
    # dùng đọc lại tên, còn hơn đưa họ tới nhầm chỗ.
    #
    # CHƯA QUYẾT (câu hỏi mở CONTRACTS mục 7 #7): P7-error-matrix.md xác nhận
    # app KHÔNG kiểm địa điểm hôm nay -> mã này KHÔNG có nguồn phát thật. Giữ
    # nguyên câu (không tự xoá — task file T20 nói rõ "không tự chọn (a) hay
    # (b)"), nhưng `_ERROR_POLICY` bên dưới xếp nó `retryable=False` cho tới khi
    # có quyết định, để không lỡ mở một đường hỏi lại cho một mã không ai phát.
    "INVALID_DESTINATION": "Không tìm thấy địa điểm này. Vui lòng nói lại tên địa điểm.",
    "NO_RIDE_AVAILABLE": "Hiện không có xe nào gần đây.",
    # Không có nguồn phát thật (app dùng deeplink Grab, không OAuth) nhưng GIỮ
    # có chủ đích: CONTRACTS mục 5.2 / T11 chốt để dành cho provider tương lai
    # có đăng nhập tài khoản riêng. Đây là NGOẠI LỆ được DoD cho phép, khác với
    # 7 mã mồ côi bị xoá ở trên.
    "RIDE_ACCOUNT_NOT_CONNECTED": "Chưa liên kết tài khoản đặt xe.",
    # --- 8 mã T20 thêm mới (P7-error-matrix.md mục 1.3 — "mã CÂM") ---
    "PLAYBACK_FAILED": "Chưa phát được bài hát này, vui lòng thử lại hoặc chọn bài khác.",
    # Dùng chung cho contact_call VÀ emergency_call (mã không phân biệt theo
    # operation) — ưu tiên cao nhất trong 8 mã này vì gồm cả ca gọi khẩn cấp
    # không quay số được (ActionRegistry.kt:460).
    "CALL_FAILED": "Không thực hiện được cuộc gọi này, vui lòng bấm ngay vào thông báo trên điện thoại.",
    "INVALID_VOLUME": "Không đổi được âm lượng vì giá trị không hợp lệ, vui lòng nói lại to hơn hoặc nhỏ hơn.",
    "NAVIGATION_START_FAILED": "Chưa mở được chỉ đường, vui lòng bấm vào thông báo trên điện thoại.",
    "NAVIGATION_STOP_FAILED": "Chưa dừng được chỉ đường, vui lòng thử lại.",
    "RIDE_CONFIRM_FAILED": "Chưa xác nhận được chuyến xe, vui lòng bấm vào thông báo trên điện thoại.",
    "INVALID_PARAMS": "Điện thoại báo thiếu thông tin để thực hiện, vui lòng thử lại.",
    "UNSUPPORTED_ACTION": "Điện thoại chưa hỗ trợ chức năng này, có thể ứng dụng cần được cập nhật.",
}


@dataclass(frozen=True)
class ErrorPolicy:
    """21.7 — phân loại một mã lỗi: câu nói, có đáng hỏi lại không, hỏi slot nào."""

    speech: str
    retryable: bool  # có đặt pending hỏi lại không (thi công thật ở T06)
    reask: tuple[str, str] | None = None  # (slot, intent) nếu retryable


# code -> (retryable, reask). Mã không có mặt ở đây là TERMINAL, reask=None —
# lựa chọn AN TOÀN mặc định (P7-error-matrix.md mục 4.2): chưa biết rõ hỏi lại
# có ích không thì đừng tự mở một pending.
#
# CHỈ điền reask cho 3 mã đã CHỐT thật ở CONTRACTS mục 5.5 / T06-slot-policy.md
# mục D4 (bảng `_ERROR_REASK` tương lai sống ở `handlers/action_flow.py`,
# KHÔNG phải file này — T06 sở hữu, T20 không đụng) — nguồn phát xác nhận VÀ
# slot/intent đích đã có tên chính thức. Không bịa thêm cặp (slot, intent) nào
# khác: đó là phạm vi thi công của T06, chưa tồn tại (T06 chưa chạy).
#
# INVALID_VOLUME và NAVIGATION_STOP_FAILED "về bản chất" có thể hỏi lại
# (volume_direction, và tự thử lại) nhưng P7-error-matrix.md mục 4.4 ghi rõ:
# ĐỂ retryable=False cho tới khi T06/D4 dựng xong đường hỏi lại — retryable=True
# mà chưa có nơi nào tiêu thụ nó chỉ là một lời hứa suông.
_RETRYABLE: dict[str, tuple[bool, tuple[str, str] | None]] = {
    "CONTACT_NOT_FOUND": (True, ("contact_name", "contact_call")),
    "MULTIPLE_CONTACTS_FOUND": (True, ("contact_name", "contact_call")),
    "SONG_NOT_FOUND": (True, ("song_title", "music_play")),
    "PLAYBACK_STOP_FAILED": (True, None),
    "CURRENT_LOCATION_UNAVAILABLE": (True, None),
}

# Bảng phân loại đầy đủ — MỌI mã trong `_ERROR_SPEECH` có một `ErrorPolicy`.
_ERROR_POLICY: dict[str, ErrorPolicy] = {
    code: ErrorPolicy(speech, *_RETRYABLE.get(code, (False, None)))
    for code, speech in _ERROR_SPEECH.items()
}

# 21.7 · NGUYÊN TẮC: không mã lỗi nào — kể cả mã bịa ra, chưa ai từng thấy —
# được rơi vào im lặng. Mọi mã không khớp `_ERROR_SPEECH`/`_ERROR_POLICY` (và
# không có `_GENERIC_FAILURE[operation]`) rơi về policy này.
_DEFAULT_POLICY = ErrorPolicy(
    speech=(
        "Điện thoại báo chưa làm được việc này và không nói rõ lý do. "
        "Vui lòng kiểm tra thông báo trên điện thoại."
    ),
    retryable=False,
    reask=None,
)

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
    _DEFAULT_POLICY.speech,
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
    return _GENERIC_FAILURE.get(operation, _DEFAULT_POLICY.speech)
