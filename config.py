import os


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


STORAGE_DIR = get("STORAGE_DIR", "./storage")
OCR_MODEL_DIR = get("OCR_MODEL_DIR", "./models/ocr")
TRANSLATE_MODEL_DIR = get("TRANSLATE_MODEL_DIR", "./models/translate")
VISION_API_KEY = get("VISION_API_KEY", "")
