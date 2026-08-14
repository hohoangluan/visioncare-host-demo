import logging
import time
from collections import deque
from collections.abc import Iterator
from datetime import datetime

import config
from models import vlm
from services import visioncare_client

logger = logging.getLogger("blind_assist")

# Câu trả lời đi thẳng ra TTS, người dùng không nhìn màn hình: mọi ký hiệu chỉ
# có nghĩa khi ĐỌC BẰNG MẮT (dấu sao, gạch đầu dòng, emoji) đều thành rác khi
# đọc thành tiếng, nên cấm ngay trong prompt thay vì lọc lại ở dưới.
_SYSTEM_PROMPT = (
    "Bạn là trợ lý giọng nói của một người khiếm thị, đang trò chuyện tự nhiên "
    "bằng tiếng Việt. Câu trả lời sẽ được đọc thành tiếng: viết thuần văn nói, "
    "TUYỆT ĐỐI không markdown, không dấu sao, không gạch đầu dòng, không emoji, "
    "không ký hiệu chỉ đọc được bằng mắt. Trả lời ngắn gọn, thân thiện, đủ ý; "
    "cần liệt kê thì viết thành câu liền mạch. Không biết thì nói thẳng là "
    "không biết, tuyệt đối không bịa.\n"
    "Người dùng không nhìn thấy: đừng bảo họ xem, nhìn hay đọc thứ gì.\n"
    "{search}"
    "Bây giờ là {now}.\n"
    "{location}"
)

# Chỉ thêm khi lượt này thật sự bật Google Search. Dán câu "bạn tra được
# Google" vào lượt không có tool là dạy model nói dối về thứ nó vừa làm.
_SEARCH_INSTRUCTION = (
    "Bạn tra được Google. Câu hỏi này cần thông tin thực tế nên PHẢI gọi tra "
    "cứu TRƯỚC, rồi mới trả lời.\n"
    "TUYỆT ĐỐI không nêu tên địa điểm, quán, cửa hàng, thương hiệu, con số, giá "
    "hay khoảng cách nào không có trong kết quả tra cứu. Thà nói ít mà đúng.\n"
    "Tra không ra thì nói thẳng là chưa tra được, không suy đoán.\n"
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

# Vị trí đã lấy và mốc thời gian lấy. Toạ độ gần như không đổi giữa hai lượt
# chat liền nhau, mà mỗi lần lấy tốn một vòng gọi điện thoại vài giây.
_LOCATION_CACHE: tuple[str | None, float] = (None, 0.0)
_LOCATION_TTL_SECONDS = 300.0
# Lấy hỏng thì thử lại sớm hơn — định vị có thể vừa được bật lại.
_LOCATION_RETRY_SECONDS = 60.0


def reset_location_cache() -> None:
    """Quên vị trí đã lấy (dùng trong test và khi đổi thiết bị)."""
    global _LOCATION_CACHE
    _LOCATION_CACHE = (None, 0.0)

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
    """Vị trí hiện tại của người dùng, viết sẵn cho prompt.

    Lấy từ điện thoại qua `location/get`, có cache ngắn: mỗi lượt chat mà gọi
    lại là thêm vài giây chờ cho một toạ độ gần như không đổi.

    Không có vị trí thì trả chuỗi rỗng — thà để model nói "không biết bạn đang
    ở đâu" còn hơn nó đoán một thành phố.
    """
    global _LOCATION_CACHE
    cached, cached_at = _LOCATION_CACHE
    if cached is not None and time.monotonic() - cached_at < _LOCATION_TTL_SECONDS:
        return cached

    result = visioncare_client.get_device_location()
    if not result:
        # Cache cả lần hỏng, ngắn hơn: không cache thì điện thoại tắt định vị
        # là MỌI lượt chat phải chờ hết timeout trước khi model nói được câu nào.
        _LOCATION_CACHE = ("", time.monotonic() - _LOCATION_TTL_SECONDS + _LOCATION_RETRY_SECONDS)
        return ""

    address = result.get("address")
    where = address or f"toạ độ {result['lat']}, {result['lng']}"
    # Nói thẳng là cấm hỏi lại: đo thật, chỉ đưa vị trí vào prompt thì model vẫn
    # hỏi ngược "bạn muốn xem thời tiết ở đâu?" — mà người dùng khiếm thị không
    # đọc được bản đồ để trả lời, và họ vừa hỏi xong chứ không muốn hỏi lại.
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
    _LOCATION_CACHE = (text, time.monotonic())
    return text


def _search_instruction(needs_web: bool, search_failed: bool) -> str:
    if search_failed:
        return _SEARCH_UNAVAILABLE_INSTRUCTION
    return _SEARCH_INSTRUCTION if needs_web else ""


def _build_prompt(
    command_text: str,
    needs_location: bool,
    needs_web: bool = False,
    search_failed: bool = False,
) -> str:
    parts = [
        _SYSTEM_PROMPT.format(
            now=_now_text(),
            search=_search_instruction(needs_web, search_failed),
            # Chỉ đi lấy vị trí khi câu hỏi thật sự cần: lấy vị trí là một vòng
            # gọi tới điện thoại, trả giá bằng giây chờ của người dùng cho câu
            # như "kể chuyện cười đi".
            location=_location_text() if needs_location else "",
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

    `needs_location`/`needs_web` do bộ phân loại intent trả về trong cùng một
    lần gọi model — không tốn thêm lượt gọi nào để biết câu này cần gì. Bật cả
    hai cho mọi câu thì "kể chuyện cười đi" cũng phải chờ lấy vị trí và tra
    Google; tắt cả hai thì "hôm nay trời thế nào" nhận về thời tiết bịa.
    """
    params = params or {}
    needs_location = bool(params.get("needs_location"))
    needs_web = bool(params.get("needs_web"))

    if not needs_web:
        return _remember(
            command_text,
            vlm.generate_stream(_build_prompt(command_text, needs_location), search=False),
        )
    return _remember(command_text, _stream_with_search_fallback(command_text, needs_location))


def _stream_with_search_fallback(command_text: str, needs_location: bool) -> Iterator[str]:
    """Tra Google; tra hỏng thì trả lời lại và nói rõ là chưa tra được.

    Grounding có hạn mức riêng với hạn mức gọi model thường — đã gặp thật: lượt
    chat bình thường chạy tốt trong khi lượt có search trả `429`. Không có nhánh
    dự phòng thì người dùng chỉ nghe "có lỗi xảy ra", không biết là hỏng mạng,
    hỏng máy hay câu hỏi sai.
    """
    grounded = vlm.generate_stream(
        _build_prompt(command_text, needs_location, needs_web=True), search=True
    )
    try:
        first = next(grounded)
    except StopIteration:
        return
    except vlm.VLMError as exc:
        logger.warning("Tra cứu hỏng, trả lời không có tra cứu: %s", exc)
        yield from vlm.generate_stream(
            _build_prompt(command_text, needs_location, search_failed=True), search=False
        )
        return

    yield first
    yield from grounded
