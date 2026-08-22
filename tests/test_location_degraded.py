"""T07 — vị trí không được phép câm, và thread nền không được phép chết.

Không cần host thật, không cần app Android: mock thẳng
`visioncare_client.get_device_location`. Xem `docs/tasks/T07-location.md`
mục 4.1 cho danh sách ca gốc.
"""

import logging
import time

import pytest

import config
from handlers import chat
from models import vlm
from services import visioncare_client

IMG = b"fake image"


class _StopLoop(Exception):
    """Sentinel để thoát `chat._location_refresh_loop()` (vòng `while True`)
    từ bên trong `time.sleep` giả, không phải lỗi thật."""


@pytest.fixture(autouse=True)
def clean_location_state():
    chat.reset_location_cache()
    yield
    chat.reset_location_cache()


def _drive_loop(monkeypatch, iterations: int) -> list[float]:
    """Chạy `_location_refresh_loop()` đúng `iterations` vòng rồi thoát.

    `time.sleep` giả ghi lại nhịp chờ mỗi vòng và ném `_StopLoop` ở vòng thứ
    `iterations` — thay cho chờ giây thật hay dựng thread thật.
    """
    calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= iterations:
            raise _StopLoop()

    monkeypatch.setattr(time, "sleep", fake_sleep)
    with pytest.raises(_StopLoop):
        chat._location_refresh_loop()
    return calls


def _capture_prompt(monkeypatch):
    captured = {}

    def fake_generate_stream(prompt, image=None, search=False):
        captured["prompt"] = prompt
        captured["search"] = search
        yield "ok"

    monkeypatch.setattr(vlm, "generate_stream", fake_generate_stream)
    return captured


def test_empty_cache_returns_warning_block():
    """T07/C1 — ca quan trọng nhất của cả task.

    Cache rỗng phải trả một khối cấm bịa tường minh, KHÔNG BAO GIỜ trả "".
    Trả "" thì `_SEARCH_INSTRUCTION` (khi search=True) vẫn giục model tra "địa
    điểm quanh người dùng" trong khi prompt không có người dùng ở đâu — đúng
    kịch bản khiến model tự quy Tân Triều, Đồng Nai thành TP.HCM.
    """
    text = chat._location_text()

    assert text != ""
    assert "không đoán" in text
    assert "kiểm tra định vị" in text


def test_search_instruction_consistent_when_no_location(monkeypatch):
    """Cache rỗng thì prompt KHÔNG được đồng thời giục model tra "địa điểm
    ... quanh người dùng" — đây đúng là kịch bản đã khiến model bịa quán phở."""
    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: None)
    captured = _capture_prompt(monkeypatch)

    list(chat.handle(IMG, "quanh đây có quán ăn nào không"))

    prompt = captured["prompt"]
    assert captured["search"] is True
    assert "địa điểm/quán/cửa hàng cụ thể nào quanh người dùng" not in prompt
    assert "CHƯA lấy được vị trí" in prompt


def test_stale_fix_says_it_is_stale():
    """P9 — fix 5 phút tuổi, quá TTL nhưng chưa quá MAX_FIX_AGE: vẫn dùng
    được, NHƯNG khối prompt phải nói rõ là cũ — người dùng nghe không phân
    biệt được "chưa có vị trí" với "vị trí đã cũ" nếu im lặng chuyển
    thẳng về khối cấm bịa.

    KHÔNG monkeypatch TTL/MAX_FIX_AGE ở đây (khác bản trước bị review bắt
    lỗi): dùng NGUYÊN giá trị mặc định đọc từ `config.py` (TTL=180s dưới
    marker `# === T07 ===`, MAX_FIX_AGE=600s) để chứng minh nhánh giữa của
    `_location_text()` chạy được với cấu hình THẬT SẼ CHẠY trong production,
    không chỉ đúng trong một kịch bản test tự hạ TTL xuống.
    """
    chat._LOCATION_CACHE = (
        "Vị trí hiện tại của người dùng: Chỗ X (toạ độ 1.0, 2.0).\n",
        time.monotonic() - 5 * 60,
    )

    text = chat._location_text()

    assert "Chỗ X" in text
    assert "cũ" in text


def test_p9_window_is_nonempty_with_shipped_defaults():
    """Khoá lại đúng lỗi mà vòng review trước bắt được:
    `CHAT_LOCATION_TTL_SECONDS` và `CHAT_LOCATION_MAX_FIX_AGE_SECONDS` bằng
    nhau (cả hai 600s) làm cửa sổ [TTL, MAX_FIX_AGE) rỗng — tầng giữa
    của P9 đúng logic nhưng KHÔNG BAO GIỜ chạy được trong production.

    Test này không phụ thuộc con số cụ thể nào, chỉ khoá bất biến
    TTL < MAX_FIX_AGE — đổi default sau này mà lỡ đặt lại bằng nhau thì test
    đỏ ngay, không phải chờ review đọc lại config.py.
    """
    assert config.CHAT_LOCATION_TTL_SECONDS < config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS

    # Một điểm giữa cửa sổ THẬT (không phải số monkeypatch) — chứng
    # minh nhánh giữa của `_location_text()` chạy được với đúng cấu
    # hình sẽ chạy.
    age = (config.CHAT_LOCATION_TTL_SECONDS + config.CHAT_LOCATION_MAX_FIX_AGE_SECONDS) / 2
    chat._LOCATION_CACHE = (
        "Vị trí hiện tại của người dùng: Chỗ Y (toạ độ 3.0, 4.0).\n",
        time.monotonic() - age,
    )

    text = chat._location_text()

    assert "Chỗ Y" in text
    assert "cũ" in text


def test_thread_survives_missing_lat(monkeypatch):
    """T07/C2 — host trả thiếu lat/lng (chỉ có address) không được ném KeyError.

    Trước sửa: `result['lat']` nằm ngoài try -> KeyError xuyên qua hàm này,
    xuyên qua loop() (không try/except) -> thread chết im, `_REFRESHER_STARTED`
    vẫn True nên không ai khởi động lại.
    """
    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: {"address": "x"})

    assert chat.refresh_location_once() is False
    # Gọi lại lần nữa vẫn chạy — hàm không bị "hỏng vĩnh viễn" sau lần đầu.
    assert chat.refresh_location_once() is False


def test_loop_survives_any_exception(monkeypatch):
    """T07/C2 — `refresh_location_once` ném BẤT KỲ lỗi gì thì loop() không thoát."""
    def boom(*a, **k):
        raise RuntimeError("bùm bất ngờ")

    monkeypatch.setattr(chat, "refresh_location_once", boom)

    calls = _drive_loop(monkeypatch, iterations=2)

    # Vòng lặp vẫn sống đủ 2 vòng (nếu chết thì `_drive_loop` không bao giờ
    # ném được `_StopLoop`, và test này sẽ tự thất bại ở `pytest.raises`).
    assert len(calls) == 2


def test_backoff_sequence(monkeypatch):
    """T07/C3 — hỏng liên tiếp: 15s -> 30s -> 60s -> giữ 60s. Thành công thì về
    thẳng nhịp bình thường, không dò lại từ đầu."""
    assert chat._next_refresh_interval(0) == config.CHAT_LOCATION_REFRESH_SECONDS
    assert chat._next_refresh_interval(1) == 15.0
    assert chat._next_refresh_interval(2) == 30.0
    assert chat._next_refresh_interval(3) == 60.0
    assert chat._next_refresh_interval(4) == 60.0
    assert chat._next_refresh_interval(100) == 60.0

    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: None)
    calls = _drive_loop(monkeypatch, iterations=5)

    assert calls == [15.0, 30.0, 60.0, 60.0, 60.0]


def test_error_log_after_three_failures(monkeypatch, caplog):
    """T07/C4 — hỏng liên tiếp lần thứ 3 mới `logger.error`, không phải INFO mãi.

    Bằng chứng gốc: 42/42 nhịp hỏng liên tiếp chỉ log INFO giống hệt nhau,
    không ai nhìn ra đó là vĩnh viễn.
    """
    monkeypatch.setattr(visioncare_client, "get_device_location", lambda *a, **k: None)

    with caplog.at_level(logging.INFO, logger="blind_assist"):
        _drive_loop(monkeypatch, iterations=3)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "3 lần liên tiếp" in errors[0].getMessage()

    # Hai lần hỏng đầu KHÔNG được leo thang — chỉ ca thứ 3 trở đi mới ERROR.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="blind_assist"):
        _drive_loop(monkeypatch, iterations=2)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_to_vn_time_str_or_removed():
    """T07/C5 — `to_vn_time_str` từng luôn ném `NameError` (thiếu import
    `timezone`/`timedelta`) rồi bị `except Exception` nuốt câm, trả nguyên
    chuỗi đầu vào. Biến `vn_time` không ai dùng kết quả -> xoá hẳn thay vì vá,
    một hàm luôn ném exception rồi bị nuốt là mìn cho lần sửa sau."""
    assert not hasattr(chat, "to_vn_time_str")
