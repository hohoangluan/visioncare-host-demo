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


def test_chat_never_fetches_location_on_the_request_path(monkeypatch):
    """Lấy vị trí là vòng poll xuống điện thoại tới 12s — cấm nằm trong request.

    Đây là tính chất thay cho cờ `needs_location` cũ: thay vì phân loại xem câu
    nào đáng trả giá đó, không câu nào trả giá cả.
    """
    called = []
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: called.append("location") or None,
    )
    _capture(monkeypatch)

    list(chat.handle(IMG, "kể chuyện cười đi"))
    list(chat.handle(IMG, "quán cà phê gần đây"))

    assert called == []


def test_chat_uses_whatever_location_the_refresher_cached(monkeypatch):
    """Cache nóng thì mọi lượt đều có vị trí, không cần biết câu hỏi cần hay không."""
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 10.7769, "lng": 106.7009, "address": None},
    )
    assert chat.refresh_location_once() is True

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "kể chuyện cười đi"))

    assert "10.7769" in captured["prompt"]


def test_chat_drops_location_once_it_goes_stale(monkeypatch):
    """Toạ độ cũ quá thì bỏ: người khiếm thị đi bộ, chỗ đứng đổi theo thời gian."""
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 10.7769, "lng": 106.7009, "address": "Quận 1"},
    )
    chat.refresh_location_once()
    monkeypatch.setattr(config, "CHAT_LOCATION_TTL_SECONDS", 0.0)

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "quanh đây có gì"))

    assert "Quận 1" not in captured["prompt"]


def test_refresher_rejects_a_stale_fix_from_the_phone(monkeypatch):
    """Điện thoại trả VỊ TRÍ CUỐI CÙNG NÓ BIẾT, không phải fix mới.

    Đo thật trên máy này: gọi lúc 14:12 ngày 16/08 nhận về
    captured_at=2026-08-15T19:22:58Z — bản định vị 12 tiếng tuổi. Chỉ kiểm
    "server lấy về từ bao giờ" thì nó qua cửa mọi lần, vì server vừa lấy xong.
    """
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 1.0, "lng": 2.0, "address": "Chỗ cũ", "captured_at": old},
    )
    assert chat.refresh_location_once() is False

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "quanh đây có gì"))
    assert "Chỗ cũ" not in captured["prompt"]


def test_refresher_accepts_a_fix_with_no_timestamp(monkeypatch):
    """Thiếu `captured_at` thì cứ nhận: từ chối toạ độ vì thiếu metadata là mất
    chức năng để đổi lấy không gì cả."""
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 1.0, "lng": 2.0, "address": "Không mốc giờ"},
    )
    assert chat.refresh_location_once() is True


def test_refresher_keeps_old_coordinates_when_a_poll_fails(monkeypatch):
    """Mất mạng một nhịp không có nghĩa người dùng đã dịch đi đâu."""
    monkeypatch.setattr(
        visioncare_client,
        "get_device_location",
        lambda *a, **k: {"lat": 10.7769, "lng": 106.7009, "address": "Quận 1"},
    )
    chat.refresh_location_once()

    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: None)
    assert chat.refresh_location_once() is False

    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "quanh đây có gì"))
    assert "Quận 1" in captured["prompt"]


def test_chat_lets_the_model_decide_whether_to_search(monkeypatch):
    """Tool gắn vào MỌI lượt; model tự quyết có tra hay không lúc sinh chữ.

    Thay cho cờ `needs_web`: "câu này có cần tra không" là tập mở vô hạn, không
    bộ dữ liệu nào phủ hết, mà model đọc câu hỏi rồi tự quyết thì khỏi liệt kê.
    """
    captured = _capture(monkeypatch)
    list(chat.handle(IMG, "kể chuyện cười đi"))

    assert captured["search"] is True
    assert "tự quyết định có tra hay không" in captured["prompt"]


def test_chat_search_can_be_turned_off_when_grounding_quota_runs_out(monkeypatch):
    """Van dự phòng: hạn mức grounding tính riêng và đã cạn thật một lần.

    Tắt tra cứu thì PHẢI nói với model là nó không tra cứu được. Đo thật trên
    nhánh này khi chưa nói: hỏi "quanh đây có quán ăn nào không" với vị trí thật
    ở Tân Triều, model bịa ra "quán phở Thanh Bình trên đường ĐT768 cách bạn
    khoảng hai trăm mét". Người khiếm thị không có cách nào kiểm lại một cái tên
    quán đọc lên bằng giọng nói, và họ có thể đi bộ theo nó.
    """
    monkeypatch.setattr(config, "CHAT_ALWAYS_SEARCH", False)
    captured = _capture(monkeypatch)

    list(chat.handle(IMG, "quanh đây có quán ăn nào không"))

    assert captured["search"] is False
    # Câu "bạn tra được Google" không được xuất hiện ở lượt KHÔNG có tool, nếu
    # không là dạy model nói dối về thứ nó vừa làm.
    assert "tra được Google" not in captured["prompt"]
    assert "KHÔNG tra cứu được" in captured["prompt"]


def test_chat_falls_back_to_a_plain_answer_when_search_fails(monkeypatch):
    """Grounding has its own quota; a 429 there must not become "có lỗi xảy ra"."""
    prompts = []

    def flaky_stream(prompt, image=None, search=False):
        prompts.append((prompt, search))
        if search:
            raise vlm.VLMError("429 RESOURCE_EXHAUSTED")
        yield "Hiện mình chưa tra cứu được thông tin đó."

    monkeypatch.setattr(vlm, "generate_stream", flaky_stream)

    out = "".join(chat.handle(IMG, "giá vàng hôm nay"))

    assert [search for _, search in prompts] == [True, False]
    # The retry must tell the model it could not look anything up, so it says so
    # instead of answering from a training snapshot nearly two years stale.
    assert "KHÔNG tra cứu được" in prompts[1][0]
    assert out
