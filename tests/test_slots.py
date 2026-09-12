"""T06 — Bảng chính sách slot (`handlers/slots.py`).

Xem `docs/tasks/T06-slot-policy.md` mục 4.1 cho danh sách ca gốc;
`docs/tasks/CONTRACTS.md` mục 4.2 cho bảng SLOTS nguồn.

Ba test nhóm "emergency" (`test_emergency_number_not_in_slots`,
`test_emergency_never_asks_back`, `test_emergency_never_reads_back`) là KHOÁ
AN TOÀN cho CONTRACTS.md mục 0 nguyên tắc 3 — không phải test tính năng. Đừng
xoá, đừng làm yếu.
"""

import ast
import importlib
import textwrap

import pytest

from handlers import action_flow, phone, slots


@pytest.fixture(autouse=True)
def _clean_pending():
    action_flow.reset_state()
    yield
    action_flow.reset_state()


# ─── D1 — bảng SLOTS khớp CONTRACTS.md mục 4.2 ─────────────────────────────

# Copy tay từ CONTRACTS.md mục 4.2, để một sửa vô tình ở slots.py (đổi câu
# hỏi, đổi readback...) làm test này đỏ thay vì trôi âm thầm.
_CONTRACTS_TABLE = {
    "contact_name": ("Bạn muốn gọi cho ai?", "low_conf", "high", "fill"),
    "destination": ("Bạn muốn đi đâu?", "low_conf", "high", "fill"),
    "ride_destination": ("Bạn muốn đi đâu?", "always", "high", "fill"),
    "song_title": ("Bạn muốn nghe bài hát nào?", "never", "low", "fill"),
    "artist": ("Bạn muốn nghe của ca sĩ nào?", "never", "low", "fill"),
    "volume_direction": ("Bạn muốn tăng hay giảm âm lượng?", "never", "low", "fill"),
}


def test_slots_table_matches_contracts():
    assert set(slots.SLOTS) == set(_CONTRACTS_TABLE)
    for slot, (ask, readback, risk, kind) in _CONTRACTS_TABLE.items():
        spec = slots.SLOTS[slot]
        assert spec.ask == ask, slot
        assert spec.readback == readback, slot
        assert spec.risk == risk, slot
        assert spec.kind == kind, slot


def test_every_slot_has_ask_readback_risk_kind():
    for slot, spec in slots.SLOTS.items():
        assert spec.ask.strip(), slot
        assert spec.readback in ("always", "low_conf", "never"), slot
        assert spec.risk in ("high", "low"), slot
        assert spec.kind in ("fill", "confirm", "select"), slot


def test_destination_and_ride_destination_share_ask_text():
    """CONTRACTS mục 4.2: hai dòng riêng, cùng câu hỏi — khác nhau đúng
    `readback` (quyết định #2 trong bảng "Quyết định đã chốt")."""
    assert slots.SLOTS["destination"].ask == slots.SLOTS["ride_destination"].ask
    assert slots.SLOTS["destination"].readback != slots.SLOTS["ride_destination"].readback


# ─── D3 — ma trận readback ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "slot, confidence, expected",
    [
        ("ride_destination", "high", True),   # always
        ("ride_destination", "low", True),    # always
        ("ride_destination", None, True),     # always
        ("contact_name", "low", True),        # low_conf + low -> đọc lại
        ("contact_name", "high", False),      # low_conf + high -> gửi thẳng
        ("destination", "low", True),
        ("destination", "high", False),
        ("song_title", "low", False),         # never
        ("artist", "low", False),             # never
        ("volume_direction", "low", False),   # never
    ],
)
def test_readback_matrix(slot, confidence, expected):
    assert slots.should_readback(slot, confidence) is expected


def test_readback_unknown_slot_defaults_false():
    assert slots.should_readback("khong_ton_tai", "low") is False


def test_confirm_pending_uses_25s_ttl():
    """D3: pending của readback là `kind='confirm'` -> TTL 25s, KHÔNG phải
    120s (TTL mặc định của `fill`)."""
    import config

    pending = action_flow.set_pending(
        slot="contact_name",
        intent="contact_call",
        known={"contact_name": "Mẹ"},
        question="Bạn muốn gọi cho Mẹ, đúng không?",
        kind="confirm",
    )
    assert pending.kind == "confirm"
    assert pending.ttl == config.PENDING_TTL_CONFIRM_SECONDS
    assert pending.ttl == 25.0


# ─── D5 — khoá an toàn emergency (CONTRACTS mục 0 nguyên tắc 3) ────────────

def test_emergency_number_not_in_slots():
    assert "emergency_number" not in slots.SLOTS


def test_emergency_assert_runs_at_module_level_not_inside_a_function():
    """Chứng minh assert D5 chạy Ở IMPORT TIME, không nằm trong một hàm (nên
    chỉ 'có tác dụng' nếu ai đó nhớ gọi hàm đó) và không nằm trong test.

    Đọc bằng `ast`: assert phải là một statement Ở MỨC MODULE (con trực tiếp
    của `Module.body`), không phải bên trong `FunctionDef`/`AsyncFunctionDef`.
    """
    source = ast.parse(slots.__file__ and open(slots.__file__, encoding="utf-8").read())
    module_level_asserts = [node for node in source.body if isinstance(node, ast.Assert)]
    assert module_level_asserts, "Không tìm thấy assert nào ở mức module trong slots.py"

    found_emergency_assert = False
    for node in module_level_asserts:
        text = ast.dump(node)
        if "emergency_number" in text and "SLOTS" in text:
            found_emergency_assert = True
    assert found_emergency_assert, (
        "assert 'emergency_number not in SLOTS' phải là một statement Ở MỨC "
        "MODULE của handlers/slots.py, không được bọc trong hàm."
    )


def test_emergency_assert_actually_fires_when_slot_is_added():
    """Chứng minh assert này CÓ RĂNG THẬT: nếu ai đó (vô tình copy-paste) thêm
    'emergency_number' vào SLOTS, việc IMPORT module phải crash ngay, không
    phải chờ tới lúc code khác đọc SLOTS ra mới phát hiện.

    Không sửa `handlers/slots.py` thật (đó là tự phá an toàn) — tái tạo chính
    xác đoạn nguồn của nó vào một module tạm, chèn thêm một dòng
    'emergency_number', rồi thử `exec`. Đoạn nguồn TẠM này là bản sao của thứ
    đang chạy thật, không phải một bản viết tay khác đi.
    """
    real_source = open(slots.__file__, encoding="utf-8").read()
    assert 'SLOTS: dict[str, SlotSpec] = {' in real_source, (
        "Số dòng/định dạng SLOTS trong slots.py đã đổi — cập nhật lại test này."
    )
    tampered = real_source.replace(
        'SLOTS: dict[str, SlotSpec] = {',
        'SLOTS: dict[str, SlotSpec] = {\n'
        '    "emergency_number": SlotSpec("So nao?", "always", "high", "confirm"),',
        1,
    )
    assert "emergency_number" in tampered

    namespace: dict = {"__name__": "handlers._slots_tampered_for_test"}
    with pytest.raises(AssertionError, match="emergency_call"):
        exec(compile(tampered, "<tampered slots.py>", "exec"), namespace)


def test_emergency_never_asks_back(monkeypatch):
    """emergency_call thiếu MỌI param -> VẪN gửi lệnh ngay, KHÔNG hỏi lại,
    KHÔNG đặt pending nào."""
    calls = []

    def fake_call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"status": "ok", "data": {"request_id": "req-1"}}

    def fake_status(request_id):
        return {
            "request_state": "succeeded",
            "result": {"contact": "112", "sms_sent": True},
            "error": None,
        }

    monkeypatch.setattr(action_flow, "call_service_api", fake_call)
    monkeypatch.setattr(action_flow, "get_request_status", fake_status)

    out = "".join(phone.handle_emergency(b"", "", {}))

    assert len(calls) == 1, "emergency_call phải gửi lệnh ngay dù thiếu mọi param"
    assert calls[0][0] == "api/v1/service/emergency/call"
    assert action_flow.get_pending() is None, "emergency_call KHÔNG được đặt pending"
    for spec in slots.SLOTS.values():
        assert spec.ask not in out


def test_emergency_never_reads_back(monkeypatch):
    """Ngay cả khi kết quả trả về lỗi (CALL_FAILED — 'gọi khẩn cấp không quay
    số được' theo P7-error-matrix.md mục 1.3), emergency_call vẫn KHÔNG được
    đặt pending hỏi lại/đọc lại chờ xác nhận — nó chỉ được nói một câu báo lỗi
    và dừng lại."""
    calls = []

    def fake_call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"status": "ok", "data": {"request_id": "req-1"}}

    def fake_status(request_id):
        return {"request_state": "error", "result": {}, "error": {"code": "CALL_FAILED"}}

    monkeypatch.setattr(action_flow, "call_service_api", fake_call)
    monkeypatch.setattr(action_flow, "get_request_status", fake_status)

    "".join(phone.handle_emergency(b"", "", {"emergency_number": "112"}))

    assert action_flow.get_pending() is None
    # Chốt chặn tường minh thứ hai (guard theo tên operation trong
    # `_reask_pending_for_error`) — không phụ thuộc việc CALL_FAILED tình cờ
    # không có mặt trong `_ERROR_REASK`.
    assert action_flow._reask_pending_for_error("emergency_call", {
        "request_state": "error", "error": {"code": "CONTACT_NOT_FOUND"},
    }) is None
    assert action_flow.get_pending() is None
    assert slots.should_readback("emergency_number", "low") is False
