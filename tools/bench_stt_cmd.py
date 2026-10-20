"""Bàn đo STT câu lệnh của kính: nghe ĐÚNG lệnh + trễ (tool này lo phần dựng audio và chạy).

Ba bước (xem `tools/bench_stt_report.py` cho bước tính chỉ số):

  1. dựng audio (GPU, VieNeu TTS; chạy một lần, cache tất định):
       CUDA_VISIBLE_DEVICES=0 python -m tools.bench_stt_cmd build --cache DIR --shard 0 --shards 3
  2. giải mã bằng một cấu hình STT, ghi `DIR/results/<cfg>.jsonl`:
       python -m tools.bench_stt_cmd run --cache DIR --cfg greedy
  3. báo cáo: python -m tools.bench_stt_report --cache DIR --cfgs greedy beam4 ...

Bàn đo gồm:
- `cmd`: câu gold dev/test + câu lệnh bổ sung (tools/stt_bench_texts.py), 3 giọng mỗi câu,
  bản sạch (TTS + đệm im lặng) và bản nhiễu (SNR10 + ADPCM, như đường kính -> server);
- `vietmed`: giọng THẬT, mẫu phân tầng 168 clip từ tập test VietMed (dựng lại theo mô tả
  docs/EXTERNAL_VALIDATION_DATASETS.md vì bộ gốc không còn trên đĩa), dùng đo WER và việc
  hotword có chèn từ lệnh vào lời nói thường hay không.
"""

import argparse
import io
import json
import os
import statistics
import sys
import time
import wave
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR = 16000


# ── bộ nhớ đệm audio ───────────────────────────────────────────────────────

def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def voices_for(text: str) -> list[str]:
    """3 giọng khác nhau (Bắc/Trung/Nam, nam/nữ trộn), chọn tất định theo văn bản."""
    from tools.intent_gold.stt_variants import VOICES

    i = zlib.crc32(text.encode("utf-8")) % len(VOICES)
    return [VOICES[i], VOICES[(i + 3) % len(VOICES)], VOICES[(i + 7) % len(VOICES)]]


def build_cmd(cache: Path, shard: int, shards: int) -> None:
    import torch
    from pipeline import stt, tts
    from tools.intent_gold import stt_variants as sv
    from tools.stt_bench_texts import all_texts

    if not torch.cuda.is_available():
        raise RuntimeError("không thấy GPU: dừng, không chạy TTS bằng CPU")
    stt._load_asr()  # thứ tự nạp onnxruntime/sherpa trước vieneu (xem pipeline/stt.py)
    engine = tts._load_tts()
    wav_dir = cache / "cmd"
    wav_dir.mkdir(parents=True, exist_ok=True)
    part = cache / f"manifest_cmd.{shard}.jsonl"
    done = set()
    if part.exists():
        done = {json.loads(l)["id"] for l in part.read_text().splitlines() if l.strip()}
    pool = [sv.synth(engine, t, sv.VOICES[i % len(sv.VOICES)]) for i, t in enumerate(sv.BABBLE_TEXTS)]
    texts = all_texts()[shard::shards]
    t0 = time.time()
    with part.open("a", encoding="utf-8") as fh:
        for n, row in enumerate(texts, 1):
            for vi, voice in enumerate(voices_for(row["text"])):
                base = f"{zlib.crc32(row['text'].encode('utf-8')):08x}_v{vi}"
                if f"{base}:clean" in done:
                    continue
                speech = sv.synth(engine, row["text"], voice)
                if not len(speech):
                    continue
                pad = np.zeros(int(sv._PAD_S * SR), dtype=np.float32)
                clean = np.concatenate([pad, speech, pad])
                seed = zlib.crc32(f"{row['text']}|{voice}|snr10".encode("utf-8"))
                noisy = sv.adpcm_roundtrip(sv.mix(speech, 10.0, pool, seed))
                for cond, audio in (("clean", clean), ("snr10", noisy)):
                    write_wav(wav_dir / f"{base}_{cond}.wav", audio)
                    fh.write(json.dumps({
                        "id": f"{base}:{cond}", "set": "cmd", "split": row["split"], "src": row["src"],
                        "text": row["text"], "label": row["label"], "params": row["params"],
                        "device": row["device"], "voice": voice, "cond": cond,
                        "wav": f"cmd/{base}_{cond}.wav", "seconds": len(audio) / SR,
                    }, ensure_ascii=False) + "\n")
                fh.flush()
            if n % 20 == 0:
                print(f"shard {shard}: {n}/{len(texts)} ({(time.time() - t0) / n:.1f}s/câu)", flush=True)


ACCENT_GROUP = {"North Central Coast": "Trung", "South Central Coast": "Trung", "North": "Bắc",
                "South East": "Nam", "South West": "Nam"}


def build_vietmed(cache: Path, parquet: Path, seed: int = 20261020) -> None:
    """168 clip phân tầng theo vùng (30 Bắc / 59 Trung / 79 Nam, như tài liệu), 2–15 s."""
    import pyarrow.parquet as pq
    import soundfile as sf

    from pipeline.stt import _resample

    table = pq.read_table(parquet).to_pylist()
    quota = {"Bắc": 30, "Trung": 59, "Nam": 79}
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[dict]] = {k: [] for k in quota}
    for r in table:
        grp = next((v for k, v in ACCENT_GROUP.items() if r["accent"].startswith(k)), None)
        if grp and 2.0 <= r["duration"] <= 15.0 and len(r["text"].split()) >= 4:
            by_group[grp].append(r)
    wav_dir = cache / "vietmed"
    wav_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for grp, need in quota.items():
        pool = by_group[grp]
        idx = rng.permutation(len(pool))[:need]
        for k in idx:
            r = pool[int(k)]
            data, sr = sf.read(io.BytesIO(r["audio"]["bytes"]), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sr != SR:
                data = _resample(data, sr)
            name = f"{r['utterance_id']}.wav"
            write_wav(wav_dir / name, data)
            out.append({"id": r["utterance_id"], "set": "vietmed", "split": "vietmed", "text": r["text"],
                        "accent": grp, "gender": r["gender"], "rec_condition": r["rec_condition"],
                        "wav": f"vietmed/{name}", "seconds": len(data) / SR})
    (cache / "manifest_vietmed.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(f"vietmed: {len(out)} clip, {sum(r['seconds'] for r in out) / 60:.1f} phút")


def build_real(cache: Path, storage: Path) -> None:
    """Ghi âm THẬT từ kính (storage/request*.wav, ADPCM, không nhãn) -> wav PCM trong cache."""
    from pipeline import stt

    out_dir = cache / "real"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(storage.glob("request*.wav")):
        try:
            samples, sr = stt._decode_wav(p.read_bytes())
        except Exception as exc:  # noqa: BLE001
            print(f"bỏ {p.name}: {exc}")
            continue
        samples = stt._resample(samples, sr)
        if len(samples) < SR * 0.3:
            continue
        write_wav(out_dir / p.name, samples)
        rows.append({"id": f"real:{p.stem}", "set": "real", "split": "real", "text": "", "wav": f"real/{p.name}",
                     "seconds": len(samples) / SR})
    (cache / "manifest_real.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"real: {len(rows)} clip")


def load_manifest(cache: Path, sets=("cmd", "vietmed")) -> list[dict]:
    rows, seen = [], set()
    for p in sorted(cache.glob("manifest_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                # Cùng một câu nằm ở cả gold dev và test -> cùng id/cùng wav: giữ một dòng.
                if r["set"] in sets and r["id"] not in seen:
                    seen.add(r["id"])
                    rows.append(r)
    rows.sort(key=lambda r: r["id"])
    return rows


# ── các cấu hình STT ──────────────────────────────────────────────────────

# Danh sách từ lệnh cố định (hotword cấp hệ thống): động từ lệnh + đối tượng hay gặp.
COMMAND_HOTWORDS = [
    "NHẮN CHO", "NHẮN TIN", "NHẮN TIN CHO", "GỌI CHO", "GỌI ĐIỆN CHO", "GỌI ĐIỆN", "ĐỌC TIN NHẮN",
    "CẤP CỨU", "KHẨN CẤP", "CỨU TÔI", "BẬT CẢNH BÁO", "TẮT CẢNH BÁO", "DỪNG CẢNH BÁO", "NGỪNG CẢNH BÁO",
    "CẢNH BÁO VẬT CẢN", "DẪN ĐƯỜNG", "CHỈ ĐƯỜNG", "DỪNG DẪN ĐƯỜNG", "TẮT CHỈ ĐƯỜNG", "TẮT NHẠC", "DỪNG NHẠC",
    "MẸ", "BỐ", "BA", "MÁ", "VỢ", "CHỒNG",
]


class Sherpa:
    """Zipformer-vi qua sherpa-onnx; mọi biến giải mã là tham số, mặc định = pipeline hiện tại."""

    def __init__(self, model_dir="models/stt", encoder="encoder.int8.onnx", joiner="joiner.int8.onnx",
                 method="greedy_search", paths=4, threads=2, hotwords=None, score=1.5, provider="cpu",
                 stream_hotwords=None, blank_penalty=0.0, decoder="decoder.onnx"):
        import onnxruntime  # noqa: F401  (PHẢI nạp trước sherpa_onnx, xem pipeline/stt.py)
        import tempfile
        from sherpa_onnx import OfflineRecognizer

        self.kw = dict(model_dir=model_dir, encoder=encoder, joiner=joiner, method=method, paths=paths,
                       threads=threads, hotwords=hotwords, score=score, provider=provider,
                       stream_hotwords=stream_hotwords, blank_penalty=blank_penalty, decoder=decoder)
        d = str(ROOT / model_dir)
        kw = {}
        self.hotwords = hotwords
        self.stream_hotwords = stream_hotwords
        if hotwords or stream_hotwords:
            kw["modeling_unit"] = "bpe"
            kw["bpe_vocab"] = ensure_bpe_vocab(d)
            kw["hotwords_score"] = score
            if hotwords:
                f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
                f.write("\n".join(hotwords) + "\n")
                f.close()
                kw["hotwords_file"] = f.name
        self.rec = OfflineRecognizer.from_transducer(
            encoder=os.path.join(d, encoder), decoder=os.path.join(d, decoder),
            joiner=os.path.join(d, joiner), tokens=os.path.join(d, "tokens.txt"),
            num_threads=threads, sample_rate=SR, feature_dim=80, decoding_method=method,
            max_active_paths=paths, provider=provider, blank_penalty=blank_penalty, **kw)

    def decode(self, samples: np.ndarray, extra_hotwords: list[str] | None = None) -> str:
        if extra_hotwords and self.stream_hotwords is not None:
            stream = self.rec.create_stream("\n".join(w.upper() for w in extra_hotwords))
        else:
            stream = self.rec.create_stream()
        stream.accept_waveform(SR, samples)
        self.rec.decode_stream(stream)
        return stream.result.text.strip()


def ensure_bpe_vocab(model_dir: str) -> str:
    """sherpa cần `bpe.vocab` (văn bản); trong models/stt chỉ có `bpe.model` -> xuất ra cạnh nó."""
    out = Path(model_dir) / "bpe.vocab"
    if out.exists():
        return str(out)
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(Path(model_dir) / "bpe.model"))
    lines = [f"{sp.id_to_piece(i)}\t{sp.get_score(i)}" for i in range(sp.vocab_size())]
    try:
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(out)
    except OSError:
        alt = Path("/tmp") / "bpe.vocab"
        alt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(alt)


def make_decoder(cfg: str):
    from tools import stt_bench_cfgs

    return stt_bench_cfgs.make(cfg)


# ── chạy ───────────────────────────────────────────────────────────────────

def run_cfg(cache: Path, cfg: str, reps: int, sets, partial_sample: int, limit: int | None, out_name: str | None = None) -> None:
    name = out_name or cfg
    dec = make_decoder(cfg)
    rows = load_manifest(cache, sets)
    if limit:
        rows = rows[:limit]
    out_dir = cache / "results"
    out_dir.mkdir(exist_ok=True)
    audio = {r["id"]: read_wav(cache / r["wav"]) for r in rows}
    names = per_user_names(rows)
    for r in rows[:5]:  # làm nóng
        dec.decode(audio[r["id"]])
    results = []
    t_start = time.time()
    for n, r in enumerate(rows, 1):
        x = audio[r["id"]]
        extra = names.get(r["id"])
        times, hyp = [], ""
        for k in range(reps):
            t0 = time.perf_counter()
            h = dec.decode(x, extra)
            times.append(time.perf_counter() - t0)
            if k == 0:
                hyp = h
        results.append({"id": r["id"], "hyp": hyp, "ms": min(times) * 1000, "ms_med": statistics.median(times) * 1000})
        if n % 400 == 0:
            print(f"{cfg}: {n}/{len(rows)} ({time.time() - t_start:.0f}s)", flush=True)
    # Chi phí partial: giải lại prefix mỗi 0,3 s (như stt_stream) trên một mẫu clip.
    partial = []
    step = max(1, len(rows) // max(partial_sample, 1))
    for r in rows[::step][:partial_sample]:
        x = audio[r["id"]]
        total, calls = 0.0, 0
        t = 0.3
        dur = len(x) / SR
        while t < dur:
            t0 = time.perf_counter()
            dec.decode(x[: int(t * SR)], names.get(r["id"]))
            total += time.perf_counter() - t0
            calls += 1
            t += 0.3
        t0 = time.perf_counter()
        dec.decode(x, names.get(r["id"]))
        total += time.perf_counter() - t0
        partial.append({"id": r["id"], "seconds": dur, "calls": calls + 1, "total_ms": total * 1000})
    tag = ".real" if list(sets) == ["real"] else ""
    (out_dir / f"{name}{tag}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results),
                                          encoding="utf-8")
    (out_dir / f"{name}{tag}.partial.json").write_text(json.dumps(partial), encoding="utf-8")
    print(f"{cfg}: xong {len(results)} clip trong {time.time() - t_start:.0f}s")


def per_user_names(rows: list[dict]) -> dict[str, list[str]]:
    """Danh sách tên người thân giả lập của "người dùng" cho mỗi clip (care_links: 3 người).

    Gồm tên thật trong lệnh (nếu có contact_name) + 2 tên gây nhiễu chọn tất định; clip không
    nhắc người nào (chat, VietMed) vẫn nhận 3 tên nhiễu -> đo được hotword theo người dùng
    có chèn bừa không.
    """
    from tools.stt_bench_texts import NAMES

    out = {}
    for r in rows:
        want = (r.get("params") or {}).get("contact_name")
        h = zlib.crc32(r["id"].split(":")[0].encode())
        decoys = [NAMES[(h + k * 7) % len(NAMES)] for k in range(1, 4)]
        names = ([want] if want else []) + [d for d in decoys if d != want]
        out[r["id"]] = names[:3]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--cache", required=True)
    b.add_argument("--shard", type=int, default=0)
    b.add_argument("--shards", type=int, default=1)
    v = sub.add_parser("vietmed")
    v.add_argument("--cache", required=True)
    v.add_argument("--parquet", required=True)
    rl = sub.add_parser("real")
    rl.add_argument("--cache", required=True)
    rl.add_argument("--storage", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cache", required=True)
    r.add_argument("--cfg", required=True)
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--sets", nargs="*", default=["cmd", "vietmed"])
    r.add_argument("--partial-sample", type=int, default=60)
    r.add_argument("--limit", type=int)
    r.add_argument("--out-name")
    args = ap.parse_args()
    cache = Path(args.cache)
    if args.cmd == "build":
        build_cmd(cache, args.shard, args.shards)
    elif args.cmd == "real":
        build_real(cache, Path(args.storage))
    elif args.cmd == "vietmed":
        build_vietmed(cache, Path(args.parquet))
    else:
        run_cfg(cache, args.cfg, args.reps, args.sets, args.partial_sample, args.limit, args.out_name)


if __name__ == "__main__":
    main()
