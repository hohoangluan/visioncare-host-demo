"""Cổng lọc ảnh đầu vào, chạy SAU khi đã biết intent.

Phải biết người dùng hỏi gì rồi mới quyết định được ảnh có đạt hay không: cùng
một tấm ảnh là vô dụng với "đọc chữ giùm tôi" nhưng hoàn toàn không liên quan
tới "gọi cho mẹ". Chặn trước khi biết intent thì `chat` và 9 action điều khiển
điện thoại — vốn không hề đọc ảnh — vẫn bị một tấm ảnh xấu chặn đứng.

Camera thật hiện dùng 1280×720, JPEG quality 18 (thang esp32-camera 0–63, số
nhỏ = nét hơn — CONTRACTS.md mục 1 #6), KHÔNG PHẢI 1600x1200 như tài liệu cũ
từng ghi. Bộ số min=0.70 median=19.38 max=108.94 ở dưới đây đo trên 83 request
"1600x1200" cũ — mô tả một cấu hình không còn tồn tại, xem
`docs/tasks/measurements/H0-blur-720p.md` cho số đo lại trên 1280×720 (số đó
là ĐỀ XUẤT, chưa áp vào `config.IMAGE_MIN_SHARPNESS` bên dưới). Không có ngưỡng
nào tách được "ảnh mờ" khỏi "ảnh bình thường của máy này" mà không loại nhầm
phần lớn request hợp lệ — nên ngưỡng ở đây chỉ bắt outlier cực đoan, KHÔNG đảm
bảo ảnh đủ nét để đọc đúng mọi chi tiết.

Tính ở nguyên độ phân giải gốc, không resize: đo thử cho thấy resize (kể cả
Lanczos chất lượng cao) tự làm mượt đúng phần nhiễu tần số cao mà Laplacian
variance cần đo, khiến ảnh mờ thật (7.25 ở gốc) trông như bình thường (200 sau
khi resize về 640) — resize sai một bước là mất tín hiệu.

Cũng không dùng `PIL.ImageFilter.Kernel`: bộ lọc đó chạy trên ảnh 8-bit và tự
clamp giá trị trung gian về [0, 255], làm variance đo được sai lệch cả chục
lần so với convolution float64 thật (đo thử: 79.45 vs 7.25 trên cùng ảnh).
"""
import io
import logging

import numpy as np
from PIL import Image

import config
from schemas import Intent

logger = logging.getLogger("blind_assist")

_TOO_DARK = "Ảnh quá tối, vui lòng ra chỗ đủ sáng và chụp lại."
_TOO_BRIGHT = "Ảnh quá sáng, tránh để đèn chiếu thẳng vào ống kính rồi chụp lại."
_TOO_BLURRY = "Ảnh không rõ, vui lòng đưa máy lại gần rồi chụp lại."
_NO_IMAGE = "Không nhận được ảnh từ kính, vui lòng thử lại."

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (_TOO_DARK, _TOO_BRIGHT, _TOO_BLURRY, _NO_IMAGE)

# Intent thật sự đọc ảnh. Các intent còn lại (`chat` và 9 action điều khiển điện
# thoại) vẫn nhận tham số `image` nhưng bỏ qua nó, nên chất lượng ảnh không đổi
# được một chữ nào trong câu trả lời — chặn chúng chỉ là từ chối oan.
#
# 🔴 `Intent.HAZARD` đã QUAY LẠI danh sách này (2026-08-26) cùng lúc với
# `router._IMAGE_REQUIRED_INTENTS`. Nó lại là một câu hỏi về một khung hình,
# trả lời qua LLM (`handlers/describe_hazard.py`) — nên nó lại đọc ảnh.
#
# Hai danh sách này là HAI nơi khác nhau và đã lệch nhau đúng một lần: gỡ ở
# router xong, cổng này vẫn chặn, và lượt thật trên board trả về *"Không nhận
# được ảnh từ kính"* thay vì chạy. Đổi một cái thì PHẢI đổi cái kia —
# `tests/test_pipeline_e2e.py` có assert riêng cho việc hai danh sách khớp.
_READS_IMAGE = frozenset({
    Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD,
})

# Chỉ `money` mới chặn thêm theo độ nét, và đây là ngưỡng phòng xa chứ không
# phải ngưỡng đo được: chưa có ca nào chứng minh ảnh mờ khiến đọc sai mệnh giá.
# Giữ lại vì đây là intent duy nhất mà câu trả lời sai đắt hơn hẳn câu "chụp
# lại" — đọc nhầm 500 nghìn thành 20 nghìn là mất tiền thật.
#
# Các intent khác cố ý KHÔNG chặn theo độ nét, vì có bằng chứng ngược: ảnh bức
# tường trắng (request410, sharpness 0.92) bị cổng này từ chối bằng câu "giữ
# chắc tay" — chẩn đoán sai, ảnh nét bình thường, chỉ là chủ thể phẳng. Thả cho
# đi tiếp thì cả ba handler trả lời đúng và có ích hơn hẳn:
#   space -> "một bề mặt phẳng, có thể là bức tường trắng hoặc cánh cửa trơn màu"
#   ocr   -> "Không thấy rõ chữ trong ảnh, vui lòng chụp lại."
#   find  -> "Tôi không thấy rõ cái ly, vui lòng chụp lại gần hơn."
_NEEDS_SHARPNESS = frozenset({Intent.MONEY})


def _sharpness(arr: np.ndarray) -> float:
    """Phương sai Laplacian 3x3, convolution float64 thủ công (xem lý do ở docstring module)."""
    lap = (
        arr[:-2, 1:-1] + arr[2:, 1:-1] + arr[1:-1, :-2] + arr[1:-1, 2:]
        - 4 * arr[1:-1, 1:-1]
    )
    return float(lap.var())


def measure(image_bytes: bytes) -> tuple[float, float] | None:
    """(sharpness, brightness) đo ở độ phân giải gốc, hoặc None nếu không decode được.

    Không phải việc của gate này validate định dạng ảnh — bytes hỏng/không phải
    ảnh thì bỏ qua, để nguyên luồng cũ xử lý (đã vậy từ trước gate này tồn tại).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:  # noqa: BLE001 - bytes bất kỳ, không riêng lỗi PIL nào
        return None

    arr = np.asarray(img, dtype=np.float64)
    if arr.shape[0] < 3 or arr.shape[1] < 3:
        return None
    return _sharpness(arr), float(arr.mean())


def check(sharpness: float, brightness: float, need_sharpness: bool = True) -> str | None:
    """Câu từ chối (đọc được cho người khiếm thị) nếu ảnh là outlier cực đoan, None nếu đạt.

    `need_sharpness=False` bỏ qua riêng luật độ nét, cho các intent mà ảnh phẳng
    vẫn là một câu trả lời hợp lệ (xem `_NEEDS_SHARPNESS`).
    """
    if brightness < config.IMAGE_MIN_BRIGHTNESS:
        return _TOO_DARK
    if brightness > config.IMAGE_MAX_BRIGHTNESS:
        return _TOO_BRIGHT
    if need_sharpness and sharpness < config.IMAGE_MIN_SHARPNESS:
        return _TOO_BLURRY
    return None


def reject_reason(intent: str, image_bytes: bytes | None) -> str | None:
    """Câu từ chối ảnh cho `intent`, hoặc None nếu request được đi tiếp.

    Gọi sau khi đã có intent. Intent không đọc ảnh thì thoát ngay, không decode
    gì — vừa khỏi từ chối oan, vừa khỏi tốn CPU: decode ảnh rồi chạy Laplacian
    float64 tốn CPU cho mỗi request (≈0.1s đo trên 1600×1200 — cấu hình cũ,
    CHƯA đo lại trên 1280×720), kể cả request "gọi cho mẹ" không hề dùng tới
    ảnh.
    """
    if intent not in _READS_IMAGE:
        return None

    if not image_bytes:
        # Tới đây nghĩa là người dùng vừa hỏi một câu CẦN ảnh mà không có ảnh
        # nào. Nói thẳng thay vì để handler gửi ảnh rỗng cho Gemini và nhận về
        # một câu mô tả bịa.
        logger.info("intent=%s nhưng không có ảnh", intent)
        return _NO_IMAGE

    measured = measure(image_bytes)
    if measured is None:
        # Không decode được: để nguyên luồng cũ xử lý, không tự ý chặn.
        return None

    sharpness, brightness = measured
    reason = check(sharpness, brightness, need_sharpness=intent in _NEEDS_SHARPNESS)
    logger.info(
        "ảnh sharpness=%.2f brightness=%.1f intent=%s%s",
        sharpness, brightness, intent,
        f" -> từ chối: {reason}" if reason else "",
    )
    return reason


# ─── T15/H5 — đếm KHONG_CO_CHU, để có mốc "OCR hỏng bao nhiêu %" ───────────
#
# 25.5: trước task này KHONG_CO_CHU không được đếm ở đâu — không biết OCR
# hỏng 5% hay 50% số lượt thì không nói được H1/H3 có tác dụng hay không. Số
# đo thật (không phải mô phỏng) nằm ở docs/tasks/measurements/H4.md: trên 6
# lượt ảnh có chữ thật (loại bỏ ảnh hỏng cố ý `request323_overexposed`),
# `gemini-3.5-flash-lite` (model mặc định TRƯỚC H1) ra KHONG_CO_CHU 1/6 lần
# (ảnh chữ nhỏ, khung rộng); `gemini-3.5-flash` (đề xuất SAU H1, xem
# `config.GEMINI_OCR_MODEL`) và `gemini-2.5-flash` ra KHONG_CO_CHU 0/6 lần
# trên đúng bộ ảnh đó — trước/sau khác nhau thật, không phải cảm giác.
#
# `sharpness`/`brightness` PHẢI lấy từ tuple `measure()` đã chạy sẵn ở gate
# cho intent OCR (`measure()` luôn chạy cho mọi intent trong `_READS_IMAGE`,
# xem `reject_reason()` ở trên) — KHÔNG đo lại: decode ảnh + Laplacian
# float64 tốn CPU một lần nữa là vô ích khi số đã có sẵn.
#
# 🔴 Việc GỌI hàm này đúng lúc Gemini trả `NO_TEXT_SENTINEL` thuộc
# `models/ocr/__init__.py` — file đó ngoài bảng "FILE BẠN ĐƯỢC SỬA" của agent
# T15 (xem docs/tasks/reports/T15.md mục "Lệch với task file"). Đây là hạ
# tầng sẵn sàng (đếm + log đúng định dạng cần), CHƯA được nối dây vào
# production.
_no_text_count = 0


def record_no_text(sharpness: float | None, brightness: float | None) -> int:
    """Ghi nhận một lượt OCR ra KHONG_CO_CHU, trả về tổng số đã ghi nhận từ
    lúc tiến trình khởi động.

    `sharpness`/`brightness`: lấy từ `measure()` đã chạy sẵn ở gate, truyền
    `None` nếu không có (ví dụ ảnh không decode được ở bước đó).
    """
    global _no_text_count
    _no_text_count += 1
    logger.info(
        "OCR ra KHONG_CO_CHU lần %d: sharpness=%s brightness=%s",
        _no_text_count,
        f"{sharpness:.2f}" if sharpness is not None else "?",
        f"{brightness:.1f}" if brightness is not None else "?",
    )
    return _no_text_count


def no_text_count() -> int:
    """Tổng số lượt OCR ra KHONG_CO_CHU đã ghi nhận từ lúc tiến trình khởi động."""
    return _no_text_count


def reset_no_text_count() -> None:
    """Chỉ dùng cho test — đưa bộ đếm về 0 giữa các ca kiểm thử."""
    global _no_text_count
    _no_text_count = 0
