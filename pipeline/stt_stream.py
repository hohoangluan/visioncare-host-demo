"""Pseudo-streaming STT (§7.1) trên Zipformer offline của `pipeline/stt.py`.

Zipformer giải ~0,03 s/câu nên cứ giải lại TOÀN BỘ buffer mỗi 300 ms trong lúc
audio còn đang tới — không cần model streaming riêng. Bản ghi cuối chỉ còn là
một lượt giải nữa sau khi nhả nút, và bỏ hẳn được nếu từ lần giải trước tới giờ
không có mẫu mới nào.

Khối ADPCM tự mang predictor/step index riêng nên giải từng khối ngay khi đủ
256 byte là đúng y như giải cả file một lần.
"""

import struct
import threading

import numpy as np

from pipeline import adpcm, stt

_FORMAT_PCM = 0x0001


def _content_params(content_type: str | None) -> dict[str, str]:
    params = {}
    for part in (content_type or "").split(";")[1:]:
        key, _, value = part.partition("=")
        params[key.strip().lower()] = value.strip()
    return params


class StreamingTranscriber:
    """Nhận body audio theo mảnh, cho partial/final transcript bất kỳ lúc nào.

    `feed()` gọi từ event loop, `partial()`/`final()` gọi từ thread worker: mọi
    trạng thái dùng chung đi qua `_lock`. Recognizer chỉ đụng tới trong
    `_decode()`, mà mỗi lượt `/v2/turn` chỉ có một lượt giải chạy cùng lúc.
    """

    def __init__(self, content_type: str | None = None) -> None:
        params = _content_params(content_type)
        self._block_align = int(params.get("block", adpcm.BLOCK_ALIGN) or adpcm.BLOCK_ALIGN)
        self._rate = int(params.get("rate", adpcm.SAMPLE_RATE) or adpcm.SAMPLE_RATE)
        self._format = adpcm.FORMAT_TAG
        self._channels = 1
        # Còn đang dò header RIFF thì `_header_done` False; ADPCM thô thì xong luôn.
        self._header_done = False
        self._pending = b""
        self._chunks: list[np.ndarray] = []
        self._n_samples = 0
        self._lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._decoded_at = -1  # số mẫu ở lần giải gần nhất
        self._text = ""
        self.bytes_in = 0

    # ── nhận audio ──────────────────────────────────────────────────────

    def _parse_header(self) -> bool:
        """Dò header WAV ở đầu luồng. True khi đã biết chỗ bắt đầu dữ liệu."""
        data = self._pending
        if len(data) < 4:
            return False
        if data[:4] != b"RIFF":
            self._header_done = True  # ADPCM thô, tham số lấy từ Content-Type
            return True
        if len(data) < 12:
            return False
        pos = 12
        while pos + 8 <= len(data):
            chunk_id = data[pos:pos + 4]
            size = struct.unpack_from("<I", data, pos + 4)[0]
            if chunk_id == b"data":
                self._pending = data[pos + 8:]
                self._header_done = True
                return True
            if pos + 8 + size > len(data):
                return False  # chunk fmt/fact chưa tới đủ
            body = data[pos + 8:pos + 8 + size]
            if chunk_id == b"fmt ":
                tag, channels, rate, _, block_align = struct.unpack_from("<HHIIH", body)
                self._format, self._channels, self._rate = tag, channels, rate
                self._block_align = block_align
            pos += 8 + size + (size & 1)
        return False

    def feed(self, data: bytes) -> None:
        if not data:
            return
        self.bytes_in += len(data)
        with self._lock:
            self._pending += data
            if not self._header_done and not self._parse_header():
                return
            if self._format == _FORMAT_PCM:
                frame = 2 * self._channels
                usable = len(self._pending) // frame * frame
                raw = np.frombuffer(self._pending[:usable], dtype="<i2")
            else:
                usable = len(self._pending) // self._block_align * self._block_align
                raw = adpcm.decode_blocks(self._pending[:usable], self._block_align)
            self._pending = self._pending[usable:]
            if raw.size == 0:
                return
            samples = raw.astype(np.float32) / 32768.0
            if self._channels > 1:
                samples = samples.reshape(-1, self._channels).mean(axis=1)
            self._chunks.append(samples)
            self._n_samples += samples.size

    @property
    def seconds(self) -> float:
        return self._n_samples / float(self._rate or 1)

    def has_new_audio(self) -> bool:
        return self._n_samples != self._decoded_at

    # ── giải mã ─────────────────────────────────────────────────────────

    def _snapshot(self) -> tuple[np.ndarray, int]:
        with self._lock:
            if len(self._chunks) > 1:
                self._chunks = [np.concatenate(self._chunks)]
            samples = self._chunks[0] if self._chunks else np.zeros(0, np.float32)
            return samples, self._n_samples

    def _decode(self) -> str:
        with self._decode_lock:
            samples, count = self._snapshot()
            if count == self._decoded_at:
                return self._text  # không có mẫu mới: kết quả cũ vẫn đúng
            if count == 0:
                self._decoded_at, self._text = 0, ""
                return ""
            samples = stt._resample(samples, self._rate)
            recognizer = stt._load_asr()
            stream = recognizer.create_stream()
            stream.accept_waveform(stt._TARGET_SAMPLE_RATE, samples)
            recognizer.decode_stream(stream)
            self._decoded_at, self._text = count, stt._normalize(stream.result.text)
            return self._text

    def partial(self) -> str:
        return self._decode()

    def final(self) -> str:
        """Bản ghi cuối. Rẻ (0 ms) nếu partial gần nhất đã thấy hết audio."""
        return self._decode()
