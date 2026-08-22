# AGENT_RULES — luật bắt buộc cho mọi subagent

## A. Luật gốc (RUNBOOK mục 0)

1. Đọc `docs/tasks/CONTRACTS.md` TRƯỚC. Đó là nguồn sự thật. Task file mô tả
   việc phải làm; CONTRACTS mô tả thứ hai bên phải đồng ý.
2. Số dòng trong task file có thể đã trôi. VERIFY bằng grep/read trước khi sửa.
   Không sửa mù theo số dòng.
3. TDD: viết test đỏ trước, rồi mới viết code. Test nào đã liệt kê trong mục 4
   của task file thì phải có đủ, đúng tên.
4. KHÔNG báo xong khi chưa chạy lệnh trong mục DoD và nhìn thấy output xanh.
   Dán output THẬT vào báo cáo, không tóm tắt.
5. Task nào phụ thuộc repo khác mà repo đó chưa xong -> đánh dấu PARTIAL, ghi RÕ
   ca nào còn hỏng. Dùng `@pytest.mark.xfail(reason="Txx: ...")`.
   KHÔNG xoá test, KHÔNG báo xanh giả.
6. Gặp mục "Câu hỏi phải chốt" chưa có đáp án -> làm hết phần KHÔNG phụ thuộc
   câu đó, rồi HỎI trong báo cáo. Đừng tự chốt thay người dùng những câu 🔴.
7. Không mở rộng phạm vi. `handlers/find_object.py` và `handlers/read_money.py`
   KHÔNG ĐỤNG (spec mục 7). `handlers/describe_hazard.py` chỉ được thêm comment.
8. Ba nguyên tắc xuyên suốt ở CONTRACTS mục 0 thắng mọi tối ưu. Đặc biệt:
   `emergency_call` không đi qua bất kỳ bước xác minh nào.
9. Có bảng số thì mới được chốt. Ngưỡng nào chưa đo thì ghi "chưa đo", đừng copy
   số cũ của cấu hình khác.
10. Báo cáo cuối theo mẫu ở mục C dưới đây.

## B. Luật chống xung đột — vì bạn đang chạy song song với agent khác

B1. KHÔNG chạy bất kỳ lệnh git nào ghi vào repo: `add` `commit` `checkout`
    `reset` `stash` `merge` `rebase` `clean`. Chỉ đọc: `git status`, `git diff`,
    `git log`, `git grep` được phép. Phiên điều phối commit, không phải bạn.

B2. KHÔNG sửa bốn file này — chúng thuộc phiên điều phối:
      docs/tasks/CONTRACTS.md
      docs/tasks/00-INDEX.md
      docs/tasks/RUNBOOK.md
      docs/tasks/PROGRESS.md
    Cần đổi hợp đồng -> ghi đề nghị vào `docs/tasks/contract-deltas/<Txx>.md`
    theo mẫu ở mục D. Phiên điều phối sẽ gộp.

B3. Prompt của bạn có bảng "FILE BẠN ĐƯỢC SỬA". Ngoài bảng đó thì KHÔNG SỬA,
    kể cả khi task file bảo sửa. Gặp trường hợp đó -> ghi vào mục "Lệch với task
    file" của báo cáo rồi làm tiếp phần còn lại.

B4. Sửa `config.py`: chỉ thay thế đúng dòng marker `# === <Txx> ===` của bạn.
    Không thêm vào cuối file, không sửa marker của task khác.

B5. Chạy test bằng `.venv/Scripts/python.exe -m pytest <đường dẫn cụ thể> -q`.
    KHÔNG chạy `pytest tests` toàn bộ — agent khác đang sửa file khác, test của
    họ đỏ dở là bình thường và không phải việc của bạn.

## C. Mẫu báo cáo — ghi vào docs/tasks/reports/<Txx>.md

    ## Txx — <tên task>

    Trạng thái: DONE | PARTIAL | BLOCKED

    ### Đã làm
    - <mã spec>: <file:line đã sửa>

    ### Chưa làm & vì sao
    - <mã spec>: chặn bởi <Txx / câu hỏi mở số N ở CONTRACTS mục 7>

    ### Test
    ```
    $ .venv/Scripts/python.exe -m pytest <lệnh trong DoD> -q
    <dán output THẬT, không tóm tắt>
    ```
    - Thêm mới: N test
    - xfail: N test, lý do: ...
    - Sửa test cũ: <file>, vì sao

    ### Số đo (nếu có)
    - Ghi vào measurements/<file>.md

    ### Lệch với task file
    - <chỗ nào task file mô tả sai thực tế code>

    ### DoD
    - [x] ... / [ ] ... (ô nào chưa tick thì giải thích)

    ### Cần người dùng chốt
    - <câu hỏi 🔴 gặp phải>

Mục "Lệch với task file" là mục dễ bị bỏ qua nhất và có giá trị cao nhất — task
file viết từ spec, mà spec có chỗ đã trôi so với code.

## D. Mẫu contract-delta — ghi vào docs/tasks/contract-deltas/<Txx>.md

    ## Đề nghị sửa CONTRACTS.md — từ Txx

    ### Mục <số mục ở CONTRACTS>
    Hiện tại:
    ```
    <trích nguyên văn>
    ```
    Đề nghị:
    ```
    <bản mới>
    ```
    Vì sao: <một câu>
