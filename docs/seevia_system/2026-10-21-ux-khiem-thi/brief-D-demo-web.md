# Brief D — Bảng demo cho ban giám khảo (demo-web)

Repo VH `SeeVia_system/visioncare-host-demo`. Agent khác đang sửa `pipeline/`, `handlers/`, `lanes/` trên checkout chính → bạn làm trong worktree:
`git -C visioncare-host-demo worktree add ../wt-demo-ux -b demo-ux app-giao-tiep`. Chỉ sửa `demo-web/` (và `live/observers.py` nếu cần thêm dữ liệu quan sát,
kèm test). Commit trên nhánh `demo-ux`, kết commit bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Controller sẽ gộp.

Bối cảnh: `demo-web/README.md` + `demo-web/e2e/README.md`. `index.html` = bảng giám sát (giám khảo xem, màn 1920×1080, nền trắng),
`client.html` = kính giả lập (giữ để nói, camera). Nhận diện: navy `#041466`, Montserrat (font tự host trong `demo-web/assets`).
Bắt buộc gọi skill `ui-ux-pro-max` trước khi sửa giao diện.

## Việc
D1. Dòng hội thoại rõ ràng trên `index.html`: mọi lượt (không chỉ 2 câu đầu) — "Người dùng nói" (transcript), intent + làn, "Kính trả lời" (câu nói),
    độ trễ (đến tiếng đầu), trạng thái lệnh gửi điện thoại (đã gửi / đang làm / xong / lỗi). Lượt mới cuộn vào, cũ vẫn xem được.
D2. Cảnh báo vật cản / kết quả đọc chữ gắn ảnh thu nhỏ của đúng khung hình đó (JPEG 0x04 đã có ngay trước `det`/`ocr`).
D3. `client.html`: giữ phím Space để nói (ngoài nút), chỉ báo mức âm micro khi đang nghe, trạng thái đọc được bằng trình đọc màn hình
    (aria-live), nhãn rõ ràng. Nghe được tiếng kính trả lời (nếu đã có thì giữ).
D4. Đánh bóng tổng thể cho giám khảo: thứ bậc thông tin, chế độ đang bật dễ thấy, không chữ bị cắt ở 1920×1080, trạng thái rỗng/lỗi kết nối có câu rõ.
    Giữ `prefers-reduced-motion`.

## Kiểm
- Chạy `~/.venvs/seevia/bin/python demo-web/e2e/browser_e2e.py --mode fake` (và `--mode real` nếu được: chạy `serve.py` từ worktree ở cổng khác,
  vd 18090, upstream `http://127.0.0.1:18888`); so với `baseline-*.json`, không được tụt. Cập nhật baseline nếu có ca mới.
- `pytest tests/test_observe.py tests/test_demo_serve_proxy.py` xanh.
- Chụp 1 ảnh 1920×1080 `index.html` sau khi xong, lưu `SeeVia_system/docs/2026-10-21-ux-khiem-thi/demo-index.png`.
- KHÔNG mở cổng/tunnel công khai (serve.py tự gắn token kính).

## Bàn giao
Báo cáo `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-D.md`. Trả lời controller ≤ 5 dòng.
