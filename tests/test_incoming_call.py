from __future__ import annotations

import json
import struct
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

import app as app_module
import config
import services.incoming_calls as incoming_calls_module
from handlers import action_flow
from handlers import incoming_call as incoming_call_handler
from pipeline import router
from services.events_channel import events
from services.incoming_calls import (
    IncomingCallRegistry,
    announcement_for,
    incoming_calls,
    sanitize_caller,
)


_BOARD_ACCEPT = "audio/wav;codec=ima_adpcm, audio/mpeg, audio/wav"
_PCM_ONE_BLOCK = b"\x00\x00" * 505


@pytest.fixture(autouse=True)
def _clean_call_state() -> None:
    incoming_calls.clear()
    audio_cache = getattr(incoming_calls_module, "incoming_call_audio", None)
    if audio_cache is not None:
        audio_cache.clear()
    events.clear()
    yield
    incoming_calls.clear()
    if audio_cache is not None:
        audio_cache.clear()
    events.clear()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.VISIONCARE_CALLBACK_TOKEN}"}


def _post(payload: dict[str, object]):
    return TestClient(app_module.app, client=("127.0.0.1", 12345)).post(
        "/internal/device-events", json=payload, headers=_headers()
    )


def _open_payload(caller: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "device_id": "glasses-a",
        "type": "call_incoming",
        "caller": (
            caller
            if caller is not None
            else {"contact_id": "contact-1", "name": "Mẹ", "number_tail": "456"}
        ),
    }


def test_cuts_tts_within_200ms() -> None:
    before = action_flow.current_generation("glasses-a")
    started = time.monotonic()
    response = _post(_open_payload())
    elapsed_ms = (time.monotonic() - started) * 1000

    assert response.status_code == 200
    assert action_flow.current_generation("glasses-a") == before + 1
    assert response.json()["data"]["interruption_ms"] < 200
    assert elapsed_ms < 200


def test_pending_survives_incoming_call() -> None:
    token = app_module.DEVICE_ID_CTX.set("glasses-a")
    try:
        pending = action_flow.set_pending(
            "contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?"
        )
        response = _post(_open_payload())
        assert response.status_code == 200
        assert action_flow.get_pending() is pending
    finally:
        action_flow.clear_pending()
        app_module.DEVICE_ID_CTX.reset(token)


def test_emergency_beats_incoming_call(monkeypatch: pytest.MonkeyPatch) -> None:
    incoming_calls.open("glasses-a", {"name": "Mẹ"})
    monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "gọi cấp cứu")
    with patch("handlers.emergency_call.handle", return_value=iter(("emergency",))) as emergency:
        assert list(router._resolve(None, b"audio", "glasses-a")) == ["emergency"]
    emergency.assert_called_once()
    assert incoming_calls.current("glasses-a") is not None


@pytest.mark.parametrize(
    ("spoken", "intent"),
    [("nghe máy", "call_answer"), ("nghe", "call_answer"), ("trả lời", "call_answer"),
     ("từ chối", "call_reject"), ("không nghe", "call_reject"), ("bỏ", "call_reject")],
)
def test_intent_window_15s(monkeypatch: pytest.MonkeyPatch, spoken: str, intent: str) -> None:
    registry = IncomingCallRegistry(window_seconds=15)
    registry.open("glasses-a", {}, now=100)
    assert registry.command("glasses-a", spoken, now=114.999) == intent
    assert registry.command("glasses-a", spoken, now=115) is None


def test_call_control_beats_pending_and_preserves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    token = app_module.DEVICE_ID_CTX.set("glasses-a")
    try:
        pending = action_flow.set_pending(
            "contact_name", "contact_call", {}, "Bạn muốn gọi cho ai?"
        )
        incoming_calls.open("glasses-a", {"name": "Mẹ"})
        monkeypatch.setattr(router.stt, "transcribe", lambda _audio: "nghe máy")
        with patch(
            "handlers.incoming_call.handle_answer", return_value=iter(("Đang nghe máy.",))
        ) as answer:
            assert list(router._resolve(None, b"audio", "glasses-a")) == ["Đang nghe máy."]
        answer.assert_called_once()
        assert action_flow.get_pending() is pending
        assert incoming_calls.current("glasses-a") is None
    finally:
        action_flow.clear_pending()
        app_module.DEVICE_ID_CTX.reset(token)


def test_window_closes_when_ringing_stops() -> None:
    assert _post(_open_payload()).status_code == 200
    response = _post({"device_id": "glasses-a", "type": "call_ended"})
    assert response.status_code == 200
    assert incoming_calls.current("glasses-a") is None


def test_call_ended_says_nothing() -> None:
    incoming_calls.open("glasses-a", {"name": "Mẹ"})
    response = _post({"device_id": "glasses-a", "type": "call_ended"})

    assert response.status_code == 200
    assert response.json()["data"].get("announcement") is None
    assert events.drain("glasses-a") == [{"type": "call_ended"}]


def test_incoming_event_tells_firmware_where_to_fetch_audio() -> None:
    response = _post(_open_payload())
    (event,) = events.drain("glasses-a")

    assert response.status_code == 200
    assert event["audio_url"] == "/incoming-call/audio"
    assert event["caller"] == {
        "contact_id": "contact-1",
        "name": "Mẹ",
        "number_tail": "456",
    }


def test_incoming_call_is_queued_even_if_the_glasses_are_mid_turn() -> None:
    """🔴 Đây là ca kênh SSE cũ hỏng, và là lý do đổi sang hộp thư.

    Board `eventStreamPause()` trước khi bấm nút để nhường 45 KB RAM cho phiên
    TLS của `/process`. Chuông đổ đúng lúc đó thì sự kiện biến mất — im lặng,
    không log, không ai biết. Hộp thư giữ nó tới lượt poll kế tiếp.
    """
    assert events.downlink_open("glasses-a") is False
    response = _post(_open_payload())
    assert response.status_code == 200
    assert response.json()["data"]["downlink_open"] is False
    assert events.queued_count("glasses-a") == 1


def test_incoming_call_response_reports_queue_and_channel_separately() -> None:
    """`queued` LUÔN ≥ 1; `downlink_open` mới là thứ nói kính có nghe được không.

    Kênh SSE cũ trộn hai thứ này vào một số (`subscribers`) và vì thế nói dối:
    `subscribers: 1` trong khi sự kiện rơi vào một generator đã chết.
    """
    events.drain("glasses-a")  # kính vừa poll
    data = _post(_open_payload()).json()["data"]
    assert data["queued"] >= 1
    assert data["downlink_open"] is True


def test_known_contact_reads_name() -> None:
    assert announcement_for({"contact_id": "1", "name": "Mẹ", "number_tail": "456"}) == (
        "Có cuộc gọi từ Mẹ đang gọi."
    )


def test_unknown_number_reads_digits() -> None:
    assert announcement_for({"number_tail": "456"}) == "Số lạ, đuôi bốn năm sáu."


def test_duplicate_name_adds_tail() -> None:
    assert announcement_for(
        {"contact_id": "1", "name": "Mẹ", "number_tail": "789", "duplicate_name": True}
    ) == "Có cuộc gọi từ Mẹ, đuôi bảy tám chín, đang gọi."


@pytest.mark.parametrize(
    "caller",
    [
        {"number": "0901234567"},
        {"full_number": "0901234567"},
        {"number_tail": "12345"},
        {"name": "090 123 4567"},
    ],
)
def test_never_accepts_full_number(caller: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        sanitize_caller(caller)


def test_announce_caller_number_only() -> None:
    assert announcement_for({"contact_id": "1", "number_tail": "456"}) == (
        "Số gọi đến, đuôi bốn năm sáu."
    )


def test_announce_caller_ring_only() -> None:
    assert announcement_for({}) is None


def test_static_parts_prebuilt() -> None:
    """T19 4.3: represent the reusable fragments without splicing their PCM.

    The current phrase cache is sentence-granular.  The complete announcement
    is cached below so its prosody remains natural; these constants keep the
    policy-safe static text explicit for a future prosody-safe fragment cache.
    """
    static_parts = getattr(incoming_calls_module, "INCOMING_CALL_STATIC_PARTS", None)
    assert static_parts == ("Có cuộc gọi từ ", " đang gọi.")
    assert announcement_for({"contact_id": "1", "name": "Mẹ"}) == (
        static_parts[0] + "Mẹ" + static_parts[1]
    )


def test_incoming_audio_prelude_precedes_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    caller = {"contact_id": "contact-1", "name": "Mẹ", "number_tail": "456"}
    synthesized = False

    def synthesize(_pieces):
        nonlocal synthesized
        synthesized = True
        return iter([_PCM_ONE_BLOCK])

    monkeypatch.setattr(app_module.tts, "synthesize_text_stream", synthesize)
    stream = app_module._incoming_call_audio_stream(
        caller, app_module._plan_for("adpcm_wav", 0)
    )

    assert next(stream) == app_module.adpcm.wav_header(None)
    assert synthesized is False
    assert b"".join(stream)
    assert synthesized is True


def test_incoming_audio_uses_board_format(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _post(_open_payload()).status_code == 200
    monkeypatch.setattr(
        app_module.tts,
        "synthesize_text_stream",
        lambda _pieces: iter([_PCM_ONE_BLOCK]),
    )

    response = TestClient(app_module.app).get(
        "/incoming-call/audio",
        headers={"X-Device-Id": "glasses-a", "Accept": _BOARD_ACCEPT},
    )

    assert response.status_code == 200
    assert response.headers["x-audio-encoding"] == "ima_adpcm"
    assert response.headers["x-audio-sample-rate"] == "16000"
    assert response.headers["x-audio-channels"] == "1"
    assert response.content[:4] == b"RIFF"
    assert struct.unpack_from("<H", response.content, 20)[0] == app_module.adpcm.FORMAT_TAG
    assert struct.unpack_from("<H", response.content, 22)[0] == 1
    assert struct.unpack_from("<I", response.content, 24)[0] == 16000


def test_tts_cached_per_contact_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def synthesize(pieces):
        calls.append(list(pieces))
        return iter([_PCM_ONE_BLOCK])

    monkeypatch.setattr(app_module.tts, "synthesize_text_stream", synthesize)
    client = TestClient(app_module.app)

    assert _post(_open_payload()).status_code == 200
    first = client.get(
        "/incoming-call/audio",
        headers={"X-Device-Id": "glasses-a", "Accept": _BOARD_ACCEPT},
    )
    assert _post(_open_payload()).status_code == 200
    second = client.get(
        "/incoming-call/audio",
        headers={"X-Device-Id": "glasses-a", "Accept": _BOARD_ACCEPT},
    )

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert calls == [["Có cuộc gọi từ Mẹ đang gọi."]]


def test_tts_cache_separates_callers_and_policy_phrases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def synthesize(pieces):
        phrase = "".join(pieces)
        calls.append(phrase)
        sample = len(calls).to_bytes(2, "little", signed=True)
        return iter([sample * 505])

    monkeypatch.setattr(app_module.tts, "synthesize_text_stream", synthesize)
    client = TestClient(app_module.app)

    for caller in (
        {"contact_id": "contact-1", "name": "Mẹ", "number_tail": "456"},
        {"contact_id": "contact-2", "name": "Mẹ", "number_tail": "789"},
        {"contact_id": "contact-1", "number_tail": "456"},
    ):
        assert _post(_open_payload(caller)).status_code == 200
        assert client.get(
            "/incoming-call/audio",
            headers={"X-Device-Id": "glasses-a", "Accept": _BOARD_ACCEPT},
        ).status_code == 200

    assert calls == [
        "Có cuộc gọi từ Mẹ đang gọi.",
        "Có cuộc gọi từ Mẹ đang gọi.",
        "Số gọi đến, đuôi bốn năm sáu.",
    ]


def test_incoming_audio_requires_active_spoken_announcement() -> None:
    client = TestClient(app_module.app)
    assert client.get(
        "/incoming-call/audio", headers={"X-Device-Id": "glasses-a"}
    ).status_code == 404

    assert _post(_open_payload({})).status_code == 200
    assert client.get(
        "/incoming-call/audio", headers={"X-Device-Id": "glasses-a"}
    ).status_code == 204


def test_device_event_does_not_require_request_id() -> None:
    response = _post(_open_payload())
    assert response.status_code == 200
    assert response.json()["data"]["type"] == "call_incoming"


def test_device_event_rejects_full_number() -> None:
    response = _post(_open_payload({"number": "0901234567"}))
    assert response.status_code == 422
    assert "0901234567" not in response.text


def test_device_event_requires_internal_auth() -> None:
    response = TestClient(app_module.app, client=("127.0.0.1", 12345)).post(
        "/internal/device-events", json=_open_payload()
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("handler", "endpoint", "ack"),
    [
        (incoming_call_handler.handle_answer, "api/v1/service/call/answer", "Đang nghe máy."),
        (incoming_call_handler.handle_reject, "api/v1/service/call/reject", "Đã từ chối cuộc gọi."),
    ],
)
def test_call_control_uses_host_action_pipeline(
    monkeypatch: pytest.MonkeyPatch, handler, endpoint: str, ack: str
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def accept(path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((path, payload))
        return {"data": {"request_id": payload["request_id"]}}

    monkeypatch.setattr(action_flow, "call_service_api", accept)
    stream = handler(None, "", {})
    assert next(stream) == ack + "\n"
    stream.close()

    assert calls[0][0] == endpoint
    assert set(calls[0][1]) == {"request_id"}
