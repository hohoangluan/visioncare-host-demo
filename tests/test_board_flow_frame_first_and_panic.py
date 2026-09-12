"""Hai hành vi RIÊNG của kính, đo ở mức HTTP — ảnh đi trước, và nút ba nhịp.

Phạm vi nhiệm vụ của kính (người dùng chốt 2026-08-26): nó chỉ gửi ảnh + âm
thanh và phát lại âm thanh nhận về. Nhưng nó không gửi hai thứ đó trong CÙNG
một gói:

    bấm nút
      ├─ POST /frame    ảnh XGA, socket riêng, fire-and-forget  (T17)
      └─ POST /process  audio ADPCM — đi SAU, và KHÔNG kèm ảnh

Ảnh rời kính trong lúc âm thanh còn đang được nén. Đó là cả điểm mạnh (ảnh có
sẵn ở server trước khi câu nói kết thúc) lẫn chỗ dễ vỡ nhất: `/process` tới nơi
với phần `image` TRỐNG và phải tự tìm lại khung của đúng lượt đó trong
`services/frame_buffer`. Ghép nhầm lượt = trả lời về một khung hình khác.

`tests/test_frame_single_mode.py` đã kiểm `frame_buffer` ở mức hàm. File này
kiểm ĐÚNG cặp HTTP mà board thật gửi — hai request, hai socket, một `X-Turn-Id`
— cho từng chức năng cần ảnh.

Nửa sau là nút khẩn cấp ba nhịp. `tests/test_panic_button.py` đã kiểm phần
điều phối (không qua STT, không nhân đôi cuộc gọi). Ở đây kiểm phần mà người
dùng thật sự nhận được: lượt khẩn cấp có ra được BYTE AUDIO board phát được
hay không — kể cả khi nó gửi lên một gói TRỐNG RỖNG, đúng thứ firmware làm
(`api_client.cpp`: "PANIC: gui /process rong voi X-Trigger: emergency").
"""

from __future__ import annotations

import struct
import uuid
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
from app import app
from handlers import action_flow
from pipeline import adpcm
from schemas import Intent
from services.frame_buffer import frames

from tests.test_board_contract_every_function import (
    BOARD_ACCEPT, IMAGE, REPLY, TONE_HZ, TONE_PCM, _board_upload_audio,
    _decode, _peak_hz, _TAIL_SECONDS,
)

client = TestClient(app)

DEVICE = "glasses-01"

# Chỉ những chức năng THẬT SỰ đọc ảnh. Các chức năng còn lại (nhạc, gọi điện,
# chỉ đường) không đụng tới khung hình, nên gửi ảnh trước cho chúng cũng không
# kiểm chứng được gì.
IMAGE_CASES = [
    ("space",  "Mô tả xung quanh tôi.",       Intent.SPACE,  "handlers.describe_space"),
    ("ocr",    "Đọc giúp tôi tài liệu này.",  Intent.OCR,    "handlers.ocr"),
    ("find",   "Giúp tôi tìm gói bánh.",      Intent.FIND,   "handlers.find_object"),
    ("money",  "Tờ tiền này là bao nhiêu?",   Intent.MONEY,  "handlers.read_money"),
    ("hazard", "Phía trước có gì nguy hiểm?", Intent.HAZARD, "handlers.describe_hazard"),
]
IMAGE_IDS = [c[0] for c in IMAGE_CASES]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIO_PREROLL_SECONDS", 0.0)
    frames.clear()
    action_flow.reset_state()
    yield
    frames.clear()
    action_flow.reset_state()


def _post_frame(turn_id: str, body: bytes = IMAGE, device: str = DEVICE):
    """Đúng request đầu tiên board gửi: JPEG trần, không multipart."""
    return client.post(
        "/frame",
        content=body,
        headers={
            "Content-Type": "image/jpeg",
            "X-Device-Id": device,
            "X-Turn-Id": turn_id,
        },
    )


def _post_process_audio_only(text, intent, handler_module, turn_id, device=DEVICE):
    """Request thứ hai: CHỈ audio. Trả về (response, ảnh handler đã nhận)."""
    seen: list[bytes | None] = []

    def spy_handle(image, command_text, *a, **kw):
        seen.append(image)
        return iter([REPLY])

    def fake_tts(chunks):
        for _ in chunks:
            pass
        yield TONE_PCM

    with patch("pipeline.stt.transcribe", return_value=text), patch(
        "pipeline.intent.detect_with_params", return_value=(intent, {})
    ), patch("pipeline.tts.synthesize_text_stream", fake_tts), patch(
        f"{handler_module}.handle", side_effect=spy_handle
    ):
        response = client.post(
            "/process",
            files={"audio": ("record.wav", _board_upload_audio(), "audio/wav")},
            headers={
                "Accept": BOARD_ACCEPT,
                "X-Device-Id": device,
                "X-Turn-Id": turn_id,
            },
        )
    return response, (seen[0] if seen else None)


# ══════════════════════════════════════════════════════════════════════════
# 1. Ảnh đi TRƯỚC, `/process` đi sau và không mang ảnh
# ══════════════════════════════════════════════════════════════════════════


def test_frame_channel_answers_immediately_and_says_nothing():
    """Fire-and-forget: board không đọc thân trả về, nó gửi xong là quay sang
    nén audio. 204 + thân rỗng là cả hợp đồng."""
    response = _post_frame(uuid.uuid4().hex)
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.parametrize("case", IMAGE_CASES, ids=IMAGE_IDS)
def test_frame_sent_first_is_the_image_the_handler_reads(case):
    """Đường CHÍNH của board thật: hai request, hai socket, một `X-Turn-Id`.

    Handler phải nhận đúng byte ảnh đã đi lên ở request đầu — không phải None,
    không phải một khung của lượt khác.
    """
    _id, text, intent, handler_module = case
    turn_id = uuid.uuid4().hex

    assert _post_frame(turn_id).status_code == 204
    response, got_image = _post_process_audio_only(text, intent, handler_module, turn_id)

    assert response.status_code == 200
    assert got_image == IMAGE, "handler không nhận được khung đã gửi trước"


@pytest.mark.parametrize("case", IMAGE_CASES, ids=IMAGE_IDS)
def test_frame_first_turn_still_returns_adpcm_the_board_can_play(case):
    """Đi đường hai-request rồi thì thân trả về vẫn phải y hệt đường một-request
    — board không có nhánh riêng cho nó."""
    _id, text, intent, handler_module = case
    turn_id = uuid.uuid4().hex
    _post_frame(turn_id)
    response, _ = _post_process_audio_only(text, intent, handler_module, turn_id)

    assert response.headers["x-audio-encoding"] == "ima_adpcm"
    assert struct.unpack_from("<H", response.content, 20)[0] == adpcm.FORMAT_TAG
    decoded = _decode(response.content)
    tail = decoded[-int(_TAIL_SECONDS * adpcm.SAMPLE_RATE):]
    assert abs(_peak_hz(tail) - TONE_HZ) < 15


def test_a_frame_from_another_turn_is_never_reused():
    """Ghép nhầm lượt = trả lời về một khung hình người dùng đã đi qua từ lâu.
    Với người khiếm thị đó là câu trả lời SAI mà nghe vẫn rất trôi chảy."""
    other = b"\xff\xd8" + b"khung cua luot khac" * 40
    _post_frame(uuid.uuid4().hex, body=other)

    response, got_image = _post_process_audio_only(
        "Mô tả xung quanh tôi.", Intent.SPACE, "handlers.describe_space",
        uuid.uuid4().hex,
    )
    assert response.status_code == 200
    assert got_image != other


def test_a_frame_from_another_device_is_never_reused():
    """Hai kính cùng gọi lên một server. Khung của kính này không được rơi vào
    lượt của kính kia."""
    turn_id = uuid.uuid4().hex
    other = b"\xff\xd8" + b"khung cua kinh khac" * 40
    _post_frame(turn_id, body=other, device="glasses-02")

    response, got_image = _post_process_audio_only(
        "Mô tả xung quanh tôi.", Intent.SPACE, "handlers.describe_space", turn_id,
    )
    assert response.status_code == 200
    assert got_image != other


def test_process_still_answers_when_the_frame_never_arrived():
    """Ảnh đi trên socket RIÊNG, fire-and-forget: nó rớt được mà `/process` vẫn
    tới nơi. Board không có cách nào biết — nên server phải nói ra một câu, chứ
    không treo và cũng không trả mã lỗi."""
    response, got_image = _post_process_audio_only(
        "Mô tả xung quanh tôi.", Intent.SPACE, "handlers.describe_space",
        uuid.uuid4().hex,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")
    assert _decode(response.content).size > 0


def test_waiting_for_a_late_frame_is_bounded():
    """`FRAME_WAIT_MS` là trần chờ khung tới muộn. Không có trần thì một lượt
    mất ảnh sẽ treo tới hết `/process`, và board ngồi im giữa chừng."""
    assert config.FRAME_WAIT_MS > 0
    assert config.FRAME_WAIT_MS <= 2000, "chờ ảnh lâu quá thì người dùng nghe ra"
    assert config.FRAME_MAX_AGE_MS > config.FRAME_WAIT_MS


# ══════════════════════════════════════════════════════════════════════════
# 2. Nút khẩn cấp ba nhịp
# ══════════════════════════════════════════════════════════════════════════
#
# Kính đếm nhịp, KHÔNG phải server: `audio_service.cpp` gom ba nhịp trong
# `PANIC_WINDOW_MS` rồi mới gửi đúng MỘT request mang `X-Trigger: emergency`.
# Nên phần server phải kiểm là: một request như thế đi tới đâu, và người dùng
# nghe được gì.


def _panic_turn(turn_id: str | None = None, with_audio: bool = False,
                with_image: bool = False):
    """Đúng gói firmware gửi sau nhịp thứ ba — mặc định là gói TRỐNG."""
    spoken: list[str] = []
    called: list[bool] = []

    def fake_tts(chunks):
        spoken.append("".join(chunks))
        yield TONE_PCM

    def spy_emergency(*a, **kw):
        called.append(True)
        return iter(["Đang gọi cấp cứu."])

    files = {}
    if with_audio:
        files["audio"] = ("record.wav", _board_upload_audio(), "audio/wav")
    if with_image:
        files["image"] = ("capture.jpg", IMAGE, "image/jpeg")

    with patch("pipeline.tts.synthesize_text_stream", fake_tts), patch(
        "handlers.emergency_call.handle", side_effect=spy_emergency
    ), patch("pipeline.stt.transcribe", side_effect=AssertionError("STT đã chạy")):
        response = client.post(
            "/process",
            files=files or None,
            headers={
                "Accept": BOARD_ACCEPT,
                "X-Device-Id": DEVICE,
                "X-Turn-Id": turn_id or uuid.uuid4().hex,
                "X-Trigger": "emergency",
            },
        )
    return response, "".join(spoken), len(called)


def test_three_taps_reach_the_emergency_handler_with_an_empty_body():
    """Firmware gửi `/process` RỖNG sau nhịp thứ ba — không ảnh, không audio.
    Ba nhịp không cần tiếng và không cần mạng đủ tốt để đẩy 26 KB audio."""
    response, spoken, calls = _panic_turn()
    assert response.status_code == 200
    assert calls == 1
    assert spoken.strip()


def test_three_taps_produce_audio_the_board_can_actually_play():
    """Lượt khẩn cấp KHÔNG có nhánh audio riêng — cùng ADPCM, cùng header, cùng
    cách giải nén. Đây là lượt duy nhất người dùng không thể thử lại được nếu
    nó ra tiếng rè."""
    response, _, _ = _panic_turn()
    h = response.headers
    assert h["x-audio-encoding"] == "ima_adpcm"
    assert h["x-audio-channels"] == "1"
    assert h["x-audio-sample-rate"] == str(adpcm.SAMPLE_RATE)
    assert response.content[:4] == b"RIFF"
    assert struct.unpack_from("<H", response.content, 20)[0] == adpcm.FORMAT_TAG

    decoded = _decode(response.content)
    assert decoded.size > 0
    tail = decoded[-int(_TAIL_SECONDS * adpcm.SAMPLE_RATE):]
    assert abs(_peak_hz(tail) - TONE_HZ) < 15


def test_three_taps_never_run_speech_to_text_even_when_audio_is_attached():
    """Nhánh nhả-muộn của firmware gửi kèm cả đoạn đã thu. Chạy STT trên đó là
    mở lại đúng chỗ dễ vỡ mà nút ba nhịp sinh ra để tránh: người đang hoảng nói
    không thành tiếng, STT nghe ra chữ khác, và lượt cấp cứu đi sang intent
    khác. `patch(stt.transcribe)` ở đây nổ `AssertionError` nếu bị gọi."""
    response, _, calls = _panic_turn(with_audio=True, with_image=True)
    assert response.status_code == 200
    assert calls == 1


def test_the_board_retrying_the_same_press_does_not_place_two_calls():
    """Mất ACK giữa chừng thì board gửi lại cùng `X-Turn-Id`. Hai cuộc gọi cấp
    cứu cho một lần bấm là một sự cố thật, không phải phiền toái."""
    turn_id = uuid.uuid4().hex
    first, _, calls_first = _panic_turn(turn_id=turn_id)
    second, _, calls_second = _panic_turn(turn_id=turn_id)

    assert calls_first == 1
    assert calls_second == 0, "lượt trùng đã chạy lại pipeline"
    assert second.content == first.content


def test_one_tap_is_an_ordinary_turn_not_an_emergency():
    """Một nhịp = một lượt hỏi bình thường. Kính chỉ gắn `X-Trigger` sau nhịp
    thứ ba; thiếu header đó thì tuyệt đối không được rơi vào nhánh khẩn cấp."""
    called: list[bool] = []

    def fake_tts(chunks):
        for _ in chunks:
            pass
        yield TONE_PCM

    with patch("pipeline.stt.transcribe", return_value="Mô tả xung quanh tôi."), patch(
        "pipeline.intent.detect_with_params", return_value=(Intent.SPACE, {})
    ), patch("pipeline.tts.synthesize_text_stream", fake_tts), patch(
        "handlers.describe_space.handle", return_value=iter([REPLY])
    ), patch(
        "handlers.emergency_call.handle",
        side_effect=lambda *a, **kw: called.append(True) or iter([""]),
    ):
        response = client.post(
            "/process",
            files={
                "image": ("capture.jpg", IMAGE, "image/jpeg"),
                "audio": ("record.wav", _board_upload_audio(), "audio/wav"),
            },
            headers={"Accept": BOARD_ACCEPT, "X-Device-Id": DEVICE,
                     "X-Turn-Id": uuid.uuid4().hex},
        )

    assert response.status_code == 200
    assert called == [], "một nhịp đã gọi cấp cứu"


def test_three_taps_cut_off_whatever_is_already_playing():
    """Bấm khẩn cấp phải cắt ngang nhạc / chỉ đường / câu trả lời dài đang phát.
    `bump_generation()` là cơ chế làm việc đó; lượt cũ phải thành hết hạn."""
    before = action_flow.current_generation(DEVICE)
    _panic_turn()
    assert action_flow.current_generation(DEVICE) != before
