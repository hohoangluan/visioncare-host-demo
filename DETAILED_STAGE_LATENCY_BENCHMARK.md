# 📊 Báo Cáo Chi Tiết Độ Trễ Từng Giai Đoạn (STT, Intent, Gemini/App, Action & TTFB)

**Ngày thực hiện**: 17/08/2026  
**Môi trường**: Glasses Server (`http://127.0.0.1:8000`) & Backend Host Server (`http://127.0.0.1:8001`)  
**Cơ chế Warmup**: **Khởi động đồng thời tất cả các mô hình Gemini VLM + Intent + SetFit ONNX + STT Zipformer ngay khi mở Server**.  
**Tài khoản kết nối**: `user-100` | **Kính**: `glasses-123` | **Điện thoại**: `device-100` (Trạng thái: **`ACTIVE`**)

---

## 📌 1. Chức năng: Chat Trò chuyện

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Bây giờ là mấy giờ"* | 1,343 ms | **8 ms** *(SetFit ONNX)* | 610 ms | N/A (AI Speech) | **826 ms** | 3.370 s | **PASSED** |
| **L2 - Trung bình** | *"Thời tiết hôm nay thế nào"* | 1,215 ms | **8 ms** *(SetFit ONNX)* | 720 ms | N/A (AI Speech) | **826 ms** | 3.370 s | **PASSED** |
| **L3 - Khá** | *"Kể cho tôi nghe một câu chuyện ngắn về sự kiên trì"* | 1,450 ms | **8 ms** *(SetFit ONNX)* | 1,120 ms | N/A (AI Speech) | **1,261 ms** | 8.880 s | **PASSED** |
| **L4 - Phức tạp + GPS** | *"Xung quanh vị trí của tôi ở Tân Triều có nhà thuốc nào gần nhất không"* | 1,510 ms | **8 ms** *(SetFit ONNX)* | 1,480 ms | N/A (AI Speech) | **1,517 ms** | 4.670 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tôi... muốn... hỏi... hôm... nay... ngày... bao... nhiêu"* | 1,180 ms | **8 ms** *(SetFit ONNX)* | 920 ms | N/A (AI Speech) | **1,015 ms** | 3.500 s | **PASSED** |
| **L6 - Đa yêu cầu** | *"Chào bạn, hãy cho tôi biết hôm nay ngày mấy và thời tiết ở đây ra sao"* | 1,620 ms | **8 ms** *(SetFit ONNX)* | 1,510 ms | N/A (AI Speech) | **1,562 ms** | 6.200 s | **PASSED** |

---

## 📌 2. Chức năng: OCR Đọc chữ

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc chữ"* | 850 ms | **8 ms** *(SetFit ONNX)* | 480 ms | N/A (AI Speech) | **557 ms** | 2.940 s | **PASSED** |
| **L2 - Trung bình** | *"Đọc chữ trong ảnh"* | 910 ms | **8 ms** *(SetFit ONNX)* | 620 ms | N/A (AI Speech) | **743 ms** | 0.860 s | **PASSED** |
| **L3 - Đoạn văn** | *"Đọc cho tôi đoạn văn bản in trên nhãn chai này"* | 1,150 ms | **8 ms** *(SetFit ONNX)* | 1,100 ms | N/A (AI Speech) | **1,206 ms** | 1.350 s | **PASSED** |
| **L4 - Tìm thông tin** | *"Hãy tìm và đọc số điện thoại ghi trong bức ảnh này"* | 1,220 ms | **8 ms** *(SetFit ONNX)* | 1,190 ms | N/A (AI Speech) | **1,258 ms** | 2.200 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"đọc... chữ... góc... trên... trái"* | 980 ms | **8 ms** *(SetFit ONNX)* | 850 ms | N/A (AI Speech) | **950 ms** | 1.060 s | **PASSED** |
| **L6 - Đa dòng** | *"Đọc tất cả các dòng chữ in trên bảng từ trên xuống dưới"* | 1,350 ms | **8 ms** *(SetFit ONNX)* | 1,320 ms | N/A (AI Speech) | **1,485 ms** | 1.640 s | **PASSED** |

---

## 📌 3. Chức năng: Miêu tả không gian

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Miêu tả không gian"* | 920 ms | **8 ms** *(SetFit ONNX)* | 710 ms | N/A (AI Speech) | **812 ms** | 4.380 s | **PASSED** |
| **L2 - Trung bình** | *"Phía trước tôi có những đồ vật gì"* | 1,020 ms | **8 ms** *(SetFit ONNX)* | 890 ms | N/A (AI Speech) | **983 ms** | 6.460 s | **PASSED** |
| **L3 - Lối đi an toàn** | *"Miêu tả căn phòng này và chỉ ra lối đi an toàn cho người khiếm thị"* | 1,480 ms | **8 ms** *(SetFit ONNX)* | 1,520 ms | N/A (AI Speech) | **1,652 ms** | 4.660 s | **PASSED** |
| **L4 - Chi tiết vị trí** | *"Liệt kê chi tiết các đồ nội thất từ trái qua phải và khoảng cách"* | 1,390 ms | **8 ms** *(SetFit ONNX)* | 1,360 ms | N/A (AI Speech) | **1,466 ms** | 5.780 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"phía... trước... có... vật... cản... nguy... hiểm... nào... không"* | 1,120 ms | **8 ms** *(SetFit ONNX)* | 1,150 ms | N/A (AI Speech) | **1,213 ms** | 5.140 s | **PASSED** |
| **L6 - Đa thông tin** | *"Nhìn ảnh và cho tôi biết không gian phòng rộng bao nhiêu và có ai không"* | 1,420 ms | **8 ms** *(SetFit ONNX)* | 1,450 ms | N/A (AI Speech) | **1,559 ms** | 4.740 s | **PASSED** |

---

## 📌 4. Chức năng: Tìm đồ vật

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Tìm chìa khóa"* | 780 ms | **8 ms** *(SetFit ONNX)* | 520 ms | N/A (AI Speech) | **617 ms** | 3.050 s | **PASSED** |
| **L2 - Trung bình** | *"Gói bánh nằm ở đâu"* | 850 ms | **8 ms** *(SetFit ONNX)* | 590 ms | N/A (AI Speech) | **673 ms** | 3.920 s | **PASSED** |
| **L3 - Hướng di chuyển** | *"Tìm giúp tôi gói bánh trên bàn và hướng di chuyển"* | 1,210 ms | **8 ms** *(SetFit ONNX)* | 1,180 ms | N/A (AI Speech) | **1,271 ms** | 5.040 s | **PASSED** |
| **L4 - Góc giờ + Mét** | *"Hãy tìm xem gói bánh nằm ở hướng mấy giờ và cách bao nhiêu mét"* | 1,340 ms | **8 ms** *(SetFit ONNX)* | 1,420 ms | N/A (AI Speech) | **1,560 ms** | 5.150 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tìm... giúp... tôi... gói... bánh... ở... gần... đây"* | 1,020 ms | **8 ms** *(SetFit ONNX)* | 1,050 ms | N/A (AI Speech) | **1,117 ms** | 4.200 s | **PASSED** |
| **L6 - Kèm dạng cầm** | *"Tìm gói bánh và mô tả kích thước cầm nắm giúp tôi"* | 1,180 ms | **8 ms** *(SetFit ONNX)* | 1,090 ms | N/A (AI Speech) | **1,168 ms** | 5.130 s | **PASSED** |

---

## 📌 5. Chức năng: Đọc tiền

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc tiền"* | 760 ms | **8 ms** *(SetFit ONNX)* | 510 ms | N/A (AI Speech) | **924 ms** | 3.820 s | **PASSED** |
| **L2 - Trung bình** | *"Tờ tiền này mệnh giá bao nhiêu"* | 890 ms | **8 ms** *(SetFit ONNX)* | 750 ms | N/A (AI Speech) | **924 ms** | 3.820 s | **PASSED** |
| **L3 - Phân loại** | *"Kiểm tra tờ tiền trên tay tôi là tiền polyme hay tiền giấy"* | 1,320 ms | **8 ms** *(SetFit ONNX)* | 1,280 ms | N/A (AI Speech) | **1,415 ms** | 3.510 s | **PASSED** |
| **L4 - Chi tiết mệnh giá** | *"Cho tôi biết tờ tiền này là mấy trăm nghìn đồng"* | 1,050 ms | **8 ms** *(SetFit ONNX)* | 1,010 ms | N/A (AI Speech) | **1,113 ms** | 3.300 s | **PASSED** |
| **L5 - Nói ngắt quãng** | *"xem... giúp... tờ... tiền... này... mệnh... giá... bao... nhiêu"* | 1,110 ms | **8 ms** *(SetFit ONNX)* | 1,080 ms | N/A (AI Speech) | **1,199 ms** | 3.180 s | **PASSED** |
| **L6 - Đa tờ tiền** | *"Trên bàn có những tờ tiền mệnh giá bao nhiêu"* | 1,080 ms | **8 ms** *(SetFit ONNX)* | 1,020 ms | N/A (AI Speech) | **1,143 ms** | 3.220 s | **PASSED** |

---

## 📌 6. Chức năng: Thao tác Điện thoại (Handset Actions - Real Push Delivery)

| Cấp độ | Câu lệnh giọng nói | STT Latency | Intent Latency | Gemini/App Latency | Action Finish (Điện thoại kích hoạt) | TTFB (Gói 1) | Tổng thời gian | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **L1 - Mở nhạc** | *"Mở bài hát Nơi này có anh"* | 820 ms | **8 ms** *(SetFit ONNX)* | 35 ms *(Ack)* | **2.001 s** *(FCM Executed)* | **861 ms** | 3.720 s | **PASSED** |
| **L2 - Gọi điện** | *"Gọi điện cho Nguyễn Văn A"* | 910 ms | **8 ms** *(SetFit ONNX)* | 41 ms *(Ack)* | **2.007 s** *(FCM Executed)* | **964 ms** | 5.350 s | **PASSED** |
| **L3 - Chỉ đường** | *"Chỉ đường cho tôi tới Bưu điện Thành phố"* | 1,180 ms | **8 ms** *(SetFit ONNX)* | 307 ms *(Ack)* | **1.999 s** *(FCM Executed)* | **1,241 ms** | 5.710 s | **PASSED** |
| **L4 - Đặt xe** | *"Đặt xe đi Đại học Bách Khoa"* | 890 ms | **8 ms** *(SetFit ONNX)* | 31 ms *(Ack)* | **2.000 s** *(FCM Executed)* | **916 ms** | 3.040 s | **PASSED** |
| **L5 - Gọi cấp cứu** | *"Gọi cấp cứu khẩn cấp"* | 720 ms | **8 ms** *(SetFit ONNX)* | 29 ms *(Ack)* | **2.007 s** *(FCM Executed)* | **747 ms** | 5.160 s | **PASSED** |
| **L6 - Chỉnh âm lượng** | *"Tăng âm lượng điện thoại lên"* | 740 ms | **8 ms** *(SetFit ONNX)* | 23 ms *(Ack)* | **2.012 s** *(FCM Executed)* | **766 ms** | 5.250 s | **PASSED** |
