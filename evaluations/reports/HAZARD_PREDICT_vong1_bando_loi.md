**KHÔNG CHỌN ĐƯỢC** cấu hình nào thoả ràng buộc trên dev (selected=null) — xem đường đánh đổi bên dưới để quyết.

# Vật cản: dự đoán quỹ đạo (HAZARD_LOGIC=predict) — C1b

Sinh bởi `bench/hazard_grid.py` (2026-10-21 18:36). Dev = seed 1000+, test = seed 2000+, kịch bản tổng hợp; luật chọn chốt trước (spec §6).

## 1. Tóm tắt

- Lưới dev: 324 cấu hình, 4050 kịch bản/cấu hình. Baseline dev: kịp thời 3.3 %, báo oan 1.130/phút, 13.3 % kịch bản an toàn có bíp.
- **selected = null**: không cấu hình nào thoả ràng buộc 1–3 (báo oan, trễ, không tệ đi).

## 2. Bảng theo loại (test; baseline vs chọn)

(chưa có test)

## 3. Pareto dev (báo oan/phút, % an toàn có bíp, kịp thời)

| | cấu hình | báo oan/phút | % an toàn bíp | kịp thời |
|---|---|---|---|---|
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 2.501 | 23.8 | 56.5 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 2, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 2.476 | 23.8 | 55.7 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 4.285 | 31.6 | 67.4 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 5.562 | 42.3 | 76.0 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 2.491 | 24.1 | 60.1 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 4.344 | 31.8 | 70.5 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 3.678 | 34.8 | 68.2 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 5.646 | 42.3 | 78.0 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 2.570 | 24.5 | 67.2 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 4.244 | 32.5 | 76.0 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 4.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 4.376 | 31.5 | 68.3 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 4.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 6.006 | 39.1 | 76.7 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 3.875 | 35.0 | 72.1 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+1 cấu hình cùng điểm) | 5.768 | 42.7 | 80.5 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 4.0, "sigma_k": 1.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 7.515 | 48.9 | 81.0 |
| BASELINE | `logic cũ` | 1.130 | 13.3 | 3.3 |

Đọc: đi từ điểm này sang điểm kia là 'nới báo oan lên X lần/phút thì được thêm Y điểm kịp thời'.

## 4. Ca báo oan còn lại (test, cấu hình chọn)

(không có / chưa chạy test)

## 5. Ca trượt / muộn còn lại (test, theo nguyên nhân)

(không có / chưa chạy test)

## 6. Đối chứng


## 7. Kêu thừa sau khi thoát nguy hiểm

Người dùng muốn: thoát nguy hiểm thì kêu thêm chút rồi dừng. Đuôi = (khung bíp cuối − t_clear) trên kịch bản có t_clear và có bíp (0 nếu bíp cuối trước t_clear); 'còn bíp' = còn bíp sau t_clear + 1,0 s. Ràng buộc chọn: p90 <= 1 s trên dev.

(chưa có test)

## 8. Trễ

- Đo dịch chuyển/nhoè (<= 2 ms) và tổng chuỗi server (<= 10 ms): `bench/hazard_latency.py` (C1c), không đo ở đây.

## 9. Giới hạn

- Dữ liệu tổng hợp (bộ sinh tự viết); bàn đo kiểm LOGIC với detector lý tưởng, không kiểm khả năng thấy vật (C1a).
- Vật không có lớp trong bảng chiều cao: Z suy từ đáy hộp, kém chính xác hơn.
- Giả định camera nhìn thẳng; góc cúi chỉ học dần, không có IMU.
- Con số không chuyển thẳng sang đường phố thật; cần chạy lại trên clip thật trước khi bật mặc định.
- Đo trễ trong lưới chạy song song 8 tiến trình trên máy dùng chung nên p90 có thể cao hơn thực tế.
