"""Export `hiieu/halong_embedding` sang ONNX rồi lượng tử hoá int8.

Chạy:
    python tools/export_embedding_onnx.py
    python tools/export_embedding_onnx.py --out models/intent_encoder --check

Vì sao phải qua ONNX thay vì dùng thẳng sentence-transformers:

1. `sentence-transformers` kéo theo `torch` (~2.5GB) — thứ vừa bị gỡ khỏi
   `requirements.txt` khi đổi STT sang sherpa-onnx. Thêm lại một model 278M
   tham số kèm cả runtime torch chỉ để phân loại 16 nhãn là không cân xứng.
2. `onnxruntime` đã có sẵn trong môi trường (vieneu dùng nó cho TTS).
3. int8 nhanh hơn fp32 rõ rệt trên CPU và nhẹ hơn ~4 lần trên đĩa.

Script này chỉ chạy MỘT LẦN lúc chuẩn bị model; server lúc chạy thật không cần
`torch` hay `optimum`.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

MODEL_ID = "hiieu/halong_embedding"
DEFAULT_OUT = PROJ / "models" / "intent_encoder"

# Câu dùng để đối chiếu fp32 với int8. Lấy đúng loại câu sẽ gặp lúc chạy thật,
# không lấy văn bản dài — sai số lượng tử hoá phụ thuộc phân phối đầu vào.
PROBES = [
    "Đọc chữ trong ảnh giúp tôi",
    "Tờ tiền này mệnh giá bao nhiêu",
    "Miêu tả không gian phía trước cho tôi",
    "Gọi điện cho mẹ",
    "Mở bài hát nơi này có anh",
    "Chỉ đường cho tôi tới chợ bến thành",
    "Phía trước có gì nguy hiểm không",
    "Hôm nay thời tiết thế nào bạn ơi",
    "Tắt nhạc đi",
    "Ờ à ừm",
]


def export(out_dir: Path) -> None:
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    fp32_dir = out_dir / "fp32"
    print(f"[1/3] Export {MODEL_ID} -> ONNX fp32", flush=True)
    model = ORTModelForFeatureExtraction.from_pretrained(MODEL_ID, export=True)
    model.save_pretrained(fp32_dir)
    AutoTokenizer.from_pretrained(MODEL_ID).save_pretrained(out_dir)


def quantize(out_dir: Path) -> None:
    from optimum.onnxruntime import ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    fp32_dir = out_dir / "fp32"
    print("[2/3] Lượng tử hoá int8 (dynamic, avx512_vnni)", flush=True)
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    # Dynamic quantization: không cần bộ dữ liệu hiệu chuẩn, và với encoder
    # transformer thì phần nặng là các phép nhân ma trận trong linear layer —
    # đúng thứ dynamic quant hạ xuống int8. `per_channel` giữ lại độ chính xác
    # ở lớp có phân phối trọng số lệch.
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=True)
    quantizer.quantize(save_dir=out_dir, quantization_config=qconfig)

    for name in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
        src = fp32_dir / name
        if src.exists() and not (out_dir / name).exists():
            shutil.copy2(src, out_dir / name)


def _mean_pool(last_hidden, mask):
    import numpy as np

    m = mask[..., None].astype("float32")
    return (last_hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)


def check(out_dir: Path) -> None:
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    onnx_files = sorted(out_dir.glob("*.onnx"))
    if not onnx_files:
        raise SystemExit(f"Không thấy file .onnx nào trong {out_dir}")
    int8_path = onnx_files[0]
    fp32_path = out_dir / "fp32" / "model.onnx"

    tok = AutoTokenizer.from_pretrained(out_dir)
    print(f"\n[3/3] Đối chiếu int8 với fp32 trên {len(PROBES)} câu", flush=True)

    def open_session(path: Path, threads: int = 2):
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])

    def embed(sess, texts: list[str]) -> np.ndarray:
        names = {i.name for i in sess.get_inputs()}
        out = []
        for t in texts:
            enc = tok(t, return_tensors="np")
            feed = {k: v for k, v in enc.items() if k in names}
            hidden = sess.run(None, feed)[0]
            v = _mean_pool(hidden, enc["attention_mask"])
            out.append(v[0] / np.linalg.norm(v[0]))
        return np.stack(out)

    sess32, sess8 = open_session(fp32_path), open_session(int8_path)
    a = embed(sess32, PROBES)
    b = embed(sess8, PROBES)
    cos = (a * b).sum(1)
    print(f"  cosine fp32 vs int8: min {cos.min():.4f}  trung bình {cos.mean():.4f}")

    # Điều thật sự quan trọng không phải vector giống nhau bao nhiêu, mà THỨ TỰ
    # gần-xa giữa các câu có giữ nguyên không — classifier chỉ đọc khoảng cách.
    sa, sb = a @ a.T, b @ b.T
    print(f"  lệch ma trận tương đồng: tối đa {np.abs(sa - sb).max():.4f}")
    same = (sa.argsort(1)[:, -2] == sb.argsort(1)[:, -2]).mean()
    print(f"  giữ nguyên 'câu gần nhất': {same * 100:.0f}%")

    # Đo phải TÁI SỬ DỤNG session: dựng `InferenceSession` cho model 278MB tốn
    # cả trăm ms, gộp vào thì con số đo được là chi phí khởi tạo chứ không phải
    # chi phí suy luận. Server chỉ dựng session một lần lúc khởi động.
    print()
    for sess, path, label in ((sess32, fp32_path, "fp32"), (sess8, int8_path, "int8")):
        t = time.perf_counter()
        n = 0
        while time.perf_counter() - t < 3.0:
            embed(sess, PROBES)
            n += len(PROBES)
        el = (time.perf_counter() - t) / n
        print(f"  {label}: {el * 1000:6.1f}ms/câu   {path.stat().st_size / 1e6:7.1f}MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="đối chiếu + đo tốc độ sau khi export")
    ap.add_argument("--keep-fp32", action="store_true", help="giữ lại bản fp32 (mặc định xoá)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    export(args.out)
    quantize(args.out)
    if args.check:
        check(args.out)
    if not args.keep_fp32:
        shutil.rmtree(args.out / "fp32", ignore_errors=True)
        print("\nĐã xoá bản fp32 (dùng --keep-fp32 để giữ).")

    print(f"\n-> {args.out}")
    for p in sorted(args.out.iterdir()):
        if p.is_file():
            print(f"   {p.name:32s} {p.stat().st_size / 1e6:7.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
