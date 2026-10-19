"""Sinh clip cue để nạp vào flash kính: `python tools/make_cue_clips.py --out assets/cues`.

Mỗi id trong `pipeline/cues.py` -> `<out>/<id>.wav` (WAV IMA ADPCM 16 kHz mono, khối 256 byte,
đúng định dạng board phát được) + `<out>/manifest.json`:
    {"cue_version": N, "clips": {id: {"file", "bytes", "seconds", "text", "sha256"}}}

Cue có lời đọc bằng đúng TTS đang chạy (chạy trên GPU, xem `config.TTS_DEVICE`); cue
không lời (`text is None`) sinh bằng numpy: bíp sin 1 kHz 80 ms, 3 bíp nhanh 3x60 ms,
âm liên tục 600 ms, "tách" nhiễu 30 ms, "tíc" 2 kHz 25 ms. Có fade 3 ms hai đầu để loa
không bị bụp.

Đổi chữ cue -> tăng `CUE_VERSION` rồi chạy lại, nạp lại flash.
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import adpcm, cues  # noqa: E402

SR = adpcm.SAMPLE_RATE
_FADE = int(0.003 * SR)
_PEAK = 0.6  # chừa headroom: ADPCM nén có thể vượt đỉnh một chút


def _tone(freq: float, ms: int) -> np.ndarray:
    t = np.arange(int(SR * ms / 1000)) / SR
    return np.sin(2 * np.pi * freq * t)


def _gap(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000))


def _fade(x: np.ndarray) -> np.ndarray:
    x = x.copy()
    n = min(_FADE, len(x) // 2)
    ramp = np.linspace(0.0, 1.0, n)
    x[:n] *= ramp
    x[len(x) - n:] *= ramp[::-1]
    return x


def _tone_clip(freq: float, ms: int) -> np.ndarray:
    return _fade(_tone(freq, ms))


def _click() -> np.ndarray:
    """"Tách" màn trập: nhiễu trắng 30 ms tắt dần theo hàm mũ."""
    rng = np.random.default_rng(7)  # cố định seed để sinh lại ra đúng file cũ
    n = int(SR * 0.030)
    return rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / (SR * 0.008))




def _synth(cue_id: str) -> np.ndarray:
    if cue_id == "received":
        return _tone_clip(2000, 25)
    if cue_id == "hazard_1":
        return _tone_clip(1000, 80)
    if cue_id == "hazard_2":
        beep = _tone_clip(1000, 60)
        return np.concatenate([beep, _gap(40), beep, _gap(40), beep])
    if cue_id == "hazard_3":
        return _tone_clip(1000, 600)
    if cue_id == "shutter":
        return _click()
    raise SystemExit(f"cue không lời '{cue_id}' chưa có bộ sinh âm trong make_cue_clips.py")


def _speak(text: str) -> np.ndarray:
    from pipeline import tts

    pcm = b"".join(tts.synthesize_stream(text))
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    # Cắt lặng đầu/đuôi: clip nằm trong flash, mỗi 100 ms lặng là 100 ms người dùng chờ vô ích.
    loud = np.flatnonzero(np.abs(x) > 0.01)
    if loud.size:
        pad = int(0.02 * SR)
        x = x[max(0, loud[0] - pad): loud[-1] + pad]
    return x


def _to_wav(x: np.ndarray) -> tuple[bytes, float]:
    peak = float(np.max(np.abs(x))) or 1.0
    x = x * (_PEAK / peak) if peak > _PEAK or peak < 0.1 else x
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    blocks = adpcm.encode_blocks(pcm.tobytes())
    wav = adpcm.wav_header(len(blocks), SR, adpcm.BLOCK_ALIGN, sample_count=len(pcm)) + blocks
    return wav, len(pcm) / SR


def build(out_dir: str, only: list[str] | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    clips = {}
    for cue_id, text in cues.CUES.items():
        if only and cue_id not in only:
            continue
        wav, seconds = _to_wav(_speak(text) if text else _synth(cue_id))
        name = f"{cue_id}.wav"
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(wav)
        clips[cue_id] = {"file": name, "bytes": len(wav), "seconds": round(seconds, 3),
                         "text": text, "sha256": hashlib.sha256(wav).hexdigest()}
        print(f"{cue_id:24s} {seconds:5.2f}s {len(wav):7d} B  {text or '(âm thanh)'}")
    manifest = {"cue_version": cues.CUE_VERSION, "clips": clips}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="thư mục ra (vd. assets/cues)")
    ap.add_argument("--only", nargs="*", help="chỉ sinh các id này (thử nhanh)")
    args = ap.parse_args()
    manifest = build(args.out, args.only)
    total = sum(c["bytes"] for c in manifest["clips"].values())
    print(f"{len(manifest['clips'])} clip, {total} byte, cue_version={manifest['cue_version']}")


if __name__ == "__main__":
    main()
