# Trang demo SeeVia cho ban giám khảo

Trang web chỉ có **video** và **âm thanh server trả về**.

- **Video** là cái kính nhìn thấy: camera chạy trực tiếp suốt, không bị đóng băng.
- Bấm **Ghi âm**, nói lệnh, bấm **Dừng và gửi**: trang gửi giọng nói và một khung hình
  lên server (`POST /process`), rồi **phát ngay âm thanh server trả về** — phát dần
  theo từng gói, không chờ đủ câu.
- Góc trên chỉ có nhãn trạng thái (đang nghe / đang gửi / server đang xử lý / đang
  đọc / xong), tình trạng kết nối server và nút cài đặt.

## Chạy

Trên **máy đặt server** (cùng máy đang chạy `app.py` ở cổng 8000):

```bash
python demo-web/serve.py --lan
```

Lệnh in ra một địa chỉ `https://<IP-LAN>:8443`. Trên **máy client** (laptop,
điện thoại) chỉ cần trình duyệt: mở địa chỉ đó, bấm *Nâng cao → Tiếp tục* (chứng
chỉ tự ký), cho phép camera + micro.

```
 máy client (trình duyệt)  ──https──▶  serve.py :8443  ──http──▶  app.py :8000
   camera + micro + loa                 phục vụ trang +            /process, /health
                                        chuyển tiếp /api/*
```

Vì sao phải `--lan`: trình duyệt chỉ cho dùng camera/micro trên `https` hoặc
`localhost`, nên mở `http://<IP>` từ máy khác sẽ bị chặn. `--lan` tự tạo chứng chỉ
tự ký (cần lệnh `openssl`) vào `demo-web/certs/`. Đổi mạng/IP thì xoá thư mục đó
để dựng lại. Server nằm máy khác: `--upstream http://<IP>:8000`.

Chạy ngay trên một máy: `python demo-web/serve.py` rồi mở `http://localhost:8080`.

## Giới hạn cần biết

- **Video chỉ để xem, server nhận một ảnh.** `/process` nhận đúng một ảnh mỗi
  lượt, nên trang chụp một khung hình ngay lúc bấm Ghi âm rồi gửi kèm giọng nói. Gửi
  luồng video liên tục lên server cần server hỗ trợ.
- **Khác kính thật.** Kính gửi ADPCM thô; trang này gửi WAV PCM 16 kHz mono (server
  nhận cả hai) vì `MediaRecorder` chỉ cho webm/opus mà `pipeline/adpcm.py` không đọc
  được. Trang xin MP3 (hoặc WAV) về chứ không xin ADPCM.
- **Server chỉ trả âm thanh** — nên trang cũng chỉ có âm thanh, không có chữ hay khung
  phát hiện.
- Phát âm thanh dần cần MediaSource hỗ trợ MP3; Safari không có nên chờ đủ câu mới
  phát.

## Chế độ Mô phỏng

*Cài đặt → Mô phỏng* chạy không cần server: sau bước ghi âm trang đọc một câu soạn sẵn
bằng giọng của trình duyệt, để tập dượt luồng bấm → nghe. Câu đó **không phải** kết
quả của model và trang dán nhãn "Mô phỏng" suốt thời gian chế độ này bật.

## Phím tắt

`Space` bật/tắt ghi âm.
