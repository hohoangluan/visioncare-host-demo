"""Cổng bảo vệ endpoint kính: xác thực token, rate limit (Task 9).

Server mở ra internet qua Cloudflare tunnel nên MỌI endpoint của kính đòi token,
không có ngoại lệ localhost (qua tunnel, cloudflared kết nối từ 127.0.0.1 nên
"localhost" nghĩa là cả thế giới).

Độ trễ là ưu tiên số 1: cổng chỉ so chuỗi bằng `hmac.compare_digest` (thời gian
hằng, ~1 µs) và trừ một token bucket trong RAM — không I/O, không await.
"""

import hmac
import logging
import threading
import time

from starlette.requests import Request

import config

logger = logging.getLogger("blind_assist")


class GuardError(Exception):
    """Từ chối request: `status` + body JSON `{"error": ...}`."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


def _presented(headers) -> str:
    auth = headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (headers.get("x-device-token") or "").strip()


def token_ok(headers_or_value) -> bool:
    """`Authorization: Bearer <t>` hoặc `X-Device-Token: <t>` (hoặc chuỗi token trần)."""
    expected = config.VISIONCARE_DEVICE_CLIENT_TOKEN
    if not expected:
        return False
    value = headers_or_value if isinstance(headers_or_value, str) else _presented(headers_or_value)
    # So theo byte: compare_digest với str không-ASCII sẽ ném TypeError.
    return hmac.compare_digest(value.encode(), expected.encode())


def check_token(headers) -> None:
    """Ném GuardError 503 (chưa cấu hình) hoặc 401 (thiếu/sai token)."""
    if not config.VISIONCARE_DEVICE_CLIENT_TOKEN:
        raise GuardError(503, "device token not configured")
    if not token_ok(headers):
        raise GuardError(401, "invalid or missing device token")


def log_startup() -> None:
    if not config.VISIONCARE_DEVICE_CLIENT_TOKEN:
        logger.error(
            "VISIONCARE_DEVICE_CLIENT_TOKEN rỗng: MỌI endpoint của kính sẽ trả 503 "
            "cho tới khi đặt token trong .env"
        )


class RateLimiter:
    """Token bucket trong RAM, khoá theo device id. `burst` token đầy lúc đầu."""

    def __init__(self, rate_per_min: float, burst: int) -> None:
        self._rate = rate_per_min / 60.0
        self._burst = float(burst)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (self._burst, now))
            tokens = min(self._burst, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            return True


_turn_limiter: RateLimiter | None = None
_image_limiter: RateLimiter | None = None


def limiters() -> tuple[RateLimiter, RateLimiter]:
    """Dựng lười để test đổi config rồi `reset()`."""
    global _turn_limiter, _image_limiter
    if _turn_limiter is None:
        _turn_limiter = RateLimiter(config.DEVICE_TURNS_PER_MIN, max(1, int(config.DEVICE_TURNS_PER_MIN)))
        _image_limiter = RateLimiter(config.DEVICE_IMAGES_PER_MIN, max(1, int(config.DEVICE_IMAGES_PER_MIN)))
    return _turn_limiter, _image_limiter


def reset() -> None:
    global _turn_limiter, _image_limiter
    _turn_limiter = _image_limiter = None


def _device(headers) -> str:
    return headers.get("x-device-id") or config.VISIONCARE_DEVICE_ID


def _rate(kind: int, headers) -> None:
    if not limiters()[kind].allow(_device(headers)):
        raise GuardError(429, "rate limit exceeded")


def turn_guard(request: Request) -> None:
    """Dependency FastAPI cho /process và /v2/turn."""
    check_token(request.headers)
    _rate(0, request.headers)


def image_guard(request: Request) -> None:
    """Dependency FastAPI cho /v2/image."""
    check_token(request.headers)
    _rate(1, request.headers)
