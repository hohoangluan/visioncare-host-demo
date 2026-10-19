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
