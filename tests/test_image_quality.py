import io

import numpy as np
import pytest
from PIL import Image

import config
from pipeline import image_quality
from schemas import Intent


def _jpeg_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), mode="L").save(buf, format="JPEG")
    return buf.getvalue()


def _flat(color: int, size: tuple[int, int] = (100, 100)) -> bytes:
    """Ảnh phẳng một màu: sharpness ~0, brightness = color. Đại diện frame hỏng/trống."""
    return _jpeg_bytes(np.full((size[1], size[0]), color, dtype=np.uint8))


def _noisy(mean: int, size: tuple[int, int] = (100, 100)) -> bytes:
    """Nhiễu ngẫu nhiên quanh `mean`: sharpness cao, brightness ~mean. Đại diện ảnh chụp bình thường."""
    rng = np.random.default_rng(0)
    arr = np.clip(rng.normal(mean, 60, (size[1], size[0])), 0, 255)
    return _jpeg_bytes(arr)


def test_measure_returns_none_for_undecodable_bytes():
    assert image_quality.measure(b"not an image") is None


def test_measure_returns_none_for_empty_bytes():
    assert image_quality.measure(b"") is None


def test_measure_reports_low_sharpness_for_flat_image():
    result = image_quality.measure(_flat(127))
    assert result is not None
    sharpness, brightness = result
    assert sharpness < 1.0
    assert brightness == pytest.approx(127, abs=2)


def test_measure_reports_high_sharpness_for_noisy_image():
    result = image_quality.measure(_noisy(127))
    assert result is not None
    sharpness, brightness = result
    assert sharpness > 50
    assert brightness == pytest.approx(127, abs=10)


def test_check_rejects_too_dark(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    assert image_quality.check(sharpness=200, brightness=15) == image_quality._TOO_DARK


def test_check_rejects_too_bright(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MAX_BRIGHTNESS", 235)
    assert image_quality.check(sharpness=200, brightness=250) == image_quality._TOO_BRIGHT


def test_check_rejects_too_blurry(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.check(sharpness=1, brightness=127) == image_quality._TOO_BLURRY


def test_check_skips_sharpness_when_not_needed(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MAX_BRIGHTNESS", 235)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.check(sharpness=1, brightness=127, need_sharpness=False) is None


def test_check_still_rejects_darkness_when_sharpness_skipped(monkeypatch):
    """Bỏ luật độ nét không được kéo theo bỏ luật ánh sáng: ảnh quá tối khiến
    Gemini đọc sai mệnh giá một cách tự tin (đo thật, xem docstring module)."""
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    assert (
        image_quality.check(sharpness=1, brightness=10, need_sharpness=False)
        == image_quality._TOO_DARK
    )


def test_check_passes_normal_image(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MAX_BRIGHTNESS", 235)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.check(sharpness=80, brightness=120) is None


def test_darkness_check_wins_over_blur_when_both_fail(monkeypatch):
    """Ảnh cực tối cũng thường mờ (như request290/291) — lý do tối phải là câu nói ra,
    vì đó là thứ người dùng khắc phục được ngay (di chuyển chỗ sáng)."""
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.check(sharpness=1, brightness=10) == image_quality._TOO_DARK


# --- Cổng lọc theo intent -------------------------------------------------
#
# Lỗi gốc: cổng lọc chạy TRƯỚC khi biết intent, nên một tấm ảnh xấu chặn cả
# những câu không hề dùng tới ảnh ("gọi cho mẹ", "kể chuyện cười").

_NO_IMAGE_INTENTS = [
    Intent.CHAT, Intent.CONTACT_CALL, Intent.EMERGENCY_CALL,
    Intent.MUSIC_PLAY, Intent.MUSIC_STOP, Intent.MUSIC_VOLUME,
    Intent.NAV_START, Intent.NAV_STOP, Intent.RIDE_QUOTE, Intent.RIDE_CONFIRM,
    Intent.UNKNOWN,
]


@pytest.mark.parametrize("intent", _NO_IMAGE_INTENTS)
def test_intents_that_ignore_the_image_are_never_blocked(intent, monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    # Ảnh tối thui VÀ phẳng lì: hỏng theo mọi luật đang có.
    assert image_quality.reject_reason(intent, _flat(2)) is None


@pytest.mark.parametrize("intent", _NO_IMAGE_INTENTS)
def test_intents_that_ignore_the_image_accept_no_image_at_all(intent):
    assert image_quality.reject_reason(intent, None) is None


@pytest.mark.parametrize(
    "intent", [Intent.OCR, Intent.FIND, Intent.SPACE, Intent.HAZARD]
)
def test_flat_image_passes_for_non_money_intents(intent, monkeypatch):
    """request410 (bức tường trắng, sharpness 0.92) từng bị từ chối bằng câu
    'giữ chắc tay' — chẩn đoán sai, và cả ba handler tự trả lời đúng hơn hẳn."""
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.reject_reason(intent, _flat(127)) is None


def test_flat_image_still_blocked_for_money(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    monkeypatch.setattr(config, "IMAGE_MIN_SHARPNESS", 5)
    assert image_quality.reject_reason(Intent.MONEY, _flat(127)) == image_quality._TOO_BLURRY


@pytest.mark.parametrize(
    "intent", [Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD]
)
def test_darkness_still_blocks_every_image_intent(intent, monkeypatch):
    """Đo thật trên ảnh tờ 5.000đ làm tối đi: Gemini đọc thành '2 nghìn đồng',
    làm sáng quá: '500 nghìn đồng'. Tự tin và sai, không hề từ chối — nên luật
    ánh sáng phải giữ cho MỌI intent có đọc ảnh."""
    monkeypatch.setattr(config, "IMAGE_MIN_BRIGHTNESS", 30)
    assert image_quality.reject_reason(intent, _noisy(8)) == image_quality._TOO_DARK


@pytest.mark.parametrize(
    "intent", [Intent.OCR, Intent.FIND, Intent.MONEY, Intent.SPACE, Intent.HAZARD]
)
def test_missing_image_is_reported_for_intents_that_need_one(intent):
    assert image_quality.reject_reason(intent, None) == image_quality._NO_IMAGE
    assert image_quality.reject_reason(intent, b"") == image_quality._NO_IMAGE


def test_undecodable_image_is_left_to_the_handler():
    """Bytes hỏng không phải việc của cổng này — luồng cũ đã xử lý từ trước."""
    assert image_quality.reject_reason(Intent.OCR, b"not an image") is None


def test_every_intent_is_classified():
    """Thêm intent mới mà quên khai vào đây thì nó lặng lẽ rơi vào nhóm 'không
    cần ảnh' — bug đúng bằng bug gốc, chỉ ngược chiều."""
    known = set(_NO_IMAGE_INTENTS) | set(image_quality._READS_IMAGE)
    declared = {
        value for name, value in vars(Intent).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert declared == known


def test_sharpness_gate_applies_only_to_money():
    assert image_quality._NEEDS_SHARPNESS == frozenset({Intent.MONEY})
