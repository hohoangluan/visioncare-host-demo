"""Small per-device frame ring used by the split ``POST /frame`` channel."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class Frame:
    data: bytes
    turn_id: str
    received_at: float
    capture_ts: str | None = None


class FrameBuffer:
    def __init__(self, ring_size: int = 3) -> None:
        if not 1 <= ring_size <= 3:
            raise ValueError("frame ring_size must be between 1 and 3")
        self._ring_size = ring_size
        self._frames: dict[str, deque[Frame]] = defaultdict(
            lambda: deque(maxlen=self._ring_size)
        )
        self._condition = threading.Condition()

    def put(
        self,
        device_id: str,
        turn_id: str,
        data: bytes,
        *,
        capture_ts: str | None = None,
        received_at: float | None = None,
    ) -> None:
        if not device_id or not turn_id or not data:
            raise ValueError("device_id, turn_id and frame data are required")
        frame = Frame(
            data=bytes(data),
            turn_id=turn_id,
            received_at=time.monotonic() if received_at is None else received_at,
            capture_ts=capture_ts,
        )
        with self._condition:
            self._frames[device_id].append(frame)
            self._condition.notify_all()

    def latest(
        self,
        device_id: str,
        max_age_ms: float,
        *,
        turn_id: str | None = None,
        wait_ms: float = 0,
    ) -> bytes | None:
        """Return the newest matching fresh frame, optionally waiting briefly.

        Reception monotonic time is authoritative. ``X-Capture-Ts`` is retained
        for diagnostics only because the board and server clocks are not
        guaranteed to be synchronized.
        """
        deadline = time.monotonic() + max(0.0, wait_ms) / 1000.0
        with self._condition:
            while True:
                now = time.monotonic()
                ring = self._frames.get(device_id, ())
                for frame in reversed(ring):
                    if turn_id is not None and frame.turn_id != turn_id:
                        continue
                    age_ms = (now - frame.received_at) * 1000.0
                    return frame.data if age_ms <= max_age_ms else None
                remaining = deadline - now
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def snapshot(self, device_id: str) -> tuple[Frame, ...]:
        with self._condition:
            return tuple(self._frames.get(device_id, ()))

    def clear(self) -> None:
        with self._condition:
            self._frames.clear()
            self._condition.notify_all()


frames = FrameBuffer(ring_size=3)
