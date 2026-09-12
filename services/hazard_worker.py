"""T24/W5 — chấm khung canh vật cản và trả mức về ngay trong response.

Mảnh còn thiếu của T24. Trước file này cả đường dây đã có mặt nhưng **không
nối vào nhau**: `risk_engine.evaluate()`, `frames.latest_hazard()` và
`events.hazard_level()` không có một lời gọi nào trong mã production. Board
chụp, server cất khung vào bộ đệm, rồi thôi — người dùng nghe *"Đã bật chế độ
cảnh báo vật cản."* rồi im lặng vĩnh viễn.

🔴 Vì sao chấm ĐỒNG BỘ trong `POST /frame`, không phải một vòng lặp nền
--------------------------------------------------------------------------
Bản đầu của file này là một worker quét theo nhịp, vì lúc đó board đẩy khung
**fire-and-forget** (không đọc status). Chấm tại chỗ khi đó sẽ giữ request lại
236 ms trong lúc board đã bắn khung kế tiếp — vài giây là uvicorn đầy worker
và `/process` (đường bấm nút, thứ KHÔNG được phép chậm) xếp hàng sau một đống
ảnh.

Hợp đồng đã đổi (2026-08-25): board **chờ response** và đọc mức nguy hiểm từ
chính thân 200 đó. Đổi này giết luôn cái đắt nhất của vòng canh — bắt tay TLS
**616–911 ms mỗi khung**, vì `Connection: close` là bắt buộc khi mức phải về
bằng SSE (hai phiên TLS cùng lúc cần ~90 KB LIỀN, mà khối liền lớn nhất còn
77 812 B). Một phiên keep-alive vừa đủ RAM, và bắt tay biến mất khỏi vòng lặp.

Hệ quả: mỗi thiết bị chỉ có **đúng một** request đang bay. Board tự điều tiết
— server chậm thì fps tự tụt, không dồn hàng. Đó chính là tính chất mà vòng
lặp nền phải cố công dựng lại bằng "bỏ khung, không dồn hàng".

Mức vẫn được đẩy kèm qua SSE khi ĐỔI
------------------------------------
Thừa với board bản mới, nhưng giữ vì hai lý do: bản firmware cũ (ota10 trở về
trước) chỉ biết đường SSE, và `hazard_level` là thứ duy nhất cho phép server
hạ mức khi board ngừng gửi khung.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading

import config
from services.hazard_risk import risk_engine

logger = logging.getLogger("blind_assist.hazard_worker")


class HazardWorker:
    """Sổ thiết bị đang canh + chấm một khung thành một mức.

    Không tự hỏi `action_flow` xem thiết bị nào đang bật: `handlers/
    hazard_watch.py` gọi thẳng `watch()`/`unwatch()`. Cùng lý do
    `publish_level()` được tách khỏi `RiskEngine` — máy chấm điểm không biết gì
    về SSE, và worker không biết gì về session.
    """

    def __init__(
        self,
        *,
        engine=risk_engine,
        publish: Callable[[str, str, bool], int] | None = None,
        stop_watch: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._publish = publish
        self._stop_watch = stop_watch
        self._lock = threading.Lock()
        self._devices: set[str] = set()
        self._failures: dict[str, int] = {}
        # Đếm để log nói ra thay vì im.
        self.scored = 0
        self.errors = 0

    def set_sinks(
        self,
        publish: Callable[[str, str, bool], int] | None,
        stop_watch: Callable[[str], None] | None = None,
    ) -> None:
        """Nối hai đường ra. Gọi từ `handlers/hazard_watch.py` lúc nhập module.

        Không nhập thẳng ở đầu file vì `handlers.hazard_watch` đã nhập module
        này — nhập ngược là vòng tròn. Đổi chiều phụ thuộc (worker không biết
        handler, handler tự cắm mình vào) rẻ hơn một lời gọi `import` trễ nằm
        trong đường nóng.
        """
        self._publish = publish
        self._stop_watch = stop_watch

    # ── sổ thiết bị ───────────────────────────────────────────────────────
    def watch(self, device_id: str) -> None:
        with self._lock:
            self._devices.add(device_id)
            self._failures.pop(device_id, None)

    def unwatch(self, device_id: str) -> None:
        with self._lock:
            self._devices.discard(device_id)
            self._failures.pop(device_id, None)

    def watching(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._devices)

    # ── chấm một khung ────────────────────────────────────────────────────
    def score_frame(self, device_id: str, jpeg: bytes) -> tuple[str, bool] | None:
        """Chấm MỘT khung. Trả `(mức, có đổi không)`, hoặc `None` nếu không chấm.

        `None` có hai nghĩa và bên gọi phân biệt được bằng `watching()`: thiết
        bị không đăng ký canh, hoặc lượt chấm này hỏng.

        KHÔNG ném ra ngoài. Một lỗi chấm điểm không được phép làm hỏng request
        đẩy khung — nhưng nó cũng không được im: đếm vào `_failures`, và đủ
        `HAZARD_WATCH_MAX_FAILURES` lần liên tiếp thì tắt hẳn thiết bị đó.
        """
        if device_id not in self.watching():
            return None

        try:
            level, changed = self._engine.evaluate(device_id, jpeg)
        except Exception as exc:  # noqa: BLE001 — không được làm hỏng request
            self.errors += 1
            count = self._note_failure(device_id)
            logger.warning(
                "hazard: chấm hỏng cho %s (lần %d/%d): %s",
                device_id, count, config.HAZARD_WATCH_MAX_FAILURES, exc,
            )
            if count >= config.HAZARD_WATCH_MAX_FAILURES:
                self._give_up(device_id)
            return None

        self._clear_failure(device_id)
        self.scored += 1
        if changed:
            logger.info("hazard: %s -> %s", device_id, level)
            if self._publish is not None:
                # Thừa với board bản mới (nó đọc mức từ thân response), giữ cho
                # board bản cũ và cho ca server tự hạ mức. Chỉ gửi khi ĐỔI —
                # hàng đợi SSE mỗi thiết bị có 8 chỗ, gửi mỗi khung sẽ đẩy văng
                # `call_incoming`.
                self._publish(device_id, level, changed)
        return level, changed

    def _note_failure(self, device_id: str) -> int:
        with self._lock:
            count = self._failures.get(device_id, 0) + 1
            self._failures[device_id] = count
            return count

    def _clear_failure(self, device_id: str) -> None:
        with self._lock:
            self._failures.pop(device_id, None)

    def _give_up(self, device_id: str) -> None:
        """🔴 Fail-closed lần hai.

        `handlers/hazard_watch.py` đã chặn ca "không có model" lúc BẬT, nhưng
        detector còn hỏng được giữa chừng (hết RAM, ONNX ném lỗi trên một khung
        méo). Cứ nuốt lỗi và chạy tiếp nghĩa là người dùng vẫn tin mình đang
        được canh trong khi không ai chấm gì — đúng cái nguy hiểm nhất.
        """
        logger.error(
            "hazard: %s hỏng %d lần liên tiếp — TẮT chế độ canh. Board sẽ thôi "
            "chụp; người dùng KHÔNG còn được canh nữa.",
            device_id, config.HAZARD_WATCH_MAX_FAILURES,
        )
        self.unwatch(device_id)
        if self._stop_watch is not None:
            try:
                self._stop_watch(device_id)
            except Exception:  # noqa: BLE001
                logger.exception("hazard: không tắt được chế độ trên board")


worker = HazardWorker()
