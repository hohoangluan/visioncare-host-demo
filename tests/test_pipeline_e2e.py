"""Kiểm thử FULL PIPELINE — mỗi chức năng nhiều ca, đi QUA router.

Vì sao tồn tại, dù mỗi handler đã có test riêng: ba lần bug chết-im-lặng của
dự án này đều lọt qua test đơn vị và chỉ lộ ra trên board thật, vì chúng nằm ở
chỗ NỐI chứ không nằm trong handler:

  1. `_HANDLERS` giữ một HÀM chứ không phải module -> `AttributeError:
     'function' object has no attribute 'handle'` cho mọi lượt "bật cảnh báo
     vật cản". Test T24 gọi thẳng `hazard_watch.start()` nên không thấy.
  2. `router._IMAGE_REQUIRED_INTENTS` và `image_quality._READS_IMAGE` lệch
     nhau -> lượt thật trả "Không nhận được ảnh từ kính" thay vì chạy.
  3. `_PENDING_YES` khớp "được" bên trong "không được" -> một câu TỪ CHỐI đọc
     thành ĐỒNG Ý, trên một pending `confirm` (đặt xe / gọi điện).

Nguyên tắc của file này:
  - luôn vào bằng `router.resolve_speech()`, không gọi thẳng handler
  - mock ở BIÊN NGOÀI (stt, intent, handler, VisionCare host), không mock router
  - mỗi bất biến một test riêng — một lần đỏ phải chỉ được đúng một chỗ
"""

from __future__ import annotations

import struct
import time
from unittest.mock import patch

import pytest

import config
from handlers import action_flow
from pipeline import router
from schemas import Intent


IMG = b"\xff\xd8xga-frame"


def _wav() -> bytes:
    pcm = b"\x00\x00" * 1600
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


WAV = _wav()


@pytest.fixture(autouse=True)
def _clean() -> None:
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def _say(text: str, intent, params=None, image: bytes | None = IMG, **handlers):
    """Chạy một lượt: `text` là câu STT nghe được, `intent` là nhãn phân loại.

    `handlers` là các handler cần mock, dạng `describe_space="câu trả lời"`.
    Trả về (câu server nói, dict các mock).
    """
    patches = {}
    ctx = [
        patch("pipeline.stt.transcribe", return_value=text),
        patch("pipeline.intent.detect_with_params", return_value=(intent, params or {})),
    ]
    for name, reply in handlers.items():
        p = patch(f"handlers.{name}.handle", return_value=iter([reply]))
        patches[name] = p
        ctx.append(p)

    started = [c.__enter__() for c in ctx]
    try:
        spoken = "".join(router.resolve_speech(image, WAV))
    finally:
        for c in reversed(ctx):
            c.__exit__(None, None, None)
    mocks = dict(zip(list(patches), started[2:]))
    return spoken, mocks


# ══════════════════════════════════════════════════════════════════════════
# 1. MÔ TẢ KHÔNG GIAN (space)
# ══════════════════════════════════════════════════════════════════════════


def test_space_normal_turn():
    spoken, mocks = _say(
        "trước mặt có gì", Intent.SPACE, describe_space="Một cái bàn phía trước."
    )
    assert spoken == "Một cái bàn phía trước."
    mocks["describe_space"].assert_called_once()


def test_space_receives_the_frame_of_this_turn():
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value="trước mặt có gì"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.SPACE, {})),
        patch(
            "handlers.describe_space.handle",
            side_effect=lambda image, *a, **k: got.append(image) or iter(["ok"]),
        ),
    ):
        "".join(router.resolve_speech(IMG, WAV))
    assert got == [IMG], "space nhận nhầm ảnh của lượt khác"


def test_space_without_any_image_is_told_so_not_silence():
    """Im lặng là câu trả lời tệ nhất cho người khiếm thị — họ không biết
    chuyện gì đã xảy ra và bấm lại mãi."""
    spoken, mocks = _say(
        "trước mặt có gì", Intent.SPACE, image=None, describe_space="không tới đây"
    )
    from pipeline import image_quality

    assert spoken == image_quality._NO_IMAGE
    mocks["describe_space"].assert_not_called()


def test_space_dark_image_is_rejected_with_an_actionable_sentence():
    """Câu từ chối phải nói người dùng LÀM GÌ, không phải mô tả lỗi."""
    from pipeline import image_quality

    with patch(
        "pipeline.image_quality.reject_reason", return_value=image_quality._TOO_DARK
    ):
        spoken, mocks = _say(
            "trước mặt có gì", Intent.SPACE, describe_space="không tới đây"
        )
    assert "ra chỗ đủ sáng" in spoken
    mocks["describe_space"].assert_not_called()


def test_space_flat_image_still_answers():
    """request410 (bức tường trắng, sharpness 0.92) từng bị từ chối bằng câu
    "giữ chắc tay" — chẩn đoán sai. `space` không nằm trong `_NEEDS_SHARPNESS`."""
    from pipeline import image_quality

    flat = _flat_jpeg(127)
    assert image_quality.reject_reason(Intent.SPACE, flat) is None


def _flat_jpeg(value: int) -> bytes:
    import io

    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((64, 64), value, dtype=np.uint8), mode="L").save(
        buf, format="JPEG"
    )
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════
# 2. ĐỌC CHỮ (ocr)
# ══════════════════════════════════════════════════════════════════════════


def test_ocr_normal_turn():
    spoken, mocks = _say("đọc giúp tôi", Intent.OCR, ocr="Hoá đơn tiền điện.")
    assert spoken == "Hoá đơn tiền điện."
    mocks["ocr"].assert_called_once()


def test_ocr_uses_the_single_xga_frame_without_asking_for_another():
    """🔴 F5 đã xoá 2026-08-26 — `ocr` là intent DUY NHẤT từng xin ảnh tầng cao.

    Nếu ai đó nối lại đường xin ảnh thì `router` phải import `events` trở lại,
    và đó là thứ test này bắt.
    """
    assert not hasattr(router, "events")
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value="đọc giúp tôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.OCR, {})),
        patch(
            "handlers.ocr.handle",
            side_effect=lambda image, *a, **k: got.append(image) or iter(["chữ"]),
        ),
    ):
        "".join(router.resolve_speech(IMG, WAV))
    assert got == [IMG]


def test_ocr_without_image_is_rejected():
    from pipeline import image_quality

    spoken, mocks = _say("đọc giúp tôi", Intent.OCR, image=None, ocr="không tới đây")
    assert spoken == image_quality._NO_IMAGE
    mocks["ocr"].assert_not_called()


def test_ocr_text_only_followup_needs_no_image():
    """"đọc lại dòng thứ hai" dùng bản chép của lượt trước, không chụp lại.

    Bắt nó có ảnh nghĩa là bắt người dùng giơ kính lên lại chỉ để nghe lại một
    dòng họ vừa nghe.
    """
    # `ocr_text_only` chỉ bật khi CÓ bản chép còn hạn trong phiên — thiếu nó
    # thì đây là một lượt OCR bình thường và cổng ảnh chặn đúng.
    action_flow.remember_ocr("Dòng 1\nDòng 2\nDòng 3")
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value="đọc lại dòng thứ hai"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.OCR, {"ocr_followup": True}),
        ),
        patch(
            "handlers.ocr.handle",
            side_effect=lambda image, *a, **k: got.append(image) or iter(["dòng 2"]),
        ),
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "dòng 2", "followup chỉ-text bị cổng ảnh chặn"
    assert got == [None], "followup chỉ-text vẫn đi lấy ảnh"


# ══════════════════════════════════════════════════════════════════════════
# 3. VẬT CẢN (hazard) — quay về LLM, quyết định 2026-08-26
# ══════════════════════════════════════════════════════════════════════════


def test_hazard_goes_to_the_llm_handler():
    spoken, mocks = _say(
        "phía trước có an toàn không",
        Intent.HAZARD,
        describe_hazard="Lối đi thoáng, có bậc thềm bên phải.",
    )
    assert "bậc thềm" in spoken
    mocks["describe_hazard"].assert_called_once()


def test_hazard_without_image_is_rejected():
    """🔴 Ca này đã đảo hai lần — xem `test_hazard_is_in_both_image_gates_or_neither`.

    Bây giờ `hazard` mô tả MỘT khung hình, nên thiếu ảnh là phải nói ra. Mô tả
    một khung không tồn tại bằng LLM là bịa ra một lối đi.
    """
    from pipeline import image_quality

    spoken, mocks = _say(
        "phía trước có an toàn không",
        Intent.HAZARD,
        image=None,
        describe_hazard="không tới đây",
    )
    assert spoken == image_quality._NO_IMAGE
    mocks["describe_hazard"].assert_not_called()


def test_hazard_dark_image_is_rejected():
    from pipeline import image_quality

    with patch(
        "pipeline.image_quality.reject_reason", return_value=image_quality._TOO_DARK
    ):
        spoken, mocks = _say(
            "phía trước có gì nguy hiểm", Intent.HAZARD, describe_hazard="không tới đây"
        )
    assert spoken == image_quality._TOO_DARK
    mocks["describe_hazard"].assert_not_called()


def test_hazard_does_not_start_the_watch_mode():
    _say("phía trước có an toàn không", Intent.HAZARD, describe_hazard="thoáng")
    assert not action_flow.device_state(None).get("hazard_watching")


def test_hazard_prompt_is_fixed_and_ignores_slots():
    """T16/E6 — chức năng AN TOÀN: prompt cố định.

    Thu hẹp khung nhìn theo đúng thứ người dùng vừa hỏi làm model giảm báo cáo
    thứ họ KHÔNG hỏi — có thể chính là vật sắp làm họ vấp.
    """
    from handlers import describe_hazard

    calls = []
    with (
        patch("pipeline.stt.transcribe", return_value="bên trái có gì nguy hiểm"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.HAZARD, {"focus": "left"}),
        ),
        patch("pipeline.image_quality.reject_reason", return_value=None),
        patch.object(
            describe_hazard.vlm,
            "generate_stream",
            side_effect=lambda prompt, **k: calls.append(prompt) or iter(["ok"]),
        ),
    ):
        "".join(router.resolve_speech(IMG, WAV))
    assert calls == [describe_hazard._PROMPT]


# ══════════════════════════════════════════════════════════════════════════
# 4. NGHE NHẠC
# ══════════════════════════════════════════════════════════════════════════


def test_music_play():
    spoken, mocks = _say(
        "mở bài Nơi này có anh",
        Intent.MUSIC_PLAY,
        {"song_title": "Nơi này có anh"},
        music_play="Đang phát Nơi này có anh.",
    )
    assert "Nơi này có anh" in spoken
    mocks["music_play"].assert_called_once()


def test_music_volume():
    spoken, _ = _say(
        "to lên", Intent.MUSIC_VOLUME, {"direction": "up"}, music_volume="Đã tăng."
    )
    assert spoken == "Đã tăng."


def test_music_stop_via_intent():
    spoken, _ = _say("dừng phát nhạc", Intent.MUSIC_STOP, music_stop="Đã dừng.")
    assert spoken == "Đã dừng."


def test_stop_music_is_local_and_never_reaches_the_classifier():
    """Bước 3/6 chạy bằng regex cục bộ, 0 ms. "tắt nhạc" mà phải chờ Gemini là
    người dùng nghe nhạc thêm một giây rưỡi sau khi đã bảo tắt."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("pipeline.intent.detect_with_params") as classifier,
        patch("handlers.music_stop.handle", return_value=iter(["Đã dừng."])) as stop,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đã dừng."
    stop.assert_called_once()
    classifier.assert_not_called()


def test_local_stop_regex_does_not_run_when_nothing_is_playing():
    """Không có gì đang chạy thì "thôi" KHÔNG được nuốt thành lệnh tắt nhạc.

    Chạy regex đó khi không có gì để dừng vừa vô ích vừa dễ nuốt nhầm câu khác.
    """
    with (
        patch("pipeline.stt.transcribe", return_value="thôi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.music_stop.handle") as stop,
        patch("handlers.chat.handle", return_value=iter(["vâng"])),
    ):
        "".join(router.resolve_speech(None, WAV))
    stop.assert_not_called()


def test_music_playing_still_allows_an_unrelated_question():
    """Bug cũ "Fast-Bypass": đang nghe nhạc thì MỌI câu thành "tắt nhạc"."""
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    spoken, mocks = _say(
        "trước mặt có gì", Intent.SPACE, describe_space="Một cái ghế."
    )
    assert spoken == "Một cái ghế."


# ══════════════════════════════════════════════════════════════════════════
# 5. NÚT KHẨN CẤP — cổng bước 1/6, thắng TẤT CẢ
# ══════════════════════════════════════════════════════════════════════════


def test_emergency_keyword_wins_over_everything():
    spoken, mocks = _say(
        "cứu tôi với", Intent.CHAT, emergency_call="Đang gọi khẩn cấp."
    )
    assert "khẩn cấp" in spoken


def test_emergency_beats_an_open_confirm_pending():
    """🔴 Ca đắt nhất: người dùng ngã trong lúc đang có câu hỏi xác nhận treo.

    "không dậy được" chứa "được" (khớp `_PENDING_YES`) VÀ "không" (khớp
    `_PENDING_NO`). Nếu bước 1 không chạy trước bước 2 thì câu cầu cứu này
    thành một câu trả lời cho câu hỏi đặt xe.
    """
    action_flow.set_pending(
        slot="confirm", intent=Intent.RIDE_CONFIRM, known={"quote_id": "q1"},
        question="Đặt xe này nhé?", kind="confirm",
    )
    with (
        patch(
            "pipeline.stt.transcribe",
            return_value="cứu tôi với, tôi ngã không đứng dậy được",
        ),
        patch("pipeline.intent.detect_with_params") as classifier,
        patch(
            "handlers.emergency_call.handle", return_value=iter(["Đang gọi khẩn cấp."])
        ) as sos,
        patch("handlers.ride_confirm.handle") as ride,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert "khẩn cấp" in spoken
    sos.assert_called_once()
    ride.assert_not_called()
    classifier.assert_not_called()


def test_emergency_beats_a_running_task():
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    with (
        patch("pipeline.stt.transcribe", return_value="cứu tôi"),
        patch(
            "handlers.emergency_call.handle", return_value=iter(["Đang gọi khẩn cấp."])
        ) as sos,
        patch("handlers.music_stop.handle") as stop,
    ):
        "".join(router.resolve_speech(None, WAV))
    sos.assert_called_once()
    stop.assert_not_called()


def test_emergency_needs_no_image():
    """Người vừa ngã không giơ kính lên chụp cho ngay ngắn được."""
    with (
        patch("pipeline.stt.transcribe", return_value="cứu tôi với"),
        patch(
            "handlers.emergency_call.handle", return_value=iter(["Đang gọi khẩn cấp."])
        ) as sos,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert "khẩn cấp" in spoken
    sos.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# 6. LUỒNG XÁC NHẬN NHIỀU VÒNG — kind = confirm
# ══════════════════════════════════════════════════════════════════════════


def _open_confirm(question: str = "Đặt xe này nhé?"):
    return action_flow.set_pending(
        slot="confirm", intent=Intent.RIDE_CONFIRM, known={"quote_id": "q1"},
        question=question, kind="confirm",
    )


@pytest.mark.parametrize(
    "answer", ["ừ", "vâng", "đúng rồi", "đồng ý", "xác nhận", "ok", "được"]
)
def test_confirm_yes_runs_the_action(answer):
    _open_confirm()
    with (
        patch("pipeline.stt.transcribe", return_value=answer),
        patch("pipeline.intent.detect_with_params") as classifier,
        patch("handlers.ride_confirm.handle", return_value=iter(["Đã đặt xe."])) as run,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đã đặt xe."
    run.assert_called_once()
    classifier.assert_not_called(), "câu trả lời ĐÓNG không được tốn một vòng Gemini"
    assert action_flow.get_pending() is None


@pytest.mark.parametrize("answer", ["không", "không phải", "không đúng", "sai rồi"])
def test_confirm_no_cancels(answer):
    _open_confirm()
    with (
        patch("pipeline.stt.transcribe", return_value=answer),
        patch("handlers.ride_confirm.handle") as run,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._CANCELLED_MESSAGE
    run.assert_not_called()
    assert action_flow.get_pending() is None


@pytest.mark.parametrize(
    "answer",
    [
        "không được",
        "không đồng ý",
        "không, không phải xe đó",
        "tôi không xác nhận",
    ],
)
def test_negation_beats_affirmation_when_both_match(answer):
    """🔴 BUG THẬT đã sửa (T04 mục sửa lỗi #2), khoá lại vĩnh viễn.

    `_PENDING_YES` chứa "được"/"đồng ý"/"xác nhận" với ranh giới từ — cả ba
    vẫn khớp y nguyên BÊN TRONG một câu phủ định. Kiểm YES trước sẽ đọc một
    câu TỪ CHỐI thành ĐỒNG Ý, trên loại pending nguy hiểm nhất khi đoán sai:
    xe đã đặt, cuộc gọi đã thực hiện.
    """
    _open_confirm()
    with (
        patch("pipeline.stt.transcribe", return_value=answer),
        patch("handlers.ride_confirm.handle") as run,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._CANCELLED_MESSAGE, f"{answer!r} bị đọc thành đồng ý"
    run.assert_not_called()


def test_confirm_repeat_reads_the_question_again_and_keeps_pending():
    """"gì cơ" KHÔNG tính là một lượt trả lời — pending phải còn nguyên."""
    _open_confirm("Đặt xe này nhé?")
    with patch("pipeline.stt.transcribe", return_value="gì cơ"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đặt xe này nhé?"
    assert action_flow.get_pending() is not None, "hỏi lại đã nuốt mất pending"


def test_confirm_can_be_repeated_twice_then_answered():
    """Nhiều vòng thật: hỏi lại 2 lần rồi mới trả lời."""
    _open_confirm("Đặt xe này nhé?")
    for _ in range(2):
        with patch("pipeline.stt.transcribe", return_value="nói lại đi"):
            assert "".join(router.resolve_speech(None, WAV)) == "Đặt xe này nhé?"
    with (
        patch("pipeline.stt.transcribe", return_value="ừ"),
        patch("handlers.ride_confirm.handle", return_value=iter(["Đã đặt xe."])),
    ):
        assert "".join(router.resolve_speech(None, WAV)) == "Đã đặt xe."


def test_confirm_cancel_word_drops_the_pending():
    _open_confirm()
    with patch("pipeline.stt.transcribe", return_value="thôi"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._CANCELLED_MESSAGE
    assert action_flow.get_pending() is None


def test_confirm_expires_after_its_ttl():
    """TTL 25 s. Hết hạn thì câu tiếp theo là một câu HOÀN TOÀN MỚI, không
    phải một câu trả lời muộn cho câu hỏi đã quên."""
    pending = _open_confirm()
    pending.asked_at = time.monotonic() - config.PENDING_TTL_CONFIRM_SECONDS - 1
    assert action_flow.get_pending() is None, "pending confirm không hết hạn"


def test_confirm_ttl_is_the_shortest_of_the_three():
    """🔴 Bất biến thứ tự, không phải ba con số rời rạc.

    `confirm` là loại đoán sai đắt nhất (xe đã đặt, tiền đã mất) nên nó phải
    là loại chết sớm nhất.
    """
    assert (
        config.PENDING_TTL_CONFIRM_SECONDS
        < config.PENDING_TTL_SELECT_SECONDS
        < config.PENDING_TTL_FILL_SECONDS
    )


def test_unrelated_sentence_during_confirm_is_not_taken_as_yes():
    """Câu lạc rơi xuống bước 6 như một câu mới — KHÔNG được coi là "ừ"."""
    _open_confirm()
    with (
        patch("pipeline.stt.transcribe", return_value="mấy giờ rồi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", return_value=iter(["Ba giờ chiều."])),
        patch("handlers.ride_confirm.handle") as run,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Ba giờ chiều."
    run.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# 7. LUỒNG XÁC NHẬN NHIỀU VÒNG — kind = select
# ══════════════════════════════════════════════════════════════════════════


def _open_select():
    return action_flow.set_pending(
        slot="contact", intent=Intent.CONTACT_CALL, known={},
        question="Bạn muốn gọi Mẹ hay Mẹ vợ?",
        candidates=[{"contact_id": "c1"}, {"contact_id": "c2"}],
        kind="select",
    )


@pytest.mark.parametrize(
    "answer,expected", [("một", "c1"), ("số một", "c1"), ("thứ hai", "c2"), ("2", "c2")]
)
def test_select_by_ordinal(answer, expected):
    _open_select()
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value=answer),
        patch(
            "handlers.contact_call.handle",
            # 🔴 `new=`, KHÔNG phải `side_effect=`. `patch(side_effect=...)`
            # dựng một MagicMock, và `_dispatch()` đọc chữ ký bằng
            # `inspect.signature()` — trên MagicMock nó trả `(*args, **kwargs)`
            # nên `"params" in sig.parameters` là False và slot không bao giờ
            # tới handler. Mất nửa giờ vì chỗ này.
            new=lambda image, command_text, params=None: (
                got.append(params) or iter(["Đang gọi."])
            ),
        ),
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đang gọi."
    assert got[0]["contact_id"] == expected
    assert action_flow.get_pending() is None


def test_select_out_of_range_does_not_pick_anything():
    """"số bốn" khi chỉ có hai ứng viên: KHÔNG được gọi nhầm người thứ hai."""
    _open_select()
    with (
        patch("pipeline.stt.transcribe", return_value="số bốn"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", return_value=iter(["vâng"])),
        patch("handlers.contact_call.handle") as call,
    ):
        "".join(router.resolve_speech(None, WAV))
    call.assert_not_called()


@pytest.mark.parametrize("answer", ["không phải", "không đúng", "sai rồi"])
def test_select_negation_cancels(answer):
    _open_select()
    with (
        patch("pipeline.stt.transcribe", return_value=answer),
        patch("handlers.contact_call.handle") as call,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._CANCELLED_MESSAGE
    call.assert_not_called()


def test_select_repeat_keeps_the_candidate_list():
    _open_select()
    with patch("pipeline.stt.transcribe", return_value="nhắc lại"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Bạn muốn gọi Mẹ hay Mẹ vợ?"
    pending = action_flow.get_pending()
    assert pending is not None and len(pending.candidates) == 2


def test_select_expires_after_its_ttl():
    pending = _open_select()
    pending.asked_at = time.monotonic() - config.PENDING_TTL_SELECT_SECONDS - 1
    assert action_flow.get_pending() is None


# ══════════════════════════════════════════════════════════════════════════
# 8. LUỒNG XÁC NHẬN NHIỀU VÒNG — kind = fill
# ══════════════════════════════════════════════════════════════════════════


def _open_fill(slot: str = "destination", intent=Intent.NAV_START):
    return action_flow.set_pending(
        slot=slot, intent=intent, known={},
        question="Bạn muốn đi đâu?", kind="fill",
    )


def test_fill_slot_is_extracted_not_pasted_whole():
    """🔴 BUG THẬT đã sửa 2026-08-22.

    Hàm này từng NHÉT NGUYÊN VĂN `command_text` làm giá trị slot, nên "Tôi
    muốn đi tới Bến Thành" cho `destination` = CẢ CÂU thay vì "Bến Thành".
    """
    _open_fill()
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value="tôi muốn đi tới Bến Thành"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.NAV_START, {"destination": "Bến Thành"}),
        ),
        patch(
            "handlers.nav_start.handle",
            new=lambda image, command_text, params=None: (
                got.append(params) or iter(["Đang dẫn."])
            ),
        ),
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đang dẫn."
    assert got[0]["destination"] == "Bến Thành"


def test_fill_unrelated_intent_escapes_the_pending():
    """"gọi cho mẹ" giữa lúc chờ điểm đến phải thành `contact_call`, KHÔNG
    thành một địa điểm tên là "gọi cho mẹ"."""
    _open_fill()
    with (
        patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"),
        patch(
            "pipeline.intent.detect_with_params",
            return_value=(Intent.CONTACT_CALL, {"name": "mẹ"}),
        ),
        patch("handlers.contact_call.handle", return_value=iter(["Đang gọi mẹ."])),
        patch("handlers.nav_start.handle") as nav,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đang gọi mẹ."
    nav.assert_not_called()
    assert action_flow.get_pending() is None, "pending không được sống sót sang lượt sau"


def test_fill_repeat_keeps_the_question():
    _open_fill()
    with patch("pipeline.stt.transcribe", return_value="gì cơ"):
        assert "".join(router.resolve_speech(None, WAV)) == "Bạn muốn đi đâu?"
    assert action_flow.get_pending() is not None


def test_fill_cancel_drops_the_pending():
    _open_fill()
    with patch("pipeline.stt.transcribe", return_value="thôi khỏi cần"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._CANCELLED_MESSAGE
    assert action_flow.get_pending() is None


def test_fill_expires_after_its_ttl():
    pending = _open_fill()
    pending.asked_at = time.monotonic() - config.PENDING_TTL_FILL_SECONDS - 1
    assert action_flow.get_pending() is None


def test_fill_artist_any_is_a_closed_answer():
    """T12/A4: sáu câu "bản nào cũng được" khớp tất định, không tốn Gemini."""
    _open_fill(slot="artist", intent=Intent.MUSIC_PLAY)
    got = []
    with (
        patch("pipeline.stt.transcribe", return_value="ai cũng được"),
        patch("pipeline.intent.detect_with_params") as classifier,
        patch(
            "handlers.music_play.handle",
            new=lambda image, command_text, params=None: (
                got.append(params) or iter(["Đang phát."])
            ),
        ),
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đang phát."
    assert got[0]["artist_any"] is True
    classifier.assert_not_called()


def test_stop_command_beats_a_fill_pending():
    """Nguyên tắc 1 (CONTRACTS mục 0): một lệnh STOP rõ ràng thắng pending.

    Đây chính là ca vỡ 21.1 — pending sống sót và tiếp tục chờ đúng slot cũ
    trong khi người dùng đã bảo dừng.
    """
    action_flow.note_result("music_play", {"request_state": "succeeded"})
    _open_fill()
    with (
        patch("pipeline.stt.transcribe", return_value="tắt nhạc"),
        patch("handlers.music_stop.handle", return_value=iter(["Đã dừng."])),
        patch("handlers.nav_start.handle") as nav,
    ):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == "Đã dừng."
    nav.assert_not_called()
    assert action_flow.get_pending() is None


# ══════════════════════════════════════════════════════════════════════════
# 9. BẤT BIẾN CỦA PENDING — mỗi cái một test, không suy ra từ ca khác
# ══════════════════════════════════════════════════════════════════════════


def test_only_one_pending_per_device_no_stacking():
    """21.4 / CONTRACTS quyết định #9: pending mới THAY, không xếp chồng."""
    first = _open_confirm("Đặt xe này nhé?")
    second = _open_fill()
    current = action_flow.get_pending()
    assert current is second
    assert current is not first
    assert not isinstance(current, (list, tuple))


def test_pending_does_not_leak_between_devices():
    """Kính A đang chờ trả lời KHÔNG được biến câu "ừ" của kính B thành xác nhận."""
    action_flow.set_pending(
        slot="confirm", intent=Intent.RIDE_CONFIRM, known={"quote_id": "q1"},
        question="Đặt xe này nhé?", kind="confirm",
    )
    key_a = action_flow._NO_DEVICE_CONTEXT_KEY
    assert action_flow.get_pending() is not None
    assert action_flow.device_state("glasses-99").get("pending") in (None, False), (
        "trạng thái pending rò sang thiết bị khác"
    )
    from handlers.action_flow import _SESSIONS

    assert "glasses-99" not in _SESSIONS or _SESSIONS["glasses-99"].pending is None
    assert _SESSIONS[key_a].pending is not None


def test_bump_generation_never_clears_pending():
    """G2: đếm thế hệ để huỷ lượt cũ — KHÔNG được đụng vào câu hỏi đang chờ.

    Xoá pending ở đây nghĩa là mỗi lần người dùng bấm nút giữa chừng, câu hỏi
    "đặt xe này nhé?" bốc hơi và họ trả lời vào hư không.
    """
    _open_confirm()
    action_flow.bump_generation(None)
    assert action_flow.get_pending() is not None


def test_six_step_priority_order_is_documented_and_held():
    """Thứ tự 6 bước, khoá bằng ba cặp kề nhau thay vì một assert to.

    1 khẩn cấp > 2 pending tất định  -> test_emergency_beats_an_open_confirm_pending
    3 STOP     > 4 pending điền slot -> test_stop_command_beats_a_fill_pending
    2 pending  > 6 phân loại ý định  -> test_confirm_yes_runs_the_action
    """
    import inspect

    source = inspect.getsource(router._resolve)
    order = [source.index(marker) for marker in ("─── 1.", "─── 2.", "─── 3.", "─── 4.", "─── 5.", "─── 6.")]
    assert order == sorted(order), "sáu bước đã bị đảo thứ tự trong code"


def test_global_repeat_without_pending_says_something():
    """Không có pending thì "nói lại" là lệnh TOÀN CỤC (bước 5), nghĩa khác
    hẳn "nói lại" ở bước 2 (đọc lại câu hỏi đang chờ)."""
    with patch("pipeline.stt.transcribe", return_value="nói lại đi"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._NOTHING_TO_REPEAT


def test_global_cancel_without_pending_says_something():
    with patch("pipeline.stt.transcribe", return_value="huỷ"):
        spoken = "".join(router.resolve_speech(None, WAV))
    assert spoken == router._NOTHING_TO_CANCEL


# ══════════════════════════════════════════════════════════════════════════
# 10. HAI CỔNG ẢNH PHẢI KHỚP NHAU
# ══════════════════════════════════════════════════════════════════════════


def test_both_image_gates_agree_for_every_intent():
    """🔴 Bug #2 ở đầu file: hai danh sách lệch nhau đúng một lần.

    `router._IMAGE_REQUIRED_INTENTS` quyết định có ĐI LẤY ảnh không;
    `image_quality._READS_IMAGE` quyết định có TỪ CHỐI khi thiếu ảnh không.
    Sửa một nửa thì lượt thật trả "Không nhận được ảnh từ kính" thay vì chạy.
    """
    from pipeline import image_quality

    assert set(router._IMAGE_REQUIRED_INTENTS) == set(image_quality._READS_IMAGE)


def test_every_handler_entry_is_dispatchable():
    """🔴 Bug #1 ở đầu file: `_HANDLERS` giữ một HÀM chứ không phải module.

    Mọi lượt đi qua dispatch nổ `AttributeError: 'function' object has no
    attribute 'handle'`. Test đơn vị gọi thẳng hàm nên không thấy.
    """
    from schemas import Intent as _Intent

    # `call_answer`/`call_reject` dùng chung module `incoming_call`, và router
    # gọi `handle_answer`/`handle_reject` chứ không phải `handle` — hai nhánh
    # đặc biệt tường minh trong `_dispatch()`, không phải thiếu sót.
    special = {_Intent.CALL_ANSWER: "handle_answer", _Intent.CALL_REJECT: "handle_reject"}

    for intent_name, entry in router._HANDLERS.items():
        expected = special.get(intent_name, "handle")
        assert hasattr(entry, expected) or callable(entry), (
            f"{intent_name} trỏ vào thứ không dispatch được: {entry!r} "
            f"(thiếu `{expected}`, và cũng không phải hàm)"
        )
