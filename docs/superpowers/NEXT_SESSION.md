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

## Trạng thái lúc bàn giao (2026-10-19 ~20:40)

- Commit mốc `94e6785` (toàn bộ v2 trước khi sửa); các commit docs/plan của controller tới `9e9feff`.
- **Task 1 XONG** (commit `5b6ac31`): gold 267 dòng — dev 160, test 107 (211 câu sạch + 56 biến thể
  STT SNR 10 dB), 3 câu chờ người dùng duyệt ở `data/intent/gold_review.jsonl`. Lưu ý: test nhỏ →
  so A/B bằng câu bất đồng (McNemar), không bằng trung bình; `alert_on` chỉ 4 nhóm; sol qua 9router
  không tin được `response_format` lồng nhau (đã xử lý bằng prompt + parse).
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
