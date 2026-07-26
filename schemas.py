from dataclasses import dataclass


class Intent:
    OCR = "ocr"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"
    UNKNOWN = "unknown"  # không khớp luật nào -> hỏi lại thay vì đoán


@dataclass
class Result:
    speech: str    # câu tiếng Việt -> TTS
