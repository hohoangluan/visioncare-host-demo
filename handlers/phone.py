from collections.abc import Iterator
import logging

from handlers import action_flow
from handlers.contact_match import choose_candidate
from handlers.slots import SLOTS, should_readback

_CONNECTING = "Đang kết nối cuộc gọi, bạn chờ một chút."
_CONTACT_RETRY_STRATEGY = (
    "Tôi vẫn chưa tìm thấy người phù hợp. Bạn hãy nói tên theo cách đang lưu trong danh bạ."
)

logger = logging.getLogger("blind_assist")

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
    _CONNECTING,
    _CONTACT_RETRY_STRATEGY,
    _EMERGENCY_ACK,
    _EMERGENCY_FAILURE,
    *_EMERGENCY_PROGRESS,
)


def handle_contact(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = dict(params or {})
    name = params.get("contact_name") or params.get("name")

    # D6 — lượt chọn bằng tên: pending `select` vẫn còn khi router không khớp
    # số thứ tự. Dùng fuzzy trên đúng danh sách host vừa trả, không tìm bừa lại
    # toàn danh bạ. Router xử lý đường ordinal trước và đưa thẳng candidate vào
    # params, nên nhánh này chỉ dành cho câu như "gọi Nguyệt".
    pending = action_flow.get_pending()
    if (
        pending is not None
        and pending.slot == "contact_selection"
        and pending.kind == "select"
        and name
    ):
        chosen = choose_candidate(str(name), pending.candidates)
        if chosen is None:
            yield pending.question
            return
        action_flow.clear_pending()
        params.update(chosen)
        name = params.get("contact_name")

    # Không gọi bừa: fallback "người thân" trước đây khiến một câu nghe nhầm
    # thành contact_call vẫn đi tra danh bạ với một cái tên không ai nói ra.
    if not name:
        spec = SLOTS["contact_name"]
        action_flow.set_pending(
            slot="contact_name",
            intent="contact_call",
            known={"_contact_attempt": 0},
            question=spec.ask,
            kind=spec.kind,
        )
        yield spec.ask
        return

    # D3 — chỉ low confidence mới chịu một lượt xác nhận. Marker nội bộ được
    # đặt vào `known` để câu "ừ" dispatch lại mà không tự mở vòng confirm mới.
    if (
        not params.get("contact_confirmed")
        and should_readback("contact_name", params.get("slot_confidence"))
    ):
        question = f"Bạn muốn gọi cho {name}, đúng không?"
        confirmed = dict(params)
        confirmed["contact_name"] = name
        confirmed["contact_confirmed"] = True
        action_flow.set_pending(
            slot="contact_name",
            intent="contact_call",
            known=confirmed,
            question=question,
            kind="confirm",
        )
        yield question
        return

    contact_id = params.get("contact_id")
    if contact_id:
        payload = {"contact_id": contact_id}
    else:
        payload = {"name": name}
        logger.warning(
            "T08/D8 fallback theo name vì app chưa trả contact_id; "
            "so khớp bằng nhau tuyệt đối có thể vẫn trượt: %s",
            name,
        )

    previous_attempt = int(params.get("_contact_attempt") or 0)

    yield from action_flow.run_action(
        "contact_call",
        "api/v1/service/contact/call",
        payload,
        ack=f"Đang tìm số của {name}.",
        failure=f"Không thể thực hiện cuộc gọi cho {name}, vui lòng thử lại.",
        progress=(
            f"Vẫn đang tìm {name} trong danh bạ.",
            _CONNECTING,
        ),
    )

    # 21.2 — giữ số lần thử qua `known` của pending mới mà run_action vừa tạo
    # từ CONTACT_NOT_FOUND. Sau lần thứ ba, đổi hẳn cách hướng dẫn thay vì lặp
    # nguyên văn "Bạn muốn gọi cho ai?".
    retry = action_flow.get_pending()
    if retry is not None and retry.slot == "contact_name":
        retry.attempt = previous_attempt + 1
        retry.known["_contact_attempt"] = retry.attempt
        if retry.over_max_attempt():
            retry.question = _CONTACT_RETRY_STRATEGY
            yield _CONTACT_RETRY_STRATEGY


def handle_emergency(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    number = params.get("emergency_number")

    payload = {}
    if number:
        payload["number"] = number

    yield from action_flow.run_action(
        "emergency_call",
        "api/v1/service/emergency/call",
        payload,
        ack=_EMERGENCY_ACK,
        failure=_EMERGENCY_FAILURE,
        progress=_EMERGENCY_PROGRESS,
    )
