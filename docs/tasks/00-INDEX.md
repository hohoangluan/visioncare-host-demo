# 00-INDEX — bản đồ task

Nguồn: [`SPEC_CAI_THIEN_HOI_THOAI.md`](../../SPEC_CAI_THIEN_HOI_THOAI.md) ·
Ngày lập: 2026-08-22

**Đọc trước khi mở bất kỳ task nào:**
[`CONTRACTS.md`](CONTRACTS.md) — hợp đồng liên repo + quyết định đã chốt
[`RUNBOOK.md`](RUNBOOK.md) — thứ tự thi công + checklist giao cho subagent

---

## Bốn repo

| Vai trò | Đường dẫn | Cổng |
|---|---|---|
| **Server kính** (repo này) | `D:\Study\innostar\Sever_test` | 8000, ra ngoài qua Cloudflare tunnel |
| **Server app** | `D:\Study\innostar\app_demo_backend\apps\backend` | 8001 |
| **App Android** | `D:\Study\innostar\app_demo_backend\apps\android` | Kotlin + Compose, nhận FCM |
| **Firmware** | `D:\Study\innostar\your-eyes-esp32-firmware` | ESP32-S3-CAM (OV2640) |
| Postgres | `docker start app-demo-postgres-1` | |

⚠️ Có **ba** thư mục cùng tên "app". Chỉ `app_demo_backend\apps\android` là app
thật. `innostar\app` là mockup Expo không có lời gọi mạng nào;
`visioncare-workspace\Your-eyes-visioncare-mobile-app` chưa có mã nguồn.

---

## Bảng task

Cột **Repo**: 🔵 server kính · 🟢 server app · 🟡 app Android · 🔴 firmware

| Task | Mã spec | Repo | Trạng thái | Chặn bởi |
|---|---|---|---|---|
| [T01 Định danh thiết bị & lượt](T01-protocol-ids.md) | F1, 27.2 | 🔵🔴 | READY | — |
| [T02 Chunked end & tốc độ nhả TTS](T02-chunked-end-tts-rate.md) | **G10** G11 F8 | 🔵🔴 | READY | — |
| [T03 Phiên & pending](T03-session-pending.md) | B2 B4 B6 B7, 21.2-21.4 | 🔵 | READY | T01 |
| [T04 Router, ưu tiên, ngắt lời](T04-router-bargein.md) | B1, 21.1, G2 G4 | 🔵 | READY | T01 T03 |
| [T05 Intent & schema slot](T05-intent-slots.md) | A1 A2 A3, B3 B5 | 🔵 | READY | T03, T07(A3) |
| [T06 Bảng chính sách slot](T06-slot-policy.md) | D1 D3 D4 D5, G5 | 🔵 | READY | T03, T20(D4) |
| [T07 Vị trí](T07-location.md) | C1-C5, P8 P9 | 🔵🟡 | READY | — |
| [T08 Gọi danh bạ](T08-contact-call.md) | D2 D6-D9, P1 P2 | 🔵🟡 | PARTIAL | T03 T05 T06 |
| [T09 Gọi khẩn cấp](T09-emergency-call.md) | D5, 21.5, P11 | 🔵🟡 | READY | T04 T06 |
| [T10 Chỉ đường](T10-navigation.md) | D1 D3 D4, A3 | 🔵🟡 | PARTIAL | T03 T05 T06 T20 |
| [T11 Đặt xe](T11-ride.md) | R1-R7, P3-P6 | 🔵🟢🟡 | 🔴 PARTIAL | T07 ⛔Farefeed |
| [T12 Nhạc](T12-music.md) | A4 A1, D1 D4 | 🔵 | READY | T03 T05 T06 |
| [T13 Chat & lịch sử](T13-chat-search.md) | B4 E4 G7 | 🔵 | READY | T07 T03 T14 |
| [T14 OCR: ngữ cảnh](T14-ocr-context.md) | E1-E4 | 🔵 | READY | T03 |
| [T15 OCR: chất lượng](T15-ocr-quality.md) | H0-H7 | 🔵🔴 | READY | — |
| [T16 Không gian & vật cản](T16-space-hazard.md) | E5 E6 | 🔵 | READY | T05 |
| [T17 Tách `/frame`](T17-frame-channel.md) | F3 F4 F5, ~~F2~~ | 🔵🔴 | READY | T01 |
| [T18 Downlink SSE](T18-downlink-sse.md) | F6, 27.6 | 🔵🔴 | READY | T01 T22 |
| [T19 Cuộc gọi đến](T19-incoming-call.md) | 21.8, 26.9 | 🔵🟢🟡🔴 | READY | T18 T03 T04 |
| [T20 Hợp đồng mã lỗi](T20-error-contract.md) | P7, 21.7, 26.5 | 🔵🟡 | READY | — |
| [T21 Ngân sách độ trễ](T21-latency-budget.md) | G1 G3 G5 G6 G9 | 🔵 | READY | T02 T22 T17 |
| [T22 Bật lại TLS](T22-firmware-tls.md) | **F9**, 27.3 | 🔴 | READY | — |
| [T23 Quyền & cấu hình](T23-capabilities.md) | P10 P11, 26.7 | 🟡🔵 | READY | — |

**Không có task:** `find_object`, `read_money` — spec mục 7 ghi rõ **ngoài phạm
vi**, hai handler này đang đúng. TTS, ADPCM, STT, benchmark cũng không đụng.

---

## Tra ngược: mã spec → task

| Nhóm | Mã | Task |
|---|---|---|
| **A** trích slot | A1 A2 A3 | T05 · tiêu thụ ở T08 T10 T11 T12 T16 |
| | A4 xoá heuristic nhạc | T12 |
| **B** session | B1 | T04 |
| | B2 B4 B6 B7 | T03 |
| | B3 B5 | T05 |
| **C** vị trí | C1-C5 | T07 |
| **D** slot & danh bạ | D1 D3 D4 D5 | T06 |
| | D2 D6 D7 D8 D9 | T08 |
| **E** ngữ cảnh | E1 E2 E3 | T14 |
| | E4 | T13 |
| | E5 E6 | T16 |
| **F** giao thức | F1 | T01 |
| | ~~F2~~ **huỷ** | T17 (giải thích) |
| | F3 F4 F5 | T17 |
| | F6 | T18 |
| | F7 | T01 (`setNoDelay`) + T22 |
| | F8 | T02 |
| | F9 F10 | T22 |
| **G** độ trễ | G1 G3 G5 G6 G9 | T21 |
| | G2 G4 | T04 (thiết kế ở T03) |
| | G7 | T13 |
| | G8 **đổi nội dung** | T21 |
| | G10 G11 | T02 |
| **H** OCR | H0-H7 | T15 |
| **P** app | P1 P2 | T08 |
| | P3 P4 P5 P6 | T11 |
| | P7 | T20 |
| | P8 P9 | T07 |
| | P10 P11 | T23 |
| **R** đặt xe | R1-R7 | T11 |
| **21.x** | 21.1 | T04 |
| | 21.2 21.3 21.4 | T03 |
| | 21.5 | T09 |
| | 21.6 | T08 |
| | 21.7 | T20 |
| | 21.8 | T19 |
| **25** OCR chất lượng | toàn mục | T15 |
| **26** app | 26.1 26.2 | T08 |
| | 26.3 26.4 | T11 |
| | 26.5 | T20 |
| | 26.6 | T07 |
| | 26.7 26.8 | T23 |
| | 26.9 | T19 |
| **27** firmware | 27.1 27.5 | T17 · T15 |
| | 27.2 27.3 | T22 |
| | 27.4 27.8 | T02 |
| | 27.6 | T18 |
| | 27.7 | T21 |

---

## Tra ngược: file code → task

| File | Task |
|---|---|
| `app.py` | T01 T02 T17 |
| `config.py` | T01 T03 T07 T15 |
| `pipeline/router.py` | **T04** |
| `pipeline/intent.py` | **T05** · T16 |
| `pipeline/phrases.py` | T06 · T11 · T15 |
| `pipeline/image_quality.py` | T15 T17 |
| `handlers/slots.py` **(mới)** | **T06** · T09 |
| `handlers/contact_match.py` **(mới)** | **T08** |
| `handlers/action_flow.py` | **T03** · T06 T11 |
| `handlers/chat.py` | **T07 T13** · T14 |
| `handlers/phone.py` | T08 T09 |
| `handlers/result_speech.py` | T06 T08 **T20** |
| `handlers/music.py` | **T12** |
| `handlers/navigation.py` | **T10** |
| `handlers/ride.py` | **T11** |
| `handlers/ocr.py` | T14 |
| `models/ocr/__init__.py`, `prompts.py` | T14 T15 |
| `models/vlm/client.py` | T15 |
| `handlers/describe_space.py` | T16 |
| `handlers/describe_hazard.py` | T16 (**chỉ comment**) |
| `handlers/find_object.py`, `read_money.py` | **không đụng** |
| `requirements.txt` | T08 (`rapidfuzz`) |

---

## Tra ngược: repo ngoài → task

### App Android (`apps/android`)

| Việc | Task |
|---|---|
| P1 P2 — `contact_list` / `contact_id` | T08 |
| P3 P4 P5 — giá bịa, toạ độ hằng số | T11 |
| P7 — mã lỗi | T20 |
| P8 — `getCurrentLocation()` + `play-services-location` | T07 |
| P10 P11 — capabilities, số khẩn cấp | T23 |
| 26.9 — `TelephonyCallback` | T19 |

### Server app (8001)

| Việc | Task |
|---|---|
| `ride/quote` + `ride/confirm` + Farefeed | T11 |
| Geocode `address → lat/lng` *(chưa chốt ai làm)* | T11 |
| Đường riêng cho event tự phát | T19 |

### Firmware

| Việc | Task |
|---|---|
| F1 headers + `setNoDelay` | T01 |
| ~~F2~~ **KHÔNG thi công** | T17 |
| F9 bật TLS | **T22** |
| F3/F5 `/frame` + phân tầng | T17 |
| F6 kênh SSE | T18 |
| Phát tiếng khi không bấm nút | T19 |
| Sửa tài liệu 1280×720 | T15 |

---

## Trạng thái nghĩa là gì

| | |
|---|---|
| **READY** | mọi thứ cần đã có, làm được ngay khi task chặn xong |
| **PARTIAL** | một phần chạy được, phần còn lại chờ repo khác — **phải ghi rõ phần nào còn hỏng, đừng báo xong** |
| **BLOCKED** | không làm được, có điều kiện mở khoá ghi trong task |
