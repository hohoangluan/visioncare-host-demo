# Đề bài Codex: review lại PHẠM VI đợt sửa cuối (chỉ đọc, không sửa file nào ngoài file kết quả)

Repo: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/vh-od (nhánh od-du-doan). Diff cần xem (đã xuất sẵn): /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/plans/sdd-od/review-fix-final.diff (20decde..cedaa8a).
Các phát hiện gốc: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/plans/sdd-od/final-review.md (Important 1, 2; Minor 4, 5, 7). Quyết định của người điều phối cho từng mục: /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/plans/sdd-od/fix-final-brief.md.

Với MỖI mục (Important 1, Important 2, Minor 4, Minor 5, Minor 7): kết luận **ADDRESSED** hoặc **NOT ADDRESSED**, kèm file:dòng và một câu lý do,
đối chiếu với đúng yêu cầu trong fix-final-brief.md (giá trị cụ thể: 0,35·EMA, α 0,1, tối đa 2 khung chặn, 31 mẫu trung vị, kẹp [−0,02; +0,10], khoảng trống > 1,0 s, NaN, log warning).
Sau đó tìm **lỗi MỚI do chính diff này gây ra** (chỉ trong phần diff): Critical / Important / Minor, mỗi lỗi có tình huống cụ thể gây sai.
Đặc biệt kiểm: HAZARD_LOGIC=area có bị đổi hành vi không; trạng thái EMA/deque có reset đúng khi tracker reset không; có đường nào làm Z XA hơn thật hoặc chặn cảnh báo không.
Được chạy: `~/.venvs/seevia/bin/python -m pytest tests/test_hazard_predict.py -q` (chỉ đọc kết quả). Không sửa code, không git.
Ghi kết quả vào /workingspace_aiclub/WorkingSpace/Personal/vannk/SeeVia_system/docs/superpowers/plans/sdd-od/codex-rereview.md (tiếng Việt, ngắn: bảng 5 mục + danh sách lỗi mới). Không hỏi lại.
