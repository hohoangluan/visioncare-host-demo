"""Gom mảnh text rời rạc từ Gemini thành câu đủ nghĩa để đưa sang TTS.

Câu mẫu dài như câu thật của handler, không phải "Xin chào." — mảnh ngắn hơn
`_MIN_SENTENCE_CHARS` bị gộp có chủ ý, dùng câu đồ chơi sẽ kiểm nhầm luật gộp
thay vì luật cắt.
"""
from pipeline.tts import _sentences

A = "Cửa ở phía trước hướng mười hai giờ."
B = "Giữa đường có một cái ghế lệch trái."
C = "Đi thẳng rồi hơi chuyển sang phải."


def test_splits_at_sentence_end():
    assert list(_sentences([A + " ", B])) == [A, B]


def test_emits_first_sentence_before_reading_rest():
    """Điểm cốt lõi: câu đầu đi tổng hợp trong lúc Gemini còn đang viết tiếp."""
    read = []

    def chunks():
        for piece in [A + " ", B + " ", C]:
            read.append(piece)
            yield piece

    stream = _sentences(chunks())
    first = next(stream)

    assert first == A
    assert len(read) == 1, "không được đọc hết Gemini rồi mới trả câu đầu"


def test_does_not_split_inside_vietnamese_thousand_separator():
    """'50.000 đồng' tách ở dấu chấm sẽ đọc thành 'năm mươi' rồi 'không nghìn'."""
    assert list(_sentences(["Đây là tờ 50.000 đồng."])) == ["Đây là tờ 50.000 đồng."]


def test_splits_at_newline():
    assert list(_sentences([A + "\n" + B])) == [A, B]


def test_flushes_trailing_text_without_punctuation():
    assert list(_sentences(["Không có dấu chấm cuối"])) == ["Không có dấu chấm cuối"]


def test_handles_punctuation_split_across_chunks():
    """Gemini có thể cắt ngay giữa dấu câu và khoảng trắng theo sau."""
    assert list(_sentences([A, " " + B])) == [A, B]


def test_skips_whitespace_only_output():
    assert list(_sentences(["   ", "\n"])) == []


def test_splits_long_run_on_text_at_word_boundary():
    """Text dài không dấu câu vẫn phải cắt, nếu không câu đầu chờ tới tận cuối."""
    words = " ".join(f"từ{i}" for i in range(200))
    parts = list(_sentences([words]))

    assert len(parts) > 1
    assert all(len(p) <= 200 for p in parts)
    assert " ".join(parts).split() == words.split()  # không mất chữ nào


def test_keeps_question_and_exclamation_marks():
    hoi = "Bạn có muốn tôi đọc lại một lần nữa không?"
    dap = "Vậy tôi đọc tiếp phần còn lại nhé!"
    assert list(_sentences([hoi + " ", dap])) == [hoi, dap]


def test_numbered_list_marker_stays_with_its_item():
    """'1.' tách riêng thì TTS đọc rời 'một.' rồi mới tới nội dung — nghe cụt.

    Mỗi lệnh gọi TTS còn phải trả chi phí cố định: đo thật thấy 3 mảnh '1.'
    '2.' '3.' tốn 2.94s để sinh 1.68s audio.
    """
    parts = list(_sentences(["1. Ràng buộc bộ nhớ là bốn gigabyte RAM. "]))
    assert parts == ["1. Ràng buộc bộ nhớ là bốn gigabyte RAM."]


def test_short_fragment_merges_into_following_text():
    parts = list(_sentences(["Xong. ", "Tiếp theo là phần hướng dẫn sử dụng thiết bị."]))
    assert parts[0].startswith("Xong.")
    assert len(parts) == 1, f"mảnh ngắn phải gộp, nhưng ra {parts!r}"


def test_still_splits_two_full_sentences():
    text = ("Cửa ở phía trước hướng mười hai giờ cách khoảng bốn mét. "
            "Giữa đường có một cái ghế lệch sang trái nên đi vòng qua phải.")
    parts = list(_sentences([text]))
    assert len(parts) == 2


def test_trailing_short_fragment_still_spoken():
    """Gộp được thì gộp, nhưng không được nuốt mất chữ ở cuối."""
    assert list(_sentences(["Xong."])) == ["Xong."]


def test_newline_forces_a_short_utterance_out_immediately():
    """Xuống dòng = người gọi khẳng định "câu này trọn vẹn", phải đọc ngay.

    Handler điều khiển điện thoại đẩy ra từng câu trọn vẹn, và mảnh kế tiếp có
    thể cả chục giây nữa mới tới. Không có luật này thì "Đang gọi xe." (12 ký
    tự, dưới ngưỡng gộp) nằm im trong buffer tới lúc câu trấn an xuất hiện, rồi
    hai câu bung ra một lượt — nghe thành im lặng rồi nói dồn.
    """
    stream = _sentences(iter(["Đang gọi xe.\n"]))
    assert next(stream) == "Đang gọi xe."


def test_newline_rule_does_not_leak_into_gemini_text():
    """Chỉ xuống dòng mới được cắt sớm; dấu chấm thường vẫn theo luật gộp cũ."""
    assert list(_sentences(["Xong. ", "Tiếp theo là phần hướng dẫn sử dụng."])) == [
        "Xong. Tiếp theo là phần hướng dẫn sử dụng."
    ]


def test_thousand_separator_not_split_even_with_newline_rule():
    """'50.000 đồng' vẫn không được xẻ đôi — dấu chấm hàng nghìn không có \\n."""
    parts = list(_sentences(["Tờ này mệnh giá 50.000 đồng."]))
    assert parts == ["Tờ này mệnh giá 50.000 đồng."]
