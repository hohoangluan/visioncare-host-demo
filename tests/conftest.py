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


@pytest.fixture(autouse=True)
def no_v2_network_warm(monkeypatch):
    """`with TestClient(app)` chạy startup: không để nó bắt tay tới Clef/Gemma thật."""
    monkeypatch.setattr(config, "V2_WARM", False)


TEST_DEVICE_TOKEN = "test-device-token"
AUTO_TOKEN = True  # test guard tắt qua fixture `no_auto_token`


@pytest.fixture(autouse=True)
def device_token(monkeypatch):
    """Token kính GIẢ cho test (không bao giờ dùng token thật) + rate limiter sạch.

    Mọi request của `TestClient` (kể cả client dựng ở cấp module, trước khi fixture
    chạy) tự mang `X-Device-Token` giả, để các test API cũ giữ nguyên assertion.
    """
    from starlette.testclient import TestClient

    from pipeline import guard

    monkeypatch.setattr(config, "VISIONCARE_DEVICE_CLIENT_TOKEN", TEST_DEVICE_TOKEN)
    guard.reset()
    original = TestClient.build_request

    def build_request(self, *args, **kwargs):
        request = original(self, *args, **kwargs)
        if AUTO_TOKEN and "x-device-token" not in request.headers and "authorization" not in request.headers:
            request.headers["x-device-token"] = TEST_DEVICE_TOKEN
        return request

    monkeypatch.setattr(TestClient, "build_request", build_request)
    yield
    guard.reset()


@pytest.fixture
def no_auto_token(monkeypatch):
    monkeypatch.setattr(__import__("tests.conftest", fromlist=["x"]), "AUTO_TOKEN", False)
