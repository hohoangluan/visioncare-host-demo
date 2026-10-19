"""Phiên realtime B/C: token một lần cho `WS /v2/live`, mỗi kính một phiên.

Token tạo ngay lúc ĐOÁN SỚM ra làn B/C (prewarm, §7.4) nên khi `/v2/turn` trả
header thì token đã có sẵn. Đoán sai thì token hết hạn sau 10 s, không ai dùng.
"""

import queue
import secrets
import threading
import time
from dataclasses import dataclass, field

import config


@dataclass
class LiveSession:
    token: str
    device: str
    mode: str  # "ocr" | "nav"
    params: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    # Gắn khi WS mở; `close()` từ chỗ khác (nav_stop, lượt mới) đặt cờ này.
    closed: threading.Event = field(default_factory=threading.Event)
    # Hàng đợi audio đẩy vào phiên từ ngoài (vd. kết quả làn D khi đang dẫn đường).
    outbox: queue.Queue = field(default_factory=queue.Queue)


class SessionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, LiveSession] = {}
        self._active: dict[str, LiveSession] = {}  # device -> phiên đang mở

    def create(self, device: str, mode: str, params: dict | None = None) -> LiveSession:
        session = LiveSession(secrets.token_urlsafe(12), device, mode, dict(params or {}))
        with self._lock:
            self._prune()
            self._pending[session.token] = session
        return session

    def _prune(self) -> None:
        now = time.monotonic()
        for token in [t for t, s in self._pending.items() if now - s.created_at > config.LIVE_TOKEN_TTL_S]:
            del self._pending[token]

    def claim(self, token: str) -> LiveSession | None:
        """Dùng token đúng một lần; mở phiên mới thì đóng phiên cũ của kính đó."""
        with self._lock:
            self._prune()
            session = self._pending.pop(token, None)
            if session is None:
                return None
            old = self._active.get(session.device)
            if old is not None:
                old.closed.set()
            self._active[session.device] = session
            return session

    def discard(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._pending.pop(token, None)

    def active(self, device: str) -> LiveSession | None:
        with self._lock:
            session = self._active.get(device)
            return None if session is None or session.closed.is_set() else session

    def release(self, session: LiveSession) -> None:
        session.closed.set()
        with self._lock:
            if self._active.get(session.device) is session:
                del self._active[session.device]

    def close_device(self, device: str, mode: str | None = None) -> bool:
        """Đóng phiên đang chạy của kính (vd. "tắt cảnh báo"). True nếu có phiên."""
        with self._lock:
            session = self._active.get(device)
            if session is None or (mode is not None and session.mode != mode):
                return False
            session.closed.set()
            del self._active[device]
            return True

    def clear(self) -> None:
        with self._lock:
            for session in self._active.values():
                session.closed.set()
            self._pending.clear()
            self._active.clear()


sessions = SessionManager()
