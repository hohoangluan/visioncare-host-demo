import logging
import threading
import time
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime

import config
from models import vlm
from services import visioncare_client

logger = logging.getLogger("blind_assist")

# Câu trả lời đi thẳng ra TTS, người dùng không nhìn màn hình: mọi ký hiệu chỉ
# có nghĩa khi ĐỌC BẰNG MẮT (dấu sao, gạch đầu dòng, emoji) đều thành rác khi
# đọc thành tiếng, nên cấm ngay trong prompt thay vì lọc lại ở dưới.
_SYSTEM_PROMPT = (
    "Bạn là trợ lý giọng nói của một người khiếm thị, đang trò chuyện tự nhiên "
    "bằng tiếng Việt. Câu trả lời sẽ được ĐỌC THÀNH TIẾNG.\n"
    "\n"
    "CÁCH VIẾT:\n"
    "- Thuần văn nói. TUYỆT ĐỐI không markdown, không dấu sao, không gạch đầu "
    "dòng, không emoji, không ký hiệu chỉ đọc được bằng mắt. Cần liệt kê thì "
    "viết thành câu liền mạch.\n"
    "- Người dùng không nhìn thấy: đừng bảo họ xem, nhìn hay đọc thứ gì.\n"
    # Đo thật: cùng một bộ prompt mà lượt "lô ca ta xi mà" xưng em/anh còn các
    # lượt khác xưng tôi/bạn. Người dùng chỉ có kênh âm thanh, nên đổi cách xưng
    # hô giữa hai lượt nghe như vừa đổi sang một người khác.
    "- Luôn xưng \"tôi\" và gọi người dùng là \"bạn\". Không đổi sang "
    "em/anh/chị/cháu ở bất kỳ lượt nào. Không thêm \"dạ\", \"ạ\" đầu hay cuối "
    "câu.\n"
    "\n"
    "ĐỘ DÀI — nghe bằng tai thì không tua lại được, câu dài là câu bị quên:\n"
    "- Mặc định 1 đến 3 câu. Chỉ dài hơn khi người dùng hỏi một thứ thật sự "
    "cần nhiều bước.\n"
    "- Trả lời THẲNG vào trọng tâm câu hỏi ngay câu đầu tiên. Không mở bài, "
    "không nhắc lại câu hỏi, không rào đón, không xin phép.\n"
    "- Hỏi gì đáp nấy. Đừng thêm thông tin không được hỏi, đừng gợi ý việc "
    "tiếp theo, đừng hỏi ngược lại nếu không thật sự cần.\n"
    "- Hỏi mình đang ở đâu thì đọc thẳng địa điểm hiện tại. Hỏi mấy giờ thì đọc "
    "thẳng giờ. Đừng giải thích vì sao mình biết.\n"
    "- Được kể chuyện, kể đùa, đọc thơ khi người dùng nhờ — nhưng kể gọn, vào "
    "thẳng chuyện, bỏ phần dẫn dắt.\n"
    "\n"
    "KHÔNG BỊA — đây là ràng buộc quan trọng nhất:\n"
    "- Không biết thì nói thẳng là không biết. Không suy đoán, không lấp chỗ "
    "trống bằng thứ nghe có vẻ hợp lý.\n"
    "- Câu người dùng vừa nói là do máy nhận dạng giọng nói ghi lại, nên có thể "
    "nghe nhầm thành một chuỗi từ rời rạc, hoặc mic chỉ thu được tiếng ồn. Khi "
    "bạn KHÔNG đoán ra người ta muốn gì, hãy nói ngắn gọn rằng bạn chưa hiểu và "
    "mời họ nói lại. TUYỆT ĐỐI không bịa ra một câu hỏi rồi tự trả lời nó.\n"
    "- Nhưng đừng vội bỏ cuộc: câu ngắn, cụt, sai ngữ pháp mà vẫn đoán ra ý thì "
    "cứ trả lời bình thường. Chỉ nói chưa hiểu khi thật sự không có manh mối.\n"
    "{search}"
    "Bây giờ là {now}.\n"
    "{location}"
)

# Chỉ thêm khi lượt này thật sự bật Google Search. Dán câu "bạn tra được
# Google" vào lượt không có tool là dạy model nói dối về thứ nó vừa làm.
#
# ĐÃ SỬA khi bỏ cờ `needs_web`: bản cũ viết "câu hỏi này cần thông tin thực tế
# nên PHẢI gọi tra cứu TRƯỚC" — đúng khi bộ phân loại đã kết luận câu này cần
# tra, nhưng giờ tool gắn vào MỌI lượt nên câu đó ép model tra cả khi hỏi
# "một cân bằng bao nhiêu gam". Chuyển thành trao quyền quyết định: nói rõ khi
# nào PHẢI tra, khi nào KHÔNG cần, rồi để model tự chọn lúc sinh chữ.
#
# Đây chính là chỗ thay cho cả bộ phân loại `needs_web`: "câu này có cần tra
# không" là tập mở vô hạn, không bộ dữ liệu nào phủ hết — nhưng model đọc câu
# hỏi rồi tự quyết thì không cần liệt kê trường hợp nào.
_SEARCH_INSTRUCTION = (
    "Bạn tra được Google, và tự quyết định có tra hay không.\n"
    "PHẢI tra trước khi trả lời nếu câu trả lời thay đổi theo ngày hoặc theo "
    "nơi chốn: thời tiết, tin tức, giá cả, tỉ số, giờ mở cửa, sự kiện đang diễn "
    "ra, hay bất cứ địa điểm/quán/cửa hàng cụ thể nào quanh người dùng.\n"
    "KHÔNG cần tra với kiến thức chung, tính toán, định nghĩa, kể chuyện, chào "
    "hỏi, hay câu hỏi về chính cuộc trò chuyện này — cứ trả lời thẳng cho nhanh.\n"
    "Khi đã tra: TUYỆT ĐỐI không nêu tên địa điểm, quán, cửa hàng, thương hiệu, "
    "con số, giá hay khoảng cách nào không có trong kết quả tra cứu. Thà nói ít "
    "mà đúng. Tra không ra thì nói thẳng là chưa tra được, không suy đoán.\n"
)

# Dùng khi lượt tra cứu hỏng (hết quota, mất mạng). Trí nhớ của model dừng ở
# thời điểm huấn luyện: hỏi ngày hôm nay mà không tra, nó trả lời lệch gần hai
# năm — nên phải cấm đoán chứ không để nó tự tin nói bừa.
_SEARCH_UNAVAILABLE_INSTRUCTION = (
    "Bạn KHÔNG tra cứu được lúc này. Câu hỏi này cần thông tin thay đổi theo "
    "ngày mà bạn không có. Hãy nói thẳng với người dùng là hiện chưa tra cứu "
    "được thông tin đó, và tuyệt đối không đoán con số, ngày tháng hay tình "
    "hình hiện tại. Được phép nói phần kiến thức chung không đổi theo thời "
    "gian, nếu có.\n"
)

# Vị trí đã lấy và mốc thời gian lấy, do thread nền ghi vào.
#
# Đường xử lý request chỉ ĐỌC cache này, không bao giờ tự đi lấy: lấy vị trí là
# một vòng gọi xuống điện thoại có poll, trần 12s, và đặt nó trên đường người
# dùng chờ là bắt họ đứng im ngần ấy giây trước khi nghe được chữ nào.
_LOCATION_CACHE: tuple[str | None, float] = (None, 0.0)
_LOCATION_LOCK = threading.Lock()
_REFRESHER_STARTED = False


def reset_location_cache() -> None:
    """Quên vị trí đã lấy (dùng trong test và khi đổi thiết bị)."""
    global _LOCATION_CACHE
    with _LOCATION_LOCK:
        _LOCATION_CACHE = (None, 0.0)


def to_vn_time_str(captured_at: str | None) -> str:
    if not captured_at:
        return "Không có"
    try:
        stamp = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        vn_stamp = stamp.astimezone(timezone(timedelta(hours=7)))
        return vn_stamp.strftime("%H:%M:%S (%d/%m/%Y)")
    except Exception:
        return str(captured_at)


def _fix_age_seconds(captured_at: str | None) -> float | None:
    """Bản định vị này già bao nhiêu giây, theo đồng hồ điện thoại.

    `None` khi không đọc được mốc thời gian — lúc đó cứ nhận, vì từ chối một
    toạ độ chỉ vì thiếu metadata là mất chức năng để đổi lấy không gì cả.
    """
    if not captured_at:
        return None
    try:
        # `fromisoformat` của Python 3.11+ đọc được hậu tố "Z".
        stamp = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        logger.info("Không đọc được captured_at=%r, bỏ qua kiểm tuổi", captured_at)
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (datetime.now(UTC) - stamp).total_seconds()


def refresh_location_once() -> bool:
    """Đi lấy vị trí một lần và ghi vào cache. Trả về lấy được hay không.

    Tách khỏi vòng lặp để test gọi được thẳng, và để `app.py` lấy lượt đầu ngay
    lúc khởi động thay vì đợi hết một nhịp.
    """
    global _LOCATION_CACHE
    try:
        result = visioncare_client.get_device_location()
    except Exception:  # noqa: BLE001 - thread nền chết lặng còn tệ hơn
        logger.exception("Lỗi khi lấy vị trí ở thread nền")
        return False

    if not result:
        # KHÔNG xoá toạ độ cũ khi lấy hỏng. Mất mạng một nhịp không có nghĩa
        # người dùng đã dịch đi đâu; toạ độ vài phút trước vẫn dùng được, và
        # `_location_text()` tự bỏ nó khi quá hạn.
        logger.info("Chưa lấy được vị trí ở nhịp này, giữ toạ độ cũ")
        return False

    age = _fix_age_seconds(result.get("captured_at"))
    vn_time = to_vn_time_str(result.get("captured_at"))
    if age is not None and age > config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS:
        # Điện thoại trả về vị trí cuối cùng nó biết chứ không phải fix mới —
        # app bị treo nền, hoặc định vị đang tắt. Nhận vào là dạy trợ lý trả lời
        # tự tin về một chỗ người dùng rời đi từ lâu.
        logger.warning(
            "Bỏ bản định vị cũ %.0f phút (captured_at=%s), giữ toạ độ trước đó",
            age / 60, result.get("captured_at"),
        )
        return False

    address = result.get("address")
    where = address or f"toạ độ {result['lat']}, {result['lng']}"
    text = (
        f"Vị trí hiện tại của người dùng: {where} "
        f"(toạ độ {result['lat']}, {result['lng']}).\n"
        # Nói thẳng là cấm hỏi lại: đo thật, chỉ đưa vị trí vào prompt thì model
        # vẫn hỏi ngược "bạn muốn xem thời tiết ở đâu?", mà người dùng khiếm thị
        # không đọc bản đồ để trả lời. Cấm đổi sang thành phố lớn vì nó từng
        # tự quy Tân Triều, Đồng Nai thành TP.HCM — lệch khoảng 20 km.
        "Tính theo đúng vị trí này. TUYỆT ĐỐI không hỏi lại người dùng đang ở "
        "đâu, và không đổi sang thành phố lớn gần đó cho tiện.\n"
        "Khi gợi ý quán ăn, cửa hàng hay địa điểm: mọi gợi ý phải ở QUANH ĐÚNG "
        "vị trí trên, không phải ở trung tâm tỉnh/thành hay một khu nổi tiếng "
        "cách đó hàng chục cây số. Nói rõ chỗ đó nằm ở đâu so với người dùng "
        "(tên đường, xã/phường) để họ biết có tới được không. Quanh đây không "
        "có gì thì nói thẳng là quanh đây không có, chứ đừng với ra xa để có "
        "cái mà kể.\n"
        "Chỉ nhắc tới vị trí khi câu hỏi thật sự cần; đừng thêm thông tin thừa.\n"
    )
    with _LOCATION_LOCK:
        _LOCATION_CACHE = (text, time.monotonic())
    return True


def start_location_refresher() -> None:
    """Chạy nền, giữ toạ độ luôn nóng. Gọi một lần lúc khởi động server.

    Daemon thread: server tắt thì nó đi theo, không giữ tiến trình sống.
    """
    global _REFRESHER_STARTED
    if _REFRESHER_STARTED:
        return
    _REFRESHER_STARTED = True

    def loop() -> None:
        while True:
            refresh_location_once()
            time.sleep(config.CHAT_LOCATION_REFRESH_SECONDS)

    threading.Thread(target=loop, name="location-refresher", daemon=True).start()
    logger.info(
        "Thread nền lấy vị trí đã chạy, nhịp %.0fs",
        config.CHAT_LOCATION_REFRESH_SECONDS,
    )

_WEEKDAYS = [
    "thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật",
]

# (câu người dùng, câu trả lời, mốc thời gian). deque có maxlen tự bỏ lượt cũ
# nhất, nên lịch sử không phình vô hạn theo thời gian chạy của server.
_HISTORY: deque[tuple[str, str, float]] = deque(maxlen=config.CHAT_HISTORY_TURNS)


def reset_history() -> None:
    _HISTORY.clear()


def _now_text() -> str:
    """Giờ máy chủ, viết sẵn bằng tiếng Việt.

    Gemini không tự biết bây giờ là mấy giờ — không nhét vào prompt thì câu
    "mấy giờ rồi" nhận về một lời từ chối hoặc một con số bịa.
    """
    now = datetime.now()
    return (
        f"{now.hour} giờ {now.minute} phút, {_WEEKDAYS[now.weekday()]} "
        f"ngày {now.day} tháng {now.month} năm {now.year}"
    )


def _recent_turns() -> list[tuple[str, str]]:
    """Các lượt gần đây, sau khi bỏ lịch sử đã nguội.

    Người dùng bỏ máy rồi quay lại sau vài giờ là một cuộc trò chuyện khác;
    kéo theo lượt cũ chỉ khiến model trả lời lạc đề.
    """
    if _HISTORY and time.monotonic() - _HISTORY[-1][2] > config.CHAT_HISTORY_TTL_SECONDS:
        _HISTORY.clear()
    return [(user, reply) for user, reply, _ in _HISTORY]


def _location_text() -> str:
    """Vị trí hiện tại, lấy từ cache mà thread nền giữ nóng. KHÔNG BAO GIỜ chờ.

    Chưa có hoặc đã quá hạn thì trả chuỗi rỗng — thà để model nói "không biết
    bạn đang ở đâu" còn hơn nó đoán một thành phố, và hơn hẳn việc bắt người
    dùng đứng chờ hết vòng poll xuống điện thoại.
    """
    cached, cached_at = _LOCATION_CACHE
    if cached and time.monotonic() - cached_at < config.CHAT_LOCATION_TTL_SECONDS:
        return cached
    return ""


def _search_instruction(search: bool, search_failed: bool) -> str:
    if search_failed:
        return _SEARCH_UNAVAILABLE_INSTRUCTION
    return _SEARCH_INSTRUCTION if search else ""


def _build_prompt(command_text: str, search: bool = False, search_failed: bool = False) -> str:
    parts = [
        _SYSTEM_PROMPT.format(
            now=_now_text(),
            search=_search_instruction(search, search_failed),
            # Luôn nhét vị trí, không phân loại xem câu này có cần hay không.
            # Cache do thread nền giữ nóng nên đọc ra tức thì, và đo được là
            # thêm ~75 token này không làm mảnh đầu chậm đi
            # (xem `config.CHAT_LOCATION_REFRESH_SECONDS`).
            location=_location_text(),
        )
    ]

    turns = _recent_turns()
    if turns:
        parts.append("\nCác lượt trước (cũ trước, mới sau):")
        for user, reply in turns:
            parts.append(f"Người dùng: {user}\nTrợ lý: {reply}")

    parts.append(f'\nNgười dùng vừa nói: "{command_text}"\nTrợ lý:')
    return "\n".join(parts)


def _remember(command_text: str, pieces: Iterator[str]) -> Iterator[str]:
    """Đẩy từng mảnh ra ngay, đồng thời gom lại để ghi vào lịch sử khi xong.

    Chỉ ghi khi luồng chạy hết: lỗi giữa chừng thì câu trả lời cụt đó không
    được làm bối cảnh cho lượt sau.
    """
    reply: list[str] = []
    for piece in pieces:
        reply.append(piece)
        yield piece

    text = "".join(reply).strip()
    if text:
        _HISTORY.append((command_text, text, time.monotonic()))


def handle(image: bytes, command_text: str, params: dict | None = None) -> Iterator[str]:
    """Trò chuyện tự do, không kèm ảnh.

    `image` bị bỏ qua có chủ ý: mọi câu hỏi thật sự cần ảnh đều đã có intent
    riêng (ocr/find/money/space) bắt trước. Gửi kèm ảnh ở đây chỉ làm mỗi lượt
    chat chậm thêm và tốn token mà không đổi được câu trả lời.

    `params` không còn được đọc. Trước đây nó mang `needs_location`/`needs_web`
    do một lượt gọi Gemini RIÊNG sinh ra, nằm nối tiếp trước handler — người
    dùng chờ trắng ~0.9s chỉ để lấy hai giá trị boolean. Cả hai giờ đã bỏ:
    vị trí do thread nền giữ nóng nên cứ nhét vào, còn có tra cứu hay không thì
    chính model quyết lúc sinh chữ. Giữ tham số lại để không phải sửa `router`
    và các handler khác cho khớp chữ ký.
    """
    if not config.CHAT_ALWAYS_SEARCH:
        # `search_failed=True`, không phải prompt trần. Tắt tra cứu bằng cấu hình
        # và tra cứu hỏng vì 429 là CÙNG MỘT tình huống với model: nó không có
        # dữ liệu mới. Không nói ra thì nó lấp chỗ trống — đo thật trên đúng
        # nhánh này, với vị trí thật ở Tân Triều, Đồng Nai:
        #
        #   "quanh đây có quán ăn nào không"
        #     -> "quán phở Thanh Bình trên đường ĐT768 cách bạn khoảng hai trăm
        #         mét, và quán cơm bình dân Ba Chợ..."     BỊA cả tên lẫn cự ly
        #   "chỗ tôi có mưa không"
        #     -> "trời không có mưa, thời tiết đang tạnh ráo"   BỊA thời tiết
        #
        # Cùng ba câu đó qua `search_failed=True` thì cả ba đều nói thẳng là
        # chưa tra cứu được. Một cờ boolean là toàn bộ khác biệt giữa "không
        # biết" và "bịa một quán phở có địa chỉ và khoảng cách".
        return _remember(
            command_text,
            vlm.generate_stream(
                _build_prompt(command_text, search_failed=True), search=False
            ),
        )
    return _remember(command_text, _stream_with_search_fallback(command_text))


def _stream_with_search_fallback(command_text: str) -> Iterator[str]:
    """Tra Google; tra hỏng thì trả lời lại và nói rõ là chưa tra được.

    Grounding có hạn mức riêng với hạn mức gọi model thường — đã gặp thật: lượt
    chat bình thường chạy tốt trong khi lượt có search trả `429`. Không có nhánh
    dự phòng thì người dùng chỉ nghe "có lỗi xảy ra", không biết là hỏng mạng,
    hỏng máy hay câu hỏi sai.
    """
    grounded = vlm.generate_stream(_build_prompt(command_text, search=True), search=True)
    try:
        first = next(grounded)
    except StopIteration:
        return
    except vlm.VLMError as exc:
        logger.warning("Tra cứu hỏng, trả lời không có tra cứu: %s", exc)
        yield from vlm.generate_stream(
            _build_prompt(command_text, search_failed=True), search=False
        )
        return

    yield first
    yield from grounded
