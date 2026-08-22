# T18 — Kênh downlink server → kính (SSE)

| | |
|---|---|
| **Mã spec** | F6 · 27.6 |
| **SPEC gốc** | mục 19 (F6), 27.6 |
| **Repo đụng** | Server kính · **Firmware** |
| **Trạng thái** | READY — nhưng **nặng hơn spec giả định** |
| **Chặn bởi** | **T01** · **T22** (đo RAM phải làm SAU khi bật TLS) |
| **Chặn** | T17/F5 (xin ảnh tầng cao) · **T19** (cuộc gọi đến) |

> ⚠️ Spec phần II xếp F6 như một việc vừa. **27.6 sửa lại: đây là một module
> mạng MỚI trên firmware**, không phải cấu hình thêm. Xếp lại công trước khi lên
> lịch.

---

## 1. Hiện trạng

**Không có đường server → kính.** Kính chỉ nói được khi người dùng bấm nút. Mọi
thứ server muốn chủ động báo (cuộc gọi đến, đổi cấu hình camera, xin ảnh tầng
cao) đều **không gửi được**.

### Ba thứ chưa có phía firmware (27.6)

1. **Board không có đường nhận chủ động.** Task audio xoay quanh nút bấm; web
   server cổng 80/81 chỉ để chẩn đoán, và board nằm **sau NAT của hotspot điện
   thoại** nên **server không gọi vào được**. Kênh do board mở là **cách duy
   nhất** — đúng như F6, nhưng đó là một **module mạng mới**.

2. **Thêm một socket giữ mở lâu** song song với socket POST, trên board đang chạy
   camera + `esp_http_server` + I2S full-duplex. Bật TLS (T22) thì thành **hai
   phiên TLS cùng lúc**. **Phải đo RAM trước** — `bigAlloc()` xin buffer lớn một
   lần lúc khởi động, phần còn lại rất mỏng.

3. **T19 đòi board tự phát tiếng lúc không ai bấm nút.** Trình tự hiện nằm gọn
   trong `audio_service.cpp` và **luôn bắt đầu từ nút**. Đây là đường mới trong
   đúng file mà kiến trúc firmware gọi là *"file DUY NHẤT biết trình tự"*.

---

## 2. Việc phải làm

### F6 — một kênh, **hai** mục đích

Kính mở `GET /events` và giữ.

```
1. xin ảnh tầng cao          (T17/F5)
2. báo cuộc gọi đến           (T19)
```

**Hai nhu cầu, xây một lần.** Đừng làm hai kênh.

### 2.1 Server kính

```
GET /events
  X-Device-Id  BẮT BUỘC
  → text/event-stream, giữ mở
  → heartbeat định kỳ (board cần biết kênh còn sống)
```

Sự kiện:

```jsonc
// xin ảnh tầng cao
{ "type": "frame_request", "turn_id": "...", "tier": "high" }

// cuộc gọi đến (T19)
{ "type": "call_incoming", "caller": {...} }

// heartbeat
{ "type": "ping" }
```

Yêu cầu:
- kênh **theo device**, không broadcast
- board rớt → server phát hiện được, không tích sự kiện vô hạn
- server restart → board tự nối lại (backoff)
- **không** dùng kênh này cho thứ có thể đi kèm response của `/process`

### 2.2 Firmware

- Module mạng mới: mở `GET /events`, giữ, tự nối lại khi rớt
- **Đo RAM trước khi viết** — làm **sau T22** (bật TLS) vì hai phiên TLS là ca
  xấu nhất
- Xử lý `frame_request` → chụp tầng cao → `POST /frame` (T17)
- Xử lý `call_incoming` → thuộc T19

### 2.3 Thứ tự đúng

```
T01 (device id)  →  T22 (bật TLS, đo RAM có TLS)  →  T18 (đo RAM 2 socket)  →  T19
                                                  →  T17/F5 (xin tầng cao)
```

**Đo RAM sau khi bật TLS, không phải trước.** Đo trước là đo một cấu hình không
được phép phát hành (xem T22).

---

## 3. Hợp đồng đổi

Ghi vào `CONTRACTS.md` mục *Kênh downlink*:

```
GET /events        (board mở, server giữ)
  X-Device-Id      BẮT BUỘC
  heartbeat         mỗi N giây
  event types       frame_request | call_incoming | ping
```

---

## 4. Test

### 4.1 Server — `tests/test_events_channel.py` (mới)

```
test_events_requires_device_id
test_events_per_device_not_broadcast
  sự kiện của device A KHÔNG tới device B

test_heartbeat_sent
test_client_disconnect_detected
  board rớt → server dọn, không giữ generator treo

test_events_do_not_queue_forever
  không có board nối → sự kiện KHÔNG tích vô hạn

test_frame_request_carries_turn_id            # T17
test_call_incoming_event_shape                 # T19
```

### 4.2 Vòng đời

```
test_reconnect_after_server_restart
test_two_devices_two_channels
test_channel_survives_process_request
  đang có /process chạy → /events không bị đóng
```

### 4.3 Firmware — đo, không phải test

| Đo | Cách | Ngưỡng |
|---|---|---|
| **RAM còn lại với 2 socket + TLS** | `esp_get_free_heap_size()` sau khi cả hai mở | phải còn đủ cho camera capture |
| Board tự nối lại | rút wifi 30 s rồi cắm | nối lại trong < 30 s |
| Kênh không ảnh hưởng lượt thường | đo p50 TTFB trước/sau | không tăng |

Kết quả ghi vào `docs/tasks/measurements/F6-ram.md`.

### 4.4 Thủ công

| Kịch bản | Đạt khi |
|---|---|
| Mở `/events`, để 10 phút | kênh còn sống, có heartbeat |
| Bấm nút hỏi bình thường trong lúc kênh mở | không chậm hơn |
| Restart server | board nối lại, không cần reboot board |

---

## 5. DoD

```bash
pytest tests/test_events_channel.py -q
```

- [ ] `GET /events` chạy, theo device, có heartbeat
- [ ] Board rớt → server dọn, không treo generator, không tích sự kiện
- [ ] Board tự nối lại sau khi server restart
- [ ] **RAM đo được với 2 socket + TLS**, có số trong `measurements/F6-ram.md`
- [ ] Kênh không làm chậm lượt `/process` thường (đo trước/sau)
- [ ] Một kênh phục vụ **cả hai** mục đích (frame_request + call_incoming) —
      không đẻ ra kênh thứ hai

---

## 6. Câu hỏi phải chốt

1. 🔴 **RAM còn đủ cho socket SSE thứ hai không?** Chưa đo, và **phải đo SAU khi
   bật TLS** (T22) chứ không phải trước. Đây là câu hỏi mở số 3 của mục 27.
2. **Cloudflare tunnel có giữ được SSE lâu không?** Tunnel có thể đóng kết nối
   nhàn rỗi. Heartbeat bao lâu một lần thì đủ? Chưa đo.
3. **Board tiêu thụ pin thêm bao nhiêu khi giữ socket?** Kính đeo đầu chạy pin —
   nếu tốn đáng kể thì cân nhắc chỉ mở kênh khi cần (nhưng như vậy thì
   `call_incoming` không tới được).
4. **Không làm được F6 thì T19 (cuộc gọi đến) chết theo.** Có phương án dự phòng
   nào không? (ví dụ: app tự phát tiếng qua loa điện thoại thay vì qua kính)
