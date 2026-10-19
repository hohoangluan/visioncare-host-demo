# Endpoint cho firmware ESP32-S3 (voice server v2)

Dành cho người viết firmware kính. Mọi con số và khung dưới đây đọc từ mã nguồn:
`live/device_session.py` (WebSocket), `pipeline/guard.py` (token, trần, rate limit),
`config.py` (mục "Voice server v2"), `live/protocol.py` (khung live), `pipeline/cues.py`.
Chỗ nào server chưa làm xong thì ghi rõ "(server ghi nhận từ Task 14)".

Hợp đồng cũ (`POST /process`, WAV ADPCM 60 byte header) vẫn ở `HUONG_DAN_SERVER.md`.
Đường chính từ nay là **một WebSocket mỗi kính**: `WS /v2/session`.

---

## 1. Token

- Server đọc token từ biến `VISIONCARE_DEVICE_CLIENT_TOKEN`. **Để trống = mọi endpoint kính trả 503**
  (HTTP) hoặc đóng 4401 (WS).
- Firmware lưu token trong NVS (partition mã hoá nếu bật flash encryption), nạp lúc provisioning.
  Không biên dịch cứng vào firmware, không in ra serial/log, không gửi qua URL (query string bị
  Cloudflare ghi log).
- Cách gửi, chọn một:
  - Trong khung `hello` của WS (`"token": "..."`), hoặc
  - Header `Authorization: Bearer <token>` hoặc `X-Device-Token: <token>` lúc bắt tay HTTP
    (server chỉ dùng header khi `token` trong `hello` rỗng).
- Server so token bằng `hmac.compare_digest`; mọi endpoint, kể cả từ `localhost`, đều đòi token
  (qua Cloudflare tunnel, mọi request đều đến từ 127.0.0.1).

## 2. Kết nối `WS /v2/session`

- URL: `wss://api.visioncare-host.uk/v2/session` (TLS, cổng 443; server nội bộ ở cổng 18888).
- Server **accept trước** rồi mới kiểm `hello` (đóng trước accept thành HTTP 403, firmware không
  đọc được mã lỗi). Nên firmware luôn đọc **mã đóng** WS, không dựa vào HTTP status.
- Khung text là JSON UTF-8; khung binary có **byte đầu là loại**.

### 2.1 Kính gửi lên server

| Khung | Nội dung | Ghi chú |
|---|---|---|
| text `hello` | `{"t":"hello","device":"glasses-123","token":"...","cue_version":2,"fw":"1.0.3","accept":"ima_adpcm"}` | **Bắt buộc là khung đầu tiên, trong 10 s.** `device` cắt ở 64 ký tự. `accept` chỉ được ghi log (audio ra luôn là ADPCM, xem §5). |
| text `turn_start` | `{"t":"turn_start","turn":"<id>","t_press_ms":123456}` | Bấm nút. `turn` là chuỗi do kính sinh (ví dụ bộ đếm + `millis()`), dùng để đối chiếu mọi khung của lượt. Xem §2.3 về huỷ. |
| binary `0x01` + JPEG | ảnh của lượt | Gửi ngay sau `turn_start`, song song với audio. Trần 2 MB (§7). Chỉ nhận khi đang có lượt. |
| binary `0x03` + ADPCM | audio lượt, mảnh bất kỳ cỡ nào | Stream trong lúc nói (server đoán ý sớm trên mảnh đã tới, không chờ nhả nút). IMA ADPCM 4-bit, mono, 16 kHz, **khối 256 byte, không header RIFF** (xem §5). Trần 30 s. |
| text `turn_end` | `{"t":"turn_end","turn":"<id>","t_release_ms":125000}` | Nhả nút. `turn` phải khớp lượt đang chạy, không khớp thì bị bỏ qua. |
| binary `0x04` + JPEG | khung live | Chỉ có nghĩa khi server đã bật live (§4); ngoài live thì bị bỏ. Trần 300 KB, tối đa 15 fps. |
| text `cancel` | `{"t":"cancel"}` | Bỏ lượt hiện tại + live + lệnh làn D đang chờ đọc xong. |
| text `played` | `{"t":"played","turn":"<id>","first_byte_ms":412,"first_audio_ms":455}` | Báo mốc phát. Server ghi một dòng bổ sung `{"turn","device","glasses":{first_byte_ms,first_audio_ms}}` vào `turns.jsonl` (ghép với dòng chính của lượt theo `turn`, xem §6). |
| text `ping` | `{"t":"ping"}` | Server trả `{"t":"pong"}`. Gửi mỗi **25 s** (§3). |

Khung text sai JSON/thiếu `t`/loại lạ, binary rỗng/loại lạ, ảnh/audio gửi khi chưa có `turn_start`
đều trả `{"t":"error","code":"bad_frame"}`; kết nối **vẫn mở**.

### 2.2 Server gửi xuống kính

| Khung | Nội dung | Ghi chú |
|---|---|---|
| text `hello_ok` | `{"t":"hello_ok","session":"a1b2c3d4e5f6","cue_version":2,"ping_s":25}` | Từ đây mới được gửi `turn_start`. `cue_version` là bản cue của server. |
| text `reply` | `{"t":"reply","turn":"<id>","cues":["received"],"live":null,"audio":{...}}` | Gửi **ngay** khi có kết quả, trước audio. Kính phát `cues` từ flash trong lúc TTS dựng mảnh đầu. |
| binary `0x02` + ADPCM | khối audio, bội số của 256 byte | Phát dần; dựng đệm `preroll_s` trước khi phát để loa không đói. |
| text `reply_end` | `{"t":"reply_end","turn":"<id>"}` | Hết audio của lượt. |
| text `cam` / `capture` / `cue` / `hazard` / `end` | khung live | Mở sau `reply_end` của lượt có `live` khác `null` (§4). Khi nav live đang chạy (nó sống qua các lượt sau), **khung JSON `hazard`/`cue`/`end` có thể tới bất cứ lúc nào, kể cả giữa hai khối `0x02` của một `reply`**: kính phải xử lý chúng ngay, không chờ `reply_end`. |
| text `pong` | `{"t":"pong"}` | |
| text `error` | `{"t":"error","code":"rate_limited"\|"too_large"\|"bad_frame"}` | Kết nối giữ nguyên. |

`reply.live` là `"ocr"`, `"nav"` hoặc `null`. `reply.audio` là `null` khi chỉ có cue, nếu không là
`{"format":"ima_adpcm;rate=16000;channels=1;block=256","sample_rate":16000,"preroll_s":0.2}`.

Nếu `hello.cue_version` thấp hơn `CUE_VERSION` của server thì `reply.cues` là `[]` và các cue được
**đọc thành tiếng** trong audio (kính cũ vẫn nghe đủ). Vì vậy kính phải khai `cue_version` đúng với
bộ clip đang có trong flash (§6).

**Câu kết quả do server chủ động đẩy (`result-<request_id>`).** Hành động làn D chạy nền ("gọi mẹ", "đặt xe",
"phát nhạc", "khẩn cấp") được đọc lại ngay, lệnh tới điện thoại sau cửa sổ huỷ; khi điện thoại báo kết quả
(thành công, `MULTIPLE_CONTACTS_FOUND`, `CONTACT_NOT_FOUND`, lỗi quyền...) server đẩy **một lượt trả lời không do
kính yêu cầu** xuống đúng socket của kính, cùng dạng với lượt thường:

| Khung | Ghi chú |
|---|---|
| text `reply` | `{"t":"reply","turn":"result-<request_id>","cues":[],"live":null,"audio":{...}}`. `turn` bắt đầu bằng `result-`; kết quả có nhiều câu thì các lượt sau là `result-<request_id>.1`, `.2`... |
| binary `0x02` ... + text `reply_end` | audio đọc kết quả, `reply_end.turn` trùng id trên |

Kính xử lý như mọi `reply` (phát audio, có thể báo `played`) và không được coi là trả lời cho lượt bấm gần nhất.

**Một kênh audio `0x02` có thứ tự.** Server giữ MỘT hàng đợi audio cho mỗi phiên: mỗi câu (lượt trả lời
`reply`...`reply_end`, câu `result-*`, câu nói của chỉ đường live như kết quả mở lộ trình / "vẫn đang thực hiện...", cue
đọc thay clip cho kính cũ, câu đọc chữ của OCR live) được gửi **trọn câu** rồi mới tới câu sau, theo thứ tự tới (FIFO).
Hai câu không bao giờ xen khối `0x02` vào nhau, nên kính chỉ cần phát tuần tự theo thứ tự nhận. Chỉ **khung JSON** là
không xếp hàng (hazard mức >= 2 vẫn tới ngay và ngắt câu của chỉ đường live; câu bị ngắt được đọc lại khi yên). `turn_start`, `cancel`, đóng socket hoặc phiên thay thế **bỏ** câu kết quả đang phát
dở và các câu chưa đọc (người dùng đã chuyển sang việc khác). Kính không có phiên WS (đường POST `/v2/turn`, `/process`)
không nhận kênh đẩy này.

### 2.3 Huỷ và lượt mới

- `turn_start` mới luôn **huỷ lượt đang chạy** (STT, Gemma, TTS dừng, audio đang phát dở bị cắt) và
  huỷ lệnh làn D đang chờ đọc xong ("gọi mẹ", "đặt xe"...). Lệnh chờ mà kính chưa nghe xong thì
  không bao giờ được thi hành sau khi bấm lại hay rớt mạng.
- `turn_start` mới **không** dừng phiên live **nav** đang chạy: chỉ đường vẫn chạy và vẫn cảnh báo
  vật cản trong lúc người dùng hỏi thứ khác. Nav chỉ kết thúc khi: người dùng ra lệnh dừng chỉ đường
  (server gửi `end`), `cancel`, socket đóng, hoặc phiên mới của cùng kính thay thế.
- `turn_start` mới **huỷ** phiên live **OCR** đang chạy (kính nên dừng gửi khung 0x04 khi nhận được
  `end` hoặc ngay khi bấm nút).
- Nhạc đang phát hoặc điện thoại đang dẫn đường: **chỉ khi lượt không có lời nói** (bấm nút rồi nhả, VAD không thấy
  tiếng) server hiểu là "dừng" (dừng nhạc / dừng chỉ đường, kèm `end` nếu nav live đang chạy). Lượt có lời được phân loại
  bình thường: "tăng âm lượng" lúc đang nghe nhạc là đổi âm lượng, câu hỏi thường lúc đang dẫn đường không tắt chỉ đường.
- `cancel` huỷ lượt, live OCR và lệnh chờ; live **nav** vẫn chạy (như `turn_start`). Hành vi nav ở trên là quy định
  hiện hành (controller, Task 10 fix); nếu kính nhận hành vi khác thì đọc lại `live/device_session.py`.
- OCR live mở giữa lúc đang chỉ đường **tạm thay** nav live (kính chỉ có một phiên live). Khi OCR live kết thúc (xong,
  bị lượt mới huỷ...) server tự dựng lại nav live: kính nhận lại `cam` của nav và cảnh báo vật cản chạy tiếp.
- Mọi khung WS của kính (binary hay text) tối đa **~2,1 MB** (`uvicorn --ws-max-size 2100000`); quá thì server đóng
  socket (1009) hoặc trả `error: too_large`.

## 3. Giữ kết nối và mở lại

- Gửi `ping` mỗi **25 s**. Server đóng `1001` nếu im lặng quá 90 s (Cloudflare cắt kết nối idle
  khoảng 100 s, nên ping 25 s là bắt buộc, kể cả khi đang chờ người dùng).
- Khi socket rớt (WiFi, 1001, 4000, lỗi mạng): mở lại với **backoff 0,5 → 1 → 2 → 4 → 8 s** (giữ 8 s
  làm trần, cộng nhiễu ±20%). Mở lại thành công thì đặt lại backoff về 0,5 s. Sau khi mở lại phải gửi
  `hello` mới; lượt đang dở của phiên cũ **đã bị huỷ sạch** phía server, không tiếp tục được.
- Không mở nhiều socket cho cùng một kính: phiên mới thay phiên cũ (4000, §8). Đừng tự động mở lại
  khi nhận 4000 trừ khi chính kính vừa mở phiên mới.

## 4. Live: OCR và chỉ đường

Live chạy **trên chính socket này**, không mở WS riêng. Server chỉ bật live sau `reply_end` của lượt
yêu cầu nó (`reply.live` = `"ocr"` hoặc `"nav"`). Khung live giữ nguyên `live/protocol.py`:

| Khung | Ý nghĩa |
|---|---|
| `{"t":"cam","size":"vga","fps":5,"quality":12}` | đặt camera: cỡ ảnh (`qvga`/`vga`/...), khung/giây, chất lượng JPEG; kính làm đúng và bắt đầu gửi 0x04 |
| `{"t":"capture","size":"uxga"}` | chụp **một** ảnh độ phân giải cao, gửi lại bằng 0x04 |
| `{"t":"cue","id":"move_closer"}` | phát clip cue từ flash |
| `{"t":"hazard","level":2,"dir":"left","kind":"vehicle"}` | cảnh báo vật cản: kính phát bíp/clip theo mức và hướng |
| `{"t":"end"}` | kết thúc live; kính dừng gửi 0x04 và tắt camera live |
| binary `0x02` + ADPCM | lời nói trong live (OCR đọc chữ, nav đọc kết quả mở lộ trình) |

Kính chỉ làm **đúng lệnh vừa nhận**, không tự suy đoán.

### 4.1 Chuỗi khung mẫu: một lượt chat

```
kính  -> {"t":"hello","device":"glasses-123","token":"…","cue_version":2,"fw":"1.0.3","accept":"ima_adpcm"}
server-> {"t":"hello_ok","session":"a1b2c3d4e5f6","cue_version":2,"ping_s":25}
kính  -> {"t":"turn_start","turn":"t42","t_press_ms":10000}
kính  -> 0x01 <JPEG 250 KB>
kính  -> 0x03 <ADPCM 2048 B> ... (nhiều khung 0x03 khi đang nói)
kính  -> {"t":"turn_end","turn":"t42","t_release_ms":12300}
server-> {"t":"reply","turn":"t42","cues":["received"],"live":null,
          "audio":{"format":"ima_adpcm;rate=16000;channels=1;block=256","sample_rate":16000,"preroll_s":0.2}}
server-> 0x02 <ADPCM 768 B> ... (nhiều khung 0x02)
server-> {"t":"reply_end","turn":"t42"}
kính  -> {"t":"played","turn":"t42","first_byte_ms":13050,"first_audio_ms":13120}
```

### 4.1b Chuỗi khung mẫu: gọi điện (lệnh làn D + kết quả do server đẩy)

```
kính  -> turn_start / 0x03... / turn_end                      ("gọi cho Nam")
server-> {"t":"reply","turn":"t45","cues":[],"live":null,"audio":{...}}   (đọc lại "Đang gọi cho Nam.")
server-> 0x02 ... ; {"t":"reply_end","turn":"t45"}
          ... cửa sổ huỷ ~2 s (bấm nút/cancel/ngắt mạng lúc này thì lệnh KHÔNG được gửi) ...
          server gửi lệnh tới điện thoại; điện thoại báo MULTIPLE_CONTACTS_FOUND
server-> {"t":"reply","turn":"result-9f1c...","cues":[],"live":null,"audio":{...}}   (server chủ động)
server-> 0x02 ... ; {"t":"reply_end","turn":"result-9f1c..."}   ("Có nhiều người trùng tên trong danh bạ...")
```

### 4.2 Chuỗi khung mẫu: OCR live

```
kính  -> turn_start / 0x01 / 0x03... / turn_end        ("đọc giúp tôi tờ giấy này")
server-> {"t":"reply","turn":"t43","cues":["received"],"live":"ocr","audio":{...}}   (cue + lời hướng dẫn)
server-> 0x02 ... ; {"t":"reply_end","turn":"t43"}
server-> {"t":"cam","size":"vga","fps":5,"quality":12}      (bắt đầu căn khung)
kính  -> 0x04 <JPEG> ... (mỗi khung ≤ 300 KB, ≤ 15 fps)
server-> {"t":"cue","id":"look_left"}                         (hướng dẫn căn chữ)
server-> {"t":"capture","size":"uxga"}                        (đủ chuẩn: chụp nét)
kính  -> 0x04 <JPEG UXGA>
server-> 0x02 ... (đọc nội dung)
server-> {"t":"end"}
```

### 4.3 Chuỗi khung mẫu: chỉ đường (nav)

```
kính  -> turn_start / 0x01 / 0x03... / turn_end        ("dẫn tôi đến chợ Bến Thành")
server-> {"t":"reply","turn":"t44","cues":[],"live":"nav","audio":{...}}
server-> 0x02 ... ; {"t":"reply_end","turn":"t44"}
server-> {"t":"cam","size":"qvga","fps":8,"quality":15}
kính  -> 0x04 <JPEG QVGA> ... (liên tục)
server-> {"t":"hazard","level":2,"dir":"left","kind":"vehicle"}     (kính bíp ngay từ flash)
   ...    người dùng bấm nút hỏi giờ: turn_start mới -> nav VẪN chạy, hazard vẫn tới
server-> {"t":"end"}                                           (người dùng nói "dừng chỉ đường")
```

## 5. Định dạng audio

- **Kính -> server (0x03) và server -> kính (0x02):** IMA ADPCM 4-bit (`WAVE_FORMAT_DVI_ADPCM`),
  mono, **16 000 Hz**, **khối 256 byte** (505 mẫu/khối, ~8 110 byte/giây), **không header RIFF/WAV**.
  Mỗi khối tự đủ (4 byte đầu giữ mẫu và chỉ số bước) nên có thể giải mã từng khối.
- Mảnh audio kính gửi (0x03) có thể là mọi cỡ; mảnh server gửi (0x02) luôn là bội số 256 byte.
- Chuỗi `accept` trong `hello` chưa có tác dụng. Đường POST cũ (`/process`, `/v2/turn`) vẫn có
  MP3/PCM theo `RESPONSE_FORMAT`; WS thì luôn ADPCM.

## 6. Clip cue trong flash

- Cue là tiếng phát sẵn từ flash của kính, không qua mạng/TTS: server chỉ gửi mã (`"cues":["received"]`).
  Bảng mã nằm ở `pipeline/cues.py` (`CUES`); `received` là tiếng "tíc" khi nhả nút.
- Kính khai `cue_version` trong `hello`. Server hiện tại: `CUE_VERSION = 2`. Nếu số của kính thấp hơn,
  server không gửi mã cue mà đọc thành câu nói qua TTS.
- Đổi chữ của cue thì phải tăng `CUE_VERSION` và nạp lại clip vào flash.
- Clip nằm trong repo ở `assets/cues/` (một file `<id>.wav` mỗi mã cue, WAV IMA ADPCM 16 kHz mono, khối 256 byte,
  cùng định dạng audio trả lời) cùng `assets/cues/manifest.json`:
  `{"cue_version": N, "clips": {id: {"file","bytes","seconds","text","sha256"}}}`. Firmware nạp flash theo
  manifest và khai `cue_version` = giá trị trong manifest. Sinh lại bằng
  `python tools/make_cue_clips.py --out assets/cues` (TTS chạy trên GPU); cue không lời (`received`, `shutter`,
  `hazard_1..3`) sinh bằng numpy. Test `test_cue_manifest_complete` đỏ nếu bảng cue đổi mà clip chưa sinh lại.
- Khung `played` đủ **4 mốc** của một lượt: `t_press_ms` (trong `turn_start`), `t_release_ms` (trong
  `turn_end`), `first_byte_ms` (byte audio đầu tới kính) và `first_audio_ms` (tiếng đầu ra loa), tất
  cả tính theo đồng hồ `millis()` của kính. Server ghi mỗi lượt một dòng JSON vào
  `<STORAGE_DIR>/metrics/turns.jsonl` (timing phía server + `glasses` với `t_press_ms`/`t_release_ms` đã có
  lúc lượt xong) và khi `played` tới thì thêm một dòng `{"turn","glasses":{first_byte_ms,first_audio_ms}}`;
  ghép hai dòng theo `turn`. Mọi dòng log của lượt mang `[<device> <turn>]`. Kính cứ gửi đủ mốc.

## 7. Các trần

| Hạng mục | Giá trị | Biến | Khi vượt |
|---|---|---|---|
| Ảnh lượt (0x01) / `/v2/image` | 2 MB | `DEVICE_MAX_IMAGE_BYTES` | WS: `error too_large`, bỏ ảnh; HTTP: 413 |
| Audio một lượt | 30 s | `DEVICE_MAX_AUDIO_S` | WS: một `error too_large`, bỏ phần còn lại |
| Khung live (0x04) | 300 KB | `LIVE_MAX_FRAME_BYTES` | bỏ khung đó |
| Tốc độ khung live | 15 fps | `LIVE_MAX_FPS` | khung dư bị bỏ |
| Lượt/phút | 30 | `DEVICE_TURNS_PER_MIN` | WS: `error rate_limited`, lượt bị bỏ qua; HTTP: 429 |
| Ảnh/phút (HTTP `/v2/image`) | 40 | `DEVICE_IMAGES_PER_MIN` | 429 |
| Body `POST /process` | ảnh + audio + 64 KB | `DEVICE_MAX_PROCESS_BYTES` | 413 trước khi parse |

Rate limit khoá theo `device`. Khi nhận `rate_limited`, kính báo người dùng bằng cue cục bộ, chờ vài
giây, không thử lại dồn dập.

## 8. Mã đóng WebSocket

| Mã | Ý nghĩa | Kính làm gì |
|---|---|---|
| `4000` | phiên mới của cùng kính đã thay phiên này | không tự mở lại (đã có phiên khác) |
| `4400` | khung đầu không phải `hello` hợp lệ, hoặc quá 10 s chưa có `hello` | sửa firmware |
| `4401` | token sai/thiếu/server chưa cấu hình token | không thử lại vòng lặp; báo lỗi cấu hình |
| `1001` | server đóng vì im lặng quá 90 s | mở lại theo backoff (§3) |
| khác / rớt mạng | | mở lại theo backoff (§3) |

## 9. Máy trạng thái kính (gợi ý)

```
OFFLINE --connect--> CONNECTING --hello_ok--> IDLE
IDLE --nhấn nút--> LISTENING (turn_start, gửi 0x01 + 0x03)
LISTENING --nhả nút--> WAITING (turn_end)
WAITING --reply--> PLAYING (phát cue, rồi 0x02 sau preroll)
PLAYING --reply_end--> IDLE | LIVE_OCR | LIVE_NAV (theo reply.live)
LIVE_OCR --end/nhấn nút--> IDLE (hoặc LISTENING)
LIVE_NAV --nhấn nút--> LISTENING (nav vẫn chạy nền) ; LIVE_NAV --end--> IDLE
mọi trạng thái --socket rớt--> OFFLINE (huỷ phát/camera, backoff mở lại)
```

Nhấn nút ở bất kỳ trạng thái nào: dừng phát, gửi `turn_start` mới (server huỷ lượt cũ). Rớt socket giữa
lượt: bỏ lượt đó, mở lại và để người dùng nói lại.

## 10. Đường HTTP còn giữ

Đều **đòi token** (`Authorization: Bearer` hoặc `X-Device-Token`), đều giới hạn như §7.

| Endpoint | Việc | Lỗi |
|---|---|---|
| `POST /process` | đường cũ: multipart `image` + `audio` (WAV ADPCM), trả audio | 401 sai/thiếu token, 413 body quá cỡ, 429 quá tốc độ, 503 server chưa cấu hình token |
| `POST /v2/image` | ảnh lượt (header `X-Turn-Id`, `X-Device-Id`), trả 204 | 401, 413, 429, 503 |
| `POST /v2/turn` | audio ADPCM chunked của lượt, trả cue/audio; header `X-Cue`, `X-Live`, `X-Live-Token` | 401, 429, 503 |
| `WS /v2/live` | live theo token một lần (`X-Live-Token`) | đóng 4401 |
| `GET /health` | kiểm sống, không cần token | |

WS `/v2/session` thay cho cả bốn đường trên khi có mạng ổn; giữ HTTP làm dự phòng.
