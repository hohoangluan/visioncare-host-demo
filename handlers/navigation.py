from collections.abc import Iterator

from handlers.action_flow import forget, recall, run_action

_ASK_DESTINATION = "Bạn muốn đi đâu? Vui lòng nói lại kèm tên địa điểm."

# Địa chỉ nằm ở câu kết quả phía sau — đó mới là địa chỉ điện thoại thật sự mở,
# nên nhắc ở đây nữa chỉ làm câu nói dài gấp đôi.
_START_ACK = "Đang mở chỉ đường."
_OPENING_MAP = "Đang mở bản đồ trên điện thoại, bạn chờ một chút."

_NOTHING_TO_STOP = "Hiện không có lộ trình nào đang chạy để dừng."
_STOP_ACK = "Đang dừng chỉ đường."
_STOP_FAILURE = "Không thể dừng điều hướng, vui lòng thử lại."
_STOP_PROGRESS = ("Vẫn đang dừng chỉ đường, bạn chờ một chút.",)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
    _ASK_DESTINATION,
    _START_ACK,
    _OPENING_MAP,
    _NOTHING_TO_STOP,
    _STOP_ACK,
    _STOP_FAILURE,
    *_STOP_PROGRESS,
)


def handle_start(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    destination = params.get("destination")

    # Không bịa điểm đến. Trước đây thiếu `destination` thì rơi về chuỗi
    # "điểm đến yêu cầu" và vẫn gửi lệnh, nên một câu bị nghe nhầm thành
    # nav_start làm điện thoại bắt đầu dẫn đường tới một nơi không ai nhắc tới.
    if not destination:
        yield _ASK_DESTINATION
        return

    yield from run_action(
        "navigation_start",
        "api/v1/service/navigation/start",
        {"destination": {"address": destination}},
        ack=_START_ACK,
        failure=f"Không thể bắt đầu điều hướng đến {destination}, vui lòng thử lại.",
        progress=(
            f"Vẫn đang tìm đường tới {destination}.",
            _OPENING_MAP,
        ),
    )


def handle_stop(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    nav_id = params.get("navigation_id") or recall("navigation_id")

    if not nav_id:
        from handlers.action_flow import mark_inactive
        mark_inactive("navigating")
        yield _NOTHING_TO_STOP
        return

    yield from run_action(
        "navigation_stop",
        "api/v1/service/navigation/stop",
        {"navigation_id": nav_id},
        ack=_STOP_ACK,
        failure=_STOP_FAILURE,
        progress=_STOP_PROGRESS,
    )
    forget("navigation_id")
