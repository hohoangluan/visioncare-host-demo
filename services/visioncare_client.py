import json
import logging
import threading
import time
import uuid

import httpx

import config
from pipeline import device_ctx

logger = logging.getLogger("blind_assist")

# MỘT client dùng chung, giữ kết nối sống giữa các lệnh gọi.
#
# Trước đây file này dùng `urllib.request.urlopen`, tức mỗi lệnh gọi dựng một
# kết nối mới. Một lượt `get_device_location()` là 1 POST rồi poll 0,5s/lần;
# `wait_for_result()` của các action dài còn gọi nhiều hơn, nên vẫn tái dùng
# kết nối HTTP tới app server chạy trên localhost.
#
# `httpx.Client` an toàn khi nhiều luồng dùng chung, và server chạy request
# trong threadpool nên điều đó là bắt buộc chứ không phải tiện tay.
_CLIENT: httpx.Client | None = None
_CLIENT_LOCK = threading.Lock()

_BASE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VisionCare-Glasses/1.0",
}


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT = httpx.Client(
                    base_url=config.VISIONCARE_HOST_URL.rstrip("/"),
                    headers=_BASE_HEADERS,
                    # Giữ kết nối sống hẳn 5 phút: nhịp lấy vị trí ở nền là 240 s,
                    # nên hạn ngắn hơn thế là mỗi nhịp lại mở kết nối từ đầu.
                    limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=300.0),
                    timeout=10.0,
                )
    return _CLIENT


def reset_client() -> None:
    """Đóng client dùng chung (dùng trong test, và khi đổi host lúc chạy)."""
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            _CLIENT.close()
            _CLIENT = None


def _auth_header() -> dict:
    # Đọc token mỗi lượt chứ không nướng vào client: test đổi
    # `config.VISIONCARE_CLIENT_TOKEN` bằng monkeypatch, và nếu token nằm trong
    # header của client thì bản đổi đó không có tác dụng.
    return {"Authorization": f"Bearer {config.VISIONCARE_CLIENT_TOKEN}"}


class VisionCareAPIError(Exception):
    """Lỗi khi gọi VisionCare Host Service API."""
    def __init__(self, message: str, status_code: int = 500, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


def call_service_api(endpoint_path: str, payload: dict, bare: bool = False) -> dict:
    """Gửi POST request tới VisionCare Host Public Service API (`/api/v1/service/...`).

    Tự động chèn `device_id` (luôn là kính đã xác thực) và `request_id` (UUID4) nếu chưa có, và thêm
    các header xác thực Bearer token.

    `bare=True`: gửi đúng payload của nơi gọi, KHÔNG chèn gì. Các endpoint gọi/nhắn/khẩn cấp của AB
    (`service/call|messages|emergency/...`) khai schema `extra="forbid"` với tên trường riêng
    (`glasses_device_id`, hangup không có `request_id`) nên chèn thêm `device_id`/`request_id` là 422.
    """
    url = f"{config.VISIONCARE_HOST_URL.rstrip('/')}/{endpoint_path.lstrip('/')}"

    request_payload = dict(payload)
    if not bare:
        # Luôn là kính đã xác thực của luồng này (`device_ctx.current` do `guard.authenticate` quyết), không nhận
        # `device_id` do nơi gọi/client khai trong payload: tránh gọi AB nhân danh kính khác (C0).
        request_payload["device_id"] = device_ctx.current.get()
        if "request_id" not in request_payload:
            request_payload["request_id"] = str(uuid.uuid4())

    logger.info("Calling VisionCare API: POST %s with request_id=%s", url, request_payload.get("request_id"))

    try:
        resp = _client().post(
            url,
            content=json.dumps(request_payload).encode("utf-8"),
            headers={**_auth_header(), "Content-Type": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001 - gộp mọi lỗi mạng thành một loại
        logger.error("VisionCare API connection error: %s", exc)
        raise VisionCareAPIError(f"Lỗi kết nối VisionCare API: {exc}") from exc

    if resp.status_code >= 400:
        logger.error("VisionCare API HTTPError [%d]: %s", resp.status_code, resp.text)
        try:
            err_json = resp.json()
        except Exception:  # noqa: BLE001
            err_json = {"detail": resp.text}
        raise VisionCareAPIError(
            f"VisionCare API returned status {resp.status_code}",
            status_code=resp.status_code,
            details=err_json,
        )

    response_json = resp.json() if resp.content else {}
    logger.info("VisionCare API response [%d]: %s", resp.status_code, response_json)
    return response_json


# ── gọi điện / nhắn tin / khẩn cấp với người thân (Plan 2; AB `service/call|messages|emergency`) ──
#
# Mọi hàm: đồng bộ (gọi trong thread làn D hoặc `asyncio.to_thread`), trả phần `data` của envelope, lỗi HTTP/mạng
# -> `VisionCareAPIError` (`error_code(exc)` / `error_candidates(exc)` đọc mã lỗi AB). `glasses_device_id` luôn là
# kính đã xác thực của luồng (`device_ctx.current`), không nhận từ nơi gọi; AB suy chủ kính từ đó (không gửi `user_id`
# — một user chung cho cả server làm kính của chủ B đọc/nhắn dưới tên chủ A).

def error_code(exc: VisionCareAPIError) -> str:
    err = exc.details.get("error") if isinstance(exc.details, dict) else None
    return str(err.get("code") or "") if isinstance(err, dict) else ""


def error_candidates(exc: VisionCareAPIError) -> list[str]:
    """Tên các người thân trùng khớp khi AB trả `MULTIPLE_CONTACTS_FOUND` (`error.details.candidates`)."""
    err = exc.details.get("error") if isinstance(exc.details, dict) else None
    details = err.get("details") if isinstance(err, dict) else None
    items = details.get("candidates") if isinstance(details, dict) else None
    return [str(c) for c in items] if isinstance(items, list) else []


def _service(path: str, payload: dict) -> dict:
    return call_service_api(path, payload, bare=True).get("data", {}) or {}


def call_start(contact_alias: str, media_token: str, request_id: str | None = None,
               emergency: bool = False) -> dict:
    return _service("api/v1/service/call/start", {
        "glasses_device_id": device_ctx.current.get(), "contact_alias": contact_alias,
        "media_token": media_token, "request_id": request_id or str(uuid.uuid4()), "emergency": emergency,
    })


def call_hangup(call_id: str, reason: str | None = None) -> dict:
    return _service(f"api/v1/service/call/{call_id}/hangup", {"reason": reason} if reason else {})


def call_answer(call_id: str, media_token: str) -> dict:
    return _service(f"api/v1/service/call/{call_id}/answer", {"media_token": media_token})


def emergency_start(media_tokens: list[str], request_id: str | None = None) -> dict:
    return _service("api/v1/service/emergency/start", {
        "glasses_device_id": device_ctx.current.get(),
        "request_id": request_id or str(uuid.uuid4()), "media_tokens": media_tokens,
    })


def emergency_stop(emergency_id: str) -> dict:
    return _service(f"api/v1/service/emergency/{emergency_id}/stop", {})


def messages_send(contact_alias: str, text: str, request_id: str | None = None) -> dict:
    return _service("api/v1/service/messages/send", {
        "glasses_device_id": device_ctx.current.get(), "contact_alias": contact_alias, "text": text,
        "request_id": request_id or str(uuid.uuid4()),
    })


def messages_unread() -> list[dict]:
    """Tin chưa đọc (cũ -> mới, tối đa 50): `[{message_id, from_display_name, text, created_at}]`."""
    url = f"{config.VISIONCARE_HOST_URL.rstrip('/')}/api/v1/service/messages/unread"
    try:
        resp = _client().get(url, params={"glasses_device_id": device_ctx.current.get()}, headers=_auth_header())
    except Exception as exc:  # noqa: BLE001
        raise VisionCareAPIError(f"Lỗi kết nối VisionCare API: {exc}") from exc
    if resp.status_code >= 400:
        raise VisionCareAPIError(f"VisionCare API returned status {resp.status_code}", status_code=resp.status_code)
    return (resp.json().get("data") or {}).get("messages", [])


def message_read(message_id: str) -> dict:
    return _service(f"api/v1/service/messages/{message_id}/read", {"glasses_device_id": device_ctx.current.get()})


def get_request_status(request_id: str) -> dict:
    """Đọc trạng thái hiện tại của một request qua `GET /api/v1/requests/{id}`.

    Trả về phần `data` của envelope: `{request_id, operation, request_state,
    result, error, created_at, updated_at}`.
    """
    url = f"{config.VISIONCARE_HOST_URL.rstrip('/')}/api/v1/requests/{request_id}"

    try:
        resp = _client().get(url, headers=_auth_header())
    except Exception as exc:  # noqa: BLE001
        logger.error("VisionCare status connection error: %s", exc)
        raise VisionCareAPIError(f"Lỗi kết nối khi tra trạng thái: {exc}") from exc

    if resp.status_code >= 400:
        logger.error("VisionCare status HTTPError [%d]: %s", resp.status_code, resp.text)
        raise VisionCareAPIError(
            f"Không tra được trạng thái request {request_id}", status_code=resp.status_code
        )
    return resp.json().get("data", {})


def get_device_location(timeout_seconds: float = 12.0) -> dict | None:
    """Toạ độ hiện tại của điện thoại, hoặc `None` khi không lấy được.

    Trả `{"lat", "lng", "address", "captured_at"}` từ
    `POST /api/v1/service/location/get`. Không raise: vị trí chỉ là bối cảnh
    thêm cho câu trả lời, hỏng thì trả lời không có vị trí vẫn hơn là không
    trả lời gì.
    """
    try:
        resp = call_service_api("api/v1/service/location/get", {})
        request_id = resp.get("data", {}).get("request_id", "")
    except VisionCareAPIError as exc:
        logger.info("Không lấy được vị trí: %s", exc)
        return None
    if not request_id:
        return None

    data = wait_for_result(request_id, timeout_seconds=timeout_seconds)
    if not data or data.get("request_state") != "succeeded":
        logger.info("Vị trí không sẵn sàng: %s", (data or {}).get("error"))
        return None
    return data.get("result") or None


def wait_for_result(request_id: str, timeout_seconds: float | None = None) -> dict | None:
    """Poll tới khi request rời trạng thái `processing`, hoặc hết thời gian chờ.

    Trả về `data` cuối cùng, hoặc `None` khi hết giờ mà vẫn `processing` — người
    gọi phân biệt được "điện thoại đã trả lời" với "chờ mãi không thấy" để nói
    hai câu khác nhau.
    """
    budget = timeout_seconds if timeout_seconds is not None else config.VISIONCARE_RESULT_TIMEOUT_SECONDS
    deadline = time.monotonic() + budget

    while time.monotonic() < deadline:
        try:
            data = get_request_status(request_id)
        except VisionCareAPIError:
            # Một lần tra hỏng (mạng chớp) không có nghĩa là action hỏng — thử lại
            # tới khi hết thời gian chờ.
            time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)
            continue

        if data.get("request_state") and data["request_state"] != "processing":
            logger.info(
                "Request %s finished: %s", request_id, data["request_state"]
            )
            return data
        time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)

    logger.warning("Request %s vẫn processing sau %.0fs", request_id, budget)
    return None
