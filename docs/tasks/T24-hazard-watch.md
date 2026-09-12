# T24 — Cảnh báo vật cản thời gian thực (`hazard_watch`)

| | |
|---|---|
| **Mã spec** | W1–W6 |
| **SPEC gốc** | mục 28 |
| **Repo đụng** | Server kính · **Firmware** |
| **Trạng thái** | 🟠 PARTIAL (2026-08-24) — 4 tầng có code, 26 test xanh, model YOLO đã cài. Xem [`reports/T24.md`](reports/T24.md) |
| **Chặn bởi** | **T18** (kênh downlink) · T17 (chỉ tái dùng `/frame`, đã READY) |
| **Chặn** | — |

> Tính năng **mới**, không phải sửa lỗi. Lật lại quyết định loại bỏ "cảnh báo
> vật cản thời gian thực" đã ghi ở mở đầu Phần II (mục 19) — xem mục 28.0 của
> spec. Không thay thế `hazard` theo lượt (**T16**), chạy song song.

---

## 1. Hiện trạng

Chưa có gì phía server kính lẫn firmware:

| Tầng | Trạng thái |
|---|---|
| Server kính | ❌ không có intent `hazard_watch_*`, không có worker suy luận, không có cờ `hazard_watching` |
| Firmware | ❌ camera chỉ chụp theo nút bấm (T17); không có vòng lặp chụp liên tục; không có tông cảnh báo cục bộ theo mức |

Phụ thuộc trực tiếp **T18** (`GET /events`) — hiện PARTIAL, kẹt phần cứng
(board chưa nạp lại được, xem memory `board-firmware-lags-repo-head`). Không
có kênh downlink thì task này **không khởi động được**.

Tham khảo thiết kế: `github.com/LuanLuKim/OD_module` — YOLO11n ONNX + risk
engine corridor/proximity/approach + state machine hysteresis. Giữ phần suy
luận, đổi phần vận chuyển (không tách microservice, không UDP) và cách phát
cảnh báo (tông cục bộ, không TTS) cho khớp ràng buộc thật của hệ thống này.

---

## 2. Việc phải làm

### W1 — Intent & vòng đời

- Thêm `hazard_watch_start` / `hazard_watch_stop` vào SetFit + Gemini (mục 2).
- `device_state()` thêm `hazard_watching: bool`, độc lập `music_playing` /
  `navigating` (**B7** — đa active-state).
- Barge-in cục bộ (**B1**, `pipeline/router.py`): `tắt cảnh báo|dừng cảnh
  báo|tắt an toàn` → chạy khi `hazard_watching=True`, 0 ms.
- `emergency_call` giữ quyền tuyệt đối như mục 10 — không đổi.

### W2 — Uplink khung hình liên tục

Mở rộng `POST /frame` (T17), **không** giao thức mới:

```
POST /frame
  X-Device-Id       BẮT BUỘC (như cũ)
  X-Stream-Kind     "turn" (mặc định, hành vi cũ) | "hazard"
  X-Turn-Id         bắt buộc khi Stream-Kind=turn; KHÔNG cần khi =hazard
  X-Capture-Ts      nên có
  body: JPEG tầng thấp (F5)
  → 204 (như cũ)
```

Board mở **một kết nối keep-alive**, gọi lại API đã xanh (F3) theo chu kỳ khi
`hazard_watching=True` — không bắt tay TLS lại mỗi khung.

**Vì sao HTTP, không UDP:**

| Tiêu chí | UDP | HTTP lặp lại (chọn) |
|---|---|---|
| JPEG ~20-50 KB > MTU 1472B | phải tự phân mảnh + ráp lại | TCP lo, không cần code mới |
| Qua Cloudflare tunnel | cần cấu hình `cloudflared` riêng | dùng đúng đường HTTPS đang chạy |
| TLS (T22) | phải tự làm bảo mật | có sẵn qua keep-alive |
| Rủi ro firmware | thư viện + logic ráp gói mới | gọi lại API đã có, không giao thức mới |
| Tiền lệ | — | khớp lý do **F2 bị huỷ** — đổi cách gói tin phức tạp trên board đã bị từ chối trước đây |

Khung `Stream-Kind=hazard` lưu **slot riêng, 1 khung mới nhất/thiết bị**, tách
khỏi ring 1-3 khung của lượt hỏi-đáp (T17) — tránh đụng
`test_frame_matched_by_turn_id`. Worker (W4) tự kéo khung mới nhất theo nhịp
nó xử lý được — chiến lược "latest-frame, size=1" gốc của OD_module.

### W3 — Downlink lệnh, mở rộng kênh T18

```jsonc
{ "type": "hazard_watch", "action": "start" | "stop" }
{ "type": "hazard_level", "level": "SAFE" | "LOW" | "MEDIUM" | "HIGH" }
```

`hazard_level` gửi **mỗi khi mức đổi**, không phải mỗi khung hình. Không audio
qua kênh này — board tự sinh tông (W6).

### W4 — Worker suy luận, nhúng process riêng

Process/worker riêng trong server kính (**không** tách microservice port
8002 như OD_module gốc — giữ nguyên tắc một cửa ra ngoài qua Cloudflare
tunnel). Nhận khung qua queue nội bộ, tách khỏi vòng lặp asyncio chính để
không giành CPU với STT/intent ONNX (`pipeline/intent_local.py`).

Giữ nguyên từ OD_module: YOLO11n ONNX (640×640, letterbox, confidence 0.25,
NMS IoU 0.45), CorridorEngine (hành lang trái 20%–phải 80%), ProximityEngine
(area 0.60 + bottom 0.40), ApproachEngine (hồi quy độ dốc diện tích box).

**Đổi**: SAFE/LOW/HIGH (2 tầng) → **SAFE/LOW/MEDIUM/HIGH** (3 tầng) để khớp
tông tăng dần (W6). Ngưỡng enter/exit gốc (0.70/0.55, cooldown 2500 ms) chỉ là
điểm khởi đầu — **phải đo lại** để chia 3 khoảng, giữ cơ chế hysteresis (tăng
mức phát ngay, giảm mức trễ theo cooldown).

### W5 — Firmware: vòng lặp chụp liên tục

Module mới trong `audio_service.cpp`/camera loop, bật bởi `hazard_watch.start`,
tắt bởi `hazard_watch.stop`. Cùng loại rủi ro đã ghi ở **27.6/T18** (board
không có đường chủ động, đo RAM/pin trước khi viết) — không phải giao thức
mạng mới, chỉ vòng lặp gọi lại `/frame`.

### W6 — Firmware: tông cục bộ theo mức

```
SAFE    im lặng
LOW     tít chậm
MEDIUM  tít nhanh hơn, chưa dồn dập
HIGH    liên tục / dồn dập nhất
```

Cùng triết lý **G8** (`cueSent()` trong `audio_cues.cpp`) — tông cục bộ rẻ và
nhanh hơn audio qua mạng. Cần cơ chế né/trộn cục bộ để không chồng lấp lúc
board đang phát TTS câu trả lời khác — tiền lệ kỹ thuật đã có ở chính file đó
(earcon core 1 song song lúc core 0 chờ server).

---

## 3. Ngoài phạm vi

- Không đọc tên loại vật cản bằng lời — để mở, xem câu hỏi mở.
- Không đụng server app 8001.
- Không chốt fps, ngưỡng risk 3 tầng, mức tiêu hao pin/băng thông — đo trên
  board thật.
- Không thay thế `hazard` theo lượt (**T16**) — song song, không loại trừ
  nhau.

---

## 4. Hợp đồng đổi

Ghi vào `CONTRACTS.md` khi thi công:

```
POST /frame     + X-Stream-Kind (mới, mặc định "turn" — không phá đường cũ)
GET  /events    + event hazard_watch, hazard_level (mới)
device_state()  + hazard_watching (mới)
```

---

## 5. Test

### 5.1 Vòng đời — `tests/test_hazard_watch.py` (mới)

```
test_hazard_watch_start_sets_state
test_hazard_watch_coexists_with_music_and_navigation      # B7
test_hazard_watch_stop_via_bargein_regex                   # W1, 0 ms
test_emergency_call_wins_during_hazard_watch                # mục 10 không đổi
```

### 5.2 Uplink — `tests/test_hazard_frame.py` (mới)

```
test_hazard_frame_uses_separate_slot_from_turn_frame        # W2
test_hazard_frame_does_not_require_turn_id
test_turn_frame_contract_unchanged                           # Stream-Kind mặc định "turn"
```

### 5.3 Risk engine — `tests/test_hazard_risk_engine.py` (mới)

```
test_risk_engine_three_tier_hysteresis                       # W4
test_risk_cooldown_prevents_flicker
test_od_worker_does_not_block_stt_pipeline                   # cách ly CPU
```

### 5.4 Downlink — `tests/test_hazard_events.py` (mới)

```
test_hazard_level_event_sent_only_on_change                  # W3
test_no_audio_bytes_sent_for_hazard_level                    # 🔴 khoá kiến trúc
```

### 5.5 Thủ công / đo — firmware

| Kiểm | Cách | Kỳ vọng |
|---|---|---|
| fps thật qua Cloudflare tunnel | đo băng thông ở tầng ảnh thấp | ghi số vào `measurements/T24-fps.md` |
| Pin tiêu hao thêm | so với chỉ `/events` không `hazard_watch` | ghi số |
| Tông không chồng TTS | bật `hazard_watch`, hỏi câu dài | nghe được cả hai, không lẫn |

---

## 6. DoD

```bash
pytest tests/test_hazard_watch.py tests/test_hazard_frame.py \
       tests/test_hazard_risk_engine.py tests/test_hazard_events.py -q
```

- [ ] **T18 xong trước** — không có kênh downlink thì task này không chạy được
- [ ] `hazard_watch_start/stop` chạy qua intent, cùng tồn tại với nhạc/chỉ đường
- [ ] Barge-in tắt 0 ms
- [ ] Khung hazard tách slot, không đụng hợp đồng `X-Turn-Id` cũ
- [ ] Risk engine 3 tầng, hysteresis, không giành CPU với STT
- [ ] `hazard_level` chỉ gửi khi đổi mức, không audio qua downlink
- [ ] fps/pin đo được, có số trong `measurements/`
- [ ] `hazard` theo lượt (T16) không bị đụng

---

## 7. Câu hỏi phải chốt

0. 🔴 **MỚI, và nó lớn hơn mọi câu bên dưới: YOLO11n KHÔNG đủ.**
   Model đã cài và chạy đúng, nhưng nó biết **đúng 80 lớp COCO và không có
   lớp "vật thể chung"**. Cột điện, tường, bậc thềm, cành cây thấp, cửa kính,
   hàng rào — **không cái nào** nằm trong 80 lớp đó, nên hệ báo `SAFE` cho
   một cây cột chắn ngay trước mặt.

   Đo được trên ảnh thật: `ocr_screenshot.png` → 0 vật → `SAFE`;
   `space_room.jpg` → `person 0.92` → `HIGH`. Nó bắt tốt người/xe, mù với hạ
   tầng tĩnh — thứ người khiếm thị hay va vào nhất.

   Hướng đúng: **ước lượng độ sâu** (Depth Anything V2 small ONNX ~25 MB),
   cho khoảng cách theo từng pixel nên không cần danh sách lớp.
   `hazard_risk.Detector` đã là `Protocol` nên cắm vào được mà không đụng
   luật chấm điểm. **Chờ chốt có tải thêm model đó không.**

1. Tên chức năng người dùng gọi (`hazard_watch` là tên nội bộ).
2. fps thật gửi được qua Cloudflare tunnel ở tầng ảnh thấp — chưa đo.
3. Ngưỡng risk cắt 3 tầng LOW/MEDIUM/HIGH — chưa đo trên dữ liệu thật.
4. Pin tiêu hao thêm khi board vừa giữ keep-alive `/frame` vừa nghe `/events`.
5. Có nên nói một từ (loại vật cản) ở mức HIGH lần đầu mỗi cooldown, thay vì
   luôn chỉ-tông? Để mở, không phải yêu cầu ban đầu.
