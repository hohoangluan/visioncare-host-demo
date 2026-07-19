from dataclasses import dataclass


class Intent:
    # nhóm AI
    OCR = "ocr"
    TRANSLATE = "translate"
    FIND = "find"
    MONEY = "money"
    SPACE = "space"
    # nhóm tiện ích
    DATETIME = "datetime"
    CALL = "call"
    MESSAGE = "message"


@dataclass
class Result:
    speech: str                    # câu tiếng Việt -> TTS
    action: dict | None = None     # None = chỉ audio; có = đẩy FCM push
