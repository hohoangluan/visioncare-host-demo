Bạn là reviewer code Python. Đọc spec docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md (§1–§6) và diff docs/superpowers/plans/sdd-od/money-v2.diff
(nhánh ocr-tien trong worktree vh-ocr; có thể đọc thêm file trong vh-ocr để lấy ngữ cảnh). KHÔNG sửa file nào, KHÔNG chạy lệnh ghi.
Chỉ báo LỖI ĐÚNG SAI (correctness) có thật, xếp nặng → nhẹ, mỗi lỗi: file:dòng, kịch bản cụ thể gây sai, vì sao. Tập trung:
1) lượt đọc chắc có bị chậm/đổi hành vi so với trước không; 2) luồng live money_retry: huỷ khi turn_start/socket đóng, hết hạn 3 s, không khung nào,
khung trong 1 s đầu bị bỏ, chỉ đọc lại 1 lần, dựng lại nav; 3) luật hint (mờ > ×10/"không rõ" > lại gần), cặp ×10; 4) MONEY_RETRY=0 giữ hành vi cũ;
5) race/async (task không được await, ngoại lệ nuốt mất). Bỏ qua style. Không có lỗi thì ghi "không thấy lỗi đáng kể". Trả lời tiếng Việt, ≤ 400 từ.
