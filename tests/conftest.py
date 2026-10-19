from contextlib import contextmanager
from unittest.mock import patch

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


@contextmanager
def fake_turn(speech=("xin chào",), cues=(), error=None, reply=None):
    """Thay `turn.run` bằng lượt giả: `/process` giờ chạy pipeline v2 (Task 12).

    `speech`: list các mảnh text, hoặc hàm không đối số trả generator (để mô phỏng
    mảnh text nổ giữa chừng / kéo lười). `error`: ngoại lệ ném ra từ `turn.run`.
    Trả danh sách các lần gọi (device, turn_id, content_type, body đã gom, state, kwargs).
    """
    from pipeline.reply import Reply
    from pipeline.turn import TurnResult

    calls = []

    async def run(device, turn_id, content_type, body, state, **kwargs):
        data = b"".join([chunk async for chunk in body])
        calls.append({"device": device, "turn_id": turn_id, "content_type": content_type,
                      "body": data, "state": state, **kwargs})
        if error is not None:
            raise error
        if reply is not None:
            return TurnResult(reply)
        pieces = speech() if callable(speech) else list(speech)
        return TurnResult(Reply(cues=list(cues), speech=pieces))

    with patch("pipeline.turn.run", run):
        yield calls
