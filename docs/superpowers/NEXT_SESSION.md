# Session kế tiếp: đọc file này trước

Cập nhật 2026-10-20 (chiều). VH = `SeeVia_system/visioncare-host-demo`, AB = `SeeVia_system/app-demo-backend` (code `server/`),
cả hai nhánh `voice-v2-hardening`, CHƯA push (chưa được bảo thì không push/merge vào main).

**Tiết kiệm token (người dùng yêu cầu):** xem memory `seevia-toi-uu-token-dieu-phoi`. Gộp task cho 1 agent sonnet, review chỉ
bảo mật + 1 review cuối, hand-back ≤ 5 dòng, ít nhắn trạng thái. Trả lời tiếng Việt, ngắn.

## Đã xong

- Plan `plans/2026-10-20-modes-demo-app-protocol.md` (đã gộp VH + AB):
  dẫn đường = gửi `maps_url` Google Maps về điện thoại, người dùng tự chạm (bộ định tuyến riêng để sau);
  tránh vật cản = chế độ riêng `alert_on/alert_off`, chỉ kêu mức ≥ `HAZARD_MIN_LEVEL`=2;
  khung debug `hello.debug` (trace/say/det/ocr/mode); demo-web mới giao diện TRẮNG, chỉ 1920×1080 (`demo-web/README.md`);
  `AB/docs/MOBILE_APP_PROTOCOL.md` (giao thức app).
- Plan 2 `plans/2026-10-19-glasses-calls-messages.md` (có mục "Sửa đổi 2026-10-20" + Task C0):
  - VH đã gộp: C0 (token theo từng kính), C5 (cầu âm thanh, `WS /v2/call`, `/internal/calls`).
  - VH: C6 (gọi điện/khẩn cấp phía kính) + C7 (nhắn tin, 489 pass) ĐÃ gộp vào `voice-v2-hardening`.
  - AB nhánh `wt-calls` (worktree `../ab-wt-calls`): C1 care_links, C2 calls, C3 messages, C4 emergency (eb8ef3f). CHƯA gộp.

Ledger chi tiết (quyết định "Ruling:", minor hoãn): `VH/.superpowers/sdd/2026-10-19-glasses-calls-messages/progress.md`
và `.../2026-10-20-modes-demo-app-protocol/progress.md` (git-ignored). Report từng task cùng thư mục.

## Còn lại (theo thứ tự)

1. Gộp `wt-calls` → AB `voice-v2-hardening`
   (chạy toàn bộ test hai repo sau gộp; AB cần `PYTHONPATH=$PWD/src` + Postgres
   `compose.test.yaml` cổng 55432; test `test_committed_openapi_artifacts_are_up_to_date` chỉ hỏng trong worktree).
2. C8 (1 agent): `AB/scripts/relative_sim.py`, `VH/tools/e2e_calls.py`, viết phần gọi điện/nhắn tin vào
   `AB/docs/MOBILE_APP_PROTOCOL.md` (KHÔNG file riêng), `FIRMWARE_ENDPOINTS.md` khung cuộc gọi. Dùng hợp đồng trong report C2–C7.
3. Review cuối toàn nhánh (opus), đưa vào các dòng `minor (deferred)` + `Ruling:` của 2 ledger; MỘT lượt sửa.
   Điểm cần xem: `VISIONCARE_USER_ID` một user cho cả server (AB nên suy user từ kính); C6 đã sửa hành vi C5 (chưa review);
   STT nghe nhầm "bật cảnh báo vật cản"; e2e `sc_alert` cần ảnh vật cản mức 2.
4. C9 đo qua Cloudflare: cổng 18888 đang có server người dùng chạy — HỎI trước khi tắt/bật lại.
5. Dọn worktree `../vh-wt-*`, `../ab-wt-*` (đã gộp), xoá thư mục SDD; cập nhật `docs/HANDOFF_VOICE_V2.md`.

## Điều người dùng đã chốt (đừng hỏi lại)

- Ưu tiên độ trễ thấp nhất, rồi chính xác; đo p50/p90 trước/sau; chỉ giữ thay đổi nhanh hơn. Chỉ tối ưu Gemma; Clef dự phòng.
- Khoá token MỌI endpoint kính. App điện thoại người dùng tự làm; không sửa `mobile/`.
- Hỏi trước khi gỡ/cài gói trong `~/.venvs/seevia`; GPU: chọn GPU trống, không lùi CPU. Không `source` file `.env`.
- UI SeeVia qua skill `ui-ux-pro-max`; nhận diện navy #041466 (memory `seevia-brand-identity-ui-logo`).
