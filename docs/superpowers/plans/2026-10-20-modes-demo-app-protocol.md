# Tách chế độ dẫn đường / vật cản, demo-web cho giám khảo, giao thức app — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps dùng checkbox.

**Goal:** (1) Dẫn đường = chỉ gửi lệnh + link Google Maps về điện thoại, người dùng tự chạm mở; tránh vật cản = chế độ
riêng, chỉ kêu khi vật ở gần trong lối đi. (2) demo-web hiện POV kính + cách server xử lý (box vật cản, box OCR, chế độ hiện
tại, lịch sử hội thoại nhiều lượt). (3) Tài liệu giao thức để người dùng clone app mobile về là nối được AB và làm các task.

**Repo:** VH = `SeeVia_system/visioncare-host-demo` (nhánh `voice-v2-hardening`), AB = `SeeVia_system/app-demo-backend`
(nhánh `voice-v2-hardening`; code server ở `server/`, KHÔNG sửa `mobile/`).

**Ràng buộc chung:** như Global Constraints của `2026-10-19-voice-v2-hardening.md` (venv `~/.venvs/seevia`, không cài/gỡ gói,
GPU trống không lùi CPU, commit có `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, không push, không `source .env`).
Chế độ nhanh: 1–3 test/task, chạy toàn bộ test VH (`pytest -q`) trước commit, không giảm số pass hiện có (429 pass/2 skip).

---

### Task N1 (VH): Tách dẫn đường khỏi cảnh báo vật cản

**Files:** `pipeline/intent_early.py` (LANE: `nav_start`,`nav_stop` → `"D"`; `alert_on`,`alert_off` giữ `"C"`),
`pipeline/final_router.py` (`_lane_c` chỉ còn `alert_on`/`alert_off`; `nav_start`/`nav_stop` đi `_lane_d`; bỏ mọi
`_lane_c if intent == "nav_start"`; `nav_stop` KHÔNG đóng live `nav`), `handlers/navigation.py` (câu), `live/hazard.py` +
`config.py` (`HAZARD_MIN_LEVEL`, mặc định 2), `lanes/nav_live.py` (không gửi khung hazard có level < `HAZARD_MIN_LEVEL`),
`pipeline/phrases.py` nếu cần dựng sẵn câu mới. Test `tests/test_modes_split.py` + sửa test cũ nào khẳng định nav_start bật live.

- `nav_start` giữ cổng an toàn (đọc lại + cửa sổ huỷ + hỏi điểm đến) như cũ nhưng **không** `live="nav"`, không `nav_alert_on`.
- Câu ack/kết quả: thay `_START_ACK` = "Đang gửi chỉ đường về điện thoại."; kết quả thành công (`handlers/result_speech.py`
  cho `navigation_start`) = "Đã gửi chỉ đường tới {address} về điện thoại. Mở thông báo để đi bằng Google Maps." (giữ đúng
  nguyên văn; thiếu address thì bỏ " tới {address}").
- Vật cản: `alert_on` bật live nav như cũ (WS), `alert_off` tắt. Mức 1 (vật xa/ngoài lối đi) không gửi khi
  `HAZARD_MIN_LEVEL=2`; mức 2–3 giữ nguyên luật chống làm phiền.
- [ ] Test: `test_nav_start_does_not_start_live`, `test_nav_stop_keeps_obstacle_mode`, `test_level1_not_sent_by_default`.
- [ ] Gold intent: `tools/eval_intent.py` không phải chạy lại (nhãn không đổi, chỉ đổi lane).
- [ ] FAIL → sửa → PASS toàn bộ. Commit.

### Task N2 (AB server): `maps_url` trong lệnh `navigation_start`

**Files:** `server/src/app/adapters/delivery.py` (`_command_data`: khi `action == navigation_start` thêm trường top-level
`maps_url` = `https://www.google.com/maps/dir/?api=1&destination=<urlencode(address hoặc "lat,lng")>&travelmode=walking`),
fixture `server/tests/fixtures/server_payloads/` nếu có mẫu navigation_start, `server/scripts/phone_sim.py` (không đổi hành vi,
chỉ log `maps_url`), test trong file test delivery hiện có. Thêm trường là additive, không đổi trường cũ.
- [ ] Test `test_navigation_start_payload_has_maps_url` (address có dấu tiếng Việt; và lat/lng). Test AB theo `AB/claude.md`
  (PostgreSQL thật qua `compose.test.yaml` nếu test cần DB). Commit.

### Task P1 (AB docs): `docs/MOBILE_APP_PROTOCOL.md` — clone app về là nối được

Đọc nguồn sự thật là CODE (`server/src/app/...`, `contracts/device-api.openapi.yaml`, `mobile/app/src/main/java/com/youreyes/app/`
chỉ để đọc), không chép mù `docs/project-context.md`. Nội dung, tiếng Việt, có ví dụ JSON thật:
1. Bắt đầu nhanh: clone, `local.properties` (các khoá `youreyes.*`), token lấy ở đâu (`SeeVia_system/.env` — chỉ nêu TÊN biến,
   không chép giá trị), URL `https://app.visioncare-host.uk` / `https://api.visioncare-host.uk`.
2. Đăng ký/ghép: user, device, FCM token, ghép kính (BLE provisioning nếu có), xác thực Device API.
3. Nhận lệnh: FCM data-only — mọi trường (`request_id,user_id,device_id,action,params_json,issued_at,deadline_at,expires_at,
   requested_priority`, `maps_url` cho navigation_start), hạn/TTL, xử lý trùng.
4. Bảng từng `action`: params, việc app phải làm, result schema khi succeeded, mã lỗi. **navigation_start mới:** app hiện thông
   báo "Chỉ đường tới {address} — chạm để mở Google Maps" (PendingIntent mở `maps_url`, hoặc `google.navigation:q=...&mode=w`
   nếu có app Maps); báo `succeeded` ngay khi thông báo đã hiện (không chờ người dùng chạm). Ghi rõ đây là thay đổi so với
   hành vi hiện tại của `NavigationActions.kt` (tự mở Maps).
5. Báo kết quả: endpoint report, idempotency, retry (`ReportFlusher`), trạng thái, timeout.
6. Sự kiện điện thoại → server (cuộc gọi đến, vị trí, capabilities).
7. Mục "Gọi điện / nhắn tin với kính" để trống tiêu đề + "(bổ sung khi plan 2026-10-19-glasses-calls-messages xong)".
8. Kiểm thử không cần kính: `server/scripts/phone_sim.py`, transport webhook.
- [ ] Self-check: mọi endpoint/trường trong doc grep ra được trong code. Commit (AB).

### Task D1 (VH): Khung debug cho demo trên `WS /v2/session`

Bật khi `hello` có `"debug": true` (kính thật không gửi → không đổi gì). Lưu cờ trên `DeviceSession`. Mọi khung debug là
JSON text, gửi **không chờ khoá audio** và không chặn đường hazard (lỗi gửi thì bỏ qua). Hợp đồng (D2 dựa vào nguyên văn):

| Khung | Khi nào | Trường |
|---|---|---|
| `{"t":"trace","turn",...}` | sau khi `turn_v2.run` xong, trước `reply` | `transcript:str`, `intent:str\|null`, `lane:str\|null`, `source:str`, `confidence:float\|null`, `params:dict` (rỗng nếu không có), `cues:[str]`, `live:"ocr"\|"nav"\|null`, `timings:{audio_s,upload_s,final_stt_s,intent_s,route_s,release_to_reply_s}` (giá trị có thì gửi), `pending:str\|null` (câu hỏi đang chờ lượt sau, vd "Bạn muốn đi đâu?" / "… phải không?" — lấy từ `phone._PENDING`/`_CONFIRM` của thiết bị) |
| `{"t":"say","turn","text"}` | mỗi đoạn câu nói được đưa vào TTS (cả lượt thường, `result-*`, outbox live, cue đọc bằng TTS) | `text:str` |
| `{"t":"det","w","h","boxes":[{"kind","score","box":[x0,y0,x1,y1],"level"}],"hazard":{"level","dir","kind"}\|null,"sent":bool}` | mỗi khung live nav đã xử lý | box chuẩn hoá 0..1; `level` từng box theo `hazard.level_of`; `sent` = khung hazard có thật sự gửi kính không |
| `{"t":"ocr","w","h","boxes":[[x0,y0,x1,y1]],"cue":str\|null,"capture":bool}` | mỗi khung live OCR | box PIXEL theo `w,h` của ảnh đã giải mã |
| `{"t":"mode","obstacle":bool,"ocr":bool,"navigating":bool,"music":bool,"call":str\|null}` | sau `hello_ok`, và mỗi khi live bắt đầu/kết thúc hoặc `device_state` đổi sau lượt/kết quả | `call` để null (plan 2 sẽ điền) |

Ngoài ra `hello_ok` thêm `"debug": true` khi đã bật. **Files:** `live/device_session.py`, `lanes/nav_live.py`
(`process_frame` trả thêm detections), `live/hazard.py` (`assess` có thể trả level từng box), `lanes/ocr_live.py`, nơi TTS
tiêu thụ câu (tìm chỗ duy nhất text → TTS trong đường WS), `docs/FIRMWARE_ENDPOINTS.md` (mục "Debug (chỉ demo)").
- [ ] Test `tests/test_debug_frames.py`: không có `debug` → không khung debug nào; có `debug` → `trace` + `say` + `mode` cho một
  lượt; `det` có box khi detector giả trả detection. Đo: thêm khung không làm chậm khung hazard (so p50 test hiện có nếu có).
- [ ] FAIL → cài → PASS toàn bộ. Commit.

### Task D2 (VH demo-web): Trang demo cho giám khảo

**Files:** viết lại `demo-web/index.html`, `app.js`, `styles.css`; thêm `demo-web/adpcm.js`; sửa `demo-web/serve.py` (proxy
WebSocket `/api/v2/session` → upstream `/v2/session`: bắt `Upgrade: websocket`, mở TCP tới upstream, chuyển dòng request +
header, rồi bơm byte hai chiều bằng 2 thread); `demo-web/README.md`. Giữ `mock.js`/`wav.js` nếu còn dùng.

Giao thức: dùng `WS /v2/session` như kính, `hello {device:"demo-web", token, debug:true, cue_version, accept}`.
Ghi âm: giữ Space/nút → `turn_start`, ảnh `0x01` JPEG lúc bấm, audio `0x03` = header WAV RIFF PCM16 16 kHz mono (data size
0xFFFFFFFF) rồi các khối PCM16 stream, thả → `turn_end`. Nhận `0x02` ADPCM IMA 16 kHz (khối 256 B, không header — xem
`pipeline/adpcm.py`) → giải mã JS → phát WebAudio liên tục. Khi nhận `cam {size,fps,quality}` gửi khung `0x04` JPEG theo
size/fps đó (qvga 320×240, vga 640×480); `capture {size}` → gửi 1 khung `0x04` cỡ ≥ 1000 px rộng (uxga 1600×1200 hoặc lớn nhất
camera có); `end` → dừng gửi live. `ping` mỗi 20 s.

Bố cục (dark, brand SeeVia: nền Evergreen #07240F tối hơn cho canvas, Cyan #09BBC8 nhấn trên nền tối, Glow #8A80E6 chỉ gradient,
Montserrat 400–700, số đo dùng font mono; logo `../../ui/logo/logo-white.svg` copy vào `demo-web/assets/`; mọi chữ/nền đạt WCAG AA;
icon SVG, không emoji; tôn trọng prefers-reduced-motion):
- Trái (≈60%): **POV kính** — video + canvas phủ. Box vật cản màu theo level (0/1 xám mờ, 2 cam, 3 đỏ) kèm nhãn
  `kind score`; khi `sent` nháy viền khung + mũi tên hướng. Box OCR viền cyan + chip hướng dẫn (`look_left`→"Quay trái",
  `move_closer`→"Lại gần", `hold_still`→"Giữ yên", …) + chớp trắng khi `capture`. Góc: fps khung live, độ trễ khung.
- Thanh **chế độ hiện tại** trên POV: chip Tránh vật cản / Đọc chữ trực tiếp / Chỉ đường (đã gửi điện thoại) / Nhạc / Cuộc gọi,
  sáng theo khung `mode`.
- Phải: **Server xử lý lượt hiện tại** (timeline: Nghe → STT "transcript" → Intent `intent` · lane · source · confidence →
  Hành động/params → Trả lời; ms từ `timings`) và **Lịch sử hội thoại** (bong bóng người dùng = transcript, SeeVia = các `say`
  gom theo turn; tin `result-*` hiện là "Kết quả từ điện thoại"; lượt có `pending` gắn nhãn "Đang chờ trả lời: …" và nối với
  lượt sau bằng đường kẻ để thấy multi-turn). Log vật cản rút gọn (chỉ khung `sent`).
- Dưới: nút giữ-để-nói lớn (≥ 44 px), trạng thái kết nối, nút Cài đặt (server, token, camera trước/sau).
- Giữ chế độ Mô phỏng (không server) chỉ cho luồng bấm-nghe, dán nhãn "Mô phỏng".
- Kiểm thử: `python demo-web/serve.py` + VH chạy local (GPU trống, cổng tạm, tắt sau khi xong), mở bằng trình duyệt headless
  nếu có (playwright/chromium có sẵn thì dùng, KHÔNG cài) hoặc client Python giả lập WS gửi `debug:true` để xác nhận proxy WS
  + khung debug tới. Chụp màn hình nếu có trình duyệt. Commit.
