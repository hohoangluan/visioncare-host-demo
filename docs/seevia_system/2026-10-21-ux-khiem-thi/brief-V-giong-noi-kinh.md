# Brief V — UX giọng nói trên kính (VH)

Repo: `SeeVia_system/visioncare-host-demo` (VH), nhánh `app-giao-tiep` (mốc b3c2fc0). Làm thẳng trên checkout này, commit mỗi mục một commit
(kết commit bằng dòng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). KHÔNG restart VH đang chạy ở cổng 18888 (controller làm).

Người dùng cuối: người khiếm thị đeo kính, chỉ NGHE (không nhìn màn hình). Mọi phản hồi phải là câu nói ngắn, tự nhiên, làm được ngay;
không bao giờ bảo họ "xem/bấm trên điện thoại". Dùng hằng ngày nên cần tin cậy: thà hỏi lại một câu ngắn còn hơn chạy nhầm lệnh có tác dụng phụ.

Đọc trước: `SeeVia_system/docs/2026-10-21-han-che-chay-full-e2e.md` mục 2.2, 3 (đủ bối cảnh). Code liên quan: `pipeline/final_router.py`
(dòng ~212, ~330, ~354: `ask_confirm`, `is_yes`), `lanes/phone.py` (`_PENDING`, `extract`), `pipeline/intent_classifier.py`, `pipeline/intent_early.py`,
`handlers/chat.py`, `handlers/result_speech.py`, `pipeline/phrases.py`, `pipeline/cues.py`.

## Việc (theo thứ tự)

V1 (lỗi an toàn, ưu tiên nhất). Lời đáp có/không đứng một mình ("Đúng", "Có", "Ừ", "Vâng", "Ok", "Được", "Không", "Thôi") khi KHÔNG có câu hỏi xác
nhận/hỏi lại nào đang chờ cho kính đó → không chạy lệnh nào (hiện đang ra `nav_stop`/`ride_confirm`). Nói: "Mình chưa hỏi gì cả. Bạn cần mình giúp gì?".
Test pytest cho từng từ, có và không có pending.

V2. Bỏ câu chung "Tôi chưa hiểu ý bạn, bạn có thể nói lại được không?" khi lệnh rơi vào `chat` do STT nghe sai:
 a) Khớp gần âm KHÔNG DẤU (bỏ dấu, chuẩn hoá) giữa câu nghe được và danh mục câu lệnh mẫu của từng intent (tự xây từ dữ liệu intent có sẵn,
    vd `tools/gen_intent_dataset.py`/manifest bench). Khớp mạnh: lệnh không tác dụng phụ hoặc lệnh DỪNG/TẮT (space, hazard, ocr, money, find,
    nav_stop, alert_off, music_stop, music_volume…) → chạy luôn; lệnh có tác dụng phụ (gọi, nhắn, đặt/xác nhận xe, dẫn đường, khẩn cấp, phát nhạc)
    → hỏi xác nhận bằng đoán tốt nhất qua cơ chế `ask_confirm`/`is_yes` có sẵn ("Bạn muốn đọc chữ phải không?").
 b) Khớp yếu nhưng có manh mối → đọc lại điều nghe được + tối đa 3 lựa chọn: "Mình nghe là 'tiêu đê bảo'. Bạn muốn đọc chữ, tìm đồ hay tả cảnh?"
 c) Không được cướp câu hỏi thật: câu hỏi kiến thức/chat ("Vịnh Hạ Long thuộc tỉnh nào") phải vẫn đi `chat` như cũ.
 Đo ghép đôi trên `SeeVia_system/stt-bench-cache` (đọc README/manifest trong đó, `demo-web/e2e/stt_ab.py`, `stt_err.py`): trước/sau trên CÙNG bộ clip,
 báo intent cuối đúng (%), số câu sửa đúng / làm sai (câu bất đồng), số câu chat thật bị cướp, và độ trễ thêm (p50/p90, phải < 5 ms).
 Nếu làm sai nhiều hơn sửa đúng thì không giữ — ghi lại và dừng mục này.

V3. Bỏ hẳn trích `emergency_number` ở `lanes/phone.py` (~dòng 154) và mọi chỗ dùng nó: cấp cứu chỉ gọi người thân, không bao giờ gọi 115.

V4. Rà mọi câu nói tới kính trong `handlers/result_speech.py`, `handlers/*.py`, `pipeline/phrases.py`: ngắn (≤ ~15 từ khi được), nói điều đã xảy ra
+ bước tiếp, không câu "xem điện thoại", không thuật ngữ kỹ thuật/mã lỗi. Sửa câu tệ; không đổi logic.

## Ràng buộc
- GPU: chọn GPU trống nhất theo `nvidia-smi` (`CUDA_VISIBLE_DEVICES`), OOM thì đổi GPU, KHÔNG lùi về CPU. Python: `~/.venvs/seevia/bin/python`.
- Không thêm gói mới trừ khi thật cần (cài vào `~/.venvs/seevia`, ghi lại).
- `pytest` toàn bộ VH phải xanh trước mỗi commit.

## Bàn giao
Viết báo cáo vào `SeeVia_system/docs/2026-10-21-ux-khiem-thi/report-V.md` (việc, commit, số đo, còn gì). Trả lời controller ≤ 5 dòng.
