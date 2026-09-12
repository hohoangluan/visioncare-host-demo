"""Per-device incoming-call state and privacy-safe caller announcements."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
import threading
import time

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

# Keep the reusable text explicit, but do not synthesize and concatenate these
# fragments independently.  The current TTS cache is sentence-granular and
# joining separately spoken fragments changes the pause and intonation around
# the caller name.  ``IncomingCallAudioCache`` therefore caches the complete,
# naturally spoken announcement after its first use.
_KNOWN_CALL_PREFIX = "Có cuộc gọi từ "
_KNOWN_CALL_SUFFIX = " đang gọi."
INCOMING_CALL_STATIC_PARTS = (_KNOWN_CALL_PREFIX, _KNOWN_CALL_SUFFIX)


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


class IncomingCallAudioCache:
    """Bounded PCM cache keyed by caller identity and the safe spoken phrase.

    Including both fields is intentional: ``contact_id`` prevents two caller
    records from sharing an entry, while the complete announcement separates
    privacy policies and later name/tail changes for the same contact.
    """

    def __init__(self, *, max_entries: int = 128) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._pcm: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    def get_or_create(
        self,
        caller: Mapping[str, object],
        render: Callable[[str], bytes],
    ) -> bytes | None:
        announcement = announcement_for(caller)
        if announcement is None:
            return None
        key = (str(caller.get("contact_id") or ""), announcement)

        # VieNeu uses one shared inference session and the normal TTS pipeline
        # already serializes its work.  Keeping the lock through this rare,
        # short announcement also prevents simultaneous pulls from rendering
        # the same contact twice before either can populate the cache.
        with self._lock:
            cached = self._pcm.get(key)
            if cached is not None:
                self._pcm.move_to_end(key)
                return cached

            pcm = render(announcement)
            if not pcm:
                raise ValueError("incoming-call TTS returned no audio")
            self._pcm[key] = pcm
            self._pcm.move_to_end(key)
            while len(self._pcm) > self._max_entries:
                self._pcm.popitem(last=False)
            return pcm

    def clear(self) -> None:
        with self._lock:
            self._pcm.clear()


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
            return f"{_KNOWN_CALL_PREFIX}{name}, đuôi {spoken_tail}, đang gọi."
        return f"{_KNOWN_CALL_PREFIX}{name}{_KNOWN_CALL_SUFFIX}"
    if spoken_tail:
        label = "Số gọi đến" if caller.get("contact_id") else "Số lạ"
        return f"{label}, đuôi {spoken_tail}."
    return None


incoming_calls = IncomingCallRegistry(window_seconds=config.INCOMING_CALL_WINDOW_SECONDS)
incoming_call_audio = IncomingCallAudioCache()
