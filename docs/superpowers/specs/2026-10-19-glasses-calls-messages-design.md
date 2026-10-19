# Gọi điện và nhắn tin qua kính (server ↔ app người thân)

Ngày: 2026-10-19. Phạm vi: server kính (`visioncare-host-demo`, "VH") + app server
(`app-demo-backend/server`, "AB") + **hợp đồng** cho app điện thoại. App điện thoại do người
dùng tự làm theo hợp đồng ở §7; không sửa code `mobile/` trong dự án này.

## 1. Ý định

Người dùng: gọi điện và nhắn tin làm **hoàn toàn trong hệ thống**, không dùng trình gọi/SMS
của hệ điều hành (né giới hạn iOS: app không tự gọi số, không tự gửi SMS). Người khiếm thị
**nghe và nói ngay trên kính**; âm thanh đi qua server tới **app của người thân**. Người thân
là **user của chính app hiện tại**, app thêm chức năng mới. Khẩn cấp = **gọi người thân**
(không gọi 115). Mọi chức năng khác (Spotify, Maps, Grab, nhạc, chỉ đường) **giữ nguyên**.
Tiêu chí như dự án trước: độ trễ thấp nhất, chính xác nhất.

## 2. Mục tiêu, không làm, phản mục tiêu

**Mục tiêu:**
- Kính gọi người thân bằng giọng nói ("gọi cho mẹ"); người thân gọi tới kính (lựa chọn của
  Claude: hai chiều — ghi ở §9).
- Nhắn tin bằng giọng nói ("nhắn cho mẹ là con về muộn"); tin người thân gửi được đọc trên kính.
- Khẩn cấp: gọi lần lượt người thân khẩn cấp tới khi có người nghe + nhắn vị trí cho tất cả.
- Độ trễ âm thanh một chiều (miệng → tai) qua Cloudflare ≤ 400 ms; nhả nút → chuông kêu trên
  app người thân ≤ readback + 1 s.

**Không làm:** gọi số điện thoại thường/115; video; nhóm gọi; sửa code app điện thoại; WebRTC
(chỉ cân nhắc nếu đo ra WebSocket kém, §5.3).

**Phản mục tiêu:** gọi nhầm người; người thân không biết có cuộc gọi (chuông không kêu);
khẩn cấp dừng ở người đầu tiên không nghe máy; lộ âm thanh/tin nhắn cho người không được
liên kết.

## 3. Kiến trúc: tách tín hiệu và âm thanh

```
TÍN HIỆU (gọi ai, chuông, nghe/từ chối/cúp, tin nhắn, danh sách người thân)
  kính ──WS phiên──▶ VH ──HTTP (token glasses-server)──▶ AB ──FCM──▶ app người thân
  kính ◀──WS phiên── VH ◀──callback /internal/...────── AB ◀──HTTP── app người thân

ÂM THANH CUỘC GỌI (không qua AB)
  kính ──WS phiên (0x05 mic ADPCM)──▶ VH call bridge ──WS /v2/call (PCM16)──▶ app
  kính ◀──WS phiên (0x02 ADPCM)───── VH call bridge ◀──WS /v2/call (PCM16)── app
```

- **AB** sở hữu: quan hệ người thân, cuộc gọi (trạng thái, lịch sử), tin nhắn (lưu trữ), FCM,
  xác thực app. Đúng vai hiện có của nó (user, thiết bị, FCM, at-least-once).
- **VH** sở hữu: WebSocket phiên của kính (dự án trước, `WS /v2/session`), cầu âm thanh,
  STT/TTS, token media một lần. Mỗi chặng trung chuyển thêm độ trễ nên âm thanh không đi qua AB.

## 4. Mô hình dữ liệu ở AB

- `care_links`: `id`, `owner_user_id` (người khiếm thị), `relative_user_id`, `aliases`
  (danh sách tên gọi: "mẹ", "má"), `display_name`, `emergency` (bool), `priority` (int, nhỏ =
  gọi trước), `status` (`pending|active|revoked`), thời gian. Một cặp (owner, relative) duy nhất.
- `calls`: `id`, `owner_user_id`, `glasses_device_id`, `relative_user_id`, `direction`
  (`to_relative|to_glasses`), `emergency`, `state` (`ringing|active|ended|missed|rejected|failed`),
  `end_reason`, `media_token_hash`, `created_at/answered_at/ended_at`.
- `messages`: `id`, `owner_user_id`, `relative_user_id`, `direction`, `text`, `created_at`,
  `delivered_at`, `read_at`, `request_id` (idempotent).

## 5. Luồng

### 5.1. Kính gọi người thân

1. Intent `contact_call` (đã có), tham số `contact_name`. VH gọi AB
   `POST /api/v1/service/call/start {user_id, contact_alias, emergency:false, media_token}`.
   AB khớp `contact_alias` với `aliases`/`display_name` của các link `active` (chuẩn hoá: thường
   hoá, bỏ dấu câu; có dấu và không dấu đều khớp). Kết quả: một người → tạo call `ringing`, FCM
   `call_incoming` tới mọi thiết bị của người thân; nhiều người → `MULTIPLE_CONTACTS_FOUND`
   kèm ứng viên → kính hỏi "Bạn muốn gọi ai: …?"; không ai → `CONTACT_NOT_FOUND` → "Chưa có
   người thân tên … trong danh sách."
2. Cổng an toàn làn D của dự án trước giữ nguyên: đọc lại "Đang gọi cho Mẹ." rồi mới gọi AB;
   bấm nút trong lúc đọc → huỷ (`pending_action`).
3. Kính nghe tiếng chuông chờ (cue `call_ringing` lặp). Người thân bấm nghe → app gọi AB
   `POST /api/v1/calls/{id}/answer` → AB trả `{media_url, media_token}` (token do VH sinh ở
   bước 1, AB chỉ chuyển) và callback VH `call_answered`. App mở `WS /v2/call?token=…`.
   VH nối âm thanh hai bên, gửi kính `call_state active`.
4. Cúp: kính bấm nút (`call_hangup`) hoặc app (`{"t":"hangup"}` trên media WS + AB
   `/calls/{id}/hangup`) → VH đóng cầu, báo AB; AB ghi `ended`.
5. Không ai nghe sau `CALL_RING_TIMEOUT_S` = 30 s → `missed`; kính nghe "Mẹ chưa nghe máy.
   Bạn muốn nhắn tin không?" (lượt sau trả lời có/không như cơ chế pending của dự án trước).

### 5.2. Người thân gọi tới kính

App `POST /api/v1/calls {owner_user_id}` (người gọi phải có link `active`) → AB tạo call
`to_glasses`, callback VH `call_incoming {call_id, from: display_name}`. VH: kính có phiên WS
→ gửi `call_state ringing_in` + chuông, đọc "Mẹ đang gọi. Bấm nút để nghe."; không có phiên →
báo AB `GLASSES_OFFLINE` ngay. Kính bấm nút → `call_answer` → VH trả AB, app nhận
`media_url/media_token` qua FCM `call_answered` hoặc polling `GET /api/v1/calls/{id}`.

### 5.3. Âm thanh

- Kính ↔ VH: trên WS phiên sẵn có. Mic kính gửi binary `0x05` + ADPCM 16 kHz (tách khỏi
  `0x03` của lượt lệnh để không đụng logic lượt). VH gửi kính binary `0x02` ADPCM như hiện tại.
- App ↔ VH: `WS /v2/call?token=` một lần, binary PCM16LE 16 kHz mono khung 20 ms (640 B);
  text `{"t":"hangup"}`, `{"t":"mute","on":bool}`; VH gửi `{"t":"state","state":…}`.
- VH: đệm chống giật (jitter buffer) mục tiêu 60 ms mỗi hướng, bỏ khung trễ quá 200 ms;
  ADPCM ↔ PCM16 bằng `pipeline/adpcm.py`.
- **Vọng tiếng**: loa và mic kính gần nhau. Khử vọng là việc của firmware (ESP-SR AFE AEC);
  VH có chế độ dự phòng `CALL_HALF_DUPLEX=1` (giảm mic kính 20 dB khi đầu kia đang nói). Phải
  đo trên kính thật.
- WebSocket trước vì đi qua tunnel Cloudflare được ngay; WebRTC (UDP, cần TURN) chỉ làm nếu đo
  ra trễ/giật kém trên mạng di động.

### 5.4. Nhắn tin

- Intent mới `message_send` (tham số `contact_name`, `text`) và `message_read`. Gửi: đọc lại
  "Nhắn cho Mẹ: con về muộn." + cửa sổ huỷ → AB `POST /api/v1/service/messages/send
  {user_id, contact_alias, text, request_id}` → FCM `message_in` tới người thân.
- Người thân gửi: app `POST /api/v1/messages {owner_user_id, text, request_id}` → AB callback VH
  `message_received {message_id, from, text}`. Kính rảnh (không trong lượt/cuộc gọi/live OCR)
  → cue `message_in` + "Mẹ nhắn: …", rồi báo AB `read`. Đang bận → xếp hàng, đọc khi rảnh.
  "Đọc tin nhắn" (`message_read`) → đọc các tin chưa đọc (AB `GET` theo owner).
- Hai nhãn mới phải vào tập gold + bộ phân loại bằng chính công cụ của dự án trước
  (`tools/intent_gold`, `tools/eval_intent.py`); không giảm độ chính xác các nhãn cũ.

### 5.5. Khẩn cấp

`emergency_call` → VH đọc "Đang gọi người thân khẩn cấp, bấm nút để huỷ." → AB
`POST /api/v1/service/emergency/start {user_id, media_token_seed}`. AB: lấy link
`emergency=true` theo `priority`; cùng lúc gửi tin "KHẨN CẤP: <tên> cần giúp. Vị trí: <link bản
đồ>" (vị trí lấy bằng operation `location_get` sẵn có trên điện thoại người khiếm thị; lỗi thì
gửi không kèm vị trí) tới tất cả; gọi lần lượt, mỗi người đổ chuông 30 s, hết danh sách lặp
lại, tối đa 3 vòng. Người đầu tiên nghe → nối âm thanh như §5.1. Bấm nút trên kính lúc đang
chuông → dừng chuỗi. FCM khẩn cấp dùng priority cao + kênh thông báo riêng.

## 6. Giao thức kính (thêm vào `WS /v2/session`)

| Hướng | Khung | Ý nghĩa |
|---|---|---|
| server → kính | `{"t":"call_state","call":id,"state":"ringing_out"\|"ringing_in"\|"active"\|"ended","peer":str,"reason"?:str}` | trạng thái cuộc gọi |
| kính → server | binary `0x05` + ADPCM | mic trong cuộc gọi |
| server → kính | binary `0x02` + ADPCM | tiếng đầu kia (như audio trả lời) |
| kính → server | `{"t":"call_answer","call":id}` / `{"t":"call_hangup","call":id}` | nghe / cúp |

Nút: `ringing_in` → bấm = nghe; `ringing_out`/`active` → bấm = cúp (kính gửi `call_hangup`, không
gửi `turn_start`). Đang gọi thì làn C (cảnh báo vật cản) dừng; âm hazard không trộn vào cuộc gọi
ở bản này.

## 7. Hợp đồng cho app (người dùng tự làm)

Viết thành `app-demo-backend/docs/CALLS_MESSAGES_APP_CONTRACT.md`: các endpoint `/api/v1/care/*`,
`/api/v1/calls*`, `/api/v1/messages*` (request/response/lỗi), payload FCM (`call_incoming`,
`call_answered`, `call_ended`, `message_in`, `emergency_alert`), media WS, máy trạng thái màn
hình cuộc gọi, quyền cần (mic, thông báo toàn màn hình). OpenAPI cập nhật bằng
`scripts/export_openapi.py`.

## 8. Kiểm thử

- AB: test trên PostgreSQL thật (quy định `AB/claude.md`), mọi chuyển trạng thái call/link/message,
  idempotency `request_id`, timeout chuông.
- VH: test cầu âm thanh với WS giả hai đầu (thứ tự khung, jitter, cúp từ mỗi phía, token dùng lại bị từ chối).
- Mô phỏng người thân `AB/scripts/relative_sim.py`: user người thân, nhận FCM qua transport
  `webhook` (dự án trước, Task 15), nghe/từ chối theo kịch bản, mở media WS, phát WAV, ghi lại tiếng nhận.
- `VH/tools/e2e_calls.py`: kính giả lập ↔ VH ↔ AB ↔ relative_sim; đo nhả nút → chuông, nghe →
  tiếng đầu, trễ một chiều (chèn tiếng "tách" và dò ở đầu kia), cả local và qua Cloudflare.

## 9. Lựa chọn do Claude quyết (người dùng kiểm khi đọc)

- Gọi **hai chiều** (người thân gọi được tới kính) — câu hỏi chưa được trả lời; làm cả hai vì
  luồng ngược dùng lại gần hết luồng xuôi.
- Token media do VH sinh, AB chỉ chuyển (VH là nơi kiểm token khi app mở WS).
- WebSocket PCM16 thay vì WebRTC/Opus; jitter 60 ms; chuông 30 s; khẩn cấp tối đa 3 vòng.
- Mic cuộc gọi dùng khung `0x05` riêng; đang gọi thì tắt làn C.
- Khớp tên người thân ở AB (nơi có dữ liệu), không ở VH.
- Phụ thuộc dự án trước: `WS /v2/session`, `guard`, `pending_action`, transport `webhook` —
  dự án này bắt đầu sau khi plan `2026-10-19-voice-v2-hardening.md` xong Task 15.
