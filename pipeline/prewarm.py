"""Task Prewarm (§7.4): đoán sớm chỉ CHUẨN BỊ tài nguyên, không thực thi gì.

| Đoán sớm | Prewarm                                          | Tuyệt đối không          |
| A        | Gemma max_tokens=1 với đúng prefix (ảnh + system) | sinh câu trả lời         |
| B        | tạo live session + token; chạy text detector trên ảnh buffer | mở camera, phát cue |
| C        | tạo live session + token (hazard model nạp sẵn lúc khởi động) | gửi lệnh điện thoại |
| D        | Gemma max_tokens=1 với prefix trích tham số        | gửi lệnh điện thoại      |

Đoán sai thì `discard()` bỏ phần đã nóng: token không dùng tự hết hạn.
"""

import asyncio
import logging

from lanes import general, phone
from live import text_align
from live.session import LiveSession, sessions
from models import llm
from pipeline.image_buffer import image_buffer
from pipeline.intent_early import Decision

logger = logging.getLogger("blind_assist")


class Prewarmer:
    def __init__(self, device: str, turn_id: str) -> None:
        self.device, self.turn_id = device, turn_id
        self.live_ok = True  # False ở `/process`: không có WS nên không tạo phiên live
        self.live: dict[str, LiveSession] = {}  # "ocr"|"nav" -> phiên đã tạo sẵn
        self.ocr_assessment: asyncio.Task | None = None
        self._done: set[str] = set()
        self._tasks: list[asyncio.Task] = []

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.append(task)
        return task

    def session(self, mode: str, params: dict | None = None) -> LiveSession:
        """Phiên của làn B/C: lấy bản đã tạo sẵn, hoặc tạo mới."""
        session = self.live.get(mode)
        if session is None:
            session = self.live[mode] = sessions.create(self.device, mode)
        session.params.update(params or {})
        return session

    def assess_buffer(self) -> asyncio.Task | None:
        if self.ocr_assessment is None:
            entry = image_buffer.get(self.device, self.turn_id)
            if entry is None:
                return None
            self.ocr_assessment = self._spawn(asyncio.to_thread(text_align.assess_jpeg, entry.jpeg))
        return self.ocr_assessment

    async def _warm_llm_vision(self, intent: str) -> None:
        entry = image_buffer.get(self.device, self.turn_id)
        image = await asyncio.to_thread(entry.llm_jpeg) if entry is not None else None
        await llm.prewarm(general.prefix_messages(intent, image))

    def on_guess(self, intent: str, mode: str, source: str) -> None:
        lane = Decision(intent, mode).lane
        key = f"{lane}:{intent if lane == 'A' else ''}"
        if key in self._done:
            return
        self._done.add(key)
        logger.info("prewarm làn %s (%s, %s)", lane, intent, source)
        if lane == "A" and not (intent == "ocr" and mode == "reread"):
            self._spawn(self._warm_llm_vision(intent))
        elif lane == "B" and intent == "ocr":
            if self.live_ok:
                self.session("ocr")
                self.assess_buffer()
        elif lane == "B" and intent in ("money", "find"):
            self._spawn(self._warm_llm_vision(intent))
        elif lane == "C" and intent in ("nav_start", "alert_on"):
            if self.live_ok:
                self.session("nav")
        if intent in phone.SLOT:
            self._spawn(llm.prewarm(phone.extraction_prefix()))

    def discard(self, keep: str | None = None) -> None:
        """Bỏ phiên tạo sẵn không dùng tới; không huỷ task (chúng tự kết thúc)."""
        for mode, session in self.live.items():
            if session.token != keep:
                sessions.discard(session.token)
