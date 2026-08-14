from handlers import ocr, find_object, read_money, describe_space, describe_hazard
from handlers.text_utils import has_vietnamese
from models import vlm

IMG = b"fake image"


def test_has_vietnamese_true_for_vi_text():
    assert has_vietnamese("chào buổi sáng") is True


def test_has_vietnamese_false_for_plain_ascii():
    assert has_vietnamese("good morning") is False


def _stub_read_stream(captured):
    def read_stream(image, mode):
        captured["mode"] = mode
        yield "kết quả"

    return read_stream


def test_ocr_normal_mode_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read_stream", _stub_read_stream(captured))

    speech = "".join(ocr.handle(IMG, "đọc chữ giúp tôi"))

    assert speech == "kết quả"
    assert captured["mode"] == ocr.ocr.Mode.NORMAL


def test_ocr_raw_mode_when_nguyen_van(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read_stream", _stub_read_stream(captured))

    list(ocr.handle(IMG, "đọc nguyên văn giúp tôi"))

    assert captured["mode"] == ocr.ocr.Mode.RAW


def test_ocr_specialized_mode_when_chuyen_nganh(monkeypatch):
    captured = {}
    monkeypatch.setattr(ocr.ocr, "read_stream", _stub_read_stream(captured))

    list(ocr.handle(IMG, "đọc chữ chuyên ngành"))

    assert captured["mode"] == ocr.ocr.Mode.SPECIALIZED


def test_find_and_space_stream_text_pieces(monkeypatch):
    """read_money không nằm đây: nó không streaming, xem tests/test_read_money.py."""
    monkeypatch.setattr(
        vlm, "generate_stream", lambda prompt, image=None: iter(["kết ", "quả"])
    )
    for h in (find_object, describe_space, describe_hazard):
        pieces = list(h.handle(IMG, "lệnh bất kỳ"))
        assert pieces == ["kết ", "quả"], f"{h.__name__} không stream từng mảnh"


def test_read_money_calls_vlm_directly_no_ocr(monkeypatch):
    """read_money dùng thẳng Gemini API, không qua OCR (OCR hay đọc sai số tiền)."""
    captured = {}

    def fake_generate_json(prompt, image=None, schema=None):
        captured["image"] = image
        return {"anh_du_ro": True, "cac_to": [
            {"so_in_doc_duoc": "50000", "menh_gia": 50000}
        ]}

    monkeypatch.setattr(vlm, "generate_json", fake_generate_json)

    speech = "".join(read_money.handle(IMG, "mệnh giá bao nhiêu"))

    assert speech == "Đây là tờ 50 nghìn đồng."
    assert captured["image"] == IMG
