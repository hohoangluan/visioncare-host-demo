# PROGRESS — trạng thái 25 task

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
| T15 | 2 | ✅ | a297bab | reports/T15.md | H1/H3/H5 đã nối production trong T14 (`c39b8d2`) |
| T20 (còn lại) | 2 | ✅ | a8ce029 | reports/T20.md | _DEFAULT_POLICY xong |
| T22 | 2 | 🟠 | a32e461 | reports/T22.md | code xong, số đo phần cứng chờ controller |
| T05 | 3 | ✅ | af90284 | reports/T05.md | phát hiện + fix bug router.py điền pending (nhét thô transcript) |
| T06 | 3 | ✅ | a623f26 | reports/T06.md | 6 slot trọn, emergency_number assert module-level |
| T08 | 4 | 🟠 | Codex | reports/T08.md | server xong; chờ app P1 `contact_list` + đo ngưỡng danh bạ thật; commit ad03887 |
| T09 | 4 | 🟠 | Codex | reports/T09.md | 15 pass/7 xfail; khóa an toàn xanh, chờ abort + classifier thấp + T21/P11; commit cc508f5 |
| T10 | 4 | 🟠 | Codex | reports/T10.md | pending/readback/ack xong; D4 xfail vì app chưa phát INVALID_DESTINATION; commit 6636028 |
| T12 | 4 | ✅ | Codex | reports/T12.md | slot/pending thay toàn bộ string heuristic; 16 DoD pass; commit `80cedf2` |
| T14 | 4 | ✅ | Codex | reports/T14.md | OCR cache/follow-up text-only + nối H1/H3/H5; 24 DoD pass; commit `c39b8d2` |
| T16 | 4 | ✅ | Codex | reports/T16.md | space focus; hazard logic khóa nguyên; 15 DoD pass; commit `cd0932c` |
| T11 | 5 | 🟠 | Codex | reports/T11.md | server fail-closed; 151 pass/9 xfail; AVD build/install/start xanh; chờ Farefeed/geocode/app contract; commit `11662ac` |
| T13 | 5 | 🟠 | Codex | reports/T13.md | code + 33 DoD/134 regression xanh; chờ đo Gemini/prefix thật; commit `0a18376` |
| T23 | 5 | 🟠 | Codex | reports/T23.md | code 3 lớp xong; 9 DoD/90 regression/Android build+AVD xanh; chờ nạp & manual trên điện thoại thật |
| T17 | 6 | 🟠 | phiên 2026-08-25 | reports/T17.md | **F5 thi công xong + chạy trên board** (`X-Frame-Tier`, VGA mặc định / HD chỉ cho `ocr`); còn nợ DUY NHẤT: ngưỡng blur đo riêng theo tầng |
| T18 | 6 | ✅ | phiên 2026-08-25 | reports/T18.md | **DoD đóng hết**: SSE chạy trên board, tự nối lại sau restart (2.3 s), RAM đã đo → `measurements/F6-ram.md` (khối liền **36 852 B**, trần **2 phiên TLS**) |
| T19 | 6 | 🟠 | Codex | reports/T19.md | server/host/Android code xanh; AVD TelephonyCallback + PhoneLookup xác nhận; SSE nay mang `audio_url`, server có `GET /incoming-call/audio` phát PCM cache theo contact (commit `7758a65`); firmware phía kính (pull audio_url) vẫn chờ COM8 |
| T21 | 7 | 🟠 | phiên 2026-08-24 | reports/T21.md | trace G9 + bảng G1 đo được; **15/16 intent vượt ngân sách**, 11/16 dưới ngưỡng nhả — xem measurements/G1.md |
| T24 | 8 | 🟠 | phiên 2026-08-25 | reports/T24.md | **worker đã viết + nối dây** (trước đó `risk_engine.evaluate()` KHÔNG có lời gọi nào trong mã production — người dùng nghe "đã bật" rồi im vĩnh viễn). Mức về trong thân `POST /frame`, board giữ 1 phiên keep-alive. `hazard` intent giờ BẬT CHẾ ĐỘ CANH thay vì gọi Gemini. Vẫn nợ: 5/8 bắt được, 2/11 báo oan |
| T25 | 8 | ✅ | phiên 2026-08-25 | (task file) | **OTA kéo qua internet nghiệm thu 3 lần** (ota7/8/9) trên board thật. Sửa lỗi hỏng im lặng do RAM liền |
| **Nút khẩn cấp 3 nhịp** | 9 | 🟠 | phiên 2026-08-25 | measurements/T24.md | server 10 test xanh, board kêu đúng; **chưa thấy request tới server** — xem bên dưới |

Ký hiệu: ⬜ chưa · 🟡 đang chạy · ✅ DONE · 🟠 PARTIAL · ⛔ BLOCKED

## 🔴 Ba phát hiện của phiên 2026-08-24 — đọc trước khi lập kế hoạch tiếp

1. **Board nạp lại được, qua OTA.** Ghi chú "board chưa nạp lại được" ở T17/
   T18/T19/T24 **đã hết hiệu lực**. Cổng là **COM10** (không phải COM8), và
   partition phải là **`min_spiffs`** — `huge_app` là *"3MB **No OTA**"*.
   Từ giờ nạp bằng `espota.exe`, không cắm dây. Xem `T25-ota-provisioning.md`.

2. **Bảng ngân sách G1 mâu thuẫn với `AUDIO_PREROLL_SECONDS = 2.0`.**
   Preroll gom 2000 ms trước byte đầu ⟹ mọi dòng ≤ 1200 ms là không thể đạt,
   kể cả khi xử lý mất 0 ms. Đo được: `emergency_call` **4820 ms** so với ngân
   sách 300 ms. Phải chốt bằng người — `reports/T21.md` câu hỏi #1.

3. **G8 đang bị vi phạm.** `AUDIO_PREROLL_MODE="warm_melodic"` nghĩa là server
   phát earcon, trong khi board đã kêu `cueSent()` ở 0 ms → bíp hai lần.
   RUNBOOK mục 7 cấm đúng chuyện này. Chưa tự gỡ vì đoạn nhạc còn gánh việc
   chống hụt tiếng — `reports/T21.md` câu hỏi #2.

## ~~Mạng thử nghiệm đang chặn cổng 443~~ — ĐÃ GIẢI, 2026-08-25

Đổi kính sang mạng `Thanh_Cuong_FI` là hết. Cùng một bản firmware:

| | hotspot `Redmi Note 14` | `Thanh_Cuong_FI` |
|---|---|---|
| bắt tay TLS | **HỎNG**, `mbedtls -1` sau 18337 ms | **OK, 616-911 ms** |

Ghi chú cũ đổ cho RAM/mbedtls của board là **đổ oan** — code không đổi một
dòng nào. Mọi phép đo bị chặn vì lý do này đã mở khoá.

## Đã nghiệm thu TRÊN BOARD THẬT, 2026-08-25

| Việc | Bằng chứng |
|---|---|
| **OTA kéo qua internet** (T25) | `ota7`, `ota8`, `ota9` — mỗi lần `0%→100%`, sha256 khớp, khởi động lại đúng bản. Đây là việc gác lâu nhất của dự án |
| **SSE `/events` phía firmware** (T18) | `[SSE] Duong xuong /events da mo`; nhận được `firmware_update` và chạy đúng |
| Bản `ota3+` lên board | qua espota LAN **và** qua kéo internet |
| Server thấy kính qua tunnel | `/devices` trả `fw_version`, `wifi_ssid`, `online: true` |
| `emergency_call` tới điện thoại | `202 Accepted` sau khi ghép đôi (trước đó `404 GLASSES_DEVICE_NOT_LINKED`) |
| Nút khẩn cấp 3 nhịp — **phía board** | `===== NUT KHAN CAP: 3 NHIP =====` |

🔴 **espota (đẩy qua LAN) hỏng ở 79% trong khi kéo qua internet xong trọn.**
Đường vòng qua Cloudflare giờ đáng tin hơn đường thẳng trong nhà — ngược hẳn
giả định ban đầu.

### 🔴 OTA kéo từng hỏng IM LẶNG — nguyên nhân và cách sửa

Lần đầu board in "Server bao co ban firmware moi" rồi tắt tiếng; server không
nhận request nào. Nhánh `status == 0` trong `otaPullIfAvailable()` **không in
gì cả**, nên "OTA không chạy" nhìn y hệt "OTA chưa tới lượt".

Nguyên nhân: mbedtls cần **~45 KB LIỀN** mỗi phiên; `/events` + phiên giữ sẵn
đã chiếm chỗ nên phiên thứ ba chết ngay ở `connect()`. Sửa: `apiDropWarmSession()`
+ `eventStreamPause()` trước khi kéo, và in kèm RAM khi hỏng:

```
[OTA-PULL] Khong mo duoc phien — DRAM noi con 67912 B,
           khoi lien lon nhat 36852 B (mbedtls can ~45 KB LIEN)
```

36852 < 45000. Chẩn đoán nằm trong log, không phải suy đoán.

## Câu hỏi 🔴 agent đẩy lên (phiên điều phối gom, hỏi người dùng một lượt/đợt)

| Đợt | Task | Câu hỏi | Đã chốt? |
|---|---|---|---|
| 4 | T09 | Endpoint abort; cửa sổ 3 hay 5 giây; danh sách từ khóa recall cao; P11 gộp T23? | Chưa; tạm gộp P11 vào T23 |
| 4 | T10 | Có forward geocode ở app không, và ngưỡng invalid là gì? | Chưa |
