"""Luồng chung cho 9 action điều khiển điện thoại qua VisionCare Host."""

from collections.abc import Iterator, Sequence
import logging
import threading
import time
import uuid

import config
from pipeline import tts
from handlers.result_speech import speak_result
from handlers.waiting import wait_for
from services.visioncare_client import (
    VisionCareAPIError,
    call_service_api,
    get_request_status,
)
from services.action_callbacks import action_callbacks

logger = logging.getLogger("blind_assist")

# Câu trấn an mặc định, phát xoay vòng. Lặp đúng một câu bốn lần liền nghe như
# máy bị kẹt, nên danh sách quay vòng để mỗi lần chờ nghe khác nhau. Nhịp đẩy
# câu do `waiting.notice_delays()` quyết định — xem `config.py` để biết vì sao
# nó giãn dần thay vì đều đặn.
#
# Không câu nào được lặp lại ý câu chào ("hệ thống đang xử lý") — người dùng vừa
# nghe nó vài giây trước, nghe lại thì tưởng máy phát lại chứ không phải đang
# chạy tiếp. Mỗi câu ở đây nói một điều CỤ THỂ hơn câu chào: đang chờ ai, chờ
# tới đâu rồi.
_DEFAULT_PROGRESS = (
    "Vẫn đang chờ điện thoại phản hồi.",
    "Sắp xong rồi, bạn chờ thêm chút nữa.",
    "Điện thoại chưa báo về, nhưng chưa có gì bất thường.",
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio.
STATIC_SPEECH: tuple[str, ...] = _DEFAULT_PROGRESS

# Dấu báo "câu này đã trọn vẹn, đọc ngay đi" cho `tts._sentences()`.
#
# Cần vì luồng text ở đây khác hẳn luồng của Gemini. Gemini đẩy ra từng mảnh
# vụn cách nhau vài chục mili giây, nên gom chờ mảnh sau là đúng. Còn ở đây mỗi
# lần `yield` là một câu trọn vẹn, và mảnh kế tiếp có thể cả chục giây nữa mới
# tới. Không có dấu này thì "Đang gọi xe." nằm im trong buffer tới lúc câu trấn
# an đầu tiên xuất hiện, rồi hai câu bung ra một lượt — nghe thành im lặng một
# lúc rồi nói dồn, đúng triệu chứng đo được lúc chạy thật.
_UTTERANCE_END = "\n"


def _utterance(text: str) -> str:
    return text.rstrip() + _UTTERANCE_END

# Id do điện thoại sinh ra ở lần gọi trước, cần cho lệnh tiếp theo:
# `navigation_stop` phải mang đúng `navigation_id` của `navigation_start`, và
# `ride_confirm` phải mang đúng `quote_id` của `ride_quote`. Hardcode như trước
# ("nav-123"/"quote-123") thì host luôn trả NOT_FOUND.
#
# Dict trong bộ nhớ tiến trình là đủ cho demo một kính một máy; nhiều kính thì
# phải khoá theo `device_id`.
_LAST_IDS: dict[str, str] = {}

# Kết quả nào của action nào cần nhớ lại cho lệnh sau.
_REMEMBER_KEYS = {
    "navigation_start": "navigation_id",
    "ride_quote": "quote_id",
}

# Việc gì đang CHẠY trên điện thoại -> lúc nó bắt đầu (`time.monotonic()`).
#
# Khác `_LAST_IDS` ở mục đích: `_LAST_IDS` giữ id để gửi kèm lệnh sau, còn cái
# này trả lời câu hỏi "lúc này cái gì đang chạy" để gỡ mơ hồ cho bộ phân loại ý
# định. "Tắt đi", "dừng lại", "thôi đủ rồi" không tự nó cho biết tắt cái gì —
# đây là cặp nhãn lẫn nhau nhiều nhất khi đo trên bộ câu huấn luyện, và không
# chữa được bằng thêm dữ liệu vì chính người nghe cũng không phân biệt nổi nếu
# không biết cái gì đang chạy.
#
# Giữ mốc thời gian chứ không phải cờ bật/tắt: khi cả nhạc lẫn chỉ đường cùng
# chạy thì phải chọn được cái vừa bật gần đây nhất, thay vì chọn bừa một cái.
#
# BIẾT TRƯỚC MỘT CHỖ HỞ: host không báo về khi bài hát tự hết, nên `music_playing`
# vẫn bật sau khi nhạc đã tắt tự nhiên. Hậu quả nhẹ và không đối xứng nên chấp
# nhận được: "tắt đi" lúc đó ra `music_stop`, handler gửi lệnh dừng một thứ đã
# dừng và host trả lời bình thường. Ngược lại — đoán thành `nav_stop` khi người
# dùng đang muốn tắt nhạc — mới là cái phải tránh. Sửa được khi host đẩy sự kiện
# "hết bài" về; đừng thay bằng TTL đoán mò, vì không có con số nào đúng cho mọi
# bài hát.
_ACTIVE: dict[str, float] = {}

# Action nào bật/tắt việc gì. Chỉ tính khi điện thoại báo `succeeded` — lệnh gửi
# đi mà máy báo hỏng thì nhạc không hề chạy, đánh dấu là chạy sẽ khiến "tắt đi"
# ngay sau đó bị hiểu thành tắt một thứ chưa từng bật.
_STARTS = {"music_play": "music_playing", "navigation_start": "navigating"}
_ENDS = {"music_stop": "music_playing", "navigation_stop": "navigating"}


def remember(key: str, value: str) -> None:
    """Ghi lại một giá trị cho lượt nói tiếp theo (điểm đến đang chờ xác nhận)."""
    _LAST_IDS[key] = value


def recall(key: str) -> str | None:
    """Id gần nhất đã nhận được cho `key` (`navigation_id`, `quote_id`)."""
    return _LAST_IDS.get(key)


def forget(key: str) -> None:
    """Xoá id sau khi nó đã được dùng xong (chuyến đã hủy, lộ trình đã dừng)."""
    _LAST_IDS.pop(key, None)


def device_state() -> dict:
    """Cái gì đang chạy trên điện thoại lúc này.

    Dùng cho bước phân loại ý định, không phải để hiển thị. `most_recent` là
    việc vừa bật gần đây nhất trong số đang chạy — chỗ dựa duy nhất khi cả nhạc
    lẫn chỉ đường cùng chạy và người dùng chỉ nói "tắt đi".
    """
    running = sorted(_ACTIVE.items(), key=lambda kv: kv[1])
    return {
        "music_playing": "music_playing" in _ACTIVE,
        "navigating": "navigating" in _ACTIVE,
        "ride_quote_pending": "quote_id" in _LAST_IDS,
        "most_recent": running[-1][0] if running else None,
    }


def reset_state() -> None:
    """Xoá sạch id lẫn trạng thái đang chạy. Dùng trong test và khi khởi động."""
    _LAST_IDS.clear()
    _ACTIVE.clear()


def mark_active(task: str) -> None:
    """Đánh dấu tác vụ `task` ('music_playing' hoặc 'navigating') đang hoạt động duy nhất."""
    _ACTIVE.clear()
    _ACTIVE[task] = time.monotonic()


def mark_inactive(task: str | None = None) -> None:
    """Xóa tác vụ đang hoạt động."""
    if task:
        _ACTIVE.pop(task, None)
    else:
        _ACTIVE.clear()


def note_result(operation: str, data: dict | None) -> None:
    """Cập nhật id và trạng thái đang chạy từ kết quả thật của một action."""
    if not data or data.get("request_state") != "succeeded":
        return

    key = _REMEMBER_KEYS.get(operation)
    if key:
        value = (data.get("result") or {}).get(key)
        if value:
            _LAST_IDS[key] = value
            logger.info("Nhớ %s=%s từ %s", key, value, operation)

    started = _STARTS.get(operation)
    if started:
        mark_active(started)
        logger.info("Bắt đầu: %s", started)
    ended = _ENDS.get(operation)
    if ended and _ACTIVE.pop(ended, None) is not None:
        logger.info("Kết thúc: %s", ended)


def _await_result(
    request_id: str,
    timeout_seconds: float,
    progress: Sequence[str],
    opening_seconds: float = 0.0,
) -> Iterator[str]:
    """Poll kết quả, xen câu trấn an vào những quãng chờ dài.

    Là generator để vừa nói vừa chờ: `yield` ra câu cần đọc, và `return` kết quả
    cuối (`None` nếu hết giờ) cho người gọi lấy bằng `yield from`.

    `opening_seconds` là độ dài câu xác nhận vừa đọc trước đó — nó cũng là một
    câu trấn an, nên mốc kế tiếp đếm từ lúc nó đọc xong.
    """
    deadline = time.monotonic() + timeout_seconds

    def poll() -> dict | None:
        """Hỏi host tới khi xong hoặc hết giờ. Chạy ở luồng nền của `wait_for`.

        Đặt vòng `sleep` ở đây, không ở luồng chính, chính là điểm mấu chốt:
        trước kia luồng chính ngủ một nhịp poll sau mỗi lần hỏi, nên kết quả vừa
        về vẫn phải nằm chờ tới một giây mới được nói ra. Giờ luồng chính chỉ
        chờ trên hàng đợi và bật dậy ngay khi có kết quả.
        """
        while time.monotonic() < deadline:
            try:
                data = get_request_status(request_id)
            except VisionCareAPIError:
                # Một lần tra hỏng (mạng chớp) không có nghĩa là action hỏng.
                data = {}

            state = data.get("request_state")
            if state and state != "processing":
                logger.info("Request %s finished: %s", request_id, state)
                return data

            time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)

        logger.warning("Request %s vẫn processing sau %.0fs", request_id, timeout_seconds)
        return None

    return (yield from wait_for(poll, progress, opening_seconds))


def run_action(
    operation: str,
    endpoint: str,
    payload: dict,
    ack: str,
    failure: str,
    result_timeout: float | None = None,
    progress: Sequence[str] = _DEFAULT_PROGRESS,
) -> Iterator[str]:
    """Gửi lệnh, đọc câu xác nhận ngay, rồi đọc kết quả thật từ điện thoại.

    Trả nhiều mảnh text chứ không phải một: mảnh đầu phát ngay để người dùng
    biết lệnh đã đi, các mảnh giữa lấp những quãng chờ dài, mảnh cuối là kết quả
    thật. Dừng ở `202` như trước thì "đang gọi cho Em iu" và "chưa gọi được"
    nghe giống hệt nhau — người khiếm thị không có cách nào biết máy có làm gì
    không, và một quãng im lặng 30 giây thì không phân biệt được với hỏng hệ
    thống.
    """
    started = time.monotonic()
    generated_request_id = str(uuid.uuid4())
    request_payload = {**payload, "request_id": generated_request_id}
    action_callbacks.register(
        generated_request_id,
        operation,
        lambda data: note_result(operation, data),
        registered_at=started,
    )
    try:
        resp = call_service_api(endpoint, request_payload)
        request_id = resp.get("data", {}).get("request_id", "")
        action_callbacks.move(generated_request_id, request_id)
        logger.info("%s requested, request_id=%s", operation, request_id)
    except VisionCareAPIError as exc:
        logger.error("%s error: %s", operation, exc)
        yield failure
        return
    except Exception:
        logger.exception("%s unexpected error", operation)
        yield failure
        return

    yield _utterance(ack)
    if not request_id:
        return

    # Một GET tức thời là recovery probe cho backend cũ/test; critical path sau
    # đó chỉ ngủ trên Event và được callback đánh thức ngay, không poll 0,5 giây.
    try:
        probe = get_request_status(request_id)
        if probe.get("request_state") not in {None, "processing"}:
            action_callbacks.resolve(request_id, probe)
    except VisionCareAPIError:
        pass

    remaining = config.VISIONCARE_FAST_ACTION_SECONDS - (time.monotonic() - started)
    final = action_callbacks.wait(request_id, remaining)
    if final is not None:
        yield speak_result(operation, final)
        return

    # Không hủy action ở mốc SLO. Polling chỉ còn là recovery nền nếu callback
    # bị mất/restart; callback muộn vẫn cập nhật navigation_id/quote_id/state.
    budget = result_timeout if result_timeout is not None else config.VISIONCARE_RESULT_TIMEOUT_SECONDS

    def reconcile_late() -> None:
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            try:
                data = get_request_status(request_id)
            except VisionCareAPIError:
                data = {}
            if data.get("request_state") not in {None, "processing"}:
                action_callbacks.resolve(request_id, data)
                return
            time.sleep(config.VISIONCARE_RESULT_POLL_SECONDS)

    threading.Thread(
        target=reconcile_late,
        name=f"action-reconcile-{request_id[:8]}",
        daemon=True,
    ).start()
    yield _utterance("Điện thoại vẫn đang thực hiện, tôi sẽ cập nhật khi có kết quả.")
