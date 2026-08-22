import inspect
import logging
import re
import time
from collections.abc import Callable, Iterator

from schemas import Intent
from pipeline import image_quality, intent_local, stt, intent as intent_mod
from handlers import (
    ocr, find_object, read_money, describe_space, describe_hazard, chat,
    nav_start, nav_stop, contact_call, emergency_call, ride_quote, ride_confirm,
    music_play, music_stop, music_volume
)
from handlers.waiting import with_progress_notice

logger = logging.getLogger("blind_assist")

_HANDLERS = {
    Intent.OCR: ocr,
    Intent.FIND: find_object,
    Intent.MONEY: read_money,
    Intent.SPACE: describe_space,
    Intent.HAZARD: describe_hazard,
    Intent.CHAT: chat,
    Intent.NAV_START: nav_start,
    Intent.NAV_STOP: nav_stop,
    Intent.CONTACT_CALL: contact_call,
    Intent.EMERGENCY_CALL: emergency_call,
    Intent.RIDE_QUOTE: ride_quote,
    Intent.RIDE_CONFIRM: ride_confirm,
    Intent.MUSIC_PLAY: music_play,
    Intent.MUSIC_STOP: music_stop,
    Intent.MUSIC_VOLUME: music_volume,
}

# Chỉ còn HAI câu, và cả hai đều nói về một trạng thái LỖI của hệ thống, không
# phải về việc người dùng nói khó hiểu.
#
# Câu thứ ba ("tôi chưa hiểu bạn muốn gì") đã bỏ cùng với nhãn `unknown`: câu
# nghe ra chữ mà không ra nghĩa giờ về `chat`, và chính Gemini nói mình chưa
# hiểu — nó đọc được nguyên văn nên nói được câu sát tình huống, thay vì đọc một
# câu soạn sẵn cho mọi trường hợp.
_NO_SPEECH_MESSAGE = "Xin lỗi, tôi không nghe rõ, vui lòng nói lại."
# Không nhận là "tôi chưa hiểu": lúc này hệ thống chưa hiểu được câu nào cả, kể
# cả câu hoàn hảo. Nói đúng thứ đang xảy ra để người dùng biết cứ thử lại.
_CLASSIFY_FAILED_MESSAGE = "Hệ thống đang bận, bạn vui lòng thử lại sau giây lát."

# ─── T04 (docs/tasks/T04-router-bargein.md, CONTRACTS.md mục 4.3 / 21.1) ───
#
# 1. EMERGENCY                 <- tuyệt đối
# 2. PENDING TẤT ĐỊNH          <- ừ/không/số thứ tự/thôi/nói lại
# 3. STOP / LỆNH TOÀN CỤC      <- chèn vào ĐÂY, GIỮA hai pha pending
# 4. PENDING ĐIỀN SLOT         <- qua slot validator
# 5. CANCEL / REPEAT
# 6. INTENT DETECT
#
# Đây là thứ dễ bị viết lại sai nhất trong cả spec (docs/tasks/CONTRACTS.md
# mục 4.3): bước 3 nằm GIỮA hai pha pending, không phải trên hay dưới cả hai.
#
# Nguyên tắc 1 (CONTRACTS.md mục 0): trạng thái thiết bị (nhạc đang phát, chỉ
# đường đang chạy) là GỢI Ý CHO BỘ PHÂN LOẠI, KHÔNG PHẢI HÀNG RÀO ở đây — hai
# nhánh "Fast-Bypass" cũ (nhạc đang phát -> mọi câu thành tắt nhạc; chỉ đường
# đang chạy -> mọi câu thành dừng chỉ đường) đã BỊ XOÁ, không phải đổi tên hay
# giấu đi. Người dùng phải nói được bất cứ gì, bất cứ lúc nào — kể cả lúc nhạc
# đang phát: hỏi giờ, gọi cấp cứu, hỏi vật cản đều phải đi được.

# 21.5 (T09 sẽ hoàn thiện: cổng từ khoá ĐỘ CHÍNH XÁC CAO OR
# classifier(p > ngưỡng thấp), ưu tiên RECALL hơn precision cho lớp này). T04
# chỉ dựng được NỬA ĐẦU (từ khoá) vì không được sửa `pipeline/intent.py` (nơi
# định nghĩa `_LABELS`/ngưỡng phân loại cục bộ) — file đó NẰM NGOÀI "FILE BẠN
# ĐƯỢC SỬA" của task này. Từ khoá ở đây ưu tiên ĐỘ CHÍNH XÁC (khó nhầm với câu
# nói thường) hơn độ phủ: thiếu vế OR-classifier thì một từ khoá quá rộng sẽ
# bắt oan một câu bình thường thành khẩn cấp. Câu khẩn cấp không khớp từ khoá
# này vẫn còn một đường thứ hai (yếu hơn): bước 6 (INTENT DETECT) vẫn có thể
# nhận ra `emergency_call` qua bộ phân loại cục bộ/Gemini như trước T04 — chỉ
# là khi đó nó không còn "tuyệt đối" (có thể bị bước 2-5 xử lý trước nếu rơi
# đúng câu chữ trùng với một mẫu khác). Xem "Cần người dùng chốt" ở
# docs/tasks/reports/T04.md.
_LOCAL_EMERGENCY = re.compile(
    r"cấp cứu|khẩn cấp|gọi 115|gọi 113|sos|cứu (tôi|với|em|cháu|giúp)",
    re.I,
)

# B1: barge-in cục bộ — KHÔNG chạy Gemini, chỉ chạy khi CÓ tác vụ đang chạy
# (`device_state()` báo nhạc hoặc chỉ đường). Không có gì đang chạy thì bỏ qua
# hẳn bước này (rớt xuống bước 4/5/6) — chạy regex này khi không có gì để dừng
# vừa vô ích vừa dễ nuốt nhầm câu khác không liên quan tới dừng cái gì cả.
_LOCAL_STOP = re.compile(
    r"tắt nhạc|dừng nhạc|dừng chỉ đường|dừng lại|thôi|im lặng", re.I
)

# ─── Pha 2 — PENDING TẤT ĐỊNH: câu trả lời ĐÓNG, khớp tất định, không LLM ──
_PENDING_YES = re.compile(
    r"\b(ừ|ừm|vâng|đúng rồi|đúng vậy|đồng ý|xác nhận|được|ok|okay)\b", re.I
)
_PENDING_NO = re.compile(
    r"\b(không phải|không đúng|sai rồi|không)\b", re.I
)
_PENDING_REPEAT = re.compile(
    r"nói lại|nhắc lại|lặp lại|gì cơ|sao cơ|nghe không rõ", re.I
)
_PENDING_CANCEL = re.compile(
    r"\bthôi\b|bỏ đi|hủy|huỷ|khỏi cần|không cần nữa", re.I
)
_ORDINAL_INDEX: dict[str, int] = {
    "thứ nhất": 0, "số một": 0, "một": 0, "1": 0,
    "thứ hai": 1, "số hai": 1, "hai": 1, "2": 1,
    "thứ ba": 2, "số ba": 2, "ba": 2, "3": 2,
    "thứ tư": 3, "số bốn": 3, "bốn": 3, "4": 3,
}
_CANCELLED_MESSAGE = "Đã huỷ."

# ─── Pha 5 — CANCEL / REPEAT toàn cục (không có pending nào đang mở) ───────
#
# `cancel`/`repeat` CHƯA phải nhãn trong schema phân loại của Gemini (spec mục
# "B5 — Thêm nhãn cancel và repeat" còn TODO, và `pipeline/intent.py` không
# nằm trong "FILE BẠN ĐƯỢC SỬA" của T04) — CONTRACTS.md mục 3 xếp hai chức
# năng này vào nhóm "không mạng ngoài, không LLM", nên bước 5 nhận diện bằng
# regex cục bộ y như bước 3, KHÔNG đi qua bước 6.
_GLOBAL_CANCEL = re.compile(r"\bhủy\b|\bhuỷ\b|bỏ đi|thôi khỏi|không cần nữa", re.I)
_GLOBAL_REPEAT = re.compile(
    r"nói lại|nhắc lại|lặp lại|nghe không rõ|gì cơ|sao cơ", re.I
)
_NOTHING_TO_CANCEL = "Hiện không có gì để huỷ."
# Bước 5 KHÔNG có pending để mượn `question`, và việc nối vào "câu vừa nói"
# dùng chung (B4, hạ tầng `action_flow.record_history_turn`/`recent_history`)
# CHƯA được `router.py` ghi vào — không handler nào trong pipeline này gọi
# `record_history_turn()` nên `recent_history()` luôn rỗng ở thời điểm T04.
# Nối lịch sử thật là việc CHUNG với B4 (đã ghi nhận là việc CHƯA XONG ở
# docs/tasks/reports/T03.md), không phải phạm vi ưu tiên router của T04 — xem
# "Lệch với task file" trong docs/tasks/reports/T04.md. Vẫn trả lời có nghĩa
# thay vì im lặng hay rơi vào Gemini.
_NOTHING_TO_REPEAT = "Chưa có câu nào để nhắc lại."

# ─── Slot validator (KHUNG) — T08/T10/T12 cắm danh sách từ chối của họ vào ──
#
# INTERFACE (giữ ổn định, ba task sau đọc mục này để cắm đúng — xem
# docs/tasks/reports/T04.md phần "Slot validator"):
#
#     validator(text: str) -> bool
#         `text`: NGUYÊN VĂN câu STT của lượt đang trả lời pending (không phải
#         params đã trích). True = CHẤP NHẬN dùng `text` làm giá trị lấp cho
#         slot. False = TỪ CHỐI — pending bị bỏ, câu được xử lý lại từ đầu qua
#         bước 6 (INTENT DETECT) như một câu nói hoàn toàn mới.
#
#     register_slot_validator(slot: str, validator) -> None
#         Đăng ký/GHI ĐÈ validator cho một `slot`. Gọi một lần (import time là
#         đủ) từ module của task sở hữu slot đó — KHÔNG cần sửa
#         `pipeline/router.py`.
#
# Danh sách dưới đây (`_IMPERATIVE_VERBS`, `_VOLUME_DIRECTION_WORDS`, ba mục
# trong `_SLOT_VALIDATORS`) chỉ là PHẦN KHUNG/CHỖ GIỮ TẠM đúng bảng ở
# docs/tasks/T04-router-bargein.md mục 2 — CHƯA đo trên dữ liệu thật, T08
# (`contact_name`), T10 (`destination`), T12 (`volume_direction`/`song_title`)
# được kỳ vọng THAY THẾ bằng danh sách đầy đủ hơn của họ qua
# `register_slot_validator()`, không phải chỉnh trực tiếp các hằng số này.
_IMPERATIVE_VERBS = re.compile(
    r"^\s*(tắt|dừng|mở|gọi|phát|bật|tăng|giảm|hủy|huỷ|im lặng)\b", re.I
)
_VOLUME_DIRECTION_WORDS = re.compile(
    r"\b(tăng|giảm|to hơn|nhỏ hơn|lớn hơn|bé hơn|nhỏ lại|to lên|\d+)\b", re.I
)


def _default_slot_validator(text: str) -> bool:
    """Mặc định CHẤP NHẬN mọi thứ trừ khi khớp lệnh toàn cục (`_LOCAL_STOP`) —
    an toàn hơn từ chối oan một câu hợp lệ khi slot chưa có validator riêng."""
    return _LOCAL_STOP.search(text or "") is None


def _reject_imperative(text: str) -> bool:
    """`contact_name`/`destination`: KHÔNG nhận động từ mệnh lệnh mở đầu câu
    (tắt, dừng, mở, gọi, phát...) — đây chính là ca vỡ 21.1 ("tắt nhạc" đi lấp
    nhầm `contact_name`)."""
    return _IMPERATIVE_VERBS.search(text or "") is None and _default_slot_validator(text)


def _accept_volume_direction(text: str) -> bool:
    """`volume_direction`: CHỈ nhận tăng/giảm/số — mọi thứ khác bị từ chối."""
    return _VOLUME_DIRECTION_WORDS.search(text or "") is not None


_SLOT_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "contact_name": _reject_imperative,
    "destination": _reject_imperative,
    "volume_direction": _accept_volume_direction,
    # "song_title": gần như mọi thứ là tên bài hợp lệ, chỉ chặn lệnh dừng toàn
    # cục — dùng thẳng mặc định, liệt kê tường minh ở đây để bảng khớp đúng
    # docs/tasks/T04-router-bargein.md mục 2, không phải vì hành vi khác mặc định.
    "song_title": _default_slot_validator,
}


def register_slot_validator(slot: str, validator: Callable[[str], bool]) -> None:
    """Đăng ký (hoặc ghi đè) validator cho `slot`. Xem docstring khối phía trên
    để biết interface đầy đủ — T08/T10/T12 gọi hàm này từ module của họ."""
    _SLOT_VALIDATORS[slot] = validator


def _validate_slot(slot: str, text: str) -> bool:
    validator = _SLOT_VALIDATORS.get(slot, _default_slot_validator)
    return validator(text)


# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = (
    _NO_SPEECH_MESSAGE,
    _CLASSIFY_FAILED_MESSAGE,
    _CANCELLED_MESSAGE,
    _NOTHING_TO_CANCEL,
    _NOTHING_TO_REPEAT,
)


def _capture_device_key() -> str:
    """Chụp `device_key` của thiết bị đang gọi, NGAY TRONG lúc còn chắc chắn ở
    luồng request thật (có `app.DEVICE_ID_CTX` đúng).

    Bắt buộc phải làm việc này ở `resolve_speech()` — TRƯỚC khi giao việc cho
    `with_progress_notice()` — chứ không được để cho `_resolve()` tự đọc ambient
    context lúc thân hàm nó THỰC SỰ chạy: `with_progress_notice()` ->
    `handlers/waiting.py::wait_for()` kéo MẢNH ĐẦU của `_resolve()` trên một
    `threading.Thread` TRẦN (`daemon=True, name="waiting"`), và một thread trần
    KHÔNG kế thừa `contextvars.Context` của thread tạo ra nó. Toàn bộ thân
    `_resolve()` — kể cả `bump_generation()` ở đầu hàm và mảnh đầu kéo qua
    `_with_bargein()` — chạy TRỌN VẸN trên thread đó cho tới yield đầu tiên.

    Không chụp ở đây thì `action_flow._device_key()` (ambient) đọc ra `None`
    lúc chạy trên thread trần đó, rơi về `_NO_DEVICE_CONTEXT_KEY` — một session
    DÙNG CHUNG cho MỌI thiết bị. Hậu quả thật (tái hiện được, không phải giả
    thuyết): barge-in trở thành TOÀN SERVER thay vì THEO THIẾT BỊ (lượt của
    thiết bị B huỷ nhầm lượt của thiết bị A), và bất cứ lúc nào có nơi khác
    (ví dụ luồng tiêu thụ của `pipeline/tts.py`) vô tình gắn đúng context thiết
    bị vào một thread trần tương tự, generation của lượt đó lệch khỏi
    generation mà `_resolve()` đã lỡ ghi vào `_NO_DEVICE_CONTEXT_KEY` — mọi
    câu trả lời sẽ tự cắt cụt sau mảnh đầu, kèm một dòng log "Barge-in" trông
    như cố ý. Xem `docs/tasks/reports/T04.md` mục sửa lỗi cho bằng chứng tái
    hiện.

    Nhập trễ + đọc thẳng `app.DEVICE_ID_CTX`/hằng số `_NO_DEVICE_CONTEXT_KEY`
    của `handlers.action_flow` (không phải một hàm public mới): phạm vi sửa
    `handlers/action_flow.py` được cấp cho T04 CHỈ gồm hai chữ ký
    `bump_generation()`/`current_generation()` thêm tham số tuỳ chọn — không
    được thêm hàm mới vào file đó.
    """
    from handlers import action_flow

    try:
        import app as _app_module
    except ImportError:
        return action_flow._NO_DEVICE_CONTEXT_KEY
    device_id = _app_module.DEVICE_ID_CTX.get()
    return device_id or action_flow._NO_DEVICE_CONTEXT_KEY


def resolve_speech(
    image: bytes | None, audio: bytes, opening_seconds: float = 0.0
) -> Iterator[str]:
    """Pipeline audio -> STT -> ưu tiên (21.1) -> handler -> từng mảnh câu cần đọc.

    Trả luồng mảnh text chứ không phải chuỗi hoàn chỉnh, và không tự gọi TTS:
    `app.py` bắt đầu tổng hợp giọng nói từ câu đầu trong lúc Gemini còn đang
    viết phần sau.

    Câu trấn an bọc quanh CẢ pipeline, không riêng handler: STT với phân loại
    intent tốn khoảng 2 giây trước khi handler chạy dòng đầu tiên, nên đặt đồng
    hồ ở trong là 2 giây đó không ai đếm và người dùng chờ dài hơn đúng ngần ấy.

    `opening_seconds`: độ dài câu chào `app.py` vừa nói trước khi gọi vào đây.
    """
    # G4: chụp device_key ở ĐÂY — hàm này chạy ĐỒNG BỘ trong luồng request
    # thật, TRƯỚC khi `with_progress_notice` có cơ hội giao việc kéo mảnh đầu
    # sang một thread trần khác. Xem `_capture_device_key()`.
    device_key = _capture_device_key()
    return with_progress_notice(
        _resolve(image, audio, device_key), opening_seconds=opening_seconds
    )


def _dispatch(
    intent_name: str, image: bytes | None, command_text: str, params: dict | None = None
) -> Iterator[str]:
    """Gọi handler của `intent_name`, tự dò chữ ký (một số handler nhận
    `params`, một số thì không) — dùng chung cho MỌI bước (1-6) dispatch tới
    handler, không riêng bước 6."""
    handler_mod = _HANDLERS.get(intent_name, chat)
    sig = inspect.signature(handler_mod.handle)
    if "params" in sig.parameters:
        return handler_mod.handle(image, command_text, params=params or {})
    return handler_mod.handle(image, command_text)


def _with_bargein(
    pieces: Iterator[str], action_flow, device_key: str
) -> tuple[str, Iterator[str]]:
    """G4 (barge-in) + G2 (không giữ lock lúc gọi LLM): kéo mảnh ĐẦU ngay (để
    bên gọi đo thời gian/log như cũ), chụp lại `generation` NGAY SAU đó, rồi
    trả một generator cho PHẦN CÒN LẠI có kiểm tra generation trước khi kéo
    mỗi mảnh kế tiếp.

    Chụp `generation` SAU mảnh đầu, không phải trước khi gọi handler: một số
    handler (`run_action()` ở `handlers/action_flow.py`, T03) tự bump
    generation NGAY BÊN TRONG, trước khi yield mảnh đầu (ack) — chụp sớm hơn
    sẽ khiến chính lượt này tưởng nhầm mình đã lỗi thời và tự huỷ ngay sau khi
    vừa nói xong ack (xem "Lệch với task file"/mục deferred ở
    docs/tasks/reports/T03.md — đây chính là cái bẫy T03 đã cảnh báo trước).

    Lượt MỚI cùng thiết bị tới -> `action_flow.bump_generation()` của NÓ (chạy
    ở đầu `_resolve()`, một luồng/request KHÁC) tăng generation của session
    dùng chung -> `action_flow.current_generation()` đọc lại ở đây lệch với
    giá trị đã chụp -> dừng NGAY, không gọi thêm `next()` nào lên `pieces`
    nữa. Handler càng dùng generator streaming thật (`vlm.generate_stream` ở
    `handlers/chat.py`) thì dừng ở đây càng đúng nghĩa "huỷ lượt cũ": không
    còn token nào được kéo thêm từ Gemini. `app.py` chỉ tổng hợp giọng (TTS)
    từ đúng những mảnh mà generator NÀY thực sự yield ra, nên dừng sinh mảnh ở
    đây cũng dừng luôn TTS của lượt cũ — không cần `app.py`/`pipeline/tts.py`
    biết gì về generation (cả hai đều NẰM NGOÀI "FILE BẠN ĐƯỢC SỬA" của T04).

    Việc này KHÔNG hủy được cuộc gọi HTTP đang chờ VisionCare host bên trong
    `run_action()` (đó là code của `handlers/action_flow.py`, ngoài phạm vi
    sửa) — chỉ dừng việc RELAY tiếp audio/text của lượt cũ ra ngoài. Đây là
    giới hạn thật, ghi rõ trong báo cáo, không phải hành vi che giấu.

    `device_key`: BẮT BUỘC truyền tường minh — chụp SẴN ở `resolve_speech()`
    qua `_capture_device_key()`, KHÔNG được để `action_flow.bump_generation()`/
    `current_generation()` tự đọc ambient context ở đây. Thân hàm này (và của
    `_resolve()`) có thể chạy trên một `threading.Thread` TRẦN
    (`handlers/waiting.py::wait_for`), không kế thừa ContextVar — đọc ambient
    context ở đó luôn ra `None`, khiến generation của MỌI thiết bị đổ chung
    vào một session (`_NO_DEVICE_CONTEXT_KEY`) và barge-in hoá ra TOÀN SERVER
    thay vì THEO THIẾT BỊ. Xem `docs/tasks/reports/T04.md` mục sửa lỗi.
    """
    it = iter(pieces)
    first = next(it, "")
    my_generation = action_flow.current_generation(device_key)

    def _rest() -> Iterator[str]:
        while True:
            if action_flow.current_generation(device_key) != my_generation:
                logger.info(
                    "Barge-in (G4): lượt mới cùng thiết bị đã tới (generation "
                    "lệch, cũ=%s) -> huỷ phần còn lại của lượt này, không kéo "
                    "thêm token/audio nào nữa",
                    my_generation,
                )
                return
            try:
                piece = next(it)
            except StopIteration:
                return
            yield piece

    return first, _rest()


def _ordinal_index(text: str) -> int | None:
    lowered = (text or "").lower()
    for phrase, idx in _ORDINAL_INDEX.items():
        if phrase in lowered:
            return idx
    return None


def _resolve_deterministic_pending(
    pending, image: bytes | None, command_text: str, action_flow
) -> Iterator[str] | None:
    """Pha 2 (21.1) — PENDING TẤT ĐỊNH: câu trả lời ĐÓNG cho pending đang mở
    (ừ/không/số thứ tự/thôi/nói lại), khớp tất định, KHÔNG LLM.

    Trả `None` nếu câu KHÔNG khớp bất kỳ mẫu đóng nào — KHÔNG coi "không khớp"
    là "huỷ": để bước 3 (STOP) rồi bước 4 (PENDING ĐIỀN SLOT) xét tiếp, tránh
    nuốt nhầm một câu không liên quan (ví dụ câu trả lời MỞ cho pending `fill`).
    """
    text = command_text or ""

    if _PENDING_REPEAT.search(text):
        # "gì cơ"/"nói lại": đọc lại NGUYÊN VĂN câu hỏi, pending GIỮ NGUYÊN
        # (không tính là một lượt trả lời, không tăng attempt).
        return iter([pending.question])

    if _PENDING_CANCEL.search(text):
        action_flow.clear_pending()
        return iter([_CANCELLED_MESSAGE])

    if pending.kind == "confirm":
        # SỬA LỖI review (docs/tasks/reports/T04.md mục sửa lỗi #2): kiểm
        # PHỦ ĐỊNH TRƯỚC khẳng định. `_PENDING_YES` chứa "được"/"đồng ý" với
        # ranh giới `` — hai từ đó vẫn khớp y nguyên BÊN TRONG một câu phủ
        # định ("không được", "không đồng ý", "tôi bị ngã không dậy được"),
        # nên kiểm YES trước sẽ đọc một câu từ chối/cầu cứu thành "đồng ý".
        # CONTRACTS mục 4.1 xếp `confirm` là loại pending NGUY HIỂM NHẤT khi
        # đoán sai (đặt xe/gọi điện đã lỡ xác nhận) — phủ định phải thắng khi
        # cả hai cùng khớp, đúng cách một người nghe sẽ hiểu câu đó.
        if _PENDING_NO.search(text):
            action_flow.clear_pending()
            return iter([_CANCELLED_MESSAGE])
        if _PENDING_YES.search(text):
            action_flow.clear_pending()
            return _dispatch(pending.intent, image, command_text, dict(pending.known))
        return None

    if pending.kind == "select":
        # Cùng lý do: phủ định ("không phải cái này") phải thắng trước khi
        # xét số thứ tự — số thứ tự không tự nhiên xuất hiện chung với phủ
        # định trong một câu ngắn, nên đổi thứ tự này không mất ca hợp lệ nào.
        if _PENDING_NO.search(text):
            action_flow.clear_pending()
            return iter([_CANCELLED_MESSAGE])
        idx = _ordinal_index(text)
        if idx is not None and idx < len(pending.candidates):
            action_flow.clear_pending()
            chosen = pending.candidates[idx]
            known = dict(pending.known)
            if isinstance(chosen, dict):
                known.update(chosen)
            else:
                known["selected"] = chosen
            return _dispatch(pending.intent, image, command_text, known)
        return None

    # kind == "fill": không có câu trả lời ĐÓNG khả dĩ nào khác — để pha 4 xử lý.
    return None


def _global_stop_target(command_text: str, state: dict) -> str | None:
    """Pha 3 (21.1) — STOP / LỆNH TOÀN CỤC: `None` nếu KHÔNG có gì đang chạy
    (regex không chạy trong trường hợp đó — chạy luôn tốn vô ích, brief mục
    2/B1), hoặc câu không khớp `_LOCAL_STOP`.

    Dùng lại đúng bộ luật gỡ mơ hồ đã có ở `pipeline/intent.py`
    (`_apply_state`: câu chữ trước, "vừa bật gần đây nhất" sau khi cả hai cùng
    chạy) thay vì viết lại — một nguồn sự thật duy nhất cho "tắt đi nghĩa là
    tắt cái gì". Nhãn truyền vào (`MUSIC_STOP`) không quan trọng: cả hai nhãn
    đều nằm trong `_STATE_DEPENDENT` nên cho cùng kết quả.
    """
    if not (state.get("music_playing") or state.get("navigating")):
        return None
    if not _LOCAL_STOP.search(command_text or ""):
        return None
    return intent_mod._apply_state(Intent.MUSIC_STOP, state, command_text)


def _try_fill_pending_slot(
    pending, image: bytes | None, command_text: str, state: dict
) -> Iterator[str] | None:
    """Pha 4 (21.1) — PENDING ĐIỀN SLOT, qua Gemini có ngữ cảnh pending (B3/T05).

    Trả `None` nếu KHÔNG lấp được — bên gọi (`_resolve`) tự bỏ pending
    (`clear_pending()`) và để câu này chảy tiếp xuống bước 6 như một câu nói
    HOÀN TOÀN MỚI. Hai lý do khiến không lấp được:

    1. Câu này thật ra là một Ý ĐỊNH KHÁC HẲN — `detect_with_params(pending=)`
       (có toàn bộ ngữ cảnh câu hỏi, không chỉ nhãn cục bộ rẻ tiền) trả về
       intent khác `pending.intent` và khác `chat`/`unknown`. Đây là ca
       `test_unrelated_intent_during_pending`: "gọi cho mẹ" giữa lúc đang chờ
       trả lời `song_title` phải thành `contact_call`, không phải một tên bài
       hát tên là "gọi cho mẹ".
    2. Gemini không trích được `pending.slot` từ câu này (thiếu key trong
       `params` trả về), hoặc trích được nhưng bị chính validator của
       `pending.slot` từ chối (`test_slot_validator_rejects_imperative`,
       `test_volume_validator_only_accepts_direction`).

    🔴 SỬA 2026-08-22 — bug thật đã nằm trong code từ bản T04 gốc: hàm này
    từng dùng `intent_local.classify()` (bộ phân loại cục bộ, KHÔNG trích
    tham số) chỉ để lọc ý-định-khác, rồi NHÉT NGUYÊN VĂN `command_text` làm
    giá trị slot. Hậu quả: người dùng trả lời "Tôi muốn nghe bài Nơi này có
    anh" thì `song_title` = CẢ CÂU, không phải tên bài sạch "Nơi này có anh".
    `detect_with_params(..., pending=...)` (B3, `pipeline/intent.py`, T05) đã
    có sẵn từ T05 nhưng CHƯA TỪNG được gọi từ đây cho tới bản sửa này — T05 và
    T06 độc lập phát hiện gap này (xem `docs/tasks/reports/T05.md`, `T06.md`
    mục "Lệch với task file"). Giờ nối vào: dùng TRÍCH XUẤT THẬT của Gemini
    (có khối hỏi-gì trong prompt) thay vì nhét thô, và unrelated-intent check
    cũng chính xác hơn (Gemini thấy cả ngữ cảnh, không chỉ nhãn cục bộ rẻ).
    """
    text = (command_text or "").strip()
    if not text:
        return None

    resolved, params = intent_mod.detect_with_params(text, state, pending=pending)

    if (
        resolved is not None
        and resolved != pending.intent
        and resolved not in (Intent.CHAT, Intent.UNKNOWN)
    ):
        return None

    known = dict(pending.known)
    known.update(params)
    value = known.get(pending.slot)
    if value is None or not _validate_slot(pending.slot, value):
        return None

    return _dispatch(pending.intent, image, command_text, known)


def _try_global_cancel_repeat(command_text: str, action_flow) -> str | None:
    """Pha 5 (21.1) — CANCEL / REPEAT TOÀN CỤC, chỉ xét khi KHÔNG có pending
    nào đang mở (pending có "thôi"/"nói lại" của riêng nó ở pha 2, mang nghĩa
    khác: huỷ CÂU HỎI đang chờ, không phải huỷ một tác vụ/nhắc lại câu vừa
    nói). `None` nếu câu không khớp — để bước 6 (INTENT DETECT) xử lý."""
    text = command_text or ""
    if _GLOBAL_REPEAT.search(text):
        history = action_flow.recent_history()
        return history[-1][1] if history else _NOTHING_TO_REPEAT
    if _GLOBAL_CANCEL.search(text):
        return _NOTHING_TO_CANCEL
    return None


def _resolve(
    image: bytes | None, audio: bytes, device_key: str | None = None
) -> Iterator[str]:
    # Nhập trễ (không phải đầu file): `handlers.action_flow` transitively kéo
    # theo `handlers.music`/`handlers.navigation`/`handlers.phone`, và bản
    # thân module này (`pipeline.router`) đã import các module đó ở trên rồi
    # — an toàn — nhưng giữ kiểu nhập trễ đúng như code T01/T03 để lại
    # (tránh phải suy luận lại toàn bộ đồ thị import mỗi lần một file trong
    # chuỗi này đổi thứ tự `import`).
    from handlers import action_flow

    # `device_key` PHẢI được `resolve_speech()` chụp sẵn và truyền vào —
    # KHÔNG được để hàm này tự đọc ambient context, vì chính THÂN HÀM NÀY có
    # thể chạy trên một thread trần không kế thừa ContextVar (xem
    # `_capture_device_key()`). Nhánh `is None` dưới đây CHỈ để test/script
    # gọi thẳng `_resolve()` (2 tham số, không qua `resolve_speech()`) không
    # bị vỡ chữ ký — trong sản xuất, `resolve_speech()` LUÔN truyền tường minh.
    if device_key is None:
        device_key = _capture_device_key()

    # G2/G4: ranh giới "một lượt MỚI bắt đầu" THẬT SỰ — trước T04, generation
    # chỉ tăng GIỮA lượt (bên trong `run_action()`/`set_pending()`, xem mục
    # deferred ở docs/tasks/reports/T03.md). Bump ở ĐÂY, TRƯỚC bất cứ bước nào
    # khác, vì "lượt mới tới" (kể cả lượt sẽ resolve thành `chat`/`ocr` không
    # hề gọi `run_action()`) là chính xác cái sự kiện phải huỷ MỌI lượt cũ
    # đang chạy dở của CÙNG thiết bị — không đợi tới lúc handler tự bump.
    #
    # Hai điểm bump GIỮA lượt cũ (`run_action()`, `set_pending()`) CỐ Ý ĐƯỢC
    # GIỮ NGUYÊN, không xoá/dời: xoá đòi sửa `handlers/action_flow.py` (ngoài
    # "FILE BẠN ĐƯỢC SỬA" của T04). `run_action()` vô hại với thiết kế ở đây:
    # mọi nơi CHỤP `generation` để so sánh sau này (`_with_bargein`) đều chụp
    # SAU khi mảnh đầu của handler đã được kéo — tức là SAU khi bump giữa lượt
    # của `run_action()` (nếu handler gọi tới) đã xảy ra — nên nó không gây
    # huỷ nhầm (false positive) lượt đang chạy. `set_pending()` KHÔNG có lời
    # gọi thật nào trong `handlers/`/`pipeline/` tính tới T04 — đây là một
    # RÀNG BUỘC cho người viết handler sau này (T06), không phải một tính chất
    # tự động của cơ chế: xem docstring `_with_bargein()` và
    # docs/tasks/reports/T04.md mục "generation phải bump TRƯỚC mảnh đầu".
    action_flow.bump_generation(device_key)

    started = time.monotonic()
    command_text = stt.transcribe(audio)
    stt_seconds = time.monotonic() - started

    # ─── 1. EMERGENCY (21.1) — tuyệt đối, không qua bước nào khác ─────────
    if _LOCAL_EMERGENCY.search(command_text or ""):
        logger.info(
            "nghe='%s' -> EMERGENCY (bước 1/6, cổng từ khoá cục bộ, bỏ qua "
            "pending/stop/slot/Gemini) | stt=%.2fs",
            command_text, stt_seconds,
        )
        first, rest = _with_bargein(
            _dispatch(Intent.EMERGENCY_CALL, image, command_text, {}),
            action_flow, device_key,
        )
        if first:
            yield first
        yield from rest
        return

    state = action_flow.device_state()
    pending = action_flow.get_pending()

    # ─── 2. PENDING TẤT ĐỊNH (21.1) ────────────────────────────────────────
    if pending is not None:
        deterministic = _resolve_deterministic_pending(
            pending, image, command_text, action_flow
        )
        if deterministic is not None:
            logger.info(
                "nghe='%s' -> PENDING tất định (bước 2/6, slot=%s kind=%s)",
                command_text, pending.slot, pending.kind,
            )
            first, rest = _with_bargein(deterministic, action_flow, device_key)
            if first:
                yield first
            yield from rest
            return

    # ─── 3. STOP / LỆNH TOÀN CỤC (21.1) — chèn GIỮA hai pha pending ────────
    stop_target = _global_stop_target(command_text, state)
    if stop_target is not None:
        logger.info(
            "nghe='%s' -> STOP cục bộ (bước 3/6, %s), bỏ qua Gemini intent",
            command_text, stop_target,
        )
        # Nguyên tắc 1 (CONTRACTS mục 0): một lệnh STOP rõ ràng thắng bất kỳ
        # pending fill nào đang treo (đây chính là ca vỡ 21.1) — bỏ pending
        # luôn, không để nó sống sót sang lượt sau chờ đúng slot cũ.
        action_flow.clear_pending()
        first, rest = _with_bargein(
            _dispatch(stop_target, image, command_text), action_flow, device_key
        )
        if first:
            yield first
        yield from rest
        return

    # ─── 4. PENDING ĐIỀN SLOT (21.1) — qua slot validator ──────────────────
    if pending is not None and pending.kind == "fill":
        filled = _try_fill_pending_slot(pending, image, command_text, state)
        if filled is not None:
            action_flow.clear_pending()
            logger.info(
                "nghe='%s' -> PENDING điền slot (bước 4/6, slot=%s)",
                command_text, pending.slot,
            )
            first, rest = _with_bargein(filled, action_flow, device_key)
            if first:
                yield first
            yield from rest
            return
        # Không lấp được: bỏ pending, KHÔNG mang nó sang lượt sau — nguyên tắc
        # 1 (CONTRACTS mục 0): trạng thái/pending là gợi ý, không phải hàng
        # rào, câu tiếp theo được xử lý lại HOÀN TOÀN mới ở bước 6.
        action_flow.clear_pending()

    # ─── 5. CANCEL / REPEAT (21.1) — toàn cục, không có pending ────────────
    global_reply = _try_global_cancel_repeat(command_text, action_flow)
    if global_reply is not None:
        logger.info("nghe='%s' -> CANCEL/REPEAT toàn cục (bước 5/6)", command_text)
        yield global_reply
        return

    # ─── 6. INTENT DETECT (21.1) — như cũ, qua bộ phân loại cục bộ/Gemini ──
    intent_started = time.monotonic()
    res = intent_mod.detect_with_params(command_text, state)
    # Đo riêng, không gộp vào `handler`: đây là một lượt gọi Gemini TRỌN VẸN nằm
    # nối tiếp giữa STT và handler, và người dùng chờ hết nó trước khi công việc
    # thật bắt đầu. Gộp vào chỗ khác thì không ai thấy nó tốn bao nhiêu.
    intent_seconds = time.monotonic() - intent_started
    if isinstance(res, tuple):
        intent_name, params = res
    else:
        intent_name, params = res, {}

    if intent_name == Intent.UNKNOWN:
        # `unknown` không còn là kết quả phân loại — nó chỉ còn là trạng thái
        # LỖI, và hai lỗi này người dùng phải xử lý theo hai cách khác nhau:
        # không nghe ra chữ nào thì nói to hơn / gần mic hơn, còn hệ thống bận
        # thì chỉ cần thử lại, không phải nói khác đi.
        logger.info(
            "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs handler=0.00s",
            command_text, intent_name, stt_seconds, intent_seconds,
        )
        yield _CLASSIFY_FAILED_MESSAGE if params.get("classify_failed") else _NO_SPEECH_MESSAGE
        return

    # Chất lượng ảnh chỉ xét được khi đã biết câu hỏi cần gì ở ảnh. Đặt trước
    # gate này thì "gọi cho mẹ" bị một tấm ảnh xấu chặn mất, dù handler gọi
    # điện không hề mở ảnh ra xem.
    reject_reason = image_quality.reject_reason(intent_name, image)
    if reject_reason is not None:
        logger.info(
            "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs -> từ chối ảnh",
            command_text, intent_name, stt_seconds, intent_seconds,
        )
        yield reject_reason
        return

    handler_started = time.monotonic()
    pieces = _dispatch(intent_name, image, command_text, params)

    first, rest = _with_bargein(pieces, action_flow, device_key)
    # handler đo tới MẢNH ĐẦU, không phải tới lúc Gemini viết xong
    logger.info(
        "nghe='%s' intent=%s | stt=%.2fs phân-loại=%.2fs handler=%.2fs",
        command_text, intent_name, stt_seconds, intent_seconds,
        time.monotonic() - handler_started,
    )

    if first:
        yield first
    yield from rest
