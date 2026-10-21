**KHÔNG CHỌN ĐƯỢC** cấu hình nào thoả ràng buộc trên dev (selected=null) — xem đường đánh đổi bên dưới để quyết.

# Vật cản: dự đoán quỹ đạo (HAZARD_LOGIC=predict) — C1b

Sinh bởi `bench/hazard_grid.py` (2026-10-21 19:27). Dev = seed 1000+, test = seed 2000+, kịch bản tổng hợp; luật chọn chốt trước (spec §6).

## 1. Tóm tắt

- Lưới dev: 648 cấu hình, 4050 kịch bản/cấu hình. Baseline dev: kịp thời 3.3 %, báo oan 1.130/phút, 13.3 % kịch bản an toàn có bíp.
- **selected = null**: không cấu hình nào thoả ràng buộc 1–3 (báo oan, trễ, không tệ đi).

## 2. Bảng theo loại (test; baseline vs chọn)

(chưa có test)

## 3. Pareto dev (báo oan/phút, % an toàn có bíp, kịp thời)

| | cấu hình | báo oan/phút | % an toàn bíp | kịp thời |
|---|---|---|---|---|
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 0.695 | 10.7 | 69.6 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.103 | 1.6 | 61.3 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.041 | 0.8 | 32.5 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 2, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+5 cấu hình cùng điểm) | 0.038 | 0.7 | 32.4 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+1 cấu hình cùng điểm) | 0.066 | 1.3 | 54.8 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 0.138 | 2.2 | 65.7 |
|  | `{"tte_l3_s": 1.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 2, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+5 cấu hình cùng điểm) | 0.063 | 1.2 | 54.8 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 0.757 | 10.8 | 73.7 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.103 | 1.7 | 61.7 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 1.502 | 19.5 | 81.3 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 1.484 | 19.2 | 81.1 |
|  | `{"tte_l3_s": 1.5, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 0.141 | 2.2 | 66.0 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.833 | 11.4 | 80.1 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.106 | 1.9 | 64.4 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` (+1 cấu hình cùng điểm) | 0.050 | 0.8 | 34.0 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "v_conf_k": 0.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 0.836 | 11.6 | 80.4 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 2.5, "new_near_m": 4.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.5, "v_conf_k": 0.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.0}` | 1.502 | 17.8 | 80.6 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 1.609 | 19.3 | 83.8 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 0.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+1 cấu hình cùng điểm) | 0.372 | 5.8 | 68.6 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.5, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+1 cấu hình cùng điểm) | 0.141 | 2.4 | 68.0 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 0.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 1.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` (+1 cấu hình cùng điểm) | 0.075 | 1.3 | 55.9 |
|  | `{"tte_l3_s": 2.0, "tte_l2_s": 3.5, "new_near_m": 4.0, "sigma_k": 0.0, "l3_vote": 1, "bypass_vote": true, "coast": 3, "release_s": 0.25, "v_conf_k": 0.0, "yaw_tau_s": 3.0, "q": 1.0, "down_hold": 2, "horizon_s": 3.5}` | 2.260 | 25.2 | 84.0 |

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
