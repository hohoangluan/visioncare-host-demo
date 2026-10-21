"""Lệnh chờ theo thiết bị cho làn D (hành động có tác dụng phụ).

Làn D đọc lại lệnh cho người dùng nghe rồi MỚI thi hành (gọi điện, mở bản đồ...).
Trong khoảng chờ đó, nếu kính bắt đầu lượt mới hoặc ngắt kết nối thì lệnh phải
bị huỷ — thi hành lệnh đã bị huỷ là lỗi an toàn. Mỗi thiết bị tối đa một lệnh
chờ; lệnh mới thay lệnh cũ. Mọi thao tác dưới một khoá nên schedule/cancel
chạy đua nhau cũng không bao giờ để fn đã huỷ chạy.
"""

import logging
import threading
import time
from typing import Callable, Dict

import config
from pipeline import device_ctx, tts

log = logging.getLogger("pending_action")

_lock = threading.Lock()
_pending: Dict[str, "PendingAction"] = {}
_generation: Dict[str, int] = {}
# device -> lúc một lệnh chờ bị lượt mới huỷ (chưa kịp chạy). Để lượt "Không"/"Thôi" đứng một mình biết mình
# vừa huỷ được lệnh nào đó và nói "Đã huỷ" thay vì "chưa hỏi gì".
_cancelled_by_turn: Dict[str, float] = {}
_RECENT_CANCEL_S = 20.0


def begin_turn(device: str) -> int:
    """Lượt mới của `device`: tăng thế hệ rồi huỷ lệnh chờ, dưới cùng một khoá.

    Lượt cũ còn đang trong router không được phép schedule sau đây — `schedule`
    so thế hệ nó mang theo với thế hệ hiện tại và từ chối nếu đã cũ.
    """
    with _lock:
        _generation[device] = _generation.get(device, 0) + 1
        gen = _generation[device]
    if cancel(device, "lượt mới"):
        with _lock:
            _cancelled_by_turn[device] = time.monotonic()
    return gen


def take_recent_cancel(device: str) -> bool:
    """Lượt hiện tại vừa huỷ một lệnh chờ chưa chạy? Lấy ra (dùng một lần)."""
    with _lock:
        at = _cancelled_by_turn.pop(device, None)
    return at is not None and time.monotonic() - at <= _RECENT_CANCEL_S


def generation(device: str) -> int:
    with _lock:
        return _generation.get(device, 0)


class PendingAction:
    def __init__(self, device: str, fn: Callable[[], None], label: str):
        self.device = device
        self.label = label
        # Chụp lúc tạo: Timer chạy ở thread mới, mất ContextVar. Chỉ giữ khi lệnh đặt cho đúng kính của luồng này.
        self.per_device = device_ctx.per_device.get() and device == device_ctx.current.get()
        self.fired = threading.Event()
        self.cancelled = threading.Event()
        self._fn = fn
        self._timer: threading.Timer | None = None

    def _run(self) -> None:
        # Quyết định "chạy hay không" và đánh dấu fired trong cùng một khoá với
        # cancel(): sau khi cancel() trả True, fn chắc chắn không chạy.
        with _lock:
            if self.cancelled.is_set():
                return
            if _pending.get(self.device) is self:
                del _pending[self.device]
            self.fired.set()
        # `threading.Timer` chạy trong thread mới với ContextVar mặc định: không đặt lại thì
        # `run_background` copy nhầm kính mặc định và lệnh gọi/chỉ đường đi về sai kính
        # (bench_load 2026-10-19: GLASSES_DEVICE_NOT_LINKED device_id=glasses-123).
        try:
            with device_ctx.use(self.device, self.per_device):
                self._fn()
        except Exception:
            log.exception("làn D: lệnh chờ %s lỗi", self.label)


    def arm(self, delay_s: float) -> bool:
        """Bắt đầu đếm ngược (lệnh đặt với `delay_s=None`). Gọi đúng lúc khối audio đọc lại ĐẦU TIÊN rời
        server tới kính. Đã huỷ/đã chạy/đã armed rồi -> False và không làm gì."""
        with _lock:
            if self.cancelled.is_set() or self.fired.is_set() or self._timer is not None:
                return False
            timer = threading.Timer(max(0.0, delay_s), self._run)
            timer.daemon = True
            self._timer = timer
            timer.start()
            return True


def schedule(device: str, delay_s: float | None, fn: Callable[[], None],
             label: str, gen: int | None = None) -> PendingAction | None:
    """Đặt lệnh chờ. `gen` cũ (đã có lượt mới hơn) -> từ chối, trả None.

    `delay_s=None`: lệnh nằm trong hàng chờ (huỷ được, bị lệnh mới thay) nhưng CHƯA đếm ngược; `arm()` mới
    bắt đầu đếm. Không bao giờ armed (audio đọc lại không tới kính) thì lệnh không chạy — fail closed.
    """
    action = PendingAction(device, fn, label)
    with _lock:
        if gen is not None and gen != _generation.get(device, 0):
            log.info("làn D bỏ %s: lượt đã cũ", label)
            return None
        old = _pending.get(device)
        if old is not None:
            _cancel_locked(old, "lệnh mới thay thế")
        _pending[device] = action
        if delay_s is not None:
            timer = threading.Timer(max(0.0, delay_s), action._run)
            timer.daemon = True
            action._timer = timer
            timer.start()
    return action


def _cancel_locked(action: PendingAction, reason: str) -> None:
    action.cancelled.set()
    if action._timer is not None:
        action._timer.cancel()
    log.info("làn D huỷ %s: %s", action.label, reason)


def cancel(device: str, reason: str) -> bool:
    with _lock:
        action = _pending.pop(device, None)
        if action is None or action.fired.is_set():
            return False
        _cancel_locked(action, reason)
        return True


def readback_delay(text: str) -> float:
    """Thời gian đọc xong `text` + đệm đầu phát + biên an toàn."""
    return (tts.speaking_seconds(text) + config.V2_AUDIO_PREROLL_SECONDS
            + config.ACTION_READBACK_MARGIN_S)
