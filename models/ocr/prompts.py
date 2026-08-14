"""Prompt cho Gemini đọc chữ thẳng từ ảnh.

Trước đây bước đọc chữ do PaddleOCR chạy cục bộ đảm nhiệm, rồi mới đưa text
sang Gemini dịch — hai chặng, chặng đầu chạy CPU nên tốn hàng chục giây. Giờ
gộp thành một lượt gọi: Gemini vừa đọc vừa dịch, và tự xử lý được ảnh chụp
nghiêng/ngược nên không cần bước chỉnh hướng riêng.
"""
# Mốc quy ước cho trường hợp không có chữ. Không có nó thì mỗi lần Gemini chế
# một câu báo lỗi khác nhau, không tách được "ảnh không có chữ" khỏi nội dung
# đọc được thật.
NO_TEXT_SENTINEL = "KHONG_CO_CHU"

_COMMON = (
    "Bạn đang hỗ trợ người khiếm thị đọc chữ trong ảnh họ vừa chụp. Ảnh có thể "
    "bị nghiêng hoặc ngược chiều — tự xoay lại trong đầu rồi hãy đọc. "
    f"Nếu trong ảnh không có chữ nào đọc được (mờ, thiếu sáng, không có chữ), "
    f"chỉ trả về đúng một từ: {NO_TEXT_SENTINEL}\n"
    "Ngược lại, chỉ trả về nội dung cần đọc, không thêm lời giải thích, không "
    "mô tả bố cục hay màu sắc.\n\n"
)

_NORMAL = _COMMON + (
    "Đọc toàn bộ chữ trong ảnh rồi dịch sang tiếng Việt tự nhiên, ngắn gọn, dễ "
    "nghe qua tai nghe."
)

_SPECIALIZED = _COMMON + (
    "Đọc toàn bộ chữ trong ảnh rồi dịch sang tiếng Việt, nhưng GIỮ NGUYÊN "
    "(không dịch) các thuật ngữ chuyên ngành, tên riêng, mã số, đơn vị đo. "
    "Chỉ dịch phần văn bản thông thường xung quanh."
)

_RAW = _COMMON + (
    "Đọc nguyên văn toàn bộ chữ trong ảnh, giữ đúng ngôn ngữ gốc — KHÔNG DỊCH, "
    "không diễn giải lại."
)


def build(mode: str) -> str:
    from . import Mode

    if mode == Mode.SPECIALIZED:
        return _SPECIALIZED
    if mode == Mode.RAW:
        return _RAW
    return _NORMAL
