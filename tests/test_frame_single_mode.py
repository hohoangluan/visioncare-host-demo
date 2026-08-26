"""Một chế độ ảnh duy nhất — XGA 1024×768, luôn gửi (quyết định #2, 2026-08-26).

🔴 File này TRƯỚC ĐÂY là `tests/test_frame_tier.py` và khoá F5 — ảnh phân tầng:

    gửi NGAY, không hỏi : tầng THẤP (VGA 640×480) -> space / hazard / find / money
    gửi khi server XIN  : tầng CAO  (HD 1280×720) -> CHỈ ocr

F5 đã XOÁ. Board gửi đúng một ảnh XGA cho mọi lượt bấm nút và `ocr` dùng luôn
ảnh đó. Đổi lại `ocr` mất hẳn một vòng hỏi-đáp: trước đây nó đẩy `frame_request`
xuống board rồi chờ tới 2500 ms cho ảnh HD đi lên.

Số đo hậu thuẫn lựa chọn XGA (`docs/tasks/measurements/F5-resolution.md`, cùng
một cảnh, đẩy quy đổi ở 24.3 KB/s):

    tầng   pixel       JPEG      đẩy       độ nét
    VGA    640×480     21 153 B    850 ms   156.0
    XGA    1024×768    43 020 B  1 729 ms    80.8   <- đang dùng
    HD     1280×720    47 892 B  1 925 ms    67.0

Ngưỡng blur KHÔNG phải hiệu chỉnh lại: `IMAGE_MIN_SHARPNESS = 5`, và nó chỉ áp
cho `money`. 80.8 dư 16 lần — xem `test_xga_sharpness_clears_the_blur_gate`.

Cái CHƯA đo được ở đây và chỉ đo được trên board: +879 ms đẩy mỗi lượt có lộ ra
không. `/frame` là fire-and-forget trên socket riêng, chạy song song với lúc
người dùng đang nói — nói ≥1.7 s thì nó miễn phí, nói cụt thì không.
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


@pytest.fixture(autouse=True)
def _clean_frames() -> None:
    frames.clear()
    yield
    frames.clear()


# ── hợp đồng HTTP ─────────────────────────────────────────────────────────


def test_frame_is_accepted_without_any_tier_header():
    response = TestClient(app).post(
        "/frame",
        content=b"\xff\xd8jpeg",
        headers={"X-Device-Id": "glasses-01", "X-Turn-Id": "t1"},
    )
    assert response.status_code == 204
    assert frames.latest("glasses-01", 60_000, turn_id="t1") == b"\xff\xd8jpeg"


def test_a_stale_firmware_still_sending_x_frame_tier_is_not_rejected():
    """🔴 Header cũ được BỎ QUA, không trả 400.

    Firmware và server nâng cấp lệch nhau là chuyện thường. Từ chối khung ảnh
    của một board chưa nạp lại nghĩa là người dùng nghe "Không nhận được ảnh
    từ kính" cho tới khi có người cầm kính đi nạp — với một thiết bị người
    khiếm thị đeo cả ngày thì đó là hỏng hẳn, không phải xuống cấp nhẹ.
    """
    for tier in ("low", "high", "medium", "HIGH_", ""):
        response = TestClient(app).post(
            "/frame",
            content=b"\xff\xd8jpeg",
            headers={
                "X-Device-Id": "glasses-01",
                "X-Turn-Id": f"t-{tier or 'blank'}",
                "X-Frame-Tier": tier,
            },
        )
        assert response.status_code == 204, f"tier={tier!r} bị từ chối"


def test_frame_still_requires_device_and_turn_id():
    """Hợp đồng T17 còn lại nguyên vẹn — bỏ F5 không được nới lỏng cái khác."""
    client = TestClient(app)
    assert client.post("/frame", content=b"jpeg").status_code == 400
    assert client.post(
        "/frame", content=b"jpeg", headers={"X-Device-Id": "glasses-01"}
    ).status_code == 400
    assert client.post(
        "/frame", content=b"jpeg", headers={"X-Turn-Id": "t1"}
    ).status_code == 400


# ── bộ đệm không còn khái niệm tầng ───────────────────────────────────────


def test_frame_dataclass_has_no_tier_field():
    """Khoá tường minh: thêm lại `tier` là dựng lại F5, phải đọc spec trước."""
    from services.frame_buffer import Frame

    assert "tier" not in Frame.__dataclass_fields__


def test_put_rejects_a_tier_keyword():
    buffer = FrameBuffer()
    with pytest.raises(TypeError):
        buffer.put("glasses-01", "turn-1", b"jpeg", tier="high")


def test_latest_rejects_a_tier_keyword():
    buffer = FrameBuffer()
    buffer.put("glasses-01", "turn-1", b"jpeg")
    with pytest.raises(TypeError):
        buffer.latest("glasses-01", 60_000, turn_id="turn-1", tier="high")


def test_newest_frame_of_the_turn_wins():
    """Board chụp một loạt và giữ khung nét nhất, nhưng nếu hai khung cùng lượt
    tới thì cái mới hơn thắng."""
    buffer = FrameBuffer()
    buffer.put("glasses-01", "turn-1", b"first")
    buffer.put("glasses-01", "turn-1", b"second")
    assert buffer.latest("glasses-01", 60_000, turn_id="turn-1") == b"second"


def test_frame_still_matched_by_turn_id():
    buffer = FrameBuffer()
    buffer.put("glasses-01", "turn-1", b"one")
    buffer.put("glasses-01", "turn-2", b"two")
    assert buffer.latest("glasses-01", 60_000, turn_id="turn-1") == b"one"
    assert buffer.latest("glasses-01", 60_000, turn_id="turn-3") is None


def test_stale_frame_is_not_returned():
    buffer = FrameBuffer()
    buffer.put("glasses-01", "turn-1", b"old", received_at=0.0)
    assert buffer.latest("glasses-01", max_age_ms=1.0, turn_id="turn-1") is None


# ── định tuyến: KHÔNG intent nào đi xin ảnh nữa ───────────────────────────


@pytest.mark.parametrize(
    "intent_name,handler_path",
    [
        (Intent.SPACE, "handlers.describe_space.handle"),
        (Intent.FIND, "handlers.find_object.handle"),
        (Intent.MONEY, "handlers.read_money.handle"),
        (Intent.HAZARD, "handlers.describe_hazard.handle"),
        (Intent.OCR, "handlers.ocr.handle"),
    ],
)
def test_no_intent_asks_the_board_for_another_frame(intent_name, handler_path):
    """🔴 Cốt lõi của quyết định #2, và `ocr` là ca đáng khoá nhất.

    `ocr` từng là intent DUY NHẤT trả giá một vòng hỏi-đáp. Giờ nó dùng luôn
    ảnh đã có. Nếu ai đó nối lại đường xin ảnh, test này đỏ ở đúng dòng `ocr`.

    Kiểm bằng cách nhìn vào chính module `router`: nó không được import
    `events` nữa, nên không có gì để mà gọi.
    """
    from pipeline import router

    assert not hasattr(router, "events"), (
        "router lại import kênh xuống — F5 đã quay lại?"
    )

    with (
        patch("pipeline.stt.transcribe", return_value="câu lệnh giả"),
        patch("pipeline.intent.detect_with_params", return_value=(intent_name, {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch(handler_path, return_value=iter(["xong"])) as handler,
    ):
        out = "".join(router.resolve_speech(b"\xff\xd8img", _fake_wav()))

    handler.assert_called_once()
    assert out == "xong"


def test_ocr_uses_the_frame_it_was_given_without_waiting():
    """`ocr` phải nhận ĐÚNG ảnh của lượt đó, ngay, không chờ khung nào khác."""
    from pipeline import router

    got: list[bytes | None] = []
    with (
        patch("pipeline.stt.transcribe", return_value="đọc giúp tôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch(
            "handlers.ocr.handle",
            side_effect=lambda image, *a, **k: got.append(image) or iter(["nội dung"]),
        ),
    ):
        out = "".join(router.resolve_speech(b"\xff\xd8xga", _fake_wav()))

    assert got == [b"\xff\xd8xga"]
    assert out == "nội dung"


def test_high_tier_wait_config_is_gone():
    """`FRAME_HIGH_TIER_WAIT_MS` đã xoá — không còn gì để chờ."""
    assert not hasattr(config, "FRAME_HIGH_TIER_WAIT_MS")


# ── XGA và cổng chất lượng ảnh ────────────────────────────────────────────


def test_xga_sharpness_clears_the_blur_gate():
    """🔴 Bất biến số học từ F5-resolution.md, không phải sở thích.

    Đo trên cùng một cảnh: VGA 156.0, XGA 80.8, HD 67.0. Điểm Laplacian tụt
    theo độ phân giải, nên ghi chú "ngưỡng blur theo TỪNG TẦNG" trong CLAUDE.md
    là mối lo có thật — nhưng nó nói về KHOẢNG CÁCH tới ngưỡng, không phải về
    việc vượt ngưỡng.

    Ngưỡng thật là 5, và nó chỉ áp cho `money`. 80.8 dư 16 lần. Nếu ai đó nâng
    `IMAGE_MIN_SHARPNESS` lên gần 80 thì test này đỏ TRƯỚC khi board thật bắt
    đầu từ chối ảnh nét của người dùng.
    """
    xga_measured_sharpness = 80.8
    assert config.IMAGE_MIN_SHARPNESS < xga_measured_sharpness / 4, (
        f"IMAGE_MIN_SHARPNESS={config.IMAGE_MIN_SHARPNESS} quá sát số đo XGA "
        f"({xga_measured_sharpness}) — ảnh nét bình thường sẽ bị từ chối"
    )
