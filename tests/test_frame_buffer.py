from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient
import pytest

from app import DEVICE_ID_CTX, app
from handlers import action_flow
from pipeline import router
from services.frame_buffer import FrameBuffer, frames


@pytest.fixture(autouse=True)
def _clear_global_frames() -> None:
    frames.clear()
    action_flow.reset_state()
    yield
    frames.clear()
    action_flow.reset_state()


def test_frame_before_process() -> None:
    buffer = FrameBuffer()
    buffer.put("device-1", "turn-1", b"before")
    assert buffer.latest("device-1", 1000, turn_id="turn-1") == b"before"


def test_frame_after_process() -> None:
    buffer = FrameBuffer()
    result: list[bytes | None] = []

    waiter = threading.Thread(
        target=lambda: result.append(
            buffer.latest("device-1", 1000, turn_id="turn-1", wait_ms=300)
        )
    )
    waiter.start()
    time.sleep(0.02)
    buffer.put("device-1", "turn-1", b"after")
    waiter.join(timeout=1)
    assert result == [b"after"]


def test_frame_never_arrives() -> None:
    buffer = FrameBuffer()
    assert buffer.latest("device-1", 1000, turn_id="turn-1", wait_ms=10) is None


def test_frame_older_than_max_age() -> None:
    buffer = FrameBuffer()
    buffer.put(
        "device-1",
        "turn-1",
        b"old",
        received_at=time.monotonic() - 2,
    )
    assert buffer.latest("device-1", 100, turn_id="turn-1") is None


def test_ring_keeps_latest() -> None:
    buffer = FrameBuffer(ring_size=3)
    for index in range(5):
        buffer.put("device-1", f"turn-{index}", str(index).encode())
    assert [frame.data for frame in buffer.snapshot("device-1")] == [b"2", b"3", b"4"]
    assert buffer.latest("device-1", 1000) == b"4"


def test_frames_isolated_per_device() -> None:
    buffer = FrameBuffer()
    buffer.put("device-a", "turn-1", b"a")
    buffer.put("device-b", "turn-1", b"b")
    assert buffer.latest("device-a", 1000, turn_id="turn-1") == b"a"
    assert buffer.latest("device-b", 1000, turn_id="turn-1") == b"b"


def test_frame_matched_by_turn_id() -> None:
    buffer = FrameBuffer()
    buffer.put("device-1", "turn-old", b"wrong")
    assert buffer.latest("device-1", 1000, turn_id="turn-new") is None


def test_frame_endpoint_is_fire_and_forget_204() -> None:
    client = TestClient(app)
    response = client.post(
        "/frame",
        content=b"jpeg",
        headers={"X-Device-Id": "device-1", "X-Turn-Id": "turn-1"},
    )
    assert response.status_code == 204
    assert response.content == b""
    assert frames.latest("device-1", 1000, turn_id="turn-1") == b"jpeg"


@pytest.mark.parametrize("headers", [{}, {"X-Device-Id": "device-1"}, {"X-Turn-Id": "turn-1"}])
def test_frame_endpoint_requires_identity(headers: dict[str, str]) -> None:
    response = TestClient(app).post("/frame", content=b"jpeg", headers=headers)
    assert response.status_code == 400


def test_image_free_intents_never_wait_for_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    image_free = (
        "chat",
        "music_play",
        "music_stop",
        "music_volume",
        "nav_start",
        "nav_stop",
        "contact_call",
        "emergency_call",
        "ride_quote",
        "ride_confirm",
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("image-free intent waited for a frame")

    monkeypatch.setattr(router.frames, "latest", forbidden)
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "command")
    monkeypatch.setattr(router, "_dispatch", lambda *_args, **_kwargs: iter(("ok",)))
    for intent_name in image_free:
        monkeypatch.setattr(
            router.intent_mod,
            "detect_with_params",
            lambda _text, _state, value=intent_name: (value, {}),
        )
        assert "ok" in "".join(router._resolve(None, b"audio", "device-1", "turn-1"))


def test_emergency_never_waits_for_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router.frames,
        "latest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("emergency must never wait for a frame")
        ),
    )
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "gọi khẩn cấp")
    monkeypatch.setattr(
        router.intent_mod,
        "detect_with_params",
        lambda _text, _state: ("emergency_call", {}),
    )
    monkeypatch.setattr(router, "_dispatch", lambda *_args, **_kwargs: iter(("ok",)))
    assert "ok" in "".join(router._resolve(None, b"audio", "device-1", "turn-1"))


@pytest.mark.parametrize("reply", ["cancelled", "repeated"])
def test_cancel_repeat_never_wait_for_frame(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    monkeypatch.setattr(
        router.frames,
        "latest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cancel/repeat must never wait for a frame")
        ),
    )
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "command")
    monkeypatch.setattr(router, "_try_global_cancel_repeat", lambda *_args: reply)
    assert reply in "".join(router._resolve(None, b"audio", "device-1", "turn-1"))


def test_pending_answer_does_not_request_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    token = DEVICE_ID_CTX.set("device-1")
    try:
        action_flow.set_pending(
            "confirm_call",
            "contact_call",
            {},
            "Bạn có chắc muốn gọi không?",
            kind="confirm",
        )
        monkeypatch.setattr(
            router.frames,
            "latest",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("pending answer must never wait for a frame")
            ),
        )
        monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "ừ")
        monkeypatch.setattr(
            router,
            "_resolve_deterministic_pending",
            lambda *_args, **_kwargs: iter(("ok",)),
        )
        assert "ok" in "".join(
            router._resolve(None, b"audio", "device-1", "turn-1")
        )
    finally:
        DEVICE_ID_CTX.reset(token)


def test_ocr_followup_does_not_request_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    action_flow.remember_ocr("Nội dung cũ", device_key="device-1")
    monkeypatch.setattr(
        router.frames,
        "latest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("OCR follow-up must reuse cached text without a frame")
        ),
    )
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "đọc dòng hai")
    monkeypatch.setattr(
        router.intent_mod,
        "detect_with_params",
        lambda _text, _state: ("ocr", {"ocr_followup": True}),
    )
    monkeypatch.setattr(router, "_dispatch", lambda *_args, **_kwargs: iter(("ok",)))
    assert "ok" in "".join(router._resolve(None, b"audio", "device-1", "turn-1"))


def test_router_uses_matching_frame_without_changing_handler_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames.put("device-1", "turn-1", b"split-frame")
    seen: list[bytes | None] = []
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "đọc chữ")
    monkeypatch.setattr(
        router.intent_mod,
        "detect_with_params",
        lambda _text, _state: ("ocr", {}),
    )
    monkeypatch.setattr(router.image_quality, "reject_reason", lambda _intent, image: None)

    def dispatch(_intent: str, image: bytes | None, *_args: object, **_kwargs: object):
        seen.append(image)
        return iter(("ok",))

    monkeypatch.setattr(router, "_dispatch", dispatch)
    list(router._resolve(None, b"audio", "device-1", "turn-1"))
    assert seen == [b"split-frame"]


def test_legacy_multipart_image_bypasses_frame_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "đọc chữ")
    monkeypatch.setattr(
        router.intent_mod,
        "detect_with_params",
        lambda _text, _state: ("ocr", {}),
    )
    monkeypatch.setattr(router.image_quality, "reject_reason", lambda _intent, image: None)
    monkeypatch.setattr(
        router.frames,
        "latest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy image must not query FrameBuffer")
        ),
    )
    seen: list[bytes | None] = []
    monkeypatch.setattr(
        router,
        "_dispatch",
        lambda _intent, image, *_args, **_kwargs: seen.append(image) or iter(("ok",)),
    )
    list(router._resolve(b"multipart-image", b"audio", "device-1", "turn-1"))
    assert seen == [b"multipart-image"]
