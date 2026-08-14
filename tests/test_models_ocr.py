from models import ocr

IMG = b"fake image bytes"


def _capture(monkeypatch, *pieces: str):
    """Thay Gemini bằng generator giả, trả dict ghi lại prompt và ảnh đã gửi."""
    captured = {}

    def fake_generate_stream(prompt, image=None):
        captured["prompt"] = prompt
        captured["image"] = image
        captured["pulled"] = 0
        for piece in pieces:
            captured["pulled"] += 1
            yield piece

    monkeypatch.setattr(ocr.vlm, "generate_stream", fake_generate_stream)
    return captured


def test_read_sends_image_to_gemini_in_one_call(monkeypatch):
    """Một lượt gọi ảnh->câu tiếng Việt, không qua bước OCR cục bộ nào."""
    captured = _capture(monkeypatch, "Xin chào ", "thế giới")

    result = "".join(ocr.read_stream(IMG, ocr.Mode.NORMAL))

    assert result == "Xin chào thế giới"
    assert captured["image"] == IMG


def test_normal_mode_asks_for_vietnamese_translation(monkeypatch):
    captured = _capture(monkeypatch, "đã dịch")

    list(ocr.read_stream(IMG, ocr.Mode.NORMAL))

    assert "dịch" in captured["prompt"].lower()
    assert "chuyên ngành" not in captured["prompt"].lower()


def test_specialized_mode_asks_to_keep_technical_terms(monkeypatch):
    captured = _capture(monkeypatch, "đã dịch")

    list(ocr.read_stream(IMG, ocr.Mode.SPECIALIZED))

    assert "chuyên ngành" in captured["prompt"].lower()


def test_raw_mode_asks_to_read_without_translating(monkeypatch):
    captured = _capture(monkeypatch, "Hello World")

    result = "".join(ocr.read_stream(IMG, ocr.Mode.RAW))

    assert result == "Hello World"
    assert "không dịch" in captured["prompt"].lower()


def test_every_mode_tells_gemini_the_no_text_sentinel(monkeypatch):
    """Không có mốc quy ước thì Gemini tự chế câu báo lỗi khác nhau mỗi lần."""
    for mode in (ocr.Mode.NORMAL, ocr.Mode.SPECIALIZED, ocr.Mode.RAW):
        captured = _capture(monkeypatch, "gì đó")
        list(ocr.read_stream(IMG, mode))
        assert ocr.NO_TEXT_SENTINEL in captured["prompt"], f"thiếu ở mode {mode}"


def test_no_text_sentinel_becomes_spoken_instruction(monkeypatch):
    """Người khiếm thị nghe được câu bảo chụp lại, không nghe mã quy ước."""
    _capture(monkeypatch, ocr.NO_TEXT_SENTINEL)

    result = "".join(ocr.read_stream(IMG, ocr.Mode.NORMAL))

    assert ocr.NO_TEXT_SENTINEL not in result
    assert "chụp lại" in result.lower()


def test_no_text_sentinel_detected_despite_extra_whitespace(monkeypatch):
    """Model hay thêm dấu chấm/xuống dòng quanh câu trả lời."""
    _capture(monkeypatch, "\n", ocr.NO_TEXT_SENTINEL, ".\n")

    result = "".join(ocr.read_stream(IMG, ocr.Mode.NORMAL))

    assert "chụp lại" in result.lower()


def test_read_stream_starts_speaking_before_gemini_finishes(monkeypatch):
    """Chỉ giữ lại đủ ký tự để loại trừ mốc KHONG_CO_CHU, rồi thả ngay."""
    long_text = "Đây là một đoạn văn bản dài hơn hẳn mốc quy ước, đủ để kết luận."
    captured = _capture(monkeypatch, long_text, " Phần sau còn dài nữa.")

    stream = ocr.read_stream(IMG, ocr.Mode.NORMAL)
    next(stream)

    assert captured["pulled"] == 1, "không được đọc hết Gemini rồi mới trả chữ đầu"
