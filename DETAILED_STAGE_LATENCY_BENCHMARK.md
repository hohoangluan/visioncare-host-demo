# 📊 Báo Cáo Chi Tiết Độ Trễ Từng Giai Đoạn (STT, Intent, Gemini/App, Action & TTFB)

**Ngày thực hiện**: 24/08/2026 13:08

**Môi trường**: Glasses Server (`8000`) & Backend Host Server (`8001`)

**Đường ngoài**: `https://api.visioncare-host.uk/process` (Cloudflare tunnel, keep-alive)

**Tài khoản**: `user-100` | **Kính**: `glasses-123` | **Điện thoại**: `device-100` (ACTIVE)


## 📌 Phần Cloudflare cộng thêm (đo riêng, 272KB qua `/frame`)

Đo trên `/frame` vì nó trả 204 ngay, không có Gemini xen vào — khác với cột TTFB ở các bảng dưới, vốn còn cõng độ trễ Gemini dao động 56ms–5930ms và KHÔNG được đem trừ cho nhau.

| Đường | Kết nối mới mỗi lượt | Keep-alive | Keep-alive tiết kiệm |
| :--- | :---: | :---: | :---: |
| localhost | 28 ms | 3 ms | 25 ms |
| Cloudflare tunnel | 1350 ms | 516 ms | 834 ms |

---

## 📌 Chức năng: Chat Trò chuyện

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Bây giờ là mấy giờ"* | 2424 ms | 60582 ms (chat) | 5435 ms | **N/A (AI Speech)** | **88 ms** | **1461 ms** | 9.077 s | **PASSED** |
| **L2 - Trung bình** | *"Thời tiết hôm nay thế nào"* | 38 ms | 17 ms (chat) | 1188 ms | **N/A (AI Speech)** | **16 ms** | **1343 ms** | 2.910 s | **PASSED** |
| **L3 - Khá** | *"Kể cho tôi nghe một câu chuyện ngắn về sự kiên trì"* | 62 ms | 14 ms (chat) | 1057 ms | **N/A (AI Speech)** | **29 ms** | **1765 ms** | 9.585 s | **PASSED** |
| **L4 - Phức tạp + GPS** | *"Xung quanh vị trí của tôi ở Tân Triều có nhà thuốc nào gần nhất không"* | 65 ms | 16 ms (chat) | 1663 ms | **N/A (AI Speech)** | **45 ms** | **1855 ms** | 3.989 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tôi... muốn... hỏi... hôm... nay... ngày... bao... nhiêu"* | 44 ms | 13 ms (chat) | 1499 ms | **N/A (AI Speech)** | **33 ms** | **2404 ms** | 2.984 s | **PASSED** |
| **L6 - Đa yêu cầu** | *"Chào bạn, hãy cho tôi biết hôm nay ngày mấy và thời tiết ở đây ra sao"* | 68 ms | 13 ms (chat) | 1346 ms | **N/A (AI Speech)** | **65 ms** | **1838 ms** | 4.894 s | **PASSED** |

---

## 📌 Chức năng: OCR Đọc chữ

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc chữ"* | 23 ms | 8 ms (ocr) | 116 ms | **N/A (AI Speech)** | **34 ms** | **1707 ms** | 0.143 s | **PASSED** |
| **L2 - Trung bình** | *"Đọc chữ trong ảnh"* | 28 ms | 10 ms (ocr) | 51 ms | **N/A (AI Speech)** | **25 ms** | **2473 ms** | 0.118 s | **PASSED** |
| **L3 - Đoạn văn** | *"Đọc cho tôi đoạn văn bản in trên nhãn chai này"* | 53 ms | 13 ms (ocr) | 82 ms | **N/A (AI Speech)** | **24 ms** | **1932 ms** | 0.152 s | **PASSED** |
| **L4 - Tìm thông tin** | *"Hãy tìm và đọc số điện thoại ghi trong bức ảnh này"* | 50 ms | 1418 ms (ocr) | 1437 ms | **N/A (AI Speech)** | **25 ms** | **1729 ms** | 1.258 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"đọc... chữ... góc... trên... trái"* | 38 ms | 10 ms (ocr) | 71 ms | **N/A (AI Speech)** | **35 ms** | **2157 ms** | 0.164 s | **PASSED** |
| **L6 - Đa dòng** | *"Đọc tất cả các dòng chữ in trên bảng từ trên xuống dưới"* | 54 ms | 13 ms (ocr) | 82 ms | **N/A (AI Speech)** | **44 ms** | **2343 ms** | 0.173 s | **PASSED** |

---

## 📌 Chức năng: Miêu tả không gian

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Miêu tả không gian"* | 26 ms | 9 ms (space) | 3247 ms | **N/A (AI Speech)** | **18 ms** | **1374 ms** | 5.053 s | **PASSED** |
| **L2 - Trung bình** | *"Phía trước tôi có những đồ vật gì"* | 41 ms | 1123 ms (space) | 2668 ms | **N/A (AI Speech)** | **29 ms** | **1424 ms** | 5.797 s | **PASSED** |
| **L3 - Lối đi an toàn** | *"Miêu tả căn phòng này và chỉ ra lối đi an toàn cho người khiếm thị"* | 63 ms | 16 ms (space) | 1982 ms | **N/A (AI Speech)** | **44 ms** | **1826 ms** | 4.811 s | **PASSED** |
| **L4 - Chi tiết vị trí** | *"Liệt kê chi tiết các đồ nội thất từ trái qua phải và khoảng cách"* | 60 ms | 1403 ms (space) | 2812 ms | **N/A (AI Speech)** | **30 ms** | **1826 ms** | 5.589 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"phía... trước... có... vật... cản... nguy... hiểm... nào... không"* | 52 ms | 15 ms (hazard) | 2070 ms | **N/A (AI Speech)** | **23 ms** | **1676 ms** | 4.532 s | **PASSED** |
| **L6 - Đa thông tin** | *"Nhìn ảnh và cho tôi biết không gian phòng rộng bao nhiêu và có ai không"* | 65 ms | 16 ms (space) | 1965 ms | **N/A (AI Speech)** | **25 ms** | **1563 ms** | 5.848 s | **PASSED** |

---

## 📌 Chức năng: Tìm đồ vật

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Tìm chìa khóa"* | 35 ms | 11 ms (find) | 2903 ms | **N/A (AI Speech)** | **33 ms** | **1541 ms** | 5.098 s | **PASSED** |
| **L2 - Trung bình** | *"Gói bánh nằm ở đâu"* | 28 ms | 12 ms (find) | 2831 ms | **N/A (AI Speech)** | **27 ms** | **1508 ms** | 4.436 s | **PASSED** |
| **L3 - Hướng di chuyển** | *"Tìm giúp tôi gói bánh trên bàn và hướng di chuyển"* | 54 ms | 11 ms (find) | 2763 ms | **N/A (AI Speech)** | **36 ms** | **1435 ms** | 4.324 s | **PASSED** |
| **L4 - Góc giờ + Mét** | *"Hãy tìm xem gói bánh nằm ở hướng mấy giờ và cách bao nhiêu mét"* | 75 ms | 13 ms (chat) | 1443 ms | **N/A (AI Speech)** | **39 ms** | **2690 ms** | 2.915 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tìm... giúp... tôi... gói... bánh... ở... gần... đây"* | 38 ms | 11 ms (chat) | 1182 ms | **N/A (AI Speech)** | **34 ms** | **1294 ms** | 3.160 s | **PASSED** |
| **L6 - Kèm dạng cầm** | *"Tìm gói bánh và mô tả kích thước cầm nắm giúp tôi"* | 50 ms | 12 ms (find) | 2694 ms | **N/A (AI Speech)** | **48 ms** | **1320 ms** | 5.020 s | **PASSED** |

---

## 📌 Chức năng: Đọc tiền

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc tiền"* | 23 ms | 8 ms (money) | 2767 ms | **N/A (AI Speech)** | **35 ms** | **1876 ms** | 2.653 s | **PASSED** |
| **L2 - Trung bình** | *"Tờ tiền này mệnh giá bao nhiêu"* | 37 ms | 10 ms (money) | 2493 ms | **N/A (AI Speech)** | **43 ms** | **1606 ms** | 1.861 s | **PASSED** |
| **L3 - Phân loại** | *"Kiểm tra tờ tiền trên tay tôi là tiền polyme hay tiền giấy"* | 56 ms | 13 ms (money) | 2257 ms | **N/A (AI Speech)** | **34 ms** | **2040 ms** | 3.000 s | **PASSED** |
| **L4 - Chi tiết mệnh giá** | *"Cho tôi biết tờ tiền này là mấy trăm nghìn đồng"* | 50 ms | 11 ms (money) | 2059 ms | **N/A (AI Speech)** | **37 ms** | **1214 ms** | 4.174 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"xem... giúp... tờ... tiền... này... mệnh... giá... bao... nhiêu"* | 57 ms | 15 ms (money) | 2516 ms | **N/A (AI Speech)** | **31 ms** | **1523 ms** | 2.847 s | **PASSED** |
| **L6 - Đa tờ tiền** | *"Trên bàn có những tờ tiền mệnh giá bao nhiêu"* | 46 ms | 17 ms (money) | 2158 ms | **N/A (AI Speech)** | **15 ms** | **1335 ms** | 3.502 s | **PASSED** |

---

## 📌 Chức năng: Thao tác Điện thoại

| Cấp độ | Lệnh thoại | STT Latency | Intent Latency | Gemini/App Latency | Action Finish | TTFB local | TTFB qua Cloudflare | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Mở nhạc** | *"Mở bài hát Nơi này có anh"* | 34 ms | 1707 ms (music_play) | 1259 ms | **0.000 s** | **31 ms** | **1143 ms** | 1.857 s | **PASSED** |
| **L2 - Gọi điện** | *"Gọi điện cho Nguyễn Văn A"* | 33 ms | 1612 ms (contact_call) | 6495 ms | **0.000 s** | **27 ms** | **1392 ms** | 8.201 s | **PASSED** |
| **L3 - Chỉ đường** | *"Chỉ đường cho tôi tới Bưu điện Thành phố"* | 41 ms | 1358 ms (nav_start) | 5215 ms | **0.000 s** | **23 ms** | **1579 ms** | 7.228 s | **PASSED** |
| **L4 - Đặt xe** | *"Đặt xe đi Đại học Bách Khoa"* | 40 ms | 1743 ms (ride_quote) | 1349 ms | **0.000 s** | **26 ms** | **1385 ms** | 1.436 s | **PASSED** |
| **L5 - Gọi cấp cứu** | *"Gọi cấp cứu khẩn cấp"* | 31 ms | 1297 ms (emergency_call) | 4118 ms | **0.000 s** | **59 ms** | **1346 ms** | 4.209 s | **PASSED** |
| **L6 - Chỉnh âm lượng** | *"Tăng âm lượng điện thoại lên"* | 30 ms | 1354 ms (music_volume) | 5359 ms | **0.000 s** | **33 ms** | **1293 ms** | 5.282 s | **PASSED** |

---
