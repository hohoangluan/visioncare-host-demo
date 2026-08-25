"""Nút khẩn cấp: bấm 3 lần trên gọng kính ≡ nói "gọi cấp cứu".

Vì sao khoá bằng test chứ không chỉ đọc code
---------------------------------------------
Đường này chạy đúng lúc mọi thứ khác đang hỏng — người ngã, nói không thành
tiếng, mic tắc. Không ai bấm thử nó hàng ngày để phát hiện nó gãy, nên nó là
đúng loại tính năng chết âm thầm rồi vẫn nằm trong tài liệu như đang chạy.

Bốn ràng buộc dưới đây là những chỗ một lần refactor vô ý sẽ phá:

1. panic KHÔNG được chạy STT — nếu nó chạy, tính năng mất hết lý do tồn tại;
2. panic KHÔNG được rơi vào câu "không nhận được tiếng nói" (nó cố ý không
   mang audio);
3. panic PHẢI huỷ lượt đang chạy (nhạc/chỉ đường/câu trả lời dài);
4. request THƯỜNG không mang header thì phải cư xử y như cũ.
"""

import io
import wave
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
import config
from app import app
from pipeline import router


client = TestClient(app, client=("127.0.0.1", 12345))

PANIC_HEADERS = {
    "X-Device-Id": "glasses-01",
    "X-Trigger": "emergency",
}


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


@pytest.fixture
def captured_pieces(monkeypatch):
    """Chặn ở tầng text: khỏi chạy TTS thật mà vẫn thấy đúng cái sẽ đọc lên."""
    seen: list[str] = []

    def fake_stream(pieces, *args, **kwargs):
        seen.extend(pieces)
        yield b"\x00" * 64

    monkeypatch.setattr(app_module, "_stream_audio", fake_stream)
    return seen


# ---------------------------------------------------------------- 1. không STT

def test_panic_never_runs_speech_to_text(captured_pieces):
    """Cả lý do tồn tại của nút nằm ở dòng assert này.

    Nếu một ngày ai đó "gộp cho gọn" đường panic vào `resolve_speech`, test
    này đỏ trước khi người dùng phát hiện bằng cách bấm nút mà không ai tới.
    """
    with patch("pipeline.stt.transcribe") as transcribe, patch(
        "pipeline.router._dispatch"
    ) as dispatch:
        dispatch.return_value = iter(["đang gọi cấp cứu"])
        response = client.post("/process", headers=PANIC_HEADERS)

    assert response.status_code == 200
    transcribe.assert_not_called()


def test_panic_dispatches_emergency_call(captured_pieces):
    with patch("pipeline.router._dispatch") as dispatch:
        dispatch.return_value = iter(["đang gọi cấp cứu"])
        client.post("/process", headers=PANIC_HEADERS)

    assert dispatch.called
    assert dispatch.call_args.args[0] == "emergency_call"


def test_panic_passes_no_emergency_number():
    """Nút không mang được con số — handler phải tự lùi về số mặc định.

    Nhồi một số bịa vào đây sẽ gọi nhầm số, và đó là kiểu lỗi chỉ lộ ra đúng
    lúc thật.
    """
    with patch("pipeline.router._dispatch") as dispatch:
        dispatch.return_value = iter(["ok"])
        client.post("/process", headers=PANIC_HEADERS)

    params = dispatch.call_args.args[3]
    assert "emergency_number" not in params


# ------------------------------------------- 2. không rơi vào "thiếu audio"

def test_panic_without_audio_does_not_say_missing_audio(captured_pieces):
    with patch("pipeline.router._dispatch") as dispatch:
        dispatch.return_value = iter(["đang gọi cấp cứu"])
        client.post("/process", headers=PANIC_HEADERS)

    spoken = " ".join(captured_pieces)
    assert app_module._MISSING_AUDIO_MESSAGE not in spoken
    assert "cấp cứu" in spoken


# --------------------------------------------------- 3. cắt ngang lượt đang chạy

def test_panic_bumps_generation_to_cancel_whatever_is_playing():
    """Nhạc đang phát, chỉ đường đang đọc — bấm khẩn cấp phải cắt hết."""
    with patch("handlers.action_flow.bump_generation") as bump, patch(
        "pipeline.router._dispatch"
    ) as dispatch:
        dispatch.return_value = iter(["ok"])
        list(router.resolve_panic(None))

    assert bump.called


# ------------------------------------------------------ 4. đường thường nguyên vẹn

def test_request_without_trigger_header_is_unchanged(captured_pieces):
    """Không có header thì thiếu audio VẪN là câu "không nhận được tiếng nói"."""
    response = client.post("/process", headers={"X-Device-Id": "glasses-01"})

    assert response.status_code == 200
    assert app_module._MISSING_AUDIO_MESSAGE in " ".join(captured_pieces)


def test_unknown_trigger_value_is_not_treated_as_panic(captured_pieces):
    """Chỉ đúng chữ `emergency` mới kích hoạt.

    Header lạ (proxy chèn, bản firmware cũ, gõ sai) không được biến một lượt
    thường thành cuộc gọi cấp cứu — sai theo chiều này tốn của người khác một
    chuyến xe cứu thương.
    """
    response = client.post(
        "/process", headers={"X-Device-Id": "glasses-01", "X-Trigger": "nothing"}
    )

    assert response.status_code == 200
    assert app_module._MISSING_AUDIO_MESSAGE in " ".join(captured_pieces)


def test_trigger_header_is_case_insensitive(captured_pieces):
    """Firmware viết hoa/thường tuỳ bản — không được để chữ hoa làm hỏng nút."""
    with patch("pipeline.router._dispatch") as dispatch:
        dispatch.return_value = iter(["đang gọi cấp cứu"])
        client.post(
            "/process",
            headers={"X-Device-Id": "glasses-01", "X-Trigger": "EMERGENCY"},
        )

    assert dispatch.called
    assert dispatch.call_args.args[0] == "emergency_call"


def test_panic_with_audio_still_skips_stt(captured_pieces):
    """Board có thể lỡ kèm audio. Header vẫn thắng.

    Ngược lại (audio thắng header) nghĩa là một tiếng ồn ngẫu nhiên lúc bấm
    nút có thể lái lượt sang intent khác — đúng thứ nút sinh ra để tránh.
    """
    with patch("pipeline.stt.transcribe") as transcribe, patch(
        "pipeline.router._dispatch"
    ) as dispatch:
        dispatch.return_value = iter(["đang gọi cấp cứu"])
        client.post(
            "/process",
            headers=PANIC_HEADERS,
            files={"audio": ("a.wav", _wav_bytes(), "audio/wav")},
        )

    transcribe.assert_not_called()


def test_panic_reuses_idempotency_so_repeat_presses_do_not_double_call():
    """Hai request cùng `X-Turn-Id` = MỘT cuộc gọi.

    Nút bấm dồn dập rất dễ sinh hai request cho cùng một sự kiện, và hai
    chuyến xe cứu thương là một sự cố thật, không phải phiền toái nhỏ.
    """
    headers = dict(PANIC_HEADERS, **{"X-Turn-Id": "panic-turn-1"})
    with patch("pipeline.router._dispatch") as dispatch:
        dispatch.side_effect = lambda *a, **k: iter(["đang gọi cấp cứu"])
        first = client.post("/process", headers=headers)
        assert first.status_code == 200
        first.read()
        second = client.post("/process", headers=headers)
        assert second.status_code == 200
        second.read()

    assert dispatch.call_count == 1, (
        f"gọi {dispatch.call_count} lần cho cùng một X-Turn-Id — "
        "idempotency của /process không còn che được nút bấm dồn"
    )
