# Vật cản — cảnh báo theo dự đoán quỹ đạo (thiết kế)

Ngày: 2026-10-21 · Trạng thái: **người dùng đã trả lời câu hỏi mục 9, không yêu cầu sửa (2026-10-21)** · Thay cho mục 5 "Đề xuất sửa logic" trong `docs/2026-10-21-ban-giao-cai-tien-ai.md`.

Ký hiệu: **[ND]** = người dùng đã nói/chốt; **[Claude]** = lựa chọn của Claude, người dùng chưa xét riêng; **[Builder]** = để người làm quyết.

## 1. Vì sao làm

Logic cảnh báo hiện tại (`visioncare-host-demo/live/hazard.py::level_of` + `HazardTracker` + `AntiAnnoy`) xếp mức theo **diện tích hộp**
và "đang tới gần" = diện tích tăng > 15 % so với khung trước, khoá theo (loại vật, vùng trái/giữa/phải). Trên bàn đo C1b
(`evaluations/reports/HAZARD.md`) với detector **hoàn hảo**:

- cảnh báo kịp thời (bíp mức ≥ 2 sớm ≥ 1,5 s trước khi vật vào vùng < 2 m trong lối) chỉ **8,3 % [6,0–10,3]**; muộn 63 %, trượt 28,7 %;
- người đứng yên: bíp ở lead p50 0,38 s (≈ 0,5 m, quá muộn); cột 15 cm và ghế đá trượt 100 %; người đi tới: lead 0,12 s;
- báo oan 0,54 lần/phút — **toàn bộ 50 bíp đến từ một loại**: ô tô đỗ lệch 1,5 m (`edge_static_car`, mỗi kịch bản 1 bíp, 5,13/phút); mọi loại an toàn khác 0.

Detector đã được giải riêng (fine-tune ~90 % recall, `ft_11s_last`), nên nút thắt còn lại là logic.

**Điều người dùng lo nhất [ND]:** vật **xuất hiện đột ngột** và vật có **quỹ đạo lạ** (Việt Nam: xe máy lao ra từ hẻm/sau dãy xe đỗ, xe chạy
lên vỉa hè, ngược chiều, người bước ra sau ô tô [Claude: ví dụ cụ thể]). Camera rung theo bước chân, quay theo đầu, ảnh bị nhoè.

**Hướng [ND]:** ước lượng **khoảng cách và tốc độ** của từng vật để **dự đoán vị trí**, rồi mới quyết cảnh báo. Người dùng đồng ý toàn bộ các
lựa chọn kỹ thuật Claude nêu trong hội thoại (mục 4).

## 2. Mục tiêu, không phải mục tiêu, phản mục tiêu

**Mục tiêu**
1. Tăng tỉ lệ cảnh báo kịp thời trên kịch bản nguy hiểm, đặc biệt nhóm Việt Nam (xuất hiện đột ngột, quỹ đạo lạ).
2. **Không tăng báo oan** so với logic hiện tại **[ND]**: "không báo oan quá nhiều vì giảm UX rất đáng kể". Ràng buộc cứng ở mục 6.
3. Ghi chú **cẩn thận, đầy đủ** đánh đổi báo oan ↔ recall **[ND]**, để người dùng tự quyết có nới ngưỡng hay không (mục 7).

**Không phải mục tiêu**
- IMU **[ND]** (không có ngân sách/phần cứng) — chỉ heuristic trên ảnh/hộp.
- Train lại hoặc đổi detector; cài `ft_11s_last` vào VH là việc **riêng**, sau (mục 6 bàn giao, cần duyệt riêng).
- Vật detector không có lớp: ổ gà, mép vỉa hè, bậc thềm, vật ngang đầu — logic không sửa được thứ detector không thấy.
- Đo trên video thật: chưa có bộ video công khai có nhãn khoảng cách/TTC cho người đi bộ (đã tra 2026-10-20). Báo cáo ghi rõ:
  **kiểm chứng logic trên dữ liệu tổng hợp**.
- Đổi giao thức kính/app.

**Phản mục tiêu (chạy đúng mà vẫn là thất bại)**
- Kịp thời tăng nhưng báo oan vượt ràng buộc mục 6.
- Logic chỉ thắng vì khớp đúng bộ sinh kịch bản do chính Claude viết (cùng camera, cùng chiều cao vật, cùng nhiễu) — xem mục 5.3.
- Thêm trễ tính toán đáng kể trên đường nóng (ngân sách mục 6).

## 3. Ràng buộc

- Đường nóng: `lanes/nav_live.py` — mỗi khung QVGA (320×240, JPEG q15, ~8 fps) → `OnnxYolo.detect` → `HazardTracker.assess` → `AntiAnnoy.step`
  → `protocol.hazard(level, dir, kind)` gửi kính. Mức gửi khi ≥ `HAZARD_MIN_LEVEL` (2).
- **Giao thức giữ nguyên [Claude]:** kính nhận `{level, dir, kind}`; kính/app không phải sửa. Kính phát `hazard_<level>` (âm báo không lời),
  mức ≥ 2 thêm clip `dir_*`, mức 3 thêm `stop_now` ("Dừng lại.") — `docs/FIRMWARE_ENDPOINTS.md` §6–7. Clip `dir_*` là **vị trí**
  ("Bên trái." / "Phía trước." / "Bên phải."), KHÔNG phải hướng tránh. Nên `dir` giữ nghĩa vị trí: phía vật **sẽ đi vào hành lang** (vật đi
  chéo từ trái → `left`); vật đang chắn hành lang hoặc lao thẳng tới → `center`. **Câu "tránh sang trái/phải" KHÔNG có trong dự án này**
  (cần clip mới trên flash kính = đổi firmware) — xem mục 9.
- `kind` của model fine-tune (`pole`, `warning_column`…) nằm ngoài danh sách lớp trong tài liệu firmware; kính không đọc `kind` thành lời
  (chỉ phát âm báo + vị trí) nên không ảnh hưởng, nhưng phải ghi vào tài liệu firmware khi cài model mới.
- Detector có thể là COCO (`_CLASSES`) **hoặc** model fine-tune (`evaluations/train/classes_vh.json`, 20 lớp, có `pole`, `warning_column`,
  `reflective_cone`, `tricycle`…). Logic mới phải chạy với cả hai qua cùng bảng tra theo `kind`.
- Không có ảnh trong C1b (chỉ chuỗi hộp). Phần nào cần ảnh (đo dịch chuyển toàn khung, độ nhoè) phải mô phỏng được trong C1b bằng tín hiệu
  "đo được + nhiễu", và đo chi phí thật riêng ở C1c.
- Máy dùng chung: đo trễ liền nhau, kiểm `uptime`/`nvidia-smi` trước (bài học session trước).
- Làm trên **worktree mới của repo VH**, tách từ `app-giao-tiep` (HEAD hiện tại 110c642) **[Claude]**. Code logic mới (`live/hazard.py`,
  `lanes/nav_live.py`, `config.py`) sửa **trong worktree đó**; chỉ không đụng bản checkout chính `visioncare-host-demo` (người dùng có thay đổi
  chưa commit — đã kiểm 2026-10-21: các thay đổi đó KHÔNG chạm `hazard.py`/`nav_live.py`/`protocol.py`). Code bàn đo ở
  `SeeVia_system/evaluations/bench/`, chạy với `SEEVIA_VH_DIR=<worktree>`.
- **Được đổi chữ ký** `HazardTracker.assess` / `nav_live.process_frame` để truyền thêm ảnh xám thu nhỏ + **mốc thời gian khung** (tham số tuỳ
  chọn, mặc định giữ hành vi cũ) **[Claude]**.
- **Thời gian thật:** production chỉ xử lý khung mới nhất (`_Mailbox` đè khung cũ) nên khoảng cách giữa khung dao động. Bộ lọc dùng **mốc thời gian
  thật** của từng khung, không giả định 8 fps; bàn đo tập test thêm **dao động dt** và **rớt khung** **[Claude]**.
- Bật/tắt bằng cờ config **[Claude]** (`HAZARD_LOGIC=area|predict`, mặc định `area` cho tới khi người dùng duyệt kết quả) — production không đổi
  hành vi khi merge.

## 4. Cách làm (đã thống nhất trong hội thoại)

### 4.1 Track từng vật
- Gán detection giữa các khung bằng IoU (có cổng theo khoảng cách dự đoán) **[ND đồng ý]** — thay khoá (kind, dir) hiện tại.
- **Khung mất vật/nhoè:** track tiếp tục theo dự đoán 2–3 khung (coast) rồi mới xoá **[ND đồng ý]**; không coi là vật biến mất.
- Thuật toán gán (Hungarian/tham lam), số khung coast chính xác: **[Builder]**, chọn bằng lưới dev.

### 4.2 Ước lượng khoảng cách Z (m) và lệch ngang X (m)
Hai nguồn, gộp **[ND đồng ý]**:
1. **Theo chiều cao chuẩn của lớp:** Z = f · H_lớp / h_hộp. Không phụ thuộc góc cúi đầu → chịu rung lên xuống. Sai khi hộp bị cắt ở mép ảnh
   và khi vật thật lệch chuẩn. Bảng H_lớp (m) cho mọi lớp COCO + `classes_vh.json`; giá trị cụ thể **[Builder]**, ghi nguồn/lý do từng dòng.
2. **Theo đáy hộp trên mặt đất:** camera cao ~1,6 m; đáy hộp càng thấp càng gần. Không cần kích thước vật nhưng phụ thuộc góc cúi; góc cúi
   ước lượng dần theo thời gian từ chính các vật đang thấy (không IMU).
- Hộp bị cắt đáy (vật sát) → dùng cạnh trên / độ rộng thay.
- Cách gộp (trọng số theo độ tin, bỏ nguồn khi hộp chạm biên…): **[Builder]**.
- X = (cx − tâm ảnh) · Z / f. Thông số camera (HFOV 66°, cao 1,6 m) lấy từ config, **không** hard-code.

### 4.3 Bù rung / quay đầu không IMU
- Quay đầu làm mọi vật trượt ngang cùng lượng → đo **dịch chuyển toàn khung** trên ảnh thu nhỏ (~1 ms; ví dụ `cv2.phaseCorrelate` trên ảnh xám
  nhỏ — **[Builder]** chọn cách) và trừ khỏi chuyển động ngang của track. Khi có ≥ 2 track, có thể dùng thêm thành phần chung của các track.
- **Độ nhoè** (ví dụ phương sai Laplacian) → hạ độ tin của detection khung đó trong bộ lọc, không xoá track.
- Trong C1b: mô phỏng bằng "dịch chuyển đo được = thật + nhiễu", "độ nhoè đo được" tương quan với khung mất (mục 5.2).

### 4.4 Vận tốc và dự đoán
- Bộ lọc Kalman vận tốc không đổi trên (X, Z) **tương đối với người dùng** **[ND đồng ý]** — không cần tách chuyển động của người dùng.
- Dự đoán tới ~3 s; nếu đường dự đoán cắt **hành lang trước mặt** (|X| < 0,6 m, Z < 2 m — cùng định nghĩa nhãn C1b) thì
  **thời gian tới lúc cắt (TTE)** là thước đo chính:
  - TTE < ~1,5 s → mức 3; TTE < ~3 s → mức 2; vật trong tầm nhưng không cắt hành lang → mức 1 / im lặng.
  - Các ngưỡng là **tham số**, chọn bằng lưới (mục 6), không cố định.
- Có thể dùng độ bất định của bộ lọc (hiệp phương sai) để chỉ báo khi xác suất cắt hành lang đủ cao — **[Builder]**, là một chiều của lưới.
- Vật lớp `vehicle` có thể dùng ngưỡng TTE khác `person`/`static` — **[Builder]**, trong lưới.

### 4.5 Vật mới xuất hiện
- Track mới có bất định lớn → **không đợi lịch sử**: nếu ngay khung đầu Z ước lượng < ~3 m và vật ở trong hành lang thì báo luôn
  **[ND đồng ý]**. Ngưỡng ~3 m là tham số lưới.

### 4.6 Gửi cảnh báo
- `AntiAnnoy` giữ khung cũ (chỉ gửi khi mức tăng, nhắc mỗi 2 s khi ≥ 2, mức 1 tối đa 1 lần/5 s).
- Thêm: mức 3 cần **2/3 khung** gần nhất đồng ý; **hysteresis** — hạ mức phải 2 khung liên tiếp **[Claude]**. Ngoại lệ "vật mới xuất hiện
  rất gần" có được bỏ qua 2/3 hay không: **[Builder]**, trong lưới (đây là đánh đổi trễ ↔ báo oan quan trọng nhất, phải ghi trong báo cáo).
- `dir` gửi kính = phía vật sẽ đi vào/đang chắn hành lang.
- **Thoát nguy hiểm thì dừng [ND, 2026-10-21]:** "sau khi cảnh báo sẽ dừng nếu có dấu hiệu thoát khỏi trạng thái nguy hiểm (tránh được…), vẫn
  cảnh báo thêm một chút rồi dừng". Cài bằng **đuôi nhả** `HAZARD_RELEASE_S` (mặc định predict 0,5 s; area 0 = như cũ):
  - tín hiệu nguy hiểm hết liên tục `down_hold` khung → giữ cảnh báo thêm `release_s` → im hẳn, huỷ nhắc lặp 2 s;
  - nguy hiểm quay lại thì báo lại ngay.
  - Bàn đo: kịch bản `sidestep_avoid` (người dùng né sang bên sau khi được cảnh báo) + chỉ số **kêu thừa sau khi thoát** `tail_after_clear_s`;
    lưới `release_s` ∈ {0,25; 0,5; 1,0}; luật chọn thêm ràng buộc `tail_after_clear_s` p90 ≤ 1,0 s.
- **Sửa sau khi chạy thử (2026-10-21):** ở Z ≲ 3,3 m chân vật ra khỏi khung (camera 1,6 m, góc nhìn dọc ~51°) → đáy hộp bị cắt.
  - Công thức dự phòng cũ (cạnh trên + chiều cao camera) sai vật lý, đã bỏ.
  - Thay bằng **tỉ lệ bề rộng hộp** giữa hai khung của cùng track (bất biến với chiều cao vật).

## 5. Bàn đo (mở rộng C1b)

### 5.1 Giữ nguyên
24 loại hiện có (`evaluations/bench/hazard_scenarios.py`), metric và đối chứng hiện có (`bench/hazard_logic.py`: dương, âm, 2 đường ống phá hoại).
Logic cũ chạy lại trên **đúng** bộ mới làm baseline ghép đôi.

### 5.2 Thêm kịch bản Việt Nam (mỗi loại gắn nhãn nguy hiểm/an toàn bằng hình học như cũ)
Nguy hiểm:
- **Xuất hiện đột ngột:** vật bị che tới khi Z ≈ 3–5 m rồi lộ ra (bước ra sau ô tô; xe máy ra từ hẻm bên cạnh, đi chéo vào lối).
- **Quỹ đạo lạ:** xe máy đổi hướng giữa chừng vào lối; xe máy chạy ngược chiều trên vỉa hè; người đi chéo cắt lối.
- **Vật mảnh / thấp:** cột, cọc, ghế đá (đã có — hiện trượt 100 %).

An toàn (để đo báo oan — quan trọng nhất theo [ND]):
- **Dãy xe máy đỗ** sát mép lối (lệch 0,8–1,5 m), nhiều vật cùng khung.
- **Người đi ngược chiều lướt qua** bên cạnh (lệch 0,7–1,2 m) — ca "suýt chạm" dễ báo oan nhất.
- Người đi **cùng chiều** phía trước, cùng tốc độ (không tới gần).
- Xe đi ngang xa; vật xa đứng yên; ô tô đỗ lề (đã có).

Nhiễu chuyển động (áp lên cả hai nhóm):
- **Nhún bước chân** theo chu kỳ (~2 Hz, biên độ dọc vài % khung), **quay đầu** (trượt ngang chung mọi hộp, có lúc nhanh).
- **Nhoè** gắn với pha rung mạnh: mất **chuỗi** khung liên tiếp (không chỉ ngẫu nhiên 1/3 như `flicker` cũ), hộp nở/lệch.
- Nhiều vật cùng khung (để tracker phải gán đúng).

### 5.3 Chống "khớp bộ sinh của chính mình"
- **Logic dùng giá trị danh nghĩa**; bộ sinh **lấy mẫu giá trị thật** từ phân phối: chiều cao vật (người 1,45–1,85 m, có trẻ em ~1,1 m;
  xe máy có người ngồi), cao camera 1,45–1,75 m, HFOV ±4°, góc cúi lệch vài độ.
- **Seed dev và test tách nhau; phân phối nhiễu ở test rộng hơn dev** (ví dụ biên độ rung, độ dài chuỗi mất khung, sai số chiều cao).
- **Đối chứng âm mới:** xáo thứ tự khung trong kịch bản → logic dự đoán phải mất lợi thế (nếu vẫn thắng = đang dựa vào thứ khác quỹ đạo);
  kịch bản "vật tiến tới rồi dừng hẳn ở 3 m" → không được bíp mức 3.
- Báo cáo kèm **phân tích ca sai** (mỗi loại thua vài ca, giải thích được cơ chế) — theo quy tắc "kết quả phải giải thích được ca sai".

### 5.4 Metric (giữ định nghĩa C1b, thêm)
- Kịp thời (bíp mức ≥ 2 đầu tiên sớm ≥ 1,5 s trước `t_danger`), lead p50/p90, trượt, muộn — theo loại và gộp.
- **Nhóm "xuất hiện đột ngột" đo khác [Claude]:** xe máy lộ ra ở 3–5 m, tốc độ tiếp cận 4+ m/s vào vùng nguy hiểm sau 0,25–0,75 s, nên bíp sớm
  1,5 s là bất khả về hình học kể cả với logic hoàn hảo. Với nhóm này, "kịp thời" = **bíp mức ≥ 2 trước `t_danger` VÀ trong ≤ 2 khung
  (≤ 250 ms) kể từ khung đầu tiên thấy vật**. Báo kèm **trễ từ lúc lộ diện tới bíp** p50/p90. Mỗi kịch bản ghi `t_visible` (khung đầu tiên thấy
  vật) và **lead tối đa có thể** = `t_danger − t_visible`. Kịch bản có lead tối đa < 1 khung bị loại khỏi mẫu số và đếm riêng ("không thể cảnh
  báo"). Tham số bộ sinh nên có cả ca lộ diện sớm (người bước ra ở 4–5 m khi người dùng đi 1,2 m/s → ~1,7 s tới vùng nguy hiểm), để
  ngưỡng 1,5 s vẫn có nghĩa với một phần nhóm này.
- Bỏ phiếu 2/3 và hysteresis ăn trực tiếp vào cửa sổ ≤ 250 ms ở trên, nên chiều "vật mới rất gần được bỏ qua 2/3" (mục 4.6) phải nằm trong lưới.
- **Báo oan:** (a) lần/phút trên kịch bản an toàn; (b) **% kịch bản an toàn có ≥ 1 bíp**. Báo cả hai, vì (a) phụ thuộc độ dài kịch bản.
- Số lần đổi mức gửi đi; `dir` đúng phía (so với phía vật đi vào hành lang theo hình học).
- Trễ: `assess + step` µs/khung p50/p90 (CPU); trễ thuật toán (khung chờ xác nhận × 125 ms); chi phí thật của đo dịch chuyển/nhoè trên khung
  QVGA thật ở C1c (`bench/hazard_latency.py`).
- CI 95 % bootstrap theo kịch bản; Δ ghép đôi với baseline cùng kịch bản (bắt thêm / mất).

## 6. Luật chọn tham số (chốt TRƯỚC khi xem số)

Lưới tham số (ngưỡng TTE mức 2/3, ngưỡng "mới xuất hiện gần", số khung coast, cổng xác suất, có/không bỏ qua 2/3 cho vật mới, cách gộp Z…)
chạy **chỉ trên seed dev**. Chọn cấu hình:

1. **Ràng buộc báo oan [ND]** — trên tập an toàn dev, so với logic cũ trên **cùng** kịch bản:
   - lần/phút **≤ logic cũ** (gộp tập an toàn cũ + Việt Nam), **và**
   - % kịch bản an toàn có ≥ 1 bíp **≤ logic cũ**, **và**
   - không loại an toàn nào có % kịch bản bíp vượt logic cũ quá 5 điểm (chặn đổi báo oan từ loại này sang loại khác).
2. **Ràng buộc trễ:** `assess + step` p90 ≤ 1 ms/khung; đo dịch chuyển + nhoè p90 ≤ 2 ms trên QVGA thật; tổng chuỗi server p90 vẫn trong
   ngân sách C1c (≤ 10 ms với detector hiện tại).
3. **Ràng buộc không tệ đi:** không loại nguy hiểm nào giảm kịp thời > 5 điểm so với logic cũ.
4. Trong các cấu hình thoả 1–3: **tối đa tỉ lệ kịp thời** gộp trên tập nguy hiểm dev (mỗi loại cùng trọng số; nhóm đột ngột dùng định nghĩa
   mục 5.4); hoà (trong 1 điểm) thì chọn báo oan thấp hơn, rồi trễ thuật toán thấp hơn.
5. Không cấu hình nào thoả → **không chọn**; báo đường đánh đổi (mục 7) để người dùng quyết.

Ràng buộc 1 so trên **điểm ước lượng** của dev (dev đủ lớn: ≥ 50 seed mỗi loại). Dung sai "+5 điểm mỗi loại" có nghĩa là với loại mà logic cũ
0 bíp, logic mới được phép tối đa 2 trên 50 kịch bản có bíp — không phải "đúng 0" **[Claude]**.

Cấu hình đã chọn chạy **một lần** trên seed test, báo ghép đôi với logic cũ, có CI. Không chỉnh gì sau khi xem test. **Nếu trên test cấu hình
vi phạm ràng buộc báo oan** (điểm ước lượng): báo cáo ghi **"KHÔNG ĐẠT"** rõ ở đầu, kèm loại vi phạm; KHÔNG chọn lại trên test; người dùng
quyết có làm vòng mới (seed dev mới) hay không **[Claude]**.

## 7. Ghi chú đánh đổi báo oan ↔ recall (yêu cầu [ND])

Báo cáo (`evaluations/reports/HAZARD_PREDICT.md`) phải có, ngoài kết quả cấu hình chọn:
- **Đường Pareto trên dev:** mỗi điểm = (báo oan lần/phút, % kịch bản an toàn bíp, kịp thời) của các cấu hình không bị trội; đánh dấu cấu hình
  chọn và logic cũ. Đọc được: "nới báo oan lên X lần/phút thì được thêm Y điểm kịp thời".
- **Bảng theo loại kịch bản** (nguy hiểm và an toàn) cho logic cũ vs cấu hình chọn, trên test.
- **Ca báo oan còn lại**: loại nào, ở khoảng cách/lệch ngang nào, vì sao logic tưởng sẽ cắt hành lang.
- **Ca trượt/muộn còn lại**: theo loại, nguyên nhân (ước lượng Z sai do hộp cắt biên, chiều cao lệch chuẩn, dự đoán chưa hội tụ khi vật mới…).
- Giới hạn: dữ liệu tổng hợp; vật không có lớp; giả định camera nhìn thẳng; con số không chuyển thẳng sang đường phố thật.

## 8. Đầu ra

1. Worktree + nhánh mới (tên **[Builder]**), code logic mới sau cờ `HAZARD_LOGIC`, unit test (pytest VH hiện tại phải vẫn pass).
2. Bàn đo mở rộng trong `evaluations/bench/` (bộ sinh + chạy lưới + báo cáo), đối chứng âm mới.
3. `evaluations/reports/HAZARD_PREDICT.md` theo mục 5.4, 6, 7.
4. Cập nhật nhật ký `docs/2026-10-20-ra-soat-giao-tiep-vatcan-ocr-benchmark.md` và bàn giao `docs/2026-10-21-ban-giao-cai-tien-ai.md`.
5. **Không** bật `HAZARD_LOGIC=predict` mặc định, không merge vào `app-giao-tiep` khi người dùng chưa xem báo cáo.

## 9. Câu hỏi cho người dùng (sau kiểm tra của reviewer)

- **Hướng tránh bằng lời:** đề xuất ban đầu (mục 5 bàn giao) có "câu nói kèm hướng tránh". Kính chỉ có clip vị trí ("Bên trái." / "Phía
  trước." / "Bên phải.") và "Dừng lại."; muốn "Tránh sang phải" cần clip mới trên flash kính (đổi firmware, tăng `cue_version`). Dự án này
  giữ clip hiện có; hướng tránh tách thành việc sau nếu người dùng muốn.
- **[ND] 2026-10-21: giữ nguyên clip, tách hướng tránh thành việc riêng.**

## 10. Để lại cho người làm
Bảng chiều cao chuẩn; cách gộp hai nguồn Z; thuật toán gán track; cách đo dịch chuyển toàn khung/nhoè; tham số cụ thể của bộ sinh kịch bản
Việt Nam (trong khung mục 5.2–5.3); cấu trúc file code; lưới tham số cụ thể (trong khung mục 6).
