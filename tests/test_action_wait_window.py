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


def test_wait_window_matches_the_ack_length():
    """Câu ack dài bao nhiêu thì chờ bấy nhiêu — không phải một hằng số."""
    ngan = action_flow.wait_window_seconds("Đang dừng nhạc.")
    dai = action_flow.wait_window_seconds(
        "Đang mở nhạc, tìm bài Nơi này có anh. Nếu màn hình đang bật, chạm để mở."
    )
    assert dai > ngan
    assert ngan == pytest.approx(tts.speaking_seconds("Đang dừng nhạc."), abs=0.01)


def test_wait_window_never_leaves_the_user_in_silence():
    """🔴 Ràng buộc THẬT SỰ quan trọng: cửa sổ không bao giờ dài hơn câu ack.

    Dài hơn nghĩa là board đã nói xong mà server còn ngồi chờ — đúng định
    nghĩa của quãng im lặng mà người khiếm thị không phân biệt được với hỏng.
    """
    for ack in (
        "Đang dừng nhạc.",
        "Đang chỉnh âm lượng.",
        "Đang dừng chỉ đường.",
        "Đang kích hoạt cuộc gọi khẩn cấp.",
        "Đang tìm số của Nguyễn Văn A.",
    ):
        assert action_flow.wait_window_seconds(ack) <= tts.speaking_seconds(ack) + 1e-6


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
