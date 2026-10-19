"""Biến thể lỗi STT thật cho tập gold: văn bản -> VieNeu TTS -> nhiễu -> Zipformer.

Chưa có ghi âm kính thật, nên đây là phần gần nhất với đầu vào thật của bộ phân
loại: bản ghi sai chữ, rụng từ, hoặc rỗng do tạp âm. Nhãn đi theo câu gốc.

Mỗi câu chỉ tổng hợp MỘT lần (một giọng, chọn tất định theo văn bản) rồi trộn nhiễu
ở mức SNR 10 dB. Nhiễu tổng hợp, seed cố định theo văn bản + mức SNR nên chạy
lại ra đúng kết quả cũ:
- pink noise (ồn nền/đường phố: năng lượng giảm theo tần số)
- "babble": cộng 3 câu TTS khác (người nói xung quanh), mỗi câu −12 dB so với lời nói
- ù tần thấp (quạt/động cơ: 50 Hz và hài, cộng nhiễu <200 Hz)
Ba thành phần cộng thành MỘT nhiễu rồi co giãn để đạt đúng SNR yêu cầu so với lời nói.

Tín hiệu sau trộn còn đi qua IMA ADPCM (mã hoá rồi giải mã) vì kính gửi lên
đúng định dạng đó; bỏ bước này thì STT thấy âm sạch hơn thật.
"""

import io
import json
import os
import time
import wave
import zlib
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
# Quy mô nhỏ: chỉ MỘT mức SNR (10 dB, giữa dải 20/10/5). `mix()` nhận mức bất kỳ; muốn
# thêm "stt_snr20"/"stt_snr5" chỉ cần thêm vào đây.
SNRS = {"stt_snr10": 10.0}
_PAD_S = 0.25  # khoảng lặng hai đầu, như lúc nhấn/nhả nút

# Nhiều giọng (Bắc/Trung/Nam, nam/nữ) cho đỡ lệ thuộc một giọng; `Ngọc Linh` là
# giọng đang dùng ở server. Chọn tất định theo văn bản.
VOICES = ["Ngọc Linh", "Đoan Trang", "Trúc Ly", "Ngọc Trân", "Thục Đoan", "Hải Đăng",
          "Quang Sơn", "Thái Sơn", "Minh Triết", "Phạm Tuyên"]

# Lời nền cho babble: cố ý không trùng nội dung câu lệnh, để không gieo từ khoá lệnh
# vào bản ghi.
BABBLE_TEXTS = [
    "hôm nay trời nóng quá không biết chiều có mưa không",
    "em ơi lấy giúp chị cái túi ở trên bàn với",
    "cuối tuần này nhà mình về quê thăm ông bà nhé",
    "anh có thấy cái chìa khoá xe của em để ở đâu không",
    "dạo này giá rau ngoài chợ tăng ghê lắm",
    "con làm bài tập xong chưa xuống ăn cơm đi",
    "bác ơi cho cháu hai cái bánh mì không cay",
    "mai họp lúc chín giờ nhớ mang theo tài liệu nhé",
    "chiếc xe này chạy êm nhưng hơi tốn xăng",
    "tối qua tôi xem trận đấu hay lắm cả nhà cùng reo hò",
    "nhà hàng bên kia đường mới mở nghe nói đồ ăn ngon",
    "chị hai dặn mua thêm ít trái cây về cúng",
    "đợi tí nữa đèn xanh rồi mình đi qua",
    "thằng bé nhà bên học giỏi lắm năm nào cũng được khen",
    "trời tối rồi mau về kẻo mẹ lo",
    "cái điện thoại này pin yếu quá sạc cả đêm mà vẫn hết",
]


def voice_for(text: str) -> str:
    return VOICES[zlib.crc32(text.encode("utf-8")) % len(VOICES)]


def synth(engine, text: str, voice: str) -> np.ndarray:
    """Văn bản -> float32 mono 16 kHz (cùng cách hạ mẫu với `pipeline.tts`: trung bình nhóm 3)."""
    audio = engine.infer(text, voice=voice, show_progress=False)
    samples = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    ratio = int(round(engine.sample_rate / SAMPLE_RATE))
    usable = len(samples) - len(samples) % ratio
    return samples[:usable].reshape(-1, ratio).mean(axis=1) if usable else samples[:0]


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Nhiễu hồng (1/f) bằng tạo phổ rồi IFFT."""
    spec = np.fft.rfft(rng.standard_normal(n))
    freqs = np.arange(len(spec), dtype=np.float64)
    freqs[0] = 1.0
    out = np.fft.irfft(spec / np.sqrt(freqs), n)
    return (out / (np.std(out) + 1e-12)).astype(np.float32)


def low_hum(n: int, rng: np.random.Generator) -> np.ndarray:
    """Ù tần thấp: 50 Hz + hài 100/150 Hz + nhiễu giới hạn dưới 200 Hz."""
    from scipy.signal import butter, sosfilt

    t = np.arange(n) / SAMPLE_RATE
    tone = (np.sin(2 * np.pi * 50 * t + rng.uniform(0, 6.28))
            + 0.5 * np.sin(2 * np.pi * 100 * t + rng.uniform(0, 6.28))
            + 0.25 * np.sin(2 * np.pi * 150 * t + rng.uniform(0, 6.28)))
    rumble = sosfilt(butter(4, 200, btype="low", fs=SAMPLE_RATE, output="sos"),
                     rng.standard_normal(n))
    out = tone / (np.std(tone) + 1e-12) + 0.7 * rumble / (np.std(rumble) + 1e-12)
    return (out / (np.std(out) + 1e-12)).astype(np.float32)


def babble(pool: list[np.ndarray], n: int, rng: np.random.Generator,
           speech_rms: float) -> np.ndarray:
    """Cộng 3 câu TTS khác (chọn ngẫu nhiên có seed), mỗi câu −12 dB so với lời nói."""
    out = np.zeros(n, dtype=np.float32)
    for idx in rng.choice(len(pool), size=3, replace=False):
        clip = pool[int(idx)]
        shift = int(rng.integers(0, max(1, len(clip))))
        clip = np.roll(clip, shift)
        clip = np.resize(clip, n)  # lặp nếu ngắn hơn câu lệnh
        out += clip * (speech_rms * 10 ** (-12 / 20) / (_rms(clip) + 1e-9))
    return out


def mix(speech: np.ndarray, snr_db: float, pool: list[np.ndarray], seed: int) -> np.ndarray:
    """Trộn lời nói với nhiễu tổng hợp ở đúng `snr_db` (dB, theo RMS lời nói)."""
    rng = np.random.default_rng(seed)
    pad = np.zeros(int(_PAD_S * SAMPLE_RATE), dtype=np.float32)
    padded = np.concatenate([pad, speech, pad])
    n = len(padded)
    s_rms = _rms(speech) + 1e-9
    noise = (pink_noise(n, rng) * s_rms * 0.5
             + babble(pool, n, rng, s_rms)
             + low_hum(n, rng) * s_rms * 0.1)
    noise *= s_rms / (10 ** (snr_db / 20)) / (_rms(noise) + 1e-9)
    mixed = padded + noise
    peak = float(np.max(np.abs(mixed)))
    return mixed / peak * 0.95 if peak > 0.95 else mixed


def adpcm_roundtrip(samples: np.ndarray) -> np.ndarray:
    """float32 -> IMA ADPCM -> float32, như đường audio từ kính lên server."""
    from pipeline import adpcm

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    decoded = adpcm.decode_blocks(adpcm.encode_blocks(pcm))
    return decoded.astype(np.float32) / 32768.0


def transcribe(samples: np.ndarray) -> str:
    from pipeline import stt

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return stt.transcribe(buf.getvalue())


def run_shard(texts: list[str], shard: int, shards: int, out_path: Path) -> None:
    """Xử lý các câu `texts[shard::shards]`; ghi nối từng câu (chạy lại thì bỏ qua câu đã có)."""
    from pipeline import stt, tts

    import torch

    if not torch.cuda.is_available():  # TTS luôn chạy GPU: không lùi về CPU
        raise RuntimeError("không thấy GPU (CUDA_VISIBLE_DEVICES="
                           f"{os.environ.get('CUDA_VISIBLE_DEVICES')!r}) — dừng, không chạy TTS bằng CPU")
    stt._load_asr()  # nạp onnxruntime/sherpa theo đúng thứ tự trước khi vieneu vào
    engine = tts._load_tts()
    print(f"shard {shard}/{shards}: GPU {os.environ.get('CUDA_VISIBLE_DEVICES')} "
          f"({torch.cuda.get_device_name(0)})", flush=True)

    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["text"])

    pool = [synth(engine, t, VOICES[i % len(VOICES)]) for i, t in enumerate(BABBLE_TEXTS)]
    mine = [t for t in texts[shard::shards] if t not in done]
    started = time.time()
    with out_path.open("a", encoding="utf-8") as fh:
        for n, text in enumerate(mine, 1):
            voice = voice_for(text)
            speech = synth(engine, text, voice)
            stt_out = {}
            for name, snr in SNRS.items():
                seed = zlib.crc32(f"{text}|{name}".encode("utf-8"))
                noisy = adpcm_roundtrip(mix(speech, snr, pool, seed)) if len(speech) else speech
                stt_out[name] = transcribe(noisy) if len(noisy) else ""
            fh.write(json.dumps({"text": text, "voice": voice, "stt": stt_out},
                                ensure_ascii=False) + "\n")
            fh.flush()
            if n % 50 == 0:
                print(f"shard {shard}/{shards}: {n}/{len(mine)} "
                      f"({(time.time() - started) / n:.2f}s/câu)", flush=True)
