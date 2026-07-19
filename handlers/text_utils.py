# Dấu tiếng Việt, dùng để đoán một chuỗi có phải tiếng Việt không.
_VI_CHARS = "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộ" \
            "ờớởỡợùúủũụừứửữựỳýỷỹỵ"


def has_vietnamese(text: str) -> bool:
    return any(c in _VI_CHARS for c in text.lower())
