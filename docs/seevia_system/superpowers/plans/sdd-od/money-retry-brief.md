# Brief: đọc tiền v2 — đọc chặt 1 khung + hướng dẫn + đọc lại 1 lần

Spec (nguồn yêu cầu, đọc kỹ §1–§6): SeeVia_system/docs/superpowers/specs/2026-10-21-doc-tien-3-khung-design.md

Worktree: SeeVia_system/vh-ocr, nhánh `ocr-tien` (đã có `read_money.choose/combine/read_choice`, commit a907ff9). Python ~/.venvs/seevia/bin/python.
Không đụng visioncare-host-demo / vh-od / vh-vqa / vh-chot. Không push, không merge.

## Làm (TDD, mỗi bước: test hỏng → code → pass → `pytest -q` toàn bộ)
1. `config.py`: `MONEY_MIN_PROB` mặc định 0.999; thêm `MONEY_RETRY` ("1"; "0" = hành vi cũ: không đọc lại), `MONEY_RETRY_PROB=0.999`,
   `MONEY_RETRY_SETTLE_S=1.0`, `MONEY_RETRY_TIMEOUT_S=3.0`, `MONEY_BLUR_HINT` (giá trị ở bước 5). Comment tiếng Việt như khối MONEY hiện có.
2. `handlers/read_money.py`:
   - `choose()` giữ chữ ký trả về hiện có nhưng có thêm cách lấy **top-2 nhãn + xác suất** (từ logprobs đã có; nếu chỉ có top-1 thì top-2 = None).
   - `hint(top: list[tuple[str, float]], sharpness: float | None) -> str` theo luật spec §3, đúng thứ tự:
     (1) sharpness < MONEY_BLUR_HINT → "Giữ yên tay."
     (2) top-1 là "không rõ", HOẶC top-1/top-2 là hai mệnh giá lệch đúng ×10 → "Lùi ra xa một chút, để cả tờ tiền nằm giữa."
     (3) còn lại → "Đưa tờ tiền lại gần hơn một chút."
   - Câu khi đọc lại vẫn không chắc: "Tôi vẫn chưa đọc chắc được tờ này."
3. `pipeline/final_router.py::_lane_b` nhánh `money`: đọc 1 khung (ảnh buffer) như hiện tại. Chắc → như cũ.
   Không chắc + `MONEY_RETRY` + có WS (không `ctx.single_shot`) → trả `Reply(speech=<hint>, live="ocr", live_token=…)` với phiên live chế độ `money_retry`
   (dùng `ctx.prewarmer.session("money_retry", {...})` giống cách OCR mở phiên — đọc code OCR live để theo đúng mẫu).
   Không chắc + `single_shot` → nói hint, không live.
4. `lanes/ocr_live.py::run`: nhánh `mode == "money_retry"`: gửi `cam vga 5`; bỏ mọi khung trong MONEY_RETRY_SETTLE_S đầu; lấy khung đầu tiên
   sau đó có độ nét ≥ MONEY_BLUR_HINT (hết MONEY_RETRY_TIMEOUT_S thì lấy khung nét nhất đã thấy, không có khung nào thì nói câu "vẫn chưa đọc chắc");
   đọc bằng `read_money` 1 khung với ngưỡng MONEY_RETRY_PROB; nói kết quả; `end`. `turn_start` mới / socket đóng → huỷ như live OCR. Chỉ đọc lại 1 lần.
   Đang nav thì theo đúng cơ chế live OCR tạm thay nav rồi dựng lại.
5. Ngưỡng `MONEY_BLUR_HINT` chọn trên **dev** (không dùng test): độ nét tính đúng bằng hàm production `pipeline/image_quality.py` (cùng cỡ ảnh),
   trên ảnh dev `vnd_kaggle` (xem `SeeVia_system/evaluations/bench/money_vnd.py` cách lấy split dev) — ngưỡng = phân vị 25 % độ nét của các ảnh dev
   đọc ĐÚNG ở τ 0,999 trong `SeeVia_system/evaluations/results/money_vnd/20261021-1454_multi_dev.json` (khung đầu `frames[0]`). Ghi lệnh + số vào report.
6. `docs/FIRMWARE_ENDPOINTS.md`: thêm chuỗi mẫu "đọc tiền — đọc lại" theo spec §4 (không đổi khung giao thức).

## Test bắt buộc (tests/test_read_money.py và/hoặc file mới)
- `hint` ra đúng câu cho 3 nhóm + thứ tự ưu tiên (mờ thắng ×10); cặp ×10: (50 nghìn, 500 nghìn), (10 nghìn, 100 nghìn), (200 đồng, 2 nghìn).
- τ mặc định 0,999: xác suất 0,998 → từ chối.
- `MONEY_RETRY=0` → không mở live (hành vi như trước khi đổi, ngoài τ).
- Luồng live `money_retry` với socket/khung giả: khung trong 1 s đầu bị bỏ; khung nét sau đó được đọc; `end` được gửi; `turn_start` huỷ.
- Không test cũ nào bị sửa để cho qua.

## Sau khi code xong
- Chạy bàn đo offline (từ SeeVia_system/evaluations, SEEVIA_VH_DIR=../vh-ocr): `python -m bench.money_vnd --path choice --choice-prompt sys --split dev`
  rồi một lần `--split test`; xác nhận đường production 1 khung τ 0,999 ra số trong nhiễu của spec §2 (test: sai ~2,1 %, đúng ~49 %).
- Commit (tiếng Việt): `git -c user.name=LuanLuKim -c user.email=kimluanlu95@gmail.com commit`, dòng cuối `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Thêm mục "Đọc tiền v2" vào `SeeVia_system/evaluations/reports/MONEY_OCR_CAI_TIEN.md`: luật, ngưỡng độ nét (dev), bảng spec §2, số bàn đo vừa chạy, giới hạn (khung đọc lại = khung kề, cần thử thật trên kính 10 tờ × 3 tư thế).
- Không dispatch subagent.
