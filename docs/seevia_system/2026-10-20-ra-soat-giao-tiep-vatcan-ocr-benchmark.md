# Rà soát: giao tiếp kính ↔ app Android, vật cản, OCR, benchmark AI

Ngày 2026-10-20. Ghi chú để bàn trước khi làm. Chưa sửa code.
VH = `visioncare-host-demo` (server kính), AB = `app-demo-backend` (`server/` + `mobile/`).
Mỗi mục: **hiện trạng** (đã đọc code) → **vấn đề** → **đề xuất**. Mục đánh dấu ❓ là chỗ cần bạn chốt.

---

## 0. Tóm tắt một màn hình

| Phần | Tình trạng | Việc lớn nhất còn thiếu |
|---|---|---|
| Lệnh kính → điện thoại (FCM, mục 3–5 hợp đồng) | Chạy được, có chống trùng + retry report | Hàng đợi một luồng: khẩn cấp có thể chờ sau lệnh 45 s; không kiểm `expires_at`; retry report chỉ chạy khi có lệnh mới |
| Gọi/nhắn qua internet (mục 7 hợp đồng) | **Server xong, app CHƯA có dòng code nào** | FCM `type=call_incoming/...` bị app bỏ qua → người thân không nhận được cuộc gọi |
| `navigation_start` kiểu mới (mục 4.1) | Hợp đồng viết rồi, app chưa làm | App vẫn tự mở Maps từ nền (hay bị Android chặn) |
| Nhận diện vật cản | YOLO11n COCO + luật diện tích | Thiếu vật cản đặc thù vỉa hè VN, không có khoảng cách/TTC, **không có benchmark** |
| OCR | Gemma đọc ảnh + PP-OCRv4 det căn khung | Không có lớp kiểm số ("không bịa số" mới là lời hứa trong prompt), **benchmark chỉ 11 ảnh** |
| Benchmark | Có: STT, intent, độ trễ, tải | Thiếu: vật cản, OCR (VinText chưa chạy), tiền, tìm đồ, mô tả cảnh, chất lượng cuộc gọi, độ tin cậy giao lệnh |

Thứ tự đề xuất: **A (giao tiếp) → C (benchmark trước) → B1 vật cản → B2 OCR**. Lý do: A là chỗ đang hỏng thật;
còn vật cản/OCR thì phải có bàn đo trước mới biết sửa có tốt lên không (đúng nguyên tắc "chỉ đổi khi đo ra tốt hơn").

---

## A. Giao tiếp kính ↔ app Android

### A1. Hiện trạng luồng lệnh (đã đúng phần lớn)

`FcmPushReceiver` → `CommandExecutionService` (foreground `shortService`, executor 1 luồng) → `ReportFlusher.flush` →
`CommandDispatcher` → `ActionRegistry` → lưu report SQLite → `POST /api/v1/device/report`.
Có: chống chạy trùng theo `request_id`, report lưu `PENDING` trước khi gửi, 8 lần thử, mã lỗi rõ cho 13 action.

### A2. Lỗi / rủi ro tìm thấy

| # | Vấn đề | Chỗ | Hậu quả |
|---|---|---|---|
| A2.1 | Không có code gọi/nhắn (mục 7): receiver chỉ hiểu lệnh có `request_id`, mọi FCM `type=call_incoming / call_answered / call_ended / message_in` bị log "Ignoring" rồi bỏ | `command/FcmPushReceiver.kt:38` | Kính gọi người thân → không đổ chuông; tin nhắn kính gửi không hiện |
| A2.2 | Executor **một luồng**, các handler chặn tới 45 s (`contact_call`, `music_play`) | `CommandExecutionService.kt`, `CallActions.kt:38` | `emergency_call` hoặc `call_answer` (hạn 20 s) xếp sau → hết hạn trước khi chạy |
| A2.3 | App không đọc `expires_at` | `CommandDispatcher.kt:21` (`fromData` chỉ lấy 5 khoá) | FCM tới trễ vẫn chạy lệnh đã hết hạn: ví dụ `call_answer` cũ nhấc nhầm cuộc gọi mới |
| A2.4 | `shortService` (Android 14+) giới hạn ~3 phút, không override `onTimeout` | `CommandExecutionService.kt` | Hàng đợi dài → hệ thống kill/ANR giữa lệnh |
| A2.5 | Retry report chỉ chạy "trước lệnh kế tiếp", không có WorkManager/hẹn giờ | `ReportFlusher.kt` | Report rớt mạng nằm chờ tới lệnh sau → server đã `timed_out`, kính báo lỗi dù điện thoại làm xong |
| A2.6 | Report bị server từ chối vĩnh viễn (409/404) vẫn thử đủ 8 lần | `ReportFlusher.kt` | Tốn lượt, che lỗi thật trong log |
| A2.7 | `navigation_start` chưa theo mục 4.1 (không đọc `maps_url`, vẫn tự mở Maps) | `actions/NavigationActions.kt:27` | Người dùng không thấy gì; kính vẫn nói "đã mở chỉ đường" |
| A2.8 | `emergency_call` đường SIM chỉ một lượt, không có chu kỳ; `contact_id` bị bỏ qua | `CallActions.kt:185`, ghi chú mục 4 | Chấp nhận được (là dự phòng), nhưng nên ghi rõ |

### A3. Đề xuất

**A3.1 Hoàn thiện mục 7 trong app (việc lớn nhất)** — đã có spec `AB/docs/superpowers/specs/2026-10-20-seevia-mobile-app-design.md`
(chưa duyệt). Phần tối thiểu để kính ↔ người thân chạy được:

1. Receiver tách hai đường: có `type` → `CallMessageRouter`; có `request_id` → đường lệnh cũ. (Không đụng đường lệnh.)
2. Cuộc gọi đến: thông báo `CATEGORY_CALL` + full-screen intent, kênh riêng âm chuông to; emergency dùng kênh bỏ qua "Không làm phiền".
   Dùng `ConnectionService`/`TelecomManager` self-managed (Android coi như cuộc gọi thật → đổ chuông khi khoá máy, tai nghe bluetooth nghe/cúp được)
   ❓ hay chỉ notification full-screen (đơn giản hơn, nhưng dễ bị OEM Xiaomi/Oppo chặn).
3. Màn hình cuộc gọi theo máy trạng thái 7.7; một `CallAudioEngine`: `AudioRecord(VOICE_COMMUNICATION)` + AEC/NS + jitter buffer 60 ms phía nhận,
   khung 640 B/20 ms qua OkHttp WebSocket. Foreground service loại `phoneCall|microphone`.
4. Đồng bộ khi FCM trễ: mở màn hình nào cũng `GET /calls/{id}` trước (TTL FCM 30 s).
5. Nhắn tin: hội thoại 1-1, `request_id` UUID sinh trước khi gửi (gửi lại an toàn), hiện "đã nghe" theo `read_at`.

**A3.2 Sửa đường lệnh (nhỏ, nên làm cùng):**

- Hai làn: **làn ưu tiên** cho `emergency_call`, `call_answer`, `call_reject`, `location_get`, `capabilities_get` (ngắn); **làn chậm** cho phần còn lại.
  Hoặc đơn giản hơn: executor nhiều luồng + khoá theo nhóm tài nguyên (nhạc / cuộc gọi). ❓
- Đọc `expires_at`; quá hạn thì không chạy, báo `failed / COMMAND_EXPIRED` (server sẽ trả 409 → bỏ, không sao).
- `ReportFlusher` chạy cả bằng WorkManager (ràng buộc có mạng, backoff) và khi mạng trở lại; 4xx vĩnh viễn → `ABANDONED` ngay.
- Override `onTimeout` → kết thúc lệnh đang chạy bằng `failed` thay vì để hệ thống giết.
- Làm `navigation_start` theo mục 4.1 (đã đặc tả đủ).

**A3.3 UX phía app (cho người thân / chủ kính, người sáng mắt):**

- Màn "Kính của tôi" hiện **một dòng trạng thái thật**: kính online/offline, pin, lần cuối thấy, FCM token còn sống — để biết vì sao lệnh không tới.
- Nhật ký lệnh (đã có `ActivityLog`) hiện: lệnh nào, mất bao lâu, kết quả, mã lỗi tiếng Việt dễ hiểu + gợi ý sửa (ví dụ `CALL_PERMISSION_DENIED` → nút "Cấp quyền").
- Màn kiểm tra quyền một chỗ (đã có `capabilities_get`): đỏ/xanh, bấm là mở đúng trang cài đặt; nhắc tắt tối ưu pin theo hãng máy.
- Debug (spec mục 6): gọi thử echo, đo RTT, sao chép log đã che token.

**A3.4 UX phía kính (người khiếm thị nghe):**

- Mọi lệnh tới điện thoại có **phản hồi ngay** (đã có earcon/câu chờ) và **phản hồi kết quả thật**; lệnh hết hạn phải nói rõ "Điện thoại không trả lời"
  thay vì im lặng. ❓ Cần kiểm lại VH có nói câu này với `timed_out` chưa — đề xuất đưa vào bàn đo E2E.

---

## B1. Thuật toán nhận diện vật cản (`VH/live/hazard.py`, `lanes/nav_live.py`)

### Hiện trạng

YOLO11n COCO ONNX, ảnh 320, QVGA ~8 fps từ kính, ngưỡng 0,35. 14 lớp COCO (người, xe, ghế, ghế đá, cột nước...).
Mức 0–3 theo **diện tích hộp + vị trí giữa khung + "đang tới gần" (diện tích tăng >15 % so với khung trước, khoá theo (lớp, 1/3 khung))**.
`AntiAnnoy`: giữ 2 khung mới gửi (mức 3 gửi ngay), nhắc lại mỗi 2 s, mức 1 tối đa 1 lần/5 s. Kính phát bíp/câu từ flash.

### Điểm yếu

1. **Thiếu vật cản thật của vỉa hè VN:** bậc thềm/cầu thang, mép vỉa hè, ổ gà/hố ga, cột điện/biển báo, xe máy đậu, gánh hàng, bàn ghế quán,
   **vật ngang đầu** (mái hiên, cành cây, gương xe tải) — COCO không có hoặc không nhận tốt.
2. **Diện tích hộp ≠ khoảng cách:** người ở xa nhưng to vs. cột mảnh ở gần. Cạnh dưới hộp (điểm chạm đất) cho khoảng cách tốt hơn khi camera cố định độ cao.
3. **"Đang tới gần" nhiễu:** so khung liền nhau ở 8 fps, đầu người lắc → diện tích dao động >15 % thường xuyên; vật đi qua ranh 1/3 khung là mất lịch sử.
4. **Mức 3 gửi chỉ với 1 khung** → một khung nhận nhầm là bíp khẩn; streak đòi đúng *cùng mức* nên 2↔3 dao động làm reset.
5. Hướng chỉ trái/giữa/phải; không bù góc nghiêng đầu.

### Đề xuất (xếp theo chi phí tăng dần; mỗi bước phải thắng trên bàn đo C1 mới giữ)

| # | Ý tưởng | Chi phí | Kỳ vọng |
|---|---|---|---|
| B1.1 | **Tracker IoU nhẹ** (kiểu SORT/ByteTrack, không cần re-ID) thay khoá (lớp, 1/3) | thấp, CPU <1 ms | "tới gần" ổn định, không mất lịch sử khi vật đổi vùng |
| B1.2 | **Thời gian tới va chạm (TTC)** từ tốc độ giãn hộp đã làm mượt EMA: TTC ≈ Δt / (s−1) với s = tỉ lệ chiều cao hộp | thấp | Mức theo "còn mấy giây" thay vì diện tích — đúng thứ người đi bộ cần |
| B1.3 | Khoảng cách từ **cạnh dưới hộp** (hình học mặt đất, hiệu chỉnh 1 lần theo độ cao/góc kính) | thấp | Phân biệt xa-to / gần-nhỏ |
| B1.4 | Mức có **trễ (hysteresis)** + mức 3 cần 2/3 khung gần nhất thay vì 1 khung | thấp | Bớt bíp nhầm mà không chậm đáng kể (8 fps → +125 ms) ❓ đánh đổi |
| B1.5 | **Ước lượng độ sâu đơn mắt** (Depth Anything V2-Small ONNX, ~25M) chạy song song: lưới "đường đi phía trước" có gì gần hơn X m không, *bất kể lớp gì* | trung bình, cần đo GPU | Bắt vật cản không có trong COCO (cột, tường kính, xe đẩy) |
| B1.6 | **Fine-tune YOLO11n/s** trên dữ liệu vỉa hè (thêm lớp: cột, bậc thềm, hố ga, vật ngang đầu, xe máy đậu) | cao (cần nhãn) | Đúng domain nhất; cần dữ liệu (xem C1) |
| B1.7 | VLM (Gemini/Gemma) chỉ cho câu hỏi "phía trước có gì" theo yêu cầu, không ở đường nóng | đã có (`describe_hazard`) | giữ nguyên |

Ràng buộc giữ nguyên: đường nóng khung → bíp ≤ 300 ms; chỉ khung mới nhất; cảnh báo chen trước mọi tiếng nói khác (đã có `_HazardClock`).

---

## B2. OCR (`VH/lanes/ocr_live.py`, `models/ocr/prompts.py`, `docs/ARCHITECTURE_OCR.md`)

### Hiện trạng

Thiết kế đã tốt (3 chế độ đọc nhanh / đọc kỹ / hỏi về chữ, căn khung bằng bíp, trần thời gian, "đọc lại" 5 phút).
Đọc chữ = **Gemma 4 26B** (`llm.uit.edu.vn`) nhận ảnh 1600 px, temperature 0. Căn khung = PP-OCRv4 det (ONNX) đo chiều cao dòng.

### Điểm yếu

1. **"Không bao giờ bịa số" chỉ nằm trong prompt.** VLM có thể đọc "500" thành "50.000", HSD sai ngày — đúng loại lỗi nguy hiểm nhất (thuốc, tiền).
2. Phụ thuộc hoàn toàn một LLM từ xa: mạng chậm/LLM bận → không có đường lùi đọc được gì.
3. Chưa có thứ tự ưu tiên thật (HSD trước, tổng tiền trước) ngoài lời dặn prompt.
4. Đánh giá chỉ 11 ảnh nội bộ; VinText đã xác định nhưng chưa chạy.

### Đề xuất

| # | Ý tưởng | Kỳ vọng |
|---|---|---|
| B2.1 | **Kiểm chéo số bằng OCR thứ hai** (PP-OCRv4/v5 rec tiếng Việt, hoặc VietOCR) trên các vùng det đã có: số/ngày trong câu VLM phải xuất hiện trong kết quả rec; lệch thì đọc kèm "không chắc" hoặc đọc theo rec | Biến lời hứa "không bịa số" thành kiểm được; đo bằng *tỉ lệ số sai được nói ra* (C2) |
| B2.2 | **Bộ trích trường có cấu trúc** cho 3 loại quan trọng: HSD/NSX (regex ngày VN), tiền/tổng (regex số + "đ/VND"), liều thuốc; đọc trường này **trước** | Đúng yêu cầu "đọc thứ quan trọng trước" một cách xác định |
| B2.3 | **Đường lùi cục bộ:** LLM quá X s → đọc kết quả det+rec cục bộ (thô, nhưng có tiếng) | Không im lặng khi mạng xấu |
| B2.4 | Câu đầu tiên ra sớm: stream câu đầu ngay khi có (đã stream; đo lại TTFA) | giữ ≤ 2 s |
| B2.5 | Tiền: ngoài VLM, thêm bộ phân loại mệnh giá nhỏ (12 lớp VND, cả mặt trước/sau) làm phiếu thứ hai; hai bên lệch → "chụp lại" | Đọc tiền là chỗ sai = mất tiền |

---

## C. Benchmark còn thiếu

Nguyên tắc chung (từ bài học các dự án trước): mỗi bàn đo có **tập cố định + script một lệnh + số khoảng tin cậy (bootstrap)**,
so A/B **ghép đôi trên cùng mẫu**, chỉ đổi một biến, ghi kết quả vào `docs/benchmarks/*.md`. Báo cả **độ trễ p50/p90** cạnh độ chính xác.

| # | Task | Hiện có | Đề xuất bàn đo | Dữ liệu | Metric chính |
|---|---|---|---|---|---|
| C1 | **Vật cản** | 1 ảnh fixture | (a) mức khung: mAP@0.5 theo lớp liên quan; (b) **mức sự kiện trên video**: có cảnh báo đúng trước va chạm ≥ 1,5 s không, số bíp nhầm/phút; (c) độ trễ khung→bíp | Video đi bộ tự quay bằng kính/điện thoại ở vỉa hè VN (đề xuất 30–60 clip × 20 s, gán nhãn thời điểm "nguy hiểm" thủ công) + tập công khai bổ sung: **Sidewalk/“SideGuide”** (Hàn Quốc, vỉa hè), **Obstacle-Dataset/OD for VI** ❓ cần tìm thêm | recall cảnh báo kịp thời, false alarm/phút, lead time p50 |
| C2 | **OCR** | 11 ảnh | VinText test (≈500 ảnh) + **bộ VN-đời-thường tự chụp bằng kính** (HSD, hộp thuốc, hoá đơn, biển số phòng, màn LED) ~150 ảnh | VinText (AGPL, chỉ dùng đánh giá), ảnh tự chụp | CER/WER; **tỉ lệ con số sai được nói ra** (quan trọng nhất); tỉ lệ từ chối đúng/sai; TTFA |
| C3 | **Đọc tiền** | không | 12 mệnh giá × mặt × điều kiện (tối, nghiêng, gấp, nhiều tờ) ~240 ảnh tự chụp | tự chụp | accuracy mệnh giá, tỉ lệ "chụp lại" vs. đọc sai |
| C4 | **Tìm đồ / mô tả không gian** | VizWiz 12 ảnh, LLM tự chấm | 100 ảnh trong nhà/ngoài đường có nhãn vật + hướng (giờ) + khoảng cách thô; chấm bằng quy tắc (đúng hướng ±1 giờ, đúng vật) thay vì LLM chấm | tự chụp + VizWiz-VQA phần "object" | đúng hướng, đúng vật, tỉ lệ bịa vật không có |
| C5 | **Chất lượng cuộc gọi** | đo độ trễ local | Script phát tiếng chuẩn qua `relative_sim` ↔ kính giả lập, qua Cloudflare, có netem giả mất gói 0/2/5 % | tiếng đọc chuẩn | trễ một chiều p50/p90, tỉ lệ khung bỏ, underrun jitter buffer, (tuỳ chọn) PESQ/POLQA-lite |
| C6 | **Độ tin cậy giao lệnh** | test đơn vị | Chạy N=200 lệnh mỗi action qua `phone_sim` + một máy thật: FCM→handler, handler→report, tỉ lệ `timed_out`, khi máy khoá/Doze | máy thật | độ trễ giao p50/p90, tỉ lệ thành công, tỉ lệ report mồ côi |
| C7 | TTS | không | Đã xác định PhoAudiobook/VLSP; cần người nghe ❓ để sau | — | MOS |

STT, intent, độ trễ end-to-end, tải: **đã có**, giữ nguyên.

---

## Đã chốt

- 2026-10-20: đồng ý thứ tự A → C → B1 → B2. **Đợt hiện tại chỉ làm A (app giao tiếp)**; B/C sửa dần sau.
- Xong task nào ghi vào mục "Nhật ký đã làm" bên dưới.
- **Nguyên tắc:** phản hồi qua kính (người khiếm thị) = âm thanh; chữ/thông báo chỉ cho người dùng điện thoại.
- Đợt 1 = giao tiếp tối thiểu, spec đã duyệt: `AB/docs/superpowers/specs/2026-10-20-app-giao-tiep-toi-thieu-design.md`
  (thêm OkHttp + WorkManager: đã đồng ý).

## Việc ghi nhận để bàn sau

- VH đang nói với người khiếm thị "kiểm tra/bấm thông báo trên điện thoại" (`handlers/result_speech.py`: `_TIMEOUT_MESSAGE`,
  câu lỗi `navigation_start`) — trái nguyên tắc âm thanh. Cần nghĩ lại luồng chỉ đường cho người khiếm thị (Maps trên điện thoại họ không nhìn được).

## Nhật ký đã làm

- 2026-10-20 — Rà soát + spec đợt 1 (builder check xong, người dùng duyệt). Chưa sửa code.
- 2026-10-20 — Kế hoạch đợt 1 (8 task): `AB/docs/superpowers/plans/2026-10-20-app-giao-tiep-toi-thieu.md`. Người dùng duyệt; cho chạy nền + dùng Codex (gpt-6-luna, file chạy trong extension VS Code `openai.chatgpt-*/bin/linux-x86_64/codex`).
- 2026-10-20 — **Task 1 xong.** Nhánh `app-giao-tiep` ở AB và VH. Build nền lần đầu trên máy này OK không cần sửa môi trường
  (`bash ./gradlew` vì `gradlew` mất quyền chạy): 68 test JVM pass, APK debug 24 MB. Thêm OkHttp 4.12.0 + WorkManager 2.10.1 (AB `4ac427d`), build lại xanh.
- 2026-10-20 — **VH: câu nói `COMMAND_EXPIRED`** (VH `ece963b`) + test. VH pytest: test `test_ocr_live_does_not_kill_nav_alerts_for_good` chập chờn khi máy bận
  (pass 4/4 khi chạy riêng, cả trên code gốc) — không do thay đổi này. Chạy lại toàn bộ: **516 pass + 2 skip**.
- 2026-10-20 — **Task 4+5 xong** (subagent Sonnet, nhánh tạm `app-giao-tiep-calls`: `019a05c`, `5ba574e`; chưa gộp). Client API phiên
  (care/calls/messages, 401 → Unauthorized), router FCM 4 `type`, máy trạng thái cuộc gọi (FCM trùng/trễ/đảo, Nghe khi đã hết chuông, 401),
  jitter buffer 60 ms, WebSocket âm thanh, engine thu/phát AEC/NS. 129 test JVM pass (61 test mới). Token/nội dung tin bị loại khỏi `toString()`.
- 2026-10-20 — **Task 2+3 xong** (Codex gpt-6-luna; lượt 1 hỏng vì sandbox chặn socket → chạy lại với `sandbox_workspace_write.network_access=true`;
  sandbox để `.git` chỉ đọc nên controller tự review + commit `d17b9f6`). Kiểm `expires_at` → `COMMAND_EXPIRED`; hai làn FAST/SLOW;
  report 400/404/409/422 bỏ ngay, còn lại retry bằng WorkManager khi có mạng; `onTimeout`; SQLite có khoá; `navigation_start` = thông báo
  "chạm để mở Google Maps". Controller sửa 1 lỗi Codex: `stopSelf()` từ luồng nền có thể dừng service khi lệnh mới vừa tới → `stopSelf(latestStartId)`.
  Gộp Task 4+5 (`268139e`): **141 test JVM pass**, `assembleDebug` xanh.
- 2026-10-20 — **Task 6+7 xong** (subagent Sonnet, `656f3fe`, `caccba5`): FCM `type` → `CallController`; đổ chuông bằng Telecom self-managed
  (lùi về thông báo full-screen), chuông tự tắt sau 45 s nếu mất `call_ended`; màn hình cuộc gọi; guard để cuộc gọi VoIP không bị báo như
  cuộc gọi SIM; màn "Người thân" (mời/chấp nhận/thu hồi, gọi/nhắn chủ kính) và Hội thoại ("Đã nghe"/"Đã gửi", KHẨN CẤP nổi bật);
  401 → về màn đăng nhập. **165 test JVM pass**, manifest APK có `MANAGE_OWN_CALLS`, `RECORD_AUDIO`, ConnectionService, FGS phoneCall|microphone.
  Chưa có: sửa alias/ưu tiên link (thiếu PATCH ở client) — để đợt 2.
- 2026-10-20 — **Task 8 (tài liệu)** — Codex, controller commit `c900f62`: `mobile/docs/THU_TAY_GIAO_TIEP.md` (cài APK, quyền, kịch bản thử tay),
  cập nhật `MOBILE_APP_PROTOCOL.md` (hai làn, `COMMAND_EXPIRED`, retry, 4.1 đã cài, mục 7 đã cài), `NEXT_SESSION_APP.md`.
- 2026-10-20 — **Review cuối + bảo mật (Opus):** không chặn bàn giao; log/PendingIntent/exported/thứ tự hợp đồng/âm thanh đều ổn.
  3 Important: FGS cuộc gọi có thể crash nếu dừng trước `startForeground`; Outgoing/Connecting không timeout (kẹt khi mất FCM);
  làn FAST vẫn flush report treo trước lệnh (khẩn cấp trễ N×10 s) + flush đồng thời gửi đôi. 7 Minor. **Lint: 7 error mới** (thiếu `VIBRATE`,
  NewApi Telecom trên minSdk 24, chưa kiểm quyền thông báo).
- 2026-10-20 — **Sửa sau review + lint** (Sonnet, `c8470b4`): FGS luôn `startForeground` trước khi dừng; gọi đi timeout 45 s + poll `GET /calls` 5 s;
  Connecting timeout 15 s; làn FAST không flush, mọi flush dùng chung khoá, report đã SENT không bao giờ bị hạ; 4401/lỗi mạng → HANGUP;
  effect bọc try/catch; `seevia_route` chỉ nhận `auth`, `care`, `chat/<id>`; Telecom trả `createFailedConnection`; chuông lặp trên Android < 9.
  Controller tự kiểm lại: **188 test JVM pass, `assembleDebug` xanh, lint 0 error / 87 warning**, manifest có `VIBRATE`/`MANAGE_OWN_CALLS`/`RECORD_AUDIO`.
  Thêm 4 ca thử tay (#18–21). AB server và VH không đổi thêm (VH 516 pass + 2 skip).
- **Đợt 1 xong phần làm được trên máy này.** APK: `AB/mobile/app/build/outputs/apk/debug/app-debug.apk` (25 MB). Hướng dẫn: `AB/mobile/docs/THU_TAY_GIAO_TIEP.md`.
  Chưa kiểm: mọi thứ cần máy thật (đổ chuông khi khoá máy, âm thanh, Bluetooth, TalkBack). Nhánh `app-giao-tiep` (AB, VH) chưa push.
- 2026-10-20 — **Spec đợt 2** (builder check xong): `AB/docs/superpowers/specs/2026-10-20-app-dot2-design.md`. Người dùng chốt: âm thanh
  phone↔phone qua AB; gọi người đeo kính luôn đổ chuông trên kính; bạn bè không bao giờ vào chuỗi khẩn cấp; Claude chỉ viết code/migration,
  người dùng tự triển khai. **Người dùng duyệt spec (kể cả kính offline → đổ chuông điện thoại) nhưng CHƯA thực thi** — chờ lệnh.
- 2026-10-20 — **Chuyển hướng: vật cản + bộ benchmark AI** (gác đợt 2). Đo detector: YOLO11n 320 trên GPU p50 4,9 ms / p90 5,3 ms
  ⇒ trễ cảm nhận nằm ở fps/xác nhận 2 khung/mạng, không ở model. Đọc module OD của người dùng (`LuanLuKim/OD_module`): lấy tracker, corridor
  bù thị sai, hysteresis, ý tưởng hồi quy "tới gần"; "độ sâu" ở đó là heuristic gần/xa, không phải mét. Ghi chú bàn giao (NHÁP, câu hỏi đang treo):
  `SeeVia_system/docs/2026-10-20-vat-can-va-benchmark-ai.md`.
- 2026-10-20 — Người dùng chốt **không tự build dữ liệu**, chỉ dùng bộ công khai có bài báo/baseline. **Spec chi tiết (nháp, chờ duyệt):**
  `SeeVia_system/evaluations/SPEC_vat-can-va-benchmark-ai.md`. Tải nền bằng `evaluations/download_datasets.sh` vào `evaluations/datas/`
  (VinText, VIVOS, MC-OCR bản sao HF, VizWiz val+nhãn; nguồn+sha256 ở `datas/SOURCES.md`). Obstacle-Dataset phải tải tay (Drive file lẻ);
  PEDESTRIAN không tải được (DOI chưa đăng ký). Phát hiện: Obstacle-Dataset có ảnh từ COCO → phải lọc khi đo YOLO huấn luyện trên COCO.
- 2026-10-20 19:59 — **Tải xong (12 GB):** VinText 2,0 GB, VIVOS 3,2 GB, VizWiz 6,8 GB (ảnh val + nhãn VQA/caption/quality/grounding), sha256 trong `SOURCES.md`.
  **Chưa có, cần tải tay:** Obstacle-Dataset (zip từ Drive) và ảnh MC-OCR (CodaLab, cần tài khoản — bản sao HF chỉ có CSV nhãn).
  Script đã sửa: hai bộ này chỉ giải nén zip người dùng đặt vào.

## Nhật ký 2026-10-21: chạy full end-to-end

Chạy toàn tuyến kính giả lập → VH → AB → điện thoại thật; kết quả từng chức năng, nguyên nhân STT nghe sai (model, không phải VAD) và các hạn chế
còn lại ghi ở `docs/2026-10-21-han-che-chay-full-e2e.md`. Việc ưu tiên: lỗi "Đúng" không câu hỏi chạy nhầm lệnh, mở khóa gọi/nhắn, chạy pha khẩn cấp.

## D. Câu hỏi cần bạn chốt

1. **Thứ tự:** A → C → B1 → B2 như đề xuất, hay muốn làm vật cản/OCR trước?
2. **A3.1 cuộc gọi đến:** dùng `ConnectionService` self-managed (chắc đổ chuông, phức tạp hơn) hay notification full-screen (đơn giản)?
   Đề xuất: ConnectionService.
3. **A3.2 hàng đợi lệnh:** hai làn ưu tiên/chậm (đề xuất) hay nhiều luồng + khoá tài nguyên?
4. **C1/C2/C3 dữ liệu tự quay/chụp:** bạn (hoặc nhóm) có quay được video vỉa hè bằng kính và chụp ~150 ảnh chữ + ~240 ảnh tiền không?
   Nếu không, mình bắt đầu bằng tập công khai + vài chục mẫu, chấp nhận khoảng tin cậy rộng.
5. **B1.5 / B1.6:** có cho thêm mô hình độ sâu (cần GPU, có thể cài gói mới) và fine-tune YOLO không? Cả hai đều phải hỏi trước khi cài gói.
6. **B2.1:** cho thêm OCR rec cục bộ (PP-OCR rec tiếng Việt / VietOCR) làm phiếu kiểm số không?
7. Spec app ngày 2026-10-20 (gọi/nhắn, danh bạ, debug) có gộp luôn vào đợt này không, hay chỉ làm phần tối thiểu "kính ↔ người thân" ở A3.1?
- 2026-10-20 — **Spec vật cản + benchmark ĐÃ DUYỆT** (kể cả mặc định mục 11). MC-OCR bỏ (CodaLab cần tài khoản) → thay bằng **SROIE** (ICDAR 2019, đúng số)
  + **ViTextVQA** (hỏi về chữ tiếng Việt). Obstacle-Dataset: chỉ cần **tập test** (`img-test` 1.583 ảnh + `ann-test`/`label-test`) — Claude tự tải ngầm.
- 2026-10-20 ~20:10 — SROIE xong (487 MB); ViTextVQA đang tải (~9 GB). Obstacle-Dataset **tập test** tải ngầm bằng `evaluations/fetch_obstacle_test.sh`
  (trình tải riêng `fetch_drive_folder.py` vượt giới hạn 50 file của gdown, ~40 phút, log `datas/obstacle_fetch.log`).
  Người dùng dặn: session này chỉ tải + cập nhật tài liệu; **session sau lập plan và chạy** — điểm bắt đầu ghi ở đầu `evaluations/SPEC_vat-can-va-benchmark-ai.md`.
- 2026-10-20 ~20:40 — **Bắt đầu bộ benchmark (C).** Bảng metric + lý do chọn metric/dataset: `evaluations/METRICS.md`. Kế hoạch 3 gói (H vật cản, L OCR+VQA qua LLM,
  Q chất lượng ảnh+STT): `evaluations/PLAN_vat-can-va-benchmark-ai.md`. Khung chung `evaluations/bench/common` (chọn GPU trống, metadata commit VH, bootstrap CI, ghép đôi, p50/p90/p99).
  Sửa dữ liệu: VizWiz VQA bị nhãn quality ghi đè (cùng tên `val.json`) → giải nén lại vào `vizwiz/vqa/`, `vizwiz/quality/`; sửa `download_datasets.sh`.
  Phát hiện: VinText test chỉ 300 ảnh → dùng đủ tập; VizWiz val 32 % câu unanswerable; Obstacle img-test còn đang tải (1.261/1.583 lúc 20:20).
  `SeeVia_system/` không phải repo git → code bench không có version control (kết quả ghi commit VH).
- 2026-10-20 ~21:00 — Obstacle img-test tải đủ 1.583. **Đọc tiền:** không có bộ VND công khai có bài báo (BankNote-Net không có VND, chỉ embedding) → người dùng chốt dùng
  Kaggle `nguyentrongdai/vietnamese-currency` (`datas/vnd_kaggle`, 2.712 ảnh 192×144, 11 mệnh giá + 250 ảnh không tiền), ghi rõ **"cộng đồng, không baseline — chỉ chứng minh đọc được"**;
  thêm dòng C3 vào `METRICS.md`. **Phạm vi chốt:** Claude chỉ chạy thử + chạy full + ghi kết quả; người dùng tự đánh giá cải tiến (bỏ H1–H5).
- 2026-10-20 20:46 — **Bench vật cản chạy đủ xong** (`evaluations/run_hazard.sh`, GPU 0 trống): `evaluations/reports/HAZARD.md`, JSON `results/hazard/`.
  C1a non_coco: recall trong lối 42,8 % (ảnh gốc) / 37,3 % (ảnh qua kính); C1c detect p50/p90 5,2/5,7 ms; C1b 50 seed × 24 kịch bản, đối chứng 4/4 đạt.
  Gói Q (chất lượng ảnh + STT) và gói L (OCR/tiền/VizWiz, ~2.700 lượt LLM) đang chạy nền. Sửa trích dẫn: PMC 11645096 là bộ khác → bỏ khỏi METRICS/SPEC.
- 2026-10-20 ~20:47 — **Gói Q chạy đủ xong** (`evaluations/run_quick.sh`): `reports/QUALITY.md` (VizWiz-QI val 7.750 ảnh: chụp lại oan 0,46 % / 0,63 % money;
  AUROC sáng↔tối 0,91; measure() p50 36,6 ms) và `reports/STT.md` (VIVOS test 760 câu: WER 4,58 % [3,99; 5,18], người tệ nhất 17,6 %; greedy 4,60 %).
- 2026-10-20 21:00 — **Gói L chạy đủ xong** (`evaluations/run_llm.sh`, 2.702 lượt LLM, 0 lỗi): `reports/OCR.md`, `MONEY.md`, `VQA.md`.
  **Bảng tổng hợp mọi kết quả: `evaluations/reports/TONG_HOP.md`** (số + CI + độ trễ + giới hạn từng bàn đo). Người dùng tự đánh giá cải tiến.
  Việc người dùng: điền `evaluations/results/vqa_vizwiz/handcheck_50.csv` (độ đồng thuận LLM chấm); đối chiếu PDF Tang et al. (arXiv 2312.07571 đã đối chiếu xong 2026-10-20)
- 2026-10-20 21:30 — **Đợt cải tiến AI (người dùng duyệt):** kế hoạch `evaluations/PLAN_cai-tien-ai.md`. Chạy NỀN tách session (setsid):
  (1) `evaluations/train/pipeline.sh` — tải Obstacle train/val → venv riêng `~/.venvs/yolo` (ultralytics; KHÔNG cài vào seevia vì hạ cuDNN) →
  V1 ngưỡng (chọn trên val) + V2 yolo11s/m COCO → dựng tập (lọc trùng test bằng md5/dHash, nhãn giả 5 lớp chair/bench/plant/traffic_light/parking_meter)
  → V3 fine-tune s, m (imgsz 320) → NGAY SAU train: export ONNX + kiểm khói (`train/check_onnx.py`) + đo test/val + báo cáo `reports/HAZARD_MODELS.md`.
  Log `train/pipeline.log` (dòng cuối HẾT ok/LỖI); chạy lại tiếp được (`train/state/*.done`).
  (2) Codex gpt-6-luna chấm MÙ có nhìn ảnh 143 dòng VizWiz (50 kiểm tay + 104 unanswerable): `results/vqa_vizwiz/codex_judge/run_judge.sh`
  → `reports/VQA_JUDGE_CODEX.md` (log `codex_judge/judge.log`). VQA.md đã tách: không từ chối 72,1 % = khớp thiểu số 30,8 % + không khớp ai 41,3 %.
  Chưa làm: bàn đo tìm đồ (đã duyệt — cần chốt giao thức dữ liệu), cài model mới vào VH (chờ người dùng xem HAZARD_MODELS.md). Bỏ: mô tả nguy hiểm.
- 2026-10-20 21:32 — Người dùng cho **lên đời YOLO**: pipeline thêm YOLO26s/m (COCO + fine-tune, train TRƯỚC YOLO11s/m); export YOLO26 tắt end2end để VH `OnnxYolo` đọc được (kiểm bằng `check_onnx.py`). Mọi model đều đo **độ trễ chuỗi server** (decode→detect→assess→step, p50/p90/p99) + cột ngân sách trong HAZARD_MODELS.md. Pipeline khởi động lại 21:31 (tải tiếp).
- 2026-10-20 21:50 — Codex chấm mù xong 143/143 (sửa lỗi đếm dòng CSV có xuống dòng trong run_judge.sh): `reports/VQA_JUDGE_CODEX.md` — bịa thật trên unanswerable 8,7 % [3,8; 14,4] (Codex nhìn ảnh), κ từ chối Gemma↔Codex 0,29; **CHỜ đối chứng âm** (30 dòng tráo câu trả lời, `codex_judge/control.log`) trước khi tin. YOLO26s kiểm thật: export (end2end tắt) → OnnxYolo VH CUDA, đầu ra [1,84,2100] OK. Thêm bản ảnh 'như kính gửi' (rộng 320, JPEG q15–30) vào tập train. Pipeline đang tải train.
- 2026-10-20 21:55 — **Đối chứng âm Codex ĐẠT**: 20/20 câu trả lời tráo sang ảnh khác bị đánh bịa, 0/10 câu thật bị đánh bịa → tin được phán quyết nhìn ảnh. Bịa thật trên câu unanswerable (C4) = 8,7 % [3,8; 14,4]. (Sửa lỗi glob trong `bench/judge_agreement.py`.) Chỉ còn pipeline train chạy nền.
- 2026-10-20 22:00 — Commit `00ad021` (VH, nhánh app-giao-tiep, tác giả LuanLuKim <kimluanlu95@gmail.com>, không co-author): bản chụp `evaluations/` (bench, METRICS/PLAN/SPEC, reports, train scripts) vào `VH/evaluations/`; `results/` bị chặn theo ý người dùng. Bản đang chạy pipeline vẫn ở `SeeVia_system/evaluations/` (bench/common tự nhận cả hai vị trí). Chưa push.
- 2026-10-20 22:10 — **Đã push** nhánh `app-giao-tiep` của VH lên `hohoangluan/visioncare-host-demo` (đầu nhánh `00ad021`), KHÔNG merge, KHÔNG tạo PR (người dùng dặn). AB chưa push. Token dùng một lần qua `git -c credential.helper`, không lưu ra file; đã nhắc người dùng revoke token.
- 2026-10-21 02:05 — **Pipeline model vật cản xong** (`evaluations/train/pipeline.sh`): `evaluations/reports/HAZARD_MODELS.md` (V1 ngưỡng, V2 yolo26s/m + yolo11s/m COCO, V3 fine-tune cả 4). Log `evaluations/train/pipeline.log`.
- 2026-10-21 14:20 — **Hỏi về ảnh (Q1) — intent mới `ask`** theo bản chấm tay `handcheck_50_human.csv` (lỗi chung: trả lời thừa, không tập trung câu hỏi; 40/50 ghi chú).
  Gốc lỗi KHÔNG phải module OD: câu hỏi về ảnh đi qua prompt mô tả không gian (`describe_space`, bắt buộc loại phòng + bố cục, cấm đọc chữ) hoặc rơi vào
  `chat` (không gửi ảnh, 21 %) / `ocr` (đọc cả trang, 28 %). Sửa trên worktree `SeeVia_system/vh-vqa` nhánh `vqa-hoi-anh` (CHƯA commit, chưa gộp):
  `handlers/ask_image.py` (prompt ghi rõ "trả lời câu hỏi cho NGƯỜI MÙ"), nhãn `ask` (đặt CUỐI `LABELS` — chèn giữa làm lệch message_send),
  làn A + cổng ảnh, luật từ khoá, luật "lệnh đọc nói thẳng thắng `ask`". Prompt chỉnh trên 100 câu dev riêng, báo trên 300 câu test.
  Kết quả `evaluations/reports/VQA_ASK.md`: chấm mù (Claude Sonnet nhìn ảnh, đối chứng âm 15/15 + 15/15 ĐẠT, 150 cặp) câu đầu trả lời thẳng 26 → 99 %,
  có nội dung thừa 95 → 7 %, đúng với ảnh 73 → 92 %, chọn bản mới 134/150; Gemma-chấm VQA acc 70,7 → 83,6 %; số từ trung vị 35 → 20;
  định tuyến 300 câu: chat (không ảnh) 62 → 13. Độ trễ A/B gọi mới: TTFT +41 ms [+33; +49], tổng −127 ms. Gold intent: test 94,6 → 97,3 %, dev 94,7 → 93,9 % (6/7 câu
  "mất" là câu hỏi-một-chi-tiết gold ghi ocr). Codex KHÔNG còn trên máy (extension bị gỡ) → giám khảo thay bằng Sonnet subagent.
  File cho người dùng chấm lại: `SeeVia_system/handcheck_50_ask_vs_space.csv`. Sửa lỗi bench: lượt dev từng ghi đè `results/vqa_vizwiz/handcheck_50.csv` (đã dựng lại từ JSON).
  Retrain vật cản p0: ft_26s treo NFS 10:22–13:47 (đã kill, resume từ last.pt), cả 4 model đủ 120 epoch, pipeline đang đo.
- 2026-10-21 14:34 — **Pipeline model vật cản xong** (`evaluations/train/pipeline.sh`): `evaluations/reports/HAZARD_MODELS.md` (V1 ngưỡng, V2 yolo26s/m + yolo11s/m COCO, V3 fine-tune cả 4). Log `evaluations/train/pipeline.log`.
- 2026-10-21 15:30 — **Đọc tiền + OCR** (worktree `SeeVia_system/vh-ocr`, nhánh `ocr-tien`, CHƯA commit; pytest 532 passed): báo cáo
  `evaluations/reports/MONEY_OCR_CAI_TIEN.md`. Đọc tiền: Gemma chọn 1 trong 13 nhãn + xác suất (structured choice); 1 khung τ 0,995 (đang chạy,
  kính gửi 1 ảnh) / 3 khung song song luật "≥1 khung chắc, không khung nào chắc nhãn khác" τ 0,98 (cần kính chụp liên tiếp) — test: nói sai
  11,2 → 1,8 %, đúng 67,3 → 77,3 %. Lỗi còn lại = số bị cắt mép/gập/che → sửa ở khâu chụp (căn khung). OCR: cảnh báo "chưa chắc" theo xác
  suất token chữ số (AUROC test 0,85). Loại có số: JSON đối chiếu, mảnh phóng to, prompt đếm số 0, tầng 2, chuẩn hoá xác suất, 5 khung,
  prewarm (server không cache ảnh). **Tìm đồ: chức năng bổ sung, chưa đo** (người dùng chốt). Vật cản bước A: `last.pt` của 11s/26s/26m đạt
  ~90 % recall trong lối (best.pt Ultralytics chọn nhầm epoch 1); đang đo lại độ trễ cùng GPU (`train/relatency.sh`).
- 2026-10-21 cuối ngày — **Bàn giao:** `docs/2026-10-21-ban-giao-cai-tien-ai.md`.
- 2026-10-21 — **Vật cản Task 4 (bàn đo C1b):** `evaluations/bench/hazard_scenarios.py` thêm split `dev`/`test` (seed 1000+s / 2000+s, tham số thật lấy mẫu: camera, chiều cao người, nhún bước, quay đầu, nhoè, dt thất thường), 9 loại Việt Nam/đột ngột/đối chứng và biến thể `+gait/+yaw/+blur`; `Scenario` có thêm `times`, `ego`, `group`, `t_visible_frame`. Split `legacy` giữ nguyên từng bit (hash ở `bench/fixtures/c1b_legacy_hash.json`; chạy lại 8,3 % kịp thời / 0,54 báo nhầm/phút). Chi tiết: `docs/superpowers/plans/sdd-od/task-4-report.md`.
- 2026-10-21 — **Firmware kính ↔ endpoint server:** đối chiếu `your-eyes-esp32-firmware` với `vh-chot/docs/FIRMWARE_ENDPOINTS.md` + mã `live/device_session.py`: mọi khung hai chiều đã khớp (hello/turn/0x01–0x05/call_*/played/cancel/ping, `live:"ocr"` cues rỗng, `call_state` sau `hello_ok`, `result-*` lúc rảnh). Cue: 31 clip, sha256 trùng server, `cue_clips_data.h` sinh lại trùng từng byte. Sửa 2 chỗ: `camera_live.cpp` OCR live tự thoát sau 45 s không có `cam`/`capture` (server hết trần không gửi `end`); `audio_service.cpp` xoá `s_pendingLive` khi bấm nút/rớt socket (tránh `cam` nav bị coi là OCR rồi bị tắt). Chép `FIRMWARE_ENDPOINTS.md` bản vh-chot vào repo firmware. Biên dịch trên server (arduino-cli 1.1.1, esp32 3.3.10, FQBN như CLAUDE.md): 1492683 B (47%), RAM 84992 B. **Chưa nạp board** (board cắm máy người dùng, không có cổng serial qua tunnel); token riêng cho `glasses-<mac>` chưa cấp; lỗi rớt chữ đầu chưa xử lý (cần đo trên kính thật).
