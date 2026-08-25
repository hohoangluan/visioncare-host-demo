"""T24 — cảnh báo vật cản thời gian thực: vòng đời, khung hình, mức, sự kiện.

Bốn nhóm theo đúng mục 5 của `docs/tasks/T24-hazard-watch.md`. Nhóm nào khoá
lại một cách hỏng cụ thể thì docstring của ca nói rõ cách hỏng đó.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app import app
import config
from handlers import action_flow, hazard_watch
from services import hazard_risk
from services.events_channel import events
from services.frame_buffer import frames
from services.hazard_risk import Box, RiskEngine, risk_engine


class FakeDetector:
    """Detector giả — máy này chưa có file YOLO11n nào.

    Có nó thì phần dễ sai nhất (luật chấm điểm + hysteresis) test được mọi
    lần, thay vì nằm chờ tới ngày ai đó tải model về. Xem ghi chú thiết kế
    số 1 ở đầu `services/hazard_risk.py`.
    """

    def __init__(self, boxes: list[Box] | None = None) -> None:
        self.boxes = boxes or []

    def detect(self, jpeg: bytes) -> list[Box]:
        return list(self.boxes)


def _box(**kwargs) -> Box:
    defaults = dict(label="person", confidence=0.9, x1=0.4, y1=0.3, x2=0.6, y2=0.9)
    defaults.update(kwargs)
    return Box(**defaults)


@pytest.fixture(autouse=True)
def _clean():
    action_flow.reset_state()
    events.clear()
    frames.clear()
    risk_engine.reset()
    risk_engine.set_detector(None)
    yield
    action_flow.reset_state()
    events.clear()
    frames.clear()
    risk_engine.reset()
    risk_engine.set_detector(None)


# ─── 5.1 vòng đời ──────────────────────────────────────────────────────────


def test_hazard_watch_start_sets_state() -> None:
    risk_engine.set_detector(FakeDetector())
    spoken = list(hazard_watch.start("glasses-01"))
    assert spoken
    assert action_flow.device_state("glasses-01")["hazard_watching"] is True


def test_hazard_watch_coexists_with_music_and_navigation() -> None:
    """B7 — ba cờ độc lập.

    Vừa nghe nhạc vừa được chỉ đường vừa bật canh vật cản chính là mô tả của
    một người đang đi bộ ngoài đường. Bật cái này mà tắt cái kia là lặp lại
    đúng lỗi "Single Active State" mà T03/B7 đã gỡ.
    """
    risk_engine.set_detector(FakeDetector())
    action_flow.mark_active("music_playing", "glasses-01")
    action_flow.mark_active("navigating", "glasses-01")
    list(hazard_watch.start("glasses-01"))

    state = action_flow.device_state("glasses-01")
    assert state["music_playing"] is True
    assert state["navigating"] is True
    assert state["hazard_watching"] is True


def test_hazard_watch_stop_clears_state_and_frame() -> None:
    risk_engine.set_detector(FakeDetector())
    list(hazard_watch.start("glasses-01"))
    frames.put_hazard("glasses-01", b"\xff\xd8jpeg")

    list(hazard_watch.stop("glasses-01"))
    assert action_flow.device_state("glasses-01")["hazard_watching"] is False
    # Khung cũ phải bị bỏ: bật lại sau đó mà còn khung cũ thì mức đầu tiên
    # người dùng nghe là mức của căn phòng lúc trước.
    assert frames.latest_hazard("glasses-01", max_age_ms=60_000) is None


def test_stop_answers_even_when_never_started() -> None:
    """"Tắt cảnh báo" khi nó chưa bật là ca thường gặp nhất — không được im."""
    spoken = "".join(hazard_watch.stop("glasses-01"))
    assert spoken.strip()


def test_start_is_refused_without_a_detector() -> None:
    """🔴 Fail-closed: không có model thì KHÔNG bật, và nói thẳng ra.

    Bật cờ mà không ai chấm điểm nghĩa là board đốt pin chụp liên tục để đổi
    lấy im lặng, còn người dùng thì tin mình đang được canh và đi nhanh hơn.
    """
    spoken = "".join(hazard_watch.start("glasses-01"))
    assert "chưa bật được" in spoken.lower()
    assert action_flow.device_state("glasses-01")["hazard_watching"] is False
    assert events.queued_count("glasses-01") == 0


def test_start_twice_does_not_resend_command() -> None:
    risk_engine.set_detector(FakeDetector())
    stream = events.subscribe("glasses-01")
    try:
        list(hazard_watch.start("glasses-01"))
        list(hazard_watch.start("glasses-01"))
        assert json.loads(next(stream)[6:-2])["action"] == "start"
        assert events.queued_count("glasses-01") == 0
    finally:
        stream.close()


# ─── 5.2 uplink khung hình ─────────────────────────────────────────────────


def test_hazard_frame_uses_separate_slot_from_turn_frame() -> None:
    """W2 — hai ô tách hẳn nhau, không cái nào đẩy văng cái kia."""
    frames.put("glasses-01", "turn-1", b"turn-frame")
    frames.put_hazard("glasses-01", b"hazard-frame")

    assert frames.latest("glasses-01", 60_000, turn_id="turn-1") == b"turn-frame"
    assert frames.latest_hazard("glasses-01", 60_000) == b"hazard-frame"


def test_hazard_frames_never_evict_the_turn_ring() -> None:
    """Luồng canh chạy vài khung MỖI GIÂY — ring 3 chỗ của lượt sẽ bay sạch."""
    frames.put("glasses-01", "turn-1", b"turn-frame")
    for index in range(50):
        frames.put_hazard("glasses-01", f"hazard-{index}".encode())
    assert frames.latest("glasses-01", 60_000, turn_id="turn-1") == b"turn-frame"


def test_hazard_slot_keeps_only_the_newest() -> None:
    """Chiến lược latest-frame: xử một khung cũ 2 giây là báo một vật cản
    người dùng đã đi qua."""
    frames.put_hazard("glasses-01", b"old")
    frames.put_hazard("glasses-01", b"new")
    assert frames.latest_hazard("glasses-01", 60_000) == b"new"


def test_hazard_frame_does_not_require_turn_id() -> None:
    response = TestClient(app).post(
        "/frame",
        content=b"\xff\xd8jpeg",
        headers={"X-Device-Id": "glasses-01", "X-Stream-Kind": "hazard"},
    )
    assert response.status_code == 204
    assert frames.latest_hazard("glasses-01", 60_000) == b"\xff\xd8jpeg"


def test_turn_frame_contract_unchanged() -> None:
    """Không có `X-Stream-Kind` thì hành vi cũ nguyên vẹn, kể cả lỗi thiếu id."""
    client = TestClient(app)
    assert (
        client.post(
            "/frame", content=b"jpeg", headers={"X-Device-Id": "glasses-01"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/frame",
            content=b"jpeg",
            headers={"X-Device-Id": "glasses-01", "X-Turn-Id": "turn-1"},
        ).status_code
        == 204
    )


def test_unknown_stream_kind_is_rejected() -> None:
    response = TestClient(app).post(
        "/frame",
        content=b"jpeg",
        # ASCII: header HTTP không mang được ký tự ngoài latin-1, và httpx
        # từ chối ngay ở phía client trước khi request rời máy.
        headers={"X-Device-Id": "glasses-01", "X-Stream-Kind": "something-else"},
    )
    assert response.status_code == 400


# ─── 5.3 risk engine ───────────────────────────────────────────────────────


def test_corridor_filters_objects_beside_the_path() -> None:
    """Vật ở rìa khung thì người dùng đi qua bên cạnh nó, không đâm vào.

    Không lọc thì mọi cái cây ven đường đều kêu, và người dùng tắt chế độ này
    trong ngày đầu tiên.
    """
    engine = RiskEngine(FakeDetector())
    on_path = engine.score_boxes("glasses-01", [_box(x1=0.45, x2=0.55)])
    engine.reset()
    beside = engine.score_boxes("glasses-01", [_box(x1=0.0, x2=0.10)])
    assert on_path > beside


def test_bigger_and_lower_box_scores_higher() -> None:
    """Camera đơn không đo khoảng cách — box to + mép dưới thấp = gần."""
    engine = RiskEngine(FakeDetector())
    near = engine.score_boxes("a", [_box(x1=0.25, y1=0.2, x2=0.75, y2=0.98)])
    far = engine.score_boxes("b", [_box(x1=0.47, y1=0.45, x2=0.53, y2=0.55)])
    assert near > far


def test_low_confidence_boxes_are_ignored() -> None:
    engine = RiskEngine(FakeDetector())
    score = engine.score_boxes(
        "glasses-01", [_box(confidence=config.HAZARD_MIN_CONFIDENCE - 0.01)]
    )
    assert score == 0.0


def test_max_not_mean_across_boxes() -> None:
    """Một vật chắn đường giữa mười vật vô hại VẪN là một vật chắn đường."""
    engine = RiskEngine(FakeDetector())
    blocking = _box(x1=0.25, y1=0.2, x2=0.75, y2=0.98)
    harmless = [_box(x1=0.01, y1=0.01, x2=0.03, y2=0.03) for _ in range(10)]

    alone = engine.score_boxes("a", [blocking])
    engine.reset()
    crowded = engine.score_boxes("b", harmless + [blocking])
    assert crowded == pytest.approx(alone, abs=0.05)


def test_risk_engine_three_tier_hysteresis() -> None:
    engine = RiskEngine(FakeDetector())
    assert engine.update("d", config.HAZARD_ENTER_LOW) == ("LOW", True)
    assert engine.update("d", config.HAZARD_ENTER_MEDIUM) == ("MEDIUM", True)
    assert engine.update("d", config.HAZARD_ENTER_HIGH) == ("HIGH", True)


def test_level_rises_immediately_but_falls_on_cooldown() -> None:
    """🔴 Hysteresis BẤT ĐỐI XỨNG, và sự bất đối xứng đó là chủ ý.

    Lên mức chậm một nhịp là vấp. Xuống mức nhanh một nhịp thì một khung hình
    trượt detector sẽ tắt phụt tiếng cảnh báo giữa lúc người dùng đang bước
    tới đúng cái cột đó.
    """
    engine = RiskEngine(FakeDetector())
    engine.update("d", config.HAZARD_ENTER_HIGH, now=100.0)
    # Ngay lập tức hết nguy hiểm: vẫn giữ HIGH vì chưa hết cooldown.
    assert engine.update("d", 0.0, now=100.5) == ("HIGH", False)
    # Sau cooldown mới hạ.
    after = 100.0 + config.HAZARD_COOLDOWN_MS / 1000.0 + 0.1
    assert engine.update("d", 0.0, now=after) == ("SAFE", True)


def test_risk_cooldown_prevents_flicker() -> None:
    engine = RiskEngine(FakeDetector())
    engine.update("d", config.HAZARD_ENTER_HIGH, now=0.0)
    changes = sum(
        1 for step in range(1, 10) if engine.update("d", 0.0, now=step * 0.1)[1]
    )
    assert changes == 0


def test_devices_do_not_share_risk_state() -> None:
    engine = RiskEngine(FakeDetector())
    engine.update("glasses-01", config.HAZARD_ENTER_HIGH)
    assert engine.current_level("glasses-01") == "HIGH"
    assert engine.current_level("glasses-02") == "SAFE"


def test_evaluate_without_detector_raises_rather_than_reporting_safe() -> None:
    """🔴 SAFE nghĩa là "đã nhìn và thấy an toàn", không phải "chưa nhìn được".

    Trộn hai thứ đó là hứa với người dùng một thứ không tồn tại.
    """
    engine = RiskEngine(None)
    with pytest.raises(hazard_risk.HazardWatchUnavailable):
        engine.evaluate("glasses-01", b"\xff\xd8jpeg")


# ─── 5.4 downlink ──────────────────────────────────────────────────────────


def test_hazard_level_event_sent_only_on_change() -> None:
    """W3 — hàng đợi mỗi thiết bị chỉ có 8 chỗ.

    Gửi mỗi khung hình sẽ đẩy văng `call_incoming` ra khỏi hàng, tức một cuộc
    gọi đến bị nuốt mất vì chế độ canh vật cản đang bật.
    """
    stream = events.subscribe("glasses-01")
    try:
        assert hazard_watch.publish_level("glasses-01", "HIGH", changed=True) == 1
        assert hazard_watch.publish_level("glasses-01", "HIGH", changed=False) == 0
        assert json.loads(next(stream)[6:-2]) == {"type": "hazard_level", "level": "HIGH"}
        assert events.queued_count("glasses-01") == 0
    finally:
        stream.close()


def test_no_audio_bytes_sent_for_hazard_level() -> None:
    """🔴 KHOÁ KIẾN TRÚC: board tự sinh tông (W6), không nhận audio qua mạng.

    Cảnh báo vật cản mà đi qua mạng thì độ trễ mạng nằm thẳng giữa vật cản và
    cái chân người dùng. Cùng triết lý G8 (`cueSent()` ở 0 ms).
    """
    stream = events.subscribe("glasses-01")
    try:
        events.hazard_level("glasses-01", "HIGH")
        chunk = next(stream)
        assert len(chunk) < 120
        payload = json.loads(chunk[6:-2])
        assert set(payload) == {"type", "level"}
    finally:
        stream.close()


def test_unknown_hazard_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        events.hazard_level("glasses-01", "RẤT NGUY HIỂM")


def test_hazard_watch_action_must_be_start_or_stop() -> None:
    with pytest.raises(ValueError):
        events.hazard_watch("glasses-01", "pause")


# ─── T16 không bị đụng ─────────────────────────────────────────────────────


def test_turn_based_hazard_intent_now_starts_the_watch_mode() -> None:
    """🔴 ĐẢO NGƯỢC 2026-08-25, theo quyết định tường minh của người dùng.

    Test này TRƯỚC ĐÂY khoá điều ngược lại: `hazard` theo lượt (T16, qua Gemini)
    chạy song song và "không bị thay thế" — đúng như SPEC mục 28.6 viết.

    Người dùng gỡ cả hai: `hazard` giờ **bật chế độ canh**, không trả lời câu
    nào. Lý do là bản chất câu hỏi: câu trả lời một lần chỉ đúng cho khoảnh khắc
    bấm nút, mà vật cản thì gặp trong lúc ĐANG ĐI — hỏi một câu rồi bước tiếp
    năm bước là câu trả lời đã hết hạn.

    `handlers/describe_hazard.py` vì thế không còn ai gọi tới. Khoá "chỉ được
    thêm comment" trong CLAUDE.md/RUNBOOK mục 7 đã được gỡ tường minh.
    """
    from pipeline.router import _HANDLERS, _IMAGE_REQUIRED_INTENTS
    from schemas import Intent

    assert _HANDLERS[Intent.HAZARD] is _HANDLERS[Intent.HAZARD_WATCH_START]

    # Và nó KHÔNG được đòi ảnh nữa: cổng chất lượng ảnh có quyền chặn, tức
    # "ảnh mờ quá" sẽ ngăn người dùng bật được cảnh báo vật cản — đúng lúc
    # trời tối/rung tay là lúc người ta cần bật nhất.
    assert Intent.HAZARD not in _IMAGE_REQUIRED_INTENTS


# ─── T24/W4: độ sâu là tín hiệu chính, YOLO là phụ ─────────────────────────


def test_depth_catches_what_yolo_is_blind_to() -> None:
    """🔴 Lý do tồn tại của cả tầng độ sâu, khoá bằng số đo thật.

    YOLO11n biết đúng 80 lớp COCO và KHÔNG có lớp "vật thể chung". Đo được
    2026-08-24 trên `ocr_screenshot.png`:

        YOLO một mình   0 vật  -> SAFE
        độ sâu + YOLO   1 vùng -> LOW  (gần 0.74)

    `SAFE` ở đây nghĩa là "đã nhìn và thấy an toàn" — trong khi thật ra model
    chỉ **không biết gọi tên** thứ nó thấy. Cột điện, tường, bậc thềm, cành
    cây thấp đều rơi vào đúng lỗ hổng đó.

    Ca này dùng detector giả nên chạy được cả khi máy chưa tải model.
    """
    from services.depth_detector import CombinedDetector

    class BlindYolo:
        """Đúng hành vi của YOLO trước một vật ngoài 80 lớp COCO."""

        def detect(self, jpeg: bytes) -> list[Box]:
            return []

    class DepthSeesIt:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="obstacle", confidence=0.74, x1=0.3, x2=0.7)]

    engine_yolo = RiskEngine(BlindYolo())
    engine_both = RiskEngine(CombinedDetector(DepthSeesIt(), BlindYolo()))

    assert engine_yolo.score_boxes("a", BlindYolo().detect(b"")) == 0.0
    assert engine_both.score_boxes("b", engine_both._detector.detect(b"")) > 0.0


def test_named_detector_failure_does_not_silence_the_warning() -> None:
    """YOLO hỏng thì mất TÊN, không được mất CẢNH BÁO.

    Tầng đặt tên là phụ. Để lỗi của nó kéo sập tầng chính là đổi một tính
    năng phụ lấy toàn bộ chức năng an toàn.
    """
    from services.depth_detector import CombinedDetector

    class ExplodingYolo:
        def detect(self, jpeg: bytes) -> list[Box]:
            raise RuntimeError("model hỏng")

    class DepthWorks:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="obstacle", confidence=0.8)]

    boxes = CombinedDetector(DepthWorks(), ExplodingYolo()).detect(b"")
    assert len(boxes) == 1
    assert boxes[0].label == "obstacle"


def test_depth_region_borrows_the_name_of_an_overlapping_box() -> None:
    """Vùng độ sâu trùng nhiều với một box YOLO thì mượn nhãn của box đó."""
    from services.depth_detector import CombinedDetector

    class DepthWorks:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="obstacle", confidence=0.8, x1=0.4, y1=0.3, x2=0.6, y2=0.9)]

    class YoloNames:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="person", confidence=0.9, x1=0.35, y1=0.25, x2=0.65, y2=0.95)]

    boxes = CombinedDetector(DepthWorks(), YoloNames()).detect(b"")
    assert boxes[0].label == "person"
    # Độ "gần" vẫn là của tầng độ sâu, không phải confidence của YOLO.
    assert boxes[0].confidence == 0.8


def test_unnamed_region_keeps_the_generic_label() -> None:
    """Vùng không trùng box nào giữ nhãn `obstacle` — và đó là điểm mạnh.

    Chính những vùng này là thứ YOLO một mình bỏ sót hoàn toàn.
    """
    from services.depth_detector import CombinedDetector

    class DepthWorks:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="obstacle", confidence=0.8, x1=0.0, y1=0.6, x2=0.15, y2=1.0)]

    class YoloElsewhere:
        def detect(self, jpeg: bytes) -> list[Box]:
            return [_box(label="person", confidence=0.9, x1=0.7, y1=0.1, x2=0.9, y2=0.5)]

    assert CombinedDetector(DepthWorks(), YoloElsewhere()).detect(b"")[0].label == "obstacle"


def test_labels_never_affect_the_risk_score() -> None:
    """Một cái cột và một con người chắn đường đều là vật cản như nhau."""
    engine = RiskEngine(FakeDetector())
    named = engine.score_boxes("a", [_box(label="person")])
    engine.reset()
    unnamed = engine.score_boxes("b", [_box(label="obstacle")])
    assert named == unnamed


# ═══════════════════════════════════════════════════ tốc độ suy luận độ sâu

def test_depth_session_locks_the_input_size() -> None:
    """Khoá `height`/`width` là tối ưu lớn nhất của module — và dễ bị gỡ nhầm.

    Không khoá thì ORT không gấp được nhánh nội suy position-embedding của
    DINOv2 thành hằng số, và nhánh đó một mình tốn 63.5/162 ms — hơn cả 48
    phép MatMul của 12 block ViT cộng lại. Đo được: 177 ms → 107 ms.

    Nó KHÔNG đổi kết quả (gấp hằng số, không phải xấp xỉ), nên khi nó bị gỡ
    thì không có test nào khác đỏ và không có ảnh nào sai — chỉ có vòng canh
    vật cản lặng lẽ chậm đi 65%. Đó là lý do phải có đúng dòng assert này.
    """
    from pathlib import Path

    import config

    if not Path(config.DEPTH_MODEL_PATH).is_file():
        import pytest

        pytest.skip("chưa tải model độ sâu — python tools/fetch_depth_model.py")

    from services.depth_detector import DepthObstacleDetector

    detector = DepthObstacleDetector(config.DEPTH_MODEL_PATH)
    shape = detector._session.get_inputs()[0].shape
    assert shape[2] == config.DEPTH_INPUT_SIZE, (
        f"đầu vào vẫn động ({shape}) — mất 40% tốc độ, xem docstring"
    )
    assert shape[3] == config.DEPTH_INPUT_SIZE


def test_depth_input_size_is_a_multiple_of_14() -> None:
    """Patch của DINOv2 là 14×14 và đầu ra khai báo `14*floor(h/14)`.

    Cỡ không chia hết cho 14 thì model tự cắt xuống bội gần nhất — ta trả
    tiền resize cho những dòng pixel bị vứt đi, và bản đồ độ sâu lệch so với
    khung ảnh đúng phần dư đó.
    """
    import config

    assert config.DEPTH_INPUT_SIZE % 14 == 0, (
        f"DEPTH_INPUT_SIZE={config.DEPTH_INPUT_SIZE} không chia hết cho 14"
    )


# ═══════════════════════════════ chính xác trên ảnh THẬT (tests/data/hazard)

def _real_dataset():
    """(detector, labels) hoặc None nếu chưa có model/ảnh."""
    import json
    from pathlib import Path

    import config

    data = Path(__file__).parent / "data" / "hazard"
    labels_path = data / "labels.json"
    if not labels_path.is_file():
        return None
    if not Path(config.DEPTH_MODEL_PATH).is_file():
        return None

    from services.depth_detector import DepthObstacleDetector

    labels = {
        k: v for k, v in json.loads(labels_path.read_text("utf-8")).items()
        if not k.startswith("_") and (data / k).is_file()
    }
    if not labels:
        return None
    return DepthObstacleDetector(config.DEPTH_MODEL_PATH), labels, data


def _alarms(detector, data, name) -> bool:
    import config

    engine = RiskEngine(detector)
    score = engine.score_boxes(name, detector.detect((data / name).read_bytes()))
    return score >= config.HAZARD_ENTER_LOW


def test_does_not_alarm_on_an_empty_road() -> None:
    """🔴 Test đắt nhất của file này. Đọc lý do trước khi nới lỏng nó.

    Bản đầu của `depth_detector` chấm điểm bằng một ngưỡng TUYỆT ĐỐI trên bản
    đồ disparity đã chuẩn hoá theo khung. Trên 4 ảnh fixture nó trông hợp lý.
    Trên 25 ảnh thật nó **báo oan 11/11** — kêu HIGH cho một con đường quê
    trống trơn — vì chuẩn hoá theo khung luôn đẩy thứ gần nhất về 1.0, và thứ
    gần nhất trong mọi khung chụp lúc đi bộ là mặt đất dưới chân.

    Không một test giả lập nào bắt được lỗi đó: mọi `FakeDetector` đều trả
    box mà người viết test tự nghĩ ra. Chỉ ảnh thật mới lộ.

    Một chế độ canh vật cản kêu ở mọi bước chân thì người dùng tắt nó sau buổi
    sáng đầu tiên — và lúc đó tỉ lệ bỏ sót là 100%.
    """
    import pytest

    bundle = _real_dataset()
    if bundle is None:
        pytest.skip("chưa có model độ sâu hoặc bộ ảnh thật")
    detector, labels, data = bundle

    clear = [n for n, v in labels.items() if v["label"] == "clear"]
    if not clear:
        pytest.skip("bộ ảnh chưa có ảnh 'clear' nào")

    noisy = [n for n in clear if _alarms(detector, data, n)]
    # Ngưỡng khoá ở mức ĐO ĐƯỢC (2/11), không phải mức mong muốn (0/11). Đặt
    # 0 thì test đỏ ngay hôm nay và sẽ bị ai đó tắt đi; đặt ở mức đo được thì
    # nó bắt được đúng cái nó phải bắt: sự THỤT LÙI.
    assert len(noisy) <= 2, (
        f"báo oan {len(noisy)}/{len(clear)} ảnh đường trống: "
        f"{[n.rsplit('/', 1)[-1] for n in noisy]}"
    )


def test_still_catches_a_pole_that_yolo_is_blind_to() -> None:
    """Cột điện sát lối đi — không nằm trong 80 lớp COCO, YOLO im hoàn toàn."""
    import pytest

    bundle = _real_dataset()
    if bundle is None:
        pytest.skip("chưa có model độ sâu hoặc bộ ảnh thật")
    detector, labels, data = bundle

    name = "blocked/Sidewalk_guy_wire.jpg"
    if name not in labels:
        pytest.skip("chưa tải ảnh cột điện")

    assert _alarms(detector, data, name), (
        "bỏ sót cây cột chắn lối đi — đây là chính ca mà đường độ sâu sinh ra "
        "để bắt, và YOLO một mình luôn báo SAFE cho nó"
    )
