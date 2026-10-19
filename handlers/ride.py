"""Đặt xe: `ride_quote` ở lượt "đặt xe đi X", `ride_confirm {quote_id, confirm}` ở lượt xác nhận/huỷ.

Điểm đến đi qua STT nên có thể sai — "Bách Khoa" thành "Bát Khoa". Làn D đã đọc lại điểm đến và chờ cửa sổ
huỷ (pending_action) trước khi các handler này chạy, nên không cần thêm một lượt "đúng không?" riêng.
"""

from collections.abc import Iterator

from handlers.action_flow import forget, recall, run_action

# Vị trí giả cho demo. Kính chưa có GPS nên chưa lấy được toạ độ thật; đổi sang
# vị trí thật khi phần cứng có module định vị.
_DEMO_CURRENT_LOCATION = {"lat": 10.7769, "lng": 106.7009}

_ASK_DESTINATION = "Bạn muốn đi đâu? Vui lòng nói lại kèm tên điểm đến."
_CONFIRM_HINT = "Nói xác nhận để đặt, hoặc nói lại điểm đến."
_CONFIRM_ACK = "Đang xác nhận chuyến xe."
_CANCEL_ACK = "Đang hủy chuyến xe."

# Điểm đến đã được làn D đọc lại, không nhắc lại nữa.
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
    _CONFIRM_ACK,
    _CANCEL_ACK,
)


def handle_quote(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Lượt "đặt xe đi X": gửi `ride_quote` NGAY ở lượt này (làn D đã đọc lại điểm đến và có cửa sổ huỷ).

    Trước đây lượt này chỉ nhớ điểm đến và lệnh đi ở lượt "xác nhận" — nhưng câu hỏi "đúng không?" bị vứt
    (kết quả làn D nền không được đọc) nên người dùng nghe "Đang tìm xe" mà chưa có gì được gửi (E2E 2026-10-19).
    Hợp đồng: `ride_quote` -> `quote_id`, rồi `ride_confirm {quote_id, confirm}` (huỷ = confirm false).
    """
    params = params or {}
    destination = params.get("destination")

    if not destination:
        yield _ASK_DESTINATION
        return

    forget("quote_id")  # báo giá mới thay báo giá cũ
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


def handle_confirm(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Lượt "xác nhận"/"huỷ": gửi `ride_confirm` với `quote_id` của báo giá vừa nhận."""
    params = params or {}
    confirm = params.get("confirm", True)
    quote_id = recall("quote_id")

    if not quote_id:
        # Chưa có báo giá nào (chưa đặt, hoặc báo giá chưa về/đã dùng): không có gì để xác nhận hay huỷ.
        yield _CANCELLED if not confirm else _NOTHING_TO_CONFIRM
        return

    forget("quote_id")  # dùng một lần: app báo QUOTE_ALREADY_USED nếu gửi lại
    yield from run_action(
        "ride_confirm",
        "api/v1/service/ride/confirm",
        {"quote_id": quote_id, "confirm": bool(confirm)},
        ack=_CONFIRM_ACK if confirm else _CANCEL_ACK,
        failure="Chưa gửi được yêu cầu đặt xe, vui lòng thử lại." if confirm else "Chưa hủy được chuyến xe, vui lòng thử lại.",
    )
