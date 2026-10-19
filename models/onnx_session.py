"""Session onnxruntime dùng chung: GPU (CUDA) trước, CPU dự phòng.

Cần `onnxruntime-gpu` (không cài song song gói `onnxruntime` CPU — hai gói cùng
tên module, gói nào cài sau thắng). Thiếu CUDA thì tự rơi về CPU và log ra.
"""

import logging

import config

logger = logging.getLogger("blind_assist")


_preloaded = False


def _preload() -> None:
    """Nạp sẵn thư viện CUDA/cuDNN từ gói pip `nvidia-*`.

    Không có bước này, CUDAExecutionProvider báo thiếu `libcublasLt.so.13` và
    onnxruntime LẶNG LẼ rơi về CPU — đo ra số CPU mà tưởng là GPU.
    """
    global _preloaded
    if not _preloaded:
        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()
        _preloaded = True


def providers(prefer_gpu: bool = True) -> list:
    import onnxruntime as ort

    if prefer_gpu and config.ONNX_DEVICE != "cpu":
        _preload()
    available = ort.get_available_providers()
    chosen: list = []
    if prefer_gpu and config.ONNX_DEVICE != "cpu" and "CUDAExecutionProvider" in available:
        chosen.append(("CUDAExecutionProvider", {
            "device_id": config.ONNX_GPU_ID,
            # Ảnh vào luôn cùng cỡ: dò thuật toán conv nhanh nhất một lần lúc warm-up.
            "cudnn_conv_algo_search": "EXHAUSTIVE",
            "do_copy_in_default_stream": True,
        }))
    elif prefer_gpu and config.ONNX_DEVICE == "cuda":
        logger.warning("ONNX_DEVICE=cuda nhưng onnxruntime không có CUDAExecutionProvider (%s)", available)
    chosen.append("CPUExecutionProvider")
    return chosen


def session(path: str, threads: int = 4, prefer_gpu: bool = True):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(path, opts, providers=providers(prefer_gpu))
    if prefer_gpu and config.ONNX_DEVICE == "cuda" and sess.get_providers()[0] != "CUDAExecutionProvider":
        raise RuntimeError(f"ONNX_DEVICE=cuda nhưng {path} chạy trên {sess.get_providers()[0]}")
    return sess
