# D7 — ngưỡng so khớp tên danh bạ

Ngày: 2026-08-22

Trạng thái: **CHƯA ĐO trên danh bạ thật**.

## Cấu hình tạm để thi công

| Tham số | Giá trị đề xuất | Trạng thái |
|---|---:|---|
| Xác nhận một ứng viên | `score >= 88` | provisional |
| Biên hơn ứng viên nhì | `margin >= 8` | provisional |
| Cho người dùng chọn | `score >= 70` | provisional |
| Số tên đọc tối đa | `3` | ràng buộc UX, không phải ngưỡng chất lượng |
| Trọng số tầng `phon` | `0.95` | provisional |

Các unit test tổng hợp trong `tests/test_contact_match.py` xác nhận chính sách
hoạt động đúng về mặt cơ học (sai dấu, thừa họ, đảo token, các cặp âm ASR và
ngưỡng từ chối). Chúng **không** thay thế phép đo trên danh bạ thật.

## Phép đo còn thiếu

- Danh bạ thật ít nhất 200 contact.
- Đọc 20 tên thường gọi, gồm tên đầy đủ, tên đặt lạ và tên trùng.
- Ghi cho từng lượt: transcript STT, top-3, điểm `norm`, điểm `phon`, điểm cuối,
  margin, quyết định mong muốn và quyết định thực tế.
- Chỉ chốt lại 88/70/8 sau khi có bảng false accept/false reject từ phép đo này.

Không ghi số đo giả hoặc suy từ bộ ca tổng hợp vào đây.
