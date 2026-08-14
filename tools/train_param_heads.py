"""Huấn luyện các head tham số trên CÙNG encoder đã fine-tune.

Chạy:
    python tools/train_param_heads.py
    python tools/train_param_heads.py --only chat_location

Rẻ đến mức gần như miễn phí lúc chạy thật: head chỉ là một phép nhân ma trận
768×2 trên embedding mà bước phân loại nhãn ĐÃ tính rồi. Một forward pass của
encoder nuôi cả nhãn lẫn tham số.

Cũng rẻ lúc huấn luyện: nạp thẳng `model_quantized.onnx` nên không cần `torch`,
`setfit` hay `optimum` — khác `train_intent_setfit.py`.

Đầu ra: `models/intent_encoder/heads_params.npz`.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

DATA_DIR = PROJ / "data" / "intent"
OUT_DIR = PROJ / "models" / "intent_encoder"
TASKS = ("chat_location", "chat_web", "volume_direction", "ride_confirm")


def _train_intent_head(embed, args) -> dict:
    """Head nhãn chính, huấn luyện trên cùng encoder với các head tham số.

    VÌ SAO KHÔNG FINE-TUNE (SetFit) NỮA — đo trên cùng bộ eval 236 câu:

        intent            gốc 94.1%  |  fine-tune 94.5%   (+0.4 = 1 câu)
        volume_direction  gốc  100%  |  fine-tune  40.0%  (-60)
        chat_web          gốc 90.0%  |  fine-tune  80.0%  (-10)
        ride_confirm      gốc 93.3%  |  fine-tune  83.3%  (-10)

    Contrastive fine-tune kéo mọi câu CÙNG một nhãn lại gần nhau — đúng thứ ta
    muốn cho bước chọn nhãn, và đúng thứ phá bước đọc tham số, vì "tăng âm
    lượng" với "giảm âm lượng" cùng nhãn `music_volume`. 40% là dưới mức đoán
    bừa: embedding không chỉ mất thông tin mà còn bị kéo ngược.

    Bỏ fine-tune đổi lấy 1 câu intent, nhưng được cả 4 head tham số, một encoder
    dùng chung (một forward pass nuôi 5 head) và khỏi 28 phút GPU mỗi lần dựng.
    """
    from sklearn.linear_model import LogisticRegression

    def load(split):
        rows = [json.loads(line) for line in (DATA_DIR / f"{split}.jsonl").open(encoding="utf-8")]
        return [r["text"] for r in rows], np.array([r["label"] for r in rows])

    Xtr_t, ytr = load("train")
    Xev_t, yev = load("eval")
    Xtr, Xev = embed(Xtr_t), embed(Xev_t)
    clf = LogisticRegression(max_iter=2000, C=10).fit(Xtr, ytr)

    prob = clf.predict_proba(Xev)
    pred = clf.classes_[prob.argmax(1)]
    acc = float((pred == yev).mean())
    top = np.sort(prob, 1)
    keep = (top[:, -1] >= 0.5) & (top[:, -1] - top[:, -2] >= 0.15)
    kept_acc = float((pred[keep] == yev[keep]).mean()) if keep.sum() else 0.0
    print(f"{'intent':18s} n={len(ytr) + len(yev):3d}  acc {acc * 100:5.1f}%  "
          f"| conf>=0.50 biên>=0.15: nhận {keep.mean() * 100:5.1f}% đúng {kept_acc * 100:5.1f}%")

    np.savez(
        OUT_DIR / "head.npz",
        coef=np.asarray(clf.coef_, dtype=np.float32),
        intercept=np.asarray(clf.intercept_, dtype=np.float32),
        classes=np.array([str(c) for c in clf.classes_]),
    )
    return {"n": len(ytr) + len(yev), "acc": acc,
            "coverage_at_05_015": float(keep.mean()), "acc_at_05_015": kept_acc}


def _encoder():
    import onnxruntime as ort
    from transformers import AutoTokenizer

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(OUT_DIR / "model_quantized.onnx"), opts, providers=["CPUExecutionProvider"]
    )
    tok = AutoTokenizer.from_pretrained(OUT_DIR)
    names = {i.name for i in session.get_inputs()}

    def embed(texts: list[str]) -> np.ndarray:
        out = []
        for text in texts:
            enc = tok(text, return_tensors="np", truncation=True, max_length=128)
            hidden = session.run(None, {k: v for k, v in enc.items() if k in names})[0]
            mask = enc["attention_mask"][..., None].astype("float32")
            vec = (hidden * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
            out.append(vec[0] / np.linalg.norm(vec[0]))
        return np.stack(out)

    return embed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--eval-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=20260812)
    args = ap.parse_args()

    from sklearn.linear_model import LogisticRegression

    targets = [t for t in args.only.split(",") if t] or list(TASKS)
    embed = _encoder()
    bundle: dict[str, np.ndarray] = {}
    report = {}

    intent_report = None
    if not args.only:
        intent_report = _train_intent_head(embed, args)

    for task in targets:
        path = DATA_DIR / f"params_{task}.jsonl"
        if not path.exists():
            print(f"[{task}] thiếu {path} — bỏ qua", file=sys.stderr)
            continue
        rows = [json.loads(line) for line in path.open(encoding="utf-8")]
        rng = np.random.default_rng(args.seed)
        idx = rng.permutation(len(rows))
        cut = int(len(rows) * args.eval_frac)
        ev, tr = idx[:cut], idx[cut:]

        t0 = time.perf_counter()
        X = embed([r["text"] for r in rows])
        y = np.array([r["label"] for r in rows])
        clf = LogisticRegression(max_iter=2000).fit(X[tr], y[tr])

        prob = clf.predict_proba(X[ev])
        pred = clf.classes_[prob.argmax(1)]
        acc = (pred == y[ev]).mean()
        top = np.sort(prob, 1)
        # Cùng cách gác như head nhãn: chắc mới nhận, không thì để Gemini đọc.
        keep = top[:, -1] >= 0.80
        cov = keep.mean()
        kept_acc = (pred[keep] == y[ev][keep]).mean() if keep.sum() else 0.0
        print(f"{task:18s} n={len(rows):3d}  acc {acc * 100:5.1f}%  "
              f"| conf>=0.80: nhận {cov * 100:5.1f}% đúng {kept_acc * 100:5.1f}%  "
              f"({time.perf_counter() - t0:.0f}s)")

        bundle[f"{task}__coef"] = np.asarray(clf.coef_, dtype=np.float32)
        bundle[f"{task}__intercept"] = np.asarray(clf.intercept_, dtype=np.float32)
        bundle[f"{task}__classes"] = np.array([str(c) for c in clf.classes_])
        report[task] = {"n": len(rows), "acc": float(acc),
                        "coverage_at_080": float(cov), "acc_at_080": float(kept_acc)}

    if not bundle:
        print("Không head nào được huấn luyện.", file=sys.stderr)
        return 1

    np.savez(OUT_DIR / "heads_params.npz", **bundle)
    meta_path = OUT_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta = {"base_model": "hiieu/halong_embedding", "fine_tuned": False, **meta}
    if intent_report:
        meta["intent_head"] = intent_report
    meta["param_heads"] = report
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {OUT_DIR / 'heads_params.npz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
