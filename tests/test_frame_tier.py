"""F5 — ảnh phân tầng (SPEC mục 19, T17).

    gửi NGAY, không hỏi : tầng THẤP (VGA 640×480) -> space / hazard / find / money
    gửi khi server XIN  : tầng CAO  (HD 1280×720) -> CHỈ ocr

🔴 F5 được viết trong SPEC từ đầu nhưng **chưa thi công lần nào** cho tới
2026-08-25 — T17 vẫn ghi "F3/F4 code + test xanh; F5 và số board thật còn chờ".
Trong suốt thời gian đó **mọi** chức năng đều nhận HD 1280×720, kể cả vòng canh
vật cản chạy liên tục, trong khi model độ sâu resize mọi khung về 308×308 và
YOLO letterbox về 640×640.

Tên test lấy đúng từ phác thảo ở `docs/tasks/T17-frame-channel.md` mục 4.4.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from app import app
from schemas import Intent
from services.frame_buffer import FrameBuffer, frames


def _fake_wav() -> bytes:
    import struct

    pcm = b"\x00\x00" * 1600
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


# ── hợp đồng HTTP ─────────────────────────────────────────────────────────
def test_frame_tier_defaults_to_low_when_the_header_is_missing():
    """Board bản cũ không gửi `X-Frame-Tier`. Mặc định phải là tầng THẤP.

    Giả định ngược lại ("chắc là high") chỉ có một hậu quả: server dùng một
    khung VGA cho `ocr` mà tưởng là HD, rồi áp ngưỡng độ nét của HD lên nó.
    Mặc định "low" thì tệ nhất chỉ là xin thêm một khung.
    """
    response = TestClient(app).post(
        "/frame",
        content=b"\xff\xd8jpeg",
        headers={"X-Device-Id": "glasses-tier", "X-Turn-Id": "t1"},
    )
    assert response.status_code == 204
    frame = frames.latest_frame("glasses-tier", 60_000, turn_id="t1")
    assert frame is not None and frame.tier == "low"


def test_frame_tier_high_is_recorded():
    response = TestClient(app).post(
        "/frame",
        content=b"\xff\xd8jpeg",
        headers={
            "X-Device-Id": "glasses-tier",
            "X-Turn-Id": "t2",
            "X-Frame-Tier": "high",
        },
    )
    assert response.status_code == 204
    frame = frames.latest_frame("glasses-tier", 60_000, turn_id="t2")
    assert frame is not None and frame.tier == "high"


def test_unknown_tier_is_rejected_instead_of_silently_becoming_low():
    """Một giá trị lạ là lỗi hợp đồng, không phải một mặc định.

    Nuốt nó thành "low" nghĩa là một bản firmware gõ sai `X-Frame-Tier: HIGH_`
    sẽ chạy im lặng ở tầng sai suốt đời sản phẩm.
    """
    response = TestClient(app).post(
        "/frame",
        content=b"jpeg",
        headers={
            "X-Device-Id": "glasses-tier",
            "X-Turn-Id": "t3",
            "X-Frame-Tier": "medium",
        },
    )
    assert response.status_code == 400


# ── bộ đệm chọn theo tầng ─────────────────────────────────────────────────
def test_latest_can_wait_for_a_high_tier_frame_ignoring_the_low_one():
    """🔴 Cốt lõi của F5.

    Board ĐÃ gửi khung tầng thấp từ lúc bấm nút. Nếu `latest()` vớ ngay khung
    đó thì việc xin tầng cao là vô nghĩa — server sẽ luôn đọc chữ trên ảnh VGA.
    """
    buffer = FrameBuffer()
    buffer.put("glasses-01", "turn-1", b"vga", tier="low")

    assert buffer.latest("glasses-01", 60_000, turn_id="turn-1") == b"vga"
    assert buffer.latest("glasses-01", 60_000, turn_id="turn-1", tier="high") is None

    buffer.put("glasses-01", "turn-1", b"hd", tier="high")
    assert buffer.latest("glasses-01", 60_000, turn_id="turn-1", tier="high") == b"hd"


# ── định tuyến: ai được xin tầng cao ──────────────────────────────────────
@pytest.mark.parametrize(
    "intent_name,handler_path",
    [
        (Intent.SPACE, "handlers.describe_space.handle"),
        (Intent.FIND, "handlers.find_object.handle"),
        (Intent.MONEY, "handlers.read_money.handle"),
    ],
)
def test_low_tier_used_for_space_find_money_hazard(intent_name, handler_path):
    """Ba intent này KHÔNG được xin tầng cao.

    Server resize xuống 308-640 trước khi nhìn, nên HD chỉ thêm byte phải đẩy
    trên đường lên của kính — chặng đắt nhất của cả lượt.

    (`hazard` nằm trong tên test theo phác thảo T17 mục 4.4, nhưng từ
    2026-08-25 nó không còn nhận ảnh nữa: nó bật chế độ canh. Nên nó thoả điều
    kiện này một cách mạnh hơn — không xin gì cả.)
    """
    from pipeline import router

    asked: list = []
    with (
        patch("pipeline.stt.transcribe", return_value="câu lệnh giả"),
        patch("pipeline.intent.detect_with_params", return_value=(intent_name, {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch(handler_path, return_value=iter(["xong"])),
        patch.object(router.events, "request_frame", side_effect=lambda *a, **k: asked.append(a) or 1),
    ):
        "".join(router.resolve_speech(b"\xff\xd8img", _fake_wav()))

    assert asked == [], f"{intent_name} lại đi xin ảnh tầng cao"


def test_high_tier_requested_only_for_ocr():
    """🔴 `ocr` là intent DUY NHẤT trả giá một vòng hỏi-đáp để lấy HD."""
    from pipeline import router
    from services.frame_buffer import frames as real_frames

    asked: list = []
    real_frames.clear()

    with (
        patch("pipeline.stt.transcribe", return_value="đọc giúp tôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch("handlers.ocr.handle", return_value=iter(["nội dung"])),
        patch.object(
            router.events,
            "request_frame",
            side_effect=lambda d, t, **k: asked.append((d, t, k.get("tier"))) or 1,
        ),
        patch("app.TURN_ID_CTX") as turn_ctx,
    ):
        turn_ctx.get.return_value = "turn-ocr"
        "".join(router.resolve_speech(b"\xff\xd8img", _fake_wav()))

    assert asked and asked[0][2] == "high", f"ocr không xin tầng cao: {asked}"


def test_ocr_falls_back_to_the_low_tier_frame_when_high_never_arrives():
    """Kính mất sóng giữa chừng KHÔNG được biến thành "không trả lời gì".

    Ảnh mờ thì cổng chất lượng ảnh sẽ tự nói ra; im lặng thì không ai biết
    chuyện gì đã xảy ra.
    """
    from pipeline import router

    said: list[str] = []
    with (
        patch("pipeline.stt.transcribe", return_value="đọc giúp tôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch("handlers.ocr.handle", return_value=iter(["đọc từ ảnh tầng thấp"])),
        patch.object(router.events, "request_frame", return_value=1),
        patch.object(config, "FRAME_HIGH_TIER_WAIT_MS", 10.0),
        patch("app.TURN_ID_CTX") as turn_ctx,
    ):
        turn_ctx.get.return_value = "turn-ocr-2"
        said.append("".join(router.resolve_speech(b"\xff\xd8img", _fake_wav())))

    assert "đọc từ ảnh tầng thấp" in said[0]
