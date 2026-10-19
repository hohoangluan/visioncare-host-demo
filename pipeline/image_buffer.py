"""Image Buffer (§6): ảnh lúc bấm nút, giữ trong RAM theo `(device, turn)`, hạn 30 s.

Ảnh tới TRƯỚC audio, nên mọi bước tiền xử lý (giải mã, thu nhỏ cho Gemma) chạy
ngay lúc ảnh vào, ở thread nền — khi bản ghi cuối xong thì ảnh đã sẵn, không
nằm trên đường chờ. Không ghi đĩa (spec: không lưu ảnh giấy tờ).
"""

import io
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from PIL import Image

import config

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="image-prep")


def resize_jpeg(jpeg: bytes, max_side: int, quality: int = 85) -> bytes:
    """JPEG -> JPEG có cạnh dài <= `max_side`. Ảnh đã đủ nhỏ thì trả nguyên.

    `draft()` bảo libjpeg giải mã thẳng ở tỉ lệ 1/2, 1/4, 1/8 (DCT scaling)
    thay vì giải trọn 1600x1200 rồi mới thu nhỏ: UXGA -> 896 nhanh hơn ~3 lần.
    """
    img = Image.open(io.BytesIO(jpeg))
    if max(img.size) <= max_side:
        return jpeg
    img.draft("RGB", (max_side, max_side))
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.BILINEAR)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


class Entry:
    __slots__ = ("jpeg", "arrived_at", "_llm")

    def __init__(self, jpeg: bytes) -> None:
        self.jpeg = jpeg
        self.arrived_at = time.monotonic()
        self._llm: Future = _POOL.submit(self._prepare)

    def _prepare(self) -> bytes:
        try:
            return resize_jpeg(self.jpeg, config.LLM_IMAGE_MAX_SIDE)
        except Exception:  # noqa: BLE001 - ảnh hỏng: để Gemma tự nói không thấy gì
            return self.jpeg

    def prepared(self) -> bool:
        return self._llm.done()

    def llm_jpeg(self) -> bytes:
        """Bản đã thu nhỏ cho Gemma (chờ nếu thread nền chưa xong)."""
        return self._llm.result()


class ImageBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], Entry] = {}
        # Sự kiện "ảnh đã tới", kèm lúc tạo để dọn cả những lượt không bao giờ có ảnh.
        self._arrived: dict[tuple[str, str], tuple[threading.Event, float]] = {}

    def _event(self, key: tuple[str, str]) -> threading.Event:
        item = self._arrived.get(key)
        if item is None:
            item = self._arrived[key] = (threading.Event(), time.monotonic())
        return item[0]

    def _prune(self, now: float) -> None:
        ttl = config.IMAGE_BUFFER_TTL_S
        for key in [k for k, e in self._entries.items() if now - e.arrived_at > ttl]:
            del self._entries[key]
        for key in [k for k, (_, t) in self._arrived.items() if now - t > ttl]:
            del self._arrived[key]

    def put(self, device: str, turn: str, jpeg: bytes) -> Entry:
        entry = Entry(jpeg)
        with self._lock:
            self._prune(entry.arrived_at)
            self._entries[(device, turn)] = entry
            self._event((device, turn)).set()
        return entry

    def get(self, device: str, turn: str) -> Entry | None:
        with self._lock:
            entry = self._entries.get((device, turn))
            if entry is not None and time.monotonic() - entry.arrived_at > config.IMAGE_BUFFER_TTL_S:
                return None
            return entry

    def wait(self, device: str, turn: str, timeout: float) -> Entry | None:
        """Chờ ảnh của lượt này tới (kính gửi ảnh và audio tuần tự)."""
        entry = self.get(device, turn)
        if entry is not None or timeout <= 0:
            return entry
        with self._lock:
            event = self._event((device, turn))
        event.wait(timeout)
        return self.get(device, turn)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._arrived.clear()


image_buffer = ImageBuffer()
