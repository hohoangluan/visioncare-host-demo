import re
import time

import pytest

import config
from handlers import chat
from models import vlm
from services import visioncare_client

IMG = b"fake image"


@pytest.fixture(autouse=True)
def clean_history():
    chat.reset_history()
    yield
    chat.reset_history()


@pytest.fixture(autouse=True)
def no_real_location(monkeypatch):
    """Chặn lượt gọi lấy vị trí thật.

    Không chặn thì mỗi test chat đi một vòng HTTP tới host và chờ hết timeout —
    bộ test từ 5 giây phình lên gần 40 giây, và kết quả phụ thuộc vào việc có
    cắm điện thoại hay không.
    """
    chat.reset_location_cache()
    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: None)
    yield
    chat.reset_location_cache()


def _capture(monkeypatch, reply="Chào bạn."):
    """Thay Gemini bằng stub, giữ lại prompt để kiểm nội dung gửi đi."""
    captured = {}

    def fake_generate_stream(prompt, image=None, search=False):
        captured["prompt"] = prompt
        captured["image"] = image
        captured["search"] = search
        yield reply

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)
    return captured


def test_chat_streams_pieces(monkeypatch):
    monkeypatch.setattr(
        vlm, "generate_stream", lambda prompt, image=None, search=False: iter(["Chào ", "bạn."])
    )
    assert list(chat.handle(IMG, "chào bạn")) == ["Chào ", "bạn."]


def test_chat_does_not_send_image(monkeypatch):
    """Chat là nhánh text: gửi ảnh mỗi lượt chỉ tốn thời gian chờ và token."""
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "hôm nay bạn khỏe không"))

    assert captured["image"] is None


def test_chat_prompt_contains_user_command(monkeypatch):
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "kể tôi nghe một câu chuyện vui"))

    assert "kể tôi nghe một câu chuyện vui" in captured["prompt"]


def test_chat_prompt_contains_current_time(monkeypatch):
    """Gemini không tự biết giờ; thiếu dòng này thì 'mấy giờ rồi' nhận về số bịa."""
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "bây giờ là mấy giờ rồi"))

    assert re.search(r"\d+ giờ \d+ phút", captured["prompt"])
    assert re.search(r"ngày \d+ tháng \d+ năm \d{4}", captured["prompt"])


def test_chat_prompt_forbids_markdown(monkeypatch):
    """Câu trả lời đi ra TTS: dấu sao và gạch đầu dòng đọc lên thành rác."""
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "liệt kê vài loại quả"))

    assert "markdown" in captured["prompt"].lower()


def test_chat_remembers_previous_turn(monkeypatch):
    captured = _capture(monkeypatch, reply="Hà Nội là thủ đô Việt Nam.")
    list(chat.handle(IMG, "thủ đô Việt Nam là gì"))

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "ở đó có bao nhiêu người"))

    assert "thủ đô Việt Nam là gì" in captured["prompt"]
    assert "Hà Nội là thủ đô Việt Nam." in captured["prompt"]


def test_chat_history_capped_at_configured_turns(monkeypatch):
    """Lịch sử không được phình vô hạn: mỗi lượt cũ là token gửi lại ở MỌI lượt sau."""
    for i in range(config.CHAT_HISTORY_TURNS + 3):
        _capture(monkeypatch, reply=f"đáp {i}")
        list(chat.handle(IMG, f"hỏi {i}"))

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "hỏi cuối"))

    assert "hỏi 0" not in captured["prompt"]
    assert f"hỏi {config.CHAT_HISTORY_TURNS + 2}" in captured["prompt"]


def test_chat_history_dropped_when_stale(monkeypatch):
    """Bỏ máy vài giờ rồi quay lại là cuộc trò chuyện khác, không kéo lượt cũ theo."""
    stale_at = time.monotonic() - config.CHAT_HISTORY_TTL_SECONDS - 1
    chat._HISTORY.append(("thủ đô Việt Nam là gì", "Hà Nội.", stale_at))

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "xin chào"))

    assert "thủ đô Việt Nam là gì" not in captured["prompt"]


def test_chat_does_not_remember_failed_turn(monkeypatch):
    """Luồng đứt giữa chừng -> câu cụt đó không được làm bối cảnh cho lượt sau."""
    def failing_stream(prompt, image=None, search=False):
        yield "Câu bị"
        raise vlm.VLMError("mạng đứt")

    monkeypatch.setattr(vlm, "generate_stream", failing_stream)
    with pytest.raises(vlm.VLMError):
        list(chat.handle(IMG, "câu hỏi lỗi"))

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "câu hỏi sau"))

    assert "Câu bị" not in captured["prompt"]


def test_chat_skips_location_and_search_when_neither_is_needed(monkeypatch):
    """A joke costs nothing extra: no phone round-trip, no grounding round-trip."""
    called = []
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: called.append("location") or None,
    )
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "kể chuyện cười đi", {}))

    assert called == []
    assert captured["search"] is False
    assert "Người dùng đang ở" not in captured["prompt"]
    assert "tra được Google" not in captured["prompt"]


def test_chat_fetches_location_only_when_the_question_needs_it(monkeypatch):
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 10.7769, "lng": 106.7009, "address": None},
    )
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "quán cà phê gần đây", {"needs_location": True}))

    assert "10.7769" in captured["prompt"]
    assert captured["search"] is False


def test_chat_enables_search_only_when_the_answer_changes_daily(monkeypatch):
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "tin tức hôm nay", {"needs_web": True}))

    assert captured["search"] is True
    # The "you can search Google" line must not appear on turns without the
    # tool, or the model is being told it did something it never did.
    assert "tra được Google" in captured["prompt"]


def test_chat_combines_location_and_search_when_both_are_needed(monkeypatch):
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 10.7769, "lng": 106.7009, "address": "Quận 1"},
    )
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "hôm nay trời thế nào", {"needs_location": True, "needs_web": True}))

    assert "Quận 1" in captured["prompt"]
    assert captured["search"] is True


def test_chat_caches_a_failed_location_lookup(monkeypatch):
    """A phone with location off must not cost a timeout on every single turn."""
    attempts = []

    def failing_location(*a, **k):
        attempts.append(1)
        return None

    monkeypatch.setattr(visioncare_client, "get_device_location", failing_location)
    _capture(monkeypatch)

    list(chat.handle(IMG, "gần đây có gì", {"needs_location": True}))
    list(chat.handle(IMG, "còn quán ăn thì sao", {"needs_location": True}))

    assert len(attempts) == 1


def test_chat_falls_back_to_a_plain_answer_when_search_fails(monkeypatch):
    """Grounding has its own quota; a 429 there must not become "có lỗi xảy ra"."""
    prompts = []

    def flaky_stream(prompt, image=None, search=False):
        prompts.append((prompt, search))
        if search:
            raise vlm.VLMError("429 RESOURCE_EXHAUSTED")
        yield "Hiện mình chưa tra cứu được thông tin đó."

    monkeypatch.setattr(vlm, "generate_stream", flaky_stream)

    out = "".join(chat.handle(IMG, "giá vàng hôm nay", {"needs_web": True}))

    assert [search for _, search in prompts] == [True, False]
    # The retry must tell the model it could not look anything up, so it says so
    # instead of answering from a training snapshot nearly two years stale.
    assert "KHÔNG tra cứu được" in prompts[1][0]
    assert out
