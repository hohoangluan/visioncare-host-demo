import io
import os

import numpy as np

import config
from models import orientation

_ocr = None

# Paddle mặc định giữ trước ~92% VRAM cho riêng nó khi chạy GPU. Model OCR ở
# đây nhỏ (vài trăm MB), giới hạn lại để còn chỗ cho STT/TTS chạy chung trên
# GPU 4GB. Phải set trước khi `import paddle` (flag đọc lúc paddle khởi tạo).
os.environ.setdefault("FLAGS_fraction_of_gpu_memory_to_use", "0.25")


def _get_ocr():
    global _ocr
    if _ocr is None:
        import paddle
        from paddleocr import PaddleOCR

        device = "gpu:0" if paddle.device.is_compiled_with_cuda() else "cpu"

        # enable_mkldnn=False: PP-OCRv6 det model crashes on CPU oneDNN path
        # on this stack (paddlepaddle 3.3.1) with
        # "ConvertPirAttribute2RuntimeAttribute not support ...onednn...".
        _ocr = PaddleOCR(
            lang=config.OCR_LANG,
            device=device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            # Bỏ dòng chữ đọc không chắc (điểm tin cậy thấp) thay vì trả về
            # chữ đoán mò — mặc định của PaddleOCR là 0.0 (không lọc gì cả).
            text_rec_score_thresh=config.OCR_MIN_SCORE,
        )
    return _ocr


def _decode(image: bytes) -> np.ndarray:
    from PIL import Image

    img = Image.open(io.BytesIO(image)).convert("RGB")
    return np.array(img)[:, :, ::-1]  # RGB -> BGR, PaddleOCR expects BGR


def extract_text(image: bytes) -> str:
    """Chạy PaddleOCR trên ảnh, nối các dòng nhận diện được bằng '\\n'.

    Chỉnh hướng ảnh trước: model detect/nhận diện chữ của PaddleOCR giả định
    chữ nằm ngang, đúng chiều — ảnh chụp lệch/ngược làm sai lệch nhiều hơn
    nhận diện tiền qua VLM (VLM hiểu ảnh linh hoạt hơn OCR truyền thống).
    """
    image = orientation.correct(image)
    result = _get_ocr().predict(_decode(image))
    if not result:
        return ""
    texts = result[0]["rec_texts"]
    return "\n".join(texts)
