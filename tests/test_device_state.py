"""Trạng thái thiết bị (đang phát nhạc? đang chỉ đường?) và cách nó gỡ mơ hồ.

"Tắt đi", "dừng lại", "thôi đủ rồi" không tự nó cho biết tắt cái gì. Đo trên bộ
câu huấn luyện, đây là cặp lẫn nhau nhiều nhất (`nav_stop` <-> `music_stop`) và
KHÔNG chữa được bằng thêm dữ liệu — chính người nghe cũng không phân biệt được
nếu không biết cái gì đang chạy.

VIẾT LẠI ở T03 (docs/tasks/T03-session-pending.md mục 4.5): "Single Active
State" (B7) BỊ BỎ — nhạc và chỉ đường giờ chạy song song được, ca dùng thật là
đi bộ vừa nghe nhạc vừa được chỉ đường. `test_starting_new_task_clears_
previous_active_task` và `test_single_active_state_mutual_exclusion` của bản
cũ giả định điều NGƯỢC LẠI (bật cái mới tự tắt cái cũ) — đã xoá, thay bằng
`test_music_and_navigation_run_together` và
`test_music_stop_does_not_clear_navigation` (mục 4.3 của task file).

VIẾT LẠI TIẾP ở T04 (docs/tasks/T04-router-bargein.md mục 4.1): hai nhánh
"Fast-Bypass" cũ ở `pipeline/router.py` (nhạc đang phát -> MỌI câu thành tắt
nhạc; chỉ đường đang chạy -> MỌI câu thành dừng chỉ đường) đã BỊ XOÁ hẳn, thay
bằng thứ tự ưu tiên 6 bước (21.1) + barge-in cục bộ (`_LOCAL_STOP`, chỉ chạy
khi có tác vụ đang chạy). `test_router_fast_bypass_music` và
`test_router_fast_bypass_navigation` của bản cũ khoá ĐÚNG hành vi bug đó
("đang nghe nhạc thì không hỏi được gì khác") — đã xoá, thay bằng
`test_music_playing_still_allows_chat`, `test_music_playing_still_allows_emergency`,
`test_navigating_still_allows_hazard`, `test_local_stop_regex_still_fast`,
`test_local_stop_only_when_task_running`, `test_context_template_now_reachable`,
`test_both_running_picks_most_recent` (mục 4.1 của task file T04).

File này KHÔNG set `X-Device-Id`/ContextVar nào — mọi test ở đây chạy trên
"session ngầm định" (`action_flow._NO_DEVICE_CONTEXT_KEY`), giữ đúng hành vi
toàn cục mà các test vốn đã giả định trước T03 (file này không nằm trong danh
sách file được set device context của T03, và các handler nó chạm tới —
`pipeline/router.py`, `handlers/music.py`, `handlers/navigation.py` — cũng
không set context, nên đây là hành vi thật của code khi có handler chưa được
cập nhật để đọc `X-Device-Id`, không phải test giả).
"""
import pytest
from unittest.mock import patch

from handlers import action_flow
from pipeline import intent as intent_mod
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def test_no_activity_by_default():
    state = action_flow.device_state()
    assert state["music_playing"] is False
    assert state["navigating"] is False


def test_music_play_success_marks_music_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    assert action_flow.device_state()["music_playing"] is True


def test_music_play_failure_does_not_mark_playing():
    """Lệnh gửi đi mà điện thoại báo hỏng thì nhạc KHÔNG chạy — đánh dấu là chạy
    sẽ khiến "tắt đi" ngay sau đó bị hiểu thành tắt một thứ không hề bật."""
    action_flow.note_result("music_play", {"request_state": "failed"})
    assert action_flow.device_state()["music_playing"] is False


def test_music_stop_success_clears_music_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result("music_stop", {"request_state": "succeeded"})
    assert action_flow.device_state()["music_playing"] is False


def test_navigation_start_marks_navigating_and_keeps_id():
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )
    assert action_flow.device_state()["navigating"] is True
    assert action_flow.recall("navigation_id") == "nav-9"


def test_navigation_stop_clears_navigating():
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-9"}},
    )
    action_flow.note_result("navigation_stop", {"request_state": "succeeded"})
    assert action_flow.device_state()["navigating"] is False


def test_pending_ride_quote_shows_in_state():
    action_flow.remember("quote_id", "q-1")
    assert action_flow.device_state()["ride_quote_pending"] is True


# ── B7 (T03): nhạc và chỉ đường chạy SONG SONG, không loại trừ nhau ────────


def test_music_and_navigation_run_together():
    """B7: bật tác vụ mới KHÔNG tự tắt tác vụ cũ — đi bộ nghe nhạc vừa được
    chỉ đường là ca dùng thật. `device_state()` phải báo CẢ HAI cùng chạy."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    state = action_flow.device_state()
    assert state["music_playing"] is True
    assert state["navigating"] is True
    assert state["most_recent"] == "navigating"


def test_music_stop_does_not_clear_navigation():
    """Dừng nhạc không đụng tới chỉ đường đang chạy song song."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    action_flow.note_result("music_stop", {"request_state": "succeeded"})

    state = action_flow.device_state()
    assert state["music_playing"] is False
    assert state["navigating"] is True


# ── Trạng thái đi vào prompt phân loại ────────────────────────────────────


def test_prompt_states_nothing_running_when_idle():
    prompt = intent_mod._build_prompt("tắt đi", action_flow.device_state())
    assert "Nhạc: không phát" in prompt
    assert "Chỉ đường: không chạy" in prompt


def test_prompt_tells_model_music_is_playing():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    prompt = intent_mod._build_prompt("tắt đi", action_flow.device_state())
    assert "Nhạc: ĐANG PHÁT" in prompt


def test_prompt_includes_disambiguation_rule():
    """Nói cho model biết trạng thái mà không nói dùng nó thế nào thì vô ích."""
    prompt = intent_mod._build_prompt("dừng lại", action_flow.device_state())
    assert "music_stop" in prompt and "nav_stop" in prompt


def test_detect_passes_state_into_prompt(monkeypatch):
    seen = {}

    def fake_json(prompt, schema=None, model=None):
        seen["prompt"] = prompt
        return {"intent": Intent.MUSIC_STOP, "params": {}}

    monkeypatch.setattr(intent_mod.vlm, "generate_json", fake_json)
    action_flow.note_result("music_play", {"request_state": "succeeded"})

    name, _ = intent_mod.detect_with_params("tắt đi")
    assert name == Intent.MUSIC_STOP
    assert "Nhạc: ĐANG PHÁT" in seen["prompt"]


def test_detect_works_without_state(monkeypatch):
    """Gọi cũ (không truyền state) vẫn phải chạy — router cũ và test cũ dùng nó."""
    monkeypatch.setattr(
        intent_mod.vlm,
        "generate_json",
        lambda prompt, schema=None, model=None: {"intent": Intent.OCR, "params": {}},
    )
    assert intent_mod.detect_with_params("đọc chữ")[0] == Intent.OCR


# ── T04 (docs/tasks/T04-router-bargein.md mục 4.1): bypass đã xoá ──────────
#
# Test dưới đây chạy qua `router.resolve_speech()` THẬT (không tự gọi thẳng
# `action_flow`/`intent_mod`) — đúng tinh thần B1: chứng minh bằng đường THẬT
# mà người dùng đi qua, không phải bằng cách gọi thẳng hàm nội bộ.
#
# Patch đúng module MỎNG mà `pipeline/router.py` thực sự dispatch tới
# (`handlers.music_stop`/`handlers.nav_stop`/`handlers.emergency_call`), không
# phải module gốc (`handlers.music`/`handlers.navigation`/`handlers.phone`):
# `from handlers.music import handle_stop as handle` chép LUÔN giá trị hàm
# vào lúc import, patch module gốc sau đó không đổi được cái tên đã chép — hai
# module `handlers.music_stop.handle`/`handlers.music.handle_stop` là hai cái
# tên KHÁC NHAU cùng trỏ một hàm tại thời điểm import, không phải bí danh động.


def test_music_playing_still_allows_chat():
    """Ca vỡ nặng nhất của bug cũ: nhạc đang phát KHÔNG được nuốt mọi câu
    thành `music_stop`. "mấy giờ rồi" phải ra `chat` bình thường.

    SỬA (phát hiện qua chạy full suite): bản trước KHÔNG mock
    `pipeline.intent.detect_with_params` — bộ phân loại cục bộ bị tắt mặc
    định trong test (`tests/conftest.py::local_intent_disabled`), nên câu này
    rơi thẳng xuống GỌI GEMINI THẬT, một nguồn flaky mạng y hệt loại đã biết ở
    `tests/test_bang_am_thanh.py` (đã thấy đỏ một lần vì Gemini trả UNKNOWN/
    quota). Mock thẳng bước 6 như mọi test router khác trong file này."""
    from pipeline import router

    action_flow.note_result("music_play", {"request_state": "succeeded"})

    with (
        patch("pipeline.stt.transcribe", return_value="mấy giờ rồi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", return_value=iter(["Bây giờ là 10 giờ."])) as mock_chat,
        patch("handlers.music_stop.handle") as mock_stop,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "Bây giờ là 10 giờ."
    mock_chat.assert_called_once()
    mock_stop.assert_not_called()


def test_music_playing_still_allows_emergency():
    """Ca nặng nhất trong tài liệu T04: nhạc đang phát vẫn phải gọi được cấp
    cứu — bước 1 (EMERGENCY) tuyệt đối, đứng trên cả state lẫn mọi bước khác."""
    from pipeline import router

    action_flow.note_result("music_play", {"request_state": "succeeded"})

    with (
        patch("pipeline.stt.transcribe", return_value="gọi cấp cứu"),
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as mock_emergency,
        patch("handlers.music_stop.handle") as mock_stop,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "khẩn cấp" in out
    mock_emergency.assert_called_once()
    mock_stop.assert_not_called()


def test_navigating_still_allows_hazard():
    """Đúng thứ người khiếm thị cần nhất khi đang đi bộ: chỉ đường đang chạy
    không được chặn mất câu hỏi vật cản phía trước."""
    from pipeline import router

    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )

    with (
        patch("pipeline.stt.transcribe", return_value="phía trước có gì không"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.HAZARD, {})),
        patch(
            "handlers.describe_hazard.handle", return_value=iter(["Không có vật cản."])
        ) as mock_hazard,
        patch("handlers.nav_stop.handle") as mock_stop,
    ):
        out = "".join(router.resolve_speech(b"img", b"dummy"))

    assert out == "Không có vật cản."
    mock_hazard.assert_called_once()
    mock_stop.assert_not_called()


def test_local_stop_regex_still_fast():
    """Giữ đúng cái LỢI của bypass cũ cho đúng câu "tắt nhạc": vẫn ra
    `music_stop`, và vẫn KHÔNG gọi tới Gemini intent (bước 3 chạy TRƯỚC bước
    6, cục bộ, không mạng)."""
    from pipeline import router

    action_flow.note_result("music_play", {"request_state": "succeeded"})

    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("pipeline.intent.detect_with_params") as mock_detect,
        patch(
            "handlers.music_stop.handle", return_value=iter(["Đang dừng nhạc."])
        ) as mock_stop,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "Đang dừng nhạc" in out
    mock_stop.assert_called_once()
    mock_detect.assert_not_called()


def test_local_stop_only_when_task_running():
    """Không có gì đang chạy -> regex barge-in cục bộ KHÔNG được chạy (brief
    mục 2/B1: "chạy luôn tốn vô ích") — "thôi" phải rơi xuống Gemini/handler
    bình thường, KHÔNG tự ý rơi vào nhánh stop."""
    from pipeline import router

    with (
        patch("pipeline.stt.transcribe", return_value="thôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})) as mock_detect,
        patch("handlers.chat.handle", return_value=iter(["Bạn muốn nói gì tiếp ạ?"])),
        patch("handlers.music_stop.handle") as mock_music_stop,
        patch("handlers.nav_stop.handle") as mock_nav_stop,
    ):
        list(router.resolve_speech(None, b"dummy"))

    mock_detect.assert_called_once()
    mock_music_stop.assert_not_called()
    mock_nav_stop.assert_not_called()


def test_context_template_now_reachable():
    """Trước T04: bypass chặn đứng trước khi tới được bước phân loại, nên
    `_CONTEXT_TEMPLATE`/`_context_block()` (`pipeline/intent.py:215`) là dead
    code khi nhạc đang phát. Giờ phải THẬT SỰ chạy tới đó và nhét trạng thái
    vào prompt Gemini."""
    from pipeline import router

    action_flow.note_result("music_play", {"request_state": "succeeded"})
    seen = {}

    def fake_json(prompt, schema=None, model=None):
        seen["prompt"] = prompt
        return {"intent": Intent.CHAT, "params": {}}

    # Câu không khớp regex nào ở bước 1/3/5. Ép bộ phân loại CỤC BỘ (SetFit)
    # trả None để chắc chắn rơi xuống Gemini ở bước 6, nơi `_context_block()`
    # được ghép vào prompt — không phụ thuộc việc câu này có tình cờ đủ tự tin
    # ở bộ cục bộ hay không (tránh test không ổn định).
    with (
        patch("pipeline.stt.transcribe", return_value="hôm nay thời tiết thế nào"),
        patch.object(intent_mod.intent_local, "classify", return_value=None),
        patch.object(intent_mod.vlm, "generate_json", fake_json),
        patch("handlers.chat.handle", return_value=iter(["Trời nắng."])),
    ):
        list(router.resolve_speech(None, b"dummy"))

    assert "prompt" in seen, "chưa từng chạy tới Gemini -> _context_block() vẫn là dead code"
    assert "Nhạc: ĐANG PHÁT" in seen["prompt"]


def test_both_running_picks_most_recent():
    """Nhạc + chỉ đường cùng chạy, "dừng lại" (không nêu rõ cái nào) -> phải
    dừng đúng cái BẬT GẦN ĐÂY NHẤT. Bypass cũ luôn ưu tiên nhạc bất kể thứ tự
    bật — đây là dead code của `_apply_state`/`most_recent`
    (`pipeline/intent.py:231`) nay đã có đường chạy tới thật."""
    from pipeline import router

    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.note_result(
        "navigation_start",
        {"request_state": "succeeded", "result": {"navigation_id": "nav-1"}},
    )
    assert action_flow.device_state()["most_recent"] == "navigating"

    with (
        patch("pipeline.stt.transcribe", return_value="dừng lại"),
        patch("pipeline.intent.detect_with_params") as mock_detect,
        patch(
            "handlers.nav_stop.handle", return_value=iter(["Đang dừng chỉ đường."])
        ) as mock_nav_stop,
        patch("handlers.music_stop.handle") as mock_music_stop,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "Đang dừng chỉ đường" in out
    mock_nav_stop.assert_called_once()
    mock_music_stop.assert_not_called()
    mock_detect.assert_not_called()
