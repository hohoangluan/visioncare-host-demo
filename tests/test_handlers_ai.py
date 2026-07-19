from handlers import ocr, translate, find_object, read_money, describe_space
from handlers.text_utils import has_vietnamese
from schemas import Result

IMG = b"fake image"


def test_has_vietnamese_true_for_vi_text():
    assert has_vietnamese("chào buổi sáng") is True


def test_has_vietnamese_false_for_plain_ascii():
    assert has_vietnamese("good morning") is False


def test_ocr_translate_mode_default():
    r = ocr.handle(IMG, "đọc chữ giúp tôi")
    assert isinstance(r, Result) and r.action is None
    assert "dịch" in r.speech.lower()


def test_ocr_raw_mode_when_nguyen_van():
    r = ocr.handle(IMG, "đọc nguyên văn giúp tôi")
    assert "nguyên văn" in r.speech.lower()
    assert "dịch" not in r.speech.lower()


def test_ocr_raw_mode_when_chuyen_nganh():
    r = ocr.handle(IMG, "đọc chữ chuyên ngành")
    assert "nguyên văn" in r.speech.lower()


def test_translate_vi_to_en_when_vietnamese_input():
    r = translate.handle(IMG, "dịch câu chào buổi sáng")
    assert "VI->EN" in r.speech


def test_translate_en_to_vi_when_no_vietnamese():
    r = translate.handle(IMG, "translate good morning")
    assert "EN->VI" in r.speech


def test_find_money_space_return_result_no_action():
    for h in (find_object, read_money, describe_space):
        r = h.handle(IMG, "lệnh bất kỳ")
        assert isinstance(r, Result) and r.action is None
        assert len(r.speech) > 0
