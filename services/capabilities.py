"""T23 capability discovery, per-device cache, and actionable speech.

Capability discovery is advisory except for emergency calling. Old Android or
host versions may not implement the endpoint; that case deliberately returns
``None`` and keeps the old behavior instead of becoming a compatibility gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time

import config
from services import visioncare_client

logger = logging.getLogger("blind_assist")

CAPABILITY_KEYS = frozenset(
    {
        "notification_listener",
        "system_alert_window",
        "battery_optimization_off",
        "background_location",
        "fine_location",
        "read_contacts",
        "read_phone_state",
        "call_phone",
        "send_sms",
        "emergency_contact_set",
    }
)
BACKGROUND_LOCATION_VALUES = frozenset({"never", "while_using", "always"})
CAPABILITIES_TTL_SECONDS = 300.0

_EMERGENCY_CONTACT_WARNING = (
    "Bạn chưa cài số liên hệ khẩn cấp trên điện thoại. "
    "Hãy nhờ người hỗ trợ cài số trước khi cần dùng."
)
_CALL_PERMISSION_WARNING = (
    "Ứng dụng chưa được cấp quyền gọi điện. "
    "Hãy nhờ người hỗ trợ bật quyền trước khi cần gọi khẩn cấp."
)
_NOTIFICATION_LISTENER_SPEECH = (
    "Ứng dụng chưa bật quyền đọc thông báo nên chưa phát nhạc được."
)
_CONTACT_PERMISSION_SPEECH = "Ứng dụng chưa được cấp quyền đọc danh bạ."
_CALL_PERMISSION_SPEECH = "Ứng dụng chưa được cấp quyền gọi điện."
_LOCATION_PERMISSION_SPEECH = "Ứng dụng chưa được cấp quyền vị trí."
_BACKGROUND_LOCATION_SPEECH = (
    "Ứng dụng chưa được cấp quyền vị trí mọi lúc nên chưa gọi khẩn cấp được."
)
_EMERGENCY_CONTACT_SPEECH = "Chưa cài số liên hệ khẩn cấp trên điện thoại."

STATIC_SPEECH = (
    _EMERGENCY_CONTACT_WARNING,
    _CALL_PERMISSION_WARNING,
    _NOTIFICATION_LISTENER_SPEECH,
    _CONTACT_PERMISSION_SPEECH,
    _CALL_PERMISSION_SPEECH,
    _LOCATION_PERMISSION_SPEECH,
    _BACKGROUND_LOCATION_SPEECH,
    _EMERGENCY_CONTACT_SPEECH,
)


@dataclass(frozen=True)
class CacheEntry:
    values: dict[str, bool | str]
    cached_at: float


_LOCK = threading.RLock()
_CACHE: dict[str, CacheEntry] = {}
_PAIRING_WARNED: set[str] = set()


def current_device_key() -> str:
    """Use request identity when present and the configured device otherwise."""
    try:
        from app import DEVICE_ID_CTX

        return DEVICE_ID_CTX.get() or config.VISIONCARE_DEVICE_ID
    except ImportError:
        return config.VISIONCARE_DEVICE_ID


def _validate(raw_result: dict | None) -> dict[str, bool | str] | None:
    if not isinstance(raw_result, dict):
        return None
    raw = raw_result.get("capabilities")
    if not isinstance(raw, dict) or set(raw) != CAPABILITY_KEYS:
        logger.warning("Bỏ capability payload sai danh sách khoá đóng: %r", raw)
        return None
    if raw.get("background_location") not in BACKGROUND_LOCATION_VALUES:
        return None
    for key in CAPABILITY_KEYS - {"background_location"}:
        if not isinstance(raw.get(key), bool):
            return None
    return dict(raw)


def refresh(device_key: str | None = None) -> dict[str, bool | str] | None:
    """Fetch and cache a fresh snapshot; return ``None`` for old/unavailable apps."""
    key = device_key or current_device_key()
    values = _validate(visioncare_client.get_device_capabilities(device_id=key))
    if values is None:
        return None
    with _LOCK:
        _CACHE[key] = CacheEntry(values=values, cached_at=time.monotonic())
    return dict(values)


def get_cached(
    device_key: str | None = None, *, allow_stale: bool = False
) -> dict[str, bool | str] | None:
    key = device_key or current_device_key()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        if not allow_stale and time.monotonic() - entry.cached_at > CAPABILITIES_TTL_SECONDS:
            return None
        return dict(entry.values)


def cache_at_pairing(device_key: str | None = None) -> dict[str, bool | str] | None:
    """Refresh the important startup state without speaking from a worker thread."""
    return refresh(device_key)


def start_pairing_refresh(device_key: str | None = None) -> threading.Thread:
    """Start the startup lookup in the background so model warm-up is not delayed."""
    key = device_key or config.VISIONCARE_DEVICE_ID
    thread = threading.Thread(
        target=cache_at_pairing,
        args=(key,),
        name="capabilities-pairing-refresh",
        daemon=True,
    )
    thread.start()
    return thread


def consume_pairing_warning(device_key: str | None = None) -> str | None:
    """Return important setup guidance once per device for this server session."""
    key = device_key or current_device_key()
    with _LOCK:
        if key in _PAIRING_WARNED:
            return None
        entry = _CACHE.get(key)
        if entry is None:
            return None
        warnings: list[str] = []
        if entry.values["emergency_contact_set"] is False:
            warnings.append(_EMERGENCY_CONTACT_WARNING)
        if entry.values["call_phone"] is False:
            warnings.append(_CALL_PERMISSION_WARNING)
        _PAIRING_WARNED.add(key)
    return " ".join(warnings) or None


def emergency_blocking_speech(device_key: str | None = None) -> str | None:
    """Fail closed only when a cached capability proves emergency is not ready."""
    values = get_cached(device_key, allow_stale=True)
    if values is None:  # old app/no endpoint: retain the pre-T23 behavior
        return None
    if values["emergency_contact_set"] is False:
        return _EMERGENCY_CONTACT_SPEECH
    if values["call_phone"] is False:
        return _CALL_PERMISSION_SPEECH
    if values["background_location"] != "always":
        return _BACKGROUND_LOCATION_SPEECH
    return None


def _error_code(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    return str(error.get("code") or "") if isinstance(error, dict) else ""


def permission_failure_speech(
    operation: str, data: dict | None, device_key: str | None = None
) -> str | None:
    """Replace generic action failure speech with the capability that is missing."""
    if not isinstance(data, dict) or data.get("request_state") == "succeeded":
        return None
    key = device_key or current_device_key()
    code = _error_code(data)
    permission_error = code.endswith("_PERMISSION_DENIED") or code in {
        "EMERGENCY_CONTACT_NOT_CONFIGURED",
    }
    values = refresh(key) if permission_error else get_cached(key, allow_stale=True)
    if values is None:
        return None

    if operation == "music_play" and values["notification_listener"] is False:
        return _NOTIFICATION_LISTENER_SPEECH
    if operation == "contact_call":
        if values["read_contacts"] is False:
            return _CONTACT_PERMISSION_SPEECH
        if values["call_phone"] is False:
            return _CALL_PERMISSION_SPEECH
    if operation == "emergency_call":
        return emergency_blocking_speech(key)
    if operation in {"location_get", "navigation_start", "ride_quote"}:
        if values["fine_location"] is False:
            return _LOCATION_PERMISSION_SPEECH
    return None


def reset_for_test() -> None:
    with _LOCK:
        _CACHE.clear()
        _PAIRING_WARNED.clear()
