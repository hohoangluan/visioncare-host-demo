"""Bộ đệm chống giật (jitter buffer) cho đầu app -> kính của cuộc gọi.

PCM16LE 16 kHz mono, khung 20 ms (640 B) tới qua WebSocket/Cloudflare thành cụm: nghẽn 100 ms rồi 5 khung
cùng lúc. Kính chỉ có đệm preroll nhỏ nên nếu ném cụm đó xuống nguyên si thì nghe thành tiếng vỡ/giật.
Bộ đệm giữ `target_ms` âm thanh trước khi bắt đầu phát, rồi nhả đều từng khung theo nhịp `pop()`.

Quy ước:
- `seq_ts` là thời điểm (ms) của khung theo đồng hồ NGUỒN (khung thứ n = n * 20). Chỉ dùng để sắp thứ tự và
  để đo độ trễ tương đối so với khung tới sớm nhất — không cần đồng bộ đồng hồ giữa hai đầu.
- Khung tới trễ hơn `max_late_ms` so với nhịp của nguồn bị BỎ (nghe lại tiếng cũ 200 ms sau còn tệ hơn mất nó,
  và bỏ là cách duy nhất kéo độ trễ về lại mức thấp sau một cơn nghẽn).
- Khung có `seq_ts` đã phát qua rồi (tới quá muộn để chen vào) và khung trùng bị bỏ.
- `pop()`: `None` = chưa phát (đang gom đủ `target_ms`) hoặc vừa cạn và đang gom lại; `bytes` = khung kế,
  hoặc khung im lặng khi thiếu một khung giữa chừng (nối tiếp nhịp, không dồn khung sau lên).
"""

import heapq
import time

_BYTES_PER_MS = 32  # 16 kHz * 2 B
_MAX_CONCEAL_FRAMES = 5  # thiếu quá 100 ms thì nhảy tới khung kế, không bù từng khung


class JitterBuffer:
    def __init__(self, target_ms: int = 60, max_late_ms: int = 200) -> None:
        self.target_ms = target_ms
        self.max_late_ms = max_late_ms
        self._heap: list[tuple[int, bytes]] = []
        self._buffered_ms = 0.0
        self._offset: float | None = None  # min(now - seq_ts): khung "đúng giờ" nhất đã thấy
        self._last_ts: int | None = None  # seq_ts khung đã nhả gần nhất (kể cả khung im lặng chèn vào)
        self._last_dur = 20
        self._playing = False
        self.dropped_late = 0
        self.dropped_old = 0
        self.concealed = 0  # số khung im lặng chèn vào chỗ thiếu
        self.underruns = 0

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    @property
    def playing(self) -> bool:
        return self._playing

    def push(self, frame: bytes, seq_ts: int, now_ms: float | None = None) -> bool:
        """Thêm một khung. False = bị bỏ (trễ quá hạn / đã qua lượt phát / trùng)."""
        if not frame:
            return False
        now = self._now_ms() if now_ms is None else now_ms
        delta = now - seq_ts
        if self._offset is None or delta < self._offset:
            self._offset = delta
        if delta - self._offset > self.max_late_ms:
            self.dropped_late += 1
            return False
        if self._last_ts is not None and seq_ts <= self._last_ts:
            self.dropped_old += 1
            return False
        if any(ts == seq_ts for ts, _ in self._heap):
            return False
        heapq.heappush(self._heap, (seq_ts, frame))
        self._buffered_ms += len(frame) / _BYTES_PER_MS
        if not self._playing and self._buffered_ms >= self.target_ms:
            self._playing = True
        return True

    def pop(self) -> bytes | None:
        if not self._playing:
            return None
        if not self._heap:
            # Cạn: chèn một khung im lặng rồi gom lại tới target (không phát tiếng méo kéo dài).
            self.underruns += 1
            self._playing = False
            silence = self._silence()
            self._last_ts = None  # gom lại từ đầu: khung sau là mốc mới, không chèn im lặng bù đoạn đã mất
            return silence
        ts, frame = self._heap[0]
        if self._last_ts is not None and ts > self._last_ts + self._last_dur:
            if ts - self._last_ts <= _MAX_CONCEAL_FRAMES * self._last_dur:
                # Thiếu khung ở giữa (mất/chưa tới): giữ nhịp bằng im lặng, khung sau để lượt kế.
                self.concealed += 1
                return self._silence()
            self._last_ts = None  # mất cả đoạn dài: nhảy tới khung này thay vì phát một chuỗi im lặng
        heapq.heappop(self._heap)
        self._buffered_ms -= len(frame) / _BYTES_PER_MS
        self._last_ts = ts
        self._last_dur = max(1, int(len(frame) / _BYTES_PER_MS))
        return frame

    def _silence(self) -> bytes:
        dur = self._last_dur
        if self._last_ts is not None:
            self._last_ts += dur
        return bytes(dur * _BYTES_PER_MS)
