# Đọc tiền — đọc chặt 1 khung, không chắc thì hướng dẫn và đọc lại (thiết kế v2)

Ngày: 2026-10-21 · Trạng thái: **ĐÃ DUYỆT 2026-10-21** (người dùng: "Đồng ý, sau khi hoàn tất nhớ thực hiện kiểm thử và ghi chép lại") · Quyết định (b) trong `docs/2026-10-21-ban-giao-cai-tien-ai.md`.
Số đo gốc: `evaluations/reports/MONEY_OCR_CAI_TIEN.md`. Code đọc theo nhãn đã có trên nhánh `ocr-tien` (`handlers/read_money.py`).

**v1 (3 khung song song) bị người dùng bác:** chờ thêm khung VGA làm **mọi** lượt chậm thêm (ước ≤ 600 ms).
**Hướng người dùng chốt [ND]:**
- không tăng trễ;
- ưu tiên **giảm đọc sai**, chấp nhận từ chối nhiều hơn;
- khi không đọc được thì **đưa yêu cầu cụ thể** ("xa ra", "lại gần", "giữ yên").

## 1. Ý chính

Lượt đọc đầu chỉ dùng **1 khung** (ảnh buffer UXGA có sẵn lúc bấm nút), nên **trễ y như hiện tại**. Ngưỡng xác suất nâng từ 0,995 lên **0,999**, để nói sai ít hơn.
Chỉ lượt **không chắc** mới làm thêm: nói câu hướng dẫn, mở live lấy 1 khung mới, đọc lại **một lần**. Lượt đó vốn đã là lượt "không đọc
được", nên không lượt đọc thành công nào bị chậm đi.

## 2. Số đo (dev chọn, test chạy một lần; dữ liệu `vnd_kaggle`, khung "đọc lại" = khung i+3 của cùng video)

| Cấu hình — **test**, 330 ảnh có tiền | Nói sai | Đúng | Từ chối | Bịa (ảnh không tiền) | Lượt phải đọc lại | Trễ lượt đọc thành công |
|---|---|---|---|---|---|---|
| Hiện tại (nhánh `ocr-tien`): 1 khung, τ 0,995 | 3,6 % (12) | 57,0 % | 39,4 % | 0 | 0 | như cũ |
| 1 khung, τ 0,999, không đọc lại | **2,1 %** (7) | 49,4 % | 48,5 % | 0 | 0 | như cũ |
| **1 khung τ 0,999 + đọc lại 1 lần τ 0,999** | 2,7 % (9) | **65,8 %** | 31,5 % | 0 | 53 % | **như cũ** |
| v1: 3 khung song song τ 0,98 (để so) | 1,8 % | 77,3 % | 20,9 % | 0 | 0 | +~0,5 s mọi lượt |

Dev (165 ảnh có tiền), cấu hình chọn: sai 2,4 %, đúng 65,5 %, từ chối 32,1 %. Chọn trên dev theo luật "sai ≤ 2,5 % (dev), tối đa đúng".
Số test **khớp** dev.

**Đọc đúng giới hạn:**
- Khung đọc lại trong bàn đo **không** phải khung sau khi người dùng làm theo hướng dẫn. Nó chỉ là khung kề của cùng video webcam. Tỉ lệ đúng
  65,8 % vì vậy là **cận dưới**: người làm theo "lùi ra xa / giữ yên" thì khung sau tốt hơn khung kề ngẫu nhiên.
- Đọc lại làm số ca nói sai tăng từ 7 lên 9 (thêm 1 lượt đọc = thêm 1 cơ hội sai). Muốn chặt hơn nữa thì lần đọc lại dùng τ 0,9995: đổi ít đúng
  lấy ít sai (chưa đo, cần chạy dev).
- n nhỏ: 1 ca = 0,3 điểm trên test, 0,6 điểm trên dev. Chạy lại cùng ảnh lệch ±2 ca do server không tất định.

## 3. Chọn câu hướng dẫn (không tốn thêm lượt gọi model)

Nguyên nhân từ chối trên dev (82 ảnh, τ 0,999):

| Nhóm | Số ảnh |
|---|---|
| Đúng mệnh giá nhưng chưa đủ chắc | 36 |
| Model chọn "không rõ" | 24 |
| Ra mệnh giá khác | 18 |
| Lệch ×10 (số 0 bị cắt mép) | 4 |

Ảnh bị từ chối mờ hơn ảnh đọc đúng (độ nét Laplacian trung vị 363 so với 485).

Luật chọn câu, đi từ trên xuống, chỉ dùng tín hiệu đã có sẵn: xác suất top-k của lượt chọn nhãn và độ nét mà `pipeline/image_quality.py` đã tính.
1. Ảnh mờ (Laplacian dưới ngưỡng, chọn trên dev) → **"Giữ yên tay."** (clip `hold_still` có sẵn "Giữ yên.").
2. Hai nhãn đầu lệch ×10 (50.000 ↔ 500.000, 10.000 ↔ 100.000…), hoặc nhãn "không rõ" → **"Lùi ra xa một chút, để cả tờ tiền nằm giữa."** (cắt mép là gốc lỗi chính).
3. Còn lại → **"Đưa tờ tiền lại gần hơn một chút."**
   - Lưu ý: trên ảnh webcam 192×144, nhóm "đúng nhưng chưa đủ chắc" phần nhiều do ảnh nhỏ. Kính thật gửi tới 1600 px, nên có thể "lại gần" ít khi cần hơn.

**Không đo được trên bàn hiện có:** việc chọn câu nào đúng hơn phụ thuộc người dùng làm theo hướng dẫn, mà `vnd_kaggle` là video tĩnh. Phải kiểm bằng
thử thật trên kính (mục 5).

## 4. Luồng giao thức (không đổi firmware)

Firmware: sau `reply_end` của lượt có `reply.live = "ocr"`, kính làm đúng lệnh `cam` / `capture` / `cue` / `end` (`docs/FIRMWARE_ENDPOINTS.md` §6).
Không thêm khung mới, không thêm clip.

```
-- đọc chắc (~49 %): y như hiện tại
kính   turn_start ; 0x01 <JPEG UXGA buffer> ; 0x03 <ADPCM>... ; turn_end
server reply(live:null) ; 0x02... ("Tờ năm mươi nghìn.") ; reply_end

-- không chắc (~50 %): hướng dẫn + đọc lại một lần
server reply(live:"ocr") ; 0x02... ("Lùi ra xa một chút, để cả tờ tiền nằm giữa.") ; reply_end ; {"t":"cam","size":"vga","fps":5,"quality":12}
kính   0x04 <VGA> ...
server (bỏ khung trong 1,0 s đầu cho người dùng chỉnh tay; lấy khung VGA đầu tiên sau đó có độ nét đạt) -> read_choice([khung])
server 0x02... ("Tờ năm mươi nghìn." | "Tôi vẫn chưa đọc chắc được tờ này.") ; {"t":"end"}   (nói rồi mới end — như live OCR)
```

- Hạn chờ live tối đa 3 s. Hết hạn thì nói "Tôi vẫn chưa đọc chắc được tờ này." rồi `end`. `turn_start` mới hoặc socket đóng thì huỷ (giống live OCR).
- Đọc lại **chỉ một lần**, để người khiếm thị không kẹt vòng lặp.
- Không có WS (`ctx.single_shot`): đọc 1 khung τ 0,999. Không chắc thì nói câu hướng dẫn và kết thúc, người dùng tự bấm lại.
- Đang chỉ đường: live tạm thay nav như live OCR; xong thì dựng lại nav.
- Thời gian 1,0 s chờ chỉnh tay là tham số (`MONEY_RETRY_SETTLE_S`), chỉnh khi thử thật.

## 5. Đo trước khi bật

1. **Offline (đã làm, mục 2):** τ chọn trên dev, test một lần.
2. **Ngưỡng độ nét cho luật 1:** chọn trên dev (ảnh bị từ chối vì mờ so với ảnh đọc đúng), không đụng test.
3. **Thử thật trên kính, bắt buộc trước khi bật mặc định:** 10 tờ × 3 tư thế khó (lệch mép, xa, rung tay).
   - Đo % đọc được sau 1 lần hướng dẫn, % nói sai, thời gian của lượt có đọc lại.
   - Lượt đọc thành công ngay phải **không** chậm hơn bản hiện tại (so p90 cùng máy).

## 6. Phạm vi code (khi được duyệt)

- `config.py`:
  - `MONEY_MIN_PROB` 0,995 → **0,999**;
  - `MONEY_RETRY=1` (0 = tắt, hành vi hiện tại);
  - `MONEY_RETRY_PROB=0.999`, `MONEY_RETRY_SETTLE_S=1.0`, `MONEY_RETRY_TIMEOUT_S=3.0`, `MONEY_BLUR_HINT`.
- `handlers/read_money.py`: `choose()` trả thêm top-2 nhãn để chọn câu hướng dẫn; thêm `hint(choice, sharpness) -> str`.
- `pipeline/final_router.py::_lane_b`: `money` không chắc và có WS → `Reply(live="ocr", speech=hint)` + phiên live chế độ `money_retry`.
- `lanes/ocr_live.py::run`: nhánh `money_retry` (bỏ khung lúc chỉnh tay, lấy 1 khung nét, đọc lại, `end`).
- `docs/FIRMWARE_ENDPOINTS.md`: thêm chuỗi mẫu "đọc tiền đọc lại". Khung giao thức không đổi.
- Test: luật `hint` theo 3 nhóm; τ; luồng live đọc lại (khung giả); huỷ khi `turn_start`.

## 7. Không làm
Đổi firmware hoặc clip; 3 khung song song (v1); bộ dò tờ tiền; vòng đọc lại thứ hai.
