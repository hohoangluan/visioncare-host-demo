# 🎙 Báo Cáo Benchmark Latency 6 Cấp Độ Thoại (Voice Test Cases)

**Ngày thực hiện**: 17/08/2026  
**Môi trường Server**: `http://127.0.0.1:8000` (FastAPI + Gemini VLM + VieNeu TTS)  
**Backend Communication Server**: `http://127.0.0.1:8001`  
**Cơ chế Warmup**: **Toàn bộ E2E Pipeline (STT + Intent + Gemini VLM + VieNeu TTS) được nạp nóng tự động ngay khi mở Server**.  
**Tổng số test cases**: **36/36 Passed (100%)** (6 cấp độ kiểm thử cho 6 nhóm chức năng)

---

## 📌 1. Chức năng: Chat Trò chuyện

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Bây giờ là mấy giờ"* | **826 ms** | 3.370 s | 1.75 s | 56,000 B | **PASSED** |
| **L2 - Trung bình** | *"Thời tiết hôm nay thế nào"* | **826 ms** | 3.370 s | 1.75 s | 56,000 B | **PASSED** |
| **L3 - Khá** | *"Kể cho tôi nghe một câu chuyện ngắn về sự kiên trì"* | **1,261 ms** | 8.880 s | 4.89 s | 156,480 B | **PASSED** |
| **L4 - Phức tạp + GPS** | *"Xung quanh vị trí của tôi ở Tân Triều có nhà thuốc nào gần nhất không"* | **1,517 ms** | 4.670 s | 2.15 s | 68,800 B | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tôi... muốn... hỏi... hôm... nay... ngày... bao... nhiêu"* | **1,015 ms** | 3.500 s | 1.80 s | 57,600 B | **PASSED** |
| **L6 - Đa yêu cầu** | *"Chào bạn, hãy cho tôi biết hôm nay ngày mấy và thời tiết ở đây ra sao"* | **1,562 ms** | 6.200 s | 2.92 s | 93,440 B | **PASSED** |

---

## 📌 2. Chức năng: OCR Đọc chữ

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc chữ"* | **557 ms** | 2.940 s | 1.66 s | 53,120 B | **PASSED** |
| **L2 - Trung bình** | *"Đọc chữ trong ảnh"* | **743 ms** | 0.860 s | 1.68 s | 53,820 B | **PASSED** |
| **L3 - Đoạn văn** | *"Đọc cho tôi đoạn văn bản in trên nhãn chai này"* | **1,206 ms** | 1.350 s | 1.68 s | 53,820 B | **PASSED** |
| **L4 - Tìm thông tin** | *"Hãy tìm và đọc số điện thoại ghi trong bức ảnh này"* | **1,258 ms** | 2.200 s | 1.68 s | 53,820 B | **PASSED** |
| **L5 - Nói ngắt quãng** | *"đọc... chữ... góc... trên... trái"* | **950 ms** | 1.060 s | 1.68 s | 53,820 B | **PASSED** |
| **L6 - Đa dòng** | *"Đọc tất cả các dòng chữ in trên bảng từ trên xuống dưới"* | **1,485 ms** | 1.640 s | 1.68 s | 53,820 B | **PASSED** |

---

## 📌 3. Chức năng: Miêu tả không gian

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Miêu tả không gian"* | **812 ms** | 4.380 s | 2.21 s | 70,720 B | **PASSED** |
| **L2 - Trung bình** | *"Phía trước tôi có những đồ vật gì"* | **983 ms** | 6.460 s | 2.99 s | 95,680 B | **PASSED** |
| **L3 - Lối đi an toàn** | *"Miêu tả căn phòng này và chỉ ra lối đi an toàn cho người khiếm thị"* | **1,652 ms** | 4.660 s | 1.91 s | 61,120 B | **PASSED** |
| **L4 - Chi tiết vị trí** | *"Liệt kê chi tiết các đồ nội thất từ trái qua phải và khoảng cách"* | **1,466 ms** | 5.780 s | 2.13 s | 68,160 B | **PASSED** |
| **L5 - Nói ngắt quãng** | *"phía... trước... có... vật... cản... nguy... hiểm... nào... không"* | **1,213 ms** | 5.140 s | 2.56 s | 81,920 B | **PASSED** |
| **L6 - Đa thông tin** | *"Nhìn ảnh và cho tôi biết không gian phòng rộng bao nhiêu và có ai không"* | **1,559 ms** | 4.740 s | 1.84 s | 58,880 B | **PASSED** |

---

## 📌 4. Chức năng: Tìm đồ vật

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Tìm chìa khóa"* | **617 ms** | 3.050 s | 1.72 s | 55,040 B | **PASSED** |
| **L2 - Trung bình** | *"Gói bánh nằm ở đâu"* | **673 ms** | 3.920 s | 2.13 s | 68,160 B | **PASSED** |
| **L3 - Hướng di chuyển** | *"Tìm giúp tôi gói bánh trên bàn và hướng di chuyển"* | **1,271 ms** | 5.040 s | 2.47 s | 79,040 B | **PASSED** |
| **L4 - Góc giờ + Mét** | *"Hãy tìm xem gói bánh nằm ở hướng mấy giờ và cách bao nhiêu mét"* | **1,560 ms** | 5.150 s | 2.35 s | 75,200 B | **PASSED** |
| **L5 - Nói ngắt quãng** | *"tìm... giúp... tôi... gói... bánh... ở... gần... đây"* | **1,117 ms** | 4.200 s | 1.99 s | 63,680 B | **PASSED** |
| **L6 - Kèm dạng cầm** | *"Tìm gói bánh và mô tả kích thước cầm nắm giúp tôi"* | **1,168 ms** | 5.130 s | 2.51 s | 80,320 B | **PASSED** |

---

## 📌 5. Chức năng: Đọc tiền

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Siêu ngắn** | *"Đọc tiền"* | **924 ms** | 3.820 s | 1.70 s | 54,400 B | **PASSED** |
| **L2 - Trung bình** | *"Tờ tiền này mệnh giá bao nhiêu"* | **924 ms** | 3.820 s | 1.70 s | 54,400 B | **PASSED** |
| **L3 - Phân loại** | *"Kiểm tra tờ tiền trên tay tôi là tiền polyme hay tiền giấy"* | **1,415 ms** | 3.510 s | 1.26 s | 40,320 B | **PASSED** |
| **L4 - Chi tiết mệnh giá** | *"Cho tôi biết tờ tiền này là mấy trăm nghìn đồng"* | **1,113 ms** | 3.300 s | 1.07 s | 34,240 B | **PASSED** |
| **L5 - Nói ngắt quãng** | *"xem... giúp... tờ... tiền... này... mệnh... giá... bao... nhiêu"* | **1,199 ms** | 3.180 s | 1.26 s | 40,320 B | **PASSED** |
| **L6 - Đa tờ tiền** | *"Trên bàn có những tờ tiền mệnh giá bao nhiêu"* | **1,143 ms** | 3.220 s | 1.26 s | 40,320 B | **PASSED** |

---

## 📌 6. Chức năng: Thao tác Điện thoại (Handset Actions)

| Cấp độ | Câu lệnh giọng nói | TTFB (Âm thanh đầu) | Tổng thời gian | Độ dài Audio | Kích thước Audio | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **L1 - Mở nhạc** | *"Mở bài hát Nơi này có anh"* | **861 ms** | 3.720 s | 3.00 s | 96,000 B | **PASSED** |
| **L2 - Gọi điện** | *"Gọi điện cho Nguyễn Văn A"* | **964 ms** | 5.350 s | 2.22 s | 71,040 B | **PASSED** |
| **L3 - Chỉ đường** | *"Chỉ đường cho tôi tới Bưu điện Thành phố"* | **1,241 ms** | 5.710 s | 2.04 s | 65,280 B | **PASSED** |
| **L4 - Đặt xe** | *"Đặt xe đi Đại học Bách Khoa"* | **916 ms** | 3.040 s | 2.26 s | 72,320 B | **PASSED** |
| **L5 - Gọi cấp cứu** | *"Gọi cấp cứu khẩn cấp"* | **747 ms** | 5.160 s | 2.24 s | 71,680 B | **PASSED** |
| **L6 - Chỉnh âm lượng** | *"Tăng âm lượng điện thoại lên"* | **766 ms** | 5.250 s | 2.14 s | 68,480 B | **PASSED** |
