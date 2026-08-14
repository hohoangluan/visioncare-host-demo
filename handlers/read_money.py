"""Đọc mệnh giá tiền, với cơ chế từ chối khi bằng chứng không vững.

Người dùng tin tuyệt đối vào câu trả lời để tiêu tiền, nên đọc sai một chữ số
gây thiệt hại thật. Prompt văn xuôi yêu cầu "không chắc thì nói không chắc" đã
có từ trước và model vẫn khẳng định sai: đo trên ảnh thật (chụp ngược sáng, 3
tờ xoè chồng nhau), 6 mẫu cho cùng một tờ ra 20k / 20k / 50k / 50k / 50k /
500k, lần nào cũng nói chắc nịch.

Nên ở đây model chỉ được giao việc *khai từng manh mối rời*; ghép manh mối lại
và quyết định nói hay từ chối là việc của code bên dưới.

Ba manh mối, giao nhau ra đúng một tờ trong mọi trường hợp:
  màu chủ đạo  -> thu hẹp về một họ (xanh: 5k/20k/500k, nâu: 2k/10k/200k, ...)
  chữ số đầu   -> tách trong họ (xanh + '2' chỉ có thể là 20k)
  cửa sổ trong -> tách nốt phần còn lại (500k polymer có, 5k giấy cotton không)

Đòi model đọc trọn dãy số thì hỏng ở ảnh mờ; đòi từng manh mối rời thì mỗi cái
dễ hơn nhiều, mà ghép lại vẫn xác định. Đồng thời manh mối nào chỏi nhau là
dấu hiệu model đang bịa — đo thật thấy nó khai đọc được "10000" trong khi báo
màu xanh lơ, bất khả, và code bắt được ngay.

GIỚI HẠN: nếu model bịa nhất quán cả ba manh mối thì vẫn lọt. Muốn chặn nốt
cần thứ model không tự khai được — bỏ phiếu nhiều mẫu (tốn quota N lần), hoặc
cổng chất lượng ảnh tính bằng Python trước khi gọi Gemini (miễn phí; đo thử
thấy ảnh tiền nói trên có phương sai Laplacian 46.4 so với 75.5 và 95.3 của
hai ảnh chụp khác — tín hiệu có thật nhưng chưa calibrate được ngưỡng vì mới
có đúng một ảnh tiền để thử).
"""
import re
from collections.abc import Iterator

from models import vlm

REFUSAL = (
    "Tôi không chắc chắn, ảnh không đủ rõ để xác định mệnh giá, "
    "vui lòng chụp lại rõ hơn."
)

_COLOURS = ("xanh_la", "hong", "xanh", "nau", "xam", "khong_ro")

# Đặc điểm từng tờ đang lưu hành. `polymer` = có cửa sổ trong suốt; các tờ giấy
# cotton (1k, 2k, 5k và 500đ) không có.
#
# Bảng cho tờ nhỏ (500đ, 1.000đ) ít được kiểm hơn vì gần như không còn lưu
# hành. Sai ở đó chỉ gây từ chối thừa, không gây đọc sai: màu model khai sẽ
# không khớp và tờ đó bị loại khỏi danh sách ứng viên.
_NOTES = {
    500: ("xam", "5", False),
    1000: ("xam", "1", False),
    2000: ("nau", "2", False),
    5000: ("xanh", "5", False),
    10000: ("nau", "1", True),
    20000: ("xanh", "2", True),
    50000: ("hong", "5", True),
    100000: ("xanh_la", "1", True),
    200000: ("nau", "2", True),
    500000: ("xanh", "5", True),
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "anh_du_ro": {"type": "boolean"},
        "cac_to": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "so_in_doc_duoc": {"type": "string"},
                    "chu_so_dau": {"type": "string"},
                    "mau_chu_dao": {"type": "string", "enum": list(_COLOURS)},
                    "co_cua_so_trong": {
                        "type": "string",
                        "enum": ["co", "khong", "khong_ro"],
                    },
                    "menh_gia": {"type": "integer"},
                },
                "required": [
                    "so_in_doc_duoc",
                    "chu_so_dau",
                    "mau_chu_dao",
                    "co_cua_so_trong",
                    "menh_gia",
                ],
            },
        },
    },
    "required": ["anh_du_ro", "cac_to"],
}

_PROMPT = (
    "Ảnh chụp một hoặc nhiều tờ tiền Việt Nam Đồng. Với MỖI tờ nhìn thấy, khai "
    "từng manh mối dưới đây một cách độc lập.\n\n"
    "Hai lỗi nguy hiểm ngang nhau, tránh cả hai:\n"
    "1. Khai một manh mối bạn không thật sự nhìn rõ. Không rõ thì khai không rõ.\n"
    "2. Bỏ trống một manh mối bạn THẬT SỰ nhìn rõ. Nhìn rõ thì bắt buộc phải "
    "khai — thận trọng thừa cũng khiến người dùng không nhận được câu trả lời.\n\n"
    "Đừng suy ngược: không kết luận mệnh giá trước rồi điền manh mối cho khớp.\n\n"
    "- so_in_doc_duoc: con số mệnh giá in lớn trên tờ tiền, chép lại y như nhìn "
    "thấy và đủ số 0 (ví dụ '50000'). BỎ QUA số sê-ri, năm phát hành và mọi con "
    "số khác trên tờ. Không đọc rõ trọn con số mệnh giá thì để chuỗi rỗng.\n"
    "- chu_so_dau: CHỮ SỐ ĐẦU TIÊN của con số mệnh giá đó, đúng một ký tự "
    "('1', '2' hoặc '5'). Thường vẫn đọc được cả khi phần còn lại bị mờ hoặc "
    "che. Không rõ thì để chuỗi rỗng.\n"
    "- mau_chu_dao: màu nền chiếm phần lớn mặt tờ, chọn một trong:\n"
    "    xanh_la  — xanh lá cây, xanh ngọc, xanh ngả vàng\n"
    "    xanh     — xanh dương, xanh lơ, xanh tím than\n"
    "    hong     — hồng, hồng cánh sen, đỏ ngả hồng\n"
    "    nau      — nâu, nâu đỏ, nâu vàng\n"
    "    xam      — xám, xám ngả tím\n"
    "    khong_ro — ảnh ám màu, ngược sáng, hoặc bạn phân vân giữa hai màu\n"
    "  Chọn theo màu mắt bạn thấy, không theo mệnh giá bạn nghĩ. Phân vân thì "
    "khai khong_ro, đừng chọn đại.\n"
    "- co_cua_so_trong: tờ có ô cửa sổ trong suốt nhìn xuyên qua được không "
    "(thường ở mép hoặc góc tờ; tiền polymer có, tiền giấy cotton không). "
    "'co', 'khong', hoặc 'khong_ro' nếu vùng đó bị che, bị tờ khác chồng lên "
    "hoặc không phân biệt được.\n"
    "- menh_gia: mệnh giá bạn kết luận, tính bằng ĐỒNG và ghi đủ số 0. Chỉ được "
    "là một trong: 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, "
    "500000.\n\n"
    "anh_du_ro: đặt false CHỈ khi ảnh hỏng tới mức không khai nổi manh mối nào "
    "cho bất kỳ tờ nào (tối đen, nhoè hẳn, không thấy tờ tiền nào). Ảnh hơi mờ "
    "hoặc tờ bị che một phần vẫn đặt true, rồi khai không rõ ở đúng manh mối bị "
    "ảnh hưởng.\n\n"
    "Người dùng khiếm thị dùng câu trả lời này để tiêu tiền: manh mối bịa gây "
    "đọc sai mệnh giá, manh mối bỏ sót khiến họ phải chụp lại nhiều lần."
)

# Một con số viết theo nhóm nghìn ('50.000', '50 000'). Đòi nhóm cuối đúng ba
# chữ số và không dính chữ số nào phía sau, nếu không '200000 2006' (mệnh giá
# kèm năm phát hành) bị nuốt dấu cách thành một con số vô nghĩa.
_GROUPED = re.compile(r"\d{1,3}(?:[.,'’ ]\d{3})+(?!\d)")
_SEPARATORS = re.compile(r"[.,'’ ]")


def _digits(text) -> str:
    return "".join(c for c in str(text) if c.isdigit())


def _amounts(text) -> set[int]:
    """Các mệnh giá hợp lệ nằm trong dãy số model chép lại.

    Nối mọi chữ số thành một số là tự chặn mình: ảnh càng rõ model càng chép
    thêm số sê-ri và năm phát hành bên cạnh mệnh giá, ghép lại ra con số không
    tờ nào có nên tờ đó bị từ chối — đúng chiều ngược với mong đợi. Tách từng
    cụm rồi chỉ giữ cụm là mệnh giá thật thì sê-ri tự rụng.

    Chép ra hai mệnh giá khác nhau trên cùng một tờ vẫn giữ cả hai: bên dưới
    giao lại thành rỗng và tờ đó bị từ chối, đúng như mong muốn.
    """
    joined = _GROUPED.sub(lambda m: _SEPARATORS.sub("", m.group()), str(text))
    return {int(group) for group in re.findall(r"\d+", joined)} & set(_NOTES)


def _candidates(note: dict) -> set[int]:
    """Các mệnh giá còn sống sót sau khi lọc bằng mọi manh mối đã khai.

    Manh mối nào model khai là không rõ thì bỏ qua, không lọc gì.
    """
    alive = set(_NOTES)

    colour = note.get("mau_chu_dao")
    if colour in _NOTES_BY_COLOUR:
        alive &= _NOTES_BY_COLOUR[colour]

    lead = _digits(note.get("chu_so_dau", ""))[:1]
    if lead:
        alive &= {a for a in alive if _NOTES[a][1] == lead}

    window = note.get("co_cua_so_trong")
    if window in ("co", "khong"):
        alive &= {a for a in alive if _NOTES[a][2] == (window == "co")}

    # Không cụm nào là mệnh giá hợp lệ (chỉ chép được sê-ri, hoặc số bịa) thì
    # coi như chưa đọc được số, để các manh mối còn lại quyết.
    read = _amounts(note.get("so_in_doc_duoc", ""))
    if read:
        alive &= read

    return alive


_NOTES_BY_COLOUR = {
    colour: {a for a, (c, _, _) in _NOTES.items() if c == colour}
    for colour, _, _ in _NOTES.values()
}


def _read_notes(reply) -> tuple[list[int], int] | None:
    """(mệnh giá đọc chắc, số tờ chưa đọc được), hoặc None nếu không dùng được.

    Tách từng tờ thay vì bỏ cả câu trả lời khi một tờ đáng ngờ: người dùng cầm
    cả nắm tiền, biết chắc được tờ nào thì nói tờ đó — im hẳn chỉ khiến họ phải
    chụp đi chụp lại mà không nhận thêm thông tin gì.
    """
    if not isinstance(reply, dict) or reply.get("anh_du_ro") is not True:
        return None

    notes = reply.get("cac_to")
    if not isinstance(notes, list) or not notes:
        return None

    certain, unsure = [], 0
    for note in notes:
        # Còn nhiều hơn một ứng viên -> manh mối chưa đủ tách, đừng đoán.
        # Còn đúng một nhưng khác kết luận của model -> nó tự mâu thuẫn, đang bịa.
        if isinstance(note, dict) and _candidates(note) == {note.get("menh_gia")}:
            certain.append(note["menh_gia"])
        else:
            unsure += 1
    return certain, unsure


def _spell(amount: int) -> str:
    if amount >= 1000:
        return f"{amount // 1000} nghìn đồng"
    return f"{amount} đồng"


def _sentence(certain: list[int], unsure: int) -> str:
    """Câu nói do code dựng, không để model tự viết — bớt một nguồn dao động."""
    if len(certain) == 1 and not unsure:
        return f"Đây là tờ {_spell(certain[0])}."

    if len(certain) == 1:
        # Không mở bằng "Đây là tờ..." khi còn tờ chưa đọc được: người nghe bắt
        # được mỗi vế đầu sẽ tưởng đó là tất cả số tiền đang cầm.
        head = f"Đọc được một tờ {_spell(certain[0])}"
    else:
        spoken = ", ".join(_spell(a) for a in certain[:-1])
        head = f"Có {len(certain)} tờ: {spoken} và {_spell(certain[-1])}"

    if not unsure:
        return head + "."
    return f"{head}. Còn {unsure} tờ nữa tôi không đọc được, vui lòng chụp lại rõ hơn."


def handle(image: bytes, command_text: str) -> Iterator[str]:
    """Không streaming: phải đọc trọn bằng chứng rồi mới quyết nói hay từ chối.

    Không mất gì — câu trả lời vốn ngắn, đo trước đó cho thấy câu ngắn về
    cùng một lúc nên streaming không sớm hơn được.
    """
    reply = vlm.generate_json(_PROMPT, image=image, schema=_SCHEMA)
    result = _read_notes(reply)
    if result is None or not result[0]:
        yield REFUSAL
        return
    yield _sentence(*result)
