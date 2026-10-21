import sys, json, random, re, wave, collections, unicodedata, difflib
sys.path.insert(0, ".")
import numpy as np
from pipeline import stt, vad
BENCH = "/workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/stt-bench-cache"
rows = [json.loads(l) for i in range(3) for l in open(f"{BENCH}/manifest_cmd.{i}.jsonl")]
random.seed(1)
rows = [r for r in rows if r["cond"] == "clean" and r["wav"].endswith("_v0_clean.wav")]
random.shuffle(rows); rows = rows[:150]
def load(p):
    w = wave.open(p); return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
def norm(t): return re.sub(r"[^\w\s]", " ", t.lower()).split()
def strip(w): return "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn").replace("đ", "d")
def run(a):
    x = np.concatenate([np.zeros(3200, np.float32), a, np.zeros(16000, np.float32)])
    seg = vad.Segmenter()
    for i in range(0, len(x), 1600): seg.feed(x[i:i+1600])
    sp = seg.span()
    return stt._normalize(stt.decode_samples(x[sp[0]:sp[1]])) if sp else ""
cnt = collections.Counter(); ex = collections.defaultdict(list); n_words = 0; wrong_words = 0; bylabel = collections.defaultdict(lambda: [0, 0])
for r in rows:
    ref, hyp = norm(r["text"]), norm(run(load(f"{BENCH}/{r['wav']}")))
    n_words += len(ref); bylabel[r["label"]][1] += 1
    if ref == hyp: bylabel[r["label"]][0] += 1; continue
    sm = difflib.SequenceMatcher(None, ref, hyp)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal": continue
        a, b = ref[i1:i2], hyp[j1:j2]; wrong_words += max(len(a), len(b))
        pos = "đầu câu" if i1 == 0 else "giữa/cuối"
        if tag == "delete": k = f"rớt từ ({pos})"
        elif tag == "insert": k = "thêm từ"
        elif [strip(w) for w in a] == [strip(w) for w in b]: k = "chỉ sai dấu/thanh"
        else: k = f"thay từ ({pos})"
        cnt[k] += 1; ex[k].append(f"{' '.join(a)} → {' '.join(b) or '∅'}")
print("\nTỉ lệ từ sai ~ %.1f%% (%d/%d từ)" % (100 * wrong_words / n_words, wrong_words, n_words))
for k, v in cnt.most_common(): print(f"{k:24s} {v:3d}   vd: {' | '.join(ex[k][:4])}")
print("\nđúng nguyên câu theo nhóm lệnh:")
for k, (o, n) in sorted(bylabel.items(), key=lambda kv: kv[1][0] / kv[1][1]): print(f"  {k:15s} {o}/{n}")
