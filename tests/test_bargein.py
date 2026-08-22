"""G4 (ngắt lời/barge-in) + G2 (lock không giữ lúc gọi LLM) — T04.

`X-Turn-Id` mới (mô phỏng ở đây bằng gọi thẳng `action_flow.bump_generation()`,
đúng việc `pipeline/router.py::_resolve()` của lượt MỚI làm ở đầu hàm) phải
huỷ được CẢ luồng LLM (handler còn đang stream) LẪN luồng TTS (không còn mảnh
text nào được sinh ra cho `app.py` tổng hợp giọng) của lượt CŨ đang chạy dở
trên CÙNG một thiết bị.

Gọi thẳng `router._resolve()` (không qua `resolve_speech()`/`with_progress_notice`)
để kiểm soát chính xác từng lần `next()` — `with_progress_notice` kéo mảnh đầu
trên một luồng nền riêng (`handlers/waiting.py::wait_for`), làm mất đi khả
năng chèn `bump_generation()` đúng NGAY GIỮA hai lần `next()` mà các test này
cần.

SỬA LỖI review (docs/tasks/reports/T04.md mục sửa lỗi #1): bốn test gọi thẳng
`_resolve()` ở trên đều BỎ QUA đúng ranh giới thread mà bug thật nằm ở đó —
`with_progress_notice`/`wait_for` kéo mảnh ĐẦU trên một `threading.Thread`
TRẦN, không kế thừa `contextvars.Context`. `test_new_turn_cancels_via_real_resolve_speech_with_device_context`
đi qua `router.resolve_speech()` THẬT, với `app.DEVICE_ID_CTX` được set/reset
đúng như `app.py` làm — đây là ca test lẽ ra phải có ngay từ đầu để bắt được
bug đó.
"""
import threading
import time
from unittest.mock import patch

import pytest

import app as app_module
from handlers import action_flow
from pipeline import router
from schemas import Intent


@pytest.fixture(autouse=True)
def _clean_state():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


def test_new_turn_cancels_llm_stream():
    """Handler mô phỏng một stream Gemini thật (nhiều mảnh nhỏ, gọi mạng ở
    MỖI lần yield) — lượt mới cùng thiết bị tới GIỮA lúc đang kéo thì phải
    dừng NGAY, không kéo thêm mảnh (= không kéo thêm token) nào nữa."""
    pulled = []

    def streaming_chat(image, command_text, params=None):
        for i in range(10):
            pulled.append(i)
            yield f"mảnh {i} "

    with (
        patch("pipeline.stt.transcribe", return_value="kể chuyện đi"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", streaming_chat),
    ):
        stream = router._resolve(None, b"dummy")
        first = next(stream)
        second = next(stream)

        assert first == "mảnh 0 "
        assert second == "mảnh 1 "
        assert pulled == [0, 1]

        # Lượt MỚI cùng thiết bị tới — đúng việc `_resolve()` của nó làm ở
        # đầu hàm, mô phỏng lại ở đây thay vì dựng một request `/process` thật.
        action_flow.bump_generation()

        remaining = list(stream)

    assert remaining == [], "lượt cũ phải dừng NGAY, không phát thêm mảnh nào"
    assert len(pulled) == 2, "không được kéo thêm mảnh nào từ handler sau barge-in"


def test_new_turn_cancels_tts_stream():
    """Một câu trả lời NHIỀU CÂU (như `describe_space`) đang được phát dần —
    `app.py` chỉ tổng hợp giọng từ đúng những mảnh mà `_resolve()` yield ra,
    nên chặn được mảnh ở TẦNG NÀY tức là chặn được luôn phần TTS sẽ đọc."""
    pulled = []

    def long_description(image, command_text, params=None):
        sentences = [
            "Phía trước có một chiếc ghế.\n",
            "Bên trái có cầu thang đi xuống.\n",
            "Bên phải là một bức tường.\n",
            "Phía xa có cửa ra vào.\n",
        ]
        for s in sentences:
            pulled.append(s)
            yield s

    with (
        patch("pipeline.stt.transcribe", return_value="phía trước có gì"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.SPACE, {})),
        patch("handlers.describe_space.handle", long_description),
    ):
        stream = router._resolve(b"img", b"dummy")
        first = next(stream)
        assert first == "Phía trước có một chiếc ghế.\n"

        action_flow.bump_generation()

        remaining = list(stream)

    assert remaining == []
    # Ba câu SAU không được sinh ra -> không có gì để TTS đọc tiếp.
    assert pulled == ["Phía trước có một chiếc ghế.\n"]


def test_new_turn_during_host_api_call():
    """Mô phỏng ĐÚNG HÌNH DẠNG một action đang chờ VisionCare host
    (`handlers/action_flow.py::run_action()`): ack rồi tới các câu trấn an
    trong lúc chờ. Không gọi `run_action()` thật (`handlers/action_flow.py`
    không nằm trong "FILE BẠN ĐƯỢC SỬA" của T04, và mock hoá toàn bộ host chỉ
    để chứng minh cơ chế barge-in ở TẦNG ROUTER là việc thừa) — lượt cũ vẫn
    phải tự huỷ theo generation ngay giữa lúc "đang chờ host"."""
    pulled = []

    def waiting_on_host(image, command_text, params=None):
        pulled.append("ack")
        yield "Đang gọi cho mẹ.\n"
        for i in range(5):
            pulled.append(f"progress{i}")
            yield f"Vẫn đang chờ điện thoại phản hồi lần {i}.\n"
        pulled.append("final")
        yield "Đã gọi xong."

    with (
        patch("pipeline.stt.transcribe", return_value="gọi cho mẹ"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CONTACT_CALL, {})),
        patch("handlers.contact_call.handle", waiting_on_host),
    ):
        stream = router._resolve(None, b"dummy")
        ack = next(stream)
        assert "Đang gọi" in ack

        progress0 = next(stream)
        assert "lần 0" in progress0

        # Lượt mới cùng thiết bị tới NGAY GIỮA lúc lượt cũ còn đang "chờ host".
        action_flow.bump_generation()

        remaining = list(stream)

    assert remaining == []
    assert pulled == ["ack", "progress0"]
    assert "final" not in pulled


def test_lock_not_held_during_llm():
    """G2: lock (`handlers.action_flow._SESSIONS_LOCK`) chỉ bao đọc/ghi state
    trong bộ nhớ (micro giây) — KHÔNG BAO GIỜ giữ trong lúc gọi LLM/host, dù
    lượt đó tốn tới 0.5 giây. Đo THẬT bằng một luồng riêng cố lấy lock trong
    lúc router đang "ở giữa" một handler chậm — phải lấy được trong ≤ 5 ms."""
    action_flow.reset_state()

    def slow_chat_handle(image, command_text, params=None):
        time.sleep(0.5)
        yield "xong rồi"

    acquired_after: list[float] = []

    def probe() -> None:
        # Nhường một chút để chắc chắn đang chạy giữa lúc handler "gọi LLM".
        time.sleep(0.1)
        t0 = time.perf_counter()
        with action_flow._SESSIONS_LOCK:
            pass
        acquired_after.append(time.perf_counter() - t0)

    with (
        patch("pipeline.stt.transcribe", return_value="bây giờ là mấy giờ"),
        patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
        patch("handlers.chat.handle", slow_chat_handle),
    ):
        probe_thread = threading.Thread(target=probe)
        probe_thread.start()
        list(router.resolve_speech(None, b"dummy"))
        probe_thread.join(timeout=5)

    assert not probe_thread.is_alive(), "luồng đo bị treo — nghi ngờ lock bị giữ luôn"
    assert acquired_after, "luồng đo chưa từng chạy xong"
    measured_ms = acquired_after[0] * 1000
    assert measured_ms <= 5, f"lock bị giữ {measured_ms:.2f}ms > 5ms trong lúc handler đang chạy chậm"


def test_new_turn_cancels_via_real_resolve_speech_with_device_context():
    """SỬA LỖI review #1: đi qua `router.resolve_speech()` THẬT (không gọi
    thẳng `_resolve()`) với `app.DEVICE_ID_CTX` được set TRƯỚC khi kéo mảnh
    đầu và reset NGAY SAU đó — đúng vòng đời thật của một request `/process`
    (`app.py::process()` set context, gọi `resolve_speech()` đồng bộ, rồi
    `finally: DEVICE_ID_CTX.reset(...)` trước khi phần audio còn lại tiếp tục
    chảy trên luồng khác).

    Bug đã sửa: `with_progress_notice`/`wait_for` (`handlers/waiting.py`) kéo
    MẢNH ĐẦU của `_resolve()` trên một `threading.Thread` TRẦN, không kế thừa
    `contextvars.Context` — nếu `bump_generation()`/`current_generation()` tự
    đọc ambient context ở đó, generation của MỌI thiết bị đổ chung vào
    session `_NO_DEVICE_CONTEXT_KEY`, và cả câu trả lời bị cắt cụt sau mảnh
    đầu ngay khi có BẤT KỲ lượt nào khác (kể cả của thiết bị khác) bump
    generation lên do trùng session dùng chung. Test này xác nhận: (1) toàn
    bộ 10 mảnh của một thiết bị đọc được hết khi KHÔNG có lượt mới nào chen
    vào, và (2) generation của phiên `_NO_DEVICE_CONTEXT_KEY` không hề bị đụng
    tới — chứng minh lượt này thực sự chạy trên session của ĐÚNG thiết bị,
    không phải session dùng chung.
    """
    device_id = "device-xyz-that"
    pulled = []

    def streaming_chat(image, command_text, params=None):
        for i in range(10):
            pulled.append(i)
            yield f"mảnh {i} "

    token = app_module.DEVICE_ID_CTX.set(device_id)
    try:
        with (
            patch("pipeline.stt.transcribe", return_value="kể chuyện đi"),
            patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
            patch("handlers.chat.handle", streaming_chat),
        ):
            stream = router.resolve_speech(None, b"dummy")
            first = next(stream)
    finally:
        # Đúng vòng đời thật: context đã bị RESET trước khi phần còn lại của
        # luồng được kéo tiếp — nếu generation đọc ambient lúc này, nó đọc
        # ra `None`/session dùng chung, không phải "device-xyz-that".
        app_module.DEVICE_ID_CTX.reset(token)

    # Không cần patch lại STT/intent/handler ở đây: quyết định định tuyến đã
    # xong ở lần `next()` đầu tiên (trong scope `with` phía trên); phần còn
    # lại chỉ là kéo tiếp generator `streaming_chat` đã tồn tại sẵn.
    remaining = list(stream)

    assert first == "mảnh 0 "
    assert remaining == [f"mảnh {i} " for i in range(1, 10)], (
        "câu trả lời bị cắt cụt sau mảnh đầu — đúng triệu chứng của bug "
        "generation đổ chung session khi context bị reset giữa chừng"
    )
    assert pulled == list(range(10))

    # Generation của session DÙNG CHUNG (nơi bug cũ lỡ ghi nhầm vào) phải vẫn
    # còn nguyên — không lượt nào của "device-xyz-that" được phép chạm tới nó.
    assert action_flow.current_generation(action_flow._NO_DEVICE_CONTEXT_KEY) == 0
    # Generation của ĐÚNG thiết bị phải đã tăng (từ bump ở đầu `_resolve()`).
    assert action_flow.current_generation(device_id) >= 1


def test_new_turn_cancels_via_real_resolve_speech_only_same_device():
    """Phần còn lại của bug review #1: barge-in phải THEO THIẾT BỊ, không
    phải TOÀN SERVER. Lượt của thiết bị B bump generation không được huỷ lượt
    đang chạy dở của thiết bị A."""
    device_a = "device-a"
    device_b = "device-b"
    pulled = []

    def streaming_chat(image, command_text, params=None):
        for i in range(5):
            pulled.append(i)
            yield f"mảnh {i} "

    token = app_module.DEVICE_ID_CTX.set(device_a)
    try:
        with (
            patch("pipeline.stt.transcribe", return_value="kể chuyện đi"),
            patch("pipeline.intent.detect_with_params", return_value=(Intent.CHAT, {})),
            patch("handlers.chat.handle", streaming_chat),
        ):
            stream_a = router.resolve_speech(None, b"dummy")
            first_a = next(stream_a)
    finally:
        app_module.DEVICE_ID_CTX.reset(token)

    # Một lượt HOÀN TOÀN MỚI, của THIẾT BỊ KHÁC (B) — không liên quan gì tới
    # lượt đang chạy dở của A.
    action_flow.bump_generation(device_b)

    remaining_a = list(stream_a)

    assert first_a == "mảnh 0 "
    assert remaining_a == [f"mảnh {i} " for i in range(1, 5)], (
        "lượt của thiết bị A bị huỷ nhầm bởi generation của thiết bị B — "
        "barge-in đang là TOÀN SERVER thay vì THEO THIẾT BỊ"
    )
