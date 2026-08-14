import json
import logging
import time
import uuid
import urllib.request
import urllib.error

import config

logger = logging.getLogger("blind_assist")


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

    headers = {
        "Authorization": f"Bearer {config.VISIONCARE_CLIENT_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "VisionCare-Glasses/1.0",
    }

    data = json.dumps(request_payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    logger.info("Calling VisionCare API: POST %s with request_id=%s", url, request_payload.get("request_id"))

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            response_json = json.loads(resp_body) if resp_body else {}
            logger.info("VisionCare API response [%d]: %s", resp.status, response_json)
            return response_json
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8") if exc.fp else ""
        logger.error("VisionCare API HTTPError [%d]: %s", exc.code, err_body)
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"detail": err_body}
        raise VisionCareAPIError(
            f"VisionCare API returned status {exc.code}",
            status_code=exc.code,
            details=err_json,
        ) from exc
    except Exception as exc:
        logger.error("VisionCare API connection error: %s", exc)
        raise VisionCareAPIError(f"Lỗi kết nối VisionCare API: {exc}") from exc


def get_request_status(request_id: str) -> dict:
    """Đọc trạng thái hiện tại của một request qua `GET /api/v1/requests/{id}`.

    Trả về phần `data` của envelope: `{request_id, operation, request_state,
    result, error, created_at, updated_at}`.
    """
    url = f"{config.VISIONCARE_HOST_URL.rstrip('/')}/api/v1/requests/{request_id}"
    headers = {
        "Authorization": f"Bearer {config.VISIONCARE_CLIENT_TOKEN}",
        "Accept": "application/json",
        # Bắt buộc: Cloudflare trước tunnel chặn user-agent mặc định của
        # urllib bằng error 1010, request không bao giờ tới backend.
        "User-Agent": "VisionCare-Glasses/1.0",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("data", {})
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8") if exc.fp else ""
        logger.error("VisionCare status HTTPError [%d]: %s", exc.code, err_body)
        raise VisionCareAPIError(
            f"Không tra được trạng thái request {request_id}", status_code=exc.code
        ) from exc
    except Exception as exc:
        logger.error("VisionCare status connection error: %s", exc)
        raise VisionCareAPIError(f"Lỗi kết nối khi tra trạng thái: {exc}") from exc


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
