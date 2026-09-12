"""T03 — `Pending` (dataclass B2, TTL theo `kind` 21.3, `attempt` 21.2, một
pending / device 21.4).

Xem `docs/tasks/T03-session-pending.md` mục 4.1 cho danh sách 6 ca gốc; tên
test dưới đây khớp nguyên văn.
"""
import time

import pytest

from handlers import action_flow


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def test_pending_expires_by_kind():
    """fill 120s · select 45s · confirm 25s -> mỗi loại hết hạn đúng mốc."""
    now = time.monotonic()

    fill = action_flow.Pending(
        slot="song_title", intent="music_play", known={}, question="q",
        candidates=[], asked_at=now, kind="fill",
        ttl=action_flow._ttl_for_kind("fill"),
    )
    select = action_flow.Pending(
        slot="contact_candidate", intent="contact_call", known={}, question="q",
        candidates=[], asked_at=now, kind="select",
        ttl=action_flow._ttl_for_kind("select"),
    )
    confirm = action_flow.Pending(
        slot="confirm_call", intent="contact_call", known={}, question="q",
        candidates=[], asked_at=now, kind="confirm",
        ttl=action_flow._ttl_for_kind("confirm"),
    )

    assert fill.ttl == 120.0
    assert select.ttl == 45.0
    assert confirm.ttl == 25.0

    # Ngay trước mốc: còn sống. Ngay sau mốc: đã hết hạn.
    assert confirm.is_expired(now + 24.9) is False
    assert confirm.is_expired(now + 25.1) is True
    assert select.is_expired(now + 44.9) is False
    assert select.is_expired(now + 45.1) is True
    assert fill.is_expired(now + 119.9) is False
    assert fill.is_expired(now + 120.1) is True


def test_asked_at_starts_after_tts():
    """`asked_at` > thời điểm server TẠO pending (không phải cùng một mốc) —
    21.3: TTL phải đếm từ lúc TTS đọc XONG câu hỏi, không phải lúc tạo pending.
    """
    before_create = time.monotonic()
    pending = action_flow.set_pending(
        "destination", "navigation_start", {}, "Bạn muốn đi đâu vậy ạ?",
    )
    assert pending.asked_at > before_create


def test_asked_at_estimate_is_documented_as_estimate():
    """Không có hook thật từ đường phát audio (ngoài phạm vi sửa của T03) nên
    `asked_at` phải là MỘT ƯỚC LƯỢNG dựa trên độ dài câu hỏi: câu càng dài thì
    quãng [lúc gọi set_pending, asked_at] càng lớn."""
    before_short = time.monotonic()
    short = action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")
    delay_short = short.asked_at - before_short
    action_flow.clear_pending()

    before_long = time.monotonic()
    long = action_flow.set_pending(
        "song_title", "music_play", {},
        "Bạn muốn nghe bài hát nào, của ca sĩ nào, và có yêu cầu gì thêm không?",
    )
    delay_long = long.asked_at - before_long

    assert delay_long > delay_short


def test_attempt_increments():
    """Ba lượt trả lời sai -> attempt = 3."""
    action_flow.set_pending("contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?")
    action_flow.record_pending_attempt()
    action_flow.record_pending_attempt()
    action_flow.record_pending_attempt()
    assert action_flow.get_pending().attempt == 3


def test_attempt_over_max_changes_strategy():
    """attempt > max_attempt -> KHÔNG trả lại `question` nguyên văn (T03 chỉ
    cung cấp điểm quyết định `pending_should_change_strategy()`; câu thay thế
    thuộc handler gọi vào, ngoài phạm vi T03)."""
    action_flow.set_pending(
        "contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?", max_attempt=2,
    )
    assert action_flow.pending_should_change_strategy() is False

    action_flow.record_pending_attempt()
    action_flow.record_pending_attempt()
    assert action_flow.pending_should_change_strategy() is False  # attempt == max_attempt: vẫn chưa vượt

    action_flow.record_pending_attempt()
    assert action_flow.get_pending().attempt == 3
    assert action_flow.pending_should_change_strategy() is True


def test_only_one_pending_per_device():
    """Đặt pending thứ hai khi pending cũ còn sống -> pending cũ bị THAY,
    KHÔNG stack (21.4 / CONTRACTS quyết định #9)."""
    first = action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")
    second = action_flow.set_pending("destination", "navigation_start", {}, "Đi đâu?")

    current = action_flow.get_pending()
    assert current is second
    assert current is not first
    assert current.slot == "destination"
    # Không có chỗ nào khác giữ pending cũ song song — Session.pending là một
    # giá trị (Pending | None), không phải danh sách.


def test_set_pending_asserts_single_value_invariant():
    """21.4: assert trong CODE (không chỉ test) — `set_pending()` tự kiểm tra
    ngay sau khi ghi rằng `Session.pending` vẫn là một giá trị đơn, không phải
    list/tuple bị lồng."""
    pending = action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")
    session = action_flow._get_session()
    assert session.pending is pending
    assert not isinstance(session.pending, (list, tuple))


def test_pending_cleared_on_success():
    """Luồng đi trọn -> pending biến mất."""
    action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")
    assert action_flow.get_pending() is not None

    action_flow.clear_pending()
    assert action_flow.get_pending() is None


def test_pending_auto_clears_when_read_after_expiry():
    """Đọc một pending đã hết hạn thì coi như không có, và tự dọn luôn (không
    cần bên gọi nhớ `clear_pending()` cho ca hết hạn)."""
    action_flow.set_pending(
        "confirm_call", "contact_call", {}, "Xác nhận gọi cho Mẹ nhé?",
        kind="confirm",
    )
    session = action_flow._get_session()
    session.pending.asked_at = time.monotonic() - 26.0  # quá TTL confirm (25s)

    assert action_flow.get_pending() is None
    assert session.pending is None  # đã tự dọn


def test_generation_increments_when_pending_created():
    before = action_flow.current_generation()
    action_flow.set_pending("song_title", "music_play", {}, "Bài gì?")
    after = action_flow.current_generation()
    assert after > before
