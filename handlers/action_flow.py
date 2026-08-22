"""Luồng chung cho 9 action điều khiển điện thoại qua VisionCare Host."""

from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
import logging
import threading
import time
import uuid

import config
from pipeline import tts
from handlers import result_speech, slots as slot_policy
from handlers.waiting import wait_for
from services.visioncare_client import (
    VisionCareAPIError,
    call_service_api,
    get_request_status,
)
from services.action_callbacks import action_callbacks

logger = logging.getLogger("blind_assist")

# Câu trấn an mặc định, phát xoay vòng. Lặp đúng một câu bốn lần liền nghe như
# máy bị kẹt, nên danh sách quay vòng để mỗi lần chờ nghe khác nhau. Nhịp đẩy
# câu do `waiting.notice_delays()` quyết định — xem `config.py` để biết vì sao
# nó giãn dần thay vì đều đặn.
#
# Không câu nào được lặp lại ý câu chào ("hệ thống đang xử lý") — người dùng vừa
# nghe nó vài giây trước, nghe lại thì tưởng máy phát lại chứ không phải đang
# chạy tiếp. Mỗi câu ở đây nói một điều CỤ THỂ hơn câu chào: đang chờ ai, chờ
# tới đâu rồi.
_DEFAULT_PROGRESS = (
    "Vẫn đang chờ điện thoại phản hồi.",
    "Sắp xong rồi, bạn chờ thêm chút nữa.",
    "Điện thoại chưa báo về, nhưng chưa có gì bất thường.",
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = _DEFAULT_PROGRESS

# Dấu báo "câu này đã trọn vẹn, đọc ngay đi" cho `tts._sentences()`.
#
# Cần vì luồng text ở đây khác hẳn luồng của Gemini. Gemini đẩy ra từng mảnh
# vụn cách nhau vài chục mili giây, nên gom chờ mảnh sau là đúng. Còn ở đây mỗi
# lần `yield` là một câu trọn vẹn, và mảnh kế tiếp có thể cả chục giây nữa mới
# tới. Không có dấu này thì "Đang gọi xe." nằm im trong buffer tới lúc câu trấn
# an đầu tiên xuất hiện, rồi hai câu bung ra một lượt — nghe thành im lặng một
# lúc rồi nói dồn, đúng triệu chứng đo được lúc chạy thật.
_UTTERANCE_END = "\n"


def _utterance(text: str) -> str:
    return text.rstrip() + _UTTERANCE_END

# Id do điện thoại sinh ra ở lần gọi trước, cần cho lệnh tiếp theo:
# `navigation_stop` phải mang đúng `navigation_id` của `navigation_start`, và
# `ride_confirm` phải mang đúng `quote_id` của `ride_quote`. Hardcode như trước
# ("nav-123"/"quote-123") thì host luôn trả NOT_FOUND.
#
# Dict trong bộ nhớ tiến trình là đủ cho demo một kính một máy; nhiều kính thì
# phải khoá theo `device_id`.
#
# --- T03 (docs/tasks/T03-session-pending.md, mục B6) ------------------------
# Đã khoá theo `device_id`: nội dung dict này giờ nằm ở `Session.last_ids`
# (một dict con trong `_SESSIONS[device_id]`), không còn là một dict toàn cục
# duy nhất. Đoạn comment trên GIỮ NGUYÊN vì vẫn đúng nghĩa — chỉ đổi chỗ chứa.
_REMEMBER_KEYS = {
    "navigation_start": "navigation_id",
    "ride_quote": "quote_id",
}

# Việc gì đang CHẠY trên điện thoại -> lúc nó bắt đầu (`time.monotonic()`).
#
# Khác `_LAST_IDS` ở mục đích: `_LAST_IDS` giữ id để gửi kèm lệnh sau, còn cái
# này trả lời câu hỏi "lúc này cái gì đang chạy" để gỡ mơ hồ cho bộ phân loại ý
# định. "Tắt đi", "dừng lại", "thôi đủ rồi" không tự nó cho biết tắt cái gì —
# đây là cặp nhãn lẫn nhau nhiều nhất khi đo trên bộ câu huấn luyện, và không
# chữa được bằng thêm dữ liệu vì chính người nghe cũng không phân biệt nổi nếu
# không biết cái gì đang chạy.
#
# Giữ mốc thời gian chứ không phải cờ bật/tắt: khi cả nhạc lẫn chỉ đường cùng
# chạy thì phải chọn được cái vừa bật gần đây nhất, thay vì chọn bừa một cái.
#
# BIẾT TRƯỚC MỘT CHỖ HỞ: host không báo về khi bài hát tự hết, nên `music_playing`
# vẫn bật sau khi nhạc đã tắt tự nhiên. Hậu quả nhẹ và không đối xứng nên chấp
# nhận được: "tắt đi" lúc đó ra `music_stop`, handler gửi lệnh dừng một thứ đã
# dừng và host trả lời bình thường. Ngược lại — đoán thành `nav_stop` khi người
# dùng đang muốn tắt nhạc — mới là cái phải tránh. Sửa được khi host đẩy sự kiện
# "hết bài" về; đừng thay bằng TTL đoán mò, vì không có con số nào đúng cho mọi
# bài hát.
#
# --- T03 --------------------------------------------------------------------
# Đoạn trên GIỮ NGUYÊN byte-for-byte (task file `T03-session-pending.md` mục
# "Hai chỗ không đụng" yêu cầu vậy — chỗ hở này ĐÃ ĐO, ĐÃ CHẤP NHẬN, cấm thay
# bằng TTL đoán mò). Nội dung dict giờ nằm ở `Session.active`, khoá theo
# `device_id`, KHÔNG còn là dict toàn cục `_ACTIVE` — xem `Session` bên dưới.
# Chỗ hở "bài tự hết" ở trên áp dụng y hệt cho `Session.active`: không có
# TTL nào được thêm ở đây để "sửa" nó.
_STARTS = {"music_play": "music_playing", "navigation_start": "navigating"}
_ENDS = {"music_stop": "music_playing", "navigation_stop": "navigating"}


# ─── T03 — Pending & Session theo device_id ────────────────────────────────
#
# docs/tasks/T03-session-pending.md, docs/tasks/CONTRACTS.md mục 4.
#
# G2 (thiết kế tại T03, T21 sẽ dùng): lock chỉ bao đọc/ghi state trong bộ nhớ
# (micro giây) — KHÔNG bao giờ giữ lock lúc gọi mạng (Gemini, VisionCare host).
# `run_action()` ở dưới tuân theo: `_SESSIONS_LOCK` chỉ chạm dict, còn
# `call_service_api`/`get_request_status`/`wait_for` luôn chạy ngoài lock.
_SESSIONS_LOCK = threading.Lock()

# Khoá dùng khi không có request nào đang chạy (gọi thẳng hàm trong test/script,
# hoặc một handler ngoài phạm vi sửa của T03 — xem `_device_key()`). Giữ đúng
# hành vi CŨ (một trạng thái toàn cục duy nhất) cho những chỗ gọi đó.
_NO_DEVICE_CONTEXT_KEY = "_no_device_ctx"

# TTL theo `kind` — ĐÃ CHỐT ở CONTRACTS.md mục 4.1 / T03-session-pending.md mục
# 21.3. KHÔNG tự đổi ở đây; đổi thì phải sửa CONTRACTS.md trước (AGENT_RULES
# mục B2 — file đó không thuộc quyền sửa của task này).
_TTL_BY_KIND = {
    "confirm": config.PENDING_TTL_CONFIRM_SECONDS,
    "select": config.PENDING_TTL_SELECT_SECONDS,
    "fill": config.PENDING_TTL_FILL_SECONDS,
}


def _ttl_for_kind(kind: str) -> float:
    """TTL (giây) cho một `kind` pending. `kind` lạ rơi về TTL `fill` (dài nhất,
    ít nguy hiểm nhất khi đoán sai) thay vì lỗi cứng — pending vẫn phải có TTL
    kể cả khi một handler tương lai gõ nhầm tên `kind`."""
    return _TTL_BY_KIND.get(kind, config.PENDING_TTL_FILL_SECONDS)


def _estimate_speech_seconds(text: str) -> float:
    """ƯỚC LƯỢNG số giây TTS đọc xong `text`.

    21.3: `asked_at` phải tính từ lúc TTS phát xong câu hỏi, không phải lúc
    server tạo pending — chênh 1-3 giây, với `confirm` (TTL 25s) là hơn 10%
    ngân sách. Đường phát audio thật (`pipeline/tts.py`, `app.py`) không có
    hook gọi ngược về `handlers/action_flow.py`, và cả hai file đó đều NẰM
    NGOÀI danh sách "FILE BẠN ĐƯỢC SỬA" của T03 — không thêm hook được ở lượt
    này. Đây là phương án ước lượng task file cho phép dùng khi chưa có hook,
    với điều kiện ghi rõ đây là ước lượng.

    CHƯA ĐO trên giọng TTS đang dùng (AGENT_RULES mục A9: "có bảng số thì mới
    được chốt" — chưa có bảng đo thì phải ghi "chưa đo", không copy số của cấu
    hình khác). `config.PENDING_ASKED_AT_ESTIMATE_CHARS_PER_SECOND` là phỏng
    đoán hợp lý (tốc độ đọc tự nhiên), KHÔNG phải kết quả đo.
    """
    if not text:
        return 0.0
    rate = config.PENDING_ASKED_AT_ESTIMATE_CHARS_PER_SECOND
    if rate <= 0:
        return 0.0
    return len(text) / rate


@dataclass
class Pending:
    """Một câu hỏi đang chờ người dùng trả lời (B2).

    `kind` quyết định TTL mặc định qua `_ttl_for_kind()` — không phải một con
    số cố định cho mọi slot (21.3: "không 90s cho mọi slot").
    """

    slot: str  # "contact_name" | "destination" | "song_title" | ...
    intent: str  # intent chạy lại khi có câu trả lời
    known: dict  # params đã thu được
    question: str  # nguyên văn câu vừa hỏi (dùng cho "nói lại đi")
    candidates: list  # ứng viên danh bạ / dịch vụ xe, nếu có
    asked_at: float
    attempt: int = 0  # 21.2
    max_attempt: int = 2  # 21.2
    ttl: float = 120.0  # 21.3
    kind: str = "fill"  # "fill" | "confirm" | "select"

    def is_expired(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return (now - self.asked_at) > self.ttl

    def over_max_attempt(self) -> bool:
        """21.2: vượt `max_attempt` thì đổi chiến lược, không hỏi lại nguyên
        văn `question` nữa. Câu thay thế thuộc handler gọi hàm này (T04/T06),
        T03 chỉ cung cấp điểm quyết định."""
        return self.attempt > self.max_attempt


@dataclass
class Session:
    """Toàn bộ trạng thái của MỘT thiết bị (B6).

    `device_id` đọc từ `app.DEVICE_ID_CTX` (ContextVar của T01), KHÔNG từ
    `config.VISIONCARE_DEVICE_ID` — xem `_device_key()`.
    """

    last_ids: dict = field(default_factory=dict)
    active: dict = field(default_factory=dict)
    pending: "Pending | None" = None
    history: deque = field(
        default_factory=lambda: deque(maxlen=config.CHAT_HISTORY_TURNS)
    )
    last_ocr: dict | None = None  # T14/E2 — chưa dùng ở T03
    contacts: list | None = None  # T08/P1 — chưa dùng ở T03
    # G2: mỗi device một generation counter. Lượt mới -> tăng generation ->
    # lượt cũ (đang chạy dở, ví dụ đang poll VisionCare host trong
    # `run_action`) thấy generation đọc lại lệch với generation lúc nó bắt đầu
    # thì tự huỷ thay vì tiếp tục nói/ghi đè. T04 (barge-in) sẽ là nơi ĐỌC và
    # SO SÁNH generation — T03 chỉ đảm bảo con số này tồn tại và tăng đúng lúc
    # ngay từ bây giờ, vì thêm field này sau khi mọi chỗ tạo/đọc pending đã
    # thành hình sẽ đắt hơn nhiều (phải sửa lại từng chỗ).
    generation: int = 0
    last_seen: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, Session] = {}


def _device_key() -> str:
    """`device_id` của request đang chạy, đọc từ ContextVar T01.

    Import `app` LAZY (bên trong hàm), không phải ở đầu file: `app.py` nạp
    `pipeline.router` ở mức module, và `router` nạp `handlers.music`/
    `handlers.navigation` (cũng ở mức module), hai module đó lại `from
    handlers.action_flow import ...` — nếu `action_flow.py` cũng `import app`
    ngay ở đầu file thì lúc `app.py` CHƯA nạp xong (đang giữa chừng import
    `pipeline.router`) mà quay lại cần `app`, `app` sẽ chỉ mới nạp được một
    phần -> lỗi vòng lặp import. Import bên trong hàm này chỉ chạy lúc hàm
    được GỌI (lúc xử lý request thật, hoặc trong test gọi thẳng), tại thời
    điểm đó `app.py` chắc chắn đã nạp xong dù nạp theo chiều nào trước.

    Không có request nào đang chạy (test gọi thẳng hàm, hoặc một handler nằm
    NGOÀI danh sách "FILE BẠN ĐƯỢC SỬA" của T03 nên chưa từng set ContextVar)
    -> `DEVICE_ID_CTX.get()` trả `None` -> dùng `_NO_DEVICE_CONTEXT_KEY`, một
    khoá cố định tương đương "một session ngầm định duy nhất" — giữ đúng hành
    vi CŨ (state toàn cục) cho những chỗ gọi đó, không phá test/handler đang
    chạy tốt mà T03 không được phép sửa (AGENT_RULES mục B3).
    """
    try:
        import app as _app_module
    except ImportError:
        return _NO_DEVICE_CONTEXT_KEY
    device_id = _app_module.DEVICE_ID_CTX.get()
    return device_id or _NO_DEVICE_CONTEXT_KEY


def _get_session(device_key: str | None = None) -> Session:
    """Session của thiết bị `device_key`, hoặc của thiết bị hiện tại (đọc từ
    ambient ContextVar qua `_device_key()`) nếu không truyền gì. Tạo mới nếu
    chưa có. PHẢI gọi trong khi giữ `_SESSIONS_LOCK`, hoặc dùng nguyên hàm này
    (nó tự khoá).

    Truyền `device_key` TƯỜNG MINH khi gọi từ một closure/callback có thể
    được GỌI trên một luồng/request khác với lúc nó được ĐĂNG KÝ — ambient
    context (`_device_key()`) lúc gọi khi đó không còn đúng nữa. Xem
    `note_result()` để biết vì sao đây là bug thật đã xảy ra: callback đăng ký
    trong `run_action()` (đang ở trong request `/process` thật, có
    `DEVICE_ID_CTX` đúng) bị GỌI LẠI từ `POST /internal/action-results` (một
    request HOÀN TOÀN KHÁC, không có `DEVICE_ID_CTX`) hoặc từ luồng nền
    `reconcile_late` (`threading.Thread` mới không kế thừa Context của luồng
    tạo ra nó) — cả hai đọc `_device_key()` ambient ra `_NO_DEVICE_CONTEXT_KEY`
    thay vì thiết bị thật.
    """
    key = device_key if device_key is not None else _device_key()
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            _maybe_gc_idle_sessions_locked()
            session = Session()
            _SESSIONS[key] = session
        session.last_seen = time.monotonic()
        return session


_LAST_GC_AT = 0.0
_GC_SWEEP_INTERVAL_SECONDS = 300.0  # không quét mỗi lần tạo session mới, tốn CPU vô ích


def _maybe_gc_idle_sessions_locked(now: float | None = None) -> None:
    """Dọn session không hoạt động quá `config.SESSION_IDLE_GC_SECONDS`, chạy
    thưa (mỗi `_GC_SWEEP_INTERVAL_SECONDS`) mỗi khi có thiết bị MỚI xuất hiện.
    PHẢI gọi trong khi đã giữ `_SESSIONS_LOCK` (không tự khoá lại)."""
    global _LAST_GC_AT
    now = time.monotonic() if now is None else now
    if now - _LAST_GC_AT < _GC_SWEEP_INTERVAL_SECONDS:
        return
    _LAST_GC_AT = now
    idle_after = config.SESSION_IDLE_GC_SECONDS
    stale = [k for k, s in _SESSIONS.items() if now - s.last_seen > idle_after]
    for k in stale:
        del _SESSIONS[k]
    if stale:
        logger.info("Dọn %d session không hoạt động > %.0fs", len(stale), idle_after)


def gc_idle_sessions(now: float | None = None) -> int:
    """Xoá ngay session của thiết bị không hoạt động quá
    `config.SESSION_IDLE_GC_SECONDS`. Trả về số session đã xoá.

    Đề xuất "24 giờ" ở T03-session-pending.md mục 6 câu 2 — KHÔNG phải câu hỏi
    🔴 chặn trong CONTRACTS.md mục 7 (chỉ câu #9, cache vị trí, mới thật sự
    chặn task này), nên áp dụng luôn thay vì để trống.

    Hàm công khai này dọn NGAY (không chờ nhịp thưa như
    `_maybe_gc_idle_sessions_locked`) — dùng trong test, và để một task sau có
    thể gắn vào một job định kỳ nếu cần dọn chủ động thay vì chỉ dọn cơ hội lúc
    có thiết bị mới.
    """
    now = time.monotonic() if now is None else now
    idle_after = config.SESSION_IDLE_GC_SECONDS
    removed = 0
    with _SESSIONS_LOCK:
        stale = [k for k, s in _SESSIONS.items() if now - s.last_seen > idle_after]
        for k in stale:
            del _SESSIONS[k]
            removed += 1
    return removed


def bump_generation(device_key: str | None = None) -> int:
    """Tăng `generation` của session hiện tại, trả về giá trị MỚI (G2).

    Tăng ở hai điểm T03 sở hữu — cả hai đều là ranh giới "một lượt mới bắt
    đầu" theo đúng phạm vi module này: lúc `run_action()` bắt đầu một lệnh gọi
    điện thoại mới, và lúc `set_pending()` tạo một pending mới. T04 (barge-in)
    là nơi ĐỌC generation này để tự huỷ lượt cũ khi phát hiện lệch.

    `device_key`: xem `_get_session()` — truyền TƯỜNG MINH khi gọi từ một nơi
    có thể chạy trên một luồng KHÔNG kế thừa `contextvars.Context` của luồng
    đã có `X-Device-Id` đúng (T04/`pipeline/router.py`: `with_progress_notice`
    kéo mảnh đầu trên một `threading.Thread` trần — xem
    `docs/tasks/reports/T04.md` mục sửa lỗi barge-in server-global). Mặc định
    `None` giữ nguyên hành vi ambient cũ (`_device_key()`) cho mọi lời gọi
    đồng bộ hiện có trong `run_action()`/`set_pending()`.
    """
    session = _get_session(device_key)
    with _SESSIONS_LOCK:
        session.generation += 1
        return session.generation


def current_generation(device_key: str | None = None) -> int:
    """`generation` hiện tại của session — xem `bump_generation()` để biết vì
    sao `device_key` tường minh cần thiết cho T04 (barge-in qua thread trần)."""
    session = _get_session(device_key)
    with _SESSIONS_LOCK:
        return session.generation


def remember(key: str, value: str, device_key: str | None = None) -> None:
    """Ghi lại một giá trị cho lượt nói tiếp theo (điểm đến đang chờ xác nhận).

    `device_key`: xem `_get_session()` — truyền tường minh khi gọi từ một
    callback có thể chạy ngoài request/luồng đã đăng ký nó (`note_result()`).
    """
    session = _get_session(device_key)
    with _SESSIONS_LOCK:
        session.last_ids[key] = value


def recall(key: str) -> str | None:
    """Id gần nhất đã nhận được cho `key` (`navigation_id`, `quote_id`)."""
    session = _get_session()
    with _SESSIONS_LOCK:
        return session.last_ids.get(key)


def forget(key: str) -> None:
    """Xoá id sau khi nó đã được dùng xong (chuyến đã hủy, lộ trình đã dừng)."""
    session = _get_session()
    with _SESSIONS_LOCK:
        session.last_ids.pop(key, None)


def device_state() -> dict:
    """Cái gì đang chạy trên điện thoại lúc này.

    Dùng cho bước phân loại ý định, không phải để hiển thị. `most_recent` là
    việc vừa bật gần đây nhất trong số đang chạy — chỗ dựa duy nhất khi cả nhạc
    lẫn chỉ đường cùng chạy và người dùng chỉ nói "tắt đi".
    """
    session = _get_session()
    with _SESSIONS_LOCK:
        running = sorted(session.active.items(), key=lambda kv: kv[1])
        return {
            "music_playing": "music_playing" in session.active,
            "navigating": "navigating" in session.active,
            "ride_quote_pending": "quote_id" in session.last_ids,
            "most_recent": running[-1][0] if running else None,
        }


def reset_state() -> None:
    """Xoá sạch MỌI session (mọi thiết bị). Dùng trong test và khi khởi động."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


def mark_active(task: str, device_key: str | None = None) -> None:
    """Đánh dấu tác vụ `task` ('music_playing' hoặc 'navigating') đang hoạt động.

    B7 (T03): KHÔNG còn tắt các tác vụ khác trước khi bật tác vụ này ("Single
    Active State" cũ, từng gọi `_ACTIVE.clear()` ở đây trước khi set). Sai
    thực tế: đi bộ nghe nhạc vừa được chỉ đường là một ca dùng thật, và cách cũ
    khiến bật chỉ đường lặng lẽ tắt nhạc dù người dùng không hề nói tắt nhạc.
    Nhạc và chỉ đường giờ chạy song song được — `device_state()` báo cả hai,
    và bên gọi (router/intent) tự quyết định "tắt đi" nghĩa là tắt cái nào qua
    `most_recent`.

    `device_key`: xem `_get_session()` — truyền tường minh khi gọi từ một
    callback có thể chạy ngoài request/luồng đã đăng ký nó (`note_result()`).
    """
    session = _get_session(device_key)
    with _SESSIONS_LOCK:
        session.active[task] = time.monotonic()


def mark_inactive(task: str | None = None, device_key: str | None = None) -> None:
    """Xóa tác vụ đang hoạt động."""
    session = _get_session(device_key)
    with _SESSIONS_LOCK:
        if task:
            session.active.pop(task, None)
        else:
            session.active.clear()


def note_result(
    operation: str, data: dict | None, device_key: str | None = None
) -> None:
    """Cập nhật id và trạng thái đang chạy từ kết quả thật của một action.

    `device_key`: THIẾT BỊ mà kết quả này thuộc về. **BẮT BUỘC truyền tường
    minh** khi gọi hàm này từ một callback đã đăng ký ở `run_action()` — hàm
    này chạy ở HAI nơi không có `X-Device-Id` nào trong ContextVar tại thời
    điểm gọi:

    1. `POST /internal/action-results` (`app.py`) — một request HOÀN TOÀN
       KHÁC với request `/process` đã tạo ra action; endpoint đó không đụng
       tới `DEVICE_ID_CTX`.
    2. `reconcile_late()` (`threading.Thread` mới ở cuối `run_action()`) —
       một luồng mới không kế thừa `contextvars.Context` của luồng tạo ra nó.

    Ở cả hai chỗ, đọc ambient context (`_device_key()`, hành vi khi
    `device_key=None`) sẽ luôn ra `_NO_DEVICE_CONTEXT_KEY` — SAI thiết bị
    (bug thật đã xảy ra: mọi kết quả action bị ghi vào session dùng chung,
    trong khi `recall()`/`device_state()` — gọi từ trong request `/process`
    thật — đọc đúng session của thiết bị. Hai bên không bao giờ gặp nhau:
    `navigation_stop`/`ride_confirm` gửi id rỗng, `device_state()` báo
    `music_playing`/`navigating` sai vĩnh viễn). `run_action()` vì vậy LUÔN
    truyền `device_key` tường minh, chụp lại bằng `_device_key()` ngay trong
    lúc còn ở request context thật, TRƯỚC khi đăng ký callback.

    Mặc định `None` (đọc ambient qua `_get_session()`) chỉ đúng khi gọi hàm
    này trực tiếp, đồng bộ, từ bên trong một request/luồng đã có
    `DEVICE_ID_CTX` đúng (ví dụ test gọi thẳng `note_result(...)`).
    """
    if not data or data.get("request_state") != "succeeded":
        return

    key = _REMEMBER_KEYS.get(operation)
    if key:
        value = (data.get("result") or {}).get(key)
        if value:
            remember(key, value, device_key=device_key)
            logger.info("Nhớ %s=%s từ %s", key, value, operation)

    started = _STARTS.get(operation)
    if started:
        mark_active(started, device_key=device_key)
        logger.info("Bắt đầu: %s", started)
    ended = _ENDS.get(operation)
    if ended:
        session = _get_session(device_key)
        with _SESSIONS_LOCK:
            popped = session.active.pop(ended, None) is not None
        if popped:
            logger.info("Kết thúc: %s", ended)


# ─── T03 — quản lý Pending (B2, 21.2, 21.4) ────────────────────────────────


def set_pending(
    slot: str,
    intent: str,
    known: dict | None,
    question: str,
    candidates: list | None = None,
    kind: str = "fill",
    max_attempt: int = 2,
    ttl: float | None = None,
) -> Pending:
    """Tạo pending mới cho thiết bị hiện tại, THAY pending cũ nếu có.

    21.4 (CONTRACTS quyết định #9): MỘT pending / device, không stack, không
    lồng. `Session.pending` là `Pending | None` (không phải list) nên "chồng"
    không tồn tại được về mặt kiểu — pending mới ghi đè, không append. Assert
    ngay dưới đây kiểm tra invariant đó THẬT SỰ giữ đúng sau khi ghi (không chỉ
    đúng bởi kiểu khai báo), để một sửa đổi sau này (vô tình đổi `pending`
    thành list, hoặc thêm một dict phụ để "xếp hàng" nhiều pending) bị chặn
    ngay tại đây thay vì âm thầm phá luật 21.4.
    """
    now = time.monotonic()
    # 21.3: asked_at ước lượng từ lúc TTS đọc xong `question` — xem
    # `_estimate_speech_seconds()` để biết vì sao đây là ước lượng, không phải
    # số đo qua hook thật.
    asked_at = now + _estimate_speech_seconds(question)
    pending = Pending(
        slot=slot,
        intent=intent,
        known=dict(known or {}),
        question=question,
        candidates=list(candidates or []),
        asked_at=asked_at,
        attempt=0,
        max_attempt=max_attempt,
        kind=kind,
        ttl=ttl if ttl is not None else _ttl_for_kind(kind),
    )
    session = _get_session()
    with _SESSIONS_LOCK:
        session.pending = pending
        session.generation += 1
        after = session.pending

    assert after is pending, (
        "21.4: MỘT pending / device — set_pending() phải THAY session.pending, "
        "không phải xếp thêm vào một chỗ chứa khác."
    )
    assert not isinstance(session.pending, (list, tuple)), (
        "21.4: session.pending phải là MỘT Pending (hoặc None), không phải "
        "danh sách — không được lồng/xếp chồng pending (CONTRACTS quyết định #9)."
    )
    return pending


def get_pending() -> Pending | None:
    """Pending hiện tại của thiết bị, hoặc `None` nếu không có / đã hết hạn.

    Hết hạn thì tự xoá luôn (đọc một lần là dọn), để bên gọi không phải tự nhớ
    gọi `clear_pending()` cho ca hết hạn.
    """
    session = _get_session()
    now = time.monotonic()
    with _SESSIONS_LOCK:
        pending = session.pending
        if pending is not None and pending.is_expired(now):
            session.pending = None
            return None
        return pending


def clear_pending() -> None:
    """Xoá pending hiện tại (luồng đã đi trọn, hoặc bị huỷ bằng lời)."""
    session = _get_session()
    with _SESSIONS_LOCK:
        session.pending = None


def record_pending_attempt() -> int:
    """+1 vào `attempt` của pending hiện tại (21.2). Trả về giá trị MỚI, hoặc 0
    nếu không có pending nào đang chờ."""
    session = _get_session()
    with _SESSIONS_LOCK:
        if session.pending is None:
            return 0
        session.pending.attempt += 1
        return session.pending.attempt


def pending_should_change_strategy() -> bool:
    """True nếu pending hiện tại đã vượt `max_attempt` (21.2) — bên gọi (T04/
    T06) phải đổi chiến lược hỏi, KHÔNG lặp lại `question` nguyên văn nữa."""
    session = _get_session()
    with _SESSIONS_LOCK:
        pending = session.pending
        return pending is not None and pending.over_max_attempt()


# ─── T06/D4 — pending từ mã lỗi host ────────────────────────────────────────
#
# docs/tasks/T06-slot-policy.md mục D4, CONTRACTS.md mục 4.2/5.5.
#
# Trước đây bốn mã lỗi mà host trả về ("không tìm thấy người này",
# "không tìm thấy bài hát", ...) chỉ đọc một câu báo lỗi rồi DỪNG — người dùng
# phải nói lại NGUYÊN CÂU LỆNH từ đầu để thử lại, dù chỉ một từ (tên người,
# tên bài) là sai. `_ERROR_REASK` cho phép `run_action()` đặt một pending
# `fill` ngay tại đây, để lượt kế tiếp chỉ cần MỘT từ là chạy tiếp.
#
# KHÔNG liệt kê tay: lấy trực tiếp từ `result_speech._ERROR_POLICY` (T20) —
# một nguồn duy nhất quyết định "mã nào có nguồn phát thật VÀ đáng hỏi lại",
# tránh hai bảng (một ở đây, một ở T20) trôi khỏi nhau theo thời gian. T20 đã
# viết rõ trong comment của họ: bảng đó CHỈ điền `reask` cho mã đã CHỐT thật
# theo `docs/tasks/measurements/P7-error-matrix.md` — hôm nay là ba mã:
# `CONTACT_NOT_FOUND`, `MULTIPLE_CONTACTS_FOUND` (cả hai -> `contact_name`),
# `SONG_NOT_FOUND` (-> `song_title`).
#
# `INVALID_DESTINATION` CỐ Ý KHÔNG có mặt: P7-error-matrix.md mục 1.2 xác
# nhận app hôm nay KHÔNG kiểm địa điểm nên mã này chưa có nguồn phát thật
# (CONTRACTS mục 7 câu hỏi #7 CHƯA CHỐT) — `result_speech._ERROR_POLICY
# ["INVALID_DESTINATION"].retryable` vì vậy là `False`, và dict-comprehension
# dưới đây tự động bỏ qua nó. Thêm dòng cho mã này vào `_ERROR_REASK` trước
# khi câu hỏi đó được chốt là dựng một đường hỏi lại cho một mã không ai từng
# phát — đúng điều task này được dặn tránh.
_ERROR_REASK: dict[str, tuple[str, str]] = {
    code: policy.reask
    for code, policy in result_speech._ERROR_POLICY.items()
    if policy.retryable and policy.reask is not None
}


def _reask_pending_for_error(operation: str, data: dict | None) -> None:
    """D4: kết quả cuối của action vừa chạy là lỗi có mã nằm trong
    `_ERROR_REASK` -> đặt pending hỏi lại đúng slot, TTL/`kind` lấy từ
    `handlers.slots.SLOTS` (nguồn chính sách duy nhất, T06/D1).

    🔴 Chốt chặn TƯỜNG MINH thứ hai cho nguyên tắc CONTRACTS mục 0 #3
    (`emergency_call` không đi qua bất kỳ bước xác minh nào): loại trừ
    `emergency_call` NGAY TẠI ĐÂY bằng tên, không dựa hoàn toàn vào việc
    `_ERROR_REASK`/`handlers.slots.SLOTS` tình cờ không chứa mã/slot nào của
    nó. Hai lớp phòng thủ độc lập (assert import-time ở `handlers/slots.py`,
    và guard tường minh ở đây) — một lớp bị xoá hay sửa sai thì lớp còn lại
    vẫn chặn được.

    Mã KHÔNG trong `_ERROR_REASK` (terminal, hoặc lạ) -> KHÔNG đặt pending:
    21.7/CONTRACTS quyết định #9 — một pending SAI nuốt mất câu kế tiếp của
    người dùng còn tệ hơn không hỏi lại gì cả.

    `known={}`: KHÔNG mang theo các tham số khác của lượt vừa thất bại (ví dụ
    `volume` đã nói kèm `music_play`). Giữ lại chúng cần ánh xạ tên slot ↔ tên
    tham số của từng handler đích (`song_title` ở đây khác `song` mà
    `handlers/music.py::handle_play` đọc) — việc đó thuộc phạm vi handler sở
    hữu (T12), NGOÀI danh sách file được sửa của T06. Xem
    `docs/tasks/reports/T06.md` mục "Lệch với task file".
    """
    if operation == "emergency_call":
        return
    if not data or data.get("request_state") == "succeeded":
        return
    error = data.get("error") or {}
    code = error.get("code", "")
    reask = _ERROR_REASK.get(code)
    if reask is None:
        return
    slot, intent = reask
    spec = slot_policy.SLOTS.get(slot)
    if spec is None:
        return
    set_pending(
        slot=slot,
        intent=intent,
        known={},
        question=spec.ask,
        kind=spec.kind,
    )


# ─── T03 — lịch sử dùng chung theo device (hạ tầng cho B4) ─────────────────


def record_history_turn(user_text: str, reply_text: str) -> None:
    """Ghi một lượt vào lịch sử của thiết bị hiện tại.

    Đây là HẠ TẦNG cho B4 ("lịch sử dùng chung, ghi cả lượt action") — CHƯA
    nối vào `handlers/chat.py:226` (`_HISTORY`, một deque module-level RIÊNG,
    chỉ ghi lượt `chat`) vì `handlers/chat.py` NẰM NGOÀI danh sách "FILE BẠN
    ĐƯỢC SỬA" của T03 (AGENT_RULES mục B3 — không được sửa dù task file có
    nhắc tới B4). Việc chuyển `chat.py` sang đọc/ghi qua đây, và gọi hàm này từ
    mọi handler (không chỉ `chat`), là việc của một task/agent sau được phép
    sửa `handlers/chat.py`. Xem "Lệch với task file" trong `docs/tasks/reports/T03.md`.
    """
    session = _get_session()
    with _SESSIONS_LOCK:
        session.history.append((user_text, reply_text, time.monotonic()))


def recent_history() -> list[tuple[str, str]]:
    """Lịch sử (câu người dùng, câu trả lời) của thiết bị hiện tại, cũ nhất trước."""
    session = _get_session()
    with _SESSIONS_LOCK:
        return [(user, reply) for user, reply, _ in session.history]


def _await_result(
    request_id: str,
    timeout_seconds: float,
    progress: Sequence[str],
    opening_seconds: float = 0.0,
) -> Iterator[str]:
    """Poll kết quả, xen câu trấn an vào những quãng chờ dài.

    Là generator để vừa nói vừa chờ: `yield` ra câu cần đọc, và `return` kết quả
    cuối (`None` nếu hết giờ) cho người gọi lấy bằng `yield from`.

    `opening_seconds` là độ dài câu xác nhận vừa đọc trước đó — nó cũng là một
    câu trấn an, nên mốc kế tiếp đếm từ lúc nó đọc xong.
    """
    deadline = time.monotonic() + timeout_seconds

    def poll() -> dict | None:
        """Hỏi host tới khi xong hoặc hết giờ. Chạy ở luồng nền của `wait_for`.

        Đặt vòng `sleep` ở đây, không ở luồng chính, chính là điểm mấu chốt:
        trước kia luồng chính ngủ một nhịp poll sau mỗi lần hỏi, nên kết quả vừa
        về vẫn phải nằm chờ tới một giây mới được nói ra. Giờ luồng chính chỉ
        chờ trên hàng đợi và bật dậy ngay khi có kết quả.
        """
        while time.monotonic() < deadline:
            try:
                data = get_request_status(request_id)
            except VisionCareAPIError:
                # Một lần tra hỏng (mạng chớp) không có nghĩa là action hỏng.
                data = {}

            state = data.get("request_state")
            if state and state != "processing":
                logger.info("Request %s finished: %s", request_id, state)
                return data

            time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)

        logger.warning("Request %s vẫn processing sau %.0fs", request_id, timeout_seconds)
        return None

    return (yield from wait_for(poll, progress, opening_seconds))


def run_action(
    operation: str,
    endpoint: str,
    payload: dict,
    ack: str,
    failure: str,
    result_timeout: float | None = None,
    progress: Sequence[str] = _DEFAULT_PROGRESS,
) -> Iterator[str]:
    """Gửi lệnh, đọc câu xác nhận ngay, rồi đọc kết quả thật từ điện thoại.

    Trả nhiều mảnh text chứ không phải một: mảnh đầu phát ngay để người dùng
    biết lệnh đã đi, các mảnh giữa lấp những quãng chờ dài, mảnh cuối là kết quả
    thật. Dừng ở `202` như trước thì "đang gọi cho Em iu" và "chưa gọi được"
    nghe giống hệt nhau — người khiếm thị không có cách nào biết máy có làm gì
    không, và một quãng im lặng 30 giây thì không phân biệt được với hỏng hệ
    thống.
    """
    started = time.monotonic()
    # G2: một lệnh gọi điện thoại mới = một ranh giới "lượt mới" cho generation
    # của device này — xem `bump_generation()`.
    bump_generation()
    # Chụp device_key NGAY TẠI ĐÂY, trong khi còn ở request `/process` thật
    # (có `DEVICE_ID_CTX` đúng) — KHÔNG được đọc lại ambient context lúc
    # callback dưới đây thực sự CHẠY, vì nó chạy từ `POST
    # /internal/action-results` (request khác) hoặc từ luồng nền
    # `reconcile_late` (thread khác), cả hai đều không có `DEVICE_ID_CTX`. Xem
    # docstring `note_result()` để biết đây là bug thật đã xảy ra trước khi
    # sửa: mọi kết quả action bị ghi nhầm vào session dùng chung.
    device_key = _device_key()
    generated_request_id = str(uuid.uuid4())
    request_payload = {**payload, "request_id": generated_request_id}
    action_callbacks.register(
        generated_request_id,
        operation,
        lambda data: note_result(operation, data, device_key=device_key),
        registered_at=started,
    )
    try:
        resp = call_service_api(endpoint, request_payload)
        request_id = resp.get("data", {}).get("request_id", "")
        action_callbacks.move(generated_request_id, request_id)
        logger.info("%s requested, request_id=%s", operation, request_id)
    except VisionCareAPIError as exc:
        logger.error("%s error: %s", operation, exc)
        yield failure
        return
    except Exception:
        logger.exception("%s unexpected error", operation)
        yield failure
        return

    yield _utterance(ack)
    if not request_id:
        return

    # Một GET tức thời là recovery probe cho backend cũ/test; critical path sau
    # đó chỉ ngủ trên Event và được callback đánh thức ngay, không poll 0,5 giây.
    try:
        probe = get_request_status(request_id)
        if probe.get("request_state") not in {None, "processing"}:
            action_callbacks.resolve(request_id, probe)
    except VisionCareAPIError:
        pass

    remaining = config.VISIONCARE_FAST_ACTION_SECONDS - (time.monotonic() - started)
    final = action_callbacks.wait(request_id, remaining)
    if final is not None:
        # T06/D4 + T08/D6: lỗi có nguồn hỏi lại thật -> đặt pending TRƯỚC khi
        # đọc câu báo lỗi và câu hỏi, để lượt kế tiếp của người dùng đã có sẵn
        # `question`/`slot` đúng chờ sẵn. Chạy trong khi vẫn ở
        # request `/process` thật (ambient device context còn đúng) — KHÔNG
        # gọi từ `reconcile_late()`/callback nền, nơi đó không có
        # `DEVICE_ID_CTX` (cùng lớp bug mà `note_result()` đã phải vá, xem
        # docstring hàm đó).
        pieces, pending_speech = result_speech.speak_result(operation, final)
        pending_to_ask = None
        if pending_speech is not None:
            pending_to_ask = set_pending(
                slot=pending_speech.slot,
                intent=pending_speech.intent,
                known=pending_speech.known,
                question=pending_speech.question,
                candidates=pending_speech.candidates,
                kind=pending_speech.kind,
            )
        else:
            before = get_pending()
            _reask_pending_for_error(operation, final)
            after = get_pending()
            if after is not None and after is not before:
                pending_to_ask = after
                pieces = (*pieces, after.question)

        if pending_to_ask is not None:
            # `set_pending()` chỉ biết độ dài `question`. Ở đây người dùng còn
            # nghe câu báo lỗi / danh sách tên TRƯỚC câu hỏi, nên dời asked_at
            # thêm đúng phần đó để TTL thật sự bắt đầu sau khi TTS đọc xong.
            before_question = pieces[:-1] if pieces and pieces[-1] == pending_to_ask.question else pieces
            pending_to_ask.asked_at += sum(
                _estimate_speech_seconds(piece) for piece in before_question
            )
        for piece in pieces:
            yield _utterance(piece)
        return

    # Không hủy action ở mốc SLO. Polling chỉ còn là recovery nền nếu callback
    # bị mất/restart; callback muộn vẫn cập nhật navigation_id/quote_id/state.
    budget = result_timeout if result_timeout is not None else config.VISIONCARE_RESULT_TIMEOUT_SECONDS

    def reconcile_late() -> None:
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            try:
                data = get_request_status(request_id)
            except VisionCareAPIError:
                data = {}
            if data.get("request_state") not in {None, "processing"}:
                action_callbacks.resolve(request_id, data)
                return
            time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)

    threading.Thread(
        target=reconcile_late,
        name=f"action-reconcile-{request_id[:8]}",
        daemon=True,
    ).start()
    yield _utterance("Điện thoại vẫn đang thực hiện, tôi sẽ cập nhật khi có kết quả.")
