# Session kế tiếp: đọc file này trước

Cập nhật 2026-10-20. Repo `SeeVia_system/visioncare-host-demo` ("VH"), nhánh `voice-v2-hardening`
(chưa push). App server `SeeVia_system/app-demo-backend/server` ("AB", repo git riêng, nhánh `voice-v2-hardening`).

## Trạng thái

**Plan 1 XONG**: gộp vào `voice-v2-hardening` = `5963ad5` (+ commit docs), test **429 pass / 2 skip**. Số đo, E2E, Cloudflare và
việc còn lại của người dùng: `docs/HANDOFF_VOICE_V2.md`. Giao thức firmware: `docs/FIRMWARE_ENDPOINTS.md`.
Còn dọn: các worktree `../vh-wt-*` đã gộp (`git worktree remove`) và workspace SDD của plan 1
(`.superpowers/sdd/2026-10-19-voice-v2-hardening/`, git-ignored); quyết việc push/merge vào `main` cùng người dùng (chưa bảo thì không làm).

Quy ước làm việc: điều phối, không tự code; skill `superpowers:subagent-driven-development`; implementer/reviewer là subagent
`model: sonnet`, review cuối dùng opus; task độc lập chạy song song, mỗi task một worktree `../vh-wt-<N>` (symlink asset bị ignore:
`models/hazard models/stt models/text_det models/.cache models/vad certs .env tests/fixtures/*`). KHÔNG `source` file `.env` trong
shell (từng lộ khoá); đọc bằng Python. Token đã thống nhất: `SeeVia_system/.env` là nguồn duy nhất, `VH/.env` giữ bản sao.

## PLAN 2 — gọi điện / nhắn tin từ kính (người dùng: KHÔNG làm trong session plan 1)

Plan `VH/docs/superpowers/plans/2026-10-19-glasses-calls-messages.md`, spec
`VH/docs/superpowers/specs/2026-10-19-glasses-calls-messages-design.md`. Bắt đầu SAU khi plan 1 gộp xong (đã xong).
Workspace riêng: `bash ~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.0/skills/subagent-driven-development/scripts/sdd-workspace <plan2>`;
brief từng task: `.../scripts/task-brief <plan2> <N>`. Chế độ nhanh trong plan 1 cũng áp cho plan 2 (review chỉ C2, C5 + cuối).
Trước khi chạy, quét plan 2 đối chiếu với những gì plan 1 đã đổi:
- giao thức `WS /v2/session` thật (`live/device_session.py`, `docs/FIRMWARE_ENDPOINTS.md`), hàng đợi audio theo phiên, khung `result-*`
  server chủ động gửi — plan 2 gọi điện/nhắn tin phải dùng chung hàng đợi này;
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
