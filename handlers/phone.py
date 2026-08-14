from collections.abc import Iterator

from handlers.action_flow import run_action

_ASK_CONTACT = "Bạn muốn gọi cho ai? Vui lòng nói lại kèm tên người cần gọi."
_CONNECTING = "Đang kết nối cuộc gọi, bạn chờ một chút."

_EMERGENCY_ACK = "Đang kích hoạt cuộc gọi khẩn cấp."
_EMERGENCY_FAILURE = "Không thể phát cuộc gọi khẩn cấp, vui lòng kiểm tra kết nối."
_EMERGENCY_PROGRESS = (
    "Đang lấy vị trí và gọi số khẩn cấp, bạn giữ máy.",
    "Vẫn đang kết nối cuộc gọi khẩn cấp, bạn giữ máy.",
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio. Riêng
# nhóm khẩn cấp thì dựng sẵn là bắt buộc chứ không phải tối ưu: đó là lúc không
# được để người dùng chờ thêm một giây nào cho việc tổng hợp giọng.
STATIC_SPEECH: tuple[str, ...] = (
    _ASK_CONTACT,
    _CONNECTING,
    _EMERGENCY_ACK,
    _EMERGENCY_FAILURE,
    *_EMERGENCY_PROGRESS,
)


def handle_contact(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    name = params.get("contact_name")

    # Không gọi bừa: fallback "người thân" trước đây khiến một câu nghe nhầm
    # thành contact_call vẫn đi tra danh bạ với một cái tên không ai nói ra.
    if not name:
        yield _ASK_CONTACT
        return

    yield from run_action(
        "contact_call",
        "api/v1/service/contact/call",
        {"name": name},
        ack=f"Đang tìm số của {name}.",
        failure=f"Không thể thực hiện cuộc gọi cho {name}, vui lòng thử lại.",
        progress=(
            f"Vẫn đang tìm {name} trong danh bạ.",
            _CONNECTING,
        ),
    )


def handle_emergency(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    number = params.get("emergency_number")

    payload = {}
    if number:
        payload["number"] = number

    yield from run_action(
        "emergency_call",
        "api/v1/service/emergency/call",
        payload,
        ack=_EMERGENCY_ACK,
        failure=_EMERGENCY_FAILURE,
        progress=_EMERGENCY_PROGRESS,
    )
