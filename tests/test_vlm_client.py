"""Dựng nội dung gửi Gemini: prompt + ảnh kèm đúng MIME type."""
from models.vlm import client

JPEG = b"\xff\xd8\xff\xe0restofjpeg"
PNG = b"\x89PNG\r\n\x1a\nrestofpng"


def test_contents_is_prompt_only_without_image():
    assert client._build_contents("hi", None) == ["hi"]


def test_contents_appends_image_part():
    contents = client._build_contents("mô tả ảnh", JPEG)
    assert len(contents) == 2
    assert contents[0] == "mô tả ảnh"


def test_guess_mime_detects_jpeg():
    assert client._guess_mime(JPEG) == "image/jpeg"


def test_guess_mime_detects_png():
    assert client._guess_mime(PNG) == "image/png"


def test_guess_mime_falls_back_to_jpeg():
    """MCU gửi ảnh không có magic bytes quen thuộc: đoán jpeg còn hơn bỏ ảnh."""
    assert client._guess_mime(b"khong ro dinh dang") == "image/jpeg"


# ── Timeout: một lần Gemini treo không được treo cả lượt ───────────────────

import pytest  # noqa: E402

import config  # noqa: E402


class _FakeModels:
    """Bắt lại `config=` mà client thật gửi xuống SDK."""

    def __init__(self, exc=None):
        self.seen = {}
        self._exc = exc

    def _record(self, **kwargs):
        self.seen = kwargs
        if self._exc:
            raise self._exc

    def generate_content(self, **kwargs):
        self._record(**kwargs)
        return type("R", (), {"text": '{"intent": "chat"}'})()

    def generate_content_stream(self, **kwargs):
        self._record(**kwargs)
        return iter([type("P", (), {"text": "xin chào"})()])


def _fake_client(monkeypatch, exc=None):
    models = _FakeModels(exc)
    monkeypatch.setattr(client, "_get_client", lambda: type("C", (), {"models": models})())
    return models


def test_generate_json_sends_intent_timeout(monkeypatch):
    """Bước phân loại PHẢI có trần thời gian.

    Không có trần thì một lần Gemini treo là cả lượt treo theo. Đo được thật
    trong benchmark 23/08: một lượt phân loại `ocr` tốn 37977ms, trong khi p90
    của chính bước đó là 1684ms — người dùng ngồi im 38 giây.
    """
    monkeypatch.setattr(config, "GEMINI_INTENT_TIMEOUT_SECONDS", 10.0)
    models = _fake_client(monkeypatch)

    client.generate_json("phân loại giúp", schema={"type": "object"})

    assert models.seen["config"].http_options.timeout == 10000


def test_generate_stream_sends_generation_timeout(monkeypatch):
    """Nhánh sinh chữ có trần RIÊNG, rộng hơn nhánh phân loại.

    Câu trả lời dài stream trong nhiều giây là bình thường (p90 mảnh đầu
    3126ms, dài nhất 5930ms), nên dùng chung trần 8s của phân loại sẽ cắt
    nhầm những câu đang chạy đúng.
    """
    monkeypatch.setattr(config, "GEMINI_TIMEOUT_SECONDS", 30.0)
    models = _fake_client(monkeypatch)

    list(client.generate_stream("kể chuyện đi"))

    assert models.seen["config"].http_options.timeout == 30000


def test_generation_timeout_is_wider_than_intent_timeout():
    """Đặt ngược lại là cắt nhầm câu dài trong khi vẫn để phân loại treo."""
    assert config.GEMINI_TIMEOUT_SECONDS > config.GEMINI_INTENT_TIMEOUT_SECONDS


def test_timeouts_respect_the_api_hard_floor():
    """Gemini TỪ CHỐI deadline dưới 10s — đây là sàn của API, không phải sở thích.

    Thử thật với 8s (chọn theo p90 1684ms, tưởng là dư dả):
        400 INVALID_ARGUMENT
        "Manually set deadline 8s is too short. Minimum allowed deadline is 10s."

    Đặt dưới sàn không làm nhanh thêm mà làm HỎNG mọi lượt gọi — hỏng ngay từ
    lượt đầu, trên mọi intent. Test này chặn đúng cái bẫy "siết cho nhanh".
    """
    assert config.GEMINI_INTENT_TIMEOUT_SECONDS >= 10
    assert config.GEMINI_TIMEOUT_SECONDS >= 10


def test_timeout_surfaces_as_vlm_error(monkeypatch):
    """Hết giờ phải ra `VLMError` — đó là thứ các nhánh dự phòng đã bắt sẵn.

    `_ask_gemini` đổi nó thành `classify_failed`, còn
    `chat._stream_with_search_fallback` trả lời lại không kèm tra cứu. Ném ra
    một loại lỗi khác là đi thẳng ra ngoài, thành 500.
    """
    _fake_client(monkeypatch, exc=TimeoutError("hết giờ"))
    with pytest.raises(client.VLMError):
        client.generate_json("gì đó", schema={"type": "object"})

    _fake_client(monkeypatch, exc=TimeoutError("hết giờ"))
    with pytest.raises(client.VLMError):
        list(client.generate_stream("gì đó"))
