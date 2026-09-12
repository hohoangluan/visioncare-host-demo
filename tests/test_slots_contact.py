"""T08 — luồng contact_call qua pending, readback và chọn ứng viên."""

from contextlib import contextmanager
import time
from unittest.mock import patch

import pytest

import app as app_module
from handlers import action_flow, phone, result_speech, slots
from pipeline import router
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


@contextmanager
def _device(device_id: str):
    token = app_module.DEVICE_ID_CTX.set(device_id)
    try:
        yield
    finally:
        app_module.DEVICE_ID_CTX.reset(token)


def _stub_flow(monkeypatch, *, state="succeeded", result=None, error=None):
    calls = []

    def fake_call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"status": "ok", "data": {"request_id": f"req-{len(calls)}"}}

    def fake_status(request_id):
        return {"request_state": state, "result": result or {}, "error": error}

    monkeypatch.setattr(action_flow, "call_service_api", fake_call)
    monkeypatch.setattr(action_flow, "get_request_status", fake_status)
    return calls


def _multiple_error():
    return {
        "code": "MULTIPLE_CONTACTS_FOUND",
        "details": {
            "candidates": [
                {"name": "Nguyễn Nguyệt Anh", "phone_number": "***456", "contact_id": "c1"},
                {"name": "Nguyễn Minh Anh", "phone_number": "***789", "contact_id": "c2"},
                {"name": "Lan Anh", "phone_number": "***012", "contact_id": "c3"},
            ]
        },
    }


def test_contact_missing_name_two_turns(monkeypatch):
    calls = _stub_flow(
        monkeypatch,
        result={"call_state": "calling", "contact_name": "Mẹ"},
    )
    first = "".join(phone.handle_contact(b"", "gọi điện đi", {}))
    pending = action_flow.get_pending()
    assert first == slots.SLOTS["contact_name"].ask
    assert pending is not None and pending.slot == "contact_name"

    with (
        patch("pipeline.stt.transcribe", return_value="mẹ"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.CONTACT_CALL, {"contact_name": "Mẹ", "slot_confidence": "high"}),
        ),
    ):
        second = "".join(router.resolve_speech(None, b"dummy"))

    assert calls and calls[0][1]["name"] == "Mẹ"
    assert "Đang gọi cho Mẹ" in second
    assert action_flow.get_pending() is None


def test_contact_pending_ttl_expired(monkeypatch):
    phone_pending = action_flow.set_pending(
        "contact_name", Intent.CONTACT_CALL, {}, slots.SLOTS["contact_name"].ask
    )
    phone_pending.asked_at = time.monotonic() - 121

    with (
        patch("pipeline.stt.transcribe", return_value="mẹ"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", return_value=iter(["trả lời như chat"])),
        patch("handlers.contact_call.handle") as contact,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert out == "trả lời như chat"
    contact.assert_not_called()
    assert action_flow.get_pending() is None


def test_contact_pending_yields_to_stop_command(monkeypatch):
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    action_flow.set_pending(
        "contact_name", Intent.CONTACT_CALL, {}, slots.SLOTS["contact_name"].ask
    )
    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("handlers.music_stop.handle", return_value=iter(["Đang dừng nhạc."])) as stop,
        patch("handlers.contact_call.handle") as contact,
    ):
        out = "".join(router.resolve_speech(None, b"dummy"))

    assert "dừng nhạc" in out
    stop.assert_called_once()
    contact.assert_not_called()


def test_contact_attempt_max(monkeypatch):
    _stub_flow(monkeypatch, state="failed", error={"code": "CONTACT_NOT_FOUND"})
    outputs = []
    for name in ("Mê", "Mề", "Mẹ"):
        current = action_flow.get_pending()
        known = dict(current.known) if current is not None else {}
        known["contact_name"] = name
        outputs.append("".join(phone.handle_contact(b"", name, known)))

    pending = action_flow.get_pending()
    assert pending is not None and pending.attempt == 3
    assert pending.question != slots.SLOTS["contact_name"].ask
    assert pending.question in outputs[-1]


def test_multiple_contacts_reads_real_names(monkeypatch):
    _stub_flow(monkeypatch, state="failed", error=_multiple_error())
    out = "".join(phone.handle_contact(b"", "gọi Anh", {"contact_name": "Anh"}))
    pending = action_flow.get_pending()

    assert "Nguyễn Nguyệt Anh" in out and "Nguyễn Minh Anh" in out and "Lan Anh" in out
    assert "vui lòng nói rõ hơn" not in out.lower()
    assert pending is not None and pending.slot == "contact_selection"
    assert pending.kind == "select" and len(pending.candidates) == 3


def test_contact_selection_by_ordinal(monkeypatch):
    calls = _stub_flow(monkeypatch, state="failed", error=_multiple_error())
    "".join(phone.handle_contact(b"", "gọi Anh", {"contact_name": "Anh"}))
    monkeypatch.setattr(
        action_flow,
        "get_request_status",
        lambda request_id: {
            "request_state": "succeeded",
            "result": {"contact_name": "Nguyễn Minh Anh"},
            "error": None,
        },
    )

    with patch("pipeline.stt.transcribe", return_value="người thứ hai"):
        "".join(router.resolve_speech(None, b"dummy"))

    assert calls[-1][1]["contact_id"] == "c2"
    assert "name" not in calls[-1][1]


def test_contact_selection_by_name(monkeypatch):
    calls = _stub_flow(monkeypatch, state="failed", error=_multiple_error())
    "".join(phone.handle_contact(b"", "gọi Anh", {"contact_name": "Anh"}))
    monkeypatch.setattr(
        action_flow,
        "get_request_status",
        lambda request_id: {
            "request_state": "succeeded",
            "result": {"contact_name": "Nguyễn Nguyệt Anh"},
            "error": None,
        },
    )

    with (
        patch("pipeline.stt.transcribe", return_value="gọi Nguyệt"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.CONTACT_CALL, {"contact_name": "Nguyệt", "slot_confidence": "high"}),
        ),
    ):
        "".join(router.resolve_speech(None, b"dummy"))

    assert calls[-1][1]["contact_id"] == "c1"
    assert "name" not in calls[-1][1]


def test_contact_not_found_sets_pending(monkeypatch):
    _stub_flow(monkeypatch, state="failed", error={"code": "CONTACT_NOT_FOUND"})
    out = "".join(phone.handle_contact(b"", "Ai Đó", {"contact_name": "Ai Đó"}))
    pending = action_flow.get_pending()
    assert pending is not None
    assert pending.slot == "contact_name" and pending.intent == Intent.CONTACT_CALL
    assert pending.question in out


def test_low_confidence_reads_back_before_send(monkeypatch):
    calls = _stub_flow(monkeypatch)
    out = "".join(
        phone.handle_contact(
            b"", "gọi Nguyệt Anh", {"contact_name": "Nguyệt Anh", "slot_confidence": "low"}
        )
    )
    pending = action_flow.get_pending()

    assert calls == []
    assert "Nguyệt Anh" in out and "đúng không" in out
    assert pending is not None and pending.kind == "confirm"
    assert pending.known["contact_confirmed"] is True


def test_high_confidence_sends_immediately(monkeypatch):
    calls = _stub_flow(monkeypatch, result={"contact_name": "Nguyệt Anh"})
    "".join(
        phone.handle_contact(
            b"", "gọi Nguyệt Anh", {"contact_name": "Nguyệt Anh", "slot_confidence": "high"}
        )
    )
    assert calls and calls[0][1]["name"] == "Nguyệt Anh"
    assert action_flow.get_pending() is None


def test_contact_id_replaces_name(monkeypatch):
    calls = _stub_flow(monkeypatch, result={"contact_name": "Mẹ"})
    "".join(
        phone.handle_contact(
            b"",
            "người đầu",
            {"contact_name": "Mẹ", "contact_id": "raw-42", "slot_confidence": "high"},
        )
    )
    payload = calls[0][1]
    assert payload["contact_id"] == "raw-42"
    assert "name" not in payload


def test_contact_pending_is_isolated_by_device():
    with _device("glasses-A"):
        "".join(phone.handle_contact(b"", "gọi đi", {}))
        assert action_flow.get_pending() is not None

    with _device("glasses-B"):
        assert action_flow.get_pending() is None


@pytest.mark.xfail(
    strict=True,
    reason="T08/P1: app Android chưa có action contact_list để server resolve tên đặt lạ",
)
def test_contact_list_resolves_unusual_name_without_exact_app_match():
    """P1 là đường chính cho tên như “Em iu”; giữ đỏ công khai tới khi app làm."""
    assert hasattr(phone, "refresh_contact_list")


def test_speak_result_returns_pieces_and_pending_for_real_candidates():
    pieces, pending = result_speech.speak_result(
        "contact_call",
        {"request_state": "failed", "error": _multiple_error()},
    )
    assert isinstance(pieces, tuple)
    assert pending is not None and pending.slot == "contact_selection"
    assert result_speech._MULTIPLE_CONTACTS_PREFIX in result_speech.STATIC_SPEECH
    assert result_speech._CONTACT_SELECTION_QUESTION in result_speech.STATIC_SPEECH
    assert all(name not in result_speech.STATIC_SPEECH for name in ("Nguyễn Nguyệt Anh", "Lan Anh"))
