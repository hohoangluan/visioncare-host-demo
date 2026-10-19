"""Quan sát: turn id trong mọi dòng log + `turns.jsonl` (một dòng mỗi lượt).

Không có số này thì "nhả nút -> tiếng đầu" chỉ đo được bằng bench giả lập; ở đây
mỗi lượt thật ghi lại timing phía server, và mốc phía kính (khung `played`) gắn
vào cùng turn id để so hai đồng hồ.

`record_turn` chỉ `put_nowait` vào hàng đợi; một thread nền duy nhất ghi file,
nên đường chờ của lượt không bao giờ chạm tới đĩa (STORAGE_DIR có thể là NFS).
Khung `played` tới SAU khi lượt đã xong, nên nó là một dòng bổ sung
`{"turn", "glasses"}` — không sửa dòng cũ (file chỉ append, đọc theo turn id mà ghép).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time

import config
from pipeline import device_ctx

logger = logging.getLogger("blind_assist")

ROTATE_BYTES = 50 * 1024 * 1024
GLASSES_KEYS = ("t_press_ms", "t_release_ms", "first_byte_ms", "first_audio_ms")

_queue: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def path() -> str:
    return os.path.join(config.STORAGE_DIR, "metrics", "turns.jsonl")


def glasses_marks(frame: dict) -> dict:
    """Bốn mốc kính từ một khung bất kỳ (thiếu mốc nào thì None)."""
    return {k: frame.get(k) for k in GLASSES_KEYS}


def record_turn(row: dict) -> None:
    """Xếp một dòng vào hàng đợi ghi; không bao giờ ném lỗi, không chặn."""
    global _worker
    row = {"ts": round(time.time(), 3), **row}
    _queue.put(row)
    if _worker is None or not _worker.is_alive():
        with _worker_lock:
            if _worker is None or not _worker.is_alive():
                _worker = threading.Thread(target=_run, name="metrics-writer", daemon=True)
                _worker.start()


def flush(timeout: float = 5.0) -> None:
    """Chờ ghi xong các dòng đã xếp (test / tắt máy)."""
    deadline = time.monotonic() + timeout
    while _queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.005)


def _run() -> None:
    while True:
        row = _queue.get()
        try:
            _append(row)
        except Exception:  # noqa: BLE001 - quan sát hỏng không được kéo lượt hỏng
            logger.exception("metrics: ghi turns.jsonl lỗi")
        finally:
            _queue.task_done()


def _append(row: dict) -> None:
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        if os.path.getsize(target) > ROTATE_BYTES:
            os.replace(target, target + ".1")
    except FileNotFoundError:
        pass
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


class TurnLogFilter(logging.Filter):
    """Gắn `device`/`turn` (ContextVar của lượt) vào mọi LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.device = device_ctx.current.get()
        record.turn = device_ctx.turn.get() or "-"
        return True


LOG_FORMAT = "%(asctime)s %(levelname)s [%(device)s %(turn)s] %(message)s"


def install_log_filter() -> None:
    """Gắn filter vào handler của root (filter của logger không áp cho record lan từ logger con)."""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, TurnLogFilter) for f in handler.filters):
            handler.addFilter(TurnLogFilter())
