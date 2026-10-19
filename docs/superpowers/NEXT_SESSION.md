# Session kế tiếp: đọc file này trước (đủ để điều phối, không cần đọc lại codebase)

Cập nhật 2026-10-19. Repo `SeeVia_system/visioncare-host-demo` ("VH"), nhánh `voice-v2-hardening`
(không push). App server: `SeeVia_system/app-demo-backend/server` ("AB", repo git riêng).

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

## Trạng thái lúc bàn giao

- Commit mốc `94e6785` (toàn bộ v2 trước khi sửa) → `70b28a3` (plan). Task 1 (dựng tập gold
  bằng sol) đã được giao cho subagent ở session trước, BASE `70b28a3`. Kiểm:
  `git log --oneline 70b28a3..`, `ls data/intent/gold_*.jsonl`, `.../task-1-report.md`.
  Có commit + report → chạy review Task 1. Không có → giao lại Task 1 (các bước của
  `tools/intent_gold/build.py` chạy lại được từ `data/intent/gold_work/` nếu đã có).
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
