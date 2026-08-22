"""Per-device Server-Sent Events channel for glasses downlink."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import queue
import threading
import uuid

import config


_EVENT_TYPES = frozenset({"frame_request", "call_incoming", "ping"})


class EventHub:
    """Fan out bounded events only to subscribers of the addressed device."""

    def __init__(self, *, heartbeat_seconds: float = 15.0, queue_size: int = 8) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._heartbeat_seconds = heartbeat_seconds
        self._queue_size = queue_size
        self._lock = threading.Lock()
        self._subscribers: dict[str, dict[str, queue.Queue[dict[str, object]]]] = {}

    def subscribe(self, device_id: str) -> Iterator[str]:
        if not device_id:
            raise ValueError("device_id is required")
        token = uuid.uuid4().hex
        inbox: queue.Queue[dict[str, object]] = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.setdefault(device_id, {})[token] = inbox

        def stream() -> Iterator[str]:
            try:
                while True:
                    try:
                        event = inbox.get(timeout=self._heartbeat_seconds)
                    except queue.Empty:
                        event = {"type": "ping"}
                    yield self._encode(event)
            finally:
                self._unsubscribe(device_id, token)

        return stream()

    def publish(self, device_id: str, event: Mapping[str, object]) -> int:
        event_type = event.get("type")
        if event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported event type: {event_type!r}")
        payload = dict(event)
        with self._lock:
            inboxes = tuple(self._subscribers.get(device_id, {}).values())
        for inbox in inboxes:
            try:
                inbox.put_nowait(payload)
            except queue.Full:
                # A disconnected/slow board must not grow memory without bound.
                try:
                    inbox.get_nowait()
                except queue.Empty:
                    pass
                inbox.put_nowait(payload)
        return len(inboxes)

    def request_frame(self, device_id: str, turn_id: str, *, tier: str = "high") -> int:
        if not turn_id:
            raise ValueError("turn_id is required")
        return self.publish(
            device_id,
            {"type": "frame_request", "turn_id": turn_id, "tier": tier},
        )

    def call_incoming(self, device_id: str, caller: Mapping[str, object]) -> int:
        return self.publish(
            device_id,
            {"type": "call_incoming", "caller": dict(caller)},
        )

    def subscriber_count(self, device_id: str | None = None) -> int:
        with self._lock:
            if device_id is not None:
                return len(self._subscribers.get(device_id, {}))
            return sum(len(items) for items in self._subscribers.values())

    def queued_count(self, device_id: str) -> int:
        with self._lock:
            return sum(q.qsize() for q in self._subscribers.get(device_id, {}).values())

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()

    def _unsubscribe(self, device_id: str, token: str) -> None:
        with self._lock:
            device_subscribers = self._subscribers.get(device_id)
            if device_subscribers is None:
                return
            device_subscribers.pop(token, None)
            if not device_subscribers:
                self._subscribers.pop(device_id, None)

    @staticmethod
    def _encode(event: Mapping[str, object]) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"


events = EventHub(
    heartbeat_seconds=config.EVENT_HEARTBEAT_SECONDS,
    queue_size=config.EVENT_QUEUE_SIZE,
)
