import logging
import os
import re
from functools import lru_cache

import numpy as np

import config
from pipeline import adpcm

logger = logging.getLogger("blind_assist")


# Từ lệnh cố định cho contextual biasing (sherpa-onnx hotwords, chỉ có tác dụng với
# modified_beam_search). CHỮ HOA vì BPE của Zipformer học trên chữ hoa. Chỉ gồm cụm lệnh kính hay
# nghe + từ chỉ người thân ngắn (hay bị nuốt: "Nhắn cho mẹ" -> "Nhanh cho mẹ"). Số đo chọn danh sách
# và `STT_HOTWORDS_SCORE` ở config.py.
COMMAND_HOTWORDS = (
    "NHẮN CHO", "NHẮN TIN", "NHẮN TIN CHO", "GỌI CHO", "GỌI ĐIỆN CHO", "GỌI ĐIỆN", "ĐỌC TIN NHẮN",
    "CẤP CỨU", "KHẨN CẤP", "CỨU TÔI", "BẬT CẢNH BÁO", "TẮT CẢNH BÁO", "DỪNG CẢNH BÁO", "NGỪNG CẢNH BÁO",
    "CẢNH BÁO VẬT CẢN", "DẪN ĐƯỜNG", "CHỈ ĐƯỜNG", "DỪNG DẪN ĐƯỜNG", "TẮT CHỈ ĐƯỜNG", "TẮT NHẠC", "DỪNG NHẠC",
    "MẸ", "BỐ", "BA", "MÁ", "VỢ", "CHỒNG",
)

_MAX_USER_HOTWORDS = 10
_user_hotwords: tuple[str, ...] = ()


def _clean_hotword(text) -> str:
    """Tên người thân -> hotword hợp lệ (chữ hoa, chỉ chữ cái/khoảng trắng, <= 4 từ), hoặc ""."""
    words = [w for w in re.sub(r"[^\w\s]|\d|_", " ", str(text or "")).upper().split() if w]
    return " ".join(words) if 1 <= len(words) <= 4 else ""


def set_user_hotwords(names) -> None:
    """Đặt danh sách tên người thân của người dùng (care_links) làm hotword THEO LƯỢT.

    Gọi lúc đồng bộ danh bạ; mỗi lượt mới (`StreamingTranscriber`) đọc danh sách tại thời điểm tạo.
    Đo 2026-10-20 (docs trong config.STT_DECODING): tên đúng 90-92% -> 97-98%.
    """
    global _user_hotwords
    cleaned = []
    for name in names or ():
        word = _clean_hotword(name)
        if word and word not in cleaned:
            cleaned.append(word)
    _user_hotwords = tuple(cleaned[:_MAX_USER_HOTWORDS])


def user_hotwords() -> tuple[str, ...]:
    return _user_hotwords


def _cache_dir() -> str:
    path = os.path.join(config._CACHE_ROOT, "stt")
    os.makedirs(path, exist_ok=True)
    return path


def _bpe_vocab(model_dir: str) -> str | None:
    """File `bpe.vocab` (piece<TAB>score) cho contextual biasing; xuất từ `bpe.model` nếu thiếu.

    Ghi vào thư mục cache (không đụng models/stt). Thiếu sentencepiece/bpe.model -> None, và STT rơi
    về greedy không hotword thay vì hỏng.
    """
    shipped = os.path.join(model_dir, "bpe.vocab")
    if os.path.exists(shipped):
        return shipped
    model = os.path.join(model_dir, "bpe.model")
    try:
        import sentencepiece as spm

        sp = spm.SentencePieceProcessor(model_file=model)
        out = os.path.join(_cache_dir(), "bpe.vocab")
        with open(out, "w", encoding="utf-8") as fh:
            for i in range(sp.vocab_size()):
                fh.write(f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n")
        return out
    except Exception as exc:  # noqa: BLE001 - thiếu gói/tệp: không có hotword, vẫn nghe được
        logger.warning("STT: không dựng được bpe.vocab (%s) -> greedy, không hotword", exc)
        return None


def _hotwords_file() -> str | None:
    words = COMMAND_HOTWORDS
    if config.STT_HOTWORDS_FILE:
        with open(config.STT_HOTWORDS_FILE, encoding="utf-8") as fh:
            words = tuple(line.strip() for line in fh if line.strip())
    out = os.path.join(_cache_dir(), "hotwords.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(words) + "\n")
    return out


_biasing = False  # recognizer đang dùng beam + hotword (đặt trong _load_asr)


@lru_cache(maxsize=1)
def _load_asr():
    """Zipformer-vi 30M (RNN-T offline, int8) qua sherpa-onnx, chạy CPU.

    Chạy CPU là lựa chọn có chủ ý, không phải hạn chế: model int8 chỉ ~34MB nên
    CPU đã nhanh hơn thời gian thực nhiều lần, mà đổi lại GPU 4GB được để trọn
    cho OCR/TTS thay vì phải chia ba.

    Giải mã: xem `config.STT_DECODING` (beam + hotword lệnh, có số đo) — `greedy_search` để quay
    về cách cũ.
    """
    # PHẢI nạp onnxruntime (gói GPU) TRƯỚC sherpa_onnx: sherpa mang theo bản
    # libonnxruntime.so riêng, nạp nó trước thì lúc vieneu (TTS GPU) import
    # onnxruntime sẽ dính nhầm thư viện -> segfault mỗi lần (đo 2026-10-19).
    import onnxruntime  # noqa: F401
    from sherpa_onnx import OfflineRecognizer

    global _biasing
    model_dir = config.STT_MODEL_DIR
    extra = {}
    method = config.STT_DECODING
    if method == "modified_beam_search":
        vocab = _bpe_vocab(model_dir)
        if vocab is None:
            method = "greedy_search"
        else:
            extra = dict(max_active_paths=config.STT_BEAM_PATHS, modeling_unit="bpe", bpe_vocab=vocab,
                         hotwords_score=config.STT_HOTWORDS_SCORE)
            if config.STT_HOTWORDS:
                extra["hotwords_file"] = _hotwords_file()
    _biasing = method == "modified_beam_search"
    return OfflineRecognizer.from_transducer(
        encoder=os.path.join(model_dir, "encoder.int8.onnx"),
        decoder=os.path.join(model_dir, "decoder.onnx"),
        joiner=os.path.join(model_dir, "joiner.int8.onnx"),
        tokens=os.path.join(model_dir, "tokens.txt"),
        num_threads=config.STT_NUM_THREADS,
        sample_rate=_TARGET_SAMPLE_RATE,
        feature_dim=80,
        decoding_method=method,
        **extra,
    )


def decode_samples(samples: np.ndarray, hotwords=None) -> str:
    """Mẫu 16 kHz mono -> chữ thô của model (chưa `_normalize`).

    `hotwords`: tên cần ưu tiên cho RIÊNG lượt này (chỉ có tác dụng khi `_biasing`).
    """
    recognizer = _load_asr()
    if hotwords and _biasing and config.STT_USER_HOTWORDS:
        stream = recognizer.create_stream("\n".join(hotwords))
    else:
        stream = recognizer.create_stream()
    stream.accept_waveform(_TARGET_SAMPLE_RATE, samples)
    recognizer.decode_stream(stream)
    return stream.result.text


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
    return _normalize(decode_samples(samples, _user_hotwords))
