"""Bảng chính sách slot — nguồn sự thật DUY NHẤT cho câu hỏi lại (T06).

`docs/tasks/CONTRACTS.md` mục 4.2, `docs/tasks/T06-slot-policy.md` mục D1/D3/D5.

Trước T06, năm hằng số `_ASK_*` nằm rải rác ở bốn handler
(`handlers/phone.py`, `handlers/navigation.py`, `handlers/ride.py`,
`handlers/music.py`), mỗi nơi tự quyết khi nào hỏi lại và không ai đọc lại
thông tin trước khi gửi (trừ `ride`). Module này gom lại thành MỘT bảng:

  `ask`      câu hỏi khi thiếu slot
  `readback` "always" | "low_conf" | "never" — có đọc lại giá trị vừa nghe
             được cho người dùng xác nhận trước khi gửi lệnh không (D3)
  `risk`     "high" | "low" — chỉ mang tính tài liệu, sai một slot `risk=high`
             là gửi nhầm việc không sửa lại được (gọi nhầm người, đi nhầm chỗ)
  `kind`     "fill" | "confirm" | "select" — khớp với TTL của T03
             (`handlers.action_flow._TTL_BY_KIND`): fill=120s, confirm=25s,
             select=45s

⚠️ Phạm vi file được sửa của T06 KHÔNG bao gồm `handlers/phone.py`,
`handlers/navigation.py`, `handlers/ride.py`, `handlers/music.py` (xem
`docs/tasks/reports/T06.md` mục "Lệch với task file") — bốn hằng số `_ASK_*`
cũ ở đó VẪN CÒN, y nguyên, chưa được dời/xoá. Module này là nguồn CHUẨN cho
mọi pending mới được tạo qua `handlers.action_flow.set_pending()` (ví dụ
đường D4 — hỏi lại slot khi host trả mã lỗi, xem `handlers/action_flow.py`),
không phải một sự thay thế đã hoàn tất cho các nhánh "thiếu tham số -> hỏi
ngay" hiện có trong bốn handler kể trên.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotSpec:
    """Chính sách hỏi-lại của một slot."""

    ask: str
    readback: str  # "always" | "low_conf" | "never"
    risk: str  # "high" | "low"
    kind: str  # "fill" | "confirm" | "select" -> quyết định TTL (T03)


# 5 hằng số câu hỏi — CHỈ 5, không phải 6, dù SLOTS có 6 dòng: `destination` và
# `ride_destination` dùng CHUNG một câu hỏi ("Bạn muốn đi đâu?"), chỉ khác
# `readback` (xem docstring `SLOTS` bên dưới để biết vì sao KHÔNG gộp hai dòng
# này làm một). Đây là nơi DUY NHẤT trong module này định nghĩa văn bản câu hỏi
# — không viết lại chuỗi ở nơi khác trong file này.
_ASK_CONTACT_NAME = "Bạn muốn gọi cho ai?"
_ASK_DESTINATION = "Bạn muốn đi đâu?"
_ASK_SONG_TITLE = "Bạn muốn nghe bài hát nào?"
_ASK_ARTIST = "Bạn muốn nghe của ca sĩ nào?"
_ASK_VOLUME_DIRECTION = "Bạn muốn tăng hay giảm âm lượng?"

# CONTRACTS.md mục 4.2 — COPY NGUYÊN VĂN. Đủ 6 slot ngay từ bây giờ (không
# phải thêm dần theo từng đợt): một wave sau có 6 agent chạy song song, không
# ai trong số họ có thể sửa an toàn một file dùng chung nếu bảng này chưa đủ.
#
# `ride_destination` = `always`: gọi xe tốn tiền thật, và sau T11/R1 lượt đọc
# lại còn chở thêm bảng giá — lượt có giá trị nhất, đáng đọc lại toàn bộ.
# `destination` (nav_start, miễn phí, sửa được ngay bằng "thôi dừng lại") =
# `low_conf`: xác nhận mọi lần là hình phạt cho ca dùng phổ biến nhất.
SLOTS: dict[str, SlotSpec] = {
    "contact_name": SlotSpec(_ASK_CONTACT_NAME, "low_conf", "high", "fill"),
    "destination": SlotSpec(_ASK_DESTINATION, "low_conf", "high", "fill"),
    "ride_destination": SlotSpec(_ASK_DESTINATION, "always", "high", "fill"),
    "song_title": SlotSpec(_ASK_SONG_TITLE, "never", "low", "fill"),
    "artist": SlotSpec(_ASK_ARTIST, "never", "low", "fill"),
    "volume_direction": SlotSpec(_ASK_VOLUME_DIRECTION, "never", "low", "fill"),
}

# 🔴🔴🔴 D5 / CONTRACTS.md mục 0 nguyên tắc 3 — TUYỆT ĐỐI. KHÔNG XOÁ, KHÔNG
# LÀM YẾU ASSERT NÀY, KHÔNG THÊM "emergency_number" VÀO SLOTS Ở TRÊN.
#
# `emergency_call` không được đi qua BẤT KỲ bước xác minh nào. Cho nó một
# SlotSpec là tự động sinh ra một đường hỏi lại (mọi pending đều mang `ask` +
# `question` để đọc lại) — đúng MỘT thứ duy nhất tuyệt đối không được tồn tại
# cho lệnh này. Người dùng gọi khẩn cấp là lúc họ có thể đang ngã, đang bị
# thương, không nói thêm được câu thứ hai; hỏi lại "bạn muốn gọi số nào?" hay
# đọc lại số để chờ xác nhận là trì hoãn đúng lúc không được phép trì hoãn.
#
# Assert chạy NGAY LÚC MODULE NÀY ĐƯỢC IMPORT (import time), không nằm trong
# một hàm hay chỉ trong test — ai vô tình thêm "emergency_number" vào SLOTS
# (ví dụ copy-paste một slot khác rồi đổi tên) làm SERVER CRASH ngay khi nạp
# module, thay vì âm thầm mở một đường hỏi lại cho ca nguy hiểm nhất trong toàn
# bộ spec. Xem thêm `handlers/action_flow.py` (`_reask_pending_for_error`) —
# nơi có một chốt chặn TƯỜNG MINH thứ hai, độc lập với assert này.
assert "emergency_number" not in SLOTS, (
    "emergency_call KHÔNG được thêm bất kỳ bước hỏi lại hay "
    "đọc-lại-chờ-xác-nhận nào. Người dùng gọi khẩn cấp là lúc họ có thể đang "
    "ngã, đang bị thương, không nói thêm được câu thứ hai. Mọi cơ chế xác minh "
    "phải loại trừ nhãn này TƯỜNG MINH trong code, không để mặc định rơi vào."
)


def should_readback(slot: str, confidence: str | None) -> bool:
    """D3 — có cần đọc lại giá trị `slot` cho người dùng xác nhận trước khi
    gửi lệnh không.

    `confidence` là `slot_confidence` (T05/A1) — `"low"` | `"high"` | `None`.

    | `readback`  | Hành vi                                          |
    |-------------|---------------------------------------------------|
    | `always`    | luôn đọc lại, bất kể `confidence`                  |
    | `low_conf`  | chỉ đọc lại khi `confidence == "low"`              |
    | `never`     | gửi thẳng, không bao giờ đọc lại                   |

    `slot` không có trong `SLOTS` -> `False`: an toàn hơn là tự bịa ra một luật
    đọc lại cho một slot chưa từng được định nghĩa chính sách (kể cả
    `emergency_number` — xem assert ở trên, `should_readback` cho slot này
    LUÔN là `False`, không có nhánh đặc cách nào cho nó ở đây).
    """
    spec = SLOTS.get(slot)
    if spec is None:
        return False
    if spec.readback == "always":
        return True
    if spec.readback == "low_conf":
        return confidence == "low"
    return False  # "never"


# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio (G5).
# Đúng 5 câu — khớp 5 hằng số `_ASK_*` ở trên (`destination` dùng chung câu với
# `ride_destination` nên không nhân đôi trong tập này).
STATIC_SPEECH: tuple[str, ...] = (
    _ASK_CONTACT_NAME,
    _ASK_DESTINATION,
    _ASK_SONG_TITLE,
    _ASK_ARTIST,
    _ASK_VOLUME_DIRECTION,
)
