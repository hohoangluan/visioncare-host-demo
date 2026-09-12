"""T24/W5 — chấm khung canh vật cản và trả mức về ngay trong response.

🔴 File này khoá lại đúng cái lỗ đã để T24 "xanh mọi test" mà chết ngoài thực
tế: `risk_engine.evaluate()`, `frames.latest_hazard()` và `events.hazard_level()`
**không có một lời gọi nào** trong mã production. Board chụp, server cất khung
vào bộ đệm, rồi thôi.

Nên test ở đây đo **đường dây nối vào nhau**, không đo lại luật chấm điểm
(`tests/test_hazard_watch.py` đã lo phần đó).
"""

from __future__ import annotations

import config
import pytest
from fastapi.testclient import TestClient

from app import app
from services.hazard_worker import HazardWorker


class _FakeEngine:
    """Máy chấm giả. `script` là danh sách `(mức, đổi)` hoặc một Exception."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.seen: list[tuple[str, bytes]] = []

    def evaluate(self, device_id: str, jpeg: bytes, now=None):
        self.seen.append((device_id, jpeg))
        item = self.script.pop(0) if self.script else ("SAFE", False)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def rig():
    published: list[tuple[str, str, bool]] = []
    stopped: list[str] = []

    def make(script: list) -> HazardWorker:
        return HazardWorker(
            engine=_FakeEngine(script),
            publish=lambda d, l, c: published.append((d, l, c)) or 1,
            stop_watch=stopped.append,
        )

    return make, published, stopped


# ── đường dây chính ───────────────────────────────────────────────────────
def test_a_frame_from_a_watching_device_actually_gets_scored(rig):
    """🔴 Ca chết của T24: khung tới rồi nằm im."""
    make, published, _ = rig
    worker = make([("HIGH", True)])
    worker.watch("glasses-01")

    assert worker.score_frame("glasses-01", b"\xff\xd8jpeg") == ("HIGH", True)
    assert worker.scored == 1


def test_level_is_published_over_sse_only_when_it_changes(rig):
    """W3: hàng đợi SSE mỗi thiết bị có 8 chỗ. Gửi mỗi khung sẽ đẩy văng
    `call_incoming`."""
    make, published, _ = rig
    worker = make([("LOW", True), ("LOW", False), ("LOW", False)])
    worker.watch("glasses-01")

    for _ in range(3):
        worker.score_frame("glasses-01", b"jpeg")

    assert published == [("glasses-01", "LOW", True)]


def test_a_device_that_never_asked_to_watch_is_not_scored(rig):
    make, published, _ = rig
    worker = make([("HIGH", True)])
    assert worker.score_frame("glasses-01", b"jpeg") is None
    assert published == []


def test_unwatch_stops_scoring(rig):
    make, published, _ = rig
    worker = make([("HIGH", True)])
    worker.watch("glasses-01")
    worker.unwatch("glasses-01")

    assert worker.score_frame("glasses-01", b"jpeg") is None
    assert published == []


def test_each_device_is_scored_independently(rig):
    make, published, _ = rig
    worker = make([("HIGH", True), ("SAFE", False)])
    worker.watch("glasses-01")
    worker.watch("glasses-02")

    assert worker.score_frame("glasses-01", b"a") == ("HIGH", True)
    assert worker.score_frame("glasses-02", b"b") == ("SAFE", False)
    assert published == [("glasses-01", "HIGH", True)]


# ── fail-closed lần hai ───────────────────────────────────────────────────
def test_one_bad_frame_does_not_break_the_next_one(rig):
    """Một khung méo làm ONNX ném lỗi không được kéo theo khung sau."""
    make, _, _ = rig
    worker = make([RuntimeError("onnx nổ"), ("HIGH", True)])
    worker.watch("glasses-01")

    assert worker.score_frame("glasses-01", b"jpeg") is None   # hỏng
    assert worker.errors == 1
    assert worker.score_frame("glasses-01", b"jpeg") == ("HIGH", True)


def test_repeated_failures_turn_the_mode_off_instead_of_going_quiet(rig):
    """🔴 Fail-closed. Chấm hỏng mãi mà vẫn báo "đang canh" là ca nguy hiểm
    nhất của cả tính năng: người dùng tin máy đang canh nên đi nhanh hơn."""
    make, _, stopped = rig
    worker = make([RuntimeError("hỏng")] * config.HAZARD_WATCH_MAX_FAILURES)
    worker.watch("glasses-01")

    for _ in range(config.HAZARD_WATCH_MAX_FAILURES):
        worker.score_frame("glasses-01", b"jpeg")

    assert stopped == ["glasses-01"], "hỏng liên tiếp mà không tắt chế độ"
    assert worker.watching() == frozenset()


def test_a_good_frame_resets_the_failure_count(rig):
    """Hỏng lác đác (một khung méo mỗi lúc) KHÔNG được cộng dồn tới mức tắt."""
    make, _, stopped = rig
    script: list = []
    for _ in range(config.HAZARD_WATCH_MAX_FAILURES * 2):
        script += [RuntimeError("hỏng"), ("SAFE", False)]
    worker = make(script)
    worker.watch("glasses-01")

    for _ in range(len(script)):
        worker.score_frame("glasses-01", b"jpeg")

    assert stopped == [], "hỏng xen kẽ mà vẫn bị tắt"
    assert worker.watching() == frozenset({"glasses-01"})


# ── hợp đồng HTTP: mức về trong THÂN response ─────────────────────────────
def _watching(device_id: str):
    """Ngữ cảnh: đăng ký `device_id` với worker THẬT rồi gỡ ra."""
    from services.hazard_risk import risk_engine
    from services.hazard_worker import worker

    class _Ctx:
        def __enter__(self):
            self.detector = risk_engine._detector
            worker.watch(device_id)
            return worker

        def __exit__(self, *exc):
            risk_engine.set_detector(self.detector)
            worker.unwatch(device_id)

    return _Ctx()


def test_frame_response_carries_the_level_so_the_board_needs_no_sse():
    """🔴 Đây là thứ cho phép board giữ MỘT phiên TLS keep-alive.

    Trước đổi này mức phải về bằng SSE, nên board buộc phải `Connection: close`
    trên đường đẩy khung (hai phiên TLS cùng lúc cần ~90 KB LIỀN, khối liền lớn
    nhất còn 77 812 B) — tức trả 616–911 ms bắt tay cho MỖI khung.
    """
    from services.hazard_risk import risk_engine

    with _watching("glasses-01"):
        risk_engine.set_detector(None)          # sẽ ném HazardWatchUnavailable
        response = TestClient(app).post(
            "/frame",
            content=b"\xff\xd8jpeg",
            headers={"X-Device-Id": "glasses-01", "X-Stream-Kind": "hazard"},
        )
        # Không có model -> không có mức. 204 = "đã nhận, không có mức cho anh";
        # board giữ nguyên mức cuối thay vì tự cho là an toàn.
        assert response.status_code == 204

    class _Always:
        def detect(self, jpeg):
            return []

    with _watching("glasses-01"):
        risk_engine.set_detector(_Always())
        risk_engine.reset("glasses-01")
        response = TestClient(app).post(
            "/frame",
            content=b"\xff\xd8jpeg",
            headers={"X-Device-Id": "glasses-01", "X-Stream-Kind": "hazard"},
        )
        assert response.status_code == 200
        assert response.json()["level"] in {"SAFE", "LOW", "MEDIUM", "HIGH"}
        assert "changed" in response.json()


def test_frame_from_an_unwatched_device_gets_a_stop_order():
    """Restart server giữa lúc đang canh = mất cờ, board không biết gì.

    Không có nhánh này thì board chụp mãi và kêu tít mãi ở mức cuối — cảnh báo
    về một cái cột đã đi qua từ trước lúc restart, và pin vẫn cạn.
    """
    import app as app_module
    from services.events_channel import events
    from services.hazard_worker import worker

    worker.unwatch("glasses-99")
    app_module._ORPHAN_HAZARD_STOPS.pop("glasses-99", None)

    sent: list[tuple[str, str]] = []
    original = events.hazard_watch
    events.hazard_watch = lambda d, a: sent.append((d, a)) or 1  # type: ignore[assignment]
    try:
        for _ in range(3):        # nhiều khung liên tiếp
            response = TestClient(app).post(
                "/frame",
                content=b"jpeg",
                headers={"X-Device-Id": "glasses-99", "X-Stream-Kind": "hazard"},
            )
            assert response.status_code == 204
    finally:
        events.hazard_watch = original  # type: ignore[assignment]
        app_module._ORPHAN_HAZARD_STOPS.pop("glasses-99", None)

    # Đúng MỘT lệnh dừng, không phải một lệnh mỗi khung: hàng đợi SSE có 8 chỗ.
    assert sent == [("glasses-99", "stop")]


# ── nối vào handler thật ──────────────────────────────────────────────────
def test_handler_registers_and_unregisters_the_device():
    """`start()`/`stop()` của handler phải thật sự bật/tắt việc chấm.

    Không mock worker: chính chỗ nối này là thứ đã thiếu.
    """
    from handlers import action_flow, hazard_watch
    from services.hazard_risk import risk_engine
    from services.hazard_worker import worker

    action_flow.reset_state()
    worker.unwatch("glasses-01")
    detector = risk_engine._detector
    risk_engine.set_detector(object())   # giả "có model" để qua cửa fail-closed
    try:
        list(hazard_watch.start("glasses-01"))
        assert "glasses-01" in worker.watching(), "bật chế độ mà worker không biết"

        list(hazard_watch.stop("glasses-01"))
        assert "glasses-01" not in worker.watching()
    finally:
        risk_engine.set_detector(detector)
        action_flow.reset_state()


def test_handler_refuses_and_does_not_register_without_a_model():
    """Fail-closed cũ vẫn phải đứng: không model thì không có gì được bật."""
    from handlers import action_flow, hazard_watch
    from services.hazard_risk import risk_engine
    from services.hazard_worker import worker

    action_flow.reset_state()
    worker.unwatch("glasses-01")
    detector = risk_engine._detector
    risk_engine.set_detector(None)
    try:
        said = list(hazard_watch.start("glasses-01"))
        assert "Chưa bật được" in said[0]
        # Hỏi về ĐÚNG thiết bị này, không hỏi sổ có rỗng không: test file khác
        # chạy trước có thể để lại thiết bị của chúng trong sổ.
        assert "glasses-01" not in worker.watching()
    finally:
        risk_engine.set_detector(detector)
        action_flow.reset_state()


def test_hazard_is_in_both_image_gates_or_neither():
    """🔴 HAI danh sách, và chúng đã lệch nhau một lần trên board thật.

    `router._IMAGE_REQUIRED_INTENTS` quyết định có ĐI LẤY ảnh không;
    `image_quality._READS_IMAGE` quyết định có TỪ CHỐI khi thiếu ảnh không.
    Sửa một cái mà quên cái kia thì lượt thật trả về "Không nhận được ảnh từ
    kính" thay vì chạy — đo được 2026-08-25:

        intent=hazard nhưng không có ảnh -> từ chối ảnh

    Test này khoá CẢ HAI trong một chỗ, để lần sau không sửa được một nửa.
    Nó cố ý KHÔNG khoá chiều nào đúng — quyết định đó đã đảo hai lần
    (2026-08-25 gỡ ra, 2026-08-26 thêm lại) và có thể đảo nữa. Thứ không được
    phép đổi là hai danh sách phải khớp nhau.
    """
    from pipeline import image_quality
    from pipeline.router import _IMAGE_REQUIRED_INTENTS
    from schemas import Intent

    assert (Intent.HAZARD in _IMAGE_REQUIRED_INTENTS) == (
        Intent.HAZARD in image_quality._READS_IMAGE
    ), (
        "hai cổng ảnh lệch nhau về `hazard` — lượt thật sẽ trả 'Không nhận "
        "được ảnh từ kính' thay vì chạy"
    )


def test_hazard_currently_reads_the_image():
    """Chiều HIỆN TẠI của quyết định trên, tách riêng khỏi bất biến hai-danh-sách.

    Tách ra vì hai thứ này hỏng vì hai lý do khác nhau: test trên đỏ khi ai đó
    sửa nửa vời, test này đỏ khi ai đó đảo quyết định. Gộp lại thì một lần đỏ
    không nói được là cái nào.
    """
    from pipeline import image_quality
    from pipeline.router import _IMAGE_REQUIRED_INTENTS
    from schemas import Intent

    assert Intent.HAZARD in _IMAGE_REQUIRED_INTENTS
    assert image_quality.reject_reason(Intent.HAZARD, None) == image_quality._NO_IMAGE
