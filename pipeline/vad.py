"""VAD (Silero qua sherpa-onnx) cho đường STT của /v2/turn.

Model `silero_vad.onnx` (~0,6 MB, CPU, < 1 ms/khung 32 ms) tải từ
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
về `models/vad/` (git-ignored). Dùng để:
  - biết khi nào đã có tiếng / đã hết câu (im lặng >= VAD_END_SILENCE_S),
  - cắt im lặng đầu/cuối trước khi giải (nhanh hơn, bớt chữ rác do tạp âm),
  - cả lượt không có tiếng -> `no_speech` ngay, khỏi giải và khỏi gọi Gemma.

Ta tự làm hysteresis trên `is_speech_detected()` từng khung thay vì dùng segment
của sherpa: segment chỉ ra sau khi đã hết câu nên không biết được "đang nói dở".
"""

import os

import numpy as np

import config

WINDOW = 512  # khung Silero 16 kHz = 32 ms
RATE = 16000


def available() -> bool:
    return config.VAD_ENABLED and os.path.exists(config.VAD_MODEL_PATH)


def _make_detector():
    # Nạp onnxruntime (gói GPU) TRƯỚC sherpa_onnx, cùng lý do như pipeline/stt.py.
    import onnxruntime  # noqa: F401
    from sherpa_onnx import VadModelConfig, VoiceActivityDetector

    cfg = VadModelConfig()
    cfg.silero_vad.model = config.VAD_MODEL_PATH
    cfg.silero_vad.threshold = config.VAD_THRESHOLD
    cfg.silero_vad.min_silence_duration = 0.1
    cfg.silero_vad.min_speech_duration = 0.1
    cfg.silero_vad.window_size = WINDOW
    cfg.sample_rate = RATE
    cfg.num_threads = 1
    return VoiceActivityDetector(cfg, buffer_size_in_seconds=5)


class Segmenter:
    """Theo dõi tiếng nói trên luồng PCM float32 16 kHz đang tới (vị trí tính bằng mẫu)."""

    def __init__(self, detector=None, end_silence_s: float | None = None, pad_s: float | None = None) -> None:
        self._det = detector or _make_detector()
        self._end = int((config.VAD_END_SILENCE_S if end_silence_s is None else end_silence_s) * RATE)
        self._pad = int((config.VAD_PAD_S if pad_s is None else pad_s) * RATE)
        self._rest = np.zeros(0, np.float32)
        self.n = 0                       # số mẫu đã đưa vào khung xử lý
        self.first_speech: int | None = None
        self.last_speech: int | None = None  # cuối khung có tiếng gần nhất

    def feed(self, samples: np.ndarray) -> None:
        buf = np.concatenate([self._rest, samples]) if self._rest.size else samples
        usable = buf.size // WINDOW * WINDOW
        for i in range(0, usable, WINDOW):
            self._det.accept_waveform(buf[i:i + WINDOW])
            self.n += WINDOW
            if self._det.is_speech_detected():
                if self.first_speech is None:
                    self.first_speech = self.n - WINDOW
                self.last_speech = self.n
            while not self._det.empty():  # bỏ segment của sherpa, ta không dùng
                self._det.pop()
        self._rest = buf[usable:]

    @property
    def speech_started(self) -> bool:
        return self.first_speech is not None

    @property
    def speaking(self) -> bool:
        """Khung gần nhất còn tiếng (chưa tới ngưỡng im lặng kết thúc)."""
        return self.last_speech is not None and self.n - self.last_speech < self._end

    @property
    def speech_ended_at(self) -> int | None:
        """Vị trí (mẫu) hết câu; None nếu chưa có tiếng hoặc còn đang nói."""
        if self.last_speech is None or self.speaking:
            return None
        return self.last_speech

    def span(self) -> tuple[int, int] | None:
        """Đoạn có tiếng + đệm hai đầu. Cuối đoạn đứng yên khi hết câu."""
        if self.first_speech is None:
            return None
        return max(0, self.first_speech - self._pad), min(self.n, self.last_speech + self._pad)
