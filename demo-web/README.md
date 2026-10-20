# Trang demo SeeVia cho ban giám khảo

Một trang web đóng vai **cái kính**: nối `WS /v2/session` đúng như firmware (khung `hello`
có `debug:true`) rồi cho thấy cả hai phía:

- **POV kính** (trái, ~60%): hình camera của trình duyệt, phủ canvas vẽ cái server nhìn thấy.
  - Box vật cản theo mức: 0–1 xám mờ, 2 cam nét đứt, 3 đỏ nét đậm, nhãn `kind score`. Khi
    khung `det` có `sent` (kính thật sự bị cảnh báo): nháy viền khung, hiện mũi tên hướng
    ("Mức 3 · car bên trái"), bíp (số tiếng = mức, nghiêng trái/phải theo hướng) và ghi vào log.
  - Box OCR viền cyan, chip hướng dẫn (`look_left` → "Quay trái", `move_closer` → "Lại gần",
    `hold_still` → "Giữ yên"...), chớp trắng + "Đã chụp ảnh nét" khi `capture`.
  - Góc: tốc độ khung live (gửi / xử lý, fps), độ trễ khung, kích thước khung.
- **Thanh chế độ** trên POV: Tránh vật cản / Đọc chữ trực tiếp / Chỉ đường (đã gửi điện thoại) /
  Nhạc / Cuộc gọi, sáng theo khung `mode`.
- **Server xử lý lượt hiện tại** (phải): Nghe, Nhận dạng giọng nói (transcript), Hiểu ý định
  (`intent` · lane · source · độ tin cậy), Hành động (params, cue, live), Trả lời (các câu `say`),
  kèm mili-giây từ `timings` và "tiếng đầu sau X ms" đo ngay trên trình duyệt.
- **Lịch sử hội thoại**: bong bóng người dùng = transcript, SeeVia = các `say` gom theo lượt.
  `result-*` hiện là "Kết quả từ điện thoại"; lượt có `pending` gắn "Đang chờ trả lời: …" và
  nối với lượt sau bằng đường kẻ đứt để thấy hội thoại nhiều lượt.
- **Vật cản đã cảnh báo kính**: log rút gọn, chỉ khung `det` có `sent`.

Giữ nút **Giữ để nói** (hoặc giữ phím `Space`) để nói, thả để gửi. Trang gửi ảnh `0x01` lúc bấm,
audio `0x03` là WAV PCM16 16 kHz mono stream dần (header RIFF kích thước `0xFFFFFFFF` + các khối
PCM ~100 ms), rồi `turn_end`. Âm thanh server trả về là `0x02` IMA-ADPCM 16 kHz khối 256 byte
(không header), giải mã bằng `adpcm.js` và phát liên tục qua WebAudio.

## Chạy với server thật

Ba bước, theo thứ tự (ví dụ chạy tất cả trên một máy):

```bash
# 1) Server kính (VH). Cổng tạm, KHÔNG dùng 18888 nếu đó là cổng đang phục vụ kính thật.
#    Chọn GPU trống (nvidia-smi); lần đầu dựng sẵn câu TTS ~3 phút, sau đó ~25 s.
GPU=2 PORT=18990 ./run.sh                    # token/khoá đọc từ .env, không cần source

# 2) Trang demo + proxy. --upstream trỏ vào server ở bước 1.
python demo-web/serve.py --upstream http://127.0.0.1:18990        # http://localhost:8080
#    Máy khác (laptop BGK, điện thoại) mở trang: thêm --lan, xem bên dưới.

# 3) Mở trình duyệt, vào Cài đặt, dán token thiết bị rồi Lưu.
```

- **Khung debug không cần cờ phía server.** Trang tự gửi `hello` có `"debug": true`; server bật khung
  `trace`/`say`/`det`/`ocr`/`mode` chỉ cho phiên đó (kính thật không gửi nên không đổi gì). Server cũ
  chưa có D1 thì trang vẫn chạy như một kính bình thường nhưng hiện nhãn "Server chưa bật khung debug".
- **Token thiết bị** = giá trị `VISIONCARE_DEVICE_CLIENT_TOKEN` trong `.env` của server (trang lưu ở
  trình duyệt, không gửi đi đâu khác). Sai/thiếu thì server đóng phiên `4401` và trang báo "Token sai".
- **Máy khác dùng trang:** chạy trên máy đặt server `python demo-web/serve.py --lan --upstream ...`.
  `--lan` nghe `0.0.0.0` và bật https với chứng chỉ tự ký (in ra `https://<IP-LAN>:8443`), vì trình
  duyệt chỉ cho camera/micro trên `https` hoặc `localhost`. Mở địa chỉ đó, bấm *Nâng cao → Tiếp tục*,
  cho phép camera + micro.
- **Proxy WebSocket:** trang nối `/api/v2/session` cùng nguồn gốc; `serve.py` bắt `Upgrade: websocket`
  ở `/api/...`, mở TCP tới upstream (`/v2/session`), chuyển nguyên request/header (đổi `Host`) rồi bơm
  byte hai chiều bằng hai thread. Không cần CORS, chỉ dùng thư viện chuẩn. HTTP thường (`/health`...)
  cũng đi qua `/api/*`.

```
 trình duyệt ──https/wss──▶ serve.py :8443 ──http/ws──▶ server kính (VH) :18990
  camera+micro+loa           trang + /api/* (HTTP)         /v2/session, /health
                             + /api/v2/session (WS)
```

Lệnh dẫn đường, gọi điện, nhạc... cần **app server (AB)** nối với điện thoại: `VISIONCARE_HOST_URL` trong
`.env` của server trỏ tới đó. Không có AB thì lượt vẫn ra `trace`/`say` đúng nhưng kết quả `result-*`
không bao giờ về (server nói câu lỗi/hết giờ). Hỏi đáp, tránh vật cản và đọc chữ không cần AB.

### Việc nên thử trong buổi demo

| Nói | Thấy gì |
|---|---|
| "Trước mặt tôi có gì?" | Timeline đủ 5 bước, các câu `say` gom vào một bong bóng, tiếng đầu sau X ms |
| "Bật chế độ tránh vật cản" | Chip *Tránh vật cản* sáng, box vật cản vẽ theo mức, mức ≥ 2 thì viền nháy + mũi tên + bíp |
| "Đọc chữ giúp tôi" | Ảnh rõ: đọc thẳng. Ảnh mờ/lệch: chip hướng dẫn ("Quay trái"...), box chữ cyan, "Đã chụp ảnh nét", rồi bong bóng "SeeVia · trực tiếp" |
| "Dẫn đường" → "Bạn muốn đi đâu?" → "Chợ Bến Thành" → "Đúng" | Nhiều lượt: "Đang chờ trả lời: …" nối bằng đường kẻ đứt; xong có "Kết quả từ điện thoại" |

Câu cảnh báo vật cản chỉ kêu khi mức ≥ `HAZARD_MIN_LEVEL` (mặc định 2); box mức 0–1 vẫn hiện nhưng mờ.

### Kiểm nhanh không cần trình duyệt

`realcheck.py` phát các WAV 16 kHz mono qua đúng đường của trang (proxy, header WAV stream, khối
~100 ms đúng nhịp) tới server thật và in mọi khung debug nhận được:

```bash
~/.venvs/seevia/bin/python demo-web/realcheck.py --url http://127.0.0.1:8080 \
    --wav qa.wav alert_on.wav --image street.jpg --settle 8
```

Token lấy từ `.env` của repo (hoặc `--token`); `--direct --url http://127.0.0.1:18990` nối thẳng, bỏ proxy.

## Demo offline, không cần server

```bash
~/.venvs/seevia/bin/python demo-web/fake_server.py --port 18777
python demo-web/serve.py --upstream http://127.0.0.1:18777
```

`fake_server.py` phát kịch bản đúng hợp đồng (lời thoại, ý định, box là dữ liệu soạn sẵn;
giọng nói là tiếng "bi bô" tổng hợp, mã hoá bằng `pipeline/adpcm.py`). Mỗi lượt bấm đi một bước:
hỏi cảnh, đọc chữ trực tiếp (có cue, `capture`), bật cảnh báo vật cản (xe chạy vào, hazard
`sent`), gọi điện có xác nhận hai lượt (`pending`) kèm `result-*`, nhạc, tắt cảnh báo. Nó đếm
byte ảnh/audio nhận được nên chứng minh luồng thật chạy qua proxy.

`selftest.py` dựng cả hai (server giả + proxy) ở cổng tạm và kiểm hợp đồng bằng client Python (không cần trình duyệt):

```bash
~/.venvs/seevia/bin/python demo-web/selftest.py
```

## Khác kính thật

- Khai `cue_version: 0` (trang không có clip trong flash): server đọc cue thành lời, nên
  hướng dẫn OCR hiện lên từ trường `cue` của khung debug `ocr`, bíp cảnh báo do trang tự phát.
- Không gửi `played`, nên metrics `turns.jsonl` của server không có mốc phát cho demo-web.
- Ảnh/khung live cắt giữa theo tỉ lệ 4:3 như camera kính; khung POV cũng cắt đúng 4:3 để box
  (chuẩn hoá theo ảnh đã gửi) khớp hình. `cam {size,fps,quality}` được theo (qvga 320×240, vga
  640×480...); `capture` gửi một khung ≥ 1000 px rộng nếu camera cho (tối đa 1600), nén xuống
  dưới trần 300 KB.
- "Độ trễ khung" là ước lượng: ghép kết quả `det`/`ocr` với khung cũ nhất chưa có kết quả; khung
  bị server bỏ khi bận làm số này cao hơn thực tế.
- Câu live (cảnh báo/OCR) mang `turn` của lượt đã mở live: sau `reply_end` của lượt đó trang đưa chúng
  sang bong bóng riêng "SeeVia · trực tiếp" (đúng thứ tự thời gian); câu lặp liền nhau như "Quay sang
  trái." gộp thành "… ×N". Timeline chỉ giữ 2 câu đầu của lượt (còn lại "+N câu nữa").
- Phiên rớt thì tự mở lại theo backoff 0,5 → 8 s; `4401` (sai token) và `4000` (bị phiên khác
  thay) không tự mở lại.

## Chế độ Mô phỏng

*Cài đặt → Mô phỏng* không gọi server: giữ nút, thả, trang đọc một câu soạn sẵn bằng giọng của
trình duyệt, chỉ để tập dượt luồng bấm-nghe. Câu đó **không phải** kết quả model; trang dán nhãn
"Mô phỏng" suốt thời gian chế độ này bật và các bảng xử lý để trống.

## Tệp

`index.html`, `styles.css` (token màu theo bộ nhận diện, WCAG AA), `app.js`, `adpcm.js`
(giải mã ADPCM), `wav.js` (header WAV stream, hạ mẫu theo luồng), `mock.js`, `serve.py`,
`fake_server.py`, `selftest.py`, `realcheck.py`, `assets/` (logo SVG, font Montserrat + JetBrains Mono tự
host để chạy offline).
