# E2E trọn luồng: kính giả lập -> VH -> app server -> điện thoại giả lập

`tools/e2e_full.py` dựng cả chuỗi thật và chạy các kịch bản bằng giọng nói tổng hợp (VieNeu -> ADPCM,
phát đúng nhịp thời gian thực như người giữ nút) qua `WS /v2/session`:

```
kính giả (WS /v2/session) -> VH voice server (:18893) -> app server AB (:18001, DELIVERY_TRANSPORT=webhook)
      -> phone_sim (:18002, báo kết quả đúng khuôn app Android) -> AB -> callback VH -> VH đọc kết quả
```

Không đụng app server `:8001` của người dùng. Mọi tiến trình và postgres test do công cụ dựng đều bị tắt khi xong.

## Chạy

```bash
cd VH
# VH cần GPU (CUDA_VISIBLE_DEVICES chọn GPU cho TTS của công cụ; --gpu chọn GPU cho server VH). Chọn GPU còn trống bằng nvidia-smi.
CUDA_VISIBLE_DEVICES=2 ~/.venvs/seevia/bin/python tools/e2e_full.py --gpu 3
CUDA_VISIBLE_DEVICES=2 ~/.venvs/seevia/bin/python tools/e2e_full.py --gpu 3 --only call_mom call_cancel nav
```

Cần: docker (postgres `compose.test.yaml` của AB, cổng 55435, project `vh-e2e-full`), `AB/.venv` (`uv sync --frozen`),
`SeeVia_system/.env` (token công khai, callback, khoá mã hoá; chỉ đọc, không in), `.env` của VH (Clef/Gemma).
Cờ chính: `--only`, `--keep` (giữ stack để soi log trong `results/e2e_full/`), `--scenario` (JSON cho phone_sim),
`--street` (ảnh đường phố cho hazard; mặc định `$E2E_STREET_IMAGE`), `--json-out`, `--app-url` + `--no-phone-sim`
(điện thoại thật, xem `docs/E2E_REAL_PHONE.md`).

VH được khởi động với `VISIONCARE_DEVICE_ID` KHÁC id kính (`e2e-wrong-default`): nếu lệnh làn D nào mất `device_ctx`
(lỗi Task 16 đã sửa ở `pending_action`) thì AB trả `GLASSES_DEVICE_NOT_LINKED` và kịch bản hỏng ngay. Duy nhất một dòng
`ERROR ... GLASSES_DEVICE_NOT_LINKED` trong `results/e2e_full/vh.log` là phép dò vị trí lúc khởi động, đúng như thiết kế.

## Cách đo

| Cột | Mốc |
|---|---|
| nhả nút -> tiếng đầu | từ lúc gửi `turn_end` tới khối `0x02` đầu tiên (lượt đầu của kịch bản, tức câu đọc lại / trả lời) |
| nhả nút -> lệnh ĐT | từ `turn_end` của lượt kích hoạt (lượt "Đúng." nếu server hỏi lại) tới dòng `command` trong `phone_sim_log.jsonl` (cùng máy, cùng đồng hồ). Gồm cả thời gian đọc lại + cửa sổ huỷ làn D. |
| lệnh -> kết quả đọc | từ lúc ĐT `report` tới khối audio đầu tiên sau đó. `-` = người dùng KHÔNG nghe được gì. |
| hỏi lại | server có hỏi "...phải không?" (Gemma dưới `ACTION_MIN_CONFIDENCE` 0,999); kịch bản trả lời "Đúng." rồi đi tiếp |

Kịch bản huỷ: huỷ ngay sau `reply_end` (lệnh chờ còn trong cửa sổ đọc lại), rồi chờ 7 s và đòi phone_sim KHÔNG nhận lệnh nào:
bằng khung `cancel`, bằng lượt mới (`turn_start`), và bằng cách đóng socket. Kịch bản chat đòi 0 lệnh. `alert` kiểm live nav
sống qua lượt chat bằng cách reset chống-làm-phiền (khung trống) rồi cho đường phố lại và đòi hazard mới. OCR được kiểm cả đọc
thẳng ảnh buffer lẫn live qua session (`cam` -> khung 0x04 -> `capture` UXGA -> audio -> `end`).

## Kết quả (2026-10-19, GPU 0, voice-v2-hardening a1e7bbf, AB 393a02a)

| Kịch bản | Kết quả | hỏi lại | nhả nút -> tiếng đầu (ms) | nhả nút -> lệnh ĐT (ms) | lệnh -> kết quả đọc (ms) | ghi chú |
|---|---|---|---|---|---|---|
| call_mom | FAIL | không | 496 | 2205 | - | lệnh đúng (`name`=mẹ, ĐT báo succeeded); kết quả KHÔNG được đọc (B1) |
| call_nam | FAIL | không | 481 | 2137 | - | lệnh đúng, ĐT báo `MULTIPLE_CONTACTS_FOUND`; người dùng không nghe được (B1) |
| call_cancel (khung cancel) | PASS | không | 489 | - | - | ĐT không nhận lệnh nào |
| call_cancel_newturn | PASS | không | 492 | - | - | ĐT không nhận lệnh nào |
| call_cancel_disconnect | PASS | không | 513 | - | - | ĐT không nhận lệnh nào |
| ride (đặt xe -> xác nhận) | FAIL | không | 561 | 2346 | - | lượt 1 không gửi lệnh nào (đúng); lượt 2 gửi `ride_quote`; kết quả/câu hỏi không được đọc (B1, B4) |
| music (âm lượng -> phát -> bấm nút dừng) | FAIL | không | 522 | 2770 | 611 | `music_volume`, `music_play`, `music_stop` đều tới ĐT và succeeded; kết quả `music_play` không được đọc (B1); kết quả dừng đọc sau 611 ms (số đo ở cột này là của bước dừng) |
| nav (dẫn đường -> hazard -> bấm nút dừng) | FAIL | có (trả lời "Đúng.") | 584 | 2945 | 553 | `navigation_start` -> hazard -> `navigation_stop` đều đúng; nhưng sau khi dừng live nav KHÔNG đóng, hazard vẫn chạy (B2) |
| alert (cảnh báo vật cản, lượt chat giữa chừng) | PASS | không | - | - | - | không `end`, không lệnh, hazard mới vẫn tới sau lượt chat |
| emergency | FAIL | không | 485 | 3413 | - | lệnh `emergency_call` đúng, ĐT succeeded; kết quả không được đọc (B1) |
| chat (không sinh lệnh) | PASS | không | 724 | - | - | 0 lệnh |
| ocr_direct (ảnh buffer đạt) | PASS | không | 660 | - | - | đọc thẳng qua session |
| ocr_live (ảnh mờ -> live OCR) | PASS | không | 1105 | - | - | `cam` -> khung 0x04 -> `capture` -> đọc 81 KB audio -> `end` (Task 10 chưa kiểm đường này: nay đã chạy) |

Mọi FAIL đều do lỗi phía VH (dưới đây); phần luồng "kính -> VH -> AB -> điện thoại" và an toàn huỷ đều đúng.

## Lỗi tìm thấy ở VH (chưa sửa, báo lại)

- **B1 (nặng): kết quả của hành động làn D chạy nền không bao giờ được đọc.** `pipeline/final_router.py::_fire_after_readback`
  gọi `phone.run_background(..., deliver=None)` cho `contact_call`, `emergency_call`, `ride_quote/confirm`, `music_play`;
  mỗi câu kết quả bị vứt. Người dùng nghe "Đang gọi cho mẹ." rồi im: không biết cuộc gọi có đổ chuông, danh bạ có hai "Nam"
  (`MULTIPLE_CONTACTS_FOUND`), hay không tìm thấy tên. Chỉ `nav_start` có kênh (`session.outbox` của live) và các làn không-xác-nhận
  (`music_stop`, `music_volume`, bấm nút dừng) nói kết quả trong chính luồng audio của lượt. Giao thức WS hiện không có khung
  server -> kính "đọc câu này" ngoài lượt/ngoài live, nên sửa cần thêm khung (ví dụ `say` + audio) và đường đẩy từ `deliver`.
- **B2: bấm nút để dừng chỉ đường (`pipeline/turn.py::_bypass`) gửi `navigation_stop` cho ĐT nhưng không đóng live nav.** Không có
  khung `end`, cảnh báo vật cản vẫn chạy tiếp (đã xác nhận: reset chống-làm-phiền bằng khung trống, hazard mới vẫn tới). Cách sửa nhỏ:
  gọi `sessions.close_device(device, "nav")` ở nhánh `navigating` của `_bypass` (như `_lane_c` làm với `nav_stop`).
- **B3 (hành vi, cần quyết định): `_bypass` nuốt MỌI lần bấm khi đang phát nhạc / dẫn đường**: "tăng âm lượng" lúc nhạc đang phát
  = dừng nhạc; một câu hỏi chat lúc đang dẫn đường = dừng dẫn đường trên ĐT. Quy tắc "nav live sống qua lượt chat mới" chỉ đúng với
  chế độ chỉ-cảnh-báo (kịch bản `alert`), không đúng khi ĐT đang dẫn đường. Kịch bản `music`/`nav` được viết theo hành vi hiện tại
  (bấm nút = dừng), `volume` chạy trước khi phát nhạc.
- **B4 (nhỏ): lượt "đặt xe" đọc "Đang tìm xe đi X." nhưng chưa gửi gì** (`handlers/ride.py::handle_quote` chỉ nhớ điểm đến; câu hỏi
  "đúng không? Nói xác nhận" bị vứt do B1). Lệnh `ride_quote` chỉ đi ở lượt xác nhận, `ride_confirm` (quote_id) không bao giờ được gửi:
  người dùng xác nhận trong app Grab.
- Ghi nhận một lần (không tái hiện ở lần chạy cuối): `ERROR Task exception was never retrieved ... aclose(): asynchronous generator
  is already running` khi đóng socket giữa lúc câu chat dài còn đang phát.

Quan sát khác: Gemma >= 0,999 chạy thẳng ở hầu hết các lượt lệnh (chỉ lượt dẫn đường phải hỏi lại trong lần chạy cuối); đường hỏi lại ("...phải không?" -> "Đúng.") chạy đúng một lần (nav) và
lệnh vẫn tới ĐT. Độ trễ nhả nút -> lệnh ĐT (2,1-3,4 s) chủ yếu là thời gian đọc lại + cửa sổ huỷ làn D (`readback_delay` +
`ACTION_TTS_LEAD_S`), không phải độ trễ mạng/AB: lệnh từ VH tới ĐT giả mất < 0,1 s.
