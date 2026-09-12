from collections.abc import Iterator

import config
from handlers import action_flow
from handlers.slots import SLOTS

# Nhắc bấm thông báo ngay từ câu đầu: ứng dụng nhạc mở qua notification, màn
# hình đang bật thì Android chỉ hiện heads-up chứ không tự mở, nên người dùng
# cần biết ngay chứ không phải chờ hết câu kết quả.
_TAP_TO_OPEN = "Nếu màn hình đang bật, hãy nhấn vào thông báo trên điện thoại."
_ASK_ARTIST_HINT = "Nói tên ca sĩ, hoặc nói cứ phát để nghe bản phổ biến nhất."

# `music_play` là action chờ lâu nhất (tới 40s), nên cũng là chỗ dễ khiến người
# dùng tưởng máy treo nhất.
_PLAY_PROGRESS = (
    "Vẫn đang tìm bài hát trên ứng dụng nhạc.",
    "Đã mở ứng dụng nhạc, đang chờ bài hát bắt đầu phát.",
    "Vẫn đang chờ nhạc, bạn chờ thêm chút nữa.",
    "Ứng dụng nhạc đang tải bài, chưa có gì bất thường.",
    "Sắp xong rồi, bạn chờ một chút.",
)

_STOP_ACK = "Đang dừng nhạc."
_STOP_FAILURE = "Không thể dừng nhạc, vui lòng thử lại."
_STOP_PROGRESS = ("Vẫn đang dừng nhạc, bạn chờ một chút.",)

_VOLUME_ACK = "Đang chỉnh âm lượng."
_VOLUME_FAILURE = "Không thể thay đổi âm lượng, vui lòng thử lại."
_VOLUME_PROGRESS = ("Vẫn đang chỉnh âm lượng, bạn chờ một chút.",)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio. Câu ack
# của `music_play` có tên bài nên không dựng sẵn được cả câu — chỉ nửa sau là cố
# định, và `_sentences()` cắt ở dấu chấm nên đúng nửa đó vẫn trúng cache.
STATIC_SPEECH: tuple[str, ...] = (
    _TAP_TO_OPEN,
    _ASK_ARTIST_HINT,
    *_PLAY_PROGRESS,
    _STOP_ACK,
    _STOP_FAILURE,
    *_STOP_PROGRESS,
    _VOLUME_ACK,
    _VOLUME_FAILURE,
    *_VOLUME_PROGRESS,
)


def handle_play(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = dict(params or {})
    volume = params.get("volume")
    song_title = str(params.get("song_title") or params.get("song") or "").strip()
    artist = str(params.get("artist") or "").strip()

    # A4 — `song_is_specific` là tín hiệu có cấu trúc từ intent model. Không
    # còn bảng từ khóa hữu hạn để đoán câu nào là một tên bài. `None` giữ tương
    # thích cho caller cũ đã gửi được một `song_title` rõ ràng.
    if params.get("song_is_specific") is False or not song_title:
        spec = SLOTS["song_title"]
        action_flow.set_pending(
            slot="song_title",
            intent="music_play",
            known={},
            question=spec.ask,
            kind=spec.kind,
        )
        yield spec.ask
        return

    if not artist and not params.get("artist_any"):
        spec = SLOTS["artist"]
        question = f"{spec.ask} {_ASK_ARTIST_HINT}"
        known = dict(params)
        known.update({
            "song_title": song_title,
            "song_is_specific": True,
            # Câu trả lời cho câu hỏi này ĐÃ LÀ một lần chốt rồi: người dùng
            # vừa tự nói ra tên ca sĩ (hoặc "cứ phát"). Hỏi lại "đúng không?"
            # ngay sau đó là bắt họ xác nhận hai lần cho một lần chọn.
            "play_confirmed": True,
        })
        action_flow.set_pending(
            slot="artist",
            intent="music_play",
            known=known,
            question=question,
            kind=spec.kind,
        )
        yield question
        return

    # 🔴 KHÔNG hỏi lại khi người dùng đã nói ĐỦ — người dùng chốt 2026-08-27.
    #
    # Ngày 2026-08-27 (sáng) từng thêm một bước chốt: nói đủ bài + ca sĩ thì
    # server đọc lại "Bạn muốn phát X của Y, đúng không?" rồi mới phát. Người
    # dùng BỎ nó cùng ngày, và lý do đúng: câu "phát cho tôi bài Nơi này có anh
    # của Sơn Tùng MTP" đã không còn gì để hiểu nhầm — hỏi lại chỉ cộng thêm
    # một lượt bấm nút và ~4 giây cho một việc đã rõ.
    #
    # Hỏi lại chỉ còn ở chỗ THẬT SỰ thiếu thông tin: không nghe ra tên bài, hoặc
    # có tên bài mà chưa có ca sĩ (hai nhánh ngay bên trên). Đó là làm rõ, không
    # phải xác nhận.

    # Host vẫn nhận hợp đồng chuỗi cũ. Chỉ nối khi cả hai slot có mặt; tên bài
    # chứa chữ "của" không còn bị tách/đoán tại handler.
    song = f"{song_title} - {artist}" if artist else song_title
    payload = {"song": song}
    if volume is not None and isinstance(volume, int) and 0 <= volume <= 100:
        payload["volume"] = volume

    yield from action_flow.run_action(
        "music_play",
        "api/v1/service/music/play",
        payload,
        ack=f"Đang mở nhạc, tìm bài {song}. {_TAP_TO_OPEN}",
        failure=f"Không thể phát bài hát {song}, vui lòng thử lại.",
        result_timeout=config.VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS,
        progress=_PLAY_PROGRESS,
    )


def handle_stop(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    yield from action_flow.run_action(
        "music_stop",
        "api/v1/service/music/stop",
        {},
        ack=_STOP_ACK,
        failure=_STOP_FAILURE,
        progress=_STOP_PROGRESS,
    )


def handle_volume(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    direction = params.get("direction")
    level = params.get("volume")

    payload = {}
    if direction in ("up", "down"):
        payload["direction"] = direction
    elif isinstance(level, int) and 0 <= level <= 100:
        payload["level"] = level
    else:
        # Trước đây mặc định "up". Nghe không rõ mà tự tăng là bắt người khiếm
        # thị hứng một tiếng to họ không yêu cầu, và họ không nhìn được thanh âm
        # lượng để chỉnh lại. Hỏi một câu rẻ hơn nhiều.
        spec = SLOTS["volume_direction"]
        action_flow.set_pending(
            slot="volume_direction",
            intent="music_volume",
            known={},
            question=spec.ask,
            kind=spec.kind,
        )
        yield spec.ask
        return

    yield from action_flow.run_action(
        "music_volume",
        "api/v1/service/music/volume",
        payload,
        ack=_VOLUME_ACK,
        failure=_VOLUME_FAILURE,
        progress=_VOLUME_PROGRESS,
    )
