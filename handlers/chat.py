import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime

import config
from handlers import action_flow
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
)

_OCR_CONTEXT_TEMPLATE = (
    'Người dùng vừa nhờ đọc một văn bản. Nội dung: "{transcript}". Nếu câu '
    'hỏi trỏ vào văn bản này ("chữ này", "khái niệm đó", "mục kia") thì trả '
    "lời dựa vào nó. Không liên quan thì bỏ qua."
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

# Biến thể của `_SEARCH_INSTRUCTION` khi CHƯA có vị trí nào dùng được (T07/C1).
# Bản gốc bảo "PHẢI tra ... địa điểm/quán/cửa hàng cụ thể nào quanh người
# dùng" — đúng nguyên văn câu đã gây ra vụ bịa quán phở khi ghép với vị trí
# rỗng: model vẫn cố tra rồi lấy đại một địa điểm, không biết có gần người
# dùng hay không. Bản này bỏ hẳn vế "quanh người dùng" và nói thẳng vì sao.
_SEARCH_INSTRUCTION_NO_LOCATION = (
    "Bạn tra được Google, và tự quyết định có tra hay không.\n"
    "PHẢI tra trước khi trả lời nếu câu trả lời thay đổi theo ngày: thời tiết, "
    "tin tức, giá cả, tỉ số, sự kiện đang diễn ra.\n"
    "KHÔNG được tra hay đoán địa điểm/quán/cửa hàng cụ thể nào lúc này, vì "
    "CHƯA xác định được vị trí người dùng (xem phần vị trí bên dưới) — tra rồi "
    "lấy đại một địa điểm mà không biết có gần người dùng hay không còn tệ hơn "
    "là nói thẳng là chưa biết họ ở đâu.\n"
    "KHÔNG cần tra với kiến thức chung, tính toán, định nghĩa, kể chuyện, chào "
    "hỏi, hay câu hỏi về chính cuộc trò chuyện này — cứ trả lời thẳng cho nhanh.\n"
    "Khi đã tra: TUYỆT ĐỐI không nêu tên địa điểm, quán, cửa hàng, thương hiệu, "
    "con số, giá hay khoảng cách nào không có trong kết quả tra cứu. Thà nói ít "
    "mà đúng. Tra không ra thì nói thẳng là chưa tra được, không suy đoán.\n"
)

# Cache rỗng/quá hạn PHẢI trả khối này, KHÔNG BAO GIỜ trả "" (T07/C1 — sửa
# quan trọng nhất của cả task). Trả "" thì prompt đồng thời (a) không có một
# chữ nào về vị trí và (b) `_SEARCH_INSTRUCTION` (khi search=True) vẫn bảo
# model tra "địa điểm quanh người dùng" — đúng công thức khiến model tự quy
# Tân Triều, Đồng Nai thành TP.HCM rồi bịa ra một quán phở không có thật.
_LOCATION_UNAVAILABLE = (
    "CHƯA lấy được vị trí hiện tại của người dùng.\n"
    "TUYỆT ĐỐI không đoán người dùng đang ở đâu, không nêu tên thành phố, "
    "quận, hay địa điểm cụ thể nào như thể biết chỗ họ đứng.\n"
    "Nếu câu hỏi cần vị trí, nói thẳng là chưa xác định được vị trí và gợi ý "
    "người dùng kiểm tra định vị trên điện thoại.\n"
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

    TOÀN THÂN nằm trong một try/except (T07/C2): trước đây `result['lat']`
    nằm NGOÀI try, nên một host trả thiếu `lat`/`lng` ném `KeyError` xuyên qua
    hàm này, xuyên qua `loop()` (cũng không có try/except), giết chết thread
    nền vĩnh viễn — trong khi `_REFRESHER_STARTED` vẫn `True` nên không ai gọi
    lại. Bất cứ lỗi nào ở đây chỉ được phép trả `False`, không bao giờ ném ra.
    """
    global _LOCATION_CACHE
    try:
        result = visioncare_client.get_device_location()
        if not result:
            # KHÔNG xoá toạ độ cũ khi lấy hỏng. Mất mạng một nhịp không có
            # nghĩa người dùng đã dịch đi đâu; toạ độ vài phút trước vẫn dùng
            # được, và `_location_text()` tự bỏ nó khi quá hạn.
            logger.info("Chưa lấy được vị trí ở nhịp này, giữ toạ độ cũ")
            return False

        age = _fix_age_seconds(result.get("captured_at"))
        if age is not None and age > config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS:
            # Điện thoại trả về vị trí cuối cùng nó biết chứ không phải fix
            # mới — app bị treo nền, hoặc định vị đang tắt. Nhận vào là dạy
            # trợ lý trả lời tự tin về một chỗ người dùng rời đi từ lâu.
            logger.warning(
                "Bỏ bản định vị cũ %.0f phút (captured_at=%s), giữ toạ độ trước đó",
                age / 60, result.get("captured_at"),
            )
            return False

        # `.get()` chứ không phải `result["lat"]`: thiếu khoá là kết quả hỏng,
        # không phải lý do để ném `KeyError` giết thread nền.
        lat = result.get("lat")
        lng = result.get("lng")
        if lat is None or lng is None:
            logger.warning("Kết quả định vị thiếu lat/lng, coi như lấy hỏng: %r", result)
            return False

        address = result.get("address")
        where = address or f"toạ độ {lat}, {lng}"
        text = (
            f"Vị trí hiện tại của người dùng: {where} "
            f"(toạ độ {lat}, {lng}).\n"
            # Nói thẳng là cấm hỏi lại: đo thật, chỉ đưa vị trí vào prompt thì
            # model vẫn hỏi ngược "bạn muốn xem thời tiết ở đâu?", mà người
            # dùng khiếm thị không đọc bản đồ để trả lời. Cấm đổi sang thành
            # phố lớn vì nó từng tự quy Tân Triều, Đồng Nai thành TP.HCM —
            # lệch khoảng 20 km.
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
    except Exception:  # noqa: BLE001 - thread nền chết lặng còn tệ hơn
        logger.exception("Lỗi khi lấy vị trí ở thread nền")
        return False


# Backoff khi đang hỏng liên tiếp (T07/C3). GPS bật lại lúc t+10s mà phải chờ
# tới nhịp bình thường (mặc định 240s) tiếp theo là mất gần 4 phút không cần
# thiết. Hỏng lần 1 → 15s, lần 2 → 30s, lần 3 trở đi → giữ 60s. Thành công một
# lần là về thẳng nhịp bình thường, không dò lại từ đầu.
_BACKOFF_SCHEDULE_SECONDS: tuple[float, ...] = (15.0, 30.0, 60.0)


def _next_refresh_interval(consecutive_failures: int) -> float:
    """Nhịp chờ trước lần thử tiếp theo, theo số lần hỏng LIÊN TIẾP gần nhất.

    Hàm thuần, không đụng cache/thread, để test đo được backoff trực tiếp mà
    không phải dựng thread thật hay chờ giây thật.
    """
    if consecutive_failures <= 0:
        return config.CHAT_LOCATION_REFRESH_SECONDS
    index = min(consecutive_failures, len(_BACKOFF_SCHEDULE_SECONDS)) - 1
    return _BACKOFF_SCHEDULE_SECONDS[index]


def _location_refresh_loop() -> None:
    """Thân vòng lặp thật của thread nền (T07/C2, C3, C4).

    Tách khỏi `start_location_refresher` để test gọi thẳng được: cho `time.sleep`
    giả ném một ngoại lệ sau N lần gọi là dừng được vòng `while True` mà không
    cần chờ giây thật hay dựng thread.

    Mỗi vòng bọc `refresh_location_once()` trong try/except RIÊNG — bản thân
    hàm đó đã tự bắt lỗi và trả `False`, nhưng đây là lưới an toàn thứ hai:
    KHÔNG có ngoại lệ nào từ đây được phép thoát ra ngoài vòng lặp.
    """
    consecutive_failures = 0
    while True:
        try:
            ok = refresh_location_once()
        except Exception:
            logger.exception("Lỗi không mong đợi trong vòng lặp lấy vị trí ở thread nền")
            ok = False

        if ok:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                # 42/42 nhịp hỏng liên tiếp từng chỉ log INFO — không ai nhìn
                # ra đó là vĩnh viễn chứ không phải một lần trục trặc.
                logger.error(
                    "Lấy vị trí hỏng %d lần liên tiếp, có thể đã chết hẳn — "
                    "kiểm tra app/điện thoại (CURRENT_LOCATION_UNAVAILABLE?)",
                    consecutive_failures,
                )

        time.sleep(_next_refresh_interval(consecutive_failures))


def start_location_refresher() -> None:
    """Chạy nền, giữ toạ độ luôn nóng. Gọi một lần lúc khởi động server.

    Daemon thread: server tắt thì nó đi theo, không giữ tiến trình sống.
    """
    global _REFRESHER_STARTED
    if _REFRESHER_STARTED:
        return
    _REFRESHER_STARTED = True

    def loop() -> None:
        # `_location_refresh_loop` đã tự bọc từng vòng, nhưng đây là lưới an
        # toàn NGOÀI CÙNG (T07/C2): một lỗi bất ngờ nằm ngoài mọi dự liệu ở
        # trên (kể cả trong chính việc log) cũng không được phép giết thread —
        # `_REFRESHER_STARTED` đã `True` nên không ai khởi động lại nó.
        try:
            _location_refresh_loop()
        except Exception:
            logger.exception(
                "Thread lấy vị trí thoát ngoài ý muốn, vị trí sẽ không cập nhật "
                "nữa cho tới khi restart server"
            )

    threading.Thread(target=loop, name="location-refresher", daemon=True).start()
    logger.info(
        "Thread nền lấy vị trí đã chạy, nhịp %.0fs",
        config.CHAT_LOCATION_REFRESH_SECONDS,
    )

_WEEKDAYS = [
    "thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật",
]

def reset_history() -> None:
    action_flow.clear_history()


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


def _recent_turns(device_key: str | None = None) -> list[tuple[str, str]]:
    """Các lượt chat/action còn hạn trong Session dùng chung của thiết bị."""
    return action_flow.recent_history(device_key=device_key)


def _location_available() -> bool:
    """Có vị trí nào dùng được để nhét vào prompt hay không (mới hoặc hơi cũ).

    Chỉ dùng để quyết định `_search_instruction` có được phép bảo model tra
    "quanh người dùng" hay không — bảo model tra chỗ quanh một người mà chính
    server không biết đang đứng đâu là tự mâu thuẫn với `_LOCATION_UNAVAILABLE`
    ngay bên dưới nó trong cùng một prompt.
    """
    cached, cached_at = _LOCATION_CACHE
    if not cached:
        return False
    return time.monotonic() - cached_at < config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS


def _location_text() -> str:
    """Vị trí hiện tại, lấy từ cache mà thread nền giữ nóng. KHÔNG BAO GIỜ chờ,
    và KHÔNG BAO GIỜ trả chuỗi rỗng (T07/C1).

    Ba tầng theo tuổi cache:
    - còn trong TTL: dùng thẳng, không kèm chú thích.
    - quá TTL nhưng chưa quá MAX_FIX_AGE (P9): vẫn dùng NHƯNG nói rõ là đã cũ —
      người dùng nghe không phân biệt được "chưa có vị trí" với "vị trí cũ"
      nếu im lặng chuyển thẳng về khối cấm bịa.
    - quá MAX_FIX_AGE hoặc chưa từng có: khối `_LOCATION_UNAVAILABLE`, KHÔNG
      phải "". Trả "" là bug gốc: prompt vừa không có vị trí vừa bị
      `_SEARCH_INSTRUCTION` giục tra "quanh người dùng" — model bịa thành phố.
    """
    cached, cached_at = _LOCATION_CACHE
    if not cached:
        return _LOCATION_UNAVAILABLE

    age = time.monotonic() - cached_at
    if age < config.CHAT_LOCATION_TTL_SECONDS:
        return cached
    if age < config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS:
        minutes = max(1, round(age / 60))
        return cached + (
            f"Lưu ý: vị trí trên đã lấy được khoảng {minutes} phút trước, có "
            "thể người dùng đã di chuyển — nếu câu trả lời phụ thuộc vào đúng "
            "chỗ đứng hiện tại thì nói kèm là vị trí hơi cũ.\n"
        )
    return _LOCATION_UNAVAILABLE


def _search_instruction(search: bool, search_failed: bool, has_location: bool) -> str:
    if search_failed:
        return _SEARCH_UNAVAILABLE_INSTRUCTION
    if not search:
        return ""
    return _SEARCH_INSTRUCTION if has_location else _SEARCH_INSTRUCTION_NO_LOCATION


def _build_prompt(
    command_text: str,
    search: bool = False,
    search_failed: bool = False,
    *,
    device_key: str | None = None,
) -> str:
    # G7: tiền tố thật sự bất biến đứng trước. Giờ/vị trí/OCR/lịch sử/câu mới
    # đều nằm sau để hai lượt khác nhau vẫn dùng chung toàn bộ prefix này.
    parts = [
        _SYSTEM_PROMPT,
        _search_instruction(search, search_failed, _location_available()),
        f"Bây giờ là {_now_text()}.",
        # Luôn nhét vị trí, không phân loại xem câu này có cần hay không. Cache
        # do thread nền giữ nóng nên đọc ra tức thì.
        _location_text(),
    ]

    cached_ocr = action_flow.get_last_ocr(300.0, device_key=device_key)
    if cached_ocr is not None:
        parts.append(
            _OCR_CONTEXT_TEMPLATE.format(transcript=cached_ocr["text"])
        )

    turns = _recent_turns(device_key)
    if turns:
        parts.append("\nCác lượt trước (cũ trước, mới sau):")
        for user, reply in turns:
            parts.append(f"Người dùng: {user}\nTrợ lý: {reply}")

    parts.append(f'\nNgười dùng vừa nói: "{command_text}"\nTrợ lý:')
    return "\n".join(parts)


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
    device_key = (params or {}).get("_device_key")
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
        return action_flow.remember_stream(
            command_text,
            vlm.generate_stream(
                _build_prompt(
                    command_text, search_failed=True, device_key=device_key
                ),
                search=False,
            ),
            device_key=device_key,
        )
    return action_flow.remember_stream(
        command_text,
        _stream_with_search_fallback(command_text, device_key=device_key),
        device_key=device_key,
    )


def _stream_with_search_fallback(
    command_text: str, *, device_key: str | None = None
) -> Iterator[str]:
    """Tra Google; tra hỏng thì trả lời lại và nói rõ là chưa tra được.

    Grounding có hạn mức riêng với hạn mức gọi model thường — đã gặp thật: lượt
    chat bình thường chạy tốt trong khi lượt có search trả `429`. Không có nhánh
    dự phòng thì người dùng chỉ nghe "có lỗi xảy ra", không biết là hỏng mạng,
    hỏng máy hay câu hỏi sai.
    """
    grounded = vlm.generate_stream(
        _build_prompt(command_text, search=True, device_key=device_key), search=True
    )
    try:
        first = next(grounded)
    except StopIteration:
        return
    except vlm.VLMError as exc:
        logger.warning("Tra cứu hỏng, trả lời không có tra cứu: %s", exc)
        yield from vlm.generate_stream(
            _build_prompt(
                command_text, search_failed=True, device_key=device_key
            ),
            search=False,
        )
        return

    yield first
    yield from grounded
