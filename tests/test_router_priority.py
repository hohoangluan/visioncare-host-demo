"""Thứ tự ưu tiên 6 bước của router (21.1, CONTRACTS.md mục 4.3, T04).

    1. EMERGENCY                 <- tuyệt đối
    2. PENDING TẤT ĐỊNH          <- ừ/không/số thứ tự/thôi/nói lại
    3. STOP / LỆNH TOÀN CỤC      <- chèn vào ĐÂY, giữa hai pha pending
    4. PENDING ĐIỀN SLOT         <- qua slot validator
    5. CANCEL / REPEAT
    6. INTENT DETECT

Đây là thứ dễ bị viết lại sai nhất trong cả spec — mỗi test dưới đây khoá
đúng MỘT cặp ưu tiên kề nhau, không kiểm tra hành vi handler ở tầng sâu hơn
(đã có `tests/test_router.py`/handler riêng cho việc đó).
"""
from unittest.mock import patch

import pytest

from handlers import action_flow
from pipeline import intent_local, router
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def test_stop_beats_pending_fill():
    """Ca vỡ CHÍNH của 21.1: pending(contact_name) đang mở + nhạc đang phát +
    "tắt nhạc" -> PHẢI ra `music_stop`. `contact_name` KHÔNG được nhận "tắt
    nhạc" làm giá trị lấp."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.set_pending(
        slot="contact_name",
        intent=Intent.CONTACT_CALL,
        known={},
        question="Bạn muốn gọi cho ai?",
        kind="fill",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("pipeline.intent.detect_with_params") as mock_detect,
        patch(
            "handlers.music_stop.handle", return_value=iter(["Đang dừng nhạc."])
        ) as mock_stop,
        patch("handlers.contact_call.handle") as mock_contact,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "Đang dừng nhạc" in out
    mock_stop.assert_called_once()
    mock_contact.assert_not_called()
    mock_detect.assert_not_called()
    # Pending phải bị bỏ (không còn treo lại chờ contact_name ở lượt sau).
    assert action_flow.get_pending() is None


def test_deterministic_pending_beats_stop():
    """pending(confirm) đang mở + "ừ" -> phải đi qua PHA 2 (xác nhận, dispatch
    lại `pending.intent`), KHÔNG rơi vào nhánh STOP dù device có tác vụ đang
    chạy."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.set_pending(
        slot="confirm",
        intent=Intent.RIDE_CONFIRM,
        known={"quote_id": "q-1"},
        question="Xác nhận đặt xe GrabBike giá 32 nghìn nhé?",
        kind="confirm",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="ừ"),
        patch(
            "handlers.ride_confirm.handle", return_value=iter(["Đang đặt xe."])
        ) as mock_confirm,
        patch("handlers.music_stop.handle") as mock_stop,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "Đang đặt xe."
    mock_confirm.assert_called_once()
    mock_stop.assert_not_called()
    assert action_flow.get_pending() is None


@pytest.mark.parametrize(
    "negated_text",
    ["không được", "không đồng ý", "tôi bị ngã không dậy được"],
)
def test_negated_affirmative_reads_as_no_not_yes(negated_text):
    """SỬA LỖI review #2: `_PENDING_YES` chứa "được"/"đồng ý" với ranh giới
    `\b` — hai từ đó vẫn khớp y nguyên BÊN TRONG một câu PHỦ ĐỊNH. Trước khi
    sửa, kiểm YES trước NO khiến "không được"/"không đồng ý" đọc thành XÁC
    NHẬN — nguy hiểm nhất đúng ở `confirm` (CONTRACTS mục 4.1: pending nguy
    hiểm nhất khi đoán sai), và câu thứ ba có hình dạng một lời CẦU CỨU ("tôi
    bị ngã không dậy được") lại rơi vào cùng đường xác nhận sai đó.

    Phải đọc thành HUỶ (`_CANCELLED_MESSAGE`), KHÔNG được dispatch
    `pending.intent` (tức không được "xác nhận" hộ)."""
    action_flow.set_pending(
        slot="confirm",
        intent=Intent.RIDE_CONFIRM,
        known={"quote_id": "q-1"},
        question="Xác nhận đặt xe GrabBike giá 32 nghìn nhé?",
        kind="confirm",
    )

    with (
        patch("pipeline.stt.transcribe", return_value=negated_text),
        patch("handlers.ride_confirm.handle") as mock_confirm,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "Đã huỷ."
    mock_confirm.assert_not_called()
    assert action_flow.get_pending() is None


def test_negated_no_beats_yes_in_select_pending_too():
    """Cùng lỗi, nhánh `select`: "không được" khi đang chờ chọn 1/2/3 phải
    huỷ, không được vô tình khớp số thứ tự nào rồi vẫn xác nhận."""
    action_flow.set_pending(
        slot="service_choice",
        intent=Intent.RIDE_CONFIRM,
        known={},
        question="Chọn 1 GrabBike hay 2 GrabCar?",
        kind="select",
        candidates=[{"service_id": 1}, {"service_id": 2}],
    )

    with (
        patch("pipeline.stt.transcribe", return_value="không được"),
        patch("handlers.ride_confirm.handle") as mock_confirm,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "Đã huỷ."
    mock_confirm.assert_not_called()
    assert action_flow.get_pending() is None


def test_emergency_beats_everything():
    """Bước 1 tuyệt đối: pending đang mở + nhạc đang chạy + "gọi cấp cứu" ->
    `emergency_call` thẳng, 0 bước trung gian (không đọc pending, không kiểm
    stop, không gọi Gemini)."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.set_pending(
        slot="contact_name",
        intent=Intent.CONTACT_CALL,
        known={},
        question="Bạn muốn gọi cho ai?",
        kind="fill",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="gọi cấp cứu"),
        patch("pipeline.intent.detect_with_params") as mock_detect,
        patch(
            "handlers.emergency_call.handle",
            return_value=iter(["Đang kích hoạt cuộc gọi khẩn cấp."]),
        ) as mock_emergency,
        patch("handlers.music_stop.handle") as mock_stop,
        patch("handlers.contact_call.handle") as mock_contact,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "khẩn cấp" in out
    mock_emergency.assert_called_once()
    mock_detect.assert_not_called()
    mock_stop.assert_not_called()
    mock_contact.assert_not_called()
    # EMERGENCY không đọc/không đụng pending — nhưng cũng không phải việc của
    # bước 1 phải dọn nó; ghi lại hành vi hiện tại để không ai giả định nhầm.
    assert action_flow.get_pending() is not None


def test_slot_validator_rejects_imperative():
    """pending(contact_name) + "mở nhạc" -> validator từ chối (động từ mệnh
    lệnh), KHÔNG lấp `contact_name` bằng "mở nhạc"."""
    action_flow.set_pending(
        slot="contact_name",
        intent=Intent.CONTACT_CALL,
        known={},
        question="Bạn muốn gọi cho ai?",
        kind="fill",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="mở nhạc"),
        patch(
            "pipeline.intent.detect_with_params", return_value=(Intent.MUSIC_PLAY, {})
        ),
        patch(
            "handlers.music_play.handle", return_value=iter(["Đang mở nhạc."])
        ) as mock_play,
        patch("handlers.contact_call.handle") as mock_contact,
    ):
        list(router.resolve_speech(None, b"dummy"))

    mock_contact.assert_not_called()
    assert action_flow.get_pending() is None


def test_volume_validator_only_accepts_direction():
    """pending(volume_direction) + "Sơn Tùng" -> từ chối (không phải tăng/
    giảm/số), KHÔNG lấp `volume_direction` bằng tên ca sĩ."""
    action_flow.set_pending(
        slot="volume_direction",
        intent=Intent.MUSIC_VOLUME,
        known={},
        question="Bạn muốn tăng hay giảm âm lượng?",
        kind="fill",
    )

    with (
        patch("pipeline.stt.transcribe", return_value="Sơn Tùng"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", return_value=iter(["Tôi chưa hiểu ý bạn."])),
        patch("handlers.music_volume.handle") as mock_volume,
    ):
        list(router.resolve_speech(None, b"dummy"))

    mock_volume.assert_not_called()
    assert action_flow.get_pending() is None


def test_cancel_and_repeat_below_pending():
    """PHA 2 (nằm "bên dưới" ưu tiên EMERGENCY, ngay trên STOP) tự xử lý
    thôi/nói lại của CHÍNH pending đang mở, không cần đụng tới bước 5."""
    action_flow.set_pending(
        slot="contact_name",
        intent=Intent.CONTACT_CALL,
        known={},
        question="Bạn muốn gọi cho ai?",
        kind="fill",
    )

    with patch("pipeline.stt.transcribe", return_value="thôi bỏ đi"):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "Đã huỷ."
    assert action_flow.get_pending() is None

    action_flow.set_pending(
        slot="contact_name",
        intent=Intent.CONTACT_CALL,
        known={},
        question="Bạn muốn gọi cho ai?",
        kind="fill",
    )

    with patch("pipeline.stt.transcribe", return_value="gì cơ"):
        out2 = "".join(router.resolve_speech(None, b"dummy"))

    assert out2 == "Bạn muốn gọi cho ai?"
    # "gì cơ" chỉ đọc lại câu hỏi — pending PHẢI còn nguyên, không bị xoá.
    assert action_flow.get_pending() is not None


def test_unrelated_intent_during_pending():
    """pending(song_title) đang mở + "gọi cho mẹ" -> phải thành `contact_call`
    (ý định khác hẳn, có nhãn rõ ràng qua bộ phân loại cục bộ), KHÔNG bị lấp
    nhầm thành tên bài hát "gọi cho mẹ" dù validator riêng của `song_title`
    (bảng ở `pipeline/router.py`) vốn RẤT LỎNG.

    `tests/conftest.py::local_intent_disabled` tắt `config.INTENT_LOCAL_ENABLED`
    mặc định cho MỌI test (để không phụ thuộc file model 278MB) — giả lập kết
    quả phân loại cục bộ bằng `intent_local.LocalPrediction` thẳng, đúng quy
    ước đã có ở `tests/test_intent_local.py`, thay vì bật cờ thật."""
    action_flow.set_pending(
        slot="song_title",
        intent=Intent.MUSIC_PLAY,
        known={},
        question="Bạn muốn nghe bài hát nào?",
        kind="fill",
    )
    fake_local = intent_local.LocalPrediction(Intent.CONTACT_CALL, 0.95, 0.9)

    with (
        patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"),
        patch("pipeline.intent_local.classify", return_value=fake_local),
        patch(
            "pipeline.intent.detect_with_params", return_value=(Intent.CONTACT_CALL, {"contact_name": "mẹ"})
        ),
        patch(
            "handlers.contact_call.handle", return_value=iter(["Đang tìm số của mẹ."])
        ) as mock_contact,
        patch("handlers.music_play.handle") as mock_play,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "Đang tìm số của mẹ" in out
    mock_contact.assert_called_once()
    mock_play.assert_not_called()
    assert action_flow.get_pending() is None
