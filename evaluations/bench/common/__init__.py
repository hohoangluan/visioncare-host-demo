"""Khung chung cho mọi bàn đo (spec mục 7): đường dẫn, chọn GPU, metadata, CI bootstrap, độ trễ, ghi kết quả.

Quy ước: import code thật của VH (đo đúng đường production), không viết lại thuật toán.
Gọi `setup()` ĐẦU TIÊN trong mỗi script (trước khi import onnxruntime/torch hay module VH).
"""

import datetime as _dt
import json
import os
import platform
import random
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import numpy as np

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATAS = os.path.join(EVAL_DIR, "datas")
RESULTS = os.path.join(EVAL_DIR, "results")
REPORTS = os.path.join(EVAL_DIR, "reports")
# evaluations/ nằm TRONG repo VH (bản commit) hoặc cạnh VH (SeeVia_system/evaluations, bản đang chạy pipeline)
_PARENT = os.path.dirname(EVAL_DIR)
VH_DIR = _PARENT if os.path.exists(os.path.join(_PARENT, "config.py")) else os.path.join(_PARENT, "visioncare-host-demo")
# Đo một nhánh VH khác (worktree) mà không đổi bản đang chạy: SEEVIA_VH_DIR=/đường/dẫn/worktree
VH_DIR = os.environ.get("SEEVIA_VH_DIR") or VH_DIR

_GPU_AT_START: list[dict] = []


def _gpus() -> list[dict]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.strip().splitlines():
        i, name, used, total, util = [x.strip() for x in line.split(",")]
        rows.append({"index": int(i), "name": name, "mem_used_mib": int(used),
                     "mem_total_mib": int(total), "util_pct": int(util)})
    return rows


def pick_gpu() -> str | None:
    """GPU trống nhất (ít util rồi nhiều VRAM trống) — memory: luôn GPU, GPU đầy thì đổi GPU, không lùi CPU.
    Tôn trọng CUDA_VISIBLE_DEVICES nếu người chạy đã đặt."""
    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        return os.environ["CUDA_VISIBLE_DEVICES"]
    gpus = _gpus()
    if not gpus:
        return None
    best = min(gpus, key=lambda g: (g["util_pct"] > 10, g["mem_used_mib"]))
    os.environ["CUDA_VISIBLE_DEVICES"] = str(best["index"])
    return str(best["index"])


def setup(gpu: bool = True) -> None:
    """Chọn GPU (trước khi nạp CUDA), thêm VH vào sys.path, cố định seed."""
    global _GPU_AT_START
    if gpu:
        pick_gpu()
    _GPU_AT_START = _gpus()
    if VH_DIR not in sys.path:
        sys.path.insert(0, VH_DIR)
    random.seed(0)
    np.random.seed(0)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", VH_DIR, *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_meta(config: dict) -> dict:
    """Metadata bắt buộc cho mỗi lần chạy (spec mục 7)."""
    vis = os.environ.get("CUDA_VISIBLE_DEVICES")
    gpu_now = _gpus()

    def mine(rows):
        return [g for g in rows if vis is not None and str(g["index"]) in vis.split(",")]

    return {
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "python": platform.python_version(),
        "argv": sys.argv,
        "vh_commit": _git("rev-parse", "--short", "HEAD"),
        "vh_branch": _git("branch", "--show-current"),
        "vh_dirty": bool(_git("status", "--porcelain")),
        "cuda_visible_devices": vis,
        "gpu_at_start": mine(_GPU_AT_START),
        "gpu_at_end": mine(gpu_now),
        "config": config,
    }


def bootstrap_ci(values, stat=np.mean, n: int = 1000, seed: int = 0, alpha: float = 0.05) -> tuple[float, float, float]:
    """(giá trị, CI thấp, CI cao) — bootstrap theo mẫu (ảnh/clip/câu). values: 1-D, hoặc 2-D (mẫu × cột) cho stat tự định nghĩa."""
    arr = np.asarray(values)
    if len(arr) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n, len(arr)))
    boots = np.array([stat(arr[i]) for i in idx])
    lo, hi = np.nanpercentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(stat(arr)), float(lo), float(hi)


def paired(a, b, n: int = 1000, seed: int = 0) -> dict:
    """So A/B ghép đôi trên CÙNG mẫu: Δ = mean(b) − mean(a), CI của Δ, số ca bất đồng (cho metric 0/1)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    assert a.shape == b.shape, "A/B phải trên cùng tập mẫu"
    d, lo, hi = bootstrap_ci(b - a, n=n, seed=seed)
    out = {"n": int(len(a)), "mean_a": float(a.mean()), "mean_b": float(b.mean()), "delta": d, "delta_ci": [lo, hi]}
    if set(np.unique(np.concatenate([a, b]))) <= {0.0, 1.0}:
        out["a_only"] = int(((a == 1) & (b == 0)).sum())
        out["b_only"] = int(((a == 0) & (b == 1)).sum())
    return out


def latency_summary(ms) -> dict:
    """p50/p90/p99 (ms) — dòng độ trễ bắt buộc của mọi bàn đo."""
    arr = np.asarray([x for x in ms if x is not None], dtype=float)
    if len(arr) == 0:
        return {"n": 0}
    p50, p90, p99 = np.percentile(arr, [50, 90, 99])
    return {"n": int(len(arr)), "p50_ms": round(float(p50), 2), "p90_ms": round(float(p90), 2),
            "p99_ms": round(float(p99), 2), "mean_ms": round(float(arr.mean()), 2), "max_ms": round(float(arr.max()), 2)}


@contextmanager
def timer(store: list, key: str | None = None):
    """with timer(lst): ... -> thêm ms vào lst (hoặc lst[key] nếu là dict)."""
    t = time.perf_counter()
    yield
    ms = (time.perf_counter() - t) * 1000
    if key is None:
        store.append(ms)
    else:
        store.setdefault(key, []).append(ms)


def write_result(task: str, cfg_name: str, payload: dict, out_dir: str | None = None) -> str:
    """results/<task>/<YYYYMMDD-HHMM>_<cfg>.json. payload nên có: meta, metrics, latency, per_sample (tuỳ)."""
    out_dir = out_dir or os.path.join(RESULTS, task)
    os.makedirs(out_dir, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    path = os.path.join(out_dir, f"{stamp}_{cfg_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=float)
        f.flush()
        os.fsync(f.fileno())  # NFS từng cắt file âm thầm (memory nfs_quota) — fsync để lỗi lộ ra
    return path


def sample(items: list, k: int | None, seed: int = 0) -> list:
    """Mẫu ngẫu nhiên cố định seed (spec 11.5: 300 mẫu/bộ cho task tốn LLM). k=None -> tất cả."""
    if k is None or k >= len(items):
        return list(items)
    return random.Random(seed).sample(list(items), k)
