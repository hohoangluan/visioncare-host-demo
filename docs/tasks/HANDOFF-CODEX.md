# HANDOFF — để Codex (hoặc bất kỳ agent nào khác) tiếp tục chương trình 23-task

Viết ngày 2026-08-22. Claude Code (dùng skill `superpowers:subagent-driven-development`)
đã điều phối chương trình này tới giữa **Đợt 3**. Tài liệu này thay thế skill đó cho
một công cụ không có sẵn nó — đọc xong file này là đủ để tiếp tục đúng kỷ luật.

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

Xem bảng đầy đủ ở `docs/tasks/PROGRESS.md` (đã commit). Tóm tắt tới lúc viết file này:

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
| 3 | T06 Bảng chính sách slot | ✅ | **CHƯA COMMIT** — đợi T05 xong để commit cùng đợt |
| 3 | T05 Intent & schema slot | 🟡 **ĐANG CHẠY** — agent bị giới hạn phiên giết 2 lần, đã resume, chưa có kết quả cuối |
| 4-7 | T08-T23 còn lại | ⬜ chưa bắt đầu |

**Việc đang treo (không chặn, nhưng phải làm trước khi coi là xong thật):**
- Số đo phần cứng T22 (`docs/tasks/measurements/F9.md`) — cần board thật + arduino-cli,
  dồn về gần T21 theo Ruling 8.
- G11 (`docs/tasks/measurements/G11.md`) cần đo lại MỘT MÌNH (không có tải CPU song
  song) trước khi chốt số cho T21 — số hiện tại dao động 0.94x-2.59x vì đo lúc 5 agent
  khác chạy cùng máy.

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

4. **`handlers/phone.py`, `navigation.py`, `ride.py`, `music.py` còn giữ hằng số
   `_ASK_*` trùng với `slots.py` — dọn khi T08/T10/T11/T12 (chủ 4 file đó) chạm
   tới.** Vô hại (dedupe theo `phrase_key`), không phải bug chặn, chỉ là dọn nợ.

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

## 6. Việc còn lại — 18 task, theo đúng thứ tự RUNBOOK

**Đợt 3 (đang dở):** T05 (đang chạy, bị giới hạn phiên giết 2 lần, đã resume lần
cuối lúc viết file này — kiểm agent đó trước khi dispatch gì mới) ‖ T06 (DONE, chưa
commit — commit CÙNG LÚC với T05 khi cả hai xong, vì cùng review một wave).

**Đợt 4 — 6 nhánh song song (Ruling 3/4 ở mục 3):** T08 (gọi danh bạ, PARTIAL —
chờ app team P1), T09 (khẩn cấp, 🔴 giữ full rigor), T10 (chỉ đường, PARTIAL — chờ
T20 D4 đã xong nên có thể gỡ phần đó), T12 (nhạc), T14 (OCR ngữ cảnh — nối phần
H1/H3/H5 T15 đã xây sẵn), T16 (không gian & vật cản).

**Đợt 5:** T13 (chat & lịch sử — nối `_remember`/history T14 để dở), T11 (đặt xe,
🔴 giữ full rigor, PARTIAL chờ Farefeed), T23 (quyền & cấu hình, dùng emulator
Android đã cài).

**Đợt 6 — tuần tự (không song song, xây thẳng lên nhau):** T17 (tách `/frame`,
🔴 F2 KHÔNG thi công) → T18 (SSE downlink) → T19 (cuộc gọi đến, cả 4 repo).

**Đợt 7:** T21 (ngân sách độ trễ — 🔴 PHẢI SAU T02+T22, và phải đo TRÊN BẢN TLS=1
thật, nghĩa là làm số đo phần cứng T22 CÒN TREO ở đây trước).

**Cuối:** Task 9 trong plan — chạy 5 cổng phát hành, kiểm 12 việc-không-được-làm ở
RUNBOOK mục 7, viết `FINAL-REPORT.md`, final whole-branch review (dùng model mạnh
nhất có), rồi mới `superpowers:finishing-a-development-branch` (hoặc tương đương
nếu Codex không có skill đó — về cơ bản: xin merge/PR, không tự merge vào main).

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
- `max_age_ms` cho `/frame` (T17, §7 #10).
- P1 `contact_list` phía app có làm được không (T08, §7 #8).
