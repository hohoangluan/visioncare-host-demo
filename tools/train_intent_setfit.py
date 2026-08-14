"""Huấn luyện bộ phân loại ý định bằng SetFit, rồi export sang ONNX int8.

Chạy:
    python tools/train_intent_setfit.py
    python tools/train_intent_setfit.py --epochs 2 --batch-size 32

Khác với `export_embedding_onnx.py` (chỉ export model GỐC): SetFit fine-tune
chính thân encoder bằng contrastive learning trước, nên trọng số đổi và bản
ONNX phải dựng lại TỪ model đã fine-tune. Chạy script này là chạy cả hai bước.

Đầu ra `models/intent_encoder/`:
    model_quantized.onnx   thân encoder đã fine-tune, int8
    tokenizer.json ...     tokenizer đi kèm
    head.npz               trọng số logistic regression + danh sách nhãn
    meta.json              số đo lúc huấn luyện, để biết bản đang chạy là bản nào

Script này chỉ chạy lúc chuẩn bị model. Server lúc chạy thật chỉ cần
`onnxruntime` + `tokenizers`, không cần `torch`/`setfit`.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

# Bước lượng tử hoá của onnxruntime ghi cả model fp32 (~1.1GB) kèm external data
# ra thư mục tạm của hệ thống, mặc định nằm trên ổ C. Máy này ổ C còn 7GB nên nó
# chết giữa chừng với `OSError: [Errno 28] No space left on device`, trong khi ổ
# D còn 67GB. Trỏ về D theo đúng nếp `config.py` đã làm với HF_HOME/TORCH_HOME.
_TMP = PROJ / "models" / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
for _var in ("TMPDIR", "TEMP", "TMP"):
    os.environ[_var] = str(_TMP)
tempfile.tempdir = str(_TMP)

MODEL_ID = "hiieu/halong_embedding"
DATA_DIR = PROJ / "data" / "intent"
OUT_DIR = PROJ / "models" / "intent_encoder"


def _load(split: str) -> tuple[list[str], list[str]]:
    rows = [json.loads(line) for line in (DATA_DIR / f"{split}.jsonl").open(encoding="utf-8")]
    return [r["text"] for r in rows], [r["label"] for r in rows]


def train(args) -> tuple[object, list[str], dict]:
    import torch
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    Xtr, ytr = _load("train")
    Xev, yev = _load("eval")
    labels = sorted(set(ytr) | set(yev))
    print(f"train {len(Xtr)} câu · eval {len(Xev)} câu · {len(labels)} nhãn", flush=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)

    model = SetFitModel.from_pretrained(MODEL_ID, labels=labels)
    targs = TrainingArguments(
        batch_size=args.batch_size,
        num_epochs=args.epochs,
        # `num_iterations` quyết định số CẶP contrastive sinh ra từ mỗi câu.
        # Đây là nút chính của SetFit: dữ liệu ít thì tăng số cặp bù lại, nhưng
        # tăng quá thì cặp lặp và chỉ tốn thời gian.
        num_iterations=args.pairs,
        seed=args.seed,
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=Dataset.from_dict({"text": Xtr, "label": ytr}),
        eval_dataset=Dataset.from_dict({"text": Xev, "label": yev}),
    )
    t0 = time.perf_counter()
    trainer.train()
    train_seconds = time.perf_counter() - t0

    metrics = trainer.evaluate()
    acc = float(metrics.get("accuracy", 0.0))
    print(f"\nSetFit (torch, {device}): acc {acc * 100:.1f}%  — huấn luyện {train_seconds:.0f}s")
    return model, labels, {"setfit_torch_acc": acc, "train_seconds": train_seconds,
                           "device": device, "n_train": len(Xtr), "n_eval": len(Xev)}


def _find_hf_dir(body_dir: Path) -> Path:
    """Thư mục HF transformer thật bên trong bản `SentenceTransformer.save()`.

    Bản mới của sentence-transformers đặt transformer ngay ở GỐC (config.json +
    model.safetensors), còn `1_Pooling/` và `2_Normalize/` là module phụ và cũng
    có `config.json` riêng. Lần chạy trước tôi quét thư mục con rồi lấy cái đầu
    tiên có `config.json`, nên trúng `1_Pooling` và ONNX export chết vì trong đó
    không có `model_type`. Điều kiện phải là "có config.json VÀ có file trọng
    số", không phải chỉ có config.json.
    """
    def looks_like_model(p: Path) -> bool:
        return (p / "config.json").exists() and any(
            (p / w).exists() for w in ("model.safetensors", "pytorch_model.bin")
        )

    if looks_like_model(body_dir):
        return body_dir
    for child in sorted(body_dir.iterdir()):
        if child.is_dir() and looks_like_model(child):
            return child
    raise SystemExit(f"Không tìm thấy thư mục model HF trong {body_dir}")


def refit_head(body_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Dựng lại head logreg từ thân đã fine-tune.

    SetFit fit head bằng sklearn LogisticRegression trên embedding của tập
    train, nên dựng lại từ cùng thân + cùng dữ liệu cho ra đúng thứ đó — rẻ hơn
    nhiều so với train lại 28 phút chỉ vì head nằm trong RAM của process đã chết.
    """
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression

    # Nạp thư mục SentenceTransformer (`_body/`), không phải thư mục con HF:
    # phải đi qua đúng cả pooling lẫn normalize thì embedding mới khớp với thứ
    # `check()` tính lại từ ONNX.
    st = SentenceTransformer(str(body_dir))
    Xtr, ytr = _load("train")
    Xev, yev = _load("eval")
    Etr = st.encode(Xtr, normalize_embeddings=True, show_progress_bar=False)
    Eev = st.encode(Xev, normalize_embeddings=True, show_progress_bar=False)
    clf = LogisticRegression(max_iter=2000).fit(Etr, ytr)
    acc = float((clf.predict(Eev) == np.array(yev)).mean())
    print(f"  head dựng lại: acc {acc * 100:.1f}% (torch fp32)")
    return (np.asarray(clf.coef_, dtype=np.float32),
            np.asarray(clf.intercept_, dtype=np.float32),
            np.array([str(c) for c in clf.classes_]), acc)


def export(model, labels: list[str], meta: dict) -> None:
    """Tách SetFit thành 2 mảnh: thân -> ONNX int8, head -> npz.

    Không export cả cụm thành một đồ thị: head chỉ là một phép nhân ma trận
    768×16, nhét vào ONNX chẳng nhanh thêm mà lại khoá cứng ngưỡng vào model.
    Giữ rời thì đổi ngưỡng hoặc huấn luyện lại head không phải đụng tới file
    278MB.
    """
    from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    body_dir = OUT_DIR / "_body"
    fp32_dir = OUT_DIR / "_fp32"
    shutil.rmtree(fp32_dir, ignore_errors=True)

    if model is not None:
        shutil.rmtree(body_dir, ignore_errors=True)
        print("\n[1/3] Lưu thân encoder đã fine-tune", flush=True)
        model.model_body.save(str(body_dir))
    else:
        print("\n[1/3] Dùng lại thân đã lưu ở lần chạy trước", flush=True)

    hf_dir = _find_hf_dir(body_dir)

    print("[2/3] Export ONNX fp32", flush=True)
    ort_model = ORTModelForFeatureExtraction.from_pretrained(hf_dir, export=True)
    ort_model.save_pretrained(fp32_dir)

    print("[3/3] Lượng tử hoá int8", flush=True)
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    quantizer.quantize(
        save_dir=OUT_DIR,
        quantization_config=AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=True),
    )

    from transformers import AutoTokenizer
    AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(OUT_DIR)

    if model is not None:
        head = model.model_head  # sklearn LogisticRegression
        coef = np.asarray(head.coef_, dtype=np.float32)
        intercept = np.asarray(head.intercept_, dtype=np.float32)
        classes = np.array([str(c) for c in head.classes_])
    else:
        coef, intercept, classes, refit_acc = refit_head(body_dir)
        meta = {**meta, "head_refit_acc": refit_acc}

    np.savez(OUT_DIR / "head.npz", coef=coef, intercept=intercept, classes=classes)
    (OUT_DIR / "meta.json").write_text(
        json.dumps({"base_model": MODEL_ID, "labels": labels or list(classes), **meta},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Giữ `_body` lại: nó là 28 phút fine-tune, và export/lượng tử hoá là bước
    # dễ hỏng hơn nhiều. Xoá bằng tay khi đã chốt bản.
    shutil.rmtree(fp32_dir, ignore_errors=True)


def check() -> None:
    """Đo lại trên ĐÚNG đường chạy production: ONNX int8 + head rời.

    Con số của `trainer.evaluate()` là con số của torch fp32 — không phải thứ
    server sẽ chạy. Lượng tử hoá làm lệch embedding, nên phải đo lại ở đây.
    """
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(OUT_DIR)
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(OUT_DIR / "model_quantized.onnx"), so,
                                providers=["CPUExecutionProvider"])
    names = {i.name for i in sess.get_inputs()}
    h = np.load(OUT_DIR / "head.npz", allow_pickle=False)
    coef, intercept, classes = h["coef"], h["intercept"], h["classes"]

    def embed(text: str) -> np.ndarray:
        enc = tok(text, return_tensors="np")
        hidden = sess.run(None, {k: v for k, v in enc.items() if k in names})[0]
        m = enc["attention_mask"][..., None].astype("float32")
        v = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        return v[0] / np.linalg.norm(v[0])

    Xev, yev = _load("eval")
    E = np.stack([embed(t) for t in Xev])
    logits = E @ coef.T + intercept
    # softmax để có xác suất cho 2 ngưỡng
    e = np.exp(logits - logits.max(1, keepdims=True))
    prob = e / e.sum(1, keepdims=True)
    pred = classes[prob.argmax(1)]
    acc = (pred == np.array(yev)).mean()
    print(f"\nONNX int8 + head rời: acc {acc * 100:.1f}%")

    top = np.sort(prob, 1)
    print("2 ngưỡng (conf top1 / biên top1-top2):")
    for c, m in ((0.5, 0.15), (0.6, 0.25), (0.7, 0.35)):
        keep = (top[:, -1] >= c) & (top[:, -1] - top[:, -2] >= m)
        a = (pred[keep] == np.array(yev)[keep]).mean() * 100 if keep.sum() else 0.0
        print(f"  >={c:.1f} / >={m:.2f}: nhận {keep.mean() * 100:5.1f}%, đúng {a:5.1f}%")

    for _ in range(3):
        embed(Xev[0])
    t = time.perf_counter()
    n = 0
    while time.perf_counter() - t < 3.0:
        embed(Xev[n % len(Xev)])
        n += 1
    print(f"\ntốc độ: {(time.perf_counter() - t) / n * 1000:.1f}ms/câu (CPU, 2 luồng)")

    meta = json.loads((OUT_DIR / "meta.json").read_text(encoding="utf-8"))
    meta["onnx_int8_acc"] = float(acc)
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--pairs", type=int, default=20, help="num_iterations của SetFit")
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--skip-train", action="store_true", help="chỉ đo lại bản đã export")
    ap.add_argument("--from-body", action="store_true",
                    help="bỏ qua fine-tune, export lại từ `_body/` đã lưu")
    args = ap.parse_args()

    if args.from_body:
        export(None, [], {"resumed_from_body": True})
    elif not args.skip_train:
        model, labels, meta = train(args)
        export(model, labels, meta)
    check()
    print(f"\n-> {OUT_DIR}")
    for p in sorted(OUT_DIR.iterdir()):
        if p.is_file():
            print(f"   {p.name:24s} {p.stat().st_size / 1e6:7.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
