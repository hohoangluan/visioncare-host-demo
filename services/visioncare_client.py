import json
import logging
import threading
import time
import uuid

import httpx

import config

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


def call_service_api(endpoint_path: str, payload: dict) -> dict:
    """Gửi POST request tới VisionCare Host Public Service API (`/api/v1/service/...`).

    Tự động chèn `device_id` và `request_id` (UUID4) nếu chưa có, và thêm
    các header xác thực Bearer token.
    """
    url = f"{config.VISIONCARE_HOST_URL.rstrip('/')}/{endpoint_path.lstrip('/')}"

    request_payload = dict(payload)
    if "device_id" not in request_payload:
        request_payload["device_id"] = config.VISIONCARE_DEVICE_ID
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
