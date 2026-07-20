# Mở rộng intent FIND để bắt câu hỏi đường

## Vấn đề

Người dùng khiếm thị hỏi vị trí đồ vật theo nhiều cách khác nhau, ví dụ đều
nên hiểu là cùng một ý định ("cửa ở đâu, chỉ tôi đường đến"):

- "Cửa ở đâu" — đã khớp `Intent.FIND` (từ khóa "ở đâu").
- "Đi đến cửa như thế nào" — **không khớp luật nào**, rơi vào `Intent.SPACE`
  (mặc định) thay vì `Intent.FIND`. Đây là bug về routing.

## Thay đổi

1. `pipeline/intent.py`: thêm cụm từ khóa vào `_RULES[Intent.FIND]`:
   `"đi đến"`, `"đi tới"`, `"làm sao đến"`, `"làm sao tới"`,
   `"làm thế nào đến"`, `"đường đến"`, `"đường tới"`. Cơ chế so khớp (bỏ dấu
   câu, so theo ranh giới từ) giữ nguyên.

2. `handlers/find_object.py`: cập nhật TODO + câu giả lập để phản ánh spec
   đầu ra khi nối API vision thật sau này. Mỗi lần hỏi trả về **một câu**
   nhưng phải chi tiết: hướng (giờ hoặc trái/phải), khoảng cách ước lượng, và
   vật cản trên đường đi nếu phát hiện được. Kiến trúc vẫn stateless — người
   dùng tự hỏi lại để cập nhật hướng sau khi di chuyển, không có multi-step
   navigation trong một lần trả lời.

3. `tests/test_intent.py`: thêm case parametrize cho các cách hỏi đường mới,
   kỳ vọng `Intent.FIND`.

## Ngoài phạm vi

- Không thêm intent thứ 6.
- Không đổi `schemas.Result` (vẫn 1 field `speech`).
- Không thêm state/session giữa các request.
- Không nối API vision thật (handler vẫn stub, chỉ đổi placeholder text +
  TODO comment để mô tả đúng spec đầu ra tương lai).
