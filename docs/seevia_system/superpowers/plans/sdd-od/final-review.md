# Final review: nhánh od-du-doan (110c642..20decde), HAZARD_LOGIC=predict

Đã đọc: toàn bộ hazard_geom/track/predict/ego_motion, diff hazard.py + nav_live.py + config.py, ledger. Chạy: tests/test_hazard_predict.py (39 pass); fuzz tự viết 3000 khung (ô trống, 30-60 hộp, hộp chạm mọi mép, kind lạ, mốc trùng/lùi/NaN/None/nhảy 5 s): không crash, không NaN trong trạng thái Kalman. Review theo từng lượt (không subagent).

### Strengths
- Mặc định `area` giữ nguyên: `AntiAnnoy.step` với l3_vote=1, down_hold=1, release_s=0 rút về đúng thân hàm cũ (so với 110c642: `streak >= 1` luôn đúng); `make_anti()`/`make_tracker()` chỉ rẽ nhánh khi predict; `HazardTracker.assess` nhận `t, ego` rồi bỏ qua; `protocol.hazard(level, dir, kind)` không đổi.
- Kalman 2x2 từng trục bằng float thuần, giải kín TTE (không lặp): nhanh, không cấp phát lớn. `_dt` xử lý trùng/lùi/NaN/None/nhảy về DT_DEFAULT.
- Trạng thái nằm trong từng phiên (tracker, AntiAnnoy, EgoMeter tạo trong `run`), `process_frame` được await tuần tự, nên không có chia sẻ giữa luồng. `Camera.f_px` cached_property trên dataclass frozen chạy đúng.
- Xử lý đáy bị cắt (Z theo tỉ lệ bề rộng, neo Z thô, chặn trên theo mặt đất thấy được ×1,15) và mép bên (cạnh trong) đúng hướng an toàn; có test.
- Ledger ghi rõ các phán quyết và lý do; lỗi vật lý của plan (công thức cạnh trên) được tìm ra và sửa bằng đo.

### Issues

#### Critical
Không có.

#### Important
1. **Cổng nhoè dùng ngưỡng tuyệt đối làm tắt tạo track mới (hướng nguy hiểm: chặn cảnh báo)**
   - live/hazard_predict.py:289-290 + live/ego_motion.py:357 (`_BLUR_MIN = 30`).
   - Phương sai Laplacian toàn khung < 30 cũng xảy ra ở cảnh ít vân (tường trơn, hành lang, trời tối/sương, JPEG QVGA nén mạnh), không chỉ khi quay đầu. Khi đó `allow_new=False` kéo dài: vật mới không bao giờ thành track, nên cả luật new_near lẫn TTE đều không chạy cho vật đó, mà không có tín hiệu lỗi nào.
   - Sửa: giới hạn số khung liên tiếp bị chặn (ví dụ sau 2-3 khung vẫn cho tạo track), hoặc so với EMA nền của chính phiên (blur < 0,3 x EMA). Cần thêm một test "cảnh ít vân liên tục vẫn báo vật mới". Nếu C1c/bàn đo chưa có cảnh ít vân thì chưa chứng minh được ngưỡng 30; hiệu chỉnh trên khung kính thật.
2. **Góc cúi (pitch) tự học có thể đẩy mọi Z ra XA tới ~20% ở 3 m**
   - live/hazard_predict.py:272-277, hazard_geom.py:pitch_sample. Mẫu lấy từ chiều cao điển hình của MỌI hộp `person` (kể cả trẻ em, người ngồi, hộp bị che chân), EMA 0,1, kẹp ±0,1 rad, không phân rã khi không có mẫu. Người thấp hơn 1,65 m cho mẫu tan(p) âm, nguồn ground sau đó cho Z xa hơn thật (f·tan0,1 ≈ 24 px, tại 3 m d≈126 px nên ≈ +20%). Người cao hơn cho lệch gần hơn (an toàn), vì vậy sai lệch có hướng không đối xứng về phía nguy hiểm.
   - Sửa: dùng trung vị trên nhiều hộp / chỉ lấy mẫu khi nhiều hộp đồng thuận, kẹp hẹp hơn (±0,05), phân rã về 0 khi lâu không có mẫu; hoặc không học pitch mà lấy từ cấu hình. Ít nhất đưa lệch pitch vào bàn đo (đối chứng pitch âm).

#### Minor
3. live/hazard_predict.py:243-260 `_tte`: khi vz > 0 và z < danger (vật đang rời ra, đi vào hành lang theo chiều ngang) không có cận trên thời gian để Z còn < danger; báo thừa (an toàn, chỉ ồn). Thêm `hi = min(hi, (danger - z)/vz)` khi vz > 0.
4. live/hazard_track.py:123 + hazard_predict.py: track chỉ hết hạn theo số khung, không theo thời gian. Sau một khoảng ngừng khung > 1 s (DT_DEFAULT áp), track cũ vẫn được so khớp IoU với vật khác, vận tốc ước lượng sai. Thêm hết hạn theo mốc thời gian (ví dụ bỏ track nếu t - last_t > 1 s) hoặc `reset()` khi khoảng trống > DT_MAX.
5. Không có isfinite guard cho hộp đầu vào: một hộp NaN (nếu detector lỗi) làm trạng thái track thành NaN, mọi so sánh sai, track đó im lặng vĩnh viễn trong khi vẫn được khớp. Detector ONNX hiện không sinh NaN, nên chỉ phòng thủ: lọc `math.isfinite` các toạ độ trong `estimate`/`update`.
6. nav_live.py:run: `t = time.monotonic()` lấy lúc rút khung khỏi mailbox, không phải lúc nhận (khung có thể chờ hết một lượt xử lý). Jitter đo dt khoảng bằng độ trễ xử lý; chấp nhận được, ghi chú.
7. config.py: `HAZARD_LOGIC` sai chính tả ("Predict", "prediction") im lặng chạy `area`; `HAZARD_NEW_BYPASS_VOTE` là chuỗi "1". Nên cảnh báo log khi giá trị lạ; `HAZARD_CLASSES_JSON` thiếu file làm hỏng import `live.hazard` (fail-fast, chấp nhận nhưng nên có thông báo rõ).
8. Hiệu năng: fuzz với 30 và 60 hộp ngẫu nhiên (không thực tế cho YOLO 320 + NMS) cho assess p90 ≈ 1,4 và 1,9 ms; 1-3 hộp ≈ 0,7-0,8 ms p90 trên máy dùng chung (có tải nền). Ngân sách 1 ms đạt ở tải thực tế nhưng còn sát; Ruling 21 đã chuyển kiểm cứng sang C1c, giữ nguyên. Tạo ndarray `tb`/`db` mỗi khung nên chỉ làm khi cả hai không rỗng (đã làm).
9. Thiên lệch kích thước lớp là cố hữu: trẻ em / người ngồi cho Z theo chiều cao xa hơn thật (tới ~+37% cho trẻ 1,2 m) khi ground không hợp lệ (đáy che). Ghi vào tài liệu giới hạn, không phải lỗi mã.

### Deferred minors trong ledger: phân loại
- `Camera.f_px` cached_property + np.nonzero trong ghép IoU: ĐÃ làm trong mã hiện tại, đóng.
- `test_debug_frames` hỏng khi 2 pytest chạy chồng; `test_v2_messages` lỗi event-loop một lần khi chạy full: không do nhánh này, không chặn merge (mở ticket riêng nếu lặp lại trong CI).
- Money v2 (Co-Authored-By sai tên model, "không có tiền"/lỗi mạng không đọc lại): ngoài nhánh vh-od này, không chặn merge.
- Phải sửa trước merge: không có mục deferred nào; chỉ các mục Important 1-2 ở trên (hoặc ghi rõ chấp nhận rủi ro bằng Ruling).

### Declined to judge
- Độ đúng của các hằng số hiệu chỉnh (HAZARD_TTE_*, danger_z/lane_half, _BLUR_MIN, _CLIP_Z_MARGIN, bảng chiều cao/bề rộng lớp): thuộc kết quả bàn đo C1b/C1c, tôi không có số chốt để phán.
- Kết quả bench evaluations/bench (ngoài git) và mọi số báo oan/kịp thời: không nằm trong diff.
- Nội dung money v2 / ocr-tien: không thuộc nhánh này.
- Thiết bị kính thật (FOV 66°, cao 1,6 m, QVGA thật): chỉ kiểm theo cấu hình danh nghĩa.

### Recommendations
- Làm rõ bằng test hai ca: cảnh ít vân liên tục + vật tiến vào; pitch học từ trẻ em/người ngồi.
- Giữ `urgent` + phiếu l3 như hiện tại; thêm log (debug) cho lý do mức (new_near / in-zone / tte) để chẩn đoán hiện trường.

### Assessment
**Ready to merge?** With fixes

**Reasoning:** Mặc định `area` giữ nguyên và predict ổn định (không crash/NaN, an toàn luồng, trong ngân sách ở tải thực tế). Hai rủi ro làm cảnh báo bị muộn/mất (cổng nhoè tuyệt đối, pitch tự học lệch về phía xa) nên xử lý hoặc chấp nhận bằng Ruling trước khi bật predict ở sản phẩm; chưa cần chặn việc gộp nếu cờ giữ mặc định area.
