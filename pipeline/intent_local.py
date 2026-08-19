"""Bộ phân loại ý định chạy cục bộ: SetFit đã fine-tune, ONNX int8, CPU.

Đứng TRƯỚC Gemini, không thay Gemini. Câu nào nó đủ chắc thì trả lời ngay trong
~8ms; câu nào không chắc thì trả `None` để `pipeline/intent.py` rơi xuống Gemini
như cũ. Đo trên tập eval 236 câu: ngưỡng mặc định nhận 93.2% số câu và đúng
96.4% trong phần nhận (xem `models/intent_encoder/meta.json`).

Model dựng bằng `tools/train_intent_setfit.py`. Ở đây chỉ cần `onnxruntime` +
`tokenizers`; không cần `torch`, `setfit` hay `optimum`.
"""
import json
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

import config

logger = logging.getLogger("blind_assist")

# `InferenceSession.run` an toàn với nhiều luồng, nhưng tokenizer của
# `transformers` thì không đảm bảo. Server chạy request trong threadpool nên
# khoá lại cho chắc — một lượt phân loại chỉ ~8ms, tranh khoá không đáng kể.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class LocalPrediction:
    label: str
    confidence: float   # xác suất của nhãn cao nhất
    margin: float       # cách biệt với nhãn nhì
    # Embedding của chính câu đó, giữ lại để các head tham số dùng LẠI thay vì
    # chạy encoder lần nữa. Đây là chỗ head tham số gần như miễn phí: forward
    # pass 8ms đã trả rồi, mỗi head thêm chỉ là một phép nhân 768×2.
    embedding: np.ndarray | None = None


# Nhãn nào đọc được tham số bằng head cục bộ, và head nào phục vụ nó.
#
# Chỉ có mặt những tham số là bài PHÂN LOẠI. `destination`, `contact_name`,
# `song`, `emergency_number` là TRÍCH SPAN — tên riêng, địa danh, tên bài hát —
# nên ở lại với Gemini. Đó cũng là chỗ đoán sai thì hậu quả thật: dẫn nhầm
# đường, gọi nhầm người.
# `chat` ĐÃ RỜI bảng này. Hai head `chat_location`/`chat_web` bị bỏ vì cả hai cờ
# chúng phục vụ đều không còn: vị trí do thread nền giữ nóng nên luôn nhét vào
# prompt, còn tra Google hay không thì model tự quyết lúc sinh chữ.
#
# Chúng cũng là hai head yếu nhất — nhận 20.0% và 3.3% ở ngưỡng 0.80 — và vì
# `read_params` bắt MỌI trường phải qua ngưỡng nên hai tỉ lệ đó NHÂN với nhau:
# đo trên 18 câu chat của tập eval, 0/18 câu xong được ở bước cục bộ. Bài học
# giữ lại: đừng bắt một nhãn phụ thuộc nhiều head độc lập cùng lúc.
_PARAM_HEADS: dict[str, dict[str, str]] = {
    "music_volume": {"direction": "volume_direction"},
    "ride_confirm": {"confirm": "ride_confirm"},
}

# Nhãn head là chuỗi; đổi về đúng kiểu mà `_SCHEMA` và handler mong đợi.
_CAST = {"true": True, "false": False}


def _probabilities(vec: np.ndarray, coef: np.ndarray, intercept: np.ndarray) -> np.ndarray:
    """Xác suất từng lớp, khớp đúng `LogisticRegression.predict_proba`.

    Phải tách hai trường hợp. Bài NHỊ PHÂN được sklearn lưu MỘT hàng hệ số duy
    nhất và dùng sigmoid cho lớp thứ hai, không phải hai hàng rồi softmax. Áp
    softmax lên vector một phần tử thì mọi câu đều ra xác suất 1.0 ở chỉ số 0,
    tức là luôn trả lớp đứng đầu bảng chữ cái — đo được đúng vậy: "tăng âm
    lượng" ra `down`, "xác nhận đặt xe" ra `confirm=False`. Head huấn luyện
    đúng 96.7%, chỉ phần đọc lại lúc chạy là sai.
    """
    logits = vec @ coef.T + intercept
    if coef.shape[0] == 1:
        p1 = 1.0 / (1.0 + np.exp(-logits[0]))
        return np.array([1.0 - p1, p1], dtype=np.float32)
    exp = np.exp(logits - logits.max())
    return exp / exp.sum()


def read_params(label: str, prediction: LocalPrediction | None) -> dict | None:
    """Tham số đọc được cục bộ cho `label`, hoặc `None` khi không đủ chắc.

    `None` nghĩa là "để Gemini đọc", không phải "không có tham số" — trả `{}`
    nhầm chỗ sẽ khiến handler tưởng người dùng không nói gì và hỏi lại một câu
    họ vừa trả lời.
    """
    wanted = _PARAM_HEADS.get(label)
    if wanted is None or prediction is None or prediction.embedding is None:
        return None
    loaded = _load()
    if loaded is None:
        return None

    out: dict = {}
    for field, task in wanted.items():
        head = loaded["param_heads"].get(task)
        if head is None:
            return None
        coef, intercept, classes = head
        prob = _probabilities(prediction.embedding, coef, intercept)
        best = int(prob.argmax())
        if float(prob[best]) < config.INTENT_LOCAL_PARAM_MIN_CONF:
            # Một trường không chắc là cả nhãn phải đi Gemini: trả nửa bộ tham
            # số còn tệ hơn không trả, vì handler không phân biệt được "không có
            # cờ này" với "cờ này là false".
            return None
        value = str(classes[best])
        out[field] = _CAST.get(value, value)
    return out


@lru_cache(maxsize=1)
def _load():
    """Nạp ONNX + tokenizer + head. Trả `None` khi chưa có model trên đĩa.

    Trả `None` chứ không raise: máy chưa chạy `train_intent_setfit.py` vẫn phải
    khởi động được server và đi đường Gemini, thay vì chết lúc import.
    """
    import onnxruntime as ort
    from transformers import AutoTokenizer

    model_dir = Path(config.INTENT_LOCAL_DIR)
    onnx_path = model_dir / "model_quantized.onnx"
    head_path = model_dir / "head.npz"
    if not onnx_path.exists() or not head_path.exists():
        logger.warning(
            "Chưa có model phân loại cục bộ ở %s — dùng Gemini cho mọi câu. "
            "Dựng bằng: python tools/train_intent_setfit.py",
            model_dir,
        )
        return None

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = config.INTENT_LOCAL_NUM_THREADS
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(onnx_path), opts, providers=["CPUExecutionProvider"]
    )
    head = np.load(head_path, allow_pickle=False)
    params_path = model_dir / "heads_params.npz"
    param_heads = {}
    if params_path.exists():
        raw = np.load(params_path, allow_pickle=False)
        for key in raw.files:
            if key.endswith("__coef"):
                task = key[: -len("__coef")]
                param_heads[task] = (
                    raw[f"{task}__coef"], raw[f"{task}__intercept"], raw[f"{task}__classes"]
                )
    meta_path = model_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        logger.info(
            "Phân loại cục bộ: %d nhãn, acc eval %.1f%%",
            len(head["classes"]), 100 * meta.get("onnx_int8_acc", 0.0),
        )
    return {
        "session": session,
        "inputs": {i.name for i in session.get_inputs()},
        "tokenizer": AutoTokenizer.from_pretrained(model_dir),
        "coef": head["coef"],
        "intercept": head["intercept"],
        "classes": head["classes"],
        "param_heads": param_heads,
    }


def available() -> bool:
    return config.INTENT_LOCAL_ENABLED and _load() is not None


def warm() -> None:
    """Nạp model và chạy thử một lần lúc khởi động.

    Lần chạy đầu của onnxruntime tốn thêm thời gian khởi tạo. Trả trước ở đây để
    request thật đầu tiên không gánh, giống cách `app.py` làm với STT/TTS.
    """
    if config.INTENT_LOCAL_ENABLED and _load() is not None:
        classify("khởi động")


def classify(text: str) -> LocalPrediction | None:
    """Nhãn cục bộ cho `text`, hoặc `None` khi không đủ chắc / không có model.

    `None` nghĩa là "không kết luận", không phải "vô nghĩa" — người gọi phải hỏi
    Gemini, chứ đừng đổi thành `unknown`.
    """
    if not config.INTENT_LOCAL_ENABLED:
        return None
    loaded = _load()
    if loaded is None or not text.strip():
        return None

    with _LOCK:
        enc = loaded["tokenizer"](text, return_tensors="np", truncation=True, max_length=128)
        feed = {k: v for k, v in enc.items() if k in loaded["inputs"]}
        hidden = loaded["session"].run(None, feed)[0]

    mask = enc["attention_mask"][..., None].astype("float32")
    pooled = (hidden * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
    vec = pooled[0] / np.linalg.norm(pooled[0])

    logits = vec @ loaded["coef"].T + loaded["intercept"]
    exp = np.exp(logits - logits.max())
    prob = exp / exp.sum()

    order = np.argsort(prob)
    confidence = float(prob[order[-1]])
    margin = float(confidence - prob[order[-2]])

    # HAI ngưỡng, không phải một. Xác suất cao vẫn có thể là "hai nhãn cùng cao"
    # — đúng tình huống `nav_stop` với `music_stop` tranh nhau. Biên hẹp nghĩa là
    # model đang lưỡng lự giữa hai lựa chọn, và đó là lúc phải hỏi Gemini chứ
    # không phải lúc lấy cái nhỉnh hơn.
    if confidence < config.INTENT_LOCAL_MIN_CONF:
        return None
    if margin < config.INTENT_LOCAL_MIN_MARGIN:
        return None
    return LocalPrediction(str(loaded["classes"][order[-1]]), confidence, margin, vec)
