# Session kế tiếp: đọc file này trước (đủ để điều phối, không cần đọc lại codebase)

Cập nhật 2026-10-19. Repo `SeeVia_system/visioncare-host-demo` ("VH"), nhánh `voice-v2-hardening`
(không push). App server: `SeeVia_system/app-demo-backend/server` ("AB", repo git riêng).

## CHẾ ĐỘ NHANH

Đọc mục "CHẾ ĐỘ NHANH" đầu plan 1 — nó đè lên mọi thứ: luồng đúng + độ trễ thấp nhất,
gold 200–300 mẫu, ít test, chỉ review task rủi ro, có thêm Task 2b (VAD).

## Vai của session này

Điều phối, không tự code. Dùng skill `superpowers:subagent-driven-development`; **mọi
implementer và reviewer là subagent `model: sonnet`** (người dùng muốn tiết kiệm token
Claude). Không đọc toàn bộ codebase; subagent tự đọc phần nó cần.

## Đọc theo thứ tự (chỉ những file này)

1. Ledger plan 1: `VH/.superpowers/sdd/2026-10-19-voice-v2-hardening/progress.md` (git-ignored,
   nằm trên đĩa). Dòng `Task N: complete` = xong, đừng làm lại.
2. Plan 1: `VH/docs/superpowers/plans/2026-10-19-voice-v2-hardening.md` (17 task + 15b).
   Spec: `VH/docs/superpowers/specs/2026-10-19-voice-v2-hardening-design.md`.
3. Plan 2 (làm SAU khi plan 1 xong Task 15): `VH/docs/superpowers/plans/2026-10-19-glasses-calls-messages.md`,
   spec `VH/docs/superpowers/specs/2026-10-19-glasses-calls-messages-design.md`. Plan 2 dùng workspace riêng
   (`bash <skill>/scripts/sdd-workspace <plan2>`).

Brief cho từng task: `bash ~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.0/skills/subagent-driven-development/scripts/task-brief <plan> <N>`.
Ràng buộc chung đã tách sẵn: `VH/.superpowers/sdd/2026-10-19-voice-v2-hardening/global-constraints.md`
(đưa đường dẫn này cho mọi implementer/reviewer). Báo cáo: `.../task-N-report.md`.

## Trạng thái lúc bàn giao (2026-10-19 ~20:30)

- Commit mốc `94e6785` (toàn bộ v2 trước khi sửa); các commit docs/plan của controller tới `9e9feff`.
- **Task 1 (tập gold) gần xong, chưa commit.** Người dùng chốt: **~250 mẫu là đủ, chốt luôn**.
  Lúc bàn giao `tools/intent_gold/build.py --stage all` đang ở bước `adjudicate` (214 câu sạch:
  eval 121, suspect 25, rejected 20, train 6, sol sinh 42; 25 câu lệch đang phân xử). Biến thể
  STT chỉ làm nếu < 10 phút trên GPU trống, không thì bỏ.
  Session mới kiểm: `git log --oneline 9e9feff..`; `ls data/intent/gold_dev.jsonl data/intent/gold_test.jsonl`;
  `.superpowers/sdd/2026-10-19-voice-v2-hardening/task-1-report.md`; `tail data/intent/gold_work/build_all.log`;
  `pgrep -af intent_gold`.
  - Có gold_dev/test + commit → Task 1 xong (không cần review — chế độ nhanh), ghi
    `Task 1: complete` vào ledger, sang Task 2.
  - Chưa có, tiến trình đã chết → giao một subagent sonnet: "chạy `--stage adjudicate` rồi
    `--stage split` (cache ở `data/intent/gold_work/`, KHÔNG chạy lại relabel/generate), bỏ
    variants nếu > 10 phút, chạy `tests/test_intent_gold.py`, commit code `tools/intent_gold/` +
    4 file `data/intent/gold_*`". Chạy TTS phải đặt `CUDA_VISIBLE_DEVICES=<GPU trống>`.
- **Tiếp theo:** Task 2 (bộ đo intent) → Task 2b (VAD) → Task 3 … theo plan 1. Brief đã tách sẵn:
  `.superpowers/sdd/2026-10-19-voice-v2-hardening/task-2-brief.md`, `task-2b-brief.md`.
  Mẫu prompt dispatch: xem dispatch Task 1 trong ledger — luôn đưa đường dẫn brief + `global-constraints.md`
  + đường dẫn report, yêu cầu trả lời ≤ 15 dòng.
- Task 17 bước 3 (đo qua Cloudflare) và C9 do session điều phối tự chạy: bật server cổng 18888,
  đo, tắt ngay (`fuser -k 18888/tcp`) — server công khai qua tunnel.

## Điều người dùng đã chốt (đừng hỏi lại)

- Ưu tiên: độ trễ thấp nhất, rồi chính xác nhất. Đổi gì cũng đo p50/p90 trước/sau.
- sol 6.1 qua 9router (`localhost:20128`, khoá trong `SeeVia_system/.env`) chỉ dùng offline
  (tạo/chấm gold), không trên đường chạy thật. Tra web = SerpAPI (người dùng sẽ cấp khoá).
- Khoá token MỌI endpoint kính kể cả `/process`; viết `docs/FIRMWARE_ENDPOINTS.md` cho firmware.
- Một WebSocket phiên `/v2/session` cho kính. Làn D: đọc lại rồi mới gửi lệnh, bấm nút để huỷ.
- App điện thoại người dùng tự làm (clone về máy họ); server không sửa `mobile/`, chỉ viết hợp đồng.
- Gọi điện/nhắn tin: kính nghe-nói qua server; tín hiệu kính → VH → AB → app người thân, âm
  thanh kính ↔ VH ↔ app (không qua AB). Người thân là user của app hiện tại. Khẩn cấp = gọi người thân.
- Người dùng sẽ bật app server `:8001` thật khi cần đo làn D thật.
- Hỏi trước khi gỡ/cài gói trong `~/.venvs/seevia`; GPU: chọn GPU trống, không lùi về CPU.

## Câu trả lời cho người dùng

Viết tiếng Việt, ngắn. Không có câu hỏi nào đang chặn việc.
