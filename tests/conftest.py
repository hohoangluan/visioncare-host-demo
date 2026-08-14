import pytest

import config
from pipeline import tts


@pytest.fixture(autouse=True)
def isolated_phrase_cache_dir(tmp_path, monkeypatch):
    """Không test nào được ghi vào thư mục cache thật.

    Test hay thay `synthesize_stream` bằng bản giả trả vài byte. Ghi vào cache
    thật thì lần chạy server sau nạp đúng mấy byte đó và im lặng ở những câu
    đáng lẽ phát ngay — hỏng trong im lặng, không lỗi, không log. Đã dính rồi.
    """
    monkeypatch.setattr(config, "PHRASE_CACHE_DIR", str(tmp_path / "tts_phrases"))


@pytest.fixture(autouse=True)
def local_intent_disabled(monkeypatch):
    """Mặc định TẮT bộ phân loại ý định cục bộ trong test.

    Nó đứng trước Gemini và tự trả lời những câu nó chắc, nên bật mặc định thì
    mọi test đang kiểm đường Gemini bỗng không còn gọi Gemini nữa — và chúng
    thất bại ở một chỗ chẳng liên quan gì tới thứ chúng kiểm. Tệ hơn: kết quả
    phụ thuộc việc máy chạy test có sẵn file model 278MB hay không, nên cùng một
    commit sẽ xanh trên máy này và đỏ trên máy khác.

    Test nào muốn đường cục bộ thì tự thay `intent_local.classify` bằng bản giả
    (xem `tests/test_intent_local.py`) — không phụ thuộc model thật.
    """
    monkeypatch.setattr(config, "INTENT_LOCAL_ENABLED", False)


@pytest.fixture(autouse=True)
def no_prerendered_phrases():
    """Mỗi test bắt đầu với cache câu dựng sẵn RỖNG.

    `tts._PHRASE_PCM` là biến toàn cục của tiến trình. Một test gọi
    `preload_models()` là nạp đầy nó cho mọi test chạy sau, và những test đó
    bỗng thấy `synthesize_stream` không được gọi lần nào — thất bại ở một chỗ
    chẳng liên quan gì tới thứ chúng kiểm. Đã dính đúng vậy một lần.

    Dọn cả sau khi chạy, để test nào cố ý nạp cache cũng không rò sang test kế.
    """
    tts.clear_phrases()
    yield
    tts.clear_phrases()
