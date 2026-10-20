# Firmware kính: việc kính phải làm và endpoint

Dành cho người viết firmware ESP32-S3. Mọi khung, mã và con số đọc từ mã nguồn
(`live/device_session.py`, `live/ws_adapter.py`, `live/protocol.py`, `pipeline/guard.py`,
`pipeline/pending_action.py`, `pipeline/cues.py`, `app.py`, `config.py`) và đối chiếu với E2E thật
(`docs/E2E_FULL_FLOW.md`). Đường chính là **một WebSocket mỗi kính: `WS /v2/session`**.
Đường POST cũ (`/process`) vẫn chạy cho firmware cũ (mục 8).

## 1. Checklist việc kính phải làm (theo thứ tự)

**Bật máy**
1. Nạp token từ NVS (mục 2). Không biên dịch cứng, không in ra log/serial, không đặt trong URL.
2. Khai `cue_version` = giá trị trong `assets/cues/manifest.json` của bộ clip đang nằm trong flash (mục 7).

**Kết nối**
3. Mở `wss://api.visioncare-host.uk/v2/session` (TLS, cổng 443). Server `accept` trước rồi mới kiểm `hello`, nên
   **luôn đọc mã đóng WS**, không dựa vào HTTP status.
4. Gửi `hello` làm khung đầu tiên trong **10 s** (kèm token). Chờ `hello_ok` rồi mới được gửi `turn_start`.
5. Gửi `ping` mỗi **25 s**, kể cả khi rảnh (Cloudflare cắt kết nối idle ~100 s; server tự đóng 1001 sau 90 s im lặng).
6. **Giữ socket mở**, không mở lại mỗi lượt.

**Bấm nút -> nhả nút (một lượt)**
7. Bấm: dừng mọi thứ đang phát, gửi `turn_start` (`turn` = id kính tự sinh, `t_press_ms` = `millis()`).
   Server huỷ lượt trước và lệnh điện thoại đang chờ (mục 5).
8. Gửi ngay ảnh lượt `0x01` + JPEG (<= 2 MB), song song với audio.
9. Trong lúc giữ nút, stream audio `0x03` + ADPCM theo từng mảnh (mọi cỡ), không gom đến lúc nhả.
10. Nhả: gửi `turn_end` (`turn` khớp, `t_release_ms`).

**Phát audio theo hàng đợi**
11. Nhận `reply` -> phát mọi `cues` từ flash ngay (clip không qua mạng) -> các khối `0x02` đến sau đó -> `reply_end`.
12. Phát **tuần tự đúng thứ tự nhận**: server đã xếp hàng, kính không cần tự trộn (mục 4.2). Dựng đệm `preroll_s` (0,2 s) trước
    khi phát khối đầu.
13. Báo `played` (`first_byte_ms`, `first_audio_ms`) sau mỗi lượt có audio.

**Hazard (chỉ đường)**
14. Khung `hazard` có thể đến bất cứ lúc nào, kể cả giữa hai khối `0x02`: phát bíp/clip ngay, không chờ `reply_end`.

**Live (OCR / chỉ đường)**
15. Chỉ làm đúng lệnh vừa nhận (`cam`, `capture`, `cue`, `end`); gửi khung `0x04` + JPEG (mục 6).

**Rớt mạng / mở lại**
16. Socket rớt: dừng phát, tắt camera live, bỏ lượt dở, mở lại theo backoff 0,5 -> 1 -> 2 -> 4 -> 8 s (trần 8 s, nhiễu
    +-20%, thành công thì về 0,5 s). Sau khi mở lại gửi `hello` mới. Nhận `4000` thì **không** tự mở lại (mục 9).

## 2. Token

- Server đọc từ `VISIONCARE_DEVICE_CLIENT_TOKEN`; đây là token **kính** cho MỌI endpoint kính (HTTP và WS), kể cả `localhost`
  (qua Cloudflare tunnel mọi request đều tới từ 127.0.0.1).
- Cách gửi: trường `token` trong `hello`, hoặc header `Authorization: Bearer <token>` (cũng nhận `X-Device-Token: <token>`)
  lúc bắt tay. Server chỉ dùng header khi `token` trong `hello` rỗng. So bằng `hmac.compare_digest`.
- Server chưa cấu hình token: HTTP **503**, WS đóng **4401**. Thiếu/sai token: HTTP **401**, WS đóng **4401**.
- Hiện một token dùng chung cho mọi kính và `device` do kính tự khai; token theo từng kính nằm ở plan 2.

## 3. Khung kính -> server

Khung text là JSON UTF-8; khung binary có **byte đầu là loại**. Mọi khung WS tối đa ~2,1 MB (`--ws-max-size 2100000`; quá thì
server đóng 1009 hoặc trả `error too_large`).

| Khung | Nội dung | Ghi chú |
|---|---|---|
| text `hello` | `{"t":"hello","device":"glasses-123","token":"...","cue_version":2,"fw":"1.0.3","accept":"ima_adpcm"}` | Khung đầu tiên, trong 10 s. `device` cắt ở 64 ký tự (rỗng -> id mặc định của server). `fw`, `accept` chỉ ghi log. Sai/thiếu -> `error bad_frame` + đóng 4400; sai token -> đóng 4401. `hello` gửi lặp sau đó bị bỏ qua. |
| text `turn_start` | `{"t":"turn_start","turn":"<id>","t_press_ms":123456}` | Bấm nút. `turn` là chuỗi do kính sinh. Huỷ lượt đang chạy (mục 5). Vượt `DEVICE_TURNS_PER_MIN` (30/phút) -> `error rate_limited`, lượt bị bỏ, các khung ảnh/audio sau đó bị bỏ lặng lẽ. |
| binary `0x01` + JPEG | ảnh của lượt | Sau `turn_start`. Trần 2 MB (`DEVICE_MAX_IMAGE_BYTES`) -> `error too_large`. Không có lượt đang chạy thì bị bỏ lặng lẽ. |
| binary `0x03` + ADPCM | audio lượt | IMA ADPCM 4-bit, mono, 16 kHz, khối 256 byte, không header RIFF (mục 10). Trần 30 s (`DEVICE_MAX_AUDIO_S`): vượt thì một `error too_large` rồi bỏ phần còn lại. |
| text `turn_end` | `{"t":"turn_end","turn":"<id>","t_release_ms":125000}` | Nhả nút. `turn` không khớp lượt đang chạy thì bị bỏ qua. |
| binary `0x04` + JPEG | khung live | Chỉ có nghĩa khi live đang bật; ngoài live bị bỏ. Trần 300 KB (`LIVE_MAX_FRAME_BYTES`), tối đa 15 fps (`LIVE_MAX_FPS`), khung dư bị bỏ. |
| text `cancel` | `{"t":"cancel"}` | Huỷ lượt, live OCR và lệnh điện thoại đang chờ. Live **nav** vẫn chạy. |
| text `played` | `{"t":"played","turn":"<id>","first_byte_ms":412,"first_audio_ms":455}` | Mốc phát (mục 7). |
| text `ping` | `{"t":"ping"}` | Server trả `pong`. |

Text sai JSON/thiếu `t`/loại lạ, binary rỗng/loại lạ -> `{"t":"error","code":"bad_frame"}`, kết nối **vẫn mở**.

## 4. Khung server -> kính

| Khung | Nội dung | Ghi chú |
|---|---|---|
| text `hello_ok` | `{"t":"hello_ok","session":"a1b2c3d4e5f6","cue_version":2,"ping_s":25}` | `cue_version` là bản cue của server. |
| text `reply` | `{"t":"reply","turn":"<id>","cues":["received"],"live":null,"audio":{...}}` | Gửi **ngay** khi có kết quả, trước audio. `live` là `"ocr"`, `"nav"` hoặc `null`. `audio` là `null` khi chỉ có cue, nếu không `{"format":"ima_adpcm;rate=16000;channels=1;block=256","sample_rate":16000,"preroll_s":0.2}`. |
| binary `0x02` + ADPCM | khối audio | Bội số của 256 byte. |
| text `reply_end` | `{"t":"reply_end","turn":"<id>"}` | Hết audio của `reply` đó. |
| text `cam` / `capture` / `cue` / `hazard` / `end` | khung live | Mục 6. |
| text `pong` | `{"t":"pong"}` | |
| text `error` | `{"t":"error","code":"rate_limited"\|"too_large"\|"bad_frame"}` | Kết nối giữ nguyên. |

Kính có `cue_version` thấp hơn server: `reply.cues` là `[]` và cue được **đọc thành tiếng** trong audio (kính cũ vẫn nghe đủ).

### 4.1 Khung `result-*` do server chủ động đẩy

Lệnh làn D chạy nền (gọi điện, đặt xe, phát nhạc, khẩn cấp) được đọc lại ngay; lệnh tới điện thoại sau cửa sổ huỷ (mục 5). Khi
điện thoại báo kết quả (thành công, `MULTIPLE_CONTACTS_FOUND`, `CONTACT_NOT_FOUND`, lỗi quyền...) server đẩy **một lượt trả lời
kính không yêu cầu** xuống đúng socket, cùng dạng với lượt thường:

```
{"t":"reply","turn":"result-<request_id>","cues":[],"live":null,"audio":{...}}
0x02 ...
{"t":"reply_end","turn":"result-<request_id>"}
```

Kết quả nhiều câu thì các câu sau mang `turn` = `result-<request_id>.1`, `.2`... Kính xử lý như mọi `reply` (phát, có thể báo
`played`) và **không** coi đó là trả lời cho lượt bấm gần nhất. Kết quả `nav_start` ("Đã gửi chỉ đường tới ... về điện thoại. Mở thông báo để đi bằng Google Maps.") cũng đi qua
`result-*` như mọi lệnh khác (dẫn đường không còn là live). Kính chỉ dùng HTTP (`/v2/turn`, `/process`) không có phiên WS nên **không nhận được** khung này
và không nghe kết quả lệnh.

### 4.2 Hàng đợi audio theo phiên

Server giữ **MỘT kênh audio `0x02` có thứ tự** cho mỗi phiên. Mỗi câu (`reply`...`reply_end` của lượt, câu `result-*`, câu nói của
chỉ đường live, câu đọc chữ của OCR live, cue đọc thay clip cho kính cũ) được gửi **trọn câu** rồi mới tới câu sau, FIFO. Hai câu
không bao giờ xen khối `0x02` vào nhau, nên kính chỉ phát tuần tự theo thứ tự nhận.

- Câu của live (nav/OCR/cue đọc thay clip) **không có** `reply`/`reply_end` bao quanh: chỉ là khối `0x02` liên tục, hết câu thì
  ngừng đến. Phát hết đệm rồi đợi khối kế.
- Chỉ **khung JSON** không xếp hàng. Hazard mức >= 2 tới ngay và **ngắt** câu nói của chỉ đường đang gửi (khối `0x02` ngừng giữa
  chừng, câu được đọc lại đầy đủ khi yên ~1,5 s). Kính nên cho phép phát cụt, không coi là lỗi.
- `turn_start`, `cancel`, đóng socket hoặc phiên thay thế **bỏ** câu `result-*` đang phát dở và các câu chưa đọc.

## 5. Đọc lại lệnh, bấm huỷ, xác nhận "...phải không?"

Với lệnh có tác dụng phụ (gọi điện, khẩn cấp, đặt xe, gửi chỉ đường về điện thoại):

1. **Đọc lại**: server trả `reply` + audio đọc lại ("Đang gọi cho mẹ.", khẩn cấp: "Đang gọi người thân khẩn cấp, bấm nút để huỷ.").
   Kính phát ngay như mọi audio.
2. **Cửa sổ huỷ**: đồng hồ đếm từ lúc **khối `0x02` đầu tiên của câu đọc lại rời server** (không phải lúc route xong), dài bằng thời
   gian đọc câu + đệm đầu phát + 0,15 s biên + 0,4 s TTS. Thực đo E2E: nhả nút -> lệnh tới điện thoại 2,4–3,7 s, phần lớn là thời
   gian đọc lại. Audio đọc lại chưa tới kính thì lệnh **không bao giờ chạy** (fail closed).
3. **Huỷ**: trong cửa sổ đó, bấm nút (`turn_start`), gửi `cancel`, hoặc đóng socket đều huỷ lệnh; lệnh không được gửi tới điện thoại.
   Kính không phải làm gì thêm ngoài việc gửi đúng khung. Rớt mạng giữa chừng cũng huỷ.
4. **Nghi ngờ thì hỏi lại**: nếu độ tin cậy nhãn dưới 0,999 (hoặc không phải Gemma), server trả "Gọi cho mẹ phải không?" và chưa chạy gì
   (~1 trên 10 lệnh làn D). Với kính đây là một `reply` bình thường; người dùng trả lời bằng **lượt kế tiếp** ("đúng", "có", "không", "thôi"...).
   Chỉ câu ngắn (<= 3 từ, toàn từ đồng ý/từ chối) mới tính; câu khác bị coi là lượt mới. Hết hạn sau 30 s. Câu trả lời cho một câu hỏi
   thiếu thông tin ("Bạn muốn đi đâu?", hạn 60 s) cũng được hỏi xác nhận lại trước khi chạy.
5. **Bấm nút không nói** khi đang phát nhạc hoặc đang chỉ đường = "dừng" (dừng nhạc / dừng chỉ đường, kèm `end` nếu nav live đang chạy).
   Bấm rồi nói thì lượt được phân loại bình thường.

## 6. Live: OCR và chỉ đường (nav)

Live chạy **trên chính socket này**, bật sau `reply_end` của lượt có `reply.live` là `"ocr"` hoặc `"nav"`. Kính chỉ làm **đúng lệnh vừa nhận**.

| Khung | Ý nghĩa |
|---|---|
| `{"t":"cam","size":"vga","fps":5,"quality":12}` | đặt camera (OCR: vga 5 fps; nav: `qvga` 8 fps, quality 15) rồi gửi `0x04` liên tục |
| `{"t":"capture","size":"uxga"}` | chụp **một** ảnh UXGA, gửi lại bằng `0x04` |
| `{"t":"cue","id":"look_left"}` | phát clip cue từ flash (OCR: hướng dẫn căn chữ) |
| `{"t":"hazard","level":2,"dir":"left","kind":"car"}` | cảnh báo vật cản. `level` 1–3; `dir` `left`/`center`/`right`; `kind` là tên lớp vật: `person`, `bicycle`, `car`, `motorbike`, `bus`, `truck`, `dog`, `traffic_light`, `hydrant`, `stop_sign`, `parking_meter`, `bench`, `chair`, `plant`. Theo spec: phát `hazard_<level>`; mức >= 2 thêm `dir_*`, mức 3 thêm `stop_now` (clip có sẵn, mục 7). Server đã chống làm phiền; kính phát mọi khung nhận được. |
| `{"t":"end"}` | kết thúc live: dừng gửi `0x04`, tắt camera live |

**Nav sống qua lượt mới.** `turn_start`/`cancel` KHÔNG dừng nav live: người dùng hỏi gì giữa đường vẫn được cảnh báo vật cản. Nav
chỉ kết thúc khi `end` (người dùng nói/bấm dừng chỉ đường, `alert_off`), socket đóng, hoặc phiên thay thế.
**OCR live thì bị lượt mới huỷ** (dừng gửi `0x04` khi bấm nút hoặc khi nhận `end`). OCR mở giữa lúc đang chỉ đường **tạm thay** nav
(kính chỉ có một phiên live); OCR xong server tự dựng lại nav (kính nhận lại `cam` của nav).

Chuỗi mẫu:

```
-- chat --
kính   {"t":"turn_start","turn":"t42","t_press_ms":10000} ; 0x01 <JPEG> ; 0x03 <ADPCM>... ; {"t":"turn_end","turn":"t42","t_release_ms":12300}
server {"t":"reply","turn":"t42","cues":["received"],"live":null,"audio":{...}} ; 0x02... ; {"t":"reply_end","turn":"t42"}
kính   {"t":"played","turn":"t42","first_byte_ms":13050,"first_audio_ms":13120}

-- gọi điện --
server reply(t45, đọc lại "Đang gọi cho Nam.") ; 0x02... ; reply_end   ... cửa sổ huỷ ... lệnh tới điện thoại
server {"t":"reply","turn":"result-9f1c...",...} ; 0x02... ; {"t":"reply_end","turn":"result-9f1c..."}   (server chủ động)

-- OCR live --
server reply(live:"ocr", cues:["ocr_start"]) ; reply_end ; {"t":"cam","size":"vga","fps":5,"quality":12}
kính   0x04 <JPEG>...   server {"t":"cue","id":"look_left"} ... {"t":"capture","size":"uxga"}   kính 0x04 <UXGA>
server 0x02... (đọc nội dung) ; {"t":"end"}

-- nav --
server reply(live:"nav", cues:["nav_alert_on"]) ; reply_end ; {"t":"cam","size":"qvga","fps":8,"quality":15}
kính   0x04 <JPEG>...   server {"t":"hazard","level":2,"dir":"left","kind":"car"}
kính   (bấm nút hỏi giờ: turn_start mới, nav vẫn chạy, hazard vẫn tới)   server {"t":"end"} khi người dùng dừng
```

## 7. Cue clips và `played`

- Clip nằm ở `assets/cues/`: một file `<id>.wav` mỗi mã cue (WAV IMA ADPCM 16 kHz mono, khối 256 byte) cùng `manifest.json`
  `{"cue_version": N, "clips": {id: {"file","bytes","seconds","text","sha256"}}}`. Hiện `cue_version` = **2**, 32 clip:
  `received`, `shutter`, `hazard_1..3` (âm, không lời); `system_busy`, `no_speech`, `no_image`; `ask_destination`, `ask_contact_name`,
  `ask_song`, `ask_ride_destination`, `phone_pending`, `emergency_started`; `ocr_start`, `look_left/right/up/down`, `look_around`,
  `move_closer`, `move_away`, `hold_still`, `ocr_no_text`, `ocr_nothing_to_reread`; `dir_left/center/right`, `stop_now`,
  `nav_alert_on`, `nav_alert_off`. `received` là tiếng "tíc" khi nhả nút.
- Nạp flash theo manifest, kiểm `sha256`, khai `hello.cue_version` = giá trị trong manifest. Đổi chữ cue thì tăng `CUE_VERSION` và
  sinh lại bằng `python tools/make_cue_clips.py --out assets/cues` (test `test_cue_manifest_complete` đỏ nếu quên).
- `played` ghi đủ 4 mốc theo `millis()` của kính: `t_press_ms` (trong `turn_start`), `t_release_ms` (trong `turn_end`), `first_byte_ms`
  (byte audio đầu tới kính), `first_audio_ms` (tiếng đầu ra loa). Server ghi mỗi lượt một dòng vào `<STORAGE_DIR>/metrics/turns.jsonl` và
  thêm một dòng bổ sung khi `played` tới (ghép theo `turn`). Kính cứ gửi đủ mốc, kể cả với `result-*`.

## 8. Đường HTTP còn giữ

Đều đòi token (`Authorization: Bearer`) và chịu cùng trần/rate limit như mục 11.

| Endpoint | Việc | Lỗi |
|---|---|---|
| `POST /process` | **đường cũ**: multipart `audio` (+ `image` tuỳ chọn), trả audio stream, luôn 200 (lỗi cũng thành câu nói). Chạy chung pipeline v2 (`single_shot`: OCR đọc thẳng ảnh, chỉ đường chỉ gửi lộ trình về điện thoại, không có live). Hợp đồng chi tiết: `docs/HUONG_DAN_SERVER.md` | 401, 413 (trước khi parse), 429, 503 |
| `POST /v2/image` | ảnh lượt (header `X-Turn-Id`, `X-Device-Id`), 204 | 401, 413, 429, 503 |
| `POST /v2/turn` | audio ADPCM chunked, trả audio; header `X-Cue`, `X-Live`, `X-Live-Token`; kính khai `X-Cue-Version` | 401, 429, 503 |
| `WS /v2/live` | live theo token một lần (`X-Live-Token`) cho kính dùng HTTP | đóng 4401 |
| `GET /health` | kiểm sống, **không cần token** | |

Các đường HTTP là dự phòng; không có kênh đẩy `result-*`, không có `played`.

## 9. Mã đóng WebSocket

| Mã | Ý nghĩa | Kính làm gì |
|---|---|---|
| `4000` | phiên mới của cùng kính đã thay phiên này | không tự mở lại |
| `4400` | khung đầu không phải `hello` hợp lệ, hoặc quá 10 s chưa có `hello` | sửa firmware |
| `4401` | token sai/thiếu/server chưa cấu hình | không lặp lại; báo lỗi cấu hình |
| `1001` | server đóng vì im lặng quá 90 s | mở lại theo backoff |
| `1009` | khung quá lớn | sửa firmware |
| khác / rớt mạng | | mở lại theo backoff |

Mỗi kính chỉ một socket: phiên mới thay phiên cũ (đóng 4000 và huỷ sạch việc dở của phiên cũ).

## 10. Định dạng audio

Cả hai chiều (`0x03`, `0x02`): IMA ADPCM 4-bit, mono, **16 000 Hz**, **khối 256 byte** (505 mẫu/khối, ~8 110 byte/s), **không header
RIFF/WAV**. Mỗi khối tự đủ (4 byte đầu giữ mẫu và chỉ số bước) nên giải mã từng khối được. Mảnh kính gửi cỡ tuỳ ý; mảnh server gửi
luôn là bội số 256 byte. Trên WS luôn là ADPCM; MP3/PCM chỉ có ở đường HTTP cũ theo `RESPONSE_FORMAT`.

## 11. Các trần

| Hạng mục | Giá trị | Biến | Khi vượt |
|---|---|---|---|
| Ảnh lượt (`0x01`, `/v2/image`) | 2 MB | `DEVICE_MAX_IMAGE_BYTES` | WS `error too_large`; HTTP 413 |
| Audio một lượt | 30 s | `DEVICE_MAX_AUDIO_S` | WS một `error too_large`, bỏ phần còn lại |
| Khung live (`0x04`) | 300 KB, 15 fps | `LIVE_MAX_FRAME_BYTES`, `LIVE_MAX_FPS` | bỏ khung |
| Lượt/phút | 30 | `DEVICE_TURNS_PER_MIN` | WS `error rate_limited`; HTTP 429 |
| Ảnh/phút (HTTP) | 40 | `DEVICE_IMAGES_PER_MIN` | 429 |
| Body `POST /process` | ảnh + audio + 64 KB | `DEVICE_MAX_PROCESS_BYTES` | 413 |

Rate limit khoá theo `device`. Nhận `rate_limited` thì báo người dùng bằng cue cục bộ, chờ vài giây, không thử lại dồn dập.

## 12. Độ trễ: dùng WS, không dùng POST qua Cloudflare

Đo trên `5963ad5` (bench trên chính máy server -> điểm Hồng Kông -> tunnel -> server, 4 lượt/luồng, **không gồm WiFi kính**).
Trung vị nhả nút -> tiếng đầu (ms):

| lượt | local POST | local WS | CF POST | CF WS |
|---|--:|--:|--:|--:|
| chat | 776 | 688 | 848 | 775 |
| space | 656 | 593 | 736 | 657 |
| ocr | 726 | 655 | 872 | 773 |
| money | 609 | 539 | 805 | 680 |
| contact | 537 | 444 | 708 | 619 |

Qua Cloudflare, WS nhanh hơn POST **70–125 ms** (bỏ TLS và kết nối mới mỗi lượt). Header trả về: CF POST ~385–510 ms so với CF WS
~285–335 ms. Ảnh qua POST CF mất 400–590 ms; trên WS không có lượt POST ảnh riêng. Cloudflare còn thêm 80–175 ms (chặng edge ->
cloudflared -> origin) mà firmware không giảm được. Hệ quả cho firmware:

1. **Dùng `WS /v2/session`**; POST chỉ là dự phòng.
2. **Giữ socket mở** (TLS bắt tay ~70–130 ms mỗi kết nối bị bỏ khỏi đường nóng), ping mỗi 25 s.
3. **Gửi ảnh qua socket** (`0x01`), không `POST /v2/image` riêng. Gửi ảnh ngay sau `turn_start`; ảnh tới sau audio thì lượt phải chờ
   tối đa `IMAGE_WAIT_S` = 1,5 s trước khi trả lời làn cần ảnh.
4. Stream `0x03` trong lúc nói, đừng gom đến lúc nhả nút: server đoán ý và khởi động sớm trên phần đã tới.

## 13. Máy trạng thái gợi ý

```
OFFLINE --connect--> CONNECTING --hello_ok--> IDLE
IDLE --nhấn nút--> LISTENING (turn_start, 0x01 + 0x03)
LISTENING --nhả nút--> WAITING (turn_end)
WAITING --reply--> PLAYING (cue từ flash, rồi 0x02 sau preroll)
PLAYING --reply_end--> IDLE | LIVE_OCR | LIVE_NAV (theo reply.live)
LIVE_OCR --end/nhấn nút--> IDLE (hoặc LISTENING)
LIVE_NAV --nhấn nút--> LISTENING (nav vẫn chạy nền) ; LIVE_NAV --end--> IDLE
mọi trạng thái --socket rớt--> OFFLINE (dừng phát/camera, backoff mở lại)
```

Nhấn nút ở bất kỳ trạng thái nào: dừng phát, gửi `turn_start` mới. Rớt socket giữa lượt: bỏ lượt đó, mở lại và để người dùng nói lại.

## 14. Đã kiểm bằng E2E thật

`tools/e2e_full.py` (kính giả qua `WS /v2/session` -> VH -> app server -> phone_sim), `5963ad5`, 1 lượt mỗi kịch bản, tất cả PASS:
`call_mom`, `call_nam` (điện thoại báo `MULTIPLE_CONTACTS_FOUND`, người dùng nghe được), `ride` (`ride_quote` rồi `ride_confirm`), `music`
(có lời = đổi âm lượng, bấm không lời = dừng), `nav` (dẫn đường: lệnh `navigation_start` + `maps_url`, không live; bấm nút = `navigation_stop`), `alert` (hazard, chat giữa chừng không tắt cảnh báo), `emergency`,
`call_cancel` (điện thoại không nhận lệnh nào). Nhả nút -> tiếng đầu 502–560 ms; lệnh -> kết quả được đọc 483–992 ms. Bảng đầy đủ: `docs/E2E_FULL_FLOW.md`.

## 15. Debug (chỉ demo)

Dành cho trang demo của giám khảo, **kính thật không dùng và không cần xử lý**. Khai `"debug": true` trong `hello` (đúng kiểu boolean `true`)
thì `hello_ok` có thêm `"debug": true` và server gửi thêm các khung JSON text dưới đây. Không khai thì không có khung nào trong mục này,
mọi hành vi khác giữ nguyên. Khung debug **không chờ khoá audio** (xen được giữa hai khối `0x02`), không chặn đường hazard và lỗi gửi bị bỏ qua. Hàng đợi khung debug có chặn: `det`/`ocr` chỉ giữ khung mới nhất khi đường truyền chậm (khung cũ bị bỏ), `say`/`mode` tối đa 64 khung chờ; khung JPEG hỏng không sinh `det`.

| Khung | Khi nào | Trường |
|---|---|---|
| `{"t":"trace","turn",...}` | sau khi lượt xử lý xong, **trước** `reply` | `transcript:str`, `intent:str\|null`, `lane:str\|null`, `source:str` (nguồn quyết định ý định), `confidence:float\|null` (null khi không có bộ phân loại chấm), `params:dict` (tham số làn D; `{}` nếu không có), `cues:[str]`, `live:"ocr"\|"nav"\|null`, `timings:{audio_s,upload_s,final_stt_s,intent_s,route_s,release_to_reply_s}` (giây), `pending:str\|null` (câu đang chờ lượt sau, vd "Bạn muốn đi đâu?" / "Chỉ đường tới … phải không?") |
| `{"t":"say","turn","text"}` | mỗi câu được đưa vào TTS: lượt thường, `result-*`, outbox live nav, OCR đọc, cue đọc thay clip | `text:str`; `turn` là id lượt đang nói (`result-<id>` cho kết quả hành động) |
| `{"t":"det","w","h","boxes":[{"kind","score","box":[x0,y0,x1,y1],"level"}],"hazard":{"level","dir","kind"}\|null,"sent":bool}` | mỗi khung live nav đã xử lý | `box` chuẩn hoá 0..1 theo `w,h` (ảnh đã giải mã); `level` từng hộp theo `hazard.level_of`; `hazard` null khi khung an toàn; `sent` = khung `hazard` có thật sự đi tới kính (qua chống làm phiền) |
| `{"t":"ocr","w","h","boxes":[[x0,y0,x1,y1]],"cue":str\|null,"capture":bool}` | mỗi khung live OCR đã giải mã | `boxes` là **pixel** theo `w,h` (ảnh xám đã thu nhỏ, tối đa 800 px cạnh dài); `cue` = cue căn khung vừa gửi; `capture` = vừa ra lệnh chụp |
| `{"t":"mode","obstacle":bool,"ocr":bool,"navigating":bool,"music":bool,"call":str\|null}` | ngay sau `hello_ok`; mỗi khi live bắt đầu/kết thúc; sau mỗi lượt và mỗi `result-*` | `obstacle` = live nav đang chạy, `ocr` = live OCR đang chạy, `navigating`/`music` = điện thoại đang dẫn đường/phát nhạc; `call` = `"ringing_out"\|"ringing_in"\|"active"\|null` (trạng thái cuộc gọi, mục 16) |

## 16. Cuộc gọi và tin nhắn (qua internet, như Messenger)

Gọi điện/nhắn tin đi qua server (kính ↔ VH ↔ app server ↔ app người thân), **không dùng SIM, SMS hay số điện thoại, không video**. Chỉ chạy khi phiên
xác thực bằng **token RIÊNG của kính** (mục 2; token dùng chung vẫn vào được nhưng bị từ chối gọi/nhắn bằng câu "Kính cần token riêng để gọi điện.") và
đang có phiên `WS /v2/session` (kính chỉ dùng POST thì nghe "Kính cần cập nhật để gọi điện."). Kính KHÔNG cần biết ai là người thân: nói "gọi cho mẹ" như mọi
lệnh khác, server khớp tên.

### 16.1. Khung mới

| Hướng | Khung | Ý nghĩa |
|---|---|---|
| server → kính | text `{"t":"call_state","call":"<id>","state":"ringing_out"\|"ringing_in"\|"active"\|"ended","peer":"Mẹ","reason"?:"..."}` | trạng thái cuộc gọi. Gửi khi tạo, khi đổi, khi kết thúc (kèm `reason`). `call` là id của app server (có thể đổi từ id tạm sang id thật sau khi gọi xong, kính chỉ cần dùng id mới nhất) |
| kính → server | binary `0x05` + ADPCM | **mic trong cuộc gọi** (chỉ khi `active`; ngoài `active` bị bỏ). Cùng định dạng `0x03`: IMA ADPCM 4-bit, mono, 16 kHz, khối 256 B (505 mẫu ≈ 31,6 ms). Có thể gửi một hay nhiều khối mỗi khung, mảnh lẻ được ghép lại. KHÔNG dùng `0x03` (đó là lượt lệnh) |
| server → kính | binary `0x02` + ADPCM | tiếng đầu kia, như audio trả lời (bội số 256 B, kính phát ngay). Trong `active` kênh `0x02` chỉ còn tiếng cuộc gọi |
| kính → server | text `{"t":"call_answer","call":"<id>"}` | bấm nút khi `ringing_in` = nghe (server không so id) |
| kính → server | text `{"t":"call_hangup","call":"<id>"}` | bấm nút khi `ringing_out` hoặc `active` = cúp / huỷ / **dừng chuỗi khẩn cấp** |

Mic PCM mono 16 kHz 16-bit chia khung **20 ms = 640 byte** ở phía app (server giải mã ADPCM rồi cắt); độ trễ thêm của cầu ở kính → app ≈ 1 ms, đệm chống giật
app → kính mặc định 60 ms (`CALL_JITTER_MS`).

### 16.2. Nút và trạng thái

- `ringing_in` (người thân gọi tới): server đọc "{tên} đang gọi. Bấm nút để nghe." → bấm = `call_answer`. Kính đang bận hoặc không có phiên: server từ chối, người gọi nhận `call_ended` (`busy`/`glasses_offline`).
- `ringing_out` (kính gọi đi, kể cả chuỗi khẩn cấp): bấm = `call_hangup`. Đừng gửi `turn_start`.
- `active`: bấm = `call_hangup`. **Không gửi `turn_start` trong lúc gọi** (server cũng bỏ qua `turn_start` khi `ringing_out|active`). Server tự dừng mọi câu đang đọc, tạm dừng
  chế độ tránh vật cản (live nav) và bật lại khi cúp; kính ngừng stream `0x04` khi `active` thì tốt hơn (server không gộp hazard vào cuộc gọi).
- `ended` (kèm `reason`: `glasses_hangup|app_hangup|rejected|missed|timeout|emergency_exhausted|peer_disconnect|media_timeout|revoked|busy|...`): dừng mic `0x05`, trở về IDLE. Có lời đọc kèm
  sau đó ("Mẹ chưa nghe máy. Bạn muốn nhắn tin không?") qua `reply result-*` như mục 4.1; lượt kế "Có." = nhắn tin.
- Mất phiên WS giữa cuộc gọi: server cúp và báo app server; kính mở lại phiên thì không có cuộc gọi nào còn.
- Cue riêng cho chuông/kết nối/kết thúc CHƯA có clip (`CUE_VERSION` không đổi): kính tự phát âm báo theo `call_state` nếu muốn; giọng đọc đã đủ cho người dùng.
- Khẩn cấp ("cấp cứu, gọi người thân giúp tôi"): đọc "Đang gọi người thân khẩn cấp, bấm nút để huỷ.", sau cửa sổ huỷ là `ringing_out` kéo dài tối đa 3 vòng x số người
  (mỗi người ≤ `CALL_RING_TIMEOUT_S`); người nghe thì `active`. Hết vòng: `ended` với `reason:"emergency_exhausted"` và câu "Chưa liên lạc được người thân nào.".

### 16.3. Tin nhắn

Không có khung riêng: lời nhắn đi bằng lượt lệnh bình thường ("nhắn tin cho mẹ là con về muộn"; "đọc tin nhắn"). Tin tới từ người thân được server đọc
"{tên} nhắn: {nội dung}" bằng một `reply result-*` (mục 4.1) khi kính **rảnh** (không trong lượt, không OCR live, không cuộc gọi); đang bận thì xếp hàng và đọc sau,
không chen ngang. Đọc xong server báo app server là đã đọc.

### 16.4. Đã kiểm

`tools/e2e_calls.py` (kính giả gửi `0x05` ADPCM, nhận `0x02`, bấm `call_answer`/`call_hangup`): bảng số đo ở `docs/E2E_FULL_FLOW.md` mục "Cuộc gọi, tin nhắn, khẩn cấp".
**Chưa đo trên kính thật/Cloudflare, và firmware chưa gửi `0x05`/khử vọng (AEC) chưa kiểm.**
