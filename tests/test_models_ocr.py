from models import ocr, orientation

IMG = b"fake image bytes"


def test_raw_mode_skips_translate(monkeypatch):
    monkeypatch.setattr(ocr.engine, "extract_text", lambda image: "Hello World")
    called = []
    monkeypatch.setattr(ocr.vlm, "generate_text", lambda prompt: called.append(prompt) or "unused")

    result = ocr.read(IMG, ocr.Mode.RAW)

    assert result == "Hello World"
    assert called == []


def test_no_text_detected_skips_translate(monkeypatch):
    monkeypatch.setattr(ocr.engine, "extract_text", lambda image: "")
    called = []
    monkeypatch.setattr(ocr.vlm, "generate_text", lambda prompt: called.append(prompt) or "unused")

    result = ocr.read(IMG, ocr.Mode.NORMAL)

    assert "không thấy rõ chữ" in result.lower()
    assert called == []


def test_normal_mode_calls_translate(monkeypatch):
    monkeypatch.setattr(ocr.engine, "extract_text", lambda image: "Hello World")
    captured = {}

    def fake_generate_text(prompt):
        captured["prompt"] = prompt
        return "Xin chào thế giới"

    monkeypatch.setattr(ocr.vlm, "generate_text", fake_generate_text)

    result = ocr.read(IMG, ocr.Mode.NORMAL)

    assert result == "Xin chào thế giới"
    assert "Hello World" in captured["prompt"]
    assert "chuyên ngành" not in captured["prompt"].lower()


def test_extract_text_corrects_orientation_before_predict(monkeypatch):
    """Ảnh chụp lệch/ngược làm PaddleOCR (giả định chữ nằm ngang) đọc sai
    nhiều hơn -> extract_text phải chỉnh hướng trước khi decode/predict."""
    captured = {}
    monkeypatch.setattr(orientation, "correct", lambda image: b"rotated-" + image)
    monkeypatch.setattr(ocr.engine, "_decode", lambda image: captured.setdefault("decoded", image))

    class FakeOCR:
        def predict(self, arr):
            return [{"rec_texts": ["hi"]}]

    monkeypatch.setattr(ocr.engine, "_get_ocr", lambda: FakeOCR())

    result = ocr.engine.extract_text(IMG)

    assert result == "hi"
    assert captured["decoded"] == b"rotated-" + IMG


def test_get_ocr_passes_min_score_threshold(monkeypatch):
    """Chữ đọc dưới ngưỡng tin cậy (config.OCR_MIN_SCORE) phải bị PaddleOCR tự
    lọc bỏ, không trả về như chữ đọc chắc chắn."""
    import config

    monkeypatch.setattr(ocr.engine, "_ocr", None)
    captured = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("paddleocr.PaddleOCR", FakePaddleOCR)

    ocr.engine._get_ocr()

    assert captured["text_rec_score_thresh"] == config.OCR_MIN_SCORE
    monkeypatch.setattr(ocr.engine, "_ocr", None)


def test_specialized_mode_prompt_keeps_terms(monkeypatch):
    monkeypatch.setattr(ocr.engine, "extract_text", lambda image: "Paracetamol 500mg")
    captured = {}

    def fake_generate_text(prompt):
        captured["prompt"] = prompt
        return "đã dịch"

    monkeypatch.setattr(ocr.vlm, "generate_text", fake_generate_text)

    result = ocr.read(IMG, ocr.Mode.SPECIALIZED)

    assert result == "đã dịch"
    assert "Paracetamol 500mg" in captured["prompt"]
    assert "chuyên ngành" in captured["prompt"].lower()
