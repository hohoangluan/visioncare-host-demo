import string

from schemas import Intent

# Thứ tự quan trọng: kiểm tra cụm đặc trưng trước cụm chung.
# (dict giữ thứ tự chèn từ Python 3.7+)
_RULES = {
    Intent.MESSAGE: ["nhắn tin", "nhắn"],
    Intent.CALL: ["gọi cho", "gọi điện", "gọi"],
    Intent.DATETIME: ["mấy giờ", "ngày mấy", "thứ mấy", "ngày bao nhiêu", "hôm nay là ngày"],
    Intent.TRANSLATE: ["dịch"],
    Intent.MONEY: ["mệnh giá", "tờ tiền", "tiền"],
    Intent.OCR: ["đọc", "chữ"],
    Intent.FIND: ["tìm", "ở đâu", "đâu"],
}

_PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)


def detect(text: str) -> str:
    # Bỏ dấu câu rồi bọc khoảng trắng ở hai đầu để so khớp theo ranh giới từ:
    # " chữ " không khớp bên trong " chữa " (chữa bệnh, chữa cháy, ...).
    t = " " + text.lower().translate(_PUNCTUATION_TABLE) + " "
    for intent_name, keywords in _RULES.items():
        if any(f" {kw} " in t for kw in keywords):
            return intent_name
    return Intent.SPACE  # mặc định khi không khớp luật nào: miêu tả không gian
