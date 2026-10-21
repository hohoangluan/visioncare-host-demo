# Hạn chế còn lại sau lần chạy full end-to-end 2026-10-21

Chạy từ `client.html` (kính giả lập, Chromium thật) → VH 18888 → AB 18001 → điện thoại thật, người dùng xem ở `index.html`.
Đọc file này trước khi tối ưu. VH = `visioncare-host-demo`, AB = `app-demo-backend`.

Bằng chứng: `VH/storage/e2e-demo-web/tour-2026-10-21/` (22 ảnh bảng giám sát + `tour.log`; git-ignored).
Chạy lại: `~/.venvs/seevia/bin/python demo-web/e2e/full_tour.py A B C D E F G` (pha H = khẩn cấp thật, xem mục 2).
Đo STT: `demo-web/e2e/stt_ab.py 150` (model nguyên clip vs qua VAD) và `demo-web/e2e/stt_err.py` (phân loại kiểu sai).

## 1. Kết quả từng chức năng (pha A–G)

| Chức năng | Kết quả | Ghi chú |
|---|---|---|
| Tả cảnh (`space`) | Đạt | Đúng 2 xe tải |
| Quét vật cản (`hazard`) | Đạt | Báo hướng 11 giờ / 1 giờ |
| Hỏi đáp (`chat`) | Đạt | "Vịnh Hạ Long thuộc Quảng Ninh" |
| Bật / tắt cảnh báo vật cản | Đạt | Bật bị nghe thành "Cảnh báo vật cản" nhưng vẫn ra `alert_on` (đã biết) |
| Đọc chữ, ảnh rõ | Đạt | Đúng "CÔNG TRƯỜNG ĐANG THI CÔNG" |
| Đọc tiền | Đạt | "50 nghìn đồng" đúng ảnh |
| Đọc chữ trực tiếp (ảnh không chữ) | **Chưa kiểm** | STT nghe "Tiêu đê bảo" → rơi `chat` |
| Tìm đồ (`find`) | **Chưa kiểm** | STT nghe "Tràn nước suối" → rơi `chat` |
| Nhạc: to / nhỏ / dừng | Đạt | 26% → 13% → "Đã dừng phát nhạc" |
| Phát nhạc | Đạt một phần | "bolero" → "bullerro"; điện thoại hỏi lại ca sĩ, chưa trả lời |
| Dẫn đường | Đạt một phần | Gửi về điện thoại, mode `nav` sáng; điện thoại chỉ báo "vẫn đang thực hiện", chưa thấy kết quả cuối |
| Dừng dẫn đường | Đạt khi nói câu khác | "Dừng dẫn đường" → "Tin gắn đường" → `chat`; chỉ dừng được nhờ câu "Đúng" hiểu nhầm (mục 3.3) |
| Đặt xe | Hỏng | "Gọi xe đi sở thú" → điện thoại trả "Không tìm thấy địa điểm này" |
| Xác nhận chuyến xe | **Chưa kiểm** | "Nhận cuốc này" → "Những cuộc ngay" → `chat` |
| Gọi / nhắn / đọc tin | Bị chặn | Mục 2.1 |
| Khẩn cấp (pha H) | **Chưa chạy** | Mục 2.2 |

## 2. Gọi / nhắn / khẩn cấp

### 2.1 Gọi mẹ, nhắn mẹ, đọc tin nhắn: "Kính cần token riêng"
Nguyên nhân (đã dò trong code và DB):
- VH chưa có `VISIONCARE_DEVICE_TOKENS` trong `.env` (chỉ có `VISIONCARE_DEVICE_CLIENT_TOKEN` chung). `pipeline/guard.py`: token chung không bao giờ là `per_device`, mà `call_bridge.unavailable_reason` đòi `per_device` → chặn.
- AB (`seevia-ab-pg`): 0 `users`, 0 `care_links`; có 1 `glasses_devices` (`glasses-123`) và 1 `devices` (điện thoại).
- Gọi/nhắn thường đi qua internet giữa các **tài khoản app**, KHÔNG dùng danh bạ điện thoại. "em iu" phải là một tài khoản AB được mời qua `POST /api/v1/care/invite` rồi `accept`, tên hiển thị "em iu". Thiết kế cố ý cấm gọi/nhắn thường qua SIM (chỉ khẩn cấp có đường SIM dự phòng).
- Việc cần làm: (1) tạo file `{device_id: sha256}`, đặt `VISIONCARE_DEVICE_TOKENS`, đưa token riêng vào `serve.py`/client demo, restart VH 18888; (2) đăng ký chủ kính + gắn kính trong app (`ui/glasses`); (3) tạo tài khoản "em iu" và gắn người thân. `tools/e2e_calls.py` đã dựng sẵn toàn bộ chuỗi này trên stack riêng (cổng 18895/18011…).

### 2.2 Khẩn cấp
- Chưa chạy: lệnh sẽ gọi và nhắn SOS thật tới liên hệ khẩn cấp của điện thoại. Bộ phân quyền tự động chặn; cần người dùng tự cho phép (thêm quy tắc Bash cho `full_tour.py H`) hoặc tự chạy.
- Đã xác minh qua `capabilities_get`: điện thoại có đủ quyền (`read_contacts`, `call_phone`, `send_sms`, `fine_location`, `background_location=always`) và `emergency_contact_set=true`. Người dùng xác nhận tên là "em iu".
- **Cấp cứu gọi người thân, không gọi 115.** Luồng chính: AB gọi lần lượt người thân (`emergency/start`). Vì kính demo không có token riêng nên sẽ rơi về đường SIM (`emergency/call`), app gọi liên hệ cấu hình trong app. App không có số 115 cứng; tham số `number` bị bỏ qua.
- **Rủi ro cần xử lý:** `lanes/phone.py:157` vẫn trích `emergency_number` (115/114/113/số bất kỳ) từ câu nói và truyền xuống `handle_emergency`. App hiện bỏ qua, nhưng nên bỏ hẳn đoạn trích số để không ai sửa app sau này quay nhầm 115.

## 3. STT và UX giọng nói (hạn chế lớn nhất)

### 3.1 Nguyên nhân nghe sai: model, không phải VAD
Đo 150 câu (`stt_ab.py`, `stt_err.py`), clip là giọng tổng hợp:
- Đúng nguyên câu: model nguyên clip 48,7%, qua VAD như server 62–65%. Độ lặng đầu 0,2 / 0,6 / 1,0 s cho kết quả như nhau.
- VAD mở đoạn sớm hơn tiếng thật khoảng 76 ms (min −99 ms), 7/150 câu cắt vào tiếng > 30 ms. **Giả thuyết "VAD cắt đầu từ" bị bác.** Đừng tối ưu VAD để sửa lỗi này.
- Khoảng 10,5% từ sai: thay từ giữa/cuối 26, thay từ đầu câu 18, chỉ sai dấu thanh 9, rớt từ đầu câu 8, thêm từ 1. Ví dụ: "Chai"→"Tràn", "Dừng dẫn"→"Tin gắn", "đề báo"→"đê bảo", "Tờ tiền"→"Tiền", "Vặn"→"Bạn", "Nhận cuốc này"→"Những cuộc ngay".
- Nhóm lệnh đúng nguyên câu thấp: `music_play` 1/5, `music_volume` 1/4, `nav_stop` 2/6, `ocr` 3/8, `space` 2/5, `ride_confirm` 3/7, `alert_off` 4/7.
- Benchmark có sẵn (`stt-bench-cache/report2.md`): WER 7,7–11%, intent cuối đúng ~88%.
- Trong lượt chạy: 4/12 lệnh giọng rơi vào `chat` với câu chung "Tôi chưa hiểu ý bạn, bạn có thể nói lại được không?".
- **Giới hạn của phép đo:** toàn bộ là giọng tổng hợp (VieNeu và các giọng bench), không phải giọng người khiếm thị thật. Tỉ lệ thật chưa biết. Cần ghi âm thật trước khi kết luận.
- Lỗi đã biết còn mở: tiếng nói bắt đầu ~0,6–1,0 s sau khi bấm rớt chữ đầu ("Tắt cảnh báo" → "Cảnh báo"). Phép đo gộp 150 câu không thấy nhạy theo độ lặng, nên có thể chỉ xảy ra ở vài câu cụ thể; xem `demo-web/e2e/README.md`.

### 3.2 Đề xuất output cho người khiếm thị (chưa làm; cần đo lại trên benchmark trước khi giữ)
1. Bỏ câu chung. Đọc lại điều nghe được kèm 2–3 lựa chọn: "Mình nghe là 'tiêu đê bảo'. Bạn muốn đọc chữ, tìm đồ hay tả cảnh?"
2. Độ tin thấp thì hỏi xác nhận bằng đoán tốt nhất: "Bạn muốn đọc chữ phải không?" (cơ chế `ask_confirm`/`is_yes` đã có).
3. Khớp gần âm không dấu với câu lệnh đã biết để cứu lỗi dấu thanh và từ gần âm; chú ý các lệnh dừng (rớt "Dừng/Tắt" là nguy hiểm).
4. Tiếng báo ngắn "đã nghe" / "chưa rõ" thay câu dài.
5. Trả lời mọi phản hồi bằng âm thanh; chữ trên bảng chỉ để người xem (memory `seevia-kinh-am-thanh-dien-thoai-chu`).

### 3.3 "Đúng" khi không có câu hỏi nào chờ
`Đúng` đơn lẻ bị phân loại thành `nav_stop` (lượt 15) rồi `ride_confirm` ("Xác nhận chuyến xe phải không?", lượt 21). Phải xử lý: lời đáp có/không khi không có `pending confirm` nên trả "Mình chưa hỏi gì, bạn cần gì?", không được chạy lệnh nào. Đây là lỗi an toàn, ưu tiên cao.

### 3.4 Phụ
- Chưa nối hotword tên người thân (`stt.set_user_hotwords` chưa có nguồn tên, xem `NEXT_SESSION.md` mục 1). Không có AB care_links nên chưa đo được lợi ích thật.
- Hotword hiện không có tên bài hát/địa điểm nên "bolero", "sở thú", "bệnh viện" dễ sai.

## 4. Hạ tầng và môi trường
- `demo-web/serve.py --port 18080` chỉ nghe `127.0.0.1` (không ra LAN). Cổng 18443 (`--lan`, https tự ký) phục vụ 200 ngay trên máy server nhưng người dùng không mở được từ máy họ: nghi tường lửa/VLAN/VPN (không đọc được iptables, cần sudo). Cách vào chắc chắn: chuyển tiếp cổng 18080 trong tab Ports của VS Code rồi mở `http://localhost:18080/index.html`.
- Không mở Cloudflare công khai cho trang demo: `serve.py` tự gắn token kính cho mọi người mở trang, nên link công khai = quyền điều khiển kính.
- `VH/.env` có `VISIONCARE_HOST_URL` trỏ 8001 (cổng docker-proxy của người khác); VH đang chạy được ghi đè sang `http://127.0.0.1:18001`. Mọi script chạy ngoài phải tự đặt `VISIONCARE_HOST_URL=http://127.0.0.1:18001`.
- `SeeVia_system/.env` còn khoá trùng khác giá trị (xem `NEXT_SESSION.md` mục 4); không tự xoá.
- Playwright Chromium chưa có trên tài khoản này lúc bắt đầu; đã cài `chromium_headless_shell-1248` (~120 MiB) vào `~/.cache/ms-playwright` (cần `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64` trên Ubuntu 20.04).
- Tiến trình `nohup` (VH, AB, serve.py, cloudflared) chết khi VS Code server khởi động lại; kiểm `ss -ltn | grep -E '18001|18888|18443'` trước.
- Chạy headless nên không nghe được loa: chỉ kiểm khung `0x02` và độ trễ, không kiểm âm thanh thật.
- Mỗi lần chạy chạm kính thật: `client.html` dùng mã `glasses-123`, thay phiên kính thật nếu đang nối (`4000`) và đổi trạng thái server của kính.
- Trạng thái chờ xác nhận/hỏi lại (`_CONFIRM`, `_PENDING`) lưu theo kính, không theo trình duyệt, nên sống qua các lần mở trang; TTL 30 s / 60 s.

## 5. Ý tưởng UX bảng giám sát (từ `demo-web/e2e/README.md`, chưa quyết)
Chưa nghe lại được điều người dùng nói (chỉ có transcript); log cảnh báo không gắn với khung hình; timeline chỉ giữ 2 câu đầu; thanh chế độ bị cắt trên điện thoại; chỉ xem một kính một lúc; chưa có chỉ báo âm lượng khi kính đang nghe.

## 6. Thứ tự đề xuất
1. 3.3 ("Đúng" khi không có câu hỏi): lỗi an toàn, sửa nhỏ.
2. 3.2 mục 1–3: làm ngay trong `pipeline/final_router.py` / `lanes/`, đo trên `stt-bench-cache` (so ghép đôi trên cùng bộ clip và báo số câu bất đồng, không chỉ tỉ lệ trung bình).
3. 2.1 mở khóa gọi/nhắn (token riêng + tài khoản + care_links) rồi chạy lại `full_tour.py G` và `H`.
4. Ghi âm giọng thật để thay bộ clip tổng hợp.
5. Bỏ trích `emergency_number` ở `lanes/phone.py:157`.
