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
    "nghe qua tai nghe. GIỮ NGUYÊN, KHÔNG dịch nghĩa tên thương hiệu/tên "
    "riêng — đo thật (T15/H4, docs/tasks/measurements/H4.md) thấy Gemini dịch "
    "chữ \"PARADOX\" in trên áo thành \"Nghịch lý\", sai ý người chụp."
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


# ─── T15/H3 — hướng dẫn chụp lại, tăng dần theo attempt ────────────────────
#
# Ca thật (25.2, docs/tasks/T15-ocr-quality.md): người khiếm thị chụp lại
# đúng y tư thế cũ vì câu báo lỗi cũ (`_NO_TEXT_MESSAGE` ở
# `models/ocr/__init__.py`) không nói phải sửa cái gì. Ba câu dưới đây CỐ Ý
# khác nhau: lần chụp lại thứ hai không được cấp thêm thông tin gì nếu chỉ
# lặp lại đúng câu lần một.
#
# Thứ tự nhắm đúng ba lỗi khung hình thật của ca 25.2, theo đúng mức độ hay
# gặp: (1) chữ quá nhỏ trong khung — lỗi giết chết theo H0/25.2 — sửa trước;
# (2) góc chụp chếch/perspective; (3) mặt phẳng + ánh sáng.
_GUIDANCE_ATTEMPT_1 = (
    "Không thấy rõ chữ. Đưa kính lại gần trang giấy hơn, cách khoảng một "
    "gang tay."
)
_GUIDANCE_ATTEMPT_2 = (
    "Vẫn chưa đọc được. Hướng kính thẳng xuống trang giấy, đừng chụp chếch "
    "từ bên cạnh."
)
_GUIDANCE_ATTEMPT_3 = (
    "Chưa đọc được. Thử đặt trang giấy lên mặt phẳng, chỗ đủ sáng."
)

GUIDANCE_BY_ATTEMPT: tuple[str, ...] = (
    _GUIDANCE_ATTEMPT_1, _GUIDANCE_ATTEMPT_2, _GUIDANCE_ATTEMPT_3,
)

# Để `pipeline/phrases.py` dựng sẵn audio cho cả ba câu (T06/G5) — xem
# `_speech_modules()` ở đó. KHÔNG tổng hợp lúc chạy: đúng những câu sinh ra để
# lấp quãng chờ (người dùng vừa chụp hỏng, đang sốt ruột) mà lại đi tổng hợp
# TTS trực tiếp thì tự tạo thêm quãng chờ, giống lý do `phrases.py` tồn tại.
STATIC_SPEECH: tuple[str, ...] = GUIDANCE_BY_ATTEMPT


def guidance_for_attempt(attempt: int) -> str:
    """Câu hướng dẫn chụp lại theo SỐ LẦN ĐÃ HỎI, 1-indexed (`attempt=1` ứng
    với lần đọc hỏng ĐẦU TIÊN — câu 1; `attempt=2` — câu 2; `attempt=3` trở
    lên — câu 3, không lặp lại câu 1).

    Nhận thẳng `pending.attempt` (T03/21.2, `handlers/action_flow.py`) từ
    caller — hàm này KHÔNG giữ bộ đếm riêng, gọi hai lần cùng `attempt` phải
    ra cùng một câu (stateless), để không lệch với bộ đếm thật của pending khi
    có lượt gọi xen giữa (ví dụ do log/telemetry).

    🔴 Việc TĂNG `pending.attempt` mỗi lần OCR ra `KHONG_CO_CHU` và gọi hàm
    này với giá trị đó thuộc `models/ocr/__init__.py` / `handlers/ocr.py` —
    hai file ngoài bảng "FILE BẠN ĐƯỢC SỬA" của agent T15 (xem
    docs/tasks/reports/T15.md mục "Lệch với task file"). Hàm này là khối xây
    sẵn sàng, CHƯA được nối dây vào production.
    """
    index = min(max(attempt, 1), len(GUIDANCE_BY_ATTEMPT)) - 1
    return GUIDANCE_BY_ATTEMPT[index]
