from dataclasses import dataclass


class Intent:
    OCR = "ocr"
    TRANSLATE = "translate"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"


@dataclass
class Result:
    speech: str    # câu tiếng Việt -> TTS
