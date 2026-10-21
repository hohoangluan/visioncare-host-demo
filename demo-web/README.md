# Trang demo SeeVia cho ban giám khảo

Hai trang, hai vai tách bạch:

- **`index.html` — bảng giám sát (chỉ hiển thị).** Không bật camera, không bật micro, không gửi lượt nào. Nó nối
  `WS /v2/observe` của server kính và vẽ lại những gì **kính gửi lên** và **server xử lý ra sao**. Giám khảo chỉ cần nhìn.
- **`client.html` — kính giả lập (trên máy tính).** Có nút *Bật camera*, nút *Bật micro* và nút *Giữ để nói*. Nối
  `WS /v2/session` đúng như firmware (không khai `debug`), gửi ảnh/âm thanh lên server và phát tiếng trả lời. Bảng giám
  sát (mở ở tab hoặc máy khác) thấy ngay. Bảng chỉ xem bản sao nên không phân biệt kính thật hay giả lập.

Bảng giám sát cho thấy:

- **POV kính** (trái, ~60%): khung hình kính gửi lên server, phủ box server nhận ra. Mọi khung `det`/`ocr` đi
  kèm **đúng khung JPEG server vừa tính**, nên box luôn khớp hình dù server xử lý chậm hơn kính gửi.
  - Nhãn nguồn hình (góc trên phải): "Ảnh kính gửi lúc bấm nút" (ảnh `0x01`) hoặc "Khung live server vừa xử lý";
    kính ngừng gửi quá 3 s thì hình mờ đi, nhãn thành "Khung cuối, kính đã ngừng gửi".
  - Box vật cản theo mức: 0–1 xám mờ, 2 cam nét đứt, 3 đỏ nét đậm, nhãn `kind score`. Khung `det` có `sent`
    (kính thật sự bị cảnh báo): nháy viền khung, mũi tên hướng ("Mức 3 · car bên trái"), bíp (số tiếng = mức,
    nghiêng trái/phải theo hướng) và ghi vào log.
  - Box OCR viền cyan, chip hướng dẫn (`look_left` → "Quay trái", `move_closer` → "Lại gần", `hold_still` →
    "Giữ yên"...), chớp trắng + "Đã chụp ảnh nét" khi `capture`.
  - Góc: lệnh `cam` server đang yêu cầu kính + tốc độ server xử lý (fps), kích thước ảnh, "Người dùng đang nói X s"
    trong lúc kính giữ nút.
  - Trạng thái **Kính đã kết nối / chưa kết nối** ngay trên POV; chưa có hình thì khung ghi rõ đang thiếu mắt xích
    nào (chưa nối server, kính chưa nối, hay chờ kính bấm nút).
- **Thanh chế độ** trên POV: Tránh vật cản / Đọc chữ trực tiếp / Chỉ đường (đã gửi điện thoại) /
  Nhạc / Cuộc gọi, sáng theo khung `mode`.
- **Server xử lý lượt hiện tại** (phải): Nghe, Nhận dạng giọng nói (transcript), Hiểu ý định
  (`intent` · lane · source · độ tin cậy), Hành động (params, cue, live), Trả lời (các câu `say`),
  kèm mili-giây từ `timings` và "tiếng đầu sau X ms" đo ngay trên trình duyệt.
- **Hội thoại** (cột giữa, to nhất): mỗi lượt là một thẻ, mọi lượt đều giữ lại (cuộn lên xem cũ, lượt mới tự cuộn vào; cuộn
  lên rồi thì hiện nút "Lượt mới nhất" thay vì giật về). Thẻ gồm: *Người dùng nói* (transcript), *Ý định* (intent + làn + nguồn
  + độ tin cậy), *Kính trả lời* (các `say`, câu lặp gộp "×N"), chip **Tiếng đầu X ms**, và với lệnh làn D hàng *Điện thoại* có
  trạng thái **Chờ bạn trả lời / Đã gửi lệnh / Đang làm / Xong / Lỗi / Chưa có kết quả** (suy từ `trace` làn D + `pending`,
  `reply_end` của lượt, câu `result-*` và `call_state`; chưa có kết quả sau 25 s thì "Chưa có kết quả", không khẳng định lỗi).
  `result-*` hiện thành thẻ "Kết quả từ điện thoại", câu live thành thẻ "Kính nói · trực tiếp". Lượt có `pending` nối với
  lượt sau bằng đường kẻ đứt.
- **Ảnh thu nhỏ đúng khung hình**: thẻ trực tiếp và log cảnh báo gắn ảnh nhỏ (có vẽ box) của khung JPEG server vừa xử lý lúc
  cảnh báo (`det` có `sent`) / lúc chụp để đọc chữ (`ocr` có `capture`); thẻ lượt hỏi cảnh, đọc chữ có ảnh lúc bấm nút (`0x01`).
- **Vật cản đã cảnh báo kính**: log rút gọn, chỉ khung `det` có `sent`, mỗi dòng kèm ảnh thu nhỏ.
- **Điện thoại** (cột phải): xem mục "Ô Điện thoại" bên dưới.

Nút **Âm thanh kính: bật/tắt** ở bảng giám sát điều khiển việc phát lại tiếng server trả về kính (`0x02` IMA-ADPCM
16 kHz khối 256 byte, giải mã bằng `adpcm.js` và phát liên tục qua WebAudio) cùng tiếng bíp cảnh báo. Trình duyệt chặn
âm thanh tự phát nên chạm vào trang một lần để mở khoá.

Trên `client.html`, giữ nút **Giữ để nói** (hoặc phím `Space` ở bất kỳ đâu trừ ô nhập/hộp thoại/nút khác) để nói, thả để gửi; khi đang
nghe có **thanh mức âm micro** (`role="meter"`, kèm câu "đang nghe / chưa thấy tiếng nói / tiếng quá to"), trạng thái đọc được bằng
trình đọc màn hình (`role="status"` + `aria-live`), lỗi nối hiện dải đỏ trên đầu trang. Trang gửi ảnh `0x01` lúc bấm
(camera tắt thì lượt không có ảnh), audio `0x03` là WAV PCM16 16 kHz mono stream dần (header RIFF kích thước
`0xFFFFFFFF` + các khối PCM ~100 ms), rồi `turn_end`. Server yêu cầu live (`cam`/`capture`) thì trang gửi khung `0x04`
từ camera.

## Chạy với server thật

Ba bước, theo thứ tự (ví dụ chạy tất cả trên một máy):

```bash
# 1) Server kính (VH). Cổng tạm, KHÔNG dùng 18888 nếu đó là cổng đang phục vụ kính thật.
#    Chọn GPU trống (nvidia-smi); lần đầu dựng sẵn câu TTS ~3 phút, sau đó ~25 s.
GPU=2 PORT=18990 ./run.sh                    # token/khoá đọc từ .env, không cần source

# 2) Trang demo + proxy. --upstream trỏ vào server ở bước 1.
python demo-web/serve.py --upstream http://127.0.0.1:18990        # http://localhost:8080
#    Máy khác (laptop BGK) mở trang: thêm --lan, xem bên dưới.

# 3) Mở bảng giám sát (index.html) và kính giả lập (client.html). Không cần nhập gì: token và mã kính đã đọc sẵn.
```

- **Bảng giám sát không cần cờ gì phía kính.** `WS /v2/observe` cho server biết đây là người xem: server gửi bản sao mọi thứ
  kính gửi/nhận cùng khung `trace`/`say`/`det`/`ocr`/`mode` mà kính **không phải khai `debug`**. Người xem không thay phiên
  của kính (không bị `4000`) và không điều khiển được gì. Đặc tả khung ở `docs/FIRMWARE_ENDPOINTS.md` mục 15.
- **Cấu hình sẵn, mở là chạy.** `serve.py` đọc `VISIONCARE_DEVICE_CLIENT_TOKEN` và `VISIONCARE_DEVICE_ID` (biến môi
  trường > `.env` của repo > `--token`/`--device`; mã kính mặc định `glasses-123` như `config.py`). Token **không bao giờ xuống
  trình duyệt**: proxy tự gắn `Authorization: Bearer <token>` vào WebSocket `/api/v2/observe` và `/api/v2/session` của trang
  cùng nguồn gốc (trang từ nguồn gốc khác không được mượn token). Mã kính (không bí mật) trang lấy ở `/config.json`: bảng
  giám sát xem đúng kính đó, `client.html` đóng vai chính kính đó. Ô Token/Mã kính trong Cài đặt chỉ để ghi đè (nối thẳng
  tới server khác). Token sai/thiếu thì server đóng `4401` và trang báo "Token sai".
  **Đánh đổi:** ai mở được trang (`--lan` là cả mạng) vào luôn với quyền kính, nên chỉ bật trong mạng demo.
  `client.html` dùng cùng mã kính với kính thật nên nếu kính thật đang nối thì phiên của một bên bị thay (`4000`).
- **Máy khác dùng trang:** chạy trên máy đặt server `python demo-web/serve.py --lan --upstream ...`. `--lan` nghe
  `0.0.0.0` và bật https với chứng chỉ tự ký (in ra `https://<IP-LAN>:8443`). **Chỉ `client.html` cần https** (trình duyệt
  chỉ cho camera/micro trên `https` hoặc `localhost`): mở địa chỉ đó, bấm *Nâng cao → Tiếp tục*, cho phép camera + micro.
  Bảng giám sát không dùng camera/micro nên mở bằng http hay https đều được.
- **Proxy WebSocket:** hai trang nối `/api/v2/observe` (xem) và `/api/v2/session` (kính giả lập) cùng nguồn gốc; `serve.py`
  bắt `Upgrade: websocket` ở `/api/...`, mở TCP tới upstream, chuyển nguyên request/header (đổi `Host`) rồi bơm byte hai
  chiều bằng hai thread. Không cần CORS, chỉ dùng thư viện chuẩn. HTTP thường (`/health`...) cũng đi qua `/api/*`.

```
 client.html ──https/wss──▶ serve.py :8443 ──ws──▶ server kính (VH) :18990 ◀──ws── serve.py ◀── index.html
 camera+micro+loa           /api/v2/session        /v2/session  /v2/observe       /api/v2/observe   chỉ hiển thị
 (hoặc kính thật)
```

Lệnh dẫn đường, gọi điện, nhạc... cần **app server (AB)** nối với điện thoại: `VISIONCARE_HOST_URL` trong
`.env` của server trỏ tới đó. Không có AB thì lượt vẫn ra `trace`/`say` đúng nhưng kết quả `result-*`
không bao giờ về (server nói câu lỗi/hết giờ). Hỏi đáp, tránh vật cản và đọc chữ không cần AB.

### Ô Điện thoại (D5)

Bảng giám sát có cột "Điện thoại" bên phải (màn >= 1500 px; hẹp hơn thì thành thẻ trong cột hội thoại). Hai chế độ:

- **Không cáp (mặc định): khung điện thoại vẽ bằng HTML.** Hiện các tác vụ điện thoại đang/vừa làm: tên lệnh (Chỉ đường, Gọi điện,
  Nhắn tin, Gọi khẩn cấp, Tìm xe, Phát nhạc...), tham số chính (điểm đến, người nhận, bài hát), chip trạng thái (Đã gửi lệnh / Đang làm /
  Xong / Lỗi), câu kết quả, và trạng thái cuộc gọi từ `call_state`. Dữ liệu hoàn toàn từ `/v2/observe` (`trace` làn D, `reply_end`,
  `result-*`, `call_state`): không cần server sửa gì.
- **Có cáp: ảnh THẬT của màn hình điện thoại** (`serve.py --phone-mirror`). Trang đọc `/phone/stream.mjpg` (multipart MJPEG, 540x1170
  ~10 fps) qua thẻ `<img>`; thẻ tác vụ nhỏ nằm dưới khung. Nguồn: `adb exec-out screenrecord --output-format=h264 --size 540x1170
  --bit-rate 2000000 -` | `ffmpeg -f h264 -i - -f mjpeg -q:v 6 -r 10 -`. Chỉ chạy khi có người xem (tab ẩn thì trang ngắt luồng),
  dừng khi không còn ai, tự chạy lại khi screenrecord hết 180 s, một đường ống dùng chung cho mọi người xem. **adb chỉ được gọi khi cổng
  adb server (mặc định `127.0.0.1:5037`, vd. SSH `RemoteForward`) đang LISTEN** (thử kết nối trước mỗi lần chạy); không có thì coi như không
  có điện thoại: `/phone/stream.mjpg` trả 503 và ô Điện thoại về khung vẽ (trang thử lại sau 20 s). Không bao giờ để adb tự khởi động daemon
  cục bộ. Biến môi trường: `SEEVIA_ADB` (mặc định `~/android-sdk/platform-tools/adb`), `SEEVIA_FFMPEG`, `SEEVIA_ADB_PORT`, `SEEVIA_ADB_SERIAL`.
  **Ai mở được trang đều xem được màn hình điện thoại** (kể cả `--lan`): chỉ bật trong mạng demo. Kiểm tự động với adb giả (ffmpeg testsrc):
  `tests/test_demo_serve_proxy.py` và kịch bản `phone-mirror` của `e2e/browser_e2e.py`.

### Việc nên thử trong buổi demo

Nói vào `client.html`, nhìn `index.html`:

| Nói | Thấy gì |
|---|---|
| "Trước mặt tôi có gì?" | Timeline đủ 5 bước, các câu `say` gom vào một bong bóng, tiếng đầu sau X ms |
| "Bật chế độ tránh vật cản" | Chip *Tránh vật cản* sáng, box vật cản vẽ theo mức, mức ≥ 2 thì viền nháy + mũi tên + bíp |
| "Đọc chữ giúp tôi" | Ảnh rõ: đọc thẳng. Ảnh mờ/lệch: chip hướng dẫn ("Quay trái"...), box chữ cyan, "Đã chụp ảnh nét", rồi bong bóng "SeeVia · trực tiếp" |
| "Dẫn đường" → "Bạn muốn đi đâu?" → "Chợ Bến Thành" → "Đúng" | Nhiều lượt: "Đang chờ trả lời: …" nối bằng đường kẻ đứt; xong có "Kết quả từ điện thoại" |

Câu cảnh báo vật cản chỉ kêu khi mức ≥ `HAZARD_MIN_LEVEL` (mặc định 2); box mức 0–1 vẫn hiện nhưng mờ.

### Kiểm nhanh không cần trình duyệt

`realcheck.py` đóng vai kính: phát các WAV 16 kHz mono qua đúng đường của trang client (proxy, header WAV stream, khối
~100 ms đúng nhịp) tới server thật và in mọi khung debug nhận được:

```bash
~/.venvs/seevia/bin/python demo-web/realcheck.py --url http://127.0.0.1:8080 \
    --wav qa.wav alert_on.wav --image street.jpg --settle 8
```

Token lấy từ `.env` của repo (hoặc `--token`); `--direct --url http://127.0.0.1:18990` nối thẳng, bỏ proxy. Mở
`index.html` cùng lúc là thấy bảng giám sát chạy theo.

## Demo offline, không cần server

```bash
~/.venvs/seevia/bin/python demo-web/fake_server.py --port 18777
python demo-web/serve.py --upstream http://127.0.0.1:18777
```

Mở `index.html` (bảng giám sát) và `client.html` (kính giả lập) như trên. `fake_server.py` phát kịch bản đúng hợp đồng
(lời thoại, ý định, box là dữ liệu soạn sẵn; giọng nói là tiếng "bi bô" tổng hợp, mã hoá bằng `pipeline/adpcm.py`) và có
cả `/v2/observe` như server thật. Mỗi lượt bấm đi một bước: hỏi cảnh, đọc chữ trực tiếp (có cue, `capture`), bật cảnh
báo vật cản (xe chạy vào, hazard `sent`), gọi điện có xác nhận hai lượt (`pending`) kèm `result-*`, nhạc, tắt cảnh báo.
Nó đếm byte ảnh/audio nhận được nên chứng minh luồng thật chạy qua proxy.

`selftest.py` dựng cả hai (server giả + proxy) ở cổng tạm và kiểm hợp đồng bằng client Python (không cần trình duyệt):
một client đóng vai kính, một client đóng vai bảng giám sát (kiểm ảnh lượt đúng từng byte, khung JPEG ngay trước
`det`/`ocr`, kính nối/ngắt):

```bash
~/.venvs/seevia/bin/python demo-web/selftest.py
```

## Khác kính thật (`client.html`)

- Khai `cue_version: 0` (trang không có clip trong flash): server đọc cue thành lời, nên hướng dẫn OCR nghe được bằng
  tiếng; bíp cảnh báo do trang tự phát.
- Không gửi `played`, nên metrics `turns.jsonl` của server không có mốc phát cho client giả lập.
- Ảnh/khung live cắt giữa theo tỉ lệ 4:3 như camera kính; xem trước cũng cắt đúng 4:3. `cam {size,fps,quality}` được
  theo (qvga 320×240, vga 640×480...); `capture` gửi một khung ≥ 1000 px rộng nếu camera cho (tối đa 1600), nén xuống
  dưới trần 300 KB.
- Phiên rớt thì tự mở lại theo backoff 0,5 → 8 s; `4401` (sai token) và `4000` (kính cùng mã kết nối nơi khác) không tự mở lại.
- Mã kính mặc định `demo-client`: hai trang client cùng mã sẽ thay nhau (`4000`), như hai kính thật cùng mã.

## Khác nhau giữa bảng giám sát và kính

- "Tiếng đầu sau X ms" đo ở **trang xem** từ lúc nhận `turn_end`, nên gồm cả độ trễ mạng tới trang xem.
- Bảng giám sát chỉ thấy khung `det`/`ocr` mà server **đã xử lý**: khung kính gửi mà server bỏ vì bận thì không hiện.
- Câu live (cảnh báo/OCR) mang `turn` của lượt đã mở live: sau `reply_end` của lượt đó trang đưa chúng sang bong bóng
  riêng "SeeVia · trực tiếp" (đúng thứ tự thời gian); câu lặp liền nhau như "Quay sang trái." gộp thành "… ×N". Timeline
  chỉ giữ 2 câu đầu của lượt (còn lại "+N câu nữa").
- Người xem vào giữa chừng thì nhận ngay trạng thái kính đang nối + chế độ hiện tại, nhưng không thấy phần lượt đã qua.
- Phiên xem rớt thì tự mở lại theo backoff 0,5 → 8 s; `4401` (sai token) không tự mở lại.
- Không còn chế độ Mô phỏng: muốn tập dượt luồng bấm-nghe thì dùng `fake_server.py` + `client.html`.

## Tệp

Bảng giám sát: `index.html`, `styles.css` (token màu theo bộ nhận diện, WCAG AA), `app.js`, `adpcm.js` (giải mã ADPCM).
Kính giả lập: `client.html`, `client.css`, `client.js`, `wav.js` (header WAV stream, hạ mẫu theo luồng), dùng chung
`styles.css` + `adpcm.js`. Chung: `serve.py`, `fake_server.py`, `selftest.py`, `realcheck.py`, `assets/` (logo SVG, font
Montserrat + JetBrains Mono tự host để chạy offline). Kiểm thử bằng trình duyệt thật (ảnh chụp + số đo UX, để chỉnh giao diện
về sau): `e2e/` (xem `e2e/README.md`).
