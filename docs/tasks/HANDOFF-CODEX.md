# HANDOFF — để Codex (hoặc bất kỳ agent nào khác) tiếp tục chương trình 23-task

Viết ngày 2026-08-22; Codex cập nhật sau T17 cùng ngày. Claude Code ban đầu dùng
`superpowers:subagent-driven-development`; người dùng sau đó chốt **không cần
Superpowers**, ưu tiên hoàn tất chức năng chạy đúng và batch test để tiết kiệm thời
gian. Tài liệu này là checkpoint sống qua compaction.

**Repo:** `D:\Study\innostar\Sever_test` (server kính) + `D:\Study\innostar\your-eyes-esp32-firmware` (firmware).
**Branch làm việc:** `feat/hoi-thoai-23-task` (server kính) — **KHÔNG PHẢI `main`**.
Firmware đang trên branch `net-stream-adpcm` sẵn có (không phải branch tôi tạo).

---

## 1. Đọc theo đúng thứ tự này trước khi làm gì

1. `docs/tasks/RUNBOOK.md` — thứ tự thi công 23 task, luật gốc (mục 0).
2. `docs/tasks/CONTRACTS.md` — nguồn sự thật liên repo. **Đã được cập nhật nhiều
   lần trong lúc chạy chương trình này** (mục 2.1, 2.4, 4.4, 5.5, câu hỏi #12-15 ở
   mục 7 đều đã sửa so với bản gốc lúc lập kế hoạch). Đọc bản HIỆN TẠI, không phải
   bản trích dẫn trong RUNBOOK.
3. `docs/tasks/AGENT_RULES.md` — luật bắt buộc cho MỌI subagent (mẫu báo cáo, luật
   chống xung đột, mẫu contract-delta). Dán/paraphrase luật này vào mọi prompt dispatch.
4. `docs/superpowers/plans/2026-08-22-subagent-orchestration-23-task.md` — **kế
   hoạch gốc**, chia 23 task thành 10 "Task" điều phối (Task 0 = hạ tầng, Task 1 =
   Đợt 0 đo đạc, Task 2 = Đợt 1 nền T01→T03→T04, Task 3 = Đợt 2 5 nhánh song song,
   Task 4 = Đợt 3 T05‖T06, Task 5-8 = Đợt 4-7, Task 9 = báo cáo tổng). File này có
   TOÀN VĂN prompt dispatch cho từng task con — copy gần như nguyên văn khi dispatch.
5. **File này (HANDOFF-CODEX.md)** — 10 Ruling đã chỉnh kế hoạch gốc, đọc mục 3 dưới
   đây trước khi dispatch bất cứ gì, vì kế hoạch gốc ở mục 4 phần trên đã LỖI THỜI ở
   vài chỗ (bị Ruling ghi đè).
6. `.superpowers/sdd/2026-08-22-subagent-orchestration-23-task/progress.md` — ledger
   chi tiết từng bước đã làm, mọi quyết định, mọi kết quả review. File này **KHÔNG
   nằm trong git** (thư mục `.superpowers/` bị gitignore) — chỉ tồn tại trên máy đang
   chạy. Nếu Codex chạy trên máy khác, ledger này KHÔNG có sẵn — dùng file
   HANDOFF-CODEX.md này + `docs/tasks/PROGRESS.md` (file git-committed, bảng tóm tắt)
   thay thế.

---

## 2. Trạng thái hiện tại — task nào xong, task nào đang chạy

Xem bảng đầy đủ ở `docs/tasks/PROGRESS.md` (đã commit). Đợt 0-3 xong hoàn toàn;
Codex đã làm tiếp T08-T23 theo các task đã ghi ở bảng dưới. Hiện **20/23 task có
code xong hoặc PARTIAL đúng dự kiến**. Android AVD `test_pixel` đã build/test/cài
và khởi động app thành công; T17 server + firmware đã checkpoint, tiếp theo **T18**.
Tóm tắt:

| Đợt | Task | Trạng thái | Commit |
|---|---|---|---|
| 0 | Hạ tầng điều phối | ✅ | `d8d62a9`, `1581246` |
| 0 | G10, H0, P7 (3 phép đo) | ✅ | `abee34d` |
| 1 | T01 Định danh thiết bị & lượt | ✅ | server `72444e3`, firmware `e2d3e14` |
| 1 | T03 Phiên & pending | ✅ | `8318b01` |
| 1 | T04 Router & ngắt lời | ✅ | `8567239` |
| 2 | T02 (khoá F8 + G11) | ✅ | server `5bdcfec`, firmware `5ca6fd5` |
| 2 | T07 Vị trí | ✅ | `a7c0306` |
| 2 | T15 OCR chất lượng | ✅ | `675efa8` |
| 2 | T20 Hợp đồng mã lỗi | ✅ | `42d4ea9` |
| 2 | T22 Bật TLS | ✅ (code); ⬜ (số đo phần cứng) | server `80b1853`, firmware `302db96` |
| 3 | T05 Intent & schema slot | ✅ | `bd528c1` |
| 3 | T06 Bảng chính sách slot | ✅ | `995a431` |
| 3 | **Fix router.py** (xem mục 2b) | ✅ | `6a6017a` |
| 4 | T08 Gọi danh bạ | 🟠 server xong; chờ app P1/P2 + đo ngưỡng thật | `ad03887` |
| 4 | T09 Gọi khẩn cấp | 🟠 khóa hiện hữu xong; chờ abort/classifier thấp/T21/P11 | `cc508f5` |
| 4 | T10 Chỉ đường | 🟠 server xong; D4 chờ app phát `INVALID_DESTINATION` | `6636028` |
| 4 | T12 Nhạc | ✅ | `80cedf2` |
| 4 | T14 OCR ngữ cảnh | ✅ | `c39b8d2` |
| 4 | T16 Không gian & vật cản | ✅ | `cd0932c` |
| 5 | T13 Chat & lịch sử | 🟠 code/test xong; chờ đo Gemini/prefix thật | `0a18376` |
| 5 | T11 Đặt xe | 🟠 server fail-closed; chờ Farefeed/geocode/app | `11662ac` |
| 5 | T23 Quyền & cấu hình | 🟠 code/AVD xong; chờ điện thoại thật | `2520017` |
| 6 | T17 Tách `/frame` | 🟠 F3/F4 code/build xanh; chờ board + F5 | server `50b53e8`, firmware `61f81e7` |
| 6-7 | T18/T19/T21 còn lại | ⬜ **BẮT ĐẦU TỪ T18** |

**HEAD code chức năng hiện tại của branch `feat/hoi-thoai-23-task`: `50b53e8`.**
T17: **19 DoD + 114 regression pass**; firmware compile
**1 295 623 B (41%) / RAM tĩnh 77 520 B (23%)**.
Regression T14/T16: **94 pass**. T12 có **16 DoD + 35 services + 109 regression
pass**. Full suite sau T12: **584 pass, 1 skip, 9 xfail, 3 fail**, cả ba fail là
LLM thật trả `unknown` khi quota Gemini cạn. Một snapshot full suite lúc T14/T16
đang được sửa có thêm 3 lỗi mock OCR cũ; mock đã tương thích và 94 regression
đã xanh, nhưng full suite sạch cần chạy lại khi quota hồi.

### 2b. 🔴 Bug thật đã phát hiện VÀ SỬA trong lúc chạy Đợt 3 — đọc để hiểu vì sao có commit `6a6017a`

`pipeline/router.py::_try_fill_pending_slot` (code T04, đã commit từ Đợt 1) có bug
thật: khi người dùng trả lời một câu hỏi "fill" (VD "Bạn muốn nghe bài hát nào?"),
nó nhét **NGUYÊN VĂN transcript** làm giá trị slot thay vì trích xuất sạch. Người
dùng nói "Tôi muốn nghe bài Nơi này có anh" thì `song_title` = cả câu, không phải
"Nơi này có anh". T05 và T06 (Đợt 3) độc lập phát hiện ra cùng gap này khi build
`detect_with_params(pending=)` (B3) mà thấy nó không được router gọi tới.

Controller (Claude) đã sửa trực tiếp (không qua vòng dispatch riêng, vì user yêu
cầu và thời gian gấp) — nối `_try_fill_pending_slot` gọi
`intent_mod.detect_with_params(text, state, pending=pending)` thay vì
`intent_local.classify()` + nhét thô. Verify: 69/69 test router pass KHÔNG CẦN SỬA
TEST (test đã mock sẵn đúng interface từ trước). Chi tiết đầy đủ trong commit message
`6a6017a` và `docs/tasks/reports/T05.md` mục "Fix note".

**Codex: đây LÀ MẪU cho loại bug cần cảnh giác khi dispatch Đợt 4** — 6 agent Đợt 4
đều fill slot qua CHÍNH cơ chế này (`_try_fill_pending_slot`). Giờ đã sửa nên KHÔNG
cần lo nữa, nhưng nếu review Đợt 4 thấy giá trị slot "bẩn" (còn nguyên câu, không
sạch), quay lại kiểm `pipeline/router.py` dòng ~443 trước tiên.

### 2c. Hai test flaky đã biết — đừng tưởng là regression

- `tests/test_bang_am_thanh.py` — một test NGẪU NHIÊN trong file này có thể đỏ do
  hết quota Gemini free-tier hoặc timing thật (không phải lỗi code). Test cụ thể nào
  đỏ THAY ĐỔI giữa các lần chạy.
- `tests/test_intent_slots.py::test_stt_error_unrecognizable_name_not_invented` —
  đánh dấu `@pytest.mark.llm`, gọi Gemini thật trên một câu vô nghĩa để test chống
  bịa địa danh. Pass khi chạy riêng, có thể flaky khi chạy cùng lúc nhiều test khác
  (tải/quota).

**Việc đang treo (không chặn Đợt 4, nhưng phải làm trước khi coi là xong thật):**
- T08/P1 `contact_list` phía app và bảng đo ngưỡng danh bạ thật
  (`docs/tasks/measurements/D7-thresholds.md`). Server đã hỗ trợ fuzzy, pending,
  lựa chọn ordinal/name và payload `contact_id`; ca tên đặt lạ vẫn chờ P1.
- Số đo phần cứng T22 (`docs/tasks/measurements/F9.md`) — cần board thật + arduino-cli,
  dồn về gần T21 theo Ruling 8.
- G11 (`docs/tasks/measurements/G11.md`) cần đo lại MỘT MÌNH (không có tải CPU song
  song) trước khi chốt số cho T21 — số hiện tại dao động 0.94x-2.59x vì đo lúc 5 agent
  khác chạy cùng máy.
- T09/21.5 chưa có endpoint abort/cửa sổ 3-5 giây; chưa được hạ ngưỡng classifier
  emergency khi người dùng chưa có đường dừng cuộc gọi nhầm. “một một bốn” CỐ Ý
  còn xfail (3 số rời dễ trùng phòng/tầng, hạ precision thật khi chưa có abort —
  xem 2d). “gọi cứu thương” đã hết xfail, xem 2d.
- T10/D4 chờ quyết định forward geocode phía app và ngưỡng invalid; server đã xong
  pending 2 lượt, readback low-confidence 25 giây và ack có tên điểm đến.

### 2d. Đợt hardening (Ruling 9) — chạy 2026-08-22, sau khi T08-T16 xong

Đọc lại toàn bộ `docs/tasks/reports/T*.md` mục "Chưa làm & vì sao", lọc thứ vá
được ngay (code-only, không chặn bởi app/hardware/quyết định người dùng chưa
chốt). Hai vá thật, cả hai đã có test mới, full suite xanh (627 pass, bỏ qua
`test_bang_am_thanh.py` vì cạn quota Gemini free-tier lúc chạy — không liên
quan code):

- **`services/visioncare_client.py:81`** (nợ từ T01+T03, hai report cùng ghi):
  `call_service_api()` luôn nhét `config.VISIONCARE_DEVICE_ID` bất kể request
  đến từ kính nào — nhiều kính gọi cùng lúc thì host 8001 nhận nhầm device_id,
  sai định tuyến FCM/pairing. Sửa: đọc `app.DEVICE_ID_CTX.get()` (nhập trễ
  trong hàm, tránh vòng tròn `app`↔`services`), rơi về hằng số cũ khi ContextVar
  rỗng (thread nền, test). Test mới:
  `tests/test_services.py::test_call_service_api_uses_request_device_id_not_config_constant`.
- **`pipeline/router.py::_LOCAL_EMERGENCY`** thêm `cứu thương` (cụm động-danh từ
  đặc thù, an toàn) — xfail `gọi cứu thương` ở `tests/test_emergency_detect.py`
  đã bỏ. **KHÔNG thêm `một một bốn`**: 3 số đọc rời dễ trùng số phòng/tầng/điện
  thoại đọc dở, hạ precision thật — đúng loại rủi ro Ruling 8 cấm (không hạ độ
  nghiêm ngặt emergency). Giữ nguyên xfail, chờ T09/21.5b (cửa sổ abort) trước
  khi cân nhắc lại.

Ngoài hai cái trên: phần lớn "Chưa làm" của các report đã tự hết hạn (T13 gộp
lịch sử chat+action giải quyết nợ T03/T04 nêu; T12 dọn `_ASK_SONG`/`_ASK_VOLUME`
giải quyết nợ T06 phần music) hoặc bị chặn thật (app Android, phần cứng, quyết
định người dùng chưa chốt) — không vá thêm, tránh đoán mù.

**Bug thật tìm thấy khi test e2e sống (server 8000+8001+postgres thật, TTS
synth → `/process` → real server) trước khi vào hardening pass này:** local
SetFit classifier chặn OCR follow-up (T14) không bao giờ chạm Gemini vì `ocr`
nằm trong `_PARAM_FREE`; đã vá bằng `_has_live_ocr_cache()` trong
`pipeline/intent.py`, nằm trong commit T14 (`c39b8d2`) vì chung working tree.

**Ba task không cần đợi Đợt 4's dependencies, có thể dispatch bất cứ lúc nào (xem
mục 9 dưới để biết chi tiết):** T23, T14, T17.

---

## 3. MƯỜI RULING đã chỉnh kế hoạch gốc — PHẢI ÁP DỤNG, không phải tuỳ chọn

Kế hoạch gốc (`docs/superpowers/plans/...md`) viết trước khi biết những điều này.
Đọc plan mà không đọc mục này sẽ làm sai — dưới đây là bản tóm tắt, chi tiết đầy đủ
nằm trong `.superpowers/sdd/.../progress.md` nếu file đó còn tồn tại trên máy.

1. **Ánh xạ quy trình dispatch:** mỗi "Task N" trong plan = một wave. Trong wave,
   controller (Codex) dispatch trực tiếp từng agent con — KHÔNG có tầng agent trung
   gian. Sau khi tất cả agent con của wave báo xong: build review package (diff +
   report), dispatch MỘT reviewer (hoặc vài reviewer nếu wave có nhóm rủi ro khác
   nhau — xem Ruling 8), rồi fix loop (tối đa 5 vòng: agent tự sửa theo finding,
   re-review scoped), rồi controller tự commit — **agent con KHÔNG BAO GIỜ tự git
   commit**.

2. **`docs/tasks/reports/<Txx>.md` là nơi BÁO CÁO VĨNH VIỄN, KHÔNG phải workspace
   tạm.** Đây là lỗi tôi (Claude) mắc phải ở Đợt 0 (dispatch report vào
   `.superpowers/sdd/...` — bị gitignore, sẽ mất khi dọn workspace) — phải sửa lại
   sau. Codex: LUÔN dặn report_file = `docs/tasks/reports/<Txx>.md` ngay từ đầu.

3. **`handlers/slots.py` viết TRỌN 6 slot ngay ở T06 (Đợt 3), không để Đợt 4 tự
   thêm.** Lý do: Đợt 4 có 6 agent song song, không thể cùng sửa một file. Bảng đã
   viết xong, xem `handlers/slots.py` thật trên đĩa (T06 đã DONE).

4. **`handlers/ride.py`, `music.py` còn giữ hằng số `_ASK_*` trùng với `slots.py`
   — dọn khi T11/T12 (chủ 2 file đó) chạm tới.** T08/T10 đã dọn phần phone/navigation.

5. **Ruling 5 — kiểm `.gitignore` kỹ trước khi tin file "sẽ commit được".**
   `tests/fixtures/*` từng nuốt `app_error_codes.txt` im lặng — luôn `git check-ignore
   -v <path>` trước khi coi một file measurement/report là sẽ vào git.

6. **Ruling 7 — xem mục 2 ở trên** (report file vĩnh viễn).

7. **Ruling 8 — TỪ ĐỢT 2 TRỞ ĐI (Đợt 1 vẫn giữ nguyên độ kỹ):**
   - Review THEO CẢ WAVE (một reviewer đọc hết diff cả wave), không phải một
     reviewer/task con — trừ khi wave có task thuộc nhóm an toàn (mục 8 dưới), thì
     tách riêng một reviewer full-rigor cho task đó.
   - Hạ độ nghiêm ngặt cho task rủi ro thấp (không đụng tiền/an toàn/mã hoá):
     chấp nhận "Approved, Minor deferred" nhanh hơn.
   - KHÔNG tự kiểm phần cứng thật giữa chừng mỗi task — dồn về gần T21/T22, trừ khi
     DoD không thể tick nếu thiếu.

8. **Ba lằn ranh GIỮ NGUYÊN ĐỘ KỸ mãi mãi, không giảm dù đang ở "chuẩn nhẹ" nào:**
   - `emergency_call` KHÔNG đi qua bất kỳ bước xác minh nào (T09, và bất cứ đâu
     dính emergency).
   - TLS/mã hoá — không được tắt để bù độ trễ, dưới bất kỳ lý do nào (T22, T21 khi
     đo lại).
   - Đặt xe/tiền thật — không đặt tới toạ độ giả/hằng số (T11).

9. **Ruling 9 — TỪ ĐỢT 2 TRỞ ĐI (mở rộng Ruling 8): chỉ chặn (Critical/Important)
   khi finding LÀM SAI hoặc LÀM HỎNG LUỒNG CHÍNH** (thứ task được yêu cầu xây, chạy
   đúng cho ca thông thường). Race hiếm, rò tài nguyên chậm, edge case không nằm
   trong luồng chính, vấn đề cấu trúc file → ghi vào ledger/PROGRESS.md, KHÔNG vào
   fix loop. Ba lằn ranh ở mục 8 trên vẫn luôn Important dù nhẹ tay tới đâu.
   ⚠️ **Nợ kỹ thuật thật:** từ ruling này trở đi, KHÔNG task nào được kiểm edge case
   đầy đủ. Trước khi tuyên bố "xong sẵn sàng phát hành", phải có một đợt hardening
   riêng đọc lại toàn bộ report + Minor deferred, đánh giá lại cái nào cần vá thật.

10. **Ruling 10 — hardware smoke test khi sửa đường xử lý chính, nếu board vật lý
    có sẵn.** Không phải test kịch bản cụ thể (không bơm được giọng nói cụ thể vào
    mic thật) — chỉ xác nhận LUỒNG DÂY: nạp firmware (nếu đổi) hoặc restart server
    (nếu đổi code T01+), bấm `'p'` qua Serial console (COM8, xem mục 5 dưới) mô
    phỏng giữ nút thật, xem log server có nhận đúng request không, audio có phát về
    không. Làm SAU KHI pytest xanh, không thay thế pytest.

11. **Quyết định Codex mới nhất của người dùng:** không dùng Superpowers/subagent;
    code các phần độc lập theo batch để tối ưu thời gian, gom test về cuối cụm. Tuy
    nhiên chỉ đánh dấu DONE/PARTIAL và commit sau khi DoD/full regression tương ứng
    đã chạy thật. Sau mỗi task cập nhật file handoff này để an toàn qua compaction.

**Quyết định thêm của người dùng (không phải Ruling nhưng cần biết):**
- Android emulator ĐÃ CÀI SẴN: AVD `test_pixel` (Android 36, google_apis x86_64),
  SDK ở `D:\tmp\app-demo-android-toolchain\android-sdk`. Dùng cho T08/T11/T19/T23
  khi cần verify app-side trước khi cần điện thoại thật.
- Board vật lý ESP32-S3 **có sẵn** trên COM8 (xem mục 5).

---

## 4. Cách dispatch một wave — quy trình lặp lại cho mọi wave còn lại

1. Đọc plan file mục "Task N" tương ứng wave sắp làm (Đợt 4 = Task 5, Đợt 5 = Task
   6, Đợt 6 = Task 7, Đợt 7 = Task 8).
2. Kiểm điều kiện vào (thường là: task trước đã commit chưa — `git log --oneline`).
3. Dispatch TỪNG agent con trong wave, mỗi agent một message riêng (nếu công cụ hỗ
   trợ chạy nền song song thì dispatch cùng lúc cho các agent KHÔNG đụng file nhau —
   xem bảng "FILE ĐƯỢC SỬA" trong plan cho từng agent).
   - Copy gần nguyên văn prompt trong plan, CẬP NHẬT: report_file luôn là
     `docs/tasks/reports/<Txx>.md` (không phải workspace tạm — xem Ruling 2).
   - Luôn nói rõ: "Đọc AGENT_RULES.md trước, tuân mục B (chống xung đột): không git
     write, không đụng file ngoài danh sách được cấp."
   - Luôn dặn: baseline test hiện tại là bao nhiêu (chạy `pytest tests -q` trước khi
     dispatch để biết con số thật, đừng tin số cũ trong plan).
4. Đợi tất cả agent con báo cáo. Đọc report.
5. Tự chạy DoD command của từng agent để verify (đừng chỉ tin báo cáo).
6. Chạy full suite (`pytest tests -q`), so với baseline — không đỏ thêm (trừ flaky
   đã biết: `tests/test_bang_am_thanh.py`, một test ngẫu nhiên trong file đó có thể
   đỏ do hết quota Gemini free-tier hoặc do timing thật, KHÔNG liên quan code).
7. Build review package: diff theo ĐÚNG file mỗi agent con sở hữu (không dump cả
   git status — quá to). Dispatch reviewer theo Ruling 8/9 (nhẹ cho đa số, full rigor
   cho task chạm 3 lằn ranh ở mục 3.8).
8. Đọc verdict. Áp bộ lọc Ruling 9: chỉ finding vỡ luồng chính vào fix loop. Còn lại
   ghi vào `docs/tasks/PROGRESS.md` cột "Ghi chú" hoặc file HANDOFF/ledger.
9. Dispatch fix round (nếu có), re-review scoped, lặp tới khi sạch hoặc chạm trần 5
   vòng (breaker: tự phán xét finding còn mở, ghi ruling).
10. Commit — TÁCH THEO TASK (một task một commit, để `git bisect` dùng được), CHỈ
    `git add` đúng file agent đó sở hữu (kiểm `git status --short` trước khi add —
    nhiều agent chạy song song sẽ để dirty file của NHAU trong working tree, đừng
    quét nhầm bằng `git add -A`).
11. Cập nhật `docs/tasks/PROGRESS.md` (bảng trạng thái) và tick ô tương ứng trong
    `docs/tasks/RUNBOOK.md` mục 6. Merge contract-delta (nếu agent viết ra
    `docs/tasks/contract-deltas/<Txx>.md`) vào `CONTRACTS.md` — sửa luôn lỗi nhỏ
    (hedge thiếu, số đếm sai) khi merge, đó là việc của controller.

---

## 5. Phần cứng thật — cách dùng nếu cần

**Board ESP32-S3, COM8.** Toolchain: `arduino-cli` 1.5.1 tại
`D:\AppDownload\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`.

Compile + nạp:
```
& $cli compile --upload -p COM8 -b "esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=huge_app,FlashSize=16M,CDCOnBoot=cdc" "d:\Study\innostar\your-eyes-esp32-firmware"
```
🔴 `CDCOnBoot=cdc` BẮT BUỘC — thiếu cờ này Serial câm hoàn toàn dù board chạy bình
thường (bẫy đã biết, ghi trong `CLAUDE.md` của repo firmware).

Đọc Serial đáng tin cậy (PowerShell, KHÔNG dùng `arduino-cli monitor` qua pipe — nó
thoát ngay khi stdin không phải TTY tương tác):
```powershell
$port = New-Object System.IO.Ports.SerialPort COM8,115200,None,8,One
$port.ReadTimeout = 500
$port.Open()
Start-Sleep -Milliseconds 300
$port.DiscardInBuffer()
$port.Write("p")   # 'p' = audioSimulatePress(3000) — mô phỏng giữ nút 3s, ĐÚNG code path bấm nút thật
$sb = New-Object System.Text.StringBuilder
$deadline = (Get-Date).AddSeconds(14)
while ((Get-Date) -lt $deadline) {
  try { $chunk = $port.ReadExisting(); if ($chunk) { [void]$sb.Append($chunk) } } catch {}
  Start-Sleep -Milliseconds 200
}
$port.Close()
$sb.ToString()
```

Server kính phải đang chạy `uvicorn app:app --host 0.0.0.0 --port 8000` với code MỚI
NHẤT (restart nếu vừa sửa `app.py`/handler nào board gọi tới) — cloudflared tunnel
route thẳng `api.visioncare-host.uk` về `localhost:8000` trên máy này.

**Giới hạn:** không bơm được giọng nói cụ thể vào mic thật — `'p'` ghi âm tiếng ồn
thật xung quanh mic vật lý lúc đó. Chỉ dùng để xác nhận LUỒNG DÂY (header ra tới,
response về, không crash), không xác nhận được kịch bản STT/intent cụ thể.

---

## 6. Việc còn lại — 3 task chưa chạy + phần PARTIAL, theo RUNBOOK

**Đợt 3: XONG HOÀN TOÀN** (T05, T06, fix router.py — xem mục 2).

**Đợt 4:** Xong. T08, T09, T10 PARTIAL đúng dự kiến; T12, T14, T16 DONE. T14
đã nối H1/H3/H5 của T15 vào production và cung cấp OCR cache chung cho T13.

**Đợt 5:** T13 đã code/test xong, PARTIAL chờ đo Gemini thật. T11 server đã
fail-closed và PARTIAL chờ Farefeed/geocode/app contract. AVD `test_pixel` đã
verify ngày 2026-08-22: Gradle `testDebugUnitTest assembleDebug` xanh, APK cài và
khởi động không crash. Theo yêu cầu người dùng, app Android đã bỏ khai báo và lời
xin quyền `CAMERA`; build/cài mới xác nhận hộp thoại đầu tiên là Vị trí, không còn
Camera. T23 đã code xong cả ba lớp: 9 DoD + 90 regression server xanh, host
14 action tests/OpenAPI xanh, Android build + AVD cold-start xanh. Điện thoại thật
ngắt ADB ngay trước install nên còn 5 ca manual; xem `reports/T23.md`. Thay đổi app
đang ở working tree repo `app_demo_backend`, chưa commit để không gom nhầm các
thay đổi Spotify/backend có sẵn. Tiếp theo T17.

**Đợt 6:** T17 đã PARTIAL đúng bằng chứng: server `/frame` + FrameBuffer,
firmware hai socket, 19 test/114 regression/build xanh; 🔴 F2 không thi công.
Chưa nạp board, chưa chốt F5/RTT/max-age. Tiếp theo theo thứ tự:
T18 (SSE downlink) → T19 (cuộc gọi đến, cả 4 repo).

**Đợt 7:** T21 (ngân sách độ trễ — 🔴 PHẢI SAU T02+T22, và phải đo TRÊN BẢN TLS=1
thật, nghĩa là làm số đo phần cứng T22 CÒN TREO ở đây trước).

**Cuối:** Task 9 trong plan — chạy 5 cổng phát hành, kiểm 12 việc-không-được-làm ở
RUNBOOK mục 7, viết `FINAL-REPORT.md`, final whole-branch review (dùng model mạnh
nhất có), rồi mới `superpowers:finishing-a-development-branch` (hoặc tương đương
nếu Codex không có skill đó — về cơ bản: xin merge/PR, không tự merge vào main).

---

## 9. Ba task ĐỘC LẬP — không cần đợi Đợt 4, người dùng đồng ý "để Codex làm"

Theo `docs/tasks/00-INDEX.md`, ba task này có "Chặn bởi: —" hoặc chỉ chặn bởi task
ĐÃ XONG, nên có thể dispatch NGAY, không cần chờ Đợt 4 xong trước:

- **T23 Quyền & cấu hình** (`docs/tasks/T23-capabilities.md`) — chặn bởi: KHÔNG CÓ.
  Dùng Android emulator đã cài sẵn (mục 3, "Quyết định thêm") để verify app-side
  trước khi cần điện thoại thật.
- **T14 OCR ngữ cảnh** (`docs/tasks/T14-ocr-context.md`) — chặn bởi: T03 (đã xong).
  Nối phần H1/H3/H5 mà T15 đã xây sẵn trong `models/ocr/prompts.py` (có comment 🔴
  đánh dấu chỗ cần nối, xem `docs/tasks/reports/T15.md`).
- **T17 Tách `/frame`** (`docs/tasks/T17-frame-channel.md`) — chặn bởi: T01 (đã
  xong). 🔴 F2 (đảo thứ tự part multipart) KHÔNG được thi công — đã đo, làm chậm đi.

Cả ba dùng đúng quy trình ở mục 4. Có thể dispatch độc lập, không cần chờ Đợt 4's
6 task song song (T08/T09/T10/T12/T14/T16) hoàn tất — nhưng T14 TRÙNG với Đợt 4's
T14, nên nếu dispatch T14 riêng thì ĐỪNG dispatch lại T14 trong Đợt 4.

---

## 7. Ba câu hỏi 🔴 người dùng đã trả lời — đừng hỏi lại

- README/HUONG_DAN_SERVER firmware về TLS đã cập nhật (commit `5ca6fd5`).
- Tăng tốc: chấp nhận Ruling 8/9/10 (nhẹ tay từ Đợt 2, giữ full rigor 3 lằn ranh).
- Dispatch song song task độc lập, không đợi tuần tự cứng nhắc — miễn 00-INDEX.md
  ghi "Chặn bởi: —".

## 8. Câu hỏi 🔴 CÒN TREO — hỏi người dùng khi tới lượt cần

- Cửa sổ idempotency 60s (T01) — đang dùng tạm.
- `REQUIRE_TURN_ID` có nên tồn tại không (T01/T04).
- Cache vị trí toàn cục hay theo device (T07, CONTRACTS §7 #9).
- Ai geocode `address → lat/lng` cho T11 (§7 #2).
- Quyền partner Farefeed đã xin chưa (T11).
- Ngân sách `ocr` là bao nhiêu (T15/T21, §7 #3).
- `max_age_ms` cho `/frame` (T17, §7 #10): đang dùng tạm 6000 ms + wait 800 ms,
  phải thay bằng số board thật trước release.
- P1 `contact_list` phía app có làm được không (T08, §7 #8).
