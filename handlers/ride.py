"""Đặt xe: hỏi lại điểm đến trước, rồi mới mở ứng dụng đặt xe.

Điểm đến đi qua STT nên có thể sai — "Bách Khoa" thành "Bát Khoa". Gửi thẳng
lệnh đặt xe với một địa điểm nghe nhầm là đưa người khiếm thị tới nhầm chỗ, nên
lượt đầu chỉ đọc lại điểm đến và chờ người dùng xác nhận.
"""

from collections.abc import Iterator

from handlers import action_flow, chat, slots

_ASK_DESTINATION = slots.SLOTS["ride_destination"].ask
_CONFIRM_HINT = "Nói xác nhận để đặt, hoặc nói lại điểm đến."

# Điểm đến đã được đọc lại và xác nhận ở lượt trước, không nhắc lại nữa.
_QUOTE_ACK = "Đang gọi xe."
_OPENING_RIDE_APP = (
    "Đang mở ứng dụng đặt xe. Sau khi mở, bạn còn phải chạm một lần vào nút "
    "đặt xe ở cuối màn hình."
)

_CANCELLED = "Đã hủy, không đặt xe nữa."
_NOTHING_TO_CONFIRM = "Chưa có chuyến nào để xác nhận, bạn hãy nói điểm đến trước."
_LOCATION_UNAVAILABLE = (
    "Chưa xác định được vị trí của bạn nên chưa thể mở ứng dụng đặt xe. "
    "Bạn hãy bật định vị trên điện thoại rồi thử lại."
)
_DESTINATION_UNVERIFIED = (
    "Chưa xác định được tọa độ chính xác của điểm đến nên tôi chưa mở ứng dụng "
    "đặt xe, để tránh đưa bạn tới nhầm chỗ."
)
_WAITING_IN_APP = (
    "Ứng dụng Grab đang chờ bạn xác nhận. Tôi không theo dõi được chuyến xe sau "
    "khi bàn giao; bạn vẫn phải kiểm tra điểm đón, điểm đến và chạm nút đặt xe."
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
    _CONFIRM_HINT,
    _QUOTE_ACK,
    _OPENING_RIDE_APP,
    _CANCELLED,
    _NOTHING_TO_CONFIRM,
    _LOCATION_UNAVAILABLE,
    _DESTINATION_UNVERIFIED,
    _WAITING_IN_APP,
)


def _destination_payload(params: dict) -> dict:
    destination = params.get("destination")
    if isinstance(destination, dict):
        payload = dict(destination)
    else:
        payload = {"address": str(destination or "").strip()}
    if params.get("destination_lat") is not None:
        payload["lat"] = params["destination_lat"]
    if params.get("destination_lng") is not None:
        payload["lng"] = params["destination_lng"]
    return payload


def _open_ride_app(destination: dict, current_location: dict) -> Iterator[str]:
    yield from action_flow.run_action(
        "ride_quote",
        "api/v1/service/ride/quote",
        {
            "current_location": current_location,
            "destination": destination,
        },
        ack=_QUOTE_ACK,
        failure=(
            f"Không thể mở ứng dụng đặt xe đi {destination.get('address')}, "
            "vui lòng thử lại."
        ),
        progress=(
            f"Vẫn đang tìm xe đi {destination.get('address')}.",
            _OPENING_RIDE_APP,
        ),
    )


def handle_quote(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    destination = _destination_payload(params)

    if not destination.get("address"):
        yield _ASK_DESTINATION
        return

    if chat.get_current_location() is None:
        yield _LOCATION_UNAVAILABLE
        return

    # R1/Farefeed chưa có: lượt đầu vẫn chỉ đọc lại điểm đến, nhưng dùng Pending
    # chuẩn thay cho chuỗi tự do. Pending select TTL 45s của bảng giá thuộc R4
    # chỉ được tạo khi có services[] thật; tuyệt đối không dựng giá giả ở đây.
    question = (
        f"Bạn muốn đặt xe đi {destination['address']}, đúng không? "
        f"{_CONFIRM_HINT}"
    )
    action_flow.set_pending(
        slot="ride_destination",
        intent="ride_confirm",
        known={"destination": destination},
        question=question,
        kind="confirm",
    )
    yield question


def handle_confirm(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    confirm = params.get("confirm", True)

    if not confirm:
        action_flow.clear_pending()
        action_flow.forget("quote_id")
        yield _CANCELLED
        return

    pending = action_flow.get_pending()
    known = pending.known if pending is not None else {}
    destination = _destination_payload({**known, **params})
    if destination.get("address"):
        current_location = chat.get_current_location()
        if current_location is None:
            yield _LOCATION_UNAVAILABLE
            return
        # P6 chưa có geocoder và app hiện còn fallback toạ độ. Fail closed:
        # địa chỉ dạng chữ không bao giờ được biến thành một điểm đến mặc định.
        if destination.get("lat") is None or destination.get("lng") is None:
            yield _DESTINATION_UNVERIFIED
            return
        action_flow.clear_pending()
        yield from _open_ride_app(destination, current_location)
        return

    # Không có điểm đến đang chờ: hoặc người dùng nói "xác nhận" trước khi đặt,
    # hoặc chuyến đã mở trong app và phần xác nhận nằm ở màn hình Grab, không
    # phải ở đây.
    if action_flow.recall("quote_id"):
        yield _WAITING_IN_APP
        return

    yield _NOTHING_TO_CONFIRM
