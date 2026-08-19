"""Thread-safe callback registry for phone action results.

The HTTP callback handler runs on FastAPI's event loop while audio/action
handlers run in worker threads.  ``threading.Event`` bridges those two paths
without polling the app server on the latency-sensitive first second.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger("blind_assist")

_ENTRY_TTL_SECONDS = 15 * 60


@dataclass(slots=True)
class _Entry:
    operation: str
    registered_at: float
    on_result: Callable[[dict], None]
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    resolved_at: float | None = None


class ActionCallbackRegistry:
    """Map request IDs to waiters and retain late results for reconciliation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def _prune_locked(self, now: float) -> None:
        expired = [
            request_id
            for request_id, entry in self._entries.items()
            if now - entry.registered_at > _ENTRY_TTL_SECONDS
        ]
        for request_id in expired:
            self._entries.pop(request_id, None)

    def register(
        self,
        request_id: str,
        operation: str,
        on_result: Callable[[dict], None],
        *,
        registered_at: float | None = None,
    ) -> None:
        now = registered_at if registered_at is not None else time.monotonic()
        with self._lock:
            self._prune_locked(now)
            self._entries[request_id] = _Entry(operation, now, on_result)

    def move(self, old_request_id: str, new_request_id: str) -> None:
        """Re-key an entry if a test/legacy peer returned a different ID."""
        if old_request_id == new_request_id:
            return
        with self._lock:
            entry = self._entries.pop(old_request_id, None)
            if entry is not None:
                self._entries[new_request_id] = entry

    def resolve(self, request_id: str, data: dict) -> bool:
        """Store one terminal result; duplicate callbacks are idempotent."""
        callback: Callable[[dict], None] | None = None
        resolved: dict | None = None
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            entry = self._entries.get(request_id)
            if entry is None:
                logger.info("Callback arrived for unregistered request_id=%s", request_id)
                return False
            if entry.result is not None:
                return True
            resolved = dict(data)
            elapsed_ms = round((now - entry.registered_at) * 1000, 3)
            resolved["server_e2e_ms"] = elapsed_ms
            resolved["slo_missed"] = elapsed_ms >= 1000.0
            entry.result = resolved
            entry.resolved_at = now
            callback = entry.on_result
            entry.event.set()

        if callback is not None and resolved is not None:
            try:
                callback(resolved)
            except Exception:  # noqa: BLE001 - state update must not reject callback
                logger.exception("Late state reconciliation failed for request_id=%s", request_id)
        return True

    def wait(self, request_id: str, timeout_seconds: float) -> dict | None:
        with self._lock:
            entry = self._entries.get(request_id)
        if entry is None:
            return None
        entry.event.wait(max(0.0, timeout_seconds))
        with self._lock:
            return dict(entry.result) if entry.result is not None else None

    def reset(self) -> None:
        """Clear registry state for tests and process reset."""
        with self._lock:
            self._entries.clear()


action_callbacks = ActionCallbackRegistry()
