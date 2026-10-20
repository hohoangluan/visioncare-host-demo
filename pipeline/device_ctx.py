"""Thiết bị đang được phục vụ trong lượt hiện tại (ContextVar).

Hai kính cùng lúc không được dùng chung lịch sử chat, trạng thái nhạc/chỉ đường
hay id chờ. Thay vì luồn tham số `device` qua mọi chữ ký handler (test cũ gọi
không có nó), mỗi kho trạng thái là `dict[device, ...]` và đọc khoá từ đây.
Thread mới KHÔNG tự thừa kế ContextVar, nên mọi thread nền chạy code handler phải
khởi động bằng `run_in_thread` (copy context lúc tạo).
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Callable, Iterator

import config

current: contextvars.ContextVar[str] = contextvars.ContextVar(
    "device_id", default=config.VISIONCARE_DEVICE_ID
)

# Phiên/request này xác thực bằng token RIÊNG của kính `current` (không phải token dùng chung)?
# Mặc định False = an toàn: gọi điện/nhắn tin/khẩn cấp (Plan 2 C5–C7) chỉ chạy khi True.
# Nơi xác thực (`DeviceSession.run`, endpoint HTTP) đặt cùng lúc với `current`; thread nền thừa kế qua `run_in_thread`.
per_device: contextvars.ContextVar[bool] = contextvars.ContextVar("per_device", default=False)

# Id lượt đang chạy, để mọi dòng log của lượt mang theo (pipeline/metrics.TurnLogFilter).
turn: contextvars.ContextVar[str] = contextvars.ContextVar("turn_id", default="")


# request_id của action điện thoại đang chạy trong thread nền làn D (`action_flow.run_action` đặt),
# để câu kết quả đẩy xuống kính mang turn id `result-<request_id>`.
action_request: contextvars.ContextVar[str] = contextvars.ContextVar("action_request", default="")


# Móc "câu sắp vào TTS" cho khung debug của demo (`live/device_session.py` đặt khi hello có `debug`):
# `hook(turn_id, text)`, gọi được từ thread bất kỳ. None = tắt (kính thật).
say: contextvars.ContextVar[Callable[[str, str], None] | None] = contextvars.ContextVar("say_hook", default=None)


def announce(text: str) -> None:
    """Báo câu `text` sắp được đọc (nếu phiên đang bật debug). Lỗi của móc không bao giờ cản TTS."""
    hook = say.get()
    if hook is None or not text.strip():
        return
    try:
        hook(turn.get(), text.strip())
    except Exception:  # noqa: BLE001
        pass


@contextlib.contextmanager
def use(device: str) -> Iterator[None]:
    token = current.set(device or config.VISIONCARE_DEVICE_ID)
    try:
        yield
    finally:
        current.reset(token)


def run_in_thread(fn: Callable, *args, name: str | None = None) -> threading.Thread:
    """Tạo + chạy daemon thread giữ nguyên device của luồng gọi."""
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=ctx.run, args=(fn, *args), name=name, daemon=True)
    thread.start()
    return thread
