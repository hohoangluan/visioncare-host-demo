"""Khung lệnh `WS /v2/live` (§5.3). Kính chỉ làm đúng lệnh vừa nhận."""

import json

FRAME_JPEG = 0x01  # kính -> server: 0x01 + JPEG
FRAME_AUDIO = 0x02  # server -> kính: 0x02 + khối ADPCM


def cam(size: str, fps: int, quality: int = 12) -> str:
    return json.dumps({"t": "cam", "size": size, "fps": fps, "quality": quality})


def capture(size: str = "uxga") -> str:
    return json.dumps({"t": "capture", "size": size})


def cue(cue_id: str) -> str:
    return json.dumps({"t": "cue", "id": cue_id})


def hazard(level: int, direction: str, kind: str) -> str:
    return json.dumps({"t": "hazard", "level": level, "dir": direction, "kind": kind})


def end() -> str:
    return json.dumps({"t": "end"})


def audio(chunk: bytes) -> bytes:
    return bytes([FRAME_AUDIO]) + chunk


def parse_frame(data: bytes) -> bytes | None:
    """Khung nhị phân của kính -> JPEG, hoặc `None` nếu không phải khung ảnh."""
    if len(data) > 1 and data[0] == FRAME_JPEG:
        return data[1:]
    return None
