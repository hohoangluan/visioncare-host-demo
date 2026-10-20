"""Bộ đệm chống giật (jitter buffer) cho đầu app -> kính của cuộc gọi.

PCM16LE 16 kHz mono, khung 20 ms (640 B) tới qua WebSocket/Cloudflare thành cụm: nghẽn 100 ms rồi 5 khung
cùng lúc. Kính chỉ có đệm preroll nhỏ nên nếu ném cụm đó xuống nguyên si thì nghe thành tiếng vỡ/giật.
Bộ đệm giữ `target_ms` âm thanh trước khi bắt đầu phát, rồi nhả đều từng khung theo nhịp `pop()`.

Độ trễ đo theo ĐỘ SÂU HÀNG ĐỢI (đồng hồ phát), không theo nhịp tới của nguồn (fix C5 round 1): mốc "tới sớm nhất"
tự dựng từng làm câm vĩnh viễn sau một lần nguồn ngừng > 200 ms hoặc lệch đồng hồ 0,5%, và không chặn được trễ tích luỹ
khi nguồn nhanh hơn nhịp phát hay socket kính nghẽn.

Quy ước:
- `seq_ts` (ms, theo nguồn) chỉ dùng để sắp thứ tự và loại khung trùng / khung đã qua lượt phát. KHÔNG dùng đo trễ.
- Đệm chứa tối đa `target_ms + max_late_ms` âm thanh. Vượt thì bỏ khung CŨ nhất tới khi còn `target_ms`: nghe mất
  một đoạn ngắn còn hơn nghe trễ mãi (cách duy nhất kéo độ trễ về lại sau cơn nghẽn / lệch nhịp).
- Cạn (underrun): chèn một khung im lặng, ngừng phát, gom lại tới `target_ms`, và neo lại mốc thứ tự theo khung kế
  (nguồn ngừng rồi nói lại vẫn nghe được).
- `pop()`: `None` = chưa phát (đang gom); `bytes` = khung kế, hoặc khung im lặng khi thiếu 1 khung giữa chừng.
"""

import heapq

_BYTES_PER_MS = 32  # 16 kHz * 2 B
_MAX_CONCEAL_FRAMES = 5  # thiếu quá 100 ms thì nhảy tới khung kế, không bù từng khung


class JitterBuffer:
    def __init__(self, target_ms: int = 60, max_late_ms: int = 200) -> None:
        self.target_ms = target_ms
        self.max_late_ms = max_late_ms
        self._heap: list[tuple[int, bytes]] = []
        self._ts: set[int] = set()  # khử trùng O(1)
        self._buffered_ms = 0.0
        self._last_ts: int | None = None  # seq_ts khung đã nhả gần nhất (kể cả khung im lặng chèn vào)
        self._last_dur = 20
        self._playing = False
        self.dropped_old = 0  # khung có ts đã qua lượt phát
        self.dropped_depth = 0  # khung cũ bị bỏ vì đệm vượt trần
        self.concealed = 0  # số khung im lặng chèn vào chỗ thiếu
        self.underruns = 0

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def buffered_ms(self) -> float:
        return self._buffered_ms

    def push(self, frame: bytes, seq_ts: int) -> bool:
        """Thêm một khung. False = bị bỏ (đã qua lượt phát / trùng)."""
        if not frame:
            return False
        if (self._last_ts is not None and seq_ts <= self._last_ts) or seq_ts in self._ts:
            self.dropped_old += 1
            return False
        heapq.heappush(self._heap, (seq_ts, frame))
        self._ts.add(seq_ts)
        self._buffered_ms += len(frame) / _BYTES_PER_MS
        if self._buffered_ms > self.target_ms + self.max_late_ms:
            self._trim()
        if not self._playing and self._buffered_ms >= self.target_ms:
            self._playing = True
        return True

    def _trim(self) -> None:
        """Bỏ khung cũ nhất cho tới khi còn <= target_ms; phát tiếp từ khung còn lại (không bù im lặng)."""
        while self._heap and self._buffered_ms > self.target_ms:
            ts, frame = heapq.heappop(self._heap)
            self._ts.discard(ts)
            self._buffered_ms -= len(frame) / _BYTES_PER_MS
            self.dropped_depth += 1
        self._last_ts = None

    def pop(self) -> bytes | None:
        if not self._playing:
            return None
        if not self._heap:
            self.underruns += 1
            self._playing = False
            silence = self._silence()
            self._last_ts = None  # gom lại từ đầu: khung sau là mốc mới
            return silence
        ts, frame = self._heap[0]
        if self._last_ts is not None and ts > self._last_ts + self._last_dur:
            if ts - self._last_ts <= _MAX_CONCEAL_FRAMES * self._last_dur:
                # Thiếu khung ở giữa (mất/chưa tới): giữ nhịp bằng im lặng, khung sau để lượt kế.
                self.concealed += 1
                return self._silence()
            self._last_ts = None  # mất cả đoạn dài: nhảy tới khung này thay vì phát một chuỗi im lặng
        heapq.heappop(self._heap)
        self._ts.discard(ts)
        self._buffered_ms -= len(frame) / _BYTES_PER_MS
        self._last_ts = ts
        self._last_dur = max(1, int(len(frame) / _BYTES_PER_MS))
        return frame

    def _silence(self) -> bytes:
        dur = self._last_dur
        if self._last_ts is not None:
            self._last_ts += dur
        return bytes(dur * _BYTES_PER_MS)
