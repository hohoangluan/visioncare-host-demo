# Session kế tiếp: đọc file này trước (đủ để điều phối, không cần đọc lại codebase)

Cập nhật 2026-10-19 ~23:00. Repo `SeeVia_system/visioncare-host-demo` ("VH"), nhánh `voice-v2-hardening`
(không push). App server `SeeVia_system/app-demo-backend/server` ("AB", repo git riêng, nhánh `voice-v2-hardening`).

## Vai của session này

Điều phối, không tự code. Skill `superpowers:subagent-driven-development`; implementer/reviewer là subagent
`model: sonnet` (tiết kiệm token). Task độc lập chạy SONG SONG, mỗi task một git worktree `../vh-wt-<N>`
(nhánh `wt-task-<N>`, symlink asset bị ignore: `models/hazard models/stt models/text_det models/.cache models/vad
certs .env tests/fixtures/*`), implementer tự rebase lên `voice-v2-hardening`, controller `git merge --ff-only`.
Không resume mãi một agent đã phình context — dừng, commit WIP, giao agent mới với brief trong file.
KHÔNG `source` file `.env` trong shell (từng lộ khoá); đọc bằng Python.

Ledger: `VH/.superpowers/sdd/2026-10-19-voice-v2-hardening/progress.md` (git-ignored, trên đĩa) — đủ mọi
task/ruling/minor. Ràng buộc chung cho subagent: `.../global-constraints.md`. Báo cáo: `.../task-<N>-report.md`.

## PLAN 1 — gần xong. Còn đúng 4 việc

**Trạng thái:** mọi task 1–17 (+2b, 4c, 4d, 15A, 15b-A) đã gộp vào `voice-v2-hardening` = `71f2659`
(+ `076dd83` đổi biến `NINE_ROUTER_*`). Test 416 pass / 2 skip / 0 fail. Review cuối toàn nhánh (opus) xong:
`.../final-review.md` — "ready with fixes".

1. **Đợt sửa cuối — giao cho subagent `model: opus` (người dùng: "khó quá thì giao cho opus").** Đã dừng giữa
   chừng 2 lần (hết quota). Worktree `../vh-wt-15B`, nhánh `wt-task-15B`: `9e05470` WIP B1–B4 (agent 1) và
   `76254ec` WIP 2 (agent 2 đã sửa ~20 file: app.py, device_session, ws_adapter, nav_live, ocr_live, final_router,
   intent_classifier, pending_action, stt_stream, search/client, Dockerfile… — **CHƯA viết test, CHƯA chạy test**).
   Brief đầy đủ: `.../fixwave-brief.md` (E2E B1–B4 + review C1, I1–I5 + 3 minor + aclose); file:line ở
   `.../final-review.md`. Dispatch: "đọc fixwave-brief.md; tiếp tục trong vh-wt-15B, `git show 9e05470 76254ec`
   để xem phần đã làm, kiểm từng mục brief làm đúng chưa, viết test còn thiếu, chạy toàn bộ test, E2E chỉ các
   kịch bản từng FAIL (call_mom, call_nam, ride, music, nav, emergency, call_cancel), gộp thành một commit sửa".
   Dọn trước khi chạy: `fuser -k 18893/tcp 18001/tcp 18002/tcp`; kiểm container postgres test của AB.
2. **Re-review có phạm vi** đợt sửa (sonnet, `re-review-prompt.md` của skill) với danh sách mục trong
   fixwave-brief.md; nếu sạch → `git merge --ff-only wt-task-15B` vào `voice-v2-hardening`, chạy toàn bộ test.
3. **Đo qua Cloudflare (Task 17 bước 3, controller tự chạy):** bật server cổng 18888 (lệnh ở
   `docs/HANDOFF_VOICE_V2.md` mục "Chạy lại"), bench `tools/bench_live.py` POST và `--ws`, local và
   `--base https://api.visioncare-host.uk --resolve api.visioncare-host.uk=104.21.67.134`, `--runs 4`; token:
   bench đọc `VISIONCARE_DEVICE_CLIENT_TOKEN` từ môi trường — nạp từ `VH/.env` bằng Python (wrapper mẫu đã viết ở
   scratchpad cũ: đọc dòng `VISIONCARE_DEVICE_CLIENT_TOKEN=` rồi `runpy` bench). **Tắt ngay** `fuser -k 18888/tcp`
   (server công khai qua tunnel). Người dùng từng huỷ lệnh bench dài — hỏi trước khi chạy, hoặc chạy từng chế độ một.
   **Chưa có số Cloudflare nào.** Đã có số LOCAL POST và WS trên `71f2659` (trước đợt sửa):
   `.superpowers/sdd/2026-10-19-voice-v2-hardening/cf-bench/local_post.txt`, `local_ws.txt`; wrapper nạp token:
   `cf-bench/run_bench.py` (chạy từ thư mục VH). Đo lại sau khi gộp đợt sửa (đợt sửa đổi thời điểm bắt đầu cửa
   sổ huỷ và hàng đợi audio). "Tối ưu Cloudflare" = so POST vs `WS /v2/session` qua tunnel; nếu WS không nhanh
   hơn rõ, tìm chỗ dồn độ trễ (TLS/handshake mỗi lượt, kích thước khối audio, ping) trước khi đổi gì.
4. **Tài liệu + bàn giao (một agent sonnet):** (a) hoàn thiện `docs/FIRMWARE_ENDPOINTS.md` thành hướng dẫn
   firmware code theo được — người dùng dặn rõ "ghi lại kính cần làm gì, endpoint giao tiếp các thứ để kính code
   theo": checklist việc kính phải làm (bật máy → kết nối → bấm/nhả nút → phát audio theo hàng đợi → hazard → rớt
   mạng/mở lại), mọi khung kể cả `result-*` (B1), hàng đợi audio (I4), đọc lại + bấm huỷ + "…phải không?",
   nav sống qua lượt mới, `played`, cue clips `assets/cues/`, `/process`; đối chiếu với kết quả E2E thật.
   (b) viết lại `docs/HANDOFF_VOICE_V2.md` (đã sửa gì kèm số, còn lại gì cho người dùng). Rồi commit, xoá các
   worktree đã gộp (`git worktree remove`), xoá workspace SDD của plan 1, skill `finishing-a-development-branch`
   (không push/merge vào main nếu người dùng chưa bảo).

## Số liệu chính (để viết bàn giao)

- Intent Gemma: test acc 0,888 → 0,953, lệnh làn D nhầm 7 → 0; p50 264 → ~74 ms, p90 → ~83 ms
  (nhãn ngắn `structured_outputs` choice, `INTENT_FORMAT=label`; ocr_mode/needs_web bằng luật `INTENT_AUX=rules`;
  quay lại: `INTENT_FORMAT=json` / `INTENT_AUX=gemma`). Ngưỡng `ACTION_MIN_CONFIDENCE=0.999` (thấp hơn thì 1–2 FP;
  confidence dao động 0,998–0,999 giữa các lần chạy). Hỏi lại ~10% lệnh làn D.
- VAD (Silero): nhả nút → tiếng đầu p50 824 → 682 ms; giữ nút 1 s sau khi nói 769 → 464 ms.
- Tải: N=4 kính p90 chat 1,52× N=1 (nút thắt TTS dùng chung GPU, không phải Gemma); `docs/benchmarks/LOAD_V2.md`.
- E2E: `docs/E2E_FULL_FLOW.md` (bảng sẽ cập nhật sau đợt sửa), `docs/E2E_REAL_PHONE.md` cho máy thật.

## Rulings controller đã chốt (đưa vào bàn giao cuối, mục "Quyết định tôi đã thay bạn")

Toàn văn trong ledger (`grep Ruling progress.md`). Tóm tắt: song song qua worktree; ngưỡng 0,999; nhãn ngắn thay
JSON; luật cho needs_web/ocr_mode; keyword không được kích làn D (trừ dừng/chỉnh nhạc, dừng chỉ đường); "có/đúng"
chỉ xác nhận khi cả câu ≤ 3 từ toàn từ đồng ý; trả lời slot vẫn xác nhận; +0,4 s trước khi lệnh chạy; nav không bị
lượt mới tắt (OCR live thì có); kết quả lệnh đọc chủ động qua phiên WS (`result-*`); bypass nhạc/nav chỉ khi bấm
nút không nói; giữ Clef làm dự phòng (người dùng chốt); review cuối dùng opus.

## Việc cần NGƯỜI DÙNG (ghi vào bàn giao)

- Khoá SerpAPI (chưa có → tra web luôn báo "không tra được").
- Token kính lệch: `VISIONCARE_DEVICE_CLIENT_TOKEN` trong `VH/.env` khác `VISIONCARE_CLIENT_TOKEN` trong
  `SeeVia_system/.env` — thống nhất trước demo.
- App server `:8001` thật + điện thoại thật (`docs/E2E_REAL_PHONE.md`); ghi âm giọng thật (VAD/STT mới thử bằng TTS).
- Giấy phép trọng số model giọng vieneu trên HF (gói vieneu Apache-2.0, không cài watermark).
- AB: `deadline_at = created_at + 1 s` trong `_command_data` có vẻ sai so với hợp đồng 30–90 s (app bỏ qua);
  app không bao giờ trả `NO_ACTIVE_PLAYBACK`, `emergency_call` luôn `answered:false`.

## PLAN 2 — bàn giao cho session khác (người dùng: KHÔNG làm trong session plan 1)

Plan `VH/docs/superpowers/plans/2026-10-19-glasses-calls-messages.md`, spec
`VH/docs/superpowers/specs/2026-10-19-glasses-calls-messages-design.md`. Bắt đầu SAU khi plan 1 gộp xong.
Workspace riêng: `bash ~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.0/skills/subagent-driven-development/scripts/sdd-workspace <plan2>`;
brief từng task: `.../scripts/task-brief <plan2> <N>`. Chế độ nhanh trong plan 1 cũng áp cho plan 2 (review chỉ
C2, C5 + cuối). Trước khi chạy, quét plan 2 đối chiếu với những gì plan 1 đã đổi:
- giao thức `WS /v2/session` thật (`live/device_session.py`, `docs/FIRMWARE_ENDPOINTS.md`), hàng đợi audio theo
  phiên, khung `result-*` server chủ động gửi — plan 2 gọi điện/nhắn tin phải dùng chung hàng đợi này;
- `pipeline/pending_action.py` (begin_turn/gen, cửa sổ huỷ tính từ audio đọc lại), cổng làn D 0,999 + hỏi lại;
- transport webhook + `scripts/phone_sim.py` ở AB (Task 15A/15b), fixtures `AB/tests/fixtures/server_payloads/`;
- **I6 từ review cuối phải vào plan 2:** hiện một token dùng chung cho mọi kính và `device_id` do client tự khai
  (`services/visioncare_client.py`) → ai có token đều kích lệnh trên kính khác. Plan 2 (gọi điện tới người thân)
  cần token theo từng kính / ràng buộc device_id với token.

## Điều người dùng đã chốt (đừng hỏi lại)

- Ưu tiên: độ trễ thấp nhất, rồi chính xác. Đổi gì cũng đo p50/p90 trước/sau. Chỉ giữ thay đổi đo ra nhanh hơn.
- Chỉ tối ưu Gemma; Clef giữ làm dự phòng khi Gemma lỗi.
- sol qua 9router (`NINE_ROUTER_API_KEY/URL/MODEL` trong `SeeVia_system/.env`) chỉ offline trong `tools/`.
- Khoá token MỌI endpoint kính. App điện thoại người dùng tự làm; không sửa `mobile/`.
- Hỏi trước khi gỡ/cài gói trong `~/.venvs/seevia`; GPU: chọn GPU trống, không lùi về CPU.

Trả lời người dùng: tiếng Việt, ngắn.
