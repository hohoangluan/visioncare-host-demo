"""So Zipformer-vi 30M (sherpa-onnx, hiện tại) với ChunkFormer CTC large: WER + độ trễ.

Cùng bộ audio cho cả hai: FLEURS vi_vn test (parquet) và/hoặc thư mục wav có
file `.txt` nhãn cạnh bên. Độ trễ đo mỗi câu sau warm-up, trên CPU và GPU.

    python tools/bench_stt_compare.py --fleurs fleurs_vi_test.parquet --limit 200
    python tools/bench_stt_compare.py --wav-dir storage/labelled --models zipformer
"""

import argparse
import io
import os
import re
import statistics
import sys
import tempfile
import time
import unicodedata
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def load_fleurs(path: str, limit: int) -> list[tuple[np.ndarray, str]]:
    import pyarrow.parquet as pq
    import soundfile as sf

    table = pq.read_table(path).to_pylist()[:limit]
    items = []
    for row in table:
        audio = row["audio"]
        data, sr = sf.read(io.BytesIO(audio["bytes"]), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            from pipeline.stt import _resample
            data = _resample(data, sr)
        items.append((data.astype(np.float32), row["transcription"]))
    return items


def load_wav_dir(path: str) -> list[tuple[np.ndarray, str]]:
    from pipeline import stt

    items = []
    for name in sorted(os.listdir(path)):
        if not name.endswith(".wav"):
            continue
        ref_path = os.path.join(path, name[:-4] + ".txt")
        if not os.path.exists(ref_path):
            continue
        samples, sr = stt._decode_wav(open(os.path.join(path, name), "rb").read())
        items.append((stt._resample(samples, sr), open(ref_path, encoding="utf-8").read().strip()))
    return items


class Zipformer:
    name = "zipformer-30M-int8 (cpu)"

    def __init__(self) -> None:
        from pipeline import stt

        self._stt = stt
        self._rec = stt._load_asr()

    def __call__(self, samples: np.ndarray) -> str:
        stream = self._rec.create_stream()
        stream.accept_waveform(16000, samples)
        self._rec.decode_stream(stream)
        return stream.result.text


class ChunkFormer:
    def __init__(self, model_id: str, device: str) -> None:
        import torch
        from chunkformer import ChunkFormerModel

        self.name = f"chunkformer ({device})"
        self._torch = torch
        self._model = ChunkFormerModel.from_pretrained(model_id).to(device).eval()
        self._dir = tempfile.mkdtemp(prefix="cf-")

    def __call__(self, samples: np.ndarray) -> str:
        path = os.path.join(self._dir, "a.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        with self._torch.inference_mode():
            out = self._model.endless_decode(
                audio_path=path, chunk_size=64, left_context_size=128, right_context_size=128,
                total_batch_duration=1800, return_timestamps=False,
            )
        return out if isinstance(out, str) else str(out)


def run(model, items, warmup: int = 3) -> dict:
    for samples, _ in items[:warmup]:
        model(samples)
    errors = words = 0
    times, rtf = [], []
    for samples, ref in items:
        start = time.perf_counter()
        hyp = model(samples)
        dt = time.perf_counter() - start
        times.append(dt)
        rtf.append(dt / (len(samples) / 16000))
        r = normalize(ref)
        errors += edit_distance(r, normalize(hyp))
        words += len(r)
    return {
        "model": model.name, "n": len(items), "wer": errors / max(words, 1),
        "p50_ms": statistics.median(times) * 1000,
        "p90_ms": sorted(times)[int(0.9 * (len(times) - 1))] * 1000,
        "rtf": statistics.median(rtf),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleurs")
    parser.add_argument("--wav-dir")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--models", nargs="*", default=["zipformer", "chunkformer-cuda", "chunkformer-cpu"])
    parser.add_argument("--chunkformer", default=os.environ.get("ASR_MODEL", "khanhld/chunkformer-ctc-large-vie"))
    parser.add_argument("--max-seconds", type=float, default=0, help="cắt audio (mô phỏng câu lệnh ngắn)")
    args = parser.parse_args()

    items = []
    if args.fleurs:
        items += load_fleurs(args.fleurs, args.limit)
    if args.wav_dir:
        items += load_wav_dir(args.wav_dir)
    if not items:
        sys.exit("không có audio nào")
    total = sum(len(s) for s, _ in items) / 16000
    print(f"{len(items)} câu, tổng {total:.0f}s audio, trung bình {total / len(items):.1f}s/câu")

    for key in args.models:
        if key == "zipformer":
            model = Zipformer()
        else:
            model = ChunkFormer(args.chunkformer, "cuda" if key.endswith("cuda") else "cpu")
        r = run(model, items)
        print(f"{r['model']:32s} WER={r['wer'] * 100:5.2f}%  p50={r['p50_ms']:6.1f}ms  "
              f"p90={r['p90_ms']:6.1f}ms  RTF={r['rtf']:.4f}")


if __name__ == "__main__":
    main()
