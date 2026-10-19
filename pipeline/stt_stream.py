"""Pseudo-streaming STT (§7.1) trên Zipformer offline của `pipeline/stt.py`.

Zipformer giải ~0,03 s/câu nên cứ giải lại TOÀN BỘ buffer mỗi 300 ms trong lúc
audio còn đang tới — không cần model streaming riêng. Bản ghi cuối chỉ còn là
một lượt giải nữa sau khi nhả nút, và bỏ hẳn được nếu từ lần giải trước tới giờ
không có mẫu mới nào.

Khối ADPCM tự mang predictor/step index riêng nên giải từng khối ngay khi đủ
256 byte là đúng y như giải cả file một lần.
"""

import logging
import struct
import threading

import numpy as np

import config
from pipeline import adpcm, stt

logger = logging.getLogger("blind_assist")

_FORMAT_PCM = 0x0001
# Tham số audio do client khai (Content-Type / header RIFF) chỉ được nằm trong khoảng hợp lý: trần audio và
# trần byte tính theo rate x channels, nên con số tuỳ ý = vô hiệu hoá trần.
_MIN_RATE, _MAX_RATE = 8000, 48000
_MIN_CHANNELS, _MAX_CHANNELS = 1, 2


def _sane_rate(value) -> int:
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return adpcm.SAMPLE_RATE
    return rate if _MIN_RATE <= rate <= _MAX_RATE else adpcm.SAMPLE_RATE


def _sane_block(value) -> int:
    try:
        block = int(value)
    except (TypeError, ValueError):
        return adpcm.BLOCK_ALIGN
    return block if 0 < block <= 8192 else adpcm.BLOCK_ALIGN


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

    def __init__(self, content_type: str | None = None, vad=None) -> None:
        # `vad`: pipeline.vad.Segmenter (hoặc None = giải cả buffer như trước).
        self._vad = vad
        params = _content_params(content_type)
        self._block_align = _sane_block(params.get("block"))
        self._rate = _sane_rate(params.get("rate"))
        self._format = adpcm.FORMAT_TAG
        self._channels = 1
        # Còn đang dò header RIFF thì `_header_done` False; ADPCM thô thì xong luôn.
        self._header_done = False
        self._pending = b""
        self._chunks: list[np.ndarray] = []
        self._n_samples = 0
        self._lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._decoded_at = -1  # khoá của lần giải gần nhất (số mẫu, hoặc đoạn tiếng khi có VAD)
        self._text = ""
        self.bytes_in = 0
        self.capped = False

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
                self._format = tag
                # Header do client khai: kẹp vào khoảng hợp lý, không thì trần audio (tính theo rate/channels)
                # phồng theo con số tuỳ ý (rate=1e9 -> ~60 GB).
                self._channels = channels if _MIN_CHANNELS <= channels <= _MAX_CHANNELS else 1
                self._rate = _sane_rate(rate)
                self._block_align = _sane_block(block_align)
            pos += 8 + size + (size & 1)
        return False

    def feed(self, data: bytes) -> None:
        if not data or self.capped:
            return
        # Trần audio (Task 9): quá DEVICE_MAX_AUDIO_S thì ngừng nhận, lượt kết
        # thúc với phần đã có — chặn buffer phình vô hạn từ kẻ giữ nút mãi.
        # Chặn thêm theo BYTE: header RIFF không bao giờ hoàn tất thì _n_samples
        # đứng ở 0 và _pending phình mãi. PCM 16-bit là dạng tốn byte nhất.
        byte_cap = config.DEVICE_MAX_AUDIO_S * (self._rate or 1) * 2 * max(1, self._channels) + 65536
        if self._n_samples >= config.DEVICE_MAX_AUDIO_S * (self._rate or 1) or self.bytes_in > byte_cap:
            self.capped = True
            logger.warning("audio vượt %.0fs: bỏ phần còn lại", config.DEVICE_MAX_AUDIO_S)
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
            if self._vad is not None:
                self._vad.feed(samples if self._rate == 16000 else stt._resample(samples, self._rate))

    @property
    def seconds(self) -> float:
        return self._n_samples / float(self._rate or 1)

    def _key(self):
        """Khoá "nội dung cần giải": số mẫu, hoặc (đầu, cuối) đoạn tiếng khi có VAD.

        Có VAD thì im lặng tới thêm không đổi khoá -> không giải lại; không có
        tiếng nào -> None (không có gì để giải).
        """
        if self._vad is None:
            return self._n_samples
        return self._vad.span()

    def has_new_audio(self) -> bool:
        key = self._key()
        return key is not None and key != self._decoded_at

    @property
    def speech_ended(self) -> bool:
        """VAD báo hết câu (im lặng >= VAD_END_SILENCE_S sau tiếng) trong lúc nút còn giữ."""
        return self._vad is not None and self._vad.speech_ended_at is not None

    @property
    def has_speech(self) -> bool:
        return self._vad is None or self._vad.speech_started

    @property
    def decoded_key(self):
        return self._decoded_at

    def span_key(self):
        with self._lock:
            return self._key()

    # ── giải mã ─────────────────────────────────────────────────────────

    def _snapshot(self):
        with self._lock:
            if len(self._chunks) > 1:
                self._chunks = [np.concatenate(self._chunks)]
            samples = self._chunks[0] if self._chunks else np.zeros(0, np.float32)
            return samples, self._n_samples, self._key()

    def _decode(self) -> str:
        with self._decode_lock:
            samples, count, key = self._snapshot()
            if self._vad is not None and key is None:
                return ""  # cả lượt không có tiếng: khỏi giải
            if key == self._decoded_at:
                return self._text  # không có tiếng/mẫu mới: kết quả cũ vẫn đúng
            if count == 0:
                self._decoded_at, self._text = 0, ""
                return ""
            samples = stt._resample(samples, self._rate)
            if self._vad is not None:
                samples = samples[key[0]:key[1]]  # chỉ giải đoạn có tiếng
            recognizer = stt._load_asr()
            stream = recognizer.create_stream()
            stream.accept_waveform(stt._TARGET_SAMPLE_RATE, samples)
            recognizer.decode_stream(stream)
            self._decoded_at, self._text = key, stt._normalize(stream.result.text)
            return self._text

    def partial(self) -> str:
        return self._decode()

    def final(self) -> str:
        """Bản ghi cuối. Rẻ (0 ms) nếu partial gần nhất đã thấy hết audio."""
        return self._decode()
