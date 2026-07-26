import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "models", ".env"))


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Model download caches (HuggingFace/torch/PaddleX) mặc định nằm ở
# %USERPROFILE% (ổ C). Trỏ về đây (trong project, ổ D) để không ăn ổ C.
_CACHE_ROOT = get("MODEL_CACHE_DIR", os.path.join(os.path.dirname(__file__), "models", ".cache"))
os.environ.setdefault("HF_HOME", os.path.join(_CACHE_ROOT, "huggingface"))
os.environ.setdefault("TORCH_HOME", os.path.join(_CACHE_ROOT, "torch"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", os.path.join(_CACHE_ROOT, "paddlex"))

STORAGE_DIR = get("STORAGE_DIR", "./storage")
OCR_LANG = get("OCR_LANG", "vi")
# Dòng chữ PaddleOCR nhận diện với độ tin cậy dưới ngưỡng này bị loại bỏ,
# không đưa vào kết quả — tránh đọc nhầm chữ mờ/không rõ thành chữ khác.
OCR_MIN_SCORE = float(get("OCR_MIN_SCORE", "0.5"))
GEMINI_API_KEY = get("GEMINI_API_KEY", "")
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-2.5-flash")
STT_MODEL_DIR = get("STT_MODEL_DIR", "./models/stt")
TTS_VOICE = get("TTS_VOICE", "Ngọc Linh")
TTS_STYLE = get("TTS_STYLE", "tu_nhien")
