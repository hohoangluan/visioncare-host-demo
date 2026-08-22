# T22 — Bật lại TLS trên firmware

| | |
|---|---|
| **Mã spec** | F9 · F7 (phần còn lại) · 27.2 27.3 |
| **SPEC gốc** | 27.2, 27.3, 27.9 |
| **Repo đụng** | **Firmware** · Server kính (đo lại) |
| **Trạng thái** | READY |
| **Chặn bởi** | — |
| **Chặn** | **T21** (ngân sách phải đo có TLS) · **T18** (đo RAM phải sau khi bật TLS) |

> 🔴 **Đây là chặn phát hành, không phải việc tối ưu.**
>
> Ảnh chụp **trong nhà người dùng** và **giọng nói** của người khiếm thị đang đi
> hiện **không mã hoá** trên chặng kính → Cloudflare. Ai ở cùng lớp Wi-Fi
> (hotspot điện thoại) đều đọc được.

---

## 1. Hiện trạng

`app_config.h:52` — `#define API_USE_TLS 0`.

### Quyết định này **có số đo đằng sau**

Bắt tay TLS tốn **3992–4851 ms** CPU của ESP32-S3 (không có tăng tốc phần cứng
cho ECC). Đây là lý do thật, không phải cẩu thả.

Nhưng hệ quả phải nằm trong spec chứ không chỉ trong README firmware.

### Đường thoát đã có sẵn, chỉ chưa ghép

`apiWarmUp()` mở phiên **trước** khi người dùng bấm nút và giữ **60 s**
(`TLS_KEEPALIVE_MS`).

Bật TLS mà giữ được phiên nóng thì 4–5 giây kia **nằm ngoài đường tới hạn**.

**Rủi ro còn lại:** bấm nút sau hơn 60 s im lặng → lượt đó ăn trọn 4–5 giây.

### F7 — phần lớn đã xong (27.2)

| Việc trong F7 | Trạng thái thật |
|---|---|
| audio trước ảnh | ❌ **HUỶ** — xem T17/27.1 |
| `Connection: keep-alive` | ✅ có, giữ phiên 60 s |
| Cache IP, bỏ DNS mỗi request | ✅ `apiResolve()`, DNS một lần lúc khởi động |
| Chụp lúc **bắt đầu** nói | ✅ `photoCapture()` chạy ngay khi bấm nút |
| Phát audio từ chunk đầu | ✅ `waitAndPlay()`, đệm tự điều chỉnh |
| TLS session resumption | ⚠️ **không áp dụng — TLS đang TẮT** |
| `TCP_NODELAY` | ⚠️ chỉ ở đường **chẩn đoán** (`wifi_manager.cpp:520`); socket thật trong `api_client.cpp` **không** gọi `setNoDelay()` |
| `X-Device-Id` / `X-Turn-Id` | ❌ **T01** |
| Bỏ ảnh cho intent không cần | ❌ cần T17 + T18 |
| Ảnh phân tầng | ❌ T17 |

**Còn đúng ba việc: T01, `setNoDelay(true)` trên socket thật, và nhóm T17/T18.**

---

## 2. Việc phải làm

### F9 — bật `API_USE_TLS 1` rồi **đo lại**

```
1. bật TLS
2. đo p50/p95 với apiWarmUp() ĐANG CHẠY
3. lượt "nguội" (>60 s im lặng) vẫn 4-5 giây?
   → nới TLS_KEEPALIVE_MS
   → cho loop() warm-up CHỦ ĐỘNG
```

🔴 **Đừng bù bằng cách tắt mã hoá.** Đây là ràng buộc cứng của task.

Ba hướng nếu vẫn chậm:

| Hướng | Đổi lại |
|---|---|
| Nới `TLS_KEEPALIVE_MS` (60 s → 180 s?) | tốn pin giữ socket |
| `loop()` warm-up chủ động theo nhịp | tốn pin + băng thông |
| TLS session resumption (ticket/ID) | phải kiểm Cloudflare có hỗ trợ không |

### `setNoDelay(true)` trên socket thật

`api_client.cpp` — không phải chỉ `wifi_manager.cpp:520`. Spec F7 ước tính
**40–200 ms**. Một dòng.

### F10 — kéo theo: ngân sách phải đo lại

Mọi số trong `DETAILED_STAGE_LATENCY_BENCHMARK.md` đo với `API_USE_TLS 0`.
Sau task này, **T21 phải chạy lại toàn bộ**.

### Ràng buộc cho T18

Bật TLS xong thì `/events` là **phiên TLS thứ hai** cùng lúc. **Đo RAM sau khi
bật TLS**, không phải trước — đo trước là đo một cấu hình không phát hành được.

---

## 3. Hợp đồng đổi

Không đổi hợp đồng. Nhưng ghi vào `CONTRACTS.md`:

```
Chặng kính → server: HTTPS BẮT BUỘC trước khi phát hành.
Mọi số đo độ trễ chỉ có giá trị khi đo với API_USE_TLS 1.
```

---

## 4. Test

### 4.1 Bảo mật — kiểm bằng bắt gói

| Kiểm | Cách | Đạt khi |
|---|---|---|
| Ảnh không đi bản rõ | Wireshark trên cùng lớp Wi-Fi hotspot | không thấy JPEG magic `FF D8 FF` |
| Giọng nói không đi bản rõ | như trên | không đọc được payload |
| Server từ chối HTTP | thử `http://` | từ chối hoặc redirect |

**Đây là kiểm bằng tay, bắt buộc.** Không có test tự động nào thay được.

### 4.2 Độ trễ — `measurements/F9.md`

```
lượt NÓNG   (warm-up còn hiệu lực)   → p50, p95
lượt NGUỘI  (>60 s im lặng)          → p50, p95
so với bản TLS=0                      → chênh bao nhiêu

thử nới TLS_KEEPALIVE_MS: 60 / 120 / 180 s
  → tỉ lệ lượt nguội giảm bao nhiêu
  → pin tốn thêm bao nhiêu
```

Phải có **cả hai loại lượt**. Chỉ đo lượt nóng là giấu đúng cái ca xấu nhất.

### 4.3 `setNoDelay`

```
đo p50 TTFB trước/sau       → kỳ vọng -40…-200 ms
```

### 4.4 Ổn định

| Kiểm | Đạt khi |
|---|---|
| 50 lượt liên tiếp | không lượt nào rớt kết nối |
| Rút Wi-Fi giữa lượt rồi cắm lại | board hồi phục, không cần reboot |
| RAM sau 50 lượt | không rò rỉ |
| Chạy 1 giờ | không reset |

### 4.5 Thủ công — cảm nhận người dùng

| Kịch bản | Đạt khi |
|---|---|
| Bấm nút sau khi để máy yên 5 phút | **chú ý ca này** — lượt nguội, có bị chờ 4-5 s không |
| Bấm liên tiếp 5 lượt | lượt 2-5 nhanh như trước khi bật TLS |

---

## 5. DoD

- [ ] `API_USE_TLS 1` trong `app_config.h:52`
- [ ] **Bắt gói xác nhận** ảnh và giọng nói **không còn đi bản rõ**
- [ ] `measurements/F9.md` có p50/p95 cho **cả lượt nóng lẫn lượt nguội**
- [ ] Lượt nóng không chậm hơn đáng kể so với TLS=0
- [ ] Lượt nguội có phương án (nới keepalive / warm-up chủ động), **có số**
- [ ] `setNoDelay(true)` trên socket thật của `api_client.cpp`, đo được cải thiện
- [ ] 50 lượt liên tiếp không rớt, không rò RAM
- [ ] `CONTRACTS.md` ghi "HTTPS bắt buộc trước khi phát hành"
- [ ] **T21 được thông báo phải đo lại** toàn bộ

---

## 6. Câu hỏi phải chốt

1. 🔴 **Bật TLS rồi thì p95 là bao nhiêu?** Chưa đo. Không có số này thì bảng
   ngân sách T21 đang mô tả một cấu hình không được phép phát hành.
2. **Cloudflare tunnel có hỗ trợ TLS session resumption không?** Có thì lượt
   nguội rẻ hơn nhiều. Chưa kiểm.
3. **Nới `TLS_KEEPALIVE_MS` tốn pin bao nhiêu?** Kính đeo đầu chạy pin. Cần đo
   trước khi chọn 180 s.
4. **Có chấp nhận phát hành với lượt nguội 4-5 giây không**, nếu tỉ lệ lượt nguội
   thấp (ví dụ < 5 %)? Đây là quyết định sản phẩm, không phải kỹ thuật.
