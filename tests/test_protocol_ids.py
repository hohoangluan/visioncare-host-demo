"""T01 — Định danh thiết bị & lượt (`X-Device-Id` / `X-Turn-Id`).

Xem `docs/tasks/T01-protocol-ids.md` và `docs/tasks/CONTRACTS.md` mục 2.1.

7 ca theo mục 4.1 + 4.2 của task file:
  4.1 test_missing_device_id_rejected
      test_missing_device_id_warns_in_transition_mode
      test_duplicate_turn_id_no_second_call
      test_different_turn_id_calls_again
      test_device_id_reaches_handler
  4.2 test_two_devices_independent_state
      test_two_requests_same_device_within_100ms

Thêm sau review (findings 1 và 4 — xem docs/tasks/reports/T01.md phần "Sửa
theo review"):
  test_duplicate_turn_id_in_flight_not_called_twice
  test_bind_context_keeps_ids_after_process_returns
"""
import asyncio
import io
import logging
import threading
import time
import wave
from unittest.mock import patch

import pytest

from fastapi import Request, UploadFile
from fastapi.testclient import TestClient

import app as app_module
import config
from app import app
from app import process as process_endpoint

client = TestClient(app)


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


def _files():
    return {
        "image": ("i.jpg", b"fake img", "image/jpeg"),
        "audio": ("a.wav", _wav_bytes(), "audio/wav"),
    }


def _request(headers: dict[str, str] | None = None) -> Request:
    """Request tối thiểu để gọi thẳng `process()`, không qua TestClient.

    Dùng khi test cần chạy trên THREAD THẬT (test đồng thời) — TestClient gom
    cả body và có thể không chạy hai lượt song song thật sự.
    """
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/process", "headers": hdrs})


def _fake_pcm_stream(text_chunks):
    """Giả TTS: PHẢI tiêu thụ hết `text_chunks` (không bỏ qua như một số test ở
    `test_app.py`) — nhiều ca dưới đây gài side-effect (ghi lại ContextVar)
    vào generator `resolve_speech` giả, và side-effect đó chỉ chạy khi có ai
    thật sự kéo hết generator đó.
    """
    for _ in text_chunks:
        pass
    yield b"\x01\x02" * 100
    yield b"\x03\x04" * 100


@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    """Cache idempotency là dict toàn cục của tiến trình — dọn giữa các test
    để turn_id trùng tên ở hai test khác nhau không ăn nhầm kết quả của nhau.
    """
    app_module._IDEMPOTENCY_CACHE.clear()
    yield
    app_module._IDEMPOTENCY_CACHE.clear()


@pytest.fixture
def stream_mode(monkeypatch):
    """Ép định dạng PCM trần — tránh cuốn theo hành vi encode ADPCM/MP3, thứ
    không phải trọng tâm của bộ test này (đã có test riêng ở `test_app.py`).
    """
    monkeypatch.setattr(config, "RESPONSE_FORMAT", "pcm_stream")


# ─── 4.1 Unit / API ────────────────────────────────────────────────────────


def test_missing_device_id_rejected(stream_mode, monkeypatch):
    """Thiếu X-Device-Id, REQUIRE_DEVICE_ID=1 -> từ chối RÕ RÀNG (400), KHÔNG
    im lặng bỏ qua và KHÔNG rơi về `glasses-123`. Pipeline không được chạy.
    """
    monkeypatch.setattr(config, "REQUIRE_DEVICE_ID", True)

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])) as mock_resolve, \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        response = client.post("/process", files=_files())  # không gửi X-Device-Id

    assert response.status_code == 400
    mock_resolve.assert_not_called()  # bị chặn TRƯỚC khi chạm tới pipeline


def test_missing_device_id_warns_in_transition_mode(stream_mode, caplog):
    """REQUIRE_DEVICE_ID=0 (giai đoạn chuyển, mặc định) -> vẫn 200 nhưng phải
    có `logger.warning` — cấm rơi ngầm không dấu vết.
    """
    assert config.REQUIRE_DEVICE_ID is False  # mặc định đúng như tài liệu

    with caplog.at_level(logging.WARNING, logger="blind_assist"):
        with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), \
             patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
            response = client.post("/process", files=_files())  # không gửi X-Device-Id

    assert response.status_code == 200
    assert "X-Device-Id" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_duplicate_turn_id_no_second_call(stream_mode):
    """Hai POST cùng X-Turn-Id -> pipeline (`router.resolve_speech`, đứng vai
    "host API"/Gemini) chỉ được gọi MỘT LẦN; lượt hai trả lại đúng audio cũ.
    """
    headers = {"X-Device-Id": "glasses-dup", "X-Turn-Id": "turn-dup-1"}

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])) as mock_resolve, \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        first = client.post("/process", files=_files(), headers=headers)
        second = client.post("/process", files=_files(), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    mock_resolve.assert_called_once()
    assert second.content == first.content


def test_different_turn_id_calls_again(stream_mode):
    """Đổi X-Turn-Id -> KHÔNG bị coi là trùng, pipeline chạy lại bình thường."""
    device = {"X-Device-Id": "glasses-diff"}

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])) as mock_resolve, \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        client.post("/process", files=_files(), headers={**device, "X-Turn-Id": "turn-a"})
        client.post("/process", files=_files(), headers={**device, "X-Turn-Id": "turn-b"})

    assert mock_resolve.call_count == 2


def test_device_id_reaches_handler(stream_mode):
    """Handler (đại diện bởi `router.resolve_speech`) đọc được đúng device_id
    từ `app.DEVICE_ID_CTX` — KHÔNG phải từ hằng số `config.VISIONCARE_DEVICE_ID`.
    """
    seen: list[str | None] = []

    def fake_resolve(image, audio, opening_seconds=0.0):
        seen.append(app_module.DEVICE_ID_CTX.get())
        yield "ok"

    with patch("pipeline.router.resolve_speech", fake_resolve), \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        client.post(
            "/process", files=_files(),
            headers={"X-Device-Id": "glasses-XYZ", "X-Turn-Id": "turn-handler"},
        )

    assert seen == ["glasses-XYZ"]
    assert seen[0] != config.VISIONCARE_DEVICE_ID


# ─── 4.2 Nhiều thiết bị ────────────────────────────────────────────────────


def test_two_devices_independent_state(stream_mode):
    """Hai thiết bị gửi TRÙNG X-Turn-Id không được ăn nhầm cache của nhau —
    cache idempotency khoá theo CẢ (device_id, turn_id), không phải riêng
    turn_id. (Session/pending đầy đủ theo device là phần việc của T03; ở đây
    chỉ kiểm phần T01 sở hữu: cache + ContextVar không rò giữa hai thiết bị.)
    """
    seen: list[str | None] = []

    def fake_resolve(image, audio, opening_seconds=0.0):
        seen.append(app_module.DEVICE_ID_CTX.get())
        yield "ok"

    with patch("pipeline.router.resolve_speech", fake_resolve) as mock_resolve_wrapper, \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        r_a = client.post(
            "/process", files=_files(),
            headers={"X-Device-Id": "glasses-A", "X-Turn-Id": "shared-turn"},
        )
        r_b = client.post(
            "/process", files=_files(),
            headers={"X-Device-Id": "glasses-B", "X-Turn-Id": "shared-turn"},
        )

    assert r_a.status_code == 200
    assert r_b.status_code == 200
    # Cả hai đều thật sự chạy pipeline — không cái nào bị coi là "trùng" của
    # cái kia chỉ vì turn_id giống nhau.
    assert seen == ["glasses-A", "glasses-B"]


def test_two_requests_same_device_within_100ms(stream_mode):
    """Hai lượt CÙNG thiết bị xử lý gần như đồng thời (threadpool thật, hai
    OS thread) không được crash, không được trộn ContextVar của nhau — mỗi
    luồng phải thấy đúng turn_id của chính lượt đó.
    """
    seen: list[tuple[str | None, str | None]] = []
    seen_lock = threading.Lock()
    barrier = threading.Barrier(2, timeout=5)

    def fake_resolve(image, audio, opening_seconds=0.0):
        barrier.wait()  # ép cả hai luồng cùng ở TRONG pipeline một lúc
        with seen_lock:
            seen.append((app_module.DEVICE_ID_CTX.get(), app_module.TURN_ID_CTX.get()))
        yield "ok"

    results: list = []
    results_lock = threading.Lock()

    def call(turn_id: str) -> None:
        req = _request(headers={"X-Device-Id": "glasses-race", "X-Turn-Id": turn_id})
        resp = process_endpoint(
            req,
            image=UploadFile(file=io.BytesIO(b"fake img"), filename="i.jpg"),
            audio=UploadFile(file=io.BytesIO(_wav_bytes()), filename="a.wav"),
        )
        with results_lock:
            results.append(resp)

    with patch("pipeline.router.resolve_speech", fake_resolve), \
         patch("pipeline.tts.synthesize_text_stream", _fake_pcm_stream):
        t1 = threading.Thread(target=call, args=("turn-race-1",))
        t2 = threading.Thread(target=call, args=("turn-race-2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert len(results) == 2
    assert set(seen) == {
        ("glasses-race", "turn-race-1"),
        ("glasses-race", "turn-race-2"),
    }


# ─── Thêm sau review: Finding 1 (idempotency ca đang-chạy-dở) ─────────────


def test_duplicate_turn_id_in_flight_not_called_twice(stream_mode, tmp_path, monkeypatch):
    """Lượt 1 CÒN DANG DỞ (stream trả về của nó chưa được rút cạn — đúng ca
    "mất ACK giữa chừng, board tự thử lại" nêu trong comment của
    `_IDEMPOTENCY_CACHE`) thì lượt 2 cùng `X-Turn-Id` KHÔNG được chạy lại
    pipeline — phải đợi lượt 1 xong rồi dùng lại đúng kết quả đó.

    Đây là ca reviewer đã chứng minh bị hỏng trước khi sửa: gọi `process()`
    hai lần với header giống hệt nhau trong lúc `StreamingResponse` của lượt
    đầu chưa được tiêu thụ hết thì `router.resolve_speech` bị gọi HAI lần.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PROCESS_IDEMPOTENCY_WINDOW_SECONDS", 5.0)
    call_count = 0

    def fake_resolve(image, audio, opening_seconds=0.0):
        nonlocal call_count
        call_count += 1
        yield "xin chào"

    def multi_chunk_stream(text_chunks):
        for _ in text_chunks:
            pass
        yield b"\x01\x02" * 100
        yield b"\x03\x04" * 100

    headers = {"X-Device-Id": "glasses-inflight", "X-Turn-Id": "turn-inflight-1"}

    with patch("pipeline.router.resolve_speech", fake_resolve), \
         patch("pipeline.tts.synthesize_text_stream", multi_chunk_stream):
        req1 = _request(headers=headers)
        response1 = process_endpoint(
            req1,
            image=UploadFile(file=io.BytesIO(b"fake img"), filename="i.jpg"),
            audio=UploadFile(file=io.BytesIO(_wav_bytes()), filename="a.wav"),
        )
        assert call_count == 1  # lượt 1 đã chạy pipeline một lần

        second_result: dict = {}

        def call_second() -> None:
            req2 = _request(headers=headers)
            second_result["response"] = process_endpoint(
                req2,
                image=UploadFile(file=io.BytesIO(b"fake img"), filename="i.jpg"),
                audio=UploadFile(file=io.BytesIO(_wav_bytes()), filename="a.wav"),
            )

        t2 = threading.Thread(target=call_second)
        t2.start()
        # Cho luồng 2 đủ thời gian vào tới nhánh "wait" (đợi event) TRƯỚC khi
        # ta rút cạn lượt 1 — entry của lượt 1 vẫn "pending" tới lúc đó.
        time.sleep(0.2)
        assert call_count == 1, "lượt 2 KHÔNG được chạy pipeline trong lúc lượt 1 còn dở"

        # Rút cạn lượt 1 -> `_tee_and_cache` chạy hết vòng `for` ->
        # `_idempotent_finish` -> đánh thức lượt 2 đang đợi.
        async def _drain(agen):
            async for _ in agen:
                pass

        asyncio.run(_drain(response1.body_iterator))
        t2.join(timeout=10)

    assert call_count == 1, "lượt 2 phải dùng lại kết quả cũ, không tự chạy pipeline lần hai"
    assert "response" in second_result


# ─── Thêm sau review: Finding 4 (ContextVar sống sót qua ranh giới stream) ─


def test_bind_context_keeps_ids_after_process_returns(stream_mode, tmp_path, monkeypatch):
    """`_bind_context` phải giữ đúng device_id/turn_id cho phần audio sinh ra
    SAU KHI `process()` đã return — không chỉ cho mảnh đầu (mảnh đó tự nhiên
    đúng vì còn chung call stack).

    Mảnh TTS giả đầu tiên cố tình LỚN HƠN hẳn `AUDIO_PREROLL_SECONDS ×
    byte_rate` để `_stream_audio` trả quyền điều khiển lại cho `process()`
    NGAY sau mảnh đó — tức mảnh thứ hai chỉ được kéo sau khi hàm đã return.
    Xoá `_bind_context` (dùng thẳng `body`) sẽ khiến `seen_ctx[1]` thành
    `(None, None)` — đã tự kiểm bằng tay trước khi thêm test này.
    """
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)

    seen_ctx: list[tuple[str | None, str | None]] = []

    def recording_stream(text_chunks):
        for _ in text_chunks:
            pass
        seen_ctx.append((app_module.DEVICE_ID_CTX.get(), app_module.TURN_ID_CTX.get()))
        # To hơn hẳn mọi ngưỡng preroll hợp lý -> `_stream_audio` yield NGAY
        # sau mảnh này, không cần kéo thêm mảnh nào của TTS nữa.
        yield b"\x00\x00" * 200000
        seen_ctx.append((app_module.DEVICE_ID_CTX.get(), app_module.TURN_ID_CTX.get()))
        yield b"\x01\x01" * 100

    headers = {"X-Device-Id": "glasses-post-return", "X-Turn-Id": "turn-post-return"}

    with patch("pipeline.router.resolve_speech", return_value=iter(["xin chào"])), \
         patch("pipeline.tts.synthesize_text_stream", recording_stream):
        req = _request(headers=headers)
        response = process_endpoint(
            req,
            image=UploadFile(file=io.BytesIO(b"fake img"), filename="i.jpg"),
            audio=UploadFile(file=io.BytesIO(_wav_bytes()), filename="a.wav"),
        )
        # `process()` ĐÃ return ở đây. ContextVar của LUỒNG NÀY (thread chạy
        # test) đã bị `.reset()` trong `finally` của nó. Kéo tiếp response —
        # nếu `_bind_context` không hoạt động, mảnh thứ hai sẽ thấy
        # ContextVar rỗng thay vì giá trị của request.
        async def _drain(agen):
            async for _ in agen:
                pass

        asyncio.run(_drain(response.body_iterator))

    assert len(seen_ctx) == 2
    assert seen_ctx[0] == ("glasses-post-return", "turn-post-return")
    assert seen_ctx[1] == ("glasses-post-return", "turn-post-return")
