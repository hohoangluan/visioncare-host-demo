"""T20 — hợp đồng mã lỗi: đối chiếu app <-> server kính (21.7 · P7).

Nguồn quyết định: `docs/tasks/measurements/P7-error-matrix.md` (ma trận hai
chiều, mỗi dòng đã có quyết định (a)/(b)) và `docs/tasks/CONTRACTS.md` mục 5.5.
File này KHÔNG tự suy luận lại ma trận — chỉ khoá các quyết định đã chốt lại,
để một agent khác lỡ tay sửa `handlers/result_speech.py` là có test đỏ ngay.

Nguồn sự thật cho "mã nào app/server app thật sự phát":
`tests/fixtures/app_error_codes.txt` — chép tay, có ngày + commit hash.
"""

from __future__ import annotations

import re
from pathlib import Path

from handlers import result_speech

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "app_error_codes.txt"

# Mã trong `_ERROR_SPEECH` mà KHÔNG có trong fixture (app/app backend chưa
# từng phát) nhưng vẫn GIỮ có chủ đích — mỗi dòng có lý do đã chốt ở CONTRACTS.
# Thêm một mã vào đây bắt buộc phải trỏ tới một quyết định (a)/(b) đã ghi ở
# CONTRACTS mục 5.5 / P7-error-matrix.md, không được thêm tuỳ tiện.
_ORPHAN_KEEP_EXCEPTIONS = {
    # CONTRACTS mục 5.2, T11: không dùng cho Grab/Farefeed hôm nay, giữ cho
    # provider tương lai có OAuth thật.
    "RIDE_ACCOUNT_NOT_CONNECTED",
    # CONTRACTS mục 7 câu hỏi #7: CHƯA QUYẾT (a)/(b) — app hôm nay không kiểm
    # địa điểm nên chưa có nguồn phát thật. Task T20 không được tự chốt thay,
    # nên câu vẫn ở lại `_ERROR_SPEECH` cho tới khi có quyết định.
    "INVALID_DESTINATION",
}

# 7 mã mồ côi mà P7-error-matrix.md mục 1.2 quyết định (b) — XOÁ câu chết.
# Coi đây là test hồi quy: một agent khác vô tình thêm nhầm lại một trong các
# mã này (ví dụ copy nhầm từ git history) phải bị bắt ngay.
_ORPHANS_REMOVED = {
    "NAVIGATION_NOT_FOUND",
    "NAVIGATION_ALREADY_STOPPED",
    "QUOTE_NOT_FOUND",
    "QUOTE_EXPIRED",
    "NO_ACTIVE_PLAYBACK",
    "MUSIC_ACCOUNT_NOT_CONNECTED",
    "SMS_PERMISSION_DENIED",
    # Có nguồn thật nhưng đi bằng HTTP 404 của chính lời gọi POST, không nằm
    # trong `error.code` -> `_ERROR_SPEECH` không bao giờ tra tới. Bắt đúng chỗ
    # là `handlers/action_flow.py` (T20 không đụng file đó).
    "GLASSES_DEVICE_NOT_LINKED",
}


def _load_fixture_codes() -> set[str]:
    """Mọi mã KHÔNG phải comment/blank trong fixture — nguồn phát thật."""
    codes: set[str] = set()
    for raw in _FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert re.fullmatch(r"[A-Z0-9_]+", line), f"dòng lạ trong fixture: {raw!r}"
        codes.add(line)
    return codes


def test_fixture_has_date_and_commit_hash():
    """CONTRACTS mục 5.5: fixture chép tay bắt buộc có ngày + commit hash, nếu
    không thì sau một tuần không ai biết bảng mô tả bản app nào."""
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    assert re.search(r"Ngày đo:\s*\d{4}-\d{2}-\d{2}", text), "thiếu ngày đo"
    assert re.search(r"commit [0-9a-f]{40}", text), "thiếu commit hash (40 hex)"


def test_no_orphan_speech():
    """Mọi mã trong `_ERROR_SPEECH` PHẢI có trong danh sách app/app-backend
    phát thật -- HOẶC nằm trong `_ORPHAN_KEEP_EXCEPTIONS` với lý do đã chốt."""
    app_codes = _load_fixture_codes()
    orphans = set(result_speech._ERROR_SPEECH) - app_codes - _ORPHAN_KEEP_EXCEPTIONS
    assert not orphans, (
        f"mã mồ côi không rõ lý do trong _ERROR_SPEECH: {sorted(orphans)} -- "
        "app/app backend không phát mã này (theo fixture) và nó cũng không có "
        "trong _ORPHAN_KEEP_EXCEPTIONS. Xem P7-error-matrix.md mục 1.2 trước "
        "khi thêm ngoại lệ mới."
    )


def test_removed_orphans_stay_removed():
    """Hồi quy: 7 mã mồ côi + GLASSES_DEVICE_NOT_LINKED đã bị xoá khỏi
    `_ERROR_SPEECH` ở T20 (P7-error-matrix.md mục 1.2) không được quay lại."""
    reintroduced = _ORPHANS_REMOVED & set(result_speech._ERROR_SPEECH)
    assert not reintroduced, (
        f"mã đã bị xoá (quyết định (b)) lại xuất hiện trong _ERROR_SPEECH: "
        f"{sorted(reintroduced)}"
    )


def test_no_unhandled_app_code():
    """Mọi mã app/app-backend phát PHẢI có câu riêng trong `_ERROR_SPEECH`
    HOẶC rơi vào fallback CÓ Ý NGHĨA (`_GENERIC_FAILURE`/`_DEFAULT_POLICY`,
    không phải chuỗi rỗng)."""
    app_codes = _load_fixture_codes()
    for code in sorted(app_codes):
        data = {"request_state": "failed", "error": {"code": code}}
        # Không biết operation thật của từng mã ở đây (một mã có thể dùng cho
        # nhiều operation) -- test với một operation KHÔNG có trong
        # `_GENERIC_FAILURE`, để buộc câu trả lời phải tới từ `_ERROR_SPEECH`
        # hoặc `_DEFAULT_POLICY`, không phải tình cờ trúng generic fallback.
        speech = result_speech.speak_result("__khong_ton_tai__", data)
        assert speech and speech.strip(), f"mã {code} ra câu rỗng"
        has_own_speech = code in result_speech._ERROR_SPEECH
        is_meaningful_fallback = speech == result_speech._DEFAULT_POLICY.speech
        assert has_own_speech or is_meaningful_fallback, (
            f"mã {code} không có câu riêng và cũng không rơi đúng _DEFAULT_POLICY "
            f"-- rơi vào: {speech!r}"
        )


def test_every_code_has_policy():
    """21.7: mỗi mã trong `_ERROR_SPEECH` có `ErrorPolicy` xác định --
    `retryable` là bool tường minh, `reask` là None hoặc tuple (slot, intent)."""
    assert result_speech._ERROR_SPEECH, "bảng rỗng thì test này vô nghĩa"
    for code, speech in result_speech._ERROR_SPEECH.items():
        policy = result_speech._ERROR_POLICY[code]
        assert isinstance(policy, result_speech.ErrorPolicy), code
        assert policy.speech == speech, f"{code}: ErrorPolicy.speech lệch _ERROR_SPEECH"
        assert isinstance(policy.retryable, bool), f"{code}: retryable không phải bool"
        if policy.reask is not None:
            assert policy.retryable, f"{code}: có reask mà retryable=False"
            assert (
                isinstance(policy.reask, tuple)
                and len(policy.reask) == 2
                and all(isinstance(part, str) for part in policy.reask)
            ), f"{code}: reask phải là tuple (slot, intent)"


def test_default_policy_exists():
    """21.7: `_DEFAULT_POLICY` PHẢI tồn tại, an toàn theo mặc định (không tự
    đặt pending khi chưa biết mã lỗi nghĩa là gì), và câu nói được dựng sẵn
    audio (STATIC_SPEECH) vì đây là câu nói ra đúng lúc hệ thống đang hỏng."""
    policy = result_speech._DEFAULT_POLICY
    assert isinstance(policy, result_speech.ErrorPolicy)
    assert policy.retryable is False, "mặc định phải AN TOÀN: không tự hỏi lại"
    assert policy.reask is None
    assert policy.speech.strip(), "câu mặc định không được rỗng"
    assert policy.speech in result_speech.STATIC_SPEECH, (
        "câu _DEFAULT_POLICY phải được dựng sẵn audio (P7-error-matrix.md mục 4.4)"
    )


def test_unknown_code_never_silent():
    """🔴 Nguyên tắc 21.7: mã lỗi BỊA RA, chưa ai từng thấy, vẫn phải ra một
    câu nói được -- KHÔNG được rơi vào im lặng."""
    data = {"request_state": "failed", "error": {"code": "ZZZ_UNKNOWN"}}
    speech = result_speech.speak_result("__operation_khong_ton_tai__", data)
    assert speech == result_speech._DEFAULT_POLICY.speech
    assert speech.strip()

    # Operation CÓ trong _GENERIC_FAILURE thì câu riêng của operation đó phải
    # thắng _DEFAULT_POLICY -- thứ tự tra đã chốt ở CONTRACTS mục 5.5:
    # _ERROR_SPEECH[code] -> _GENERIC_FAILURE[operation] -> _DEFAULT_POLICY.
    data_known_op = {"request_state": "failed", "error": {"code": "ZZZ_UNKNOWN"}}
    speech_known_op = result_speech.speak_result("music_stop", data_known_op)
    assert speech_known_op == result_speech._GENERIC_FAILURE["music_stop"]
    assert speech_known_op != result_speech._DEFAULT_POLICY.speech


def test_missing_error_object_never_silent():
    """`data["error"]` vắng mặt hoàn toàn (không chỉ mã lạ) cũng không được im
    lặng -- `code` rỗng phải trượt hết `_ERROR_SPEECH` rồi rơi đúng fallback."""
    data = {"request_state": "failed"}
    speech = result_speech.speak_result("__operation_khong_ton_tai__", data)
    assert speech == result_speech._DEFAULT_POLICY.speech


def test_call_failed_never_retryable():
    """CONTRACTS mục 0 (ba nguyên tắc xuyên suốt): `emergency_call` không đi
    qua bất kỳ bước xác minh/hỏi lại nào. `CALL_FAILED` dùng chung cho
    `contact_call` VÀ `emergency_call` (mã không phân biệt operation) nên PHẢI
    terminal -- không được đặt `retryable=True` dù ca contact_call một mình có
    thể chấp nhận hỏi lại được."""
    policy = result_speech._ERROR_POLICY["CALL_FAILED"]
    assert policy.retryable is False
    assert policy.reask is None


def test_timeout_wins_over_error_code():
    """`request_state == "timed_out"` phải chặn TRƯỚC khi đọc `error.code`
    (CONTRACTS mục 5.5, thứ tự tra bước 1) -- đây là lý do `REPORT_TIMEOUT`
    không bao giờ cần một dòng trong `_ERROR_SPEECH`."""
    data = {
        "request_state": "timed_out",
        "error": {"code": "CONTACT_NOT_FOUND"},
    }
    assert result_speech.speak_result("contact_call", data) == result_speech._TIMEOUT_MESSAGE


# --- 4.2 (T20-error-contract.md mục 4.2) — CHƯA LÀM, bàn giao cho T06 -------
#
# `test_error_reask_only_for_real_codes` đòi hỏi `_ERROR_REASK` ở
# `handlers/action_flow.py` (T06-slot-policy.md mục D4). T06 CHƯA TỒN TẠI ở
# thời điểm T20 chạy (Đợt 3, sau T20) -- file đó không có bảng này, viết test
# import/tra nó bây giờ sẽ vỡ ở AttributeError chứ không phải một ca nghiệp vụ
# thật. Theo AGENT_RULES mục B3, T20 không được sửa `handlers/action_flow.py`
# hay tạo `handlers/slots.py`, nên test này CHỦ ĐỘNG bỏ trống, không viết
# xfail giả -- T06 sẽ viết test thật khi `_ERROR_REASK` tồn tại.
