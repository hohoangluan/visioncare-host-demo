"""Bảng cấu hình STT cho `tools/bench_stt_cmd.py` — MỖI cấu hình đổi đúng một biến so với `greedy`."""

import os
import tempfile
import wave
from pathlib import Path

import numpy as np

from tools.bench_stt_cmd import COMMAND_HOTWORDS, ROOT, SR, Sherpa

CAND = "models/stt_candidates"
ZIP70 = f"{CAND}/sherpa-onnx-zipformer-vi-int8-2025-04-20"



class Zip70(Sherpa):
    """Zipformer-vi bản lớn (70M, 2025-04-20): cùng API transducer, tên file khác."""

    def __init__(self, **kw):
        super().__init__(model_dir=ZIP70, encoder="encoder-epoch-12-avg-8.int8.onnx",
                         joiner="joiner-epoch-12-avg-8.int8.onnx", decoder="decoder-epoch-12-avg-8.onnx", **kw)


class Moonshine:
    def __init__(self, threads=2):
        import onnxruntime  # noqa: F401
        from sherpa_onnx import OfflineRecognizer

        d = ROOT / CAND / "sherpa-onnx-moonshine-base-vi-quantized-2026-02-27"
        self.rec = OfflineRecognizer.from_moonshine_v2(
            encoder=str(d / "encoder_model.ort"), decoder=str(d / "decoder_model_merged.ort"),
            tokens=str(d / "tokens.txt"), num_threads=threads)

    def decode(self, samples, extra=None):
        s = self.rec.create_stream()
        s.accept_waveform(SR, samples)
        self.rec.decode_stream(s)
        return s.result.text.strip()


class Omnilingual:
    def __init__(self, threads=2):
        import onnxruntime  # noqa: F401
        from sherpa_onnx import OfflineRecognizer

        d = ROOT / CAND / "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05"
        self.rec = OfflineRecognizer.from_omnilingual_asr_ctc(
            model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"), num_threads=threads)

    def decode(self, samples, extra=None):
        s = self.rec.create_stream()
        s.accept_waveform(SR, samples)
        self.rec.decode_stream(s)
        return s.result.text.strip()


class ChunkFormer:
    def __init__(self, device="cuda", model_id="khanhld/chunkformer-ctc-large-vie"):
        import torch
        from chunkformer import ChunkFormerModel

        self.torch = torch
        self.model = ChunkFormerModel.from_pretrained(model_id).to(device).eval()
        self.dir = tempfile.mkdtemp(prefix="cf-")

    def decode(self, samples, extra=None):
        path = os.path.join(self.dir, "a.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        with self.torch.inference_mode():
            out = self.model.endless_decode(
                audio_path=path, chunk_size=64, left_context_size=128, right_context_size=128,
                total_batch_duration=1800, return_timestamps=False)
        return (out if isinstance(out, str) else str(out)).strip()


def make(cfg: str):
    # hậu tố "@t<N>": số luồng CPU (mặc định 2); "@g": chạy ONNX trên GPU (CUDA_VISIBLE_DEVICES chọn card)
    if "@" in cfg:
        base, _, opt = cfg.partition("@")
        dec = make(base)
        if opt.startswith("t") and isinstance(dec, Sherpa):
            return _rebuild(dec, threads=int(opt[1:]))
        raise SystemExit(f"hậu tố không biết: {cfg}")
    # ── baseline và biến giải mã (cùng model Zipformer-vi 30M) ──
    if cfg == "greedy":
        return Sherpa()
    if cfg.startswith("thr"):  # thr1 / thr4: số luồng
        return Sherpa(threads=int(cfg[3:]))
    if cfg in ("beam2", "beam4"):
        return Sherpa(method="modified_beam_search", paths=int(cfg[4:]))
    if cfg.startswith("hw"):  # hw<score>_<paths>: hotword lệnh cố định, beam <paths>
        score, _, paths = cfg[2:].partition("_")
        return Sherpa(method="modified_beam_search", paths=int(paths or 4), hotwords=list(COMMAND_HOTWORDS),
                      score=float(score))
    if cfg.startswith("uhw"):  # uhw<score>_<paths>: hotword THEO NGƯỜI DÙNG (create_stream(hotwords=...))
        score, _, paths = cfg[3:].partition("_")
        return Sherpa(method="modified_beam_search", paths=int(paths or 4), stream_hotwords=True,
                      score=float(score))
    if cfg.startswith("bothhw"):  # bothhw<score>_<paths>: cố định + theo người dùng
        score, _, paths = cfg[6:].partition("_")
        return Sherpa(method="modified_beam_search", paths=int(paths or 4), hotwords=list(COMMAND_HOTWORDS),
                      stream_hotwords=True, score=float(score))
    # ── model khác ──
    if cfg == "zip70":
        return Zip70()
    if cfg == "zip70_beam4":
        return Zip70(method="modified_beam_search", paths=4)
    if cfg == "moonshine":
        return Moonshine()
    if cfg == "omni300":
        return Omnilingual()
    if cfg == "chunkformer_cuda":
        return ChunkFormer("cuda")
    if cfg == "chunkformer_cpu":
        return ChunkFormer("cpu")
    raise SystemExit(f"cấu hình không biết: {cfg}")


def _rebuild(dec, **over):
    """Dựng lại Sherpa với tham số khác (giữ nguyên các biến còn lại)."""
    kw = dict(dec.kw)
    kw.update(over)
    return Sherpa(**kw)
