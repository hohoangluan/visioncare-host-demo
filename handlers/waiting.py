"""Không để người dùng ngồi im chờ mà không biết máy đang làm gì.

Các handler dùng Gemini (đọc chữ, mô tả, tìm đồ vật, trò chuyện) chỉ phát ra
mảnh text đầu tiên khi model bắt đầu trả lời — vài giây im lặng. Người khiếm
thị không nhìn được màn hình nên quãng im đó không phân biệt được với máy hỏng.
"""

from collections.abc import Callable, Iterator, Sequence
import queue
import threading

import config


def notice_delays(opening_seconds: float = 0.0) -> Iterator[float]:
    """Số giây chờ trước câu trấn an kế tiếp, giãn dần.

    Dùng chung cho cả hai chỗ biết chờ: chỗ này (chờ Gemini) và
    `handlers/action_flow.py` (chờ điện thoại). Cùng một chính sách nhịp, vì
    người dùng nghe chung một cái loa và không quan tâm bên trong đang chờ ai.

    Giãn dần chứ không đều: câu trấn an không mang thông tin mới, nên nói dày
    chỉ thành tiếng ồn che mất câu báo tiến độ thật. Xem `config.py` để biết vì
    sao nhịp đều 4 giây cũ nghe thành một tràng liên tục.

    `opening_seconds` là độ dài câu vừa nói ngay trước quãng chờ này — câu chào
    "đã nhận yêu cầu" của `app.py`, hay câu xác nhận của mỗi action.

    Câu mở đầu đó CHÍNH LÀ câu trấn an thứ nhất, không phải một thứ đứng trước
    dãy trấn an. Nên khi có nó thì bỏ hẳn mốc đầu và đi thẳng vào nhịp thường:
    người dùng vừa nghe "hệ thống đang xử lý" xong mà mấy giây sau lại nghe "vẫn
    đang xử lý" thì đó là nói lại một câu, không phải báo tiến độ.

    Vẫn cộng `opening_seconds` vì mốc phải đếm từ lúc câu đó đọc XONG, chứ không
    phải từ lúc bắt đầu đọc.
    """
    interval = config.SPEECH_NOTICE_INTERVAL_SECONDS
    if opening_seconds:
        yield interval + opening_seconds
    else:
        yield config.SPEECH_FIRST_NOTICE_SECONDS

    interval = config.SPEECH_NOTICE_INTERVAL_SECONDS
    while True:
        yield interval
        interval = min(
            interval * config.SPEECH_NOTICE_BACKOFF,
            config.SPEECH_NOTICE_MAX_INTERVAL_SECONDS,
        )


# Không câu nào được lặp lại ý của câu chào ("Đã nhận yêu cầu của bạn, hệ thống
# đang xử lý." trong `app.py`). Câu "Vẫn đang xử lý, bạn chờ thêm chút nữa."
# từng đứng đầu danh sách này, và nghe thật thì hai câu liền nhau thành "hệ
# thống đang xử lý... vẫn đang xử lý" — nghe như máy nói lại một câu chứ không
# phải đang báo tiến độ. Mỗi câu ở đây phải nói một điều KHÁC câu chào.
_DEFAULT_NOTICES = (
    "Vẫn đang tìm thông tin cho bạn.",
    "Sắp có kết quả rồi.",
)

# Câu cố định của module này, để `pipeline/phrases.py` dựng sẵn audio. Trỏ vào
# đúng hằng số ở trên chứ không chép lại chữ: chép thì sửa một chỗ là chỗ kia
# trượt cache trong im lặng, mà triệu chứng đúng bằng thứ cache này sinh ra để
# chữa (người dùng chờ thêm vài giây).
STATIC_SPEECH: tuple[str, ...] = _DEFAULT_NOTICES

_SENTINEL = object()


def wait_for(
    produce: Callable[[], object],
    notices: Sequence[str] = _DEFAULT_NOTICES,
    opening_seconds: float = 0.0,
) -> Iterator[str]:
    """Chờ `produce()` xong, nói câu trấn an trong những quãng chờ dài.

    LUẬT ƯU TIÊN — âm thanh có giá trị luôn thắng câu trấn an:

    1. Kết quả từ model, mốc trạng thái thật của action, câu báo lỗi thật: có
       lúc nào phát lúc đó. Không có đồng hồ nào giữ chúng lại.
    2. Câu trấn an chỉ được nói khi tới mốc mà VẪN chưa có gì. Tới mốc mà nội
       dung thật đã sẵn sàng thì bỏ hẳn câu trấn an đó, không nói bù.
    3. Nhưng câu trấn an ĐÃ đẩy ra thì không rút lại được — audio phát tuần tự,
       nên mọi thứ sau nó phải xếp hàng chờ đọc xong. Đây là lý do phải cố hết
       sức để đừng nói hụt ở bước 2.

    `produce` chạy ở luồng nền để vừa chờ vừa nói được. Giá trị nó trả về chính
    là giá trị của generator này, lấy bằng `yield from`.

    Một chỗ duy nhất cho cả hai kiểu chờ — chờ Gemini và chờ điện thoại. Trước
    đây mỗi bên tự cài lấy, và hai bản lệch nhau: bên chờ điện thoại `sleep` cố
    định một nhịp poll nên kết quả đã sẵn sàng vẫn nằm chờ tới một giây mới được
    nói ra, đúng thứ luật ưu tiên này cấm.
    """
    channel: queue.Queue = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            channel.put(produce())
        except BaseException as exc:  # noqa: BLE001 - trả lỗi về luồng chính nguyên vẹn
            channel.put(exc)

    threading.Thread(target=run, daemon=True, name="waiting").start()

    delays = notice_delays(opening_seconds)
    index = 0
    while True:
        # Mốc trấn an, rồi một nhịp nhường cuối. `channel.get` trả về NGAY khi
        # có nội dung, nên không mốc nào giữ được kết quả đã sẵn sàng — nhịp
        # nhường chỉ cứu thêm trường hợp nội dung về sát mốc.
        ready = False
        for timeout in (next(delays), config.SPEECH_NOTICE_GRACE_SECONDS):
            try:
                value = channel.get(timeout=timeout)
                ready = True
                break
            except queue.Empty:
                continue

        if ready:
            if isinstance(value, BaseException):
                raise value
            return value

        if not notices:
            continue

        # Quay vòng thay vì dừng ở câu cuối: nghe cùng một câu nhiều lần liền
        # giống máy bị kẹt hơn là máy đang chạy.
        #
        # Xuống dòng ở cuối là dấu "câu trọn vẹn, đọc ngay" cho
        # `tts._sentences()` — không có nó thì câu trấn an nằm chờ tới khi có
        # mảnh sau, tức là chờ đúng thứ nó sinh ra để khỏi phải chờ.
        yield notices[index % len(notices)].rstrip() + "\n"
        index += 1


def with_progress_notice(
    stream: Iterator[str],
    notices: Sequence[str] = _DEFAULT_NOTICES,
    opening_seconds: float = 0.0,
) -> Iterator[str]:
    """Nói câu trấn an trong lúc chờ mảnh đầu của `stream`.

    Chỉ mảnh ĐẦU mới cần canh: từ mảnh thứ hai trở đi model đã bắt đầu viết và
    các mảnh tới liên tục.

    `opening_seconds`: độ dài câu người gọi vừa nói trước đó — xem
    `notice_delays()`.
    """
    first = yield from wait_for(
        lambda: next(iter(stream), _SENTINEL), notices, opening_seconds
    )
    if first is _SENTINEL:
        return

    yield first
    yield from stream
