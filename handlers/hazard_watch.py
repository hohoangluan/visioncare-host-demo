"""T24/W1 — bật và tắt chế độ canh vật cản thời gian thực.

KHÁC `handlers/describe_hazard.py` (T16): cái kia trả lời MỘT câu hỏi về một
khung hình. Cái này bật một chế độ chạy liên tục cho tới khi có người tắt.
Hai thứ chạy song song và không loại trừ nhau — người dùng hoàn toàn có thể
hỏi "trước mặt có gì" trong lúc chế độ canh đang bật.

🔴 Fail-closed. Không có model nhận diện thì **không bật**, và nói thẳng ra.
Một chế độ cảnh báo vật cản im lặng còn nguy hiểm hơn không có nó: người dùng
tin là đang được canh và đi nhanh hơn bình thường.
"""

from __future__ import annotations

from collections.abc import Iterator

from handlers import action_flow
from services.events_channel import events
from services.frame_buffer import frames
from services.hazard_risk import risk_engine
from services.hazard_worker import worker

_TASK = "hazard_watching"

_ON = "Đã bật chế độ cảnh báo vật cản."
_OFF = "Đã tắt chế độ cảnh báo vật cản."
_ALREADY_ON = "Chế độ cảnh báo vật cản đang bật rồi."
_ALREADY_OFF = "Chế độ cảnh báo vật cản chưa bật."
_UNAVAILABLE = (
    "Chưa bật được chế độ cảnh báo vật cản trên máy này. Bạn vẫn hỏi trước mặt "
    "có gì được như bình thường."
)


def start(device_key: str | None = None) -> Iterator[str]:
    """Bật chế độ. Câu trả lời là câu DỰNG SẴN — không gọi Gemini, không ảnh."""
    if not risk_engine.available:
        # Nói ra rồi dừng. KHÔNG bật cờ, KHÔNG gửi lệnh xuống board: bật một
        # vòng chụp liên tục mà không ai chấm điểm là đốt pin để đổi lấy im
        # lặng, và người dùng sẽ tưởng mình đang được canh.
        yield _UNAVAILABLE
        return

    if action_flow.device_state(device_key).get("hazard_watching"):
        yield _ALREADY_ON
        return

    action_flow.mark_active(_TASK, device_key)
    risk_engine.reset(device_key or "")
    events.hazard_watch(device_key or "", "start")
    # 🔴 Bật vòng chấm điểm TRƯỚC khi nói "đã bật". Không có dòng này thì board
    # chụp 2 fps, `POST /frame` cất khung vào `FrameBuffer`, và không ai đọc —
    # người dùng nghe câu dưới rồi im lặng vĩnh viễn. Xem `services/
    # hazard_worker.py` phần đầu file.
    worker.watch(device_key or "")
    yield _ON


def stop(device_key: str | None = None) -> Iterator[str]:
    """Tắt chế độ. Phải chạy được cả khi chế độ đang KHÔNG bật.

    Người dùng nói "tắt cảnh báo" khi không chắc nó đang bật hay tắt là ca
    thường gặp nhất, và trả lời bằng im lặng ở đó là tệ nhất.
    """
    was_on = bool(action_flow.device_state(device_key).get("hazard_watching"))

    # Dọn dẹp KHÔNG điều kiện, kể cả khi cờ đã tắt: cờ và khung hình đang giữ
    # có thể lệch nhau sau một lần khởi động lại server, và để sót khung cũ
    # thì lần bật sau sẽ chấm điểm trên căn phòng lúc trước.
    action_flow.mark_inactive(_TASK, device_key)
    worker.unwatch(device_key or "")
    frames.drop_hazard(device_key or "")
    risk_engine.reset(device_key or "")
    events.hazard_watch(device_key or "", "stop")

    yield _OFF if was_on else _ALREADY_OFF


def publish_level(device_id: str, level: str, changed: bool) -> int:
    """Đẩy mức mới xuống board — CHỈ khi mức thật sự đổi (W3).

    Tách khỏi `RiskEngine.update()` có chủ ý: máy chấm điểm không được biết gì
    về SSE, và cách duy nhất giữ được điều đó là để chỗ khác quyết định khi
    nào gửi.
    """
    if not changed:
        return 0
    return events.hazard_level(device_id, level)


def _force_stop(device_id: str) -> None:
    """Worker gọi khi detector hỏng liên tiếp — tắt luôn cả cờ session lẫn board.

    Không dùng lại `stop()` ở trên: cái đó là generator sinh câu nói cho một
    lượt hội thoại, còn ở đây không có lượt nào và không có ai để nói với.
    """
    action_flow.mark_inactive(_TASK, device_id)
    frames.drop_hazard(device_id)
    risk_engine.reset(device_id)
    events.hazard_watch(device_id, "stop")


# Cắm handler vào worker. Đặt ở CUỐI file: `worker.set_sinks()` cần
# `publish_level` và `_force_stop` đã định nghĩa xong.
worker.set_sinks(publish_level, _force_stop)
