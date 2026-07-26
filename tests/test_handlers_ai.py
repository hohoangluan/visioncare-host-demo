from handlers import ocr, find_object, read_money, describe_space
from handlers.text_utils import has_vietnamese
from models import vlm
from schemas import Result

IMG = b"fake image"


def test_has_vietnamese_true_for_vi_text():
    assert has_vietnamese("chào buổi sáng") is True


def test_has_vietnamese_false_for_plain_ascii():
    assert has_vietnamese("good morning") is False


def _stub_read(captured):
    def read(image, mode):
        captured["mode"] = mode
        return "kết quả"

    return read


def test_ocr_normal_mode_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read", _stub_read(captured))

    r = ocr.handle(IMG, "đọc chữ giúp tôi")

    assert isinstance(r, Result)
    assert r.speech == "kết quả"
    assert captured["mode"] == ocr.ocr.Mode.NORMAL


def test_ocr_raw_mode_when_nguyen_van(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read", _stub_read(captured))

    ocr.handle(IMG, "đọc nguyên văn giúp tôi")

    assert captured["mode"] == ocr.ocr.Mode.RAW


def test_ocr_specialized_mode_when_chuyen_nganh(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read", _stub_read(captured))

    ocr.handle(IMG, "đọc chữ chuyên ngành")

    assert captured["mode"] == ocr.ocr.Mode.SPECIALIZED


def test_find_money_space_return_result(monkeypatch):
    monkeypatch.setattr(vlm, "generate", lambda prompt, image=None: "kết quả")
    for h in (find_object, read_money, describe_space):
        r = h.handle(IMG, "lệnh bất kỳ")
        assert isinstance(r, Result)
        assert len(r.speech) > 0


def test_read_money_calls_vlm_directly_no_ocr(monkeypatch):
    """read_money dùng thẳng Gemini API, không qua OCR (OCR hay đọc sai số tiền)."""
    captured = {}

    def fake_generate(prompt, image=None):
        captured["prompt"] = prompt
        captured["image"] = image
        return "Đây là tờ 50 nghìn đồng."

    monkeypatch.setattr(vlm, "generate", fake_generate)

    r = read_money.handle(IMG, "mệnh giá bao nhiêu")

    assert r.speech == "Đây là tờ 50 nghìn đồng."
    assert captured["image"] == IMG
    assert "mệnh giá" in captured["prompt"].lower()
