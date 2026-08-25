"""Per-device Server-Sent Events channel for glasses downlink."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import queue
import threading
import uuid

import config


# Danh sách đóng, không phải gợi ý: `publish()` từ chối mọi loại lạ. Kính chỉ
# biết xử lý đúng những loại này (`onDeviceEvent()` trong sketch), nên một loại
# gõ sai sẽ đi tới board rồi rơi vào im lặng — bắt ở đây thì lỗi lộ ra ngay tại
# chỗ gọi sai.
_EVENT_TYPES = frozenset(
    {
        "frame_request",
        "call_incoming",
        "call_ended",
        "ping",
        # T25: server chủ động yêu cầu kính nạp bản mới. Sự kiện KHÔNG mang
        # theo byte firmware nào — chỉ báo "có bản mới", kính tự gọi
        # `GET /firmware/manifest` rồi `GET /firmware/bin`. Đẩy 1.35 MB qua
        # kênh SSE sẽ chặn hàng đợi của mọi sự kiện khác trong hàng chục giây,
        # trong đó có `call_incoming`.
        "firmware_update",
        # T25: app đổi Wi-Fi cho kính từ xa. Kính lưu vào NVS rồi tự khởi động
        # lại — sau đó nó nối vào mạng MỚI, nên sự kiện này luôn là điều cuối
        # cùng đi qua kênh cũ.
        "wifi_config",
        # T24/W3: bật/tắt vòng chụp liên tục trên board.
        "hazard_watch",
        # T24/W3: mức nguy hiểm hiện tại. Gửi MỖI KHI ĐỔI MỨC, không phải mỗi
        # khung hình — hàng đợi mỗi thiết bị chỉ có 8 chỗ, và gửi mỗi khung sẽ
        # đẩy văng `call_incoming` ra khỏi hàng.
        #
        # 🔴 KHÔNG mang byte audio nào. Board tự sinh tông theo mức (W6), cùng
        # triết lý G8: tông cục bộ rẻ và nhanh hơn audio qua mạng, và ở đây
        # còn quan trọng hơn — cảnh báo vật cản mà đi qua mạng thì độ trễ mạng
        # nằm thẳng giữa vật cản và cái chân người dùng.
        "hazard_level",
    }
)


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

    def call_ended(self, device_id: str) -> int:
        return self.publish(device_id, {"type": "call_ended"})

    def hazard_watch(self, device_id: str, action: str) -> int:
        """Bảo board bật/tắt vòng chụp liên tục (T24/W3)."""
        if action not in {"start", "stop"}:
            raise ValueError(f"hazard_watch action must be start|stop, got {action!r}")
        return self.publish(device_id, {"type": "hazard_watch", "action": action})

    def hazard_level(self, device_id: str, level: str) -> int:
        """Báo mức nguy hiểm mới (T24/W3). Chỉ gọi khi mức THẬT SỰ đổi."""
        if level not in {"SAFE", "LOW", "MEDIUM", "HIGH"}:
            raise ValueError(f"unsupported hazard level: {level!r}")
        return self.publish(device_id, {"type": "hazard_level", "level": level})

    def firmware_update(self, device_id: str, version: str) -> int:
        """Bảo một kính đi lấy bản firmware mới (T25).

        Chỉ mang tên phiên bản để kính ghi log và so với bản nó đang chạy —
        `url`/`size`/`sha256` nằm ở `GET /firmware/manifest`, là nguồn sự thật
        duy nhất. Nhét chúng vào đây nghĩa là có hai nguồn, và chúng sẽ lệch
        nhau đúng vào lúc phát hành lại một bản đã sửa.
        """
        if not version:
            raise ValueError("version is required")
        return self.publish(device_id, {"type": "firmware_update", "version": version})

    def wifi_config(self, device_id: str, ssid: str, password: str = "") -> int:
        """Gửi Wi-Fi mới xuống kính (T25).

        🔴 Mật khẩu đi qua kênh này ở dạng chữ thường. Chấp nhận được vì chặng
        server→Cloudflare→kính đã là TLS từ T22 (`API_USE_TLS 1`) — nhưng
        KHÔNG được ghi vào log. Chỗ gọi có trách nhiệm không in `password`.
        """
        if not ssid:
            raise ValueError("ssid is required")
        return self.publish(
            device_id,
            {"type": "wifi_config", "ssid": ssid, "password": password},
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
