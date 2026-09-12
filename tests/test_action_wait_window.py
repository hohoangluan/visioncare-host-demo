"""Cửa sổ chờ kết quả điện thoại — không ai được chờ trong im lặng.

Bối cảnh (đo trên board thật + DB server app, 2026-08-26)
--------------------------------------------------------
`run_action()` nói câu ack trước, rồi CHỜ `VISIONCARE_FAST_ACTION_SECONDS`
(2.0 s) xem điện thoại trả kết quả không. Câu ack được đọc TRONG lúc chờ, nên
"chờ 2 giây" không phải 2 giây im lặng — đo độ dài từng câu ack:

    music_play      4.98 s   cửa sổ hết trước cả khi nói xong -> im lặng 0
    nav_start       2.00 s   im lặng 0
    emergency_call  1.86 s   im lặng 0
    contact_call    1.68 s   ~0.1 s
    music_volume    1.26 s   ~0.5 s
    nav_stop        1.26 s   ~0.5 s
    music_stop      1.02 s   ~0.8 s   <- tệ nhất

Nên hằng số 2.0 s vừa THỪA cho câu ngắn (đẻ ra im lặng) vừa THIẾU cho câu dài
(`music_play` bỏ lỡ kết quả về ở giây thứ 3 dù người dùng vẫn đang nghe).

Chữa: cửa sổ = ĐÚNG độ dài câu ack. Im lặng thêm bằng 0 **theo cấu trúc**,
không phải nhờ chọn được một con số nhỏ hơn. Và câu dài được chờ lâu hơn, nên
nhiều lượt kết thúc gọn trong một hơi thở — tốt lên ở cả hai đầu cùng lúc.

Vì sao KHÔNG chỉ đơn giản đặt cửa sổ = 0
----------------------------------------
Đặt 0 thì mọi lượt đều rơi xuống nhánh "chưa có kết quả", tức người dùng luôn
nghe hai câu thay vì một, và không bao giờ biết lệnh có chạy không.

Còn một nửa việc CHƯA làm được
------------------------------
Nhánh hết giờ đang hứa "tôi sẽ cập nhật khi có kết quả" — lời hứa đó
**không bao giờ được giữ**: `action_flow` không hề chạm tới `events.`, nên kết
quả về muộn chỉ cập nhật trạng thái phiên chứ không ai nói ra. Đường giữ lời
hứa là đẩy xuống `/events`, mà đo được tối 2026-08-26 là board tự đóng
`/events` để nhường RAM (`pushed: 0`, dù server đếm `subscribers: 1`). Nên
tạm thời phải BỎ lời hứa và nói thật, ngắn.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

import config
from handlers import action_flow
from pipeline import tts


@pytest.fixture(autouse=True)
def _clean():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


# ─── cửa sổ chờ bám theo câu ack ──────────────────────────────────────────


def test_wait_window_matches_the_ack_length_when_the_ack_is_long_enough():
    """Câu ack dài hơn sàn thì chờ đúng bằng nó — không phải một hằng số."""
    ack = "Đang mở nhạc, tìm bài Nơi này có anh. Nếu màn hình đang bật, chạm để mở."
    assert tts.speaking_seconds(ack) > config.VISIONCARE_MIN_WAIT_SECONDS
    assert action_flow.wait_window_seconds(ack) == pytest.approx(
        tts.speaking_seconds(ack), abs=0.01
    )


def test_short_acks_are_floored_so_the_real_answer_is_not_thrown_away():
    """🔴 ĐẢO NGƯỢC một quyết định cũ — người dùng chốt 2026-08-27.

    Luật cũ: cửa sổ KHÔNG BAO GIỜ dài hơn câu ack, để quãng im lặng thêm bằng
    0 theo cấu trúc. Đo trên máy thật cho thấy luật đó đánh đổi sai chiều:

        lệnh           ack đọc mất   điện thoại cần   trước sàn
        music_stop        1.02 s        1.64 s        trượt
        music_volume      1.26 s        1.13 s        trượt 5/6

    "điện thoại cần" do CHÍNH server app 8001 đóng dấu, và 10/10 lượt bắn
    thẳng vào 8001 đều `succeeded` — tức người dùng nghe "Điện thoại chưa báo
    lại." trong khi máy đã làm xong. Im một nhịp rồi nghe kết quả THẬT tốt hơn
    nghe ngay một câu báo sai.
    """
    for ack in (
        "Đang dừng nhạc.",
        "Đang chỉnh âm lượng.",
        "Đang dừng chỉ đường.",
    ):
        assert tts.speaking_seconds(ack) < config.VISIONCARE_MIN_WAIT_SECONDS
        assert action_flow.wait_window_seconds(ack) == pytest.approx(
            config.VISIONCARE_MIN_WAIT_SECONDS, abs=0.01
        )


def test_the_floor_is_never_below_the_measured_phone_latency():
    """Sàn phải phủ được đuôi trên của phân bố đo được (`music_stop`:
    0.97 / 1.20 / 2.08 / 2.92 s). Hạ nó xuống dưới ~2 s là mở lại đúng con bug
    vừa sửa, nên khoá lại ở đây."""
    assert config.VISIONCARE_MIN_WAIT_SECONDS >= 2.0


def test_wait_window_shrinks_by_time_already_spent():
    """Gọi HTTP đã ăn mất một phần câu ack thì phần còn lại mới là cửa sổ."""
    ack = "Đang kích hoạt cuộc gọi khẩn cấp."   # 1.86 s
    full = action_flow.wait_window_seconds(ack)
    partial = action_flow.wait_window_seconds(ack, elapsed=1.0)
    assert partial == pytest.approx(full - 1.0, abs=0.01)


def test_wait_window_never_negative():
    """Ack ngắn mà mạng chậm hơn cả nó: chờ 0, không chờ âm."""
    assert action_flow.wait_window_seconds("Đang dừng nhạc.", elapsed=99.0) == 0.0


# ─── câu cuối khi hết giờ phải nói THẬT ───────────────────────────────────


def test_timeout_line_makes_no_promise_it_cannot_keep():
    """Câu ở nhánh hết giờ KHÔNG được hứa sẽ cập nhật sau.

    `action_flow` không publish gì xuống `/events`, và `/events` cũng không
    đáng tin (board tự đóng để nhường RAM). Một lời hứa không có đường thực
    hiện thì tệ hơn im lặng: người dùng đứng đợi một câu không bao giờ tới.
    """
    line = action_flow.TIMEOUT_LINE
    for cam in ("sẽ cập nhật", "sẽ báo", "chờ chút", "lát nữa"):
        assert cam not in line.lower(), f"câu hết giờ vẫn hứa: {line!r}"


def test_timeout_line_is_short():
    """Câu cũ mất 3.21 s để đọc, và nó là câu cuối người dùng nghe mỗi lần
    điện thoại chậm. Giữ dưới 2 giây."""
    assert tts.speaking_seconds(action_flow.TIMEOUT_LINE) < 2.0


# ─── thời gian TỔNG HỢP câu ack không phải thời gian NGHE câu ack ─────────
#
# Bug đã đo được trên máy thật (2026-08-26): `music_volume` và `music_stop`
# TRƯỢT 8/8 lượt — người dùng luôn nghe "Điện thoại chưa báo lại." trong khi
# điện thoại đã làm xong thật (đo thẳng vào host 8001: 10/10 `succeeded`,
# trung vị 1.13 s và 1.64 s do CHÍNH server app đóng dấu).
#
# Cơ chế: `run_action()` là GENERATOR. Nó đứng lại ở `yield ack` cho tới khi
# bên tiêu thụ (TTS) kéo mảnh kế tiếp — tức tới khi câu ack đã được TỔNG HỢP
# xong. Đo thời gian tổng hợp trên chính bộ TTS đang chạy:
#
#     ack             đọc mất   tổng hợp mất   cửa sổ còn lại thật
#     music_volume     1.26 s       0.68 s          0.57 s
#     music_stop       1.02 s       0.48 s          0.55 s
#     contact_call     1.68 s       0.80 s          0.87 s
#
# `elapsed = now - started` vì thế nuốt luôn phần tổng hợp, và cửa sổ chỉ còn
# non nửa thiết kế. Nhưng lúc TỔNG HỢP thì board CHƯA phát gì cả — đó không
# phải thời gian người dùng đã nghe, nên trừ nó đi là sai.
#
# Sửa ở GỐC: đo `elapsed` từ lúc generator được đánh thức TRỞ LẠI (khi ack đã
# giao xong cho TTS và board bắt đầu phát), không phải từ đầu hàm. Cửa sổ trở
# về đúng bằng độ dài câu ack — ĐÚNG như docstring của `wait_window_seconds`
# vẫn luôn nói, không nới thêm một mili giây nào.


def _run_action_with_a_slow_consumer(synth_seconds: float, result_at: float):
    """Chạy `run_action()` với bên tiêu thụ chậm y như TTS thật.

    `synth_seconds` là quãng generator bị treo ở `yield ack` (thời gian tổng
    hợp). `result_at` là lúc điện thoại trả kết quả, tính từ khi ack được nhả.
    Trả về danh sách các câu server nói ra.
    """
    import uuid as _uuid

    from services.action_callbacks import action_callbacks

    action_callbacks.reset()
    # 🔴 Mỗi lượt một `request_id` RIÊNG. Dùng chung một chuỗi cố định thì
    # thread nhả kết quả muộn của test trước resolve trúng lượt của test sau —
    # hai test xanh khi chạy lẻ, đỏ khi chạy chung.
    rid = _uuid.uuid4().hex
    final_payload = {
        "request_state": "succeeded",
        "result": {"level": 100, "volume_state": "changed"},
    }

    def resolve_later(request_id: str, delay: float) -> None:
        time.sleep(delay)
        action_callbacks.resolve(request_id, final_payload)

    with patch(
        "handlers.action_flow.call_service_api",
        return_value={"data": {"request_id": rid}},
    ), patch(
        "handlers.action_flow.get_request_status",
        return_value={"request_state": "processing"},
    ), patch(
        "handlers.action_flow.tts.speaking_seconds", return_value=1.2
    ):
        pieces = []
        gen = action_flow.run_action(
            "music_volume",
            "api/v1/service/music/volume",
            {"direction": "up"},
            ack="Đang chỉnh âm lượng.",
            failure="Chưa chỉnh được âm lượng.",
        )
        pieces.append(next(gen))  # câu ack
        # Bên tiêu thụ đang TỔNG HỢP câu ack — generator treo ở đây. Board vẫn
        # chưa phát ra tiếng nào.
        threading.Thread(
            target=resolve_later, args=(rid, synth_seconds + result_at), daemon=True
        ).start()
        time.sleep(synth_seconds)
        pieces.extend(gen)
    return pieces


def test_synthesis_time_is_not_subtracted_from_the_wait_window():
    """Kết quả về ở giây 1.0 SAU khi board bắt đầu phát câu ack 1.2 s.

    Người dùng vẫn đang nghe câu ack lúc đó, nên kết quả thật PHẢI kịp — dù
    trước đó TTS đã tiêu 0.7 s để tổng hợp chính câu ack ấy.
    """
    pieces = _run_action_with_a_slow_consumer(synth_seconds=0.7, result_at=1.0)
    spoken = " ".join(pieces)
    assert action_flow.TIMEOUT_LINE not in spoken, (
        f"bỏ lỡ kết quả thật vì trừ nhầm thời gian tổng hợp: {pieces!r}"
    )


def test_a_genuinely_late_result_still_times_out():
    """Mặt kia: sửa xong KHÔNG được thành chờ vô hạn. Kết quả về muộn hơn cả
    SÀN `VISIONCARE_MIN_WAIT_SECONDS` thì vẫn phải rơi vào nhánh hết giờ."""
    late = config.VISIONCARE_MIN_WAIT_SECONDS + 1.5
    pieces = _run_action_with_a_slow_consumer(synth_seconds=0.2, result_at=late)
    assert action_flow.TIMEOUT_LINE in " ".join(pieces)
