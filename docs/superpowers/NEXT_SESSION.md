# Session kế tiếp: đọc file này trước

Cập nhật 2026-10-20 (tối). VH = `SeeVia_system/visioncare-host-demo`, AB = `SeeVia_system/app-demo-backend` (code `server/`),
cả hai nhánh `voice-v2-hardening`, CHƯA push (chưa được bảo thì không push/merge vào main). Không còn worktree phụ.

**Tiết kiệm token (người dùng yêu cầu):** xem memory `seevia-toi-uu-token-dieu-phoi`. Gộp task cho 1 agent sonnet, review chỉ
bảo mật + 1 review cuối, hand-back ≤ 5 dòng, ít nhắn trạng thái. Trả lời tiếng Việt, ngắn.

## Đã xong

- Plan modes/demo/app-protocol (2026-10-20) và plan 2 gọi điện/nhắn tin (C0–C8) đã gộp hết, kể cả AB `wt-calls`.
- Review cuối (opus) + MỘT lượt sửa: VH `53cc680`, AB `5489faf` — AB suy chủ kính từ `glasses_device_id`; khẩn cấp không dừng khi kính
  rớt phiên; demo-web không chuyển tiếp `/internal/*`; token che trong log; 8 minor. Báo cáo: `final-review.md`, `final-fix-report.md`.
- STT (VH `cf42a0d`, gộp `wt-stt`): Zipformer-30M giữ, đổi `modified_beam_search` 4 đường + hotword (từ lệnh + tên người thân).
  Đúng từ khoá lệnh +3,6..+6,9 điểm, intent +0,4..+1,0 (bất đồng +33/−16), p90 giải lượt cuối +22..27 ms. `STT_DECODING=greedy_search` để lùi.
  Báo cáo: `stt-opt-report.md`.
- Test: VH 515 pass + 2 skip; AB 420 pass (có `TEST_DATABASE_URL`, Postgres test cổng 55432); `tools/e2e_calls.py` 11/11 local.
- Spec app Android SeeVia tách session riêng: `AB/docs/superpowers/NEXT_SESSION_APP.md`.

Ledger + report: `VH/.superpowers/sdd/2026-10-19-glasses-calls-messages/` (git-ignored; giữ tới khi xong C9).

## Còn lại (theo thứ tự)

1. **Nối hotword tên người thân:** `stt.set_user_hotwords(names)` đã có nhưng VH chưa có nguồn tên. Lấy alias từ AB care_links của chủ kính
   (theo `glasses_device_id`), cache, làm mới khi đổi. Không nối thì mức "tên 97–98%" chưa có thật.
2. **Hồi quy STT/intent nhỏ:** "bật cảnh báo vật cản" 15/18 → 14/18 clip với hotword; "Mẹ vừa nhắn gì" 2 clip bị hiểu thành gửi tin
   (đã có đọc lại + cửa sổ huỷ). Xem mục cuối `stt-opt-report.md`.
3. `sc_alert` của `tools/e2e_full.py` chưa chạy lại với ảnh vật cản mức 2 mới trong repo.
4. **`SeeVia_system/.env` có khoá trùng khác giá trị** (`FIELD_ENCRYPTION_KEY` dòng 2/24, `PUBLIC_API_TOKEN_HASH` 4/20,
   `DEVICE_API_TOKEN_HASH` 7/23) — người dùng phải chọn bản đúng; KHÔNG tự xoá (sai khoá mã hoá = mất dữ liệu).
5. C9 đo qua Cloudflare: cổng 18888 đang có server người dùng chạy — HỎI trước khi tắt/bật lại. Sau đó cập nhật `docs/HANDOFF_VOICE_V2.md`
   và xoá thư mục SDD.

## Điều người dùng đã chốt (đừng hỏi lại)

- Ưu tiên độ trễ thấp nhất, rồi chính xác; đo p50/p90 trước/sau. Riêng STT: chính xác hơn trên cả hai bàn đo thì cho chậm ≤ 50 ms p90.
- Gọi/nhắn qua internet kiểu Messenger, chỉ thoại, KHÔNG video, KHÔNG SIM; RIÊNG khẩn cấp giữ SIM làm dự phòng.
- Khoá token MỌI endpoint kính. App Android giờ Claude làm (session riêng, xem AB `NEXT_SESSION_APP.md`).
- Hỏi trước khi gỡ/cài gói trong `~/.venvs/seevia`; GPU: chọn GPU trống, không lùi CPU. Không `source` file `.env`.
- Hai file Firebase (`AB/mobile/app/google-services.json`, `~/.config/seevia/firebase-adminsdk.json`) bảo mật: không commit/copy/in.
- UI SeeVia qua skill `ui-ux-pro-max`; nhận diện navy #041466 (memory `seevia-brand-identity-ui-logo`).
