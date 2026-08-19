import os
from functools import lru_cache

import numpy as np

import config
from pipeline import adpcm


@lru_cache(maxsize=1)
def _load_asr():
    """Zipformer-vi 30M (RNN-T offline, int8) qua sherpa-onnx, chạy CPU.

    Chạy CPU là lựa chọn có chủ ý, không phải hạn chế: model int8 chỉ ~34MB nên
    CPU đã nhanh hơn thời gian thực nhiều lần, mà đổi lại GPU 4GB được để trọn
    cho OCR/TTS thay vì phải chia ba.
    """
    from sherpa_onnx import OfflineRecognizer

    model_dir = config.STT_MODEL_DIR
    return OfflineRecognizer.from_transducer(
        encoder=os.path.join(model_dir, "encoder.int8.onnx"),
        decoder=os.path.join(model_dir, "decoder.onnx"),
        joiner=os.path.join(model_dir, "joiner.int8.onnx"),
        tokens=os.path.join(model_dir, "tokens.txt"),
        num_threads=config.STT_NUM_THREADS,
        sample_rate=_TARGET_SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
    )


_TARGET_SAMPLE_RATE = 16000


def _decode_wav(audio: bytes) -> tuple[np.ndarray, int]:
    """WAV từ board -> mẫu float32 mono trong [-1, 1], kèm tần số lấy mẫu.

    Board gửi lên WAV **IMA ADPCM 4-bit** (fmt tag 0x0011), không phải PCM trần.
    Module `wave` của Python chỉ mở được `WAVE_FORMAT_PCM` — đưa file board vào
    là `wave.Error: unknown format: 17`, tức mọi request thật đều rơi xuống câu
    báo lỗi. `pipeline/adpcm.py` đọc được cả hai dạng.
    """
    raw, sample_rate, channels = adpcm.decode_wav(audio)
    samples = raw.astype(np.float32) / 32768.0
    if channels > 1:
        # Model cần mono; audio stereo/đa kênh bị đọc raw thẳng sẽ ra
        # mảng interleaved sai độ dài -> gộp về mono bằng cách lấy trung bình.
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def _resample(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Đưa về 16kHz — sherpa-onnx không tự resample như pipeline của Whisper.

    Nội suy tuyến tính là đủ: đầu vào từ MCU vốn đã là 16kHz, nhánh này chỉ để
    file test/nguồn khác tần số không cho ra kết quả rác thay vì báo lỗi.
    """
    if sample_rate == _TARGET_SAMPLE_RATE or samples.size == 0:
        return samples
    duration = samples.size / sample_rate
    target_len = int(duration * _TARGET_SAMPLE_RATE)
    if target_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0, samples.size - 1, target_len, dtype=np.float32)
    return np.interp(src_idx, np.arange(samples.size), samples).astype(np.float32)


def _normalize(text: str) -> str:
    """Zipformer trả về CHỮ HOA TOÀN BỘ, không dấu câu — đưa về dạng câu thường.

    Không phải chuyện thẩm mỹ: câu này đi thẳng vào prompt phân loại ý định, rồi
    những tham số trích ra từ nó (`song`, `contact_name`, `destination`) được gửi
    tiếp sang host để tìm bài hát/tra danh bạ. Giữ nguyên chữ hoa là đẩy
    "SƠN TÙNG" vào ô tìm kiếm và đưa "TÔI MUỐN GỌI MẸ" vào lịch sử trò chuyện.
    """
    text = text.strip()
    if not text:
        return ""
    return text[0].upper() + text[1:].lower()


def transcribe(audio: bytes) -> str:
    """Audio WAV -> câu lệnh tiếng Việt (Zipformer-vi 30M RNN-T, sherpa-onnx).

    Model đơn ngữ tiếng Việt nên không có bước nhận diện ngôn ngữ để bỏ qua như
    Whisper, và cũng không sinh token tự hồi quy trên toàn câu: decode RNN-T
    greedy chạy thẳng theo khung, thời gian gần như tỉ lệ với độ dài audio.
    """
    samples, sample_rate = _decode_wav(audio)
    samples = _resample(samples, sample_rate)
    recognizer = _load_asr()
    stream = recognizer.create_stream()
    stream.accept_waveform(_TARGET_SAMPLE_RATE, samples)
    recognizer.decode_stream(stream)
    return _normalize(stream.result.text)
