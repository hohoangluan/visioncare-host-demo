# Brief G — Mở khoá gọi / nhắn trên stack thật (máy 156)

Người dùng đã cho phép: tạo tài khoản, cấp token riêng cho kính, cấu hình AB/VH thật. Đọc trước:
`SeeVia_system/docs/2026-10-21-han-che-chay-full-e2e.md` mục 2 và 4. VH = `visioncare-host-demo`, AB = `app-demo-backend`.
`tools/e2e_calls.py` (VH) đã dựng sẵn đúng chuỗi này trên stack RIÊNG — đọc để biết cách đăng ký/OTP/mời/chấp nhận/token riêng, rồi làm y vậy
trên stack THẬT.

## Stack thật đang chạy (không dựng stack mới)
- AB native `127.0.0.1:18001`, venv `~/.venvs/seevia-ab`, env `~/.config/seevia/ab.env`, log `~/.local/state/seevia/ab.log`,
  DB container `seevia-ab-pg` (user/db `app_demo`). Hiện: 0 users, 0 care_links, 1 `glasses_devices` (`glasses-123`), 1 `devices` (điện thoại thật, chưa gắn user).
- VH `127.0.0.1:18888` (uvicorn, venv `~/.venvs/seevia`, chạy với `VISIONCARE_HOST_URL=http://127.0.0.1:18001` ghi đè `.env`).
  `demo-web/serve.py` ở 18080 và 18443 (`--lan`) gắn token kính vào WS cho `client.html` (mã kính `glasses-123`).

## Mục tiêu (phương án controller chốt)
- Điện thoại thật = tài khoản CHỦ KÍNH (tên hiển thị "Chủ kính" hoặc tên người dùng nếu đã có), chủ của `glasses-123`.
  Đăng nhập trên điện thoại thật: controller sẽ làm qua adb khi tunnel lên — bạn chuẩn bị số điện thoại + cách lấy OTP (dev) và ghi rõ vào report.
  Nếu AB cho phép gắn `devices` hiện có vào user bằng API đăng nhập thì ghi lại bước, KHÔNG sửa tay DB trừ khi không còn cách nào (ghi lý do).
- "em iu" = tài khoản AB thật, người thân của chủ kính (care invite → accept), alias "em iu", `emergency=true`, priority 0.
  Do `relative_sim.py` (AB `server/scripts/`) đóng vai: chạy nền lâu dài (nohup, log ở `~/.local/state/seevia/`), tự nghe máy, phát âm thanh
  (nếu có tuỳ chọn), trả lời tin nhắn tự động một câu ngắn để kiểm hai chiều. Ghi lệnh chạy lại vào report.
- Token riêng cho kính: tạo token mới cho `glasses-123` (dùng `tools/device_token.py` nếu đúng việc), file `{device_id: sha256}` quyền 600 ở
  `~/.config/seevia/device_tokens.json`, VH đọc qua `VISIONCARE_DEVICE_TOKENS`. Token thô cho `serve.py`: đặt sao cho `serve.py` gắn token RIÊNG
  (đọc code serve.py xem nhận từ biến nào; nếu cần thêm tuỳ chọn `--token-file` thì sửa serve.py + test, commit nhánh `app-giao-tiep`).
  Token chung cũ vẫn phải chạy cho kính thật khác nếu có (đừng phá).
- KHÔNG tự restart VH 18888 / serve.py: agent khác đang sửa code VH. Viết sẵn script `~/.local/state/seevia/restart_vh.sh` (dừng tiến trình
  VH + 2 serve.py đang chạy, chạy lại đúng lệnh hiện tại — lấy từ `ps` — cộng biến môi trường mới, log về `~/.local/state/seevia/`, chờ /health 200).
  Controller sẽ chạy nó. AB thì được restart nếu cần (`ab.env`), ghi lại.

## Kiểm (sau khi controller restart VH; trước đó kiểm được phần AB bằng API)
- AB: `care_links` có em iu active; relative_sim đang chạy và nhận được webhook/FCM giả lập.
- Viết script `SeeVia_system/visioncare-host-demo/demo-web/e2e/check_calls_live.py`: gửi lệnh giọng (clip tổng hợp như `full_tour.py`)
  qua WS kính giống `client.html` → "gọi em iu", "nhắn em iu là con về muộn", "đọc tin nhắn"; kiểm gọi được nối (có khung âm thanh hai chiều),
  em iu nhận đúng nội dung tin, tin trả lời được kính đọc. Chạy được sau khi controller restart.

## Ràng buộc
- Không in/commit/copy token, khoá mã hoá, hai file Firebase; không `source` `SeeVia_system/.env`; không đụng volume `seevia_postgres_data` cũ.
- KHÔNG gọi adb (tunnel điện thoại qua cổng 5037 sẽ hỏng nếu adb tự khởi daemon cục bộ).
- Không gửi SOS/khẩn cấp thật.

## Bàn giao
`SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-G.md`: tài khoản (số điện thoại, KHÔNG token), cách lấy OTP, lệnh relative_sim, script restart,
bước đăng nhập điện thoại thật. Trả lời controller ≤ 5 dòng.
