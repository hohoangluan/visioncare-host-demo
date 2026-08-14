import pytest

import config
from models import vlm
from models.vlm import client


class _FakePart:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, texts=None, error=None):
        self._texts = texts or []
        self._error = error
        self.calls = []

    def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return iter([_FakePart(t) for t in self._texts])


class _FakeClient:
    def __init__(self, models):
        self.models = models


def _fake(monkeypatch, texts=None, error=None):
    models = _FakeModels(texts, error)
    monkeypatch.setattr(client, "_get_client", lambda: _FakeClient(models))
    return models


def test_generate_stream_yields_each_text_piece(monkeypatch):
    _fake(monkeypatch, ["Xin ", "chào ", "thế giới"])
    assert list(vlm.generate_stream("prompt")) == ["Xin ", "chào ", "thế giới"]


def test_generate_stream_attaches_image(monkeypatch):
    models = _fake(monkeypatch, ["ok"])
    list(vlm.generate_stream("prompt", image=b"\xff\xd8fake"))
    contents = models.calls[0]["contents"]
    assert contents[0] == "prompt"
    assert len(contents) == 2  # prompt + ảnh


def test_generate_stream_skips_empty_pieces(monkeypatch):
    """Gemini hay chèn part rỗng; đẩy chuỗi rỗng xuống TTS là gọi model vô ích."""
    _fake(monkeypatch, ["Xin chào", "", None])
    assert list(vlm.generate_stream("prompt")) == ["Xin chào"]


def test_generate_stream_wraps_api_error(monkeypatch):
    """Lỗi 503/quota phải thành VLMError để app đổi sang câu báo lỗi đọc được."""
    _fake(monkeypatch, error=RuntimeError("503 UNAVAILABLE"))
    with pytest.raises(vlm.VLMError, match="503"):
        list(vlm.generate_stream("prompt"))


def test_generate_stream_raises_when_model_says_nothing(monkeypatch):
    _fake(monkeypatch, ["", ""])
    with pytest.raises(vlm.VLMError):
        list(vlm.generate_stream("prompt"))


def test_thinking_left_to_model_default(monkeypatch):
    """Đo thấy tắt thinking KHÔNG nhanh hơn, nên không tự ý đè lên mặc định.

    Đè bừa thì mất khả năng suy luận ở những chỗ cần nó (đọc mệnh giá tiền)
    mà chẳng đổi lấy giây nào.
    """
    monkeypatch.setattr(config, "GEMINI_THINKING_BUDGET", -1)
    models = _fake(monkeypatch, ["ok"])
    list(vlm.generate_stream("prompt"))

    assert models.calls[0]["config"] is None


def test_thinking_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_THINKING_BUDGET", 0)
    models = _fake(monkeypatch, ["ok"])
    list(vlm.generate_stream("prompt"))

    assert models.calls[0]["config"].thinking_config.thinking_budget == 0


def test_thinking_budget_configurable(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_THINKING_BUDGET", 512)
    models = _fake(monkeypatch, ["ok"])
    list(vlm.generate_stream("prompt"))

    assert models.calls[0]["config"].thinking_config.thinking_budget == 512


class _JsonModels:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"text": self._text})()


def _fake_json(monkeypatch, text):
    models = _JsonModels(text)
    monkeypatch.setattr(client, "_get_client", lambda: _FakeClient(models))
    return models


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def test_generate_json_parses_response(monkeypatch):
    _fake_json(monkeypatch, '{"a": 1}')
    assert vlm.generate_json("prompt", schema=SCHEMA) == {"a": 1}


def test_generate_json_sends_schema_and_json_mime(monkeypatch):
    models = _fake_json(monkeypatch, "{}")
    vlm.generate_json("prompt", image=b"\xff\xd8x", schema=SCHEMA)

    cfg = models.calls[0]["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema == SCHEMA


def test_generate_json_raises_on_unparseable_output(monkeypatch):
    """Model trả kèm ```json ... ``` hoặc câu dẫn -> phải thành VLMError."""
    _fake_json(monkeypatch, "xin lỗi, tôi không thể")
    with pytest.raises(vlm.VLMError):
        vlm.generate_json("prompt", schema=SCHEMA)


def test_generate_json_raises_on_empty_response(monkeypatch):
    _fake_json(monkeypatch, "")
    with pytest.raises(vlm.VLMError):
        vlm.generate_json("prompt", schema=SCHEMA)
