"""Per-device incoming-call state and privacy-safe caller announcements."""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time
from collections.abc import Mapping

import config


_ANSWER = re.compile(r"^\s*(nghe máy|nghe|trả lời)\s*[.!]?\s*$", re.I)
_REJECT = re.compile(r"^\s*(từ chối|không nghe|bỏ)\s*[.!]?\s*$", re.I)
_DIGIT_WORDS = {
    "0": "không",
    "1": "một",
    "2": "hai",
    "3": "ba",
    "4": "bốn",
    "5": "năm",
    "6": "sáu",
    "7": "bảy",
    "8": "tám",
    "9": "chín",
}
_CALLER_KEYS = frozenset({"contact_id", "name", "number_tail", "duplicate_name"})


@dataclass(frozen=True, slots=True)
class IncomingCall:
    caller: dict[str, object]
    opened_at: float
    expires_at: float


class IncomingCallRegistry:
    """Keep at most one short-lived incoming-call window per glasses device."""

    def __init__(self, *, window_seconds: float = 15.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._calls: dict[str, IncomingCall] = {}

    def open(
        self,
        device_id: str,
        caller: Mapping[str, object],
        *,
        now: float | None = None,
    ) -> IncomingCall:
        if not device_id:
            raise ValueError("device_id is required")
        opened_at = time.monotonic() if now is None else now
        call = IncomingCall(
            caller=dict(caller),
            opened_at=opened_at,
            expires_at=opened_at + self._window_seconds,
        )
        with self._lock:
            self._calls[device_id] = call
        return call

    def current(self, device_id: str, *, now: float | None = None) -> IncomingCall | None:
        checked_at = time.monotonic() if now is None else now
        with self._lock:
            call = self._calls.get(device_id)
            if call is not None and checked_at >= call.expires_at:
                self._calls.pop(device_id, None)
                return None
            return call

    def close(self, device_id: str) -> bool:
        with self._lock:
            return self._calls.pop(device_id, None) is not None

    def command(self, device_id: str, text: str, *, now: float | None = None) -> str | None:
        if self.current(device_id, now=now) is None:
            return None
        if _ANSWER.fullmatch(text or ""):
            return "call_answer"
        if _REJECT.fullmatch(text or ""):
            return "call_reject"
        return None

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()


def sanitize_caller(raw: Mapping[str, object]) -> dict[str, object]:
    """Return only caller fields safe to leave the phone.

    A full number is rejected rather than silently truncated here: only the
    phone has the source number and therefore only the phone can reliably
    decide which final 3--4 digits may leave the device.
    """
    unknown = set(raw) - _CALLER_KEYS
    if unknown:
        raise ValueError(f"unsupported caller fields: {sorted(unknown)}")

    clean: dict[str, object] = {}
    contact_id = raw.get("contact_id")
    if contact_id is not None:
        value = str(contact_id).strip()
        if not value or len(value) > 128:
            raise ValueError("invalid contact_id")
        clean["contact_id"] = value

    name = raw.get("name")
    if name is not None:
        value = " ".join(str(name).split())
        digits = re.sub(r"\D", "", value)
        if not value or len(value) > 80 or len(digits) >= 5:
            raise ValueError("invalid or phone-like caller name")
        clean["name"] = value

    number_tail = raw.get("number_tail")
    if number_tail is not None:
        value = str(number_tail).strip()
        if not re.fullmatch(r"\d{3,4}", value):
            raise ValueError("number_tail must contain exactly 3 or 4 digits")
        clean["number_tail"] = value

    duplicate_name = raw.get("duplicate_name")
    if duplicate_name is not None:
        if not isinstance(duplicate_name, bool):
            raise ValueError("duplicate_name must be boolean")
        clean["duplicate_name"] = duplicate_name
    return clean


def announcement_for(caller: Mapping[str, object]) -> str | None:
    """Build the privacy-safe Vietnamese phrase represented by ``caller``.

    An empty caller means the host applied ``announce_caller=ring_only``.
    A contact id without a name means ``number_only`` for a known contact.
    """
    if not caller:
        return None

    name = str(caller.get("name") or "").strip()
    tail = str(caller.get("number_tail") or "").strip()
    spoken_tail = " ".join(_DIGIT_WORDS[digit] for digit in tail) if tail else ""

    if name:
        if caller.get("duplicate_name") and spoken_tail:
            return f"Có cuộc gọi từ {name}, đuôi {spoken_tail}, đang gọi."
        return f"Có cuộc gọi từ {name} đang gọi."
    if spoken_tail:
        label = "Số gọi đến" if caller.get("contact_id") else "Số lạ"
        return f"{label}, đuôi {spoken_tail}."
    return None


incoming_calls = IncomingCallRegistry(window_seconds=config.INCOMING_CALL_WINDOW_SECONDS)
