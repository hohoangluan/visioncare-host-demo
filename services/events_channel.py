"""Per-device downlink mailbox drained by ``GET /downlink``.

🔴 ĐỔI 2026-08-26: đây TỪNG là kênh SSE thường trực (`GET /events`). Không còn.

Vì sao bỏ, đo trực tiếp trên `glasses-01` bằng `memWatchLargest()`:

    trước mọi thứ                khối liền  114 676 B
    sau MỘT phiên TLS                        69 620 B   (−45 056)
    sau khi cấp phát audio                   34 804 B

Một phiên TLS ngốn 45 056 B RAM **liền**, `/events` ngốn thêm 37 888 B. Board
không giữ nổi cả hai, nên mỗi lần khởi động nó hy sinh `/events` — và hệ quả
đã đo được: `firmware_update` trả `pushed: 0`, còn lệnh đổi Wi-Fi rơi vào hộp
thư chết dù server vẫn đếm `subscribers: 1`.

Kênh poll giải đúng bài toán đó mà không phải rời Arduino IDE: board chỉ mở
socket khi nó RẢNH (không đang `/process`, không đang phát tiếng, không đang
OTA), nên **không bao giờ có hai phiên TLS cùng lúc**.

Một điểm kênh poll còn HƠN SSE, không chỉ ngang: hàng đợi ở đây sống độc lập
với việc có ai đang nối hay không. Sự kiện đẩy vào lúc board đang bận vẫn nằm
đó chờ lượt poll kế tiếp. SSE thì mất — `eventStreamPause()` trên board là một
khoảng mù thật sự, và đó là một đánh đổi đã ghi trong `event_stream.h` cũ.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import threading
import time

import config

logger = logging.getLogger("blind_assist.events")


# Danh sách đóng, không phải gợi ý: `publish()` từ chối mọi loại lạ. Kính chỉ
# biết xử lý đúng những loại này (`onDeviceEvent()` trong sketch), nên một loại
# gõ sai sẽ đi tới board rồi rơi vào im lặng — bắt ở đây thì lỗi lộ ra ngay tại
# chỗ gọi sai.
_EVENT_TYPES = frozenset(
    {
        # T25: server chủ động yêu cầu kính nạp bản mới. Sự kiện KHÔNG mang
        # theo byte firmware nào — chỉ báo "có bản mới", kính tự gọi
        # `GET /firmware/manifest` rồi `GET /firmware/bin`.
        "firmware_update",
        # T25: app đổi Wi-Fi cho kính từ xa. Kính lưu vào NVS rồi tự khởi động
        # lại — sau đó nó nối vào mạng MỚI, nên sự kiện này luôn là điều cuối
        # cùng đi qua kênh cũ.
        "wifi_config",
        # T19/21.8: có cuộc gọi đến trên điện thoại đã ghép.
        "call_incoming",
        "call_ended",
        # T24/W3: bật/tắt vòng chụp liên tục trên board, và mức nguy hiểm
        # hiện tại.
        #
        # 🔴 2026-08-26 KHÔNG CÒN AI PHÁT hai loại này trong luồng: `hazard`
        # đã quay về `handlers/describe_hazard.py` (một câu trả lời cho một
        # khung hình, qua LLM) theo quyết định của người dùng. Giữ lại trong
        # danh sách vì `services/hazard_worker.py` và test của nó vẫn gọi tới,
        # và vì quyết định này đã đảo một lần rồi.
        "hazard_watch",
        "hazard_level",
    }
)

# 🔴 `frame_request` đã BỊ XOÁ 2026-08-26 cùng với toàn bộ F5 (hai tầng ảnh).
# Giờ mỗi lần bấm nút gửi đúng một ảnh XGA 1024×768 và `ocr` dùng luôn ảnh đó,
# không còn vòng hỏi-đáp xin tầng cao. Đừng thêm lại loại này mà không đọc
# `docs/superpowers/specs/2026-08-26-bo-sse-poll-downlink-design.md` phần 2.
#
# `ping` cũng đã xoá: nó là nhịp tim của SSE, và kênh poll không có nhịp tim
# nào để mà giữ.


class EventHub:
    """Hộp thư có giới hạn cho mỗi thiết bị, rút cạn bằng ``drain()``."""

    def __init__(self, *, queue_size: int = 8, stale_seconds: float = 10.0) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        if stale_seconds <= 0:
            raise ValueError("stale_seconds must be positive")
        self._queue_size = queue_size
        self._stale_seconds = stale_seconds
        self._lock = threading.Lock()
        # device_id -> hàng đợi FIFO các sự kiện chưa ai lấy.
        self._mailbox: dict[str, list[dict[str, object]]] = {}
        # device_id -> lần cuối thiết bị đó gọi `GET /downlink`.
        self._polled_at: dict[str, float] = {}

    # ─── phía server ghi vào ──────────────────────────────────────────────

    def publish(self, device_id: str, event: Mapping[str, object]) -> int:
        """Bỏ một sự kiện vào hộp thư. Trả về số sự kiện đang chờ SAU khi bỏ.

        🔴 Giá trị trả về ĐỔI NGHĨA 2026-08-26. Trước đây là "số subscriber
        SSE đã nhận" — tức 0 nghĩa là mất sự kiện. Giờ là "số sự kiện đang
        nằm chờ", luôn ≥ 1, vì kênh poll không đánh rơi sự kiện khi board bận.
        Muốn biết board còn sống hay không thì hỏi `downlink_open()`, KHÔNG
        suy từ số này.
        """
        event_type = event.get("type")
        if event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported event type: {event_type!r}")
        if not device_id:
            raise ValueError("device_id is required")
        payload = dict(event)
        with self._lock:
            box = self._mailbox.setdefault(device_id, [])
            box.append(payload)
            # Board rớt mạng lâu không được phép làm RAM server phình vô hạn.
            # Đầy thì bỏ cái CŨ NHẤT, giữ cái mới — y hệt chính sách của hàng
            # đợi SSE cũ. Với `call_incoming` đây là lựa chọn đúng: chuông
            # đang đổ bây giờ quan trọng hơn chuông đã tắt từ lâu.
            dropped = 0
            while len(box) > self._queue_size:
                box.pop(0)
                dropped += 1
            if dropped:
                logger.warning(
                    "downlink: hộp thư %s đầy, bỏ %d sự kiện cũ nhất",
                    device_id, dropped,
                )
            return len(box)

    # ─── phía board rút ra ────────────────────────────────────────────────

    def drain(self, device_id: str) -> list[dict[str, object]]:
        """Lấy hết sự kiện đang chờ và xoá khỏi hộp thư. Ghi nhận lượt poll.

        Rút cạn chứ không lấy từng cái: board gọi mỗi 2 giây, và trả một sự
        kiện mỗi lượt nghĩa là bốn sự kiện xếp hàng phải mất 8 giây mới đi
        hết — trong đó có thể có `call_incoming`.

        🔴 Xoá NGAY khi trả, không chờ board xác nhận. Không có ack nghĩa là
        một sự kiện có thể mất nếu board chết đúng giữa lúc nhận. Chấp nhận
        được cho cả bốn loại đang dùng: `firmware_update` sẽ được phát lại ở
        lần publish sau, `wifi_config` người dùng bấm lại, `call_incoming`
        chuông vẫn đang đổ. Thêm ack nghĩa là thêm trạng thái hai bên phải
        đồng bộ, và đó là chỗ đẻ ra bug im lặng.
        """
        if not device_id:
            raise ValueError("device_id is required")
        with self._lock:
            self._polled_at[device_id] = time.monotonic()
            return self._mailbox.pop(device_id, [])

    def downlink_open(self, device_id: str) -> bool:
        """Kính này có đang giữ kênh xuống không — tức có poll gần đây không.

        Thay cho `subscriber_count() > 0` của thời SSE. "Gần đây" là
        `DOWNLINK_STALE_SECONDS`, đặt rộng hơn nhịp poll vài lần để một nhịp
        mạng xấu không bị đọc thành "kính mất tích".
        """
        if not device_id:
            return False
        with self._lock:
            at = self._polled_at.get(device_id)
        return at is not None and (time.monotonic() - at) <= self._stale_seconds

    def last_poll_age_seconds(self, device_id: str) -> float | None:
        """Bao lâu rồi kính chưa poll. `None` nếu chưa poll lần nào."""
        with self._lock:
            at = self._polled_at.get(device_id)
        return None if at is None else time.monotonic() - at

    def queued_count(self, device_id: str) -> int:
        with self._lock:
            return len(self._mailbox.get(device_id, ()))

    def clear(self) -> None:
        with self._lock:
            self._mailbox.clear()
            self._polled_at.clear()

    # ─── đường ngắn cho từng loại sự kiện ─────────────────────────────────

    def call_incoming(self, device_id: str, caller: Mapping[str, object]) -> int:
        return self.publish(
            device_id,
            {"type": "call_incoming", "caller": dict(caller)},
        )

    def call_ended(self, device_id: str) -> int:
        return self.publish(device_id, {"type": "call_ended"})

    def hazard_watch(self, device_id: str, action: str) -> int:
        """Bảo board bật/tắt vòng chụp liên tục (T24/W3).

        Không còn ai gọi từ luồng hội thoại — xem ghi chú ở `_EVENT_TYPES`.
        """
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


events = EventHub(
    queue_size=config.EVENT_QUEUE_SIZE,
    stale_seconds=config.DOWNLINK_STALE_SECONDS,
)
