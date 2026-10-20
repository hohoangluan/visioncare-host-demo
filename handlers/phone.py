import logging
from collections.abc import Iterator

import config
from handlers.action_flow import run_action
from live import call_bridge, messages
from pipeline import device_ctx
from services import visioncare_client

logger = logging.getLogger("blind_assist")

_ASK_CONTACT = "Bạn muốn gọi cho ai? Vui lòng nói lại kèm tên người cần gọi."
_CONNECTING = "Đang kết nối cuộc gọi, bạn chờ một chút."

_EMERGENCY_ACK = "Đang kích hoạt cuộc gọi khẩn cấp."
_EMERGENCY_FAILURE = "Không thể phát cuộc gọi khẩn cấp, vui lòng kiểm tra kết nối."
_EMERGENCY_PROGRESS = (
    "Đang lấy vị trí và gọi số khẩn cấp, bạn giữ máy.",
    "Vẫn đang kết nối cuộc gọi khẩn cấp, bạn giữ máy.",
)

_CALL_BUSY = "Kính đang có cuộc gọi."
_CALL_NO_USER = "Kính chưa gắn với tài khoản để gọi điện."
_EMERGENCY_NO_CONTACT = "Chưa cài người thân khẩn cấp trong ứng dụng."

# Nhắn tin (C7). Câu "Đã gửi." và hai câu lỗi do mình thêm (spec không có): người khiếm thị cần biết tin đã đi.
MSG_NEED_UPDATE = "Kính cần cập nhật để nhắn tin."
MSG_NEED_OWN_TOKEN = "Kính cần token riêng để nhắn tin."
MSG_NONE = "Không có tin nhắn mới."
_MSG_SENT = "Đã gửi."
_MSG_ASK_NAME = "Bạn muốn nhắn cho ai?"

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio. Riêng
# nhóm khẩn cấp thì dựng sẵn là bắt buộc chứ không phải tối ưu: đó là lúc không
# được để người dùng chờ thêm một giây nào cho việc tổng hợp giọng.
STATIC_SPEECH: tuple[str, ...] = (
    _ASK_CONTACT,
    _CONNECTING,
    _EMERGENCY_ACK,
    _EMERGENCY_FAILURE,
    *_EMERGENCY_PROGRESS,
    _CALL_BUSY,
    _CALL_NO_USER,
    _EMERGENCY_NO_CONTACT,
    MSG_NEED_UPDATE,
    MSG_NEED_OWN_TOKEN,
    MSG_NONE,
    _MSG_SENT,
    _MSG_ASK_NAME,
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


# ── gọi điện qua AB + cầu âm thanh (Plan 2 C6) ───────────────────────────────────────────────
#
# Chạy trong thread nền của làn D, SAU khi câu đọc lại ("Đang gọi cho {name}.") đã tới kính và cửa sổ huỷ đã qua.
# Cuộc gọi được tạo trong `call_bridge.calls` TRƯỚC khi gọi AB vì `media_token` do VH sinh và AB cần nó lúc `start`;
# AB từ chối thì `discard` (kính nhận call_state ended). Mọi câu trả ra đây đều đọc cho kính qua `push_result`
# (không kết thúc bằng "\n": làn D bỏ câu đầu kết thúc bằng "\n" như câu xác nhận của luồng cũ).

def _ended_early(call) -> bool:
    return call.state == call_bridge.ENDED


def handle_contact_call(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    name = params.get("contact_name")
    if not name:
        yield _ASK_CONTACT
        return
    device = device_ctx.current.get()
    reason = call_bridge.unavailable_reason(device, device_ctx.per_device.get())
    if reason:  # phòng thủ: router đã chặn trước khi đọc lại, nhưng phiên có thể rớt trong cửa sổ huỷ
        yield reason
        return
    try:
        call = call_bridge.calls.create(None, device, name, call_bridge.TO_RELATIVE)
    except call_bridge.GlassesBusy:
        yield _CALL_BUSY
        return
    failure = f"Không thể gọi cho {name}, vui lòng thử lại."
    try:
        data = visioncare_client.call_start(name, call.media_token)
    except visioncare_client.VisionCareAPIError as exc:
        call_bridge.calls.discard(call)
        code = visioncare_client.error_code(exc)
        candidates = visioncare_client.error_candidates(exc)
        if code == "MULTIPLE_CONTACTS_FOUND" and len(candidates) >= 2:
            from lanes import phone as lane  # nhập muộn: lanes.phone nhập module này

            lane.set_pending_choice(device, "contact_call", candidates)
            yield f"Bạn muốn gọi ai: {candidates[0]} hay {candidates[1]}?"
        elif code == "CONTACT_NOT_FOUND":
            yield f"Chưa có người thân tên {name} trong danh sách."
        elif code == "GLASSES_DEVICE_NOT_LINKED":
            yield _CALL_NO_USER
        else:
            logger.warning("contact_call: AB từ chối start (%s, HTTP %s)", code or "?", exc.status_code)
            yield failure
        return
    except Exception:  # noqa: BLE001
        call_bridge.calls.discard(call)
        logger.exception("contact_call: lỗi bất ngờ khi gọi AB")
        yield failure
        return
    call_bridge.calls.bind(call, str(data.get("call_id") or call.call_id), (data.get("relative") or {}).get("display_name"))
    if _ended_early(call):  # người dùng cúp trong lúc AB đang xử lý `start`: AB còn đang đổ chuông bên kia
        try:
            visioncare_client.call_hangup(call.call_id, "glasses_hangup")
        except Exception:  # noqa: BLE001
            logger.warning("contact_call: báo AB cúp sớm lỗi")


def handle_emergency_call(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Khẩn cấp = AB gọi lần lượt người thân đã cài (tối đa 3 vòng), VH giữ MỘT `Call` đại diện cả chuỗi.

    DỰ PHÒNG CÓ CHỦ Ý (quyết định người dùng): kính chưa có phiên/token riêng (đường internet không dùng được) thì rơi về
    đường SIM cũ (`emergency/call`: SMS `[SOS]` + gọi qua điện thoại chủ kính). Chỉ khẩn cấp có lưới này; gọi/nhắn thường
    không bao giờ dùng SIM. Khẩn cấp không được im lặng vì thiếu cập nhật."""
    device = device_ctx.current.get()
    if call_bridge.unavailable_reason(device, device_ctx.per_device.get()):
        yield from handle_emergency(image, command_text, params)
        return
    try:
        call = call_bridge.calls.create(None, device, "người thân", call_bridge.TO_RELATIVE, emergency=True)
    except call_bridge.GlassesBusy:
        yield _CALL_BUSY
        return
    tokens = [call.media_token, *call_bridge.calls.add_tokens(call, max(1, config.EMERGENCY_MEDIA_TOKENS) - 1)]
    try:
        data = visioncare_client.emergency_start(tokens)
    except visioncare_client.VisionCareAPIError as exc:
        call_bridge.calls.discard(call)
        code = visioncare_client.error_code(exc)
        logger.warning("emergency_call: AB từ chối start (%s, HTTP %s)", code or "?", exc.status_code)
        yield _EMERGENCY_NO_CONTACT if code == "EMERGENCY_CONTACT_NOT_FOUND" else _EMERGENCY_FAILURE
        return
    except Exception:  # noqa: BLE001
        call_bridge.calls.discard(call)
        logger.exception("emergency_call: lỗi bất ngờ khi gọi AB")
        yield _EMERGENCY_FAILURE
        return
    call.emergency_id = str(data.get("emergency_id") or "") or None
    if data.get("call_id"):
        call_bridge.calls.bind(call, str(data["call_id"]), (data.get("relative") or {}).get("display_name"))
    if data.get("state") == "exhausted":
        call_bridge.calls.discard(call, "emergency_exhausted")
        yield call_bridge.EMERGENCY_NONE_REACHED
    elif _ended_early(call) and call.emergency_id:  # bấm nút dừng trước khi AB trả `emergency_id`: dừng chuỗi bù
        try:
            data = visioncare_client.emergency_stop(call.emergency_id)
            if data.get("state") == "answered" and data.get("call_id"):  # đua với người vừa nghe máy: cúp cuộc còn active
                visioncare_client.call_hangup(str(data["call_id"]), "glasses_hangup")
        except Exception:  # noqa: BLE001
            logger.warning("emergency_call: báo AB dừng sớm lỗi")


# ── nhắn tin qua AB (Plan 2 C7) ──────────────────────────────────────────────────────────────

_MSG_MAX = 1000  # giới hạn của AB (1–1000 ký tự); dài hơn thì cắt thay vì bị từ chối 400


def handle_message_send(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Chạy trong thread nền của làn D SAU câu đọc lại "Nhắn cho {name}: {text}." và cửa sổ huỷ."""
    params = params or {}
    name = (params.get("contact_name") or "").strip()
    text = (params.get("text") or "").strip()[:_MSG_MAX]
    if not name:
        yield _MSG_ASK_NAME
        return
    if not text:
        from lanes import phone as lane  # nhập muộn: lanes.phone nhập module này

        lane.set_pending_body(device_ctx.current.get(), name)
        yield lane.body_question(name)
        return
    device = device_ctx.current.get()
    reason = call_bridge.unavailable_reason(device, device_ctx.per_device.get())
    if reason:  # phòng thủ: router đã chặn, nhưng phiên có thể rớt trong cửa sổ huỷ
        yield MSG_NEED_UPDATE if reason == call_bridge.NEED_UPDATE else MSG_NEED_OWN_TOKEN
        return
    try:
        visioncare_client.messages_send(name, text)
    except visioncare_client.VisionCareAPIError as exc:
        code = visioncare_client.error_code(exc)
        candidates = visioncare_client.error_candidates(exc)
        if code == "MULTIPLE_CONTACTS_FOUND" and len(candidates) >= 2:
            from lanes import phone as lane

            lane.set_pending_choice(device, "message_send", candidates, keep={"text": text})
            yield f"Bạn muốn nhắn cho ai: {candidates[0]} hay {candidates[1]}?"
        elif code == "CONTACT_NOT_FOUND":
            yield f"Chưa có người thân tên {name} trong danh sách."
        elif code == "GLASSES_DEVICE_NOT_LINKED":
            yield _CALL_NO_USER
        else:
            logger.warning("message_send: AB từ chối (%s, HTTP %s)", code or "?", exc.status_code)
            yield f"Không gửi được tin nhắn cho {name}, vui lòng thử lại."
        return
    except Exception:  # noqa: BLE001
        logger.exception("message_send: lỗi bất ngờ khi gọi AB")
        yield f"Không gửi được tin nhắn cho {name}, vui lòng thử lại."
        return
    yield _MSG_SENT


def handle_message_read(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Đọc từng tin chưa đọc ("{name} nhắn: {text}") rồi đánh dấu đã đọc; không có thì "Không có tin nhắn mới."

    Đánh dấu SAU khi tin đã được yield (generator chỉ chạy tiếp khi TTS lấy câu kế): bị huỷ giữa chừng thì
    các tin chưa tới lượt vẫn chưa đọc ở AB."""
    try:
        unread = visioncare_client.messages_unread()
    except Exception:  # noqa: BLE001
        logger.exception("message_read: không lấy được tin chưa đọc")
        yield "Không lấy được tin nhắn, vui lòng thử lại."
        return
    spoken = 0
    for item in unread:
        message_id = str(item.get("message_id") or "")
        text = str(item.get("text") or "").strip()
        if not message_id or not text or not messages.mark_spoken(message_id):
            continue  # đã đọc (hàng đợi tin tới) hoặc tin rỗng
        spoken += 1
        try:
            yield messages.speech(str(item.get("from_display_name") or ""), text)
        except GeneratorExit:  # bị huỷ trước khi đọc xong: trả lại trạng thái chưa đọc
            messages.unmark_spoken(message_id)
            raise
        mark_read(message_id)
    if not spoken:
        yield MSG_NONE


def mark_read(message_id: str) -> None:
    try:
        visioncare_client.message_read(message_id)
    except Exception:  # noqa: BLE001
        logger.warning("message_read: báo AB đã đọc lỗi")  # AB giữ tin chưa đọc; lần sau đọc lại
