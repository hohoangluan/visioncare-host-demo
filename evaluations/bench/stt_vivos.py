"""C6 — STT (Zipformer-vi 30M, sherpa-onnx, đường VH `pipeline.stt.transcribe`) trên VIVOS test (METRICS.md C6).

    python -m bench.stt_vivos [--limit N] [--decoding production|greedy_search] [--out DIR]

Chạy đúng như production: CPU, `config.STT_NUM_THREADS` luồng, `config.STT_DECODING` (beam + hotword lệnh),
đầu vào là bytes WAV như board gửi (`transcribe(bytes)`). Chuẩn hoá chấm điểm: `tools.bench_stt_compare.normalize`
của VH (NFC, chữ thường, bỏ dấu câu) — cùng hàm bàn đo STT hiện có.
"""
import argparse
import io
import os
import re
import sys
import time
import wave
import warnings

from bench import common

common.setup(gpu=False)  # STT production chạy CPU (config.py: "Chạy CPU là lựa chọn có chủ ý")

import jiwer  # noqa: E402
import numpy as np  # noqa: E402

import config  # noqa: E402  (VH)
from pipeline import stt  # noqa: E402
from tools.bench_stt_compare import normalize  # noqa: E402  (VH, chỉ đọc)

warnings.filterwarnings("ignore", message="All-NaN slice")


def _counts_words(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """(số lỗi từ S+D+I, số từ ref)."""
    if not ref:
        return len(hyp), 0
    if not hyp:
        return len(ref), len(ref)
    o = jiwer.process_words(" ".join(ref), " ".join(hyp))
    return o.substitutions + o.deletions + o.insertions, len(ref)


def _counts_chars(ref: str, hyp: str) -> tuple[int, int]:
    if not ref:
        return len(hyp), 0
    if not hyp:
        return len(ref), len(ref)
    o = jiwer.process_characters(ref, hyp)
    return o.substitutions + o.deletions + o.insertions, len(ref)


def ratio_ci(arr) -> dict:
    """arr (n,2) = [lỗi, tổng] -> tỉ lệ gộp (WER/CER) ± CI bootstrap theo câu."""
    a = np.asarray(arr, float)
    v, lo, hi = common.bootstrap_ci(a, stat=lambda x: x[:, 0].sum() / max(x[:, 1].sum(), 1))
    return {"value": v, "ci": [lo, hi], "n": int(len(a))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--decoding", default="production", help="production = config.STT_DECODING; hoặc greedy_search")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # VH đọc đường dẫn tương đối theo cwd -> cố định tuyệt đối; cache hotword ghi ra ngoài cây VH
    if not os.path.isabs(config.STT_MODEL_DIR):
        config.STT_MODEL_DIR = os.path.join(common.VH_DIR, config.STT_MODEL_DIR)
    config._CACHE_ROOT = os.path.join(common.RESULTS, ".cache")
    if args.decoding != "production":
        config.STT_DECODING = args.decoding

    root = os.path.join(common.DATAS, "vivos", "vivos", "test")
    items = []
    for line in open(os.path.join(root, "prompts.txt"), encoding="utf-8"):
        uid, _, text = line.rstrip("\n").partition(" ")
        spk = uid.split("_")[0]
        path = os.path.join(root, "waves", spk, uid + ".wav")
        if os.path.exists(path):
            items.append({"id": uid, "spk": spk, "path": path, "ref": text})
    n_all = len(items)
    items = common.sample(items, args.limit)

    stt._load_asr()  # nạp model ngoài đồng hồ
    for it in items[:20]:  # warm-up (không tính giờ)
        stt.transcribe(open(it["path"], "rb").read())

    rows, lat, rtfs = [], [], []
    for it in items:
        raw = open(it["path"], "rb").read()
        with wave.open(io.BytesIO(raw)) as w:
            dur = w.getnframes() / w.getframerate()
        t0 = time.perf_counter()
        hyp = stt.transcribe(raw)
        ms = (time.perf_counter() - t0) * 1000
        r_tok, h_tok = normalize(it["ref"]), normalize(hyp)
        we, wn = _counts_words(r_tok, h_tok)
        ce, cn = _counts_chars(" ".join(r_tok), " ".join(h_tok))
        rows.append({"id": it["id"], "spk": it["spk"], "ref": it["ref"], "hyp": hyp, "dur_s": dur, "ms": ms,
                     "rtf": ms / 1000 / dur, "word_err": we, "n_words": wn, "char_err": ce, "n_chars": cn})
        lat.append(ms); rtfs.append(ms / 1000 / dur)

    ww = np.array([[r["word_err"], r["n_words"]] for r in rows], float)
    cc = np.array([[r["char_err"], r["n_chars"]] for r in rows], float)
    per_spk = {}
    for spk in sorted({r["spk"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["spk"] == spk]
        per_spk[spk] = ratio_ci(ww[idx]) | {"n_utts": len(idx)}
    worst = max(per_spk, key=lambda k: per_spk[k]["value"])
    metrics = {
        "wer": ratio_ci(ww), "cer": ratio_ci(cc), "per_speaker_wer": per_spk,
        "worst_speaker": {"id": worst, **per_spk[worst]},
        "best_speaker": {"id": min(per_spk, key=lambda k: per_spk[k]["value"]),
                         **per_spk[min(per_spk, key=lambda k: per_spk[k]["value"])]},
        "empty_hyp": int(sum(1 for r in rows if not r["hyp"].strip())),
    }
    total_dur = float(sum(r["dur_s"] for r in rows))
    cfg = {"limit": args.limit, "n_utts": len(rows), "n_utts_all": n_all, "n_speakers": len(per_spk),
           "device": "CPU (sherpa-onnx OfflineRecognizer, như production)", "num_threads": config.STT_NUM_THREADS,
           "decoding": config.STT_DECODING, "beam_paths": config.STT_BEAM_PATHS,
           "hotwords": bool(config.STT_HOTWORDS), "hotwords_score": config.STT_HOTWORDS_SCORE,
           "user_hotwords": list(stt.user_hotwords()), "model_dir": config.STT_MODEL_DIR,
           "loadavg_start": os.getloadavg(), "audio_total_s": total_dur,
           "normalize": "tools.bench_stt_compare.normalize (NFC, lower, bỏ dấu câu)"}
    payload = {"meta": common.run_meta(cfg), "metrics": metrics,
               "latency": {"per_utt": common.latency_summary(lat), "rtf_median": float(np.median(rtfs)), "rtf_p90": float(np.percentile(rtfs, 90)), "rtf_total": float(sum(lat) / 1000 / total_dur),
                           "loadavg_end": os.getloadavg()},
               "per_sample": rows}
    tag = ("full" if args.limit is None else f"limit{args.limit}") + ("" if args.decoding == "production" else "_" + args.decoding)
    path = common.write_result("stt_vivos", tag, payload, args.out)
    print("ghi", path)
    print(f"n={len(rows)} WER={metrics['wer']['value']*100:.2f}% [{metrics['wer']['ci'][0]*100:.2f},{metrics['wer']['ci'][1]*100:.2f}] "
          f"CER={metrics['cer']['value']*100:.2f}% worst={worst} {per_spk[worst]['value']*100:.1f}% "
          f"p50={payload['latency']['per_utt']['p50_ms']}ms RTF={payload['latency']['rtf_median']:.3f}")


if __name__ == "__main__":
    sys.exit(main())
