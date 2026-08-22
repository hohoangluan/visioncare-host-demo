# PROGRESS — trạng thái 23 task

Chỉ phiên điều phối ghi file này. Agent ghi `reports/<Txx>.md`.

## Baseline (điền ở Task 0 bước 1)

```
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

.venv\Lib\site-packages\fastapi\applications.py:4675
  D:\Study\innostar\Sever_test\.venv\Lib\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)  # ty: ignore[deprecated]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_bang_am_thanh.py::test_chat_follow_up_question_uses_previous_turn
1 failed, 390 passed, 3 warnings in 138.21s (0:02:18)
```

Đã đỏ **từ trước** (không phải do Task 0 gây ra): `tests/test_bang_am_thanh.py::test_chat_follow_up_question_uses_previous_turn`
(391 test được collect: 1 failed + 390 passed).

## Bảng trạng thái

| Task | Đợt | Trạng thái | Agent | Report | Ghi chú |
|---|---|---|---|---|---|
| G10 (T02§2.1) | 0 | ✅ | ae09a01 | reports/T02-G10.md | terminator CÓ tới, giống hệt localhost/tunnel — README firmware sai |
| H0 (T15§H0) | 0 | ✅ | a74b5f9 | reports/T15-H0.md | ngưỡng đề xuất giữ 4-6, PROVISIONAL — chưa xác nhận capture thật |
| P7 (T20§P7) | 0 | ✅ | a1af9e5 | reports/T20-P7.md | 10 orphan/8 mute (task file ghi 9/7) — xem contract-deltas/T20.md |
| T01 | 1 | ✅ | aa8a19c | reports/T01.md | header thật ra dây qua tunnel (verified phần cứng); idempotency reservation-based |
| T03 | 1 | ✅ | aec3f81 | reports/T03.md | generation từ commit đầu; nợ cho T04 (bump tại turn boundary) và T13 (TTL history) |
| T04 | 1 | ✅ | a7fd12b | reports/T04.md | 6 bước đúng thứ tự; barge-in per-device (device_key qua action_flow) |
| T02 (còn lại) | 2 | ✅ | a4a4386 | reports/T02.md | G11 dao động do tải song song lúc đo, cần đo lại riêng |
| T07 | 2 | ✅ | a727a30 | reports/T07.md | P9 TTL/MAX_FIX_AGE tách xong (180s/600s, chưa đo) |
| T15 | 2 | ✅ | a297bab | reports/T15.md | H1/H3/H5 xây xong, CHƯA nối production (nợ T14) |
| T20 (còn lại) | 2 | ✅ | a8ce029 | reports/T20.md | _DEFAULT_POLICY xong |
| T22 | 2 | 🟠 | a32e461 | reports/T22.md | code xong, số đo phần cứng chờ controller |
| T05 | 3 | ✅ | af90284 | reports/T05.md | phát hiện + fix bug router.py điền pending (nhét thô transcript) |
| T06 | 3 | ✅ | a623f26 | reports/T06.md | 6 slot trọn, emergency_number assert module-level |
| T08 | 4 | ⬜ | | | PARTIAL nếu chưa P1/P2 |
| T09 | 4 | ⬜ | | | 🔴 khoá an toàn |
| T10 | 4 | ⬜ | | | |
| T12 | 4 | ⬜ | | | |
| T14 | 4 | ⬜ | | | |
| T16 | 4 | ⬜ | | | |
| T11 | 5 | ⬜ | | | 🔴 PARTIAL, ⛔ Farefeed |
| T13 | 5 | ⬜ | | | |
| T23 | 5 | ⬜ | | | |
| T17 | 6 | ⬜ | | | F2 KHÔNG thi công |
| T18 | 6 | ⬜ | | | |
| T19 | 6 | ⬜ | | | |
| T21 | 7 | ⬜ | | | |

Ký hiệu: ⬜ chưa · 🟡 đang chạy · ✅ DONE · 🟠 PARTIAL · ⛔ BLOCKED

## Câu hỏi 🔴 agent đẩy lên (phiên điều phối gom, hỏi người dùng một lượt/đợt)

| Đợt | Task | Câu hỏi | Đã chốt? |
|---|---|---|---|
