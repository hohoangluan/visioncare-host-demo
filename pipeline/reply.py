"""Kết quả của Final Router cho một lượt `/v2/turn`."""

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class Reply:
    # Cue phát từ flash TRƯỚC audio (`X-Cue`).
    cues: list[str] = field(default_factory=list)
    # Mảnh text cho VieNeu-TTS; rỗng nếu chỉ có cue. Iterable đồng bộ vì TTS đọc
    # nó trong thread nền (`tts.synthesize_text_stream`).
    speech: Iterable[str] = ()
    # "ocr" | "nav": sau khi phát xong kính mở `WS /v2/live` (`X-Live`).
    live: str | None = None
    live_token: str | None = None
    # Nhãn cuối, chỉ để log/bench.
    intent: str = ""
    lane: str = ""
