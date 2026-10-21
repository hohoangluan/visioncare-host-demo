# Report G — Mở khoá gọi / nhắn trên stack thật (2026-10-21)

(Controller chép lại từ hand-back của agent G; agent không ghi được file.)

## Trạng thái
- Xong: chủ kính + ghép `glasses-123`; "em iu" + care_link; relative_sim chạy nền; AB gửi lai FCM/webhook (AB đã restart); token riêng + `serve.py --token-file`.
- Chưa: VH nạp token riêng (restart VH, mục 6); điện thoại thật đăng nhập chủ kính (mục 3); `check_calls_live.py` đủ ca.
- Cảnh báo: `glasses-123` giờ thuộc chủ `8EB1A80A`, điện thoại thật (`device-100`) vẫn thuộc `user-100` → lệnh kính→điện thoại lỗi "không có thiết bị" tới khi làm mục 3.

## 1. Tài khoản (AB 127.0.0.1:18001)
- Chủ kính: 0988000001, "Chủ kính", public_user_id `8EB1A80A`.
- em iu: 0988000002, "em iu", `5CB40CA5`. care_link chủ→em iu active, emergency=true, priority 0, alias ["em iu","em yêu"].
- Kính `glasses-123` → `8EB1A80A` active.
- Trạng thái: `~/.venvs/seevia-ab/bin/python app-demo-backend/server/scripts/live_calls_setup.py status`. Dựng lại (idempotent): `live_calls_setup.py owner --unlink-old user-100` rồi `live_calls_setup.py invite` (cần relative_sim đang chạy).
- Mật khẩu ngẫu nhiên trong `~/.config/seevia/live_accounts.json` (600); không in ra transcript.

## 2. OTP (dev)
`grep "Demo OTP for" ~/.local/state/seevia/ab.log | tail -1`. Hai tài khoản đã phone_verified → điện thoại chỉ cần đăng nhập số + mật khẩu.

## 3. Điện thoại thật đăng nhập chủ kính (qua adb/UI)
1. Tab đăng nhập: 0988000001 + mật khẩu → app ghi user_id `8EB1A80A`.
2. Tổng quan: KHÔNG bấm "tạo mới"; sửa ô device_id thành mã mới, vd `phone-chu-kinh` (giữ `device-100` sẽ 409 DEVICE_OWNER_MISMATCH, AB không có API đổi chủ thiết bị).
3. Bấm "Đăng ký" → FCM token + `/device/register` (8EB1A80A, phone-chu-kinh). Cần thì ghép tay `glasses-123` ở màn Kính (idempotent).
4. Kiểm: bảng `devices` có `8EB1A80A | phone-chu-kinh | active`. Dòng `user-100/device-100` cũ để nguyên.

## 4. relative_sim = em iu
- Chạy/chạy lại: `~/.local/state/seevia/start_relative_sim.sh` (`--stop` để dừng). Đổi câu tự trả lời không restart:
  `curl -s -X POST 127.0.0.1:18003/ctl/behavior -H 'content-type: application/json' -d '{"auto_reply":"Em đây"}'`.
- Tự nghe máy sau 1 s; media đi thẳng `ws://127.0.0.1:18888/v2/call`; phát im lặng + tiếng "tách" mỗi giây, ghi tiếng nhận vào `~/.local/state/seevia/relative_audio/`; nhận tin thì 1,5 s sau tự nhắn lại.
- Log: `relative_sim.jsonl`, `relative_sim.out`. Cổng 18003 (127.0.0.1). nohup chết khi VS Code server khởi động lại.

## 5. Code / cấu hình
- AB `07551dc` HybridDeliveryAdapter (token `sim*` đi webhook, token FCM thật đi FCM) + 21 test; AB `d129684` relative_sim `--media-url/--auto-reply/RELSIM_PASSWORD`, `live_calls_setup.py`.
- `~/.config/seevia/ab.env`: thêm `DELIVERY_WEBHOOK_URL=http://127.0.0.1:18003/push`; restart AB bằng `~/.local/state/seevia/restart_ab.sh`.
- VH `31777b4` `serve.py --token-file`; VH `babc9e5` `demo-web/e2e/check_calls_live.py`.
- Token riêng: `~/.config/seevia/device_tokens.json` (600, sha256), `~/.config/seevia/glasses-123.token` (600, token thô). Khi VH nạp file này, token chung không còn dùng được cho `glasses-123` → serve.py 18080/18443 PHẢI chạy với `--token-file`.

## 6. Restart VH + serve.py (cwd visioncare-host-demo)
1. Dừng uvicorn 18888 và hai `demo-web/serve.py` (18080, 18443).
2. `env -u VISIONCARE_USER_ID CUDA_VISIBLE_DEVICES=<gpu trống> VISIONCARE_HOST_URL=http://127.0.0.1:18001 VISIONCARE_DEVICE_TOKENS=$HOME/.config/seevia/device_tokens.json setsid nohup ~/.venvs/seevia/bin/python -m uvicorn app:app --host 127.0.0.1 --port 18888 --loop uvloop --http httptools --ws-max-size 2100000 >> ~/.local/state/seevia/vh.log 2>&1 < /dev/null &`
3. serve.py: `--port 18080 --upstream http://127.0.0.1:18888 --token-file $HOME/.config/seevia/glasses-123.token` và bản `--lan --port 18443` tương tự.
4. Chờ `/health` 200 (nạp model tới ~7 phút); `demo-web/e2e/check_calls_live.py --preflight` → "preflight OK".

## 7. Kiểm
- Đã: qua API với sim thật — tin tới em iu đúng nội dung, em iu tự trả lời, tin trả lời vào unread của kính; call_incoming → em iu tự nghe HTTP 200, nhận call_ended khi cúp.
- Chưa (cần mục 3 + 6): `check_calls_live.py --only call_em_iu message_em_iu read_messages` (gọi + dò tiếng tách hai chiều + trễ; nhắn "con về muộn"; kính đọc tin đến). Không có ca khẩn cấp.

## 8. Rủi ro / còn mở
1. Khoảng trống lệnh kính→điện thoại tới khi điện thoại đăng nhập.
2. Điện thoại thật dùng `CALL_MEDIA_URL=wss://api.visioncare-host.uk/v2/call` — chưa kiểm tới VH 18888.
3. `device-100/user-100` cũ còn trong `devices`.
4. Agent lỡ in `DATABASE_URL` (mật khẩu DB `app_demo`) vào transcript cục bộ; DB chỉ nghe 127.0.0.1 — xoay mật khẩu nếu muốn.
