from collections.abc import Iterator

from handlers import action_flow
from handlers.slots import SLOTS, should_readback

# Ack đọc ngay tên người dùng vừa nói để họ kịp phát hiện STT nghe sai trước khi
# Maps mở. Kết quả phía sau vẫn đọc địa chỉ điện thoại thực sự đã xác nhận.
_OPENING_MAP = "Đang mở bản đồ trên điện thoại, bạn chờ một chút."

_NOTHING_TO_STOP = "Hiện không có lộ trình nào đang chạy để dừng."
_STOP_ACK = "Đang dừng chỉ đường."
_STOP_FAILURE = "Không thể dừng điều hướng, vui lòng thử lại."
_STOP_PROGRESS = ("Vẫn đang dừng chỉ đường, bạn chờ một chút.",)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
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
        spec = SLOTS["destination"]
        action_flow.set_pending(
            slot="destination",
            intent="nav_start",
            known={},
            question=spec.ask,
            kind=spec.kind,
        )
        yield spec.ask
        return

    # D3 — điểm đến nghe không chắc phải được đọc lại trước khi Maps mở. Marker
    # nội bộ ngăn câu "ừ" dispatch lại rồi tự tạo một vòng confirm mới.
    if (
        not params.get("destination_confirmed")
        and should_readback("destination", params.get("slot_confidence"))
    ):
        question = f"Bạn muốn mở chỉ đường tới {destination}, đúng không?"
        confirmed = dict(params)
        confirmed["destination"] = destination
        confirmed["destination_confirmed"] = True
        action_flow.set_pending(
            slot="destination",
            intent="nav_start",
            known=confirmed,
            question=question,
            kind="confirm",
        )
        yield question
        return

    yield from action_flow.run_action(
        "navigation_start",
        "api/v1/service/navigation/start",
        {"destination": {"address": destination}},
        ack=f"Đang mở chỉ đường tới {destination}.",
        failure=f"Không thể bắt đầu điều hướng đến {destination}, vui lòng thử lại.",
        progress=(
            f"Vẫn đang tìm đường tới {destination}.",
            _OPENING_MAP,
        ),
    )


def handle_stop(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    nav_id = params.get("navigation_id") or action_flow.recall("navigation_id")

    if not nav_id:
        action_flow.mark_inactive("navigating")
        yield _NOTHING_TO_STOP
        return

    yield from action_flow.run_action(
        "navigation_stop",
        "api/v1/service/navigation/stop",
        {"navigation_id": nav_id},
        ack=_STOP_ACK,
        failure=_STOP_FAILURE,
        progress=_STOP_PROGRESS,
    )
    action_flow.forget("navigation_id")
