# F6 — RAM khi nhiều phiên TLS cùng mở (T18 mục 4)

Đo 2026-08-25 trên board thật, `glasses-01`, firmware `2026.08.25-ota11`,
`API_USE_TLS 1`, mạng `Thanh_Cuong_FI`.

Câu hỏi mà T18 DoD để ngỏ: *"RAM đo được với 2 socket + TLS"*. Trước file này
mọi con số về nó đều là **ước lượng**, và một trong những ước lượng đó (khối
liền còn 106 KB) hoá ra **sai gấp ba lần**.

---

## 1. Số nền — sau khi mọi thứ đã cấp phát xong

Board tự in ở cuối `setup()`:

```
--- BO NHO: truoc khi cap phat audio ---
                    con trong    khoi lien lon nhat   thap nhat tung cham
  RAM noi (DRAM)     108176 B           65524 B          108176 B
  PSRAM             8010820 B         7995380 B         8010820 B

--- BO NHO: sau khi cap phat audio — day la muc nen thuc te ---
                    con trong    khoi lien lon nhat   thap nhat tung cham
  RAM noi (DRAM)      77044 B           36852 B           77044 B
  PSRAM             6290488 B         6160372 B         6290488 B
```

🔴 **Khối liền lớn nhất là 36 852 B, không phải 106 KB.**

Con số đáng nhìn là **khối liền**, không phải tổng còn trống. mbedtls xin
**~45 KB LIỀN** cho mỗi phiên. 77 044 B còn trống mà khối liền chỉ 36 852 B thì
một phiên TLS **không** cấp phát được — dù nhìn tổng thì thừa gấp rưỡi.

| | trước file này (ước) | đo được |
|---|---|---|
| khối liền sau cấp phát audio | ~106 KB | **36 852 B** |
| số phiên TLS đồng thời có thể mở | "vừa đủ 2" | **2, và phiên thứ 3 luôn chết** |

---

## 2. Bằng chứng: phiên thứ ba chết thật, có log

Bắt được ngay trong một lần OTA kéo, lúc `/events` + phiên ấm đang mở và
`otaPullIfAvailable()` xin phiên thứ ba:

```
[OTA-PULL] 30%
  TCP/TLS toi 172.67.176.233 HONG sau 60 ms
  bat tay hong: connected=0, mbedtls -32512 (-0x7F00) SSL - Memory allocation failed
  RSSI -54 dBm, heap 61076 B, khoi lien lon nhat 31732 B
  Nhuong RAM cua /events roi thu bat tay lai MOT lan
[OTA-PULL] 40%
  TCP/TLS toi 172.67.176.233 HONG sau 58 ms
  bat tay hong: connected=0, mbedtls -32512 (-0x7F00) SSL - Memory allocation failed
  RSSI -54 dBm, heap 60816 B, khoi lien lon nhat 31732 B
```

`31732 < 45000`. Chẩn đoán nằm trong log, không phải suy đoán — và **hỏng sau
60 ms**, tức nó chết ở `malloc` chứ không phải ở mạng. Phân biệt được hai thứ
đó là toàn bộ giá trị của dòng log kèm RAM.

Lần OTA đó **vẫn xong 100%**: đường kéo firmware có phiên riêng và nó chạy
trọn; hai dòng hỏng ở trên là phiên ẤM cố mở lại giữa chừng.

---

## 3. Hệ quả đã phải sửa vì con số này

### 3.1 Vòng canh vật cản báo `fps=0.00` — và không nói gì thêm

Bản đầu của T24 mở **một phiên TLS mới cho mỗi khung** (`Connection: close`),
vì mức nguy hiểm phải về bằng SSE nên không còn RAM cho phiên thứ hai. Đo được
trên board:

```
[HAZARD] fps=0.00 (0 khung / 5139 ms)
[HAZARD] fps=0.00 (0 khung / 5419 ms)
```

Chế độ **đã bật**, vòng chụp **đang chạy**, và **không một khung nào** ra khỏi
board. `/events` + phiên ấm đã chiếm hai chỗ; phiên của vòng canh chết ngay ở
`connect()`.

Với một tính năng cảnh báo vật cản thì đây là kiểu hỏng tệ nhất có thể: im
lặng tuyệt đối, trong khi người dùng vừa nghe *"Đã bật chế độ cảnh báo vật
cản"* và đang đi nhanh hơn vì tin là có máy canh.

**Sửa:** `apiSetWarmEnabled(false)` trong suốt chế độ canh — thôi giữ phiên ấm
và thả phiên đang giữ. Phiên ấm chỉ tiết kiệm ~630 ms cho **lần bấm đầu**;
trong chế độ canh thì đường chạy liên tục mới là thứ cần RAM. Lần bấm nút lấy
lại chỗ bằng `apiHazardClose()` ở `hazardWatchPause()`.

### 3.2 Bắt tay TLS 616–911 ms mỗi khung ⟹ trần fps ~1.1–1.5

Đo trong cùng phiên, ba lần liên tiếp:

```
TCP/TLS 104.21.67.134 OK (674 ms)
TCP/TLS 104.21.67.134 OK (626 ms)
TCP/TLS 104.21.67.134 OK (633 ms)
```

`HAZARD_WATCH_PERIOD_MS = 500` đặt mục tiêu 2 fps. Một lần bắt tay đã ăn hết
1,3 chu kỳ trước khi đẩy byte JPEG nào.

**Sửa:** server trả mức nguy hiểm ngay trong **thân response 200** của
`POST /frame` thay vì đẩy qua SSE. Bỏ được ràng buộc "phải chừa chỗ cho
/events" ⟹ giữ được **một** phiên keep-alive cho cả vòng canh ⟹ bắt tay biến
mất khỏi vòng lặp. SPEC mục 28.2 vốn đã yêu cầu đúng thế (*"board mở một kết
nối keep-alive… không bắt tay TLS lại mỗi khung hình"*); bản thi công đầu làm
ngược spec.

---

## 4. Luật rút ra — ghi để không phải đo lại

**Tối đa HAI phiên TLS cùng lúc.** Bất cứ đường nào cần phiên thứ ba phải
nhường trước, tường minh:

| Đường | Nhường gì trước khi mở |
|---|---|
| OTA kéo (`otaPullIfAvailable`) | `apiDropWarmSession()` + `eventStreamPause()` + `apiHazardClose()` |
| Kéo câu thông báo cuộc gọi (T19) | `eventStreamPause()` + `apiHazardClose()` |
| Vòng canh vật cản (T24) | `apiSetWarmEnabled(false)` suốt chế độ |
| Lần bấm nút trong lúc đang canh | `apiHazardClose()` (ở `hazardWatchPause()`) |

Và: **luôn in kèm `khoi lien lon nhat` khi bắt tay hỏng.** Không có dòng đó
thì "hết RAM liền" và "mạng hỏng" nhìn giống hệt nhau, và cả hai lần đã mất
nhiều giờ để lần ra đều là vì thiếu đúng con số này.

---

## 5. Còn nợ

- [ ] Đo lại khi `/events` + keep-alive `/frame` cùng mở **liên tục nhiều
      phút** — số ở trên là ảnh chụp lúc khởi động, chưa tính phân mảnh tích
      luỹ.
- [ ] Pin tiêu hao khi giữ hai phiên TLS thường trực (T18 mục 6 câu 3, SPEC
      28.9 câu 4).
