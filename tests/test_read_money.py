"""Đọc mệnh giá: manh mối do model khai, ghép manh mối do Python.

Prompt văn xuôi bảo "không chắc thì nói không chắc" đã có sẵn và model vẫn
khẳng định sai (đo trên ảnh thật: 6 mẫu ra 20k/20k/50k/50k/50k/500k cho cùng
một tờ). Nên các luật dưới đây phải chạy trong code, không phải nhờ model.
"""
import json

import pytest

from handlers import read_money
from models import vlm

IMG = b"fake image"
REFUSAL = read_money.REFUSAL


def _note(amount, *, digits="", lead="", colour="khong_ro", window="khong_ro"):
    return {
        "so_in_doc_duoc": digits,
        "chu_so_dau": lead,
        "mau_chu_dao": colour,
        "co_cua_so_trong": window,
        "menh_gia": amount,
    }


def _reply(monkeypatch, payload):
    captured = {}

    def fake_generate_json(prompt, image=None, schema=None):
        captured["prompt"] = prompt
        captured["image"] = image
        captured["schema"] = schema
        return payload

    monkeypatch.setattr(vlm, "generate_json", fake_generate_json)
    return captured


def _speech(image=IMG):
    return "".join(read_money.handle(image, "mệnh giá bao nhiêu"))


def _say(monkeypatch, *notes, clear=True):
    _reply(monkeypatch, {"anh_du_ro": clear, "cac_to": list(notes)})
    return _speech()


# ── Đọc được trọn dãy số: bằng chứng mạnh nhất ────────────────────────────

def test_full_digits_identify_the_note(monkeypatch):
    assert "50 nghìn" in _say(monkeypatch, _note(50000, digits="50000"))


def test_two_notes_are_both_spoken(monkeypatch):
    speech = _say(monkeypatch, _note(10000, digits="10000"), _note(50000, digits="50000"))
    assert "2 tờ" in speech and "10 nghìn" in speech and "50 nghìn" in speech


def test_single_note_reads_without_counting_prefix(monkeypatch):
    speech = _say(monkeypatch, _note(200000, digits="200000"))
    assert "200 nghìn đồng" in speech
    assert "1 tờ" not in speech


def test_digits_with_separators_still_match(monkeypatch):
    """Model hay khai '50.000' hoặc '50 000' thay vì '50000'."""
    assert _say(monkeypatch, _note(50000, digits="50.000")) != REFUSAL


def test_serial_number_beside_the_value_does_not_block_the_read(monkeypatch):
    """Ảnh càng rõ model càng chép thêm sê-ri; nối tất cả lại thì tờ nào cũng hỏng."""
    assert "50 nghìn" in _say(monkeypatch, _note(50000, digits="50000 SB 20123456"))


def test_issue_year_beside_the_value_does_not_block_the_read(monkeypatch):
    assert "200 nghìn" in _say(monkeypatch, _note(200000, digits="200000 2006"))


def test_only_a_serial_number_read_falls_back_to_other_clues(monkeypatch):
    """Cụm số không phải mệnh giá thì bỏ qua, để màu và chữ số đầu quyết."""
    assert "100 nghìn" in _say(
        monkeypatch, _note(100000, digits="MZ 14567890", colour="xanh_la")
    )


def test_two_different_values_read_on_one_note_is_refused(monkeypatch):
    assert _say(monkeypatch, _note(20000, digits="20000 500000")) == REFUSAL


def test_refuses_when_digits_contradict_the_amount(monkeypatch):
    """Đúng ca đã quan sát: khai đọc 500000 nhưng kết luận 20 nghìn."""
    assert _say(monkeypatch, _note(20000, digits="500000")) == REFUSAL


def test_refuses_amount_that_is_not_a_real_vnd_note(monkeypatch):
    assert _say(monkeypatch, _note(30000, digits="30000")) == REFUSAL


# ── Không đọc được số: ghép màu + chữ số đầu + cửa sổ ─────────────────────

def test_unique_colour_alone_identifies_the_note(monkeypatch):
    """Xanh lá chỉ ứng với 100 nghìn — không tờ nào khác màu đó."""
    assert "100 nghìn" in _say(monkeypatch, _note(100000, colour="xanh_la"))


def test_pink_alone_identifies_fifty_thousand(monkeypatch):
    assert "50 nghìn" in _say(monkeypatch, _note(50000, colour="hong"))


def test_colour_family_alone_is_not_enough(monkeypatch):
    """Họ xanh có 5k/20k/500k — chưa tách được thì không đoán."""
    assert _say(monkeypatch, _note(20000, colour="xanh")) == REFUSAL


def test_leading_digit_splits_the_blue_family(monkeypatch):
    """Ý chính: cùng màu xanh, thấy chữ số đầu là '2' thì chỉ có thể là 20k."""
    assert "20 nghìn" in _say(monkeypatch, _note(20000, colour="xanh", lead="2"))


def test_leading_digit_splits_the_brown_family(monkeypatch):
    assert "10 nghìn" in _say(monkeypatch, _note(10000, colour="nau", lead="1"))


def test_window_splits_five_hundred_thousand_from_five_thousand(monkeypatch):
    """Xanh + '5' còn 500k và 5k; cửa sổ trong suốt tách nốt (polymer vs cotton)."""
    assert "500 nghìn" in _say(
        monkeypatch, _note(500000, colour="xanh", lead="5", window="co")
    )
    assert "5 nghìn" in _say(
        monkeypatch, _note(5000, colour="xanh", lead="5", window="khong")
    )


def test_window_splits_two_hundred_thousand_from_two_thousand(monkeypatch):
    assert "200 nghìn" in _say(
        monkeypatch, _note(200000, colour="nau", lead="2", window="co")
    )
    assert "2 nghìn" in _say(
        monkeypatch, _note(2000, colour="nau", lead="2", window="khong")
    )


def test_blue_and_five_without_window_info_is_refused(monkeypatch):
    """Thiếu manh mối cửa sổ thì 500k và 5k vẫn chưa tách được — sai 100 lần."""
    assert _say(monkeypatch, _note(500000, colour="xanh", lead="5")) == REFUSAL


# ── Manh mối chỏi nhau nghĩa là model đang bịa ────────────────────────────

def test_colour_contradicting_digits_is_refused(monkeypatch):
    """Ca thật đã quan sát: khai đọc '10000' nhưng báo màu xanh.

    Xanh chỉ có 500k/20k/5k, không bao giờ là 10 nghìn. Model bịa được cả chữ
    số nên luật khớp-chữ-số không cứu nổi; màu thì bắt được.
    """
    assert _say(monkeypatch, _note(10000, digits="10000", colour="xanh")) == REFUSAL


def test_leading_digit_contradicting_colour_is_refused(monkeypatch):
    """Hồng chỉ có 50k (đầu '5'); khai đầu '2' là chỏi."""
    assert _say(monkeypatch, _note(50000, colour="hong", lead="2")) == REFUSAL


def test_window_contradicting_amount_is_refused(monkeypatch):
    """100k là polymer, khai không có cửa sổ là chỏi."""
    assert _say(monkeypatch, _note(100000, colour="xanh_la", window="khong")) == REFUSAL


# ── Không đủ manh mối / dữ liệu hỏng ──────────────────────────────────────

def test_refuses_when_model_says_image_unclear(monkeypatch):
    assert _say(monkeypatch, _note(50000, digits="50000"), clear=False) == REFUSAL


def test_refuses_when_no_clue_at_all(monkeypatch):
    assert _say(monkeypatch, _note(50000)) == REFUSAL


def test_reports_the_certain_note_and_admits_the_rest(monkeypatch):
    """Đọc chắc tờ nào thì nói tờ đó, đừng im bắt người dùng chụp lại hoài."""
    speech = _say(monkeypatch, _note(50000, digits="50000"), _note(10000), _note(20000))

    assert "50 nghìn" in speech
    assert "2 tờ nữa" in speech, f"phải nói rõ còn bao nhiêu tờ chưa đọc được: {speech!r}"
    assert "chụp lại" in speech


def test_one_unread_note_is_singular(monkeypatch):
    speech = _say(monkeypatch, _note(50000, digits="50000"), _note(10000))
    assert "1 tờ nữa" in speech


def test_partial_answer_never_implies_that_is_all(monkeypatch):
    """Người nghe có thể chỉ bắt được vế đầu — vế đầu không được nghe như đã đủ."""
    speech = _say(monkeypatch, _note(50000, digits="50000"), _note(10000))
    assert not speech.startswith("Có 1 tờ")
    assert "Đây là tờ 50 nghìn đồng." not in speech


def test_several_certain_notes_plus_unread_ones(monkeypatch):
    speech = _say(
        monkeypatch,
        _note(10000, digits="10000"),
        _note(50000, digits="50000"),
        _note(20000),
    )
    assert "10 nghìn" in speech and "50 nghìn" in speech
    assert "1 tờ nữa" in speech


def test_refuses_only_when_no_note_is_certain(monkeypatch):
    assert _say(monkeypatch, _note(10000), _note(20000)) == REFUSAL


def test_all_certain_notes_say_nothing_about_unread(monkeypatch):
    speech = _say(monkeypatch, _note(10000, digits="10000"), _note(50000, digits="50000"))
    assert "chụp lại" not in speech
    assert "tờ nữa" not in speech


def test_refuses_when_no_note_found(monkeypatch):
    assert _say(monkeypatch) == REFUSAL


def test_refuses_when_model_returns_garbage(monkeypatch):
    for payload in ({}, {"cac_to": "khong phai list"}, {"anh_du_ro": True}):
        _reply(monkeypatch, payload)
        assert _speech() == REFUSAL, payload


def test_refuses_when_gemini_call_fails(monkeypatch):
    def boom(prompt, image=None, schema=None):
        raise vlm.VLMError("503 UNAVAILABLE")

    monkeypatch.setattr(vlm, "generate_json", boom)
    with pytest.raises(vlm.VLMError):
        _speech()  # app.py đổi thành câu báo lỗi chung, không nuốt ở đây


def test_speech_never_mentions_colour(monkeypatch):
    """Người nghe mù bẩm sinh không hình dung được màu — màu chỉ dùng nội bộ."""
    speech = _say(monkeypatch, _note(100000, colour="xanh_la"))
    assert "màu" not in speech.lower()
    assert "xanh" not in speech.lower()


def test_prompt_asks_for_every_clue(monkeypatch):
    captured = _reply(monkeypatch, {"anh_du_ro": True, "cac_to": []})
    _speech()
    for field in ("so_in_doc_duoc", "chu_so_dau", "mau_chu_dao", "co_cua_so_trong"):
        assert field in captured["prompt"], field
    assert json.dumps(captured["schema"])  # schema phải gửi kèm


def test_every_note_is_separable_by_the_three_clues():
    """Bảng đặc điểm phải tách được MỌI tờ, nếu không luật lọc vô dụng ở đó."""
    for amount, (colour, lead, polymer) in read_money._NOTES.items():
        note = _note(
            amount, colour=colour, lead=lead, window="co" if polymer else "khong"
        )
        assert read_money._candidates(note) == {amount}, amount
