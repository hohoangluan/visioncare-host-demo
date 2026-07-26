import string

from schemas import Intent

# Thứ tự quan trọng: kiểm tra cụm đặc trưng trước cụm chung.
# (dict giữ thứ tự chèn từ Python 3.7+)
_RULES = {
    Intent.MONEY: ["mệnh giá", "tiền"],
    Intent.OCR: ["đọc", "chữ"],
    Intent.FIND: [
        "tìm", "ở đâu", "đâu",
        "đi đến", "đi tới", "làm sao đến", "làm sao tới",
        "làm thế nào đến", "đường đến", "đường tới",
    ],
    Intent.SPACE: [
        "miêu tả", "mô tả", "không gian", "xung quanh",
        "phía trước", "trước mặt", "trước mắt",
    ],
}

_PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)


def detect(text: str) -> str:
    # Bỏ dấu câu rồi bọc khoảng trắng ở hai đầu để so khớp theo ranh giới từ:
    # " chữ " không khớp bên trong " chữa " (chữa bệnh, chữa cháy, ...).
    t = " " + text.lower().translate(_PUNCTUATION_TABLE) + " "
    for intent_name, keywords in _RULES.items():
        if any(f" {kw} " in t for kw in keywords):
            return intent_name
    # Không khớp luật nào: thà hỏi lại còn hơn đoán bừa qua VLM/OCR sai chỗ.
    return Intent.UNKNOWN
