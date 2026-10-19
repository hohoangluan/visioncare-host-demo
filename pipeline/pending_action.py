"""Lệnh chờ theo thiết bị cho làn D (hành động có tác dụng phụ).

Làn D đọc lại lệnh cho người dùng nghe rồi MỚI thi hành (gọi điện, mở bản đồ...).
Trong khoảng chờ đó, nếu kính bắt đầu lượt mới hoặc ngắt kết nối thì lệnh phải
bị huỷ — thi hành lệnh đã bị huỷ là lỗi an toàn. Mỗi thiết bị tối đa một lệnh
chờ; lệnh mới thay lệnh cũ. Mọi thao tác dưới một khoá nên schedule/cancel
chạy đua nhau cũng không bao giờ để fn đã huỷ chạy.
"""

import logging
import threading
from typing import Callable, Dict

import config
from pipeline import tts

log = logging.getLogger("pending_action")

_lock = threading.Lock()
_pending: Dict[str, "PendingAction"] = {}


class PendingAction:
    def __init__(self, device: str, fn: Callable[[], None], label: str):
        self.device = device
        self.label = label
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
        try:
            self._fn()
        except Exception:
            log.exception("làn D: lệnh chờ %s lỗi", self.label)


def schedule(device: str, delay_s: float, fn: Callable[[], None],
             label: str) -> PendingAction:
    action = PendingAction(device, fn, label)
    timer = threading.Timer(max(0.0, delay_s), action._run)
    timer.daemon = True
    action._timer = timer
    with _lock:
        old = _pending.get(device)
        if old is not None:
            _cancel_locked(old, "lệnh mới thay thế")
        _pending[device] = action
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
