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
