"""Đặt xe: hỏi lại điểm đến trước, rồi mới mở ứng dụng đặt xe.

Điểm đến đi qua STT nên có thể sai — "Bách Khoa" thành "Bát Khoa". Gửi thẳng
lệnh đặt xe với một địa điểm nghe nhầm là đưa người khiếm thị tới nhầm chỗ, nên
lượt đầu chỉ đọc lại điểm đến và chờ người dùng xác nhận.
"""

from collections.abc import Iterator

from handlers.action_flow import forget, recall, remember, run_action

# Vị trí giả cho demo. Kính chưa có GPS nên chưa lấy được toạ độ thật; đổi sang
# vị trí thật khi phần cứng có module định vị.
_DEMO_CURRENT_LOCATION = {"lat": 10.7769, "lng": 106.7009}

_PENDING_DESTINATION = "pending_ride_destination"

_ASK_DESTINATION = "Bạn muốn đi đâu? Vui lòng nói lại kèm tên điểm đến."
_CONFIRM_HINT = "Nói xác nhận để đặt, hoặc nói lại điểm đến."

# Điểm đến đã được đọc lại và xác nhận ở lượt trước, không nhắc lại nữa.
_QUOTE_ACK = "Đang gọi xe."
_OPENING_RIDE_APP = "Đang mở ứng dụng đặt xe trên điện thoại, bạn chờ một chút."

_CANCELLED = "Đã hủy, không đặt xe nữa."
_NOTHING_TO_CONFIRM = "Chưa có chuyến nào để xác nhận, bạn hãy nói điểm đến trước."
_WAITING_IN_APP = (
    "Chuyến xe đang chờ bạn xác nhận trong ứng dụng. "
    "Vui lòng nhấn vào thông báo trên điện thoại và xác nhận điểm đón, điểm đến."
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
    _ASK_DESTINATION,
    _CONFIRM_HINT,
    _QUOTE_ACK,
    _OPENING_RIDE_APP,
    _CANCELLED,
    _NOTHING_TO_CONFIRM,
    _WAITING_IN_APP,
)


def _open_ride_app(destination: str) -> Iterator[str]:
    yield from run_action(
        "ride_quote",
        "api/v1/service/ride/quote",
        {
            "current_location": _DEMO_CURRENT_LOCATION,
            "destination": {"address": destination},
        },
        ack=_QUOTE_ACK,
        failure=f"Không thể mở ứng dụng đặt xe đi {destination}, vui lòng thử lại.",
        progress=(
            f"Vẫn đang tìm xe đi {destination}.",
            _OPENING_RIDE_APP,
        ),
    )


def handle_quote(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    destination = params.get("destination")

    if not destination:
        yield _ASK_DESTINATION
        return

    # Chưa gọi API ở lượt này: đọc lại đúng thứ nghe được để người dùng sửa nếu
    # sai, rồi mới đặt ở lượt sau khi họ nói "đúng rồi" / "xác nhận".
    remember(_PENDING_DESTINATION, destination)
    yield f"Bạn muốn đặt xe đi {destination}, đúng không? {_CONFIRM_HINT}"


def handle_confirm(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    confirm = params.get("confirm", True)
    pending = recall(_PENDING_DESTINATION)

    if not confirm:
        forget(_PENDING_DESTINATION)
        forget("quote_id")
        yield _CANCELLED
        return

    if pending:
        forget(_PENDING_DESTINATION)
        yield from _open_ride_app(pending)
        return

    # Không có điểm đến đang chờ: hoặc người dùng nói "xác nhận" trước khi đặt,
    # hoặc chuyến đã mở trong app và phần xác nhận nằm ở màn hình Grab, không
    # phải ở đây.
    if recall("quote_id"):
        yield _WAITING_IN_APP
        return

    yield _NOTHING_TO_CONFIRM
