from schemas import Intent

# Thứ tự quan trọng: kiểm tra cụm đặc trưng trước cụm chung.
# (dict giữ thứ tự chèn từ Python 3.7+)
_RULES = {
    Intent.MESSAGE: ["nhắn tin", "nhắn"],
    Intent.CALL: ["gọi cho", "gọi điện", "gọi"],
    Intent.DATETIME: ["mấy giờ", "ngày mấy", "hôm nay", "bây giờ"],
    Intent.TRANSLATE: ["dịch"],
    Intent.MONEY: ["mệnh giá", "tờ tiền", "tiền"],
    Intent.OCR: ["đọc", "chữ"],
    Intent.FIND: ["tìm", "ở đâu", "đâu"],
    Intent.SPACE: ["xung quanh", "trước mặt", "không gian", "miêu tả"],
}


def detect(text: str) -> str:
    t = text.lower()
    for intent_name, keywords in _RULES.items():
        if any(kw in t for kw in keywords):
            return intent_name
    return Intent.SPACE  # mặc định: miêu tả không gian
