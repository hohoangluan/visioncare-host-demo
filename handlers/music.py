from collections.abc import Iterator

import config
from handlers.action_flow import forget, recall, remember, run_action

_PENDING_SONG = "pending_song_title"

# Người dùng đã nêu ca sĩ thì không cần hỏi lại. Nhận cả kiểu gõ ("Tên - Ca sĩ")
# lẫn kiểu nói tự nhiên ("Nơi này có anh của Sơn Tùng").
_ARTIST_MARKERS = (" - ", " của ", " by ")

# Câu trả lời mang nghĩa "ai cũng được, cứ phát đi".
_ANY_ARTIST_ANSWERS = ("cứ phát", "bất kỳ", "ai cũng được", "sao cũng được", "tuỳ", "tùy")

# Nhắc bấm thông báo ngay từ câu đầu: ứng dụng nhạc mở qua notification, màn
# hình đang bật thì Android chỉ hiện heads-up chứ không tự mở, nên người dùng
# cần biết ngay chứ không phải chờ hết câu kết quả.
_TAP_TO_OPEN = "Nếu màn hình đang bật, hãy nhấn vào thông báo trên điện thoại."
_ASK_ARTIST_HINT = "Nói tên ca sĩ, hoặc nói cứ phát để nghe bản phổ biến nhất."

# "mở nhạc đi" / "bật nhạc lên" là ý muốn nghe nhạc, chưa phải một bài cụ thể.
# Bộ phân loại trả 'song': 'nhạc' cho câu đầu và không trả gì cho câu sau (đo
# thật), nên nếu cứ đem đi tìm thì ứng dụng nhạc phát một bài bất kỳ tên "Nhạc",
# hoặc tệ hơn là một bài tên đúng bằng câu người dùng vừa nói.
_GENERIC_SONG_WORDS = frozenset({
    "nhạc", "bài hát", "bài nhạc", "bài", "một bài", "một bài hát",
    "nhạc đi", "bật nhạc", "mở nhạc", "nghe nhạc",
})
_ASK_SONG = "Bạn muốn nghe bài hát nào?"

# Không mặc định "tăng": người khiếm thị không nhìn được thanh âm lượng, một
# tiếng to đột ngột không ai yêu cầu là thứ họ không kịp trở tay.
_ASK_VOLUME = "Bạn muốn tăng hay giảm âm lượng?"

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
    _ASK_SONG,
    _ASK_VOLUME,
    *_PLAY_PROGRESS,
    _STOP_ACK,
    _STOP_FAILURE,
    *_STOP_PROGRESS,
    _VOLUME_ACK,
    _VOLUME_FAILURE,
    *_VOLUME_PROGRESS,
)


def _names_an_artist(song: str) -> bool:
    lowered = f" {song.lower()} "
    return any(marker in lowered for marker in _ARTIST_MARKERS)


def _names_a_song(song: str | None) -> bool:
    """`song` có phải một cái tên thật, hay chỉ là cách nói "tôi muốn nghe nhạc"."""
    cleaned = (song or "").strip().lower()
    return bool(cleaned) and cleaned not in _GENERIC_SONG_WORDS


def handle_play(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    params = params or {}
    volume = params.get("volume")

    pending = recall(_PENDING_SONG)
    if pending:
        # Lượt này là câu trả lời cho câu hỏi "ca sĩ nào?". Ghép tên ca sĩ vừa
        # nói vào tên bài đã hỏi, trừ khi người dùng bảo cứ phát bản nào cũng
        # được, hoặc họ đọc lại nguyên cả tên bài kèm ca sĩ. Ở nhánh này cả câu
        # người dùng vừa nói đều là câu trả lời, nên lấy `command_text` khi bộ
        # phân loại không tách được gì.
        forget(_PENDING_SONG)
        answer = (params.get("song") or command_text or "").strip()
        song = answer
        if any(phrase in answer.lower() for phrase in _ANY_ARTIST_ANSWERS):
            song = pending
        elif pending.lower() not in answer.lower():
            song = f"{pending} - {answer}"
    elif not _names_a_song(params.get("song")):
        # Muốn nghe nhạc nhưng chưa nói bài nào. Hỏi lại, chứ không lấy nguyên
        # câu lệnh làm tên bài: "bật nhạc lên" sẽ thành đi tìm một bài hát tên
        # đúng bằng câu đó.
        yield _ASK_SONG
        return
    else:
        song = params["song"].strip()

    if not pending and not _names_an_artist(song):
        # Chỉ có tên bài thì ứng dụng nhạc tự chọn trong hàng loạt bản trùng
        # tên — cover, remix, karaoke. Hỏi ca sĩ còn hơn phát nhầm rồi để người
        # khiếm thị tự mò cách đổi bài.
        remember(_PENDING_SONG, song)
        yield (
            f"Có thể có nhiều bài trùng tên {song}. Bạn muốn nghe của ca sĩ nào? "
            f"{_ASK_ARTIST_HINT}"
        )
        return

    payload = {"song": song}
    if volume is not None and isinstance(volume, int) and 0 <= volume <= 100:
        payload["volume"] = volume

    yield from run_action(
        "music_play",
        "api/v1/service/music/play",
        payload,
        ack=f"Đang mở nhạc, tìm bài {song}. {_TAP_TO_OPEN}",
        failure=f"Không thể phát bài hát {song}, vui lòng thử lại.",
        result_timeout=config.VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS,
        progress=_PLAY_PROGRESS,
    )


def handle_stop(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    yield from run_action(
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
        yield _ASK_VOLUME
        return

    yield from run_action(
        "music_volume",
        "api/v1/service/music/volume",
        payload,
        ack=_VOLUME_ACK,
        failure=_VOLUME_FAILURE,
        progress=_VOLUME_PROGRESS,
    )
