"""G9 — một dòng trace cho mỗi lượt, khoá bằng `turn_id` (T21).

Vì sao có file này
------------------
Từng chặng đã tự đo thời gian của nó (`pipeline/router.py` đo STT, intent,
handler; `app.py` đo TTFB) và mỗi chặng in một dòng log riêng. Cộng lại thì
**không trả lời được câu hỏi quan trọng nhất**: *"lượt vừa rồi chậm ở đâu?"*
— vì các dòng của một lượt nằm rải rác giữa các dòng của những lượt khác đang
chạy song song (`/process` là `def` thường, FastAPI chạy nó trong threadpool).

Không có trace thì **không phát hiện được hồi quy độ trễ**: mọi con số trong
`DETAILED_STAGE_LATENCY_BENCHMARK.md` là kết quả của một buổi đo tay, và
không có gì báo khi một thay đổi làm chậm đi 300 ms.

Khoá bằng `turn_id` chứ không phải một id mới
---------------------------------------------
`turn_id` (T01) đã là khoá của idempotency và của barge-in. Dùng chung một
khoá nghĩa là đọc log xong tra thẳng được sang "lượt này có bị gửi lặp không"
và "lượt này có bị ngắt không" — ba câu hỏi thường phải hỏi cùng lúc.

Không đo được thì để trống, đừng đoán
--------------------------------------
Chặng nào không chạy (lượt trả lời bằng câu dựng sẵn thì không có `gemini`)
thì **không có mặt** trong trace, chứ không phải bằng 0. `0 ms` và "không
chạy" là hai điều khác nhau, và gộp chúng lại là cách nhanh nhất để đọc nhầm
một bảng p50.
"""

from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
import threading
import time

logger = logging.getLogger("blind_assist.trace")


@dataclass
class TurnTrace:
    device_id: str
    turn_id: str | None
    started_at: float = field(default_factory=time.monotonic)
    stages: dict[str, float] = field(default_factory=dict)
    fields: dict[str, object] = field(default_factory=dict)

    def stage_ms(self, name: str) -> float | None:
        seconds = self.stages.get(name)
        return None if seconds is None else round(seconds * 1000, 1)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "device_id": self.device_id,
            "turn_id": self.turn_id,
        }
        payload.update(self.fields)
        for name, seconds in self.stages.items():
            payload[f"{name}_ms"] = round(seconds * 1000, 1)
        return payload


# ContextVar chứ không phải tham số: `/process` gọi xuống 15 handler, thêm một
# tham số là 15 chỗ sửa và 15 chỗ quên — cùng lý do T01 chọn ContextVar cho
# `device_id`/`turn_id` (T01-protocol-ids.md mục 2.2).
_CURRENT: ContextVar[TurnTrace | None] = ContextVar("turn_trace", default=None)


class TraceLog:
    """Giữ N lượt gần nhất trong RAM để test và `tools/measure_budget.py` đọc.

    Cố tình KHÔNG ghi xuống đĩa: đây là dữ liệu chẩn đoán của tiến trình đang
    chạy, và một file trace phình vô hạn trên máy người dùng là thứ không ai
    đi dọn. Muốn giữ lâu thì đọc dòng log — nó vẫn được in ra như thường.
    """

    def __init__(self, capacity: int = 200) -> None:
        self._lock = threading.Lock()
        self._entries: deque[TurnTrace] = deque(maxlen=capacity)

    def record(self, trace: TurnTrace) -> None:
        with self._lock:
            self._entries.append(trace)

    def recent(self, limit: int | None = None) -> list[TurnTrace]:
        with self._lock:
            items = list(self._entries)
        return items if limit is None else items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


traces = TraceLog()


def begin(device_id: str, turn_id: str | None) -> TurnTrace:
    """Mở trace cho lượt hiện tại. Gọi ngay đầu `/process`."""
    trace = TurnTrace(device_id=device_id, turn_id=turn_id)
    _CURRENT.set(trace)
    return trace


def current() -> TurnTrace | None:
    return _CURRENT.get()


def stage(name: str, seconds: float) -> None:
    """Ghi thời gian một chặng. Không có trace đang mở thì im lặng bỏ qua.

    Bỏ qua chứ không ném lỗi: các chặng này cũng chạy trong test đơn vị và
    trong `tools/bench_*.py`, những nơi không có `/process` nào mở trace. Một
    dòng đo độ trễ **không bao giờ** được là lý do một lượt thất bại.
    """
    trace = _CURRENT.get()
    if trace is not None:
        trace.stages[name] = seconds


def annotate(**fields: object) -> None:
    """Gắn thêm trường không phải thời gian: intent, confidence, error_code..."""
    trace = _CURRENT.get()
    if trace is not None:
        trace.fields.update(fields)


def finish(**fields: object) -> TurnTrace | None:
    """Đóng trace: cộng tổng, in một dòng, cất vào `traces`."""
    trace = _CURRENT.get()
    if trace is None:
        return None
    trace.fields.update(fields)
    trace.stages["total"] = time.monotonic() - trace.started_at
    traces.record(trace)
    _CURRENT.set(None)

    payload = trace.as_dict()
    logger.info(
        "turn_trace %s",
        " ".join(f"{key}={value}" for key, value in payload.items() if value is not None),
    )
    return trace
