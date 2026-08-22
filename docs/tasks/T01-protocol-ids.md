# T01 — Định danh thiết bị & lượt (`X-Device-Id` / `X-Turn-Id`)

| | |
|---|---|
| **Mã spec** | F1 · 27.2 (`setNoDelay`) |
| **SPEC gốc** | mục 19, 22 bước 1, 27.2 |
| **Repo đụng** | Server kính · **Firmware** |
| **Trạng thái** | READY |
| **Chặn bởi** | — |
| **Chặn** | **T03 T17 T18 T19** — và gián tiếp cả nhóm D, B |

> Đây là thứ **chặn nhiều việc nhất trong cả spec**. Không có `device_id` thì
> session, pending, idempotency, đa thiết bị đều không implement được.

---

## 1. Hiện trạng

### Server kính

`app.py:449-452`:

```python
def process(
    request: Request,
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
)
```

Không có `device_id`, không có `turn_id`. Thiết bị duy nhất được biết đến là
hằng số `config.py:200`:

```python
VISIONCARE_DEVICE_ID = get("VISIONCARE_DEVICE_ID", "glasses-123")
```

Hai kính chạy cùng lúc → trộn session, trộn pending, trộn nhạc.

State toàn cục, không khoá theo thiết bị:
`handlers/action_flow.py:61` `_LAST_IDS` · `:88` `_ACTIVE` · `handlers/chat.py:226`
`_HISTORY` · `:99` `_LOCATION_CACHE`.

### Firmware

`src/net/api_client.cpp:432` — không gửi header nào trong hai cái này.

`src/net/wifi_manager.cpp:520` **có** `setNoDelay()` nhưng chỉ ở đường **chẩn
đoán**; socket thật trong `api_client.cpp` không gọi.

---

## 2. Việc phải làm

### 2.1 Firmware

```
X-Device-Id:  glasses-123            // mã cứng theo board, hoặc từ NVS
X-Turn-Id:    <uuid v4, MỚI mỗi lượt>
X-Capture-Ts: <epoch ms lúc chụp>
```

**Header, không phải form field.** Server đọc được **trước khi** body upload
xong → tra được session và bắt được lượt trùng ngay, không phải đợi hết ảnh.

Thêm `setNoDelay(true)` trên socket thật của `api_client.cpp` (không phải chỉ ở
`wifi_manager.cpp:520`). Spec F7 ước tính 40–200 ms.

`X-Turn-Id` có **hai** vai trò, phải ghi rõ trong comment firmware để lần sau
không ai tưởng là một:

```
1. chống gửi lặp (idempotency)
2. ngắt lượt cũ   (barge-in — T04/G4)
```

### 2.2 Server kính

#### Đọc & bắt buộc

`app.py:449` nhận `request: Request` rồi đọc header. Thiếu `X-Device-Id` →
**từ chối rõ ràng**, không im lặng rơi về `config.VISIONCARE_DEVICE_ID`.

Rơi ngầm về hằng số là **cấm**: nó biến lỗi cấu hình firmware thành trộn session
giữa hai người dùng thật, và không có log nào báo.

Giai đoạn chuyển: cho phép fallback **nhưng `logger.warning` mỗi lần**, và có cờ
`config.REQUIRE_DEVICE_ID` bật được để test ca từ chối.

#### Idempotency

`X-Turn-Id` trùng trong cửa sổ ngắn → **không gọi API lần hai**, trả lại kết quả
cũ. Cửa sổ đề xuất 60 s, ghi vào `CONTRACTS.md`.

#### `device_id` xuống tới handler

Chữ ký handler hiện là `(image, command_text, params)`. Không nhét thêm tham số
vào từng handler — dùng **context** (`contextvars.ContextVar`) đặt ở `app.py`,
đọc ở `action_flow` / `chat` / pending store. Lý do: 15 handler, thêm tham số là
15 chỗ sửa và 15 chỗ quên.

---

## 3. Hợp đồng đổi

Ghi vào `CONTRACTS.md` mục *Giao thức kính ↔ server kính*:

```
POST /process
  X-Device-Id   BẮT BUỘC   string, ổn định theo board
  X-Turn-Id     BẮT BUỘC   uuid v4, mới mỗi lần bấm nút
  X-Capture-Ts  nên có     epoch ms lúc chụp

400 khi thiếu X-Device-Id   (giai đoạn chuyển: 200 + warning)
```

---

## 4. Test

### 4.1 Unit / API — không cần firmware

`tests/test_protocol_ids.py` **(mới)**:

```
test_missing_device_id_rejected
  POST /process không có X-Device-Id
  → từ chối RÕ RÀNG, KHÔNG im lặng bỏ qua, KHÔNG rơi về glasses-123

test_missing_device_id_warns_in_transition_mode
  REQUIRE_DEVICE_ID=0 → 200 nhưng có logger.warning

test_duplicate_turn_id_no_second_call
  hai POST cùng X-Turn-Id → host API chỉ được gọi MỘT lần
  → lượt hai trả kết quả cũ

test_different_turn_id_calls_again
  đổi X-Turn-Id → gọi lại bình thường

test_device_id_reaches_handler
  handler đọc được đúng device_id từ context, không phải hằng số config
```

### 4.2 Nhiều thiết bị (mục 23)

```
test_two_devices_independent_state
  pending / nhạc / lịch sử của device A không rò sang device B

test_two_requests_same_device_within_100ms
  không crash, không trộn kết quả
```

### 4.3 Firmware — thủ công

| Kiểm | Cách |
|---|---|
| header có ra dây không | `curl` giả lập không đủ — bắt bằng log server, mỗi lượt phải có 3 header |
| `X-Turn-Id` đổi mỗi lượt | bấm nút 5 lần, 5 uuid khác nhau |
| `setNoDelay` có tác dụng | đo p50 TTFB trước/sau, kỳ vọng −40…−200 ms |

---

## 5. DoD

```bash
pytest tests/test_protocol_ids.py -q
```

- [ ] Ba header ra dây thật từ board (log server chứng minh)
- [ ] `setNoDelay(true)` trên socket thật của `api_client.cpp`
- [ ] Từ chối khi thiếu `X-Device-Id` (hoặc warning ở chế độ chuyển)
- [ ] `device_id` đọc được từ handler qua context, **không** đọc `config.VISIONCARE_DEVICE_ID`
- [ ] `tests/test_protocol_ids.py` xanh, đủ 7 ca

---

## 6. Câu hỏi phải chốt

1. **Cửa sổ idempotency bao lâu?** Đề xuất 60 s. Dài quá thì người dùng lặp lại
   đúng câu bị nuốt; ngắn quá thì retry của board gọi API hai lần.
2. **`device_id` lấy từ đâu trên board?** MAC WiFi (ổn định, không cần cấu hình)
   hay NVS (đổi được lúc ghép máy). Ảnh hưởng luồng ghép kính ↔ tài khoản.
3. **Giai đoạn chuyển kéo dài bao lâu** trước khi bật `REQUIRE_DEVICE_ID=1`?
