import pytest

from models.vlm import client


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text=None, raise_exc=None):
        self._text = text
        self._raise = raise_exc
        self.calls = []

    def generate_content(self, model, contents):
        self.calls.append((model, contents))
        if self._raise:
            raise self._raise
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text=None, raise_exc=None):
        self.models = _FakeModels(text, raise_exc)


def test_generate_returns_text(monkeypatch):
    fake = _FakeClient(text="xin chào")
    monkeypatch.setattr(client, "_get_client", lambda: fake)
    assert client.generate("hi") == "xin chào"
    assert fake.models.calls[0][1] == ["hi"]


def test_generate_raises_on_empty_response(monkeypatch):
    monkeypatch.setattr(client, "_get_client", lambda: _FakeClient(text=""))
    with pytest.raises(client.VLMError):
        client.generate("hi")


def test_generate_raises_on_sdk_error(monkeypatch):
    fake = _FakeClient(raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(client, "_get_client", lambda: fake)
    with pytest.raises(client.VLMError):
        client.generate("hi")


def test_generate_with_image_attaches_part(monkeypatch):
    fake = _FakeClient(text="ok")
    monkeypatch.setattr(client, "_get_client", lambda: fake)
    jpeg_bytes = b"\xff\xd8\xff\xe0restofjpeg"

    result = client.generate("mô tả ảnh", image=jpeg_bytes)

    assert result == "ok"
    contents = fake.models.calls[0][1]
    assert len(contents) == 2
    assert contents[0] == "mô tả ảnh"
