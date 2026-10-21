import sys, os, json, random, re, wave, collections
sys.path.insert(0, ".")
import numpy as np
from pipeline import stt, vad
BENCH = "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/stt-bench-cache"
rows = [json.loads(l) for i in range(3) for l in open(f"{BENCH}/manifest_cmd.{i}.jsonl")]
random.seed(1)
rows = [r for r in rows if r["cond"] == "clean" and r["wav"].endswith("_v0_clean.wav")]
random.shuffle(rows); rows = rows[:int(sys.argv[1])]
def load(p):
    w = wave.open(p); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    assert w.getframerate() == 16000, w.getframerate()
    return a
def norm(t): return re.sub(r"[^\w\s]", " ", t.lower()).split()
def pipe(a, lead):
    x = np.concatenate([np.zeros(int(lead * 16000), np.float32), a, np.zeros(int(1.0 * 16000), np.float32)])
    seg = vad.Segmenter()
    for i in range(0, len(x), 1600): seg.feed(x[i:i+1600])
    sp = seg.span()
    if sp is None: return "", None
    onset = np.argmax(np.abs(x) > 0.02) / 16000
    return stt._normalize(stt.decode_samples(x[sp[0]:sp[1]])), (sp[0] / 16000 - onset)
res = collections.defaultdict(lambda: [0, 0, 0])  # ok, firstword_wrong, n
shifts = []
for r in rows:
    a = load(f"{BENCH}/{r['wav']}")
    ref = norm(r["text"])
    outs = {}
    x = np.concatenate([np.zeros(int(0.3*16000), np.float32), a, np.zeros(int(0.5*16000), np.float32)])
    outs["model_nguyen_clip"] = stt._normalize(stt.decode_samples(x))
    for lead in (0.2, 0.6, 1.0):
        t, sh = pipe(a, lead); outs[f"vad_lead{lead}"] = t
        if lead == 0.2 and sh is not None: shifts.append(sh)
    for k, t in outs.items():
        h = norm(t); res[k][2] += 1
        if h == ref: res[k][0] += 1
        elif h[1:] == ref[1:] or (h and ref and h[0] != ref[0] and h[1:] == ref[1:]): res[k][1] += 1
        elif len(h) == len(ref) - 1 and h == ref[1:]: res[k][1] += 1
for k, (ok, fw, n) in res.items(): print(f"{k:20s} khớp đúng {ok}/{n} = {100*ok/n:.1f}%   (trong số sai: lỗi chỉ ở từ đầu {fw})")
print("VAD cắt đầu đoạn so với điểm bắt đầu tiếng thật (giây; âm = cắt vào tiếng nói) lead0.2: trung vị %.3f  p10 %.3f  min %.3f" % (np.median(shifts), np.percentile(shifts, 10), min(shifts)))
print("số câu VAD cắt vào tiếng nói >30ms:", sum(s > 0.03 for s in shifts), "/", len(shifts))
