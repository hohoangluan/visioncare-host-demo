# Dấu tiếng Việt, dùng để đoán một chuỗi có phải tiếng Việt không.
_VI_CHARS = "ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộ" \
            "ờớởỡợùúủũụừứửữựỳýỷỹỵ"


def has_vietnamese(text: str) -> bool:
    return any(c in _VI_CHARS for c in text.lower())


def extract_name(command_text: str, prefixes: list[str]) -> str:
    """Cắt tiền tố lệnh (nếu có) khỏi command_text, trả về phần còn lại.

    So khớp tiền tố không phân biệt hoa/thường, nhưng phần tên trả về
    giữ nguyên cách viết hoa gốc trong command_text (không lowercase).
    Danh sách `prefixes` phải được sắp xếp dài/cụ thể trước, ngắn sau,
    vì hàm trả về ngay khi gặp tiền tố khớp đầu tiên.
    """
    original = command_text.strip()
    lowered = original.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return original[len(prefix):].strip()
    return original
