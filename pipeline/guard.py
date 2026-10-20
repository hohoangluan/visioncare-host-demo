"""Cổng bảo vệ endpoint kính: xác thực token, rate limit (Task 9).

Server mở ra internet qua Cloudflare tunnel nên MỌI endpoint của kính đòi token,
không có ngoại lệ localhost (qua tunnel, cloudflared kết nối từ 127.0.0.1 nên
"localhost" nghĩa là cả thế giới).

Độ trễ là ưu tiên số 1: cổng chỉ so chuỗi bằng `hmac.compare_digest` (thời gian
hằng, ~1 µs) và trừ một token bucket trong RAM — không I/O, không await.

Token riêng từng kính (Plan 2 / C0): file JSON `{device_id: sha256 hex}` trỏ bởi
`VISIONCARE_DEVICE_TOKENS`; `authenticate` trả `Auth(device_id, per_device)`. Chỉ phiên
`per_device=True` mới được gọi điện/nhắn tin/khẩn cấp; token chung cũ vẫn chạy (demo, kính cũ)
khi `VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN=1` nhưng không bao giờ là `per_device`.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import NamedTuple

from starlette.requests import Request

import config

logger = logging.getLogger("blind_assist")


class GuardError(Exception):
    """Từ chối request: `status` + body JSON `{"error": ...}`."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


class Auth(NamedTuple):
    """Kết quả xác thực: `device_id` là id ĐÃ xác thực (C5–C7 chỉ tin id này), `per_device` = true khi
    token là token riêng của đúng kính đó. Token dùng chung -> `per_device=False`, id vẫn do client khai."""

    device_id: str
    per_device: bool


_HEX64 = frozenset("0123456789abcdef")
_TOKENS_RECHECK_S = 2.0  # stat file token tối đa 1 lần / 2 s: thêm kính không cần restart, đường nóng không I/O
_tokens_lock = threading.Lock()
_tokens: tuple[tuple[str, bytes], ...] = ()  # (device_id, sha256 digest 32 byte)
_tokens_key: tuple[str, float] | None = None  # (đường dẫn, mtime) của lần nạp cuối
_tokens_checked = 0.0
_warned_shared = False


def tokens_path() -> str:
    path = config.VISIONCARE_DEVICE_TOKENS
    return path if not path or os.path.isabs(path) else os.path.join(os.path.dirname(config.__file__), path)


def _load_tokens(path: str) -> tuple[tuple[str, bytes], ...]:
    """Đọc file `{device_id: sha256 hex}`. Dòng sai định dạng bị bỏ (kèm cảnh báo, không in giá trị)."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("không phải object")
    except (OSError, ValueError) as exc:
        logger.error("VISIONCARE_DEVICE_TOKENS: không đọc được file token riêng (%s): %s", path, exc)
        return ()
    out = []
    for device, digest in raw.items():
        d = digest.strip().lower() if isinstance(digest, str) else ""
        if not device or len(d) != 64 or not set(d) <= _HEX64:
            logger.warning("VISIONCARE_DEVICE_TOKENS: bỏ qua mục %r (hash không phải sha256 hex)", device)
            continue
        out.append((str(device), bytes.fromhex(d)))
    return tuple(out)


def device_tokens() -> tuple[tuple[str, bytes], ...]:
    """Bảng token riêng, nạp lười từ file và nạp lại khi mtime đổi."""
    global _tokens, _tokens_key, _tokens_checked
    path = tokens_path()
    if not path:
        return ()
    now = time.monotonic()
    if _tokens_key is not None and _tokens_key[0] == path and now - _tokens_checked < _TOKENS_RECHECK_S:
        return _tokens
    with _tokens_lock:
        _tokens_checked = now
        try:
            key = (path, os.stat(path).st_mtime)
        except OSError:
            key = (path, -1.0)
        if key != _tokens_key:
            _tokens = _load_tokens(path) if key[1] >= 0 else ()
            if key[1] < 0:
                logger.error("VISIONCARE_DEVICE_TOKENS trỏ tới file không tồn tại: %s", path)
            _tokens_key = key
        return _tokens


def _presented(headers) -> str:
    auth = headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (headers.get("x-device-token") or "").strip()


def _shared_allowed() -> bool:
    return bool(config.VISIONCARE_DEVICE_CLIENT_TOKEN) and config.VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN


def configured() -> bool:
    return bool(device_tokens()) or _shared_allowed()


def authenticate(headers_or_value, claimed: str | None = None) -> Auth | None:
    """Xác thực token; None = từ chối (401 / đóng 4401).

    Token riêng: sha256(token) khớp một mục -> kính đó. Có `claimed` mà khác kính chủ token
    thì từ chối (token của kính này không mạo được kính khác); không khai thì lấy kính chủ token.
    Quét HẾT bảng bằng `compare_digest` (không thoát sớm) nên thời gian không lộ token nào gần đúng.
    Token chung (khi `VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN=1`): id do client khai, `per_device=False`.
    Chi phí: 1 sha256 + n so sánh 32 byte, ~6 µs với 50 kính (đo 2026-10-20, ngưỡng < 100 µs có test).
    """
    value = headers_or_value if isinstance(headers_or_value, str) else _presented(headers_or_value)
    if not value:
        return None
    raw = value.encode()  # so theo byte: compare_digest với str không-ASCII ném TypeError
    digest = hashlib.sha256(raw).digest()
    owner = None
    for device, expected in device_tokens():
        if hmac.compare_digest(digest, expected):
            owner = device
    if owner is not None:
        if claimed and claimed != owner:
            return None
        return Auth(owner, True)
    if _shared_allowed() and hmac.compare_digest(raw, config.VISIONCARE_DEVICE_CLIENT_TOKEN.encode()):
        return Auth(claimed or config.VISIONCARE_DEVICE_ID, False)
    return None


def token_ok(headers_or_value, claimed: str | None = None) -> bool:
    """`Authorization: Bearer <t>` hoặc `X-Device-Token: <t>` (hoặc chuỗi token trần)."""
    return authenticate(headers_or_value, claimed) is not None


def check_token(headers) -> Auth:
    """Ném GuardError 503 (chưa cấu hình) hoặc 401 (thiếu/sai token, hoặc token của kính khác)."""
    if not configured():
        raise GuardError(503, "device token not configured")
    auth = authenticate(headers, headers.get("x-device-id") or None)
    if auth is None:
        raise GuardError(401, "invalid or missing device token")
    return auth


def request_auth(request: Request) -> Auth:
    """Kết quả xác thực của request: dependency `turn_guard`/`image_guard` đã đặt vào `request.state`.

    Không có (chỉ khi test gọi thẳng hàm endpoint, bỏ qua dependency) thì coi như token chung:
    id theo `X-Device-Id`, `per_device=False` — mặc định an toàn, không bao giờ nâng quyền.
    """
    auth = getattr(request.state, "auth", None)
    if auth is not None:
        return auth
    return Auth(request.headers.get("x-device-id") or config.VISIONCARE_DEVICE_ID, False)


def log_startup() -> None:
    global _warned_shared
    n = len(device_tokens())
    if not configured():
        logger.error(
            "Chưa có token kính nào (VISIONCARE_DEVICE_CLIENT_TOKEN rỗng/bị tắt và VISIONCARE_DEVICE_TOKENS "
            "trống): MỌI endpoint của kính sẽ trả 503 cho tới khi cấu hình trong .env"
        )
    logger.info("token riêng từng kính: %d kính", n)
    if _shared_allowed() and not _warned_shared:
        _warned_shared = True
        logger.warning(
            "VISIONCARE_ALLOW_SHARED_DEVICE_TOKEN=1: token dùng chung còn được chấp nhận (kính/demo cũ); "
            "phiên đó KHÔNG gọi điện/nhắn tin/khẩn cấp được. Đặt =0 khi mọi kính đã có token riêng."
        )


class RateLimiter:
    """Token bucket trong RAM, khoá theo device id. `burst` token đầy lúc đầu."""

    def __init__(self, rate_per_min: float, burst: int) -> None:
        self._rate = rate_per_min / 60.0
        self._burst = float(burst)
        self._state: dict[str, tuple[float, float]] = {}
        self._max_keys = 4096  # X-Device-Id xoay vòng không được làm RAM phình mãi
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if key not in self._state and len(self._state) >= self._max_keys:
                # Bỏ khoá cũ nhất (dict giữ thứ tự chèn); khoá bị bỏ chỉ được đầy lại burst.
                self._state.pop(next(iter(self._state)))
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
    global _turn_limiter, _image_limiter, _tokens, _tokens_key, _warned_shared
    _turn_limiter = _image_limiter = None
    _tokens, _tokens_key, _warned_shared = (), None, False  # test đổi file/config token


def _rate(kind: int, request: Request, auth: Auth) -> None:
    # Khoá theo id ĐÃ xác thực: đổi X-Device-Id không né được rate limit của token riêng.
    if not limiters()[kind].allow(auth.device_id):
        raise GuardError(429, "rate limit exceeded")


def turn_guard(request: Request) -> None:
    """Dependency FastAPI cho /process và /v2/turn."""
    auth = request.state.auth = check_token(request.headers)
    _rate(0, request, auth)


def image_guard(request: Request) -> None:
    """Dependency FastAPI cho /v2/image."""
    auth = request.state.auth = check_token(request.headers)
    _rate(1, request, auth)


class ProcessBodyGuard:
    """ASGI middleware cho POST /process: token và trần kích thước TRƯỚC khi parse body.

    FastAPI đọc `request.form()` trước khi chạy dependency, nên một multipart khổng lồ
    không token vẫn bị parse/spool xuống đĩa. Ở đây ta chặn từ header, rồi đếm byte
    chạy qua `receive` và ngắt ngay khi vượt `DEVICE_MAX_PROCESS_BYTES`.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["path"] != "/process" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        from starlette.datastructures import Headers
        from starlette.responses import JSONResponse

        headers = Headers(scope=scope)
        try:
            check_token(headers)
        except GuardError as exc:
            await JSONResponse({"error": exc.error}, status_code=exc.status)(scope, receive, send)
            return
        cap = config.DEVICE_MAX_PROCESS_BYTES
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > cap:
            await JSONResponse({"error": "request too large"}, status_code=413)(scope, receive, send)
            return

        total, rejected = 0, False

        async def counted_receive():
            nonlocal total, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > cap:
                    rejected = True
                    await JSONResponse({"error": "request too large"}, status_code=413)(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not rejected:
                await send(message)

        await self.app(scope, counted_receive, guarded_send)
