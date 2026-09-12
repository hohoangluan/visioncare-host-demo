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
    # 🔴 Field `tier` đã XOÁ 2026-08-26 cùng toàn bộ F5. Board gửi đúng một
    # loại ảnh (XGA 1024×768) cho mọi lượt bấm nút, nên không còn gì để phân
    # tầng. Nếu bao giờ cần lại: đừng suy tầng từ kích thước byte — một cảnh
    # tối, phẳng ở HD nén ra nhỏ hơn một cảnh nhiều chi tiết ở VGA. Board phải
    # tự khai.


class FrameBuffer:
    def __init__(self, ring_size: int = 3) -> None:
        if not 1 <= ring_size <= 3:
            raise ValueError("frame ring_size must be between 1 and 3")
        self._ring_size = ring_size
        self._frames: dict[str, deque[Frame]] = defaultdict(
            lambda: deque(maxlen=self._ring_size)
        )
        # T24/W2: một khung mới nhất cho mỗi thiết bị, tách hẳn khỏi ring trên.
        # Xem khối ghi chú ở `put_hazard()`.
        self._hazard: dict[str, Frame] = {}
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

    def latest_frame(
        self,
        device_id: str,
        max_age_ms: float,
        *,
        turn_id: str | None = None,
    ) -> Frame | None:
        """Như `latest()` nhưng trả cả siêu dữ liệu (`capture_ts`, `received_at`).

        Không chờ: bên gọi đã có khung trong tay rồi mới hỏi siêu dữ liệu.
        Dùng cho chẩn đoán và cho `/devices` — F5 (người gọi cũ) đã xoá.
        """
        now = time.monotonic()
        with self._condition:
            for frame in reversed(self._frames.get(device_id, ())):
                if turn_id is not None and frame.turn_id != turn_id:
                    continue
                if (now - frame.received_at) * 1000.0 <= max_age_ms:
                    return frame
                return None
        return None

    def snapshot(self, device_id: str) -> tuple[Frame, ...]:
        with self._condition:
            return tuple(self._frames.get(device_id, ()))

    def clear(self) -> None:
        with self._condition:
            self._frames.clear()
            self._hazard.clear()
            self._condition.notify_all()

    # ─── T24/W2: khung của luồng canh vật cản ─────────────────────────────
    #
    # Ô RIÊNG, giữ đúng MỘT khung mới nhất cho mỗi thiết bị — không dùng chung
    # ring 1-3 khung của lượt hỏi-đáp. Ba lý do, mỗi lý do là một cách hỏng:
    #
    #  1. Khung canh vật cản KHÔNG có `turn_id` (nó không thuộc lượt nào cả).
    #     Nhét vào ring chung thì `latest(turn_id=...)` của T17 phải bỏ qua
    #     chúng, và `test_frame_matched_by_turn_id` là chỗ vỡ đầu tiên.
    #  2. Luồng canh chạy vài khung MỖI GIÂY. Nó sẽ đẩy văng khung của lượt
    #     hỏi-đáp ra khỏi ring 3 chỗ trước khi handler kịp đọc.
    #  3. Worker chấm điểm chạy chậm hơn tốc độ khung tới. "Ô một chỗ, luôn là
    #     khung mới nhất" chính là chiến lược latest-frame của OD_module gốc —
    #     xử một khung cũ 2 giây là báo về một vật cản người dùng đã đi qua.

    def put_hazard(
        self,
        device_id: str,
        data: bytes,
        *,
        capture_ts: str | None = None,
        received_at: float | None = None,
    ) -> None:
        if not device_id or not data:
            raise ValueError("device_id and frame data are required")
        frame = Frame(
            data=bytes(data),
            # Chuỗi rỗng chứ không phải None: `Frame.turn_id` là `str`, và một
            # `None` lọt vào đây sẽ khớp với `turn_id=None` của `latest()`.
            turn_id="",
            received_at=time.monotonic() if received_at is None else received_at,
            capture_ts=capture_ts,
        )
        with self._condition:
            self._hazard[device_id] = frame
            self._condition.notify_all()

    def latest_hazard(self, device_id: str, max_age_ms: float) -> bytes | None:
        with self._condition:
            frame = self._hazard.get(device_id)
            if frame is None:
                return None
            age_ms = (time.monotonic() - frame.received_at) * 1000.0
            return frame.data if age_ms <= max_age_ms else None

    def drop_hazard(self, device_id: str) -> None:
        """Bỏ khung đang giữ khi tắt chế độ canh.

        Không bỏ thì bật lại chế độ sau đó sẽ chấm điểm trên một khung cũ —
        và mức đầu tiên người dùng nghe được là mức của phòng họ đứng lúc
        trước, không phải chỗ họ đang đứng.
        """
        with self._condition:
            self._hazard.pop(device_id, None)


frames = FrameBuffer(ring_size=3)
