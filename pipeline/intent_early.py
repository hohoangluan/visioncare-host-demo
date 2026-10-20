"""Early Intent (§7.2) + intent cuối (§7.3).

Đoán sớm trên partial CHỈ để prewarm. Hai tầng:
1. luật từ khoá — 0 ms, chạy trên mọi partial;
2. bộ phân loại (`pipeline/intent_classifier.py`: Gemma UIT, Clef dự phòng) trên
   partial khi partial >= 3 từ và đứng yên 300 ms; tối đa 2 lượt mỗi turn.

Intent cuối: bộ phân loại trên bản ghi cuối. Người dùng thường nói xong rồi mới
nhả nút, nên partial đứng yên cuối cùng hay TRÙNG bản ghi cuối — lúc đó dùng lại
đúng kết quả đã có (hoặc đang chạy), bỏ hẳn một lượt mạng khỏi đường chờ.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import config
from pipeline import intent_classifier as classifier

logger = logging.getLogger("blind_assist")

# intent -> làn (§8). `ocr` reread đi làn A, xử lý ở router.
LANE = {
    "chat": "A", "space": "A", "hazard": "A",
    "ocr": "B", "money": "B", "find": "B",
    "nav_start": "D", "nav_stop": "D", "alert_on": "C", "alert_off": "C",
    "contact_call": "D", "emergency_call": "D", "ride_quote": "D",
    "ride_confirm": "D", "music_play": "D", "music_stop": "D", "music_volume": "D",
}

# Luật từ khoá, cụ thể đứng trước chung. (regex, intent, ocr_mode)
_RULES: tuple[tuple[re.Pattern, str, str], ...] = tuple(
    (re.compile(rf"(?<!\w)(?:{pattern})(?!\w)"), intent, mode)
    for pattern, intent, mode in (
        (r"cấp cứu|khẩn cấp|cứu tôi|cứu với|sos", "emergency_call", ""),
        (r"tắt(?: chức năng)? cảnh báo|dừng cảnh báo|ngừng cảnh báo|ngừng nhắc vật cản|đừng (?:báo|nhắc) (?:vật cản|chướng ngại)", "alert_off", ""),
        (r"bật cảnh báo|mở cảnh báo", "alert_on", ""),
        (r"dừng chỉ đường|tắt chỉ đường|dừng dẫn đường|tắt dẫn đường", "nav_stop", ""),
        (r"dẫn đường|chỉ đường|dẫn tôi|đưa tôi tới|đưa tôi đến|tìm đường|^(?:hãy )?đi (?:tới|đến)", "nav_start", ""),
        (r"tắt nhạc|dừng nhạc|ngừng nhạc|dừng nghe nhạc|ngừng nghe nhạc", "music_stop", ""),
        (r"âm lượng|to lên|nhỏ lại|vặn to|vặn nhỏ", "music_volume", ""),
        (r"nghe nhạc|phát nhạc|mở nhạc|bài hát|mở bài", "music_play", ""),
        (r"đặt xe|gọi xe|grab|taxi", "ride_quote", ""),
        (r"xác nhận đặt|huỷ chuyến|hủy chuyến|đồng ý chuyến", "ride_confirm", ""),
        (r"gọi cho|gọi điện|gọi điện thoại", "contact_call", ""),
        (r"đọc lại", "ocr", "reread"),
        (r"tóm tắt", "ocr", "summarize"),
        (r"mệnh giá|tờ tiền|số tiền|bao nhiêu tiền|tiền gì", "money", ""),
        (r"nguyên văn|y nguyên|từng chữ", "ocr", "raw"),
        (r"chuyên ngành|hợp đồng|đơn thuốc|toa thuốc|hướng dẫn sử dụng", "ocr", "specialized"),
        (r"^(?:hãy |xin |làm ơn )?đọc", "ocr", "read"),
        (r"có an toàn|vật cản|chướng ngại|có nguy hiểm không", "hazard", ""),
        (r"trước mặt|có gì|xung quanh|khung cảnh", "space", ""),
        (r"tìm|ở đâu rồi|để đâu", "find", ""),
    )
)


# needs_web bằng luật (Task 4d). Hai nhóm: (1) thông tin MỚI nói thẳng ra (thời tiết, giá, tin,
# tỉ số, giờ mở cửa...); (2) hỏi địa điểm kinh doanh "gần đây/ở đâu" (gold gán web vì phải tra bản
# đồ). Câu chỉ cảnh vật ngay trước mắt ("phía trước", "trước mặt") và hỏi địa danh hành chính
# ("thuộc tỉnh nào") KHÔNG phải web.
_WEB_FRESH = re.compile(
    r"(?<!\w)(?:thời tiết|nhiệt độ|mưa|nắng|dự báo|giá(?: cả)?|bao nhiêu tiền|tỉ giá|tỷ giá|giá vàng|giá xăng|"
    r"xăng|tin tức|thời sự|mới nhất|tỉ số|tỷ số|kết quả (?:trận|bóng)|lịch chiếu|lịch thi đấu|"
    r"giờ mở cửa|giờ đóng cửa|mấy giờ (?:mở|đóng)|còn mở|đang mở|có mở cửa|"
    r"(?:hôm nay|tối nay|ngày mai|cuối tuần|tuần này) (?:có|diễn ra|trời|sự kiện))(?!\w)"
)
_WEB_PLACE = re.compile(
    r"(?<!\w)(?:quán|tiệm|quầy|chợ|kiosk|bưu điện|cây rút tiền|cây atm|atm|ngân hàng|cửa hàng|siêu thị|"
    r"nhà thuốc|hiệu thuốc|tiệm thuốc|cà phê|nhà hàng|bệnh viện|phòng khám|trạm xăng|tiệm tạp hoá|"
    r"tạp hóa|tạp hoá)(?!\w)"
)
_WEB_WHERE = re.compile(r"(?<!\w)(?:gần nhất|gần đây|quanh đây|ở đâu|chỗ nào)(?!\w)")
_WEB_NOT = re.compile(r"(?<!\w)(?:phía trước|trước mặt|bên cạnh tôi|thuộc|thành phố nào|tỉnh nào)(?!\w)")


def needs_web_rule(text: str) -> bool:
    lowered = (text or "").lower()
    if _WEB_FRESH.search(lowered):
        return True
    return bool(
        _WEB_PLACE.search(lowered) and _WEB_WHERE.search(lowered) and not _WEB_NOT.search(lowered)
    )


_BLOCKED_BY_KEYWORD = {
    "contact_call", "emergency_call", "ride_quote", "ride_confirm", "music_play", "nav_start",
}


@dataclass
class Decision:
    intent: str
    ocr_mode: str = "read"
    needs_web: bool = False
    # "model" | "model-cache" | "keyword" | "fallback-chat" | "no_speech" | "keyword-blocked"
    source: str = ""
    confidence: float = 0.0
    seconds: float = 0.0
    # Bộ phân loại ra nhãn: "gemma" | "clef" | "" (không rõ / luật từ khoá).
    # Làn D chỉ chạy thẳng khi backend == "gemma".
    backend: str = ""
    # False: Gemma không trả logprobs nên `confidence` là giả định (xem ClefResult.confidence_known).
    confidence_known: bool = True

    @property
    def lane(self) -> str:
        if self.intent == "ocr" and self.ocr_mode == "reread":
            return "A"
        return LANE.get(self.intent, "A")


def keyword_rule(text: str) -> tuple[str, str] | None:
    lowered = (text or "").lower()
    for pattern, intent, mode in _RULES:
        if pattern.search(lowered):
            return intent, mode or "read"
    return None


class EarlyIntent:
    """Theo dõi partial của MỘT lượt, giữ đoán sớm và kết quả phân loại đã có."""

    def __init__(self, device_state: dict | None = None, on_guess=None) -> None:
        self.device_state = device_state or {}
        self._on_guess = on_guess  # gọi (intent, ocr_mode, source) khi đoán đổi
        self.guess: tuple[str, str] | None = None
        self._last_text = ""
        self._stable_since = 0.0
        self._classified: dict[str, asyncio.Task] = {}
        self._calls = 0

    def _set_guess(self, intent: str, mode: str, source: str) -> None:
        if self.guess != (intent, mode):
            self.guess = (intent, mode)
            logger.info("đoán sớm (%s): %s %s", source, intent, mode)
            if self._on_guess is not None:
                self._on_guess(intent, mode, source)

    def on_partial(self, text: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if text != self._last_text:
            self._last_text, self._stable_since = text, now
            rule = keyword_rule(text)
            if rule is not None:
                self._set_guess(*rule, "keyword")
            return
        self._maybe_classify(text, now)

    def _maybe_classify(self, text: str, now: float) -> None:
        if (
            not classifier.available()
            or len(text.split()) < config.EARLY_CLASSIFY_MIN_WORDS
            or now - self._stable_since < config.EARLY_CLASSIFY_STABLE_S
            or text in self._classified
            or self._calls >= config.EARLY_CLASSIFY_MAX_CALLS
            or (config.EARLY_CLASSIFY_SKIP_INFLIGHT and any(not t.done() for t in self._classified.values()))
        ):
            return
        self._calls += 1
        task = asyncio.get_running_loop().create_task(classifier.classify(text, self.device_state))
        self._classified[text] = task

        def done(t: asyncio.Task) -> None:
            if t.cancelled() or t.exception() is not None:
                return
            result = t.result()
            if result is not None and result.confidence >= config.CLEF_MIN_CONFIDENCE:
                self._set_guess(result.intent, result.ocr_mode, "model")

        task.add_done_callback(done)

    async def decide(self, text: str) -> Decision:
        """Intent cuối từ bản ghi cuối."""
        started = time.monotonic()
        if not text.strip():
            return Decision("", source="no_speech")

        task = self._classified.get(text)
        source = "model-cache" if task is not None else "model"
        if task is not None and task.done() and not task.cancelled() and task.exception() is None \
                and task.result() is not None:
            result = task.result()
        else:
            result, source = await self._hedged(text, task)

        rule = keyword_rule(text)
        if result is not None and result.confidence >= config.CLEF_MIN_CONFIDENCE:
            mode = result.ocr_mode
            # Luật từ khoá chắc hơn model ở chế độ OCR ("tóm tắt", "đọc lại" nói thẳng ra).
            if result.intent == "ocr" and rule is not None and rule[0] == "ocr":
                mode = rule[1]
            return Decision(
                result.intent, mode, result.needs_web, source,
                result.confidence, time.monotonic() - started,
                backend=getattr(result, "source", "") or "",
                confidence_known=getattr(result, "confidence_known", True),
            )

        if rule is not None:
            # An toàn: luật từ khoá KHÔNG BAO GIỜ được kích hoạt hành động có tác dụng
            # phụ (CONFIRM_INTENTS: gọi điện, đặt xe, nhạc; và nav_start). Bộ phân loại
            # hỏng thì báo bận thay vì đoán theo chữ. Ngoại lệ: music_stop, music_volume,
            # nav_stop — đảo ngược được, không liên quan bên thứ ba, người khiếm thị
            # phải tắt được âm thanh dù model hỏng.
            if rule[0] in _BLOCKED_BY_KEYWORD:
                logger.warning("chặn làn D theo từ khoá (bộ phân loại hỏng): %s", rule[0])
                return Decision("", source="keyword-blocked", seconds=time.monotonic() - started)
            return Decision(rule[0], rule[1], False, "keyword", 0.0, time.monotonic() - started)
        # Bộ phân loại hỏng/quá hạn và câu không khớp luật nào -> trò chuyện (làn A).
        # Lệch spec §7.3 (spec: cue system_busy): đo thật Clef có lượt > 1 s, và
        # trả "hệ thống bận" cho một câu chat hợp lệ tệ hơn để Gemma trả lời —
        # làn A không có tác dụng phụ, câu vô nghĩa thì Gemma tự nói chưa hiểu.
        # Làn D (gọi điện...) vẫn chỉ đi khi có nhãn chắc chắn.
        return Decision("chat", source="fallback-chat", seconds=time.monotonic() - started)

    async def _hedged(self, text: str, cached: asyncio.Task | None):
        """Lượt phân loại trên partial chưa xong: bắn thêm lượt mới, lấy lượt về trước."""
        fresh = asyncio.ensure_future(classifier.classify(text, self.device_state))
        tasks = {fresh: "model"}
        if cached is not None and not cached.done():
            tasks[asyncio.ensure_future(asyncio.shield(cached))] = "model-cache"
        pending = set(tasks)
        deadline = time.monotonic() + config.INTENT_DECIDE_TIMEOUT_S
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=max(0.0, deadline - time.monotonic()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    break
                for t in done:
                    if not t.cancelled() and t.exception() is None and t.result() is not None:
                        return t.result(), tasks[t]
            return None, "model"
        finally:
            for t in pending:
                t.cancel()

    def cancel(self) -> None:
        for task in self._classified.values():
            task.cancel()
