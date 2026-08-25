"""T21 — ngân sách độ trễ, deadline, và quan sát được.

Task file mô tả hiện trạng là *"code không có một timeout nào trên lời gọi
ngoài"*. **Điều đó đã trôi**: `GEMINI_TIMEOUT_SECONDS`,
`GEMINI_INTENT_TIMEOUT_SECONDS`, `timeout=10.0` của `httpx.Client`, và hai
`*_RESULT_TIMEOUT_SECONDS` đều đã có mặt (xem mục "Lệch với task file" của
`docs/tasks/reports/T21.md`). Nên phần lớn file này **khoá lại** thứ đã đúng
thay vì thêm mới — đúng loại test dễ bị xoá nhất, vì nó không đỏ lần nào cho
tới ngày ai đó gỡ một `timeout=`.

🔴 Ngưỡng thời gian THẬT không kiểm được ở đây. Máy CI chậm hơn máy dev, và
`p95` của một lượt có gọi Gemini phụ thuộc mạng chứ không phụ thuộc code —
CI sẽ đỏ ngẫu nhiên và người ta sẽ tắt nó đi. Phân công (câu hỏi 3 của task
file mục 6):

  * ở đây, chạy mọi lần: **có deadline / không treo im lặng / trace đủ trường**
  * `tools/measure_budget.py`, chạy tay trên máy chuẩn: **bảng số p50/p95**

Ca duy nhất có ngưỡng tuyệt đối là nhóm `@pytest.mark.perf` bên dưới, và
chúng chỉ đo những đường **không gọi ra ngoài** (câu dựng sẵn, cancel/repeat),
nên chậm đi ở đó là hồi quy code thật, không phải mạng dở.
"""

from __future__ import annotations

import inspect
import time

import pytest

import config
from services import turn_trace


# Bảng ngân sách G1. Đây là NGUỒN SỰ THẬT của mục 2 task file — sửa số ở đây
# thì phải sửa `CONTRACTS.md` và `measurements/G1.md` theo.
BUDGET_MS: dict[str, int] = {
    # ── không gọi mạng ngoài, audio dựng sẵn ──
    "emergency_call": 300,   # 🔴 không qua BẤT KỲ bước xác minh nào (mục 10)
    "call_answer": 300,
    "call_reject": 300,
    "music_stop": 300,
    "music_volume": 300,
    "nav_stop": 300,
    # T24/W1. `hazard_watch_stop` phải chặt: người dùng nói "tắt cảnh báo"
    # thường là vì tiếng tít đang làm phiền họ, nên mỗi mili giây trễ là một
    # mili giây nữa của thứ họ vừa xin tắt.
    "hazard_watch_start": 300,
    "hazard_watch_stop": 300,
    "unknown": 400,          # câu hỏi lại cố định
    # ── có gọi ngoài nhưng ack phát TRƯỚC kết quả API (G6) ──
    "contact_call": 600,
    "music_play": 600,
    "nav_start": 600,
    "ride_confirm": 600,
    # ── có gọi Gemini kèm ảnh ──
    "hazard": 800,
    "chat": 1000,
    "space": 1200,
    "find": 1200,
    "money": 1200,
    "ocr": 1200,             # ⚠️ xem câu hỏi mở #1: T15/H1 CỐ Ý làm chậm hơn
    "ride_quote": 1200,      # gọi giá qua server app
}

# Hai đường này không phải intent — router xử lý trước khi phân loại
# (T04 bước 2-5) — nhưng vẫn phải có ngân sách vì người dùng vẫn phải chờ.
ROUTER_BUDGET_MS: dict[str, int] = {
    "cancel": 300,
    "repeat": 300,
    "pending_deterministic": 400,  # "ừ", "số hai" — không LLM, không ảnh
}


def _all_intent_values() -> set[str]:
    """`Intent` là class hằng chuỗi, KHÔNG phải Enum — không lặp trực tiếp được.

    Đã vấp một lần: `for intent in Intent` ném `TypeError: 'type' object is not
    iterable`. Đọc qua `vars()` thì thêm một intent mới là ca này tự đỏ, đúng
    điều nó sinh ra để làm.
    """
    from schemas import Intent

    return {
        value
        for name, value in vars(Intent).items()
        if not name.startswith("_") and isinstance(value, str)
    }


@pytest.fixture(autouse=True)
def _clear_traces():
    turn_trace.traces.clear()
    yield
    turn_trace.traces.clear()


# ─── deadline: mọi lời gọi ngoài phải có trần thời gian ────────────────────


def test_every_external_call_has_deadline() -> None:
    """Không lời gọi ngoài nào được phép chờ vô hạn.

    Treo vô hạn là cách hỏng TỆ NHẤT của hệ này: người khiếm thị không nhìn
    thấy màn hình, nên "server đang nghĩ" và "server đã chết" nghe giống hệt
    nhau — im lặng. Có deadline thì ít nhất còn ra được một câu dựng sẵn.
    """
    deadlines = {
        "Gemini VLM": config.GEMINI_TIMEOUT_SECONDS,
        "Gemini phân loại ý định": config.GEMINI_INTENT_TIMEOUT_SECONDS,
        "chờ ActionResult từ điện thoại": config.VISIONCARE_RESULT_TIMEOUT_SECONDS,
        "chờ ActionResult của nhạc": config.VISIONCARE_MUSIC_RESULT_TIMEOUT_SECONDS,
    }
    for name, seconds in deadlines.items():
        assert seconds is not None, f"{name}: không có deadline"
        assert 0 < seconds <= 120, f"{name}: deadline {seconds}s vô lý"


def test_visioncare_http_client_has_timeout() -> None:
    """Client HTTP tới server app phải mang timeout ngay ở chỗ dựng nó.

    Đặt timeout ở từng chỗ gọi thì chỗ gọi thứ N+1 sẽ quên. Đặt ở client là
    chỗ duy nhất không quên được.
    """
    from services import visioncare_client

    source = inspect.getsource(visioncare_client)
    assert "timeout=" in source, "httpx.Client dựng không có timeout"


def test_gemini_config_always_carries_http_options() -> None:
    """MỌI lượt gọi Gemini mang trần thời gian, kể cả nhánh không có tuỳ chọn.

    Nhánh "không search, không đè thinking" từng `return None` — mà đó lại là
    nhánh PHỔ BIẾN NHẤT (`space`/`find`/`money`/`hazard`), tức nhánh bỏ sót
    trần sẽ đau nhất. Ca này khoá lại chỗ đã sửa.
    """
    from models.vlm import client as vlm_client

    source = inspect.getsource(vlm_client._generation_config)
    # Bỏ comment trước khi soi: chính docstring của hàm đó KỂ LẠI rằng nhánh
    # `return None` đã bị gỡ, nên tìm chuỗi thô sẽ khớp vào lời giải thích và
    # ca này đỏ mãi mãi vì một lý do sai.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "return None" not in code
    assert "http_options" in code


def test_hung_external_call_yields_prebuilt_sentence() -> None:
    """Gọi ngoài chậm → PHẢI ra câu trấn an, không phải im lặng hay traceback.

    Người khiếm thị không nhìn thấy màn hình chờ. Im lặng trong lúc server còn
    đang nghĩ nghe **giống hệt** thiết bị đã chết, và phản ứng tự nhiên là bấm
    lại — làm hỏng luôn lượt đang chạy dở.
    """
    from handlers import waiting

    spoken = list(waiting.with_progress_notice(_slow_pieces(), notices=("Chờ chút.",)))
    assert spoken, "chờ lâu mà không ra một chữ nào — đúng cách hỏng tệ nhất"
    assert any(piece.strip() for piece in spoken)
    # Câu cuối vẫn phải là câu trả lời thật, không bị câu trấn an nuốt mất.
    assert "xong rồi." in "".join(spoken)


def _slow_pieces():
    time.sleep(0.05)
    yield "xong rồi."


# ─── G9: trace ─────────────────────────────────────────────────────────────


def test_trace_has_all_stages() -> None:
    turn_trace.begin("glasses-01", "turn-1")
    turn_trace.stage("stt", 1.2)
    turn_trace.stage("intent", 0.008)
    turn_trace.stage("handler", 0.9)
    turn_trace.stage("ttfb", 1.4)
    turn_trace.annotate(intent="chat")
    trace = turn_trace.finish()

    assert trace is not None
    payload = trace.as_dict()
    for key in ("stt_ms", "intent_ms", "handler_ms", "ttfb_ms", "total_ms"):
        assert key in payload, f"trace thiếu {key}"
    assert payload["intent"] == "chat"


def test_trace_keyed_by_turn_id() -> None:
    """Khoá phải là `turn_id` của T01 — cùng khoá với idempotency và barge-in."""
    turn_trace.begin("glasses-01", "turn-abc")
    trace = turn_trace.finish()
    assert trace is not None
    assert trace.as_dict()["turn_id"] == "turn-abc"
    assert trace.as_dict()["device_id"] == "glasses-01"


def test_missing_stage_is_absent_not_zero() -> None:
    """🔴 Chặng không chạy thì KHÔNG có mặt, không phải bằng 0.

    Lượt trả lời bằng câu dựng sẵn không gọi Gemini. Ghi `gemini_ms=0` cho nó
    sẽ kéo p50 của Gemini xuống bằng số lượt dựng sẵn — một bảng số nói dối,
    và nói dối theo hướng "mọi thứ đang nhanh".
    """
    turn_trace.begin("glasses-01", "turn-static")
    turn_trace.stage("ttfb", 0.12)
    trace = turn_trace.finish()
    assert trace is not None
    assert "handler_ms" not in trace.as_dict()
    assert trace.stage_ms("handler") is None


def test_trace_records_pending_transition() -> None:
    turn_trace.begin("glasses-01", "turn-2")
    turn_trace.annotate(pending_before="ask_contact", pending_after=None)
    trace = turn_trace.finish()
    assert trace is not None
    assert trace.as_dict()["pending_before"] == "ask_contact"


def test_tts_worker_inherits_the_request_context() -> None:
    """🔴 Trace G9 mất sạch chặng nếu worker TTS không kế thừa ContextVar.

    `router.resolve_speech()` là generator, và nó được KÉO trong thread worker
    của `tts.synthesize_text_stream()` — nên STT, phân loại ý định và handler
    thật ra chạy ở thread đó, không phải ở luồng request.

    `threading.Thread` không kế thừa `ContextVar`. Đã đo được đúng triệu chứng:
    mọi lượt báo `stt_ms=0 intent_ms=0 handler_ms=0` trong khi `ttfb_ms` vẫn
    đúng (vì `ttfb` ghi ở luồng request). Bảng độ trễ nhìn như thể pipeline
    chạy trong 0 ms — sai theo hướng dễ tin nhất.

    Cùng cơ chế đó cũng giữ đúng `DEVICE_ID_CTX`/`TURN_ID_CTX` của T01.
    """
    from pipeline import tts

    source = inspect.getsource(tts.synthesize_text_stream)
    assert "copy_context" in source, "worker TTS không còn kế thừa Context"


def test_preroll_pump_inherits_the_request_context() -> None:
    """🔴 Cùng lỗi trên, ở lớp thứ HAI — và nó đã lặp lại thật.

    `_StallAwareStream` chen một thread nữa vào giữa luồng request và
    `synthesize_text_stream()`, nên nó mới là thứ ĐẦU TIÊN advance generator
    của TTS. Sửa `pipeline/tts.py` xong mà quên chỗ này thì chỗ mất context
    chỉ **dịch sang đây**, triệu chứng giống hệt (`ttfb_ms` đúng,
    `stt_ms`/`intent_ms`/`handler_ms` bằng 0) — rất dễ tưởng lần sửa trước
    không ăn.

    Đo được hai lần liên tiếp trong cùng một phiên trước khi lần ra.
    """
    import app as app_module

    source = inspect.getsource(app_module._StallAwareStream.__init__)
    assert "copy_context" in source, "bơm preroll không còn kế thừa Context"


def test_trace_crosses_thread_boundary() -> None:
    """Cùng tính chất trên, nhưng kiểm bằng hành vi thật chứ không đọc mã."""
    import contextvars
    import threading

    turn_trace.begin("glasses-01", "turn-thread")

    def worker() -> None:
        turn_trace.stage("stt", 1.5)

    context = contextvars.copy_context()
    thread = threading.Thread(target=context.run, args=(worker,))
    thread.start()
    thread.join()

    trace = turn_trace.finish()
    assert trace is not None
    assert trace.stage_ms("stt") == 1500.0, "chặng ghi từ thread khác bị rơi"


def test_trace_survives_missing_context() -> None:
    """Chặng gọi ngoài `/process` (test đơn vị, bench) không được nổ.

    Một dòng đo độ trễ không bao giờ được là lý do một lượt thất bại.
    """
    turn_trace.stage("stt", 1.0)      # không có trace nào đang mở
    turn_trace.annotate(intent="chat")
    assert turn_trace.finish() is None


def test_trace_log_is_bounded() -> None:
    """Sổ trace không được phình vô hạn qua nhiều ngày chạy."""
    log = turn_trace.TraceLog(capacity=5)
    for index in range(20):
        log.record(turn_trace.TurnTrace(device_id="glasses-01", turn_id=f"t{index}"))
    assert len(log.recent()) == 5
    assert log.recent()[-1].turn_id == "t19"


# ─── G11: tỉ lệ nhả TTS — dòng thứ hai của bảng ────────────────────────────


def test_release_rate_is_recorded_alongside_ttfb() -> None:
    """TTFB đạt mà tỉ lệ nhả dưới 1.30× thì người dùng VẪN không nghe thấy gì.

    Hai dòng đo hai thứ khác nhau và phải cùng xanh, nên phải cùng nằm trong
    một trace — tách ra hai chỗ là bảo đảm sẽ có ngày chỉ nhìn một dòng.
    """
    turn_trace.begin("glasses-01", "turn-3")
    turn_trace.stage("ttfb", 0.8)
    turn_trace.annotate(release_rate=1.42, audio_seconds=6.0)
    trace = turn_trace.finish()
    assert trace is not None
    payload = trace.as_dict()
    assert payload["ttfb_ms"] == 800.0
    assert payload["release_rate"] >= 1.30


def test_release_rate_threshold_is_documented() -> None:
    assert config.AUDIO_MIN_RELEASE_RATE >= 1.30


# ─── G8: KHÔNG earcon phía server ──────────────────────────────────────────


def test_opening_stays_a_short_tone_not_a_spoken_sentence() -> None:
    """🔴 ĐỪNG đổi sang `"voice"`. Đã thử và đã bị bác, 2026-08-24.

    Lý do bác là TRẢI NGHIỆM, không phải kỹ thuật: **người dùng bấm nút liên
    tục cả ngày.** Nghe trọn câu "Đã tiếp nhận yêu cầu" ở đầu MỖI lượt là tra
    tấn — đúng thứ làm người ta bỏ thiết bị. Một tiếng ngắn không lời thì nghe
    cả trăm lần vẫn chịu được.

    Hai lập luận đã dùng để đổi, và vì sao chúng không thắng:
      - "câu nói 1.68 s dài hơn chuông 0.94 s nên lấp được nhiều khoảng chờ
        hơn" — đúng về số, nhưng tối ưu ĐỒNG HỒ chứ không tối ưu người nghe;
      - "G8 cấm earcon phía server" — G8 chặn việc THÊM tiếng báo trùng với
        `cueSent()`; đoạn đệm này còn gánh việc lấp `AUDIO_PREROLL_SECONDS`,
        và người dùng đã chọn nó.

    Muốn đổi thì phải có người dùng THẬT nghe rồi nói là được — không phải một
    bảng số. Ca này tồn tại vì chính tôi đã tự đổi một lần dù `config.py` ghi
    rõ là không được.
    """
    assert config.AUDIO_PREROLL_MODE != "voice", (
        "câu thoại ở đầu MỖI lượt là tra tấn với người dùng liên tục — xem config.py"
    )
    assert config.AUDIO_PREROLL_MODE in {"warm_melodic", "chime"}


def test_earcon_collision_reasoning_is_kept_in_config() -> None:
    """Lý do phải còn trong `config.py`, không chỉ trong lịch sử git.

    "Phát một tiếng báo đã nhận" là ý tưởng ai cũng nghĩ ra, và không ai nghĩ
    ra rằng firmware đã làm rồi — nhanh hơn mọi thứ server làm được. Không ghi
    lại thì phiên sau sẽ thêm earcon lần thứ hai.
    """
    source = inspect.getsource(config)
    assert "cueSent()" in source, "va chạm G8 không còn được ghi trong config.py"
    assert "AUDIO_PREROLL_MODE" in source


def test_no_new_earcon_helpers() -> None:
    """Không thêm bộ sinh tiếng báo MỚI nào phía server ngoài hai cái đã biết.

    Hai cái đang có (`generate_chime_pcm`, `generate_warm_melodic_pcm`) là
    phần đệm chống hụt tiếng, đã ghi ở trên. Cái thứ ba sẽ là earcon thật.
    """
    from pipeline import phrases

    generators = {
        name
        for name in dir(phrases)
        if name.startswith("generate_") and name.endswith("_pcm")
    }
    assert generators == {"generate_chime_pcm", "generate_warm_melodic_pcm"}, (
        f"bộ sinh âm thanh mới phía server: {generators}"
    )


# ─── G1: ngân sách — ngưỡng tuyệt đối, chỉ cho đường KHÔNG gọi ra ngoài ────


@pytest.mark.perf
def test_static_speech_turns_have_zero_tts() -> None:
    """G5: câu cố định phải phát từ audio dựng sẵn, TTS = 0 ms.

    Không đạt thì mọi dòng < 300 ms của bảng G1 đều không thể đạt: chỉ riêng
    một lượt tổng hợp TTS đã vượt.
    """
    from pipeline import tts

    assert hasattr(tts, "_PHRASE_PCM"), "không còn cơ chế dựng sẵn câu cố định"


@pytest.mark.perf
def test_budget_table_covers_every_intent() -> None:
    """Mọi intent có đường nói ra đều phải có một dòng ngân sách.

    Intent không có ngân sách = intent không ai phát hiện được là đã chậm đi.
    """
    missing = sorted(_all_intent_values() - BUDGET_MS.keys())
    assert not missing, f"intent chưa có dòng ngân sách: {missing}"

    # Và chiều ngược lại: một dòng ngân sách cho intent không tồn tại là dòng
    # không ai đo, và nó che mất việc intent thật đã bị đổi tên.
    stale = sorted(BUDGET_MS.keys() - _all_intent_values())
    assert not stale, f"dòng ngân sách trỏ vào intent không có thật: {stale}"


@pytest.mark.perf
def test_emergency_has_the_tightest_budget() -> None:
    """🔴 `emergency_call` phải là dòng chặt nhất bảng, không có ngoại lệ.

    Nguyên tắc xuyên suốt #3 (CONTRACTS.md mục 0): cuộc gọi cấp cứu không đi
    qua bất kỳ bước xác minh nào. Ngân sách của nó nới ra một lần là mở đường
    cho một bước "chỉ kiểm nhanh thôi" nào đó chen vào.
    """
    assert BUDGET_MS["emergency_call"] == min(BUDGET_MS.values())
    assert BUDGET_MS["emergency_call"] <= 300


def test_wait_for_worker_inherits_the_request_context() -> None:
    """🔴 Lần THỨ BA của cùng một lỗi mất Context — và là lần còn sống.

    `router.resolve_speech()` -> `with_progress_notice()` ->
    `handlers/waiting.py::wait_for()` kéo MẢNH ĐẦU của `_resolve()` trên một
    `threading.Thread` TRẦN. Toàn bộ thân `_resolve()` chạy trên thread đó cho
    tới yield đầu tiên — tức `stage("stt")`, `stage("intent")`,
    `stage("handler")` và `annotate(intent=...)` đều gọi ở đó.

    Thread trần không kế thừa `contextvars.Context`, nên `turn_trace.current()`
    trả `None` và cả bốn dòng đo im lặng rơi mất. Triệu chứng đo được trên
    server thật (`GET /internal/traces`): trace CHỈ có `ttfb_ms`/`total_ms`,
    thiếu hẳn `stt_ms`/`intent_ms`/`handler_ms` — chứ không phải bằng 0 như hai
    lần trước, vì lần này `stage()` không tìm thấy trace nào để mà ghi vào.

    Hai test hàng xóm (`test_tts_worker_...`, `test_preroll_pump_...`) đọc mã
    nguồn tìm chữ "copy_context" nên chúng KHÔNG bắt được ca này. Test này đo
    hành vi qua đúng `wait_for()`.
    """
    from handlers import waiting

    turn_trace.begin("glasses-01", "turn-wait")

    def produce() -> str:
        turn_trace.stage("stt", 1.2)
        turn_trace.annotate(intent="chat")
        return "xong"

    result = list(waiting.wait_for(produce, notices=(), opening_seconds=0.0))

    trace = turn_trace.finish()
    assert trace is not None
    assert trace.stage_ms("stt") == 1200.0, (
        "chặng đo trong wait_for() bị rơi — thread trần không kế thừa Context"
    )
    assert trace.as_dict().get("intent") == "chat"
    assert result == [] or "xong" not in result
