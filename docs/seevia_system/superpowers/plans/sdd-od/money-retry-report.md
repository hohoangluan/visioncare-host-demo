# Báo cáo: đọc tiền v2 (đọc chặt 1 khung + hướng dẫn + đọc lại 1 lần)

Trạng thái: **DONE_WITH_CONCERNS** (mã + test + bàn đo offline xong; chưa thử thật trên kính, xem Concerns).
Worktree `vh-ocr`, nhánh `ocr-tien`. Commit: **`b212d38`** (trên `a907ff9`). Không push, không merge, không đụng worktree khác.

## Đã đổi (theo file)

| File | Thay đổi |
|---|---|
| `config.py` | `MONEY_MIN_PROB` 0,995 -> **0,999**; thêm `MONEY_RETRY` ("1"; "0" = đường cũ), `MONEY_RETRY_PROB=0.999`, `MONEY_RETRY_SETTLE_S=1.0`, `MONEY_RETRY_TIMEOUT_S=3.0`, `MONEY_BLUR_HINT=341.4`. Comment tiếng Việt. |
| `handlers/read_money.py` | `top_labels(choice, text)` (top-2 từ logprobs: nhánh rẽ mạnh nhất tại token bất kỳ ghép với phần đã chọn thành tiền tố của nhãn khác; nhiều nhãn cùng tiền tố thì ưu tiên nhãn lệch x10); `choose_ranked` (cùng nhãn/xác suất thô như `choose`, `top_logprobs=5`); `read_ranked(image, min_prob)` (lỗi -> `(UNSURE, None)`); `hint(top, sharpness)` đúng thứ tự spec §3; `blur_score(jpeg)` (thu về cạnh dài 192 px rồi gọi `image_quality.measure`); hằng `HOLD_STILL/STEP_BACK/COME_CLOSER/RETRY_FAILED`, `STATIC_SPEECH`. `choose()`, `say`, `combine`, `read_choice` giữ nguyên. |
| `pipeline/final_router.py` | `_lane_b` nhánh `money`: nếu `MONEY_RETRY` và `MONEY_MODE=="choice"` -> `_money()` mới, ngược lại đường cũ nguyên văn. `_money`: đọc 1 khung ảnh buffer; chắc / "không có tiền" / lỗi mạng -> `Reply(speech=[câu])`; `UNSURE` -> câu `hint`, có WS thì `Reply(live="ocr", live_token=...)` qua `ctx.prewarmer.session("ocr", {"mode": "money_retry"})`, `single_shot` thì chỉ nói hint. `STATIC_SPEECH` thêm 4 câu mới để audio dựng sẵn (hướng dẫn phát ngay). |
| `lanes/ocr_live.py` | `read_money_frame(jpeg, min_prob)`; `_money_retry()` + nhánh `mode == "money_retry"` đầu `run`: gửi `cam vga 5`, bỏ khung trong SETTLE_S đầu, lấy khung đầu có độ nét >= MONEY_BLUR_HINT (hết TIMEOUT_S: khung nét nhất đã thấy; không có: câu "vẫn chưa đọc chắc"), đọc 1 lần ở `MONEY_RETRY_PROB`, nói, `end`. Phiên đóng / socket đóng thì không nói. |
| `docs/FIRMWARE_ENDPOINTS.md` | Hai chuỗi mẫu mới: "đọc tiền (đọc chắc)" và "đọc tiền — đọc lại". Khung giao thức không đổi. |
| `tests/test_money_retry.py` (mới) | 37 test, xem dưới. |
| ngoài git (untracked, `SeeVia_system/evaluations`) | `bench/money_blur.py` (lệnh tính ngưỡng), mục "3. Đọc tiền v2" trong `reports/MONEY_OCR_CAI_TIEN.md`. |

## Ngưỡng độ nét (dev)

Lệnh (từ `SeeVia_system/evaluations`):
`SEEVIA_VH_DIR=../vh-ocr ~/.venvs/seevia/bin/python -m bench.money_blur`
(đọc `results/money_vnd/20261021-1454_multi_dev.json`, `frames[0]`; ảnh dev `vnd_kaggle` qua `money_vnd.pick_samples(split="dev")`; độ nét = `pipeline.image_quality.measure` trên JPEG q90 cỡ gốc 192x144).

- đọc đúng ở τ 0,999: n=81, trung vị 454,5, p25 **341,40**; nói sai n=2 (trung vị 573,1); từ chối n=82 (trung vị 321,4).
- **MONEY_BLUR_HINT = 341.4** (phân vị 25 % của 81 ảnh đọc đúng). 54,9 % ảnh bị từ chối nằm dưới ngưỡng.
- Số trung vị của tôi (454/321) khác số trong spec (485/363): spec tính trên cách khác (có thể PNG, không qua JPEG q90); tôi dùng đúng hàm production + JPEG như kính gửi.

## Test

- Trước: `540 passed, 2 skipped` (146 s). Sau: **`577 passed, 2 skipped`** (146 s). +37, không sửa test cũ nào.
- `tests/test_money_retry.py` (37): `hint` 16 ca (3 nhóm, thứ tự mờ > x10 > "không rõ", cặp x10 (50k,500k), (10k,100k), (200đ,2k) hai chiều, cặp không x10, 5k<->50k, ngưỡng lấy từ config); `top_labels` 3 ca (nhánh x10 ở chữ số 0, nhánh "không rõ", không có logprobs); mặc định τ 0,999 (0,998 -> từ chối) và các mặc định retry; định tuyến `_lane_b` 8 ca (chắc -> không live; không chắc -> hint + phiên `ocr`/`money_retry`; mờ -> "Giữ yên tay."; single_shot -> chỉ hint; `MONEY_RETRY=0` -> không đụng đường mới, không live; "không có tiền" và lỗi mạng không đọc lại; hint nằm trong `STATIC_SPEECH`); live `money_retry` 7 ca với `LiveSocket` + khung giả (khung trong khoảng chỉnh tay bị bỏ và khung mờ bị bỏ, khung nét đầu tiên được đọc ở `MONEY_RETRY_PROB`; hết hạn lấy khung nét nhất; không khung nào -> "vẫn chưa đọc chắc"; đọc lại vẫn không chắc -> nói câu fail, đúng 1 lượt Gemma, đúng 1 `cam`; `turn_start`/huỷ -> không nói, không `end`; phiên đóng giữa lúc đọc -> không nói); `blur_score`.
- Kiểm đột biến: bỏ luật "bỏ khung trong thời gian chỉnh tay" thì test tương ứng hỏng.

## Bàn đo offline (`python -m bench.money_vnd --path choice --choice-prompt sys --split dev|test`, `SEEVIA_VH_DIR=../vh-ocr`)

| τ 0,999, 1 khung (chưa đọc lại) | Nói sai | Đúng | Từ chối | Bịa |
|---|---|---|---|---|
| dev (165 có tiền) | 1,2 % | 49,1 % | 49,7 % | 0 |
| test (330 có tiền) | **1,8 %** | **49,7 %** | **48,5 %** | 0 |
| test τ 0,995 (đối chiếu) | 3,3 % | 57,3 % | 39,4 % | 0 |

So spec §2 (test 1 khung τ 0,999: sai 2,1 % / đúng 49,4 % / từ chối 48,5 %): **trong nhiễu** (chênh 1 ca sai). Cấu hình đầy đủ (1 khung + đọc lại) vẫn theo số spec: 65,8 % đúng, 2,7 % sai (khung đọc lại = khung kề trong bàn đo; không chạy lại ở đây).
Kết quả: `evaluations/results/money_vnd/20261021-1700_choice_sys_dev.json`, `20261021-1701_choice_sys.json`.

Đo kèm (180 ảnh dev, mã production, server thật):
- Trễ lượt chắc: `final_router._money` p50 187 / p90 200 ms vs đường cũ (tới mảnh text đầu `ocr_live.spoken`) p50 187 / p90 200 ms => **không chậm hơn** (60 ảnh). `choose_ranked` (top_logprobs=5) p50 188 / p90 204 vs `choose` 188 / 208.
- Trong 82 ảnh dev bị từ chối, `hint` ra: "Giữ yên tay." 44, "Lùi ra xa" 21, "Lại gần" 17. 27/82 có top-1/top-2 lệch x10; `top_labels` có top-2 ở cả 82.
- Server không tất định: hai lần `choose` liên tiếp lệch nhãn ở 12/180 ảnh; `choose` vs `choose_ranked` lệch 7-9/180 (không tệ hơn mức nhiễu nền). Câu nói ở τ 0,999 trùng 174/180.
- `blur_score`: ~22 ms (UXGA), ~5 ms (VGA); chỉ chạy ở lượt không chắc và trên khung live.

## Concerns

1. **Chưa thử trên kính.** Số 65,8 % là cận dưới trên video webcam; việc câu hướng dẫn nào đúng và ngưỡng độ nét (chọn ở 192x144) áp lên khung kính thu về 192 px đều chưa kiểm. 54 % lượt không chắc ra "Giữ yên tay." trên dev; trên kính có thể lệch. Cần chạy 10 tờ x 3 tư thế (spec §5.3) trước khi bật mặc định. `MONEY_RETRY=0` là công tắc lùi.
2. **Lệch brief ở tên phiên:** brief ghi `prewarmer.session("money_retry", ...)`, nhưng `app.py` và `device_session` chọn runner theo `session.mode == "ocr"` và nav nhường chỗ cũng theo đó. Dùng `session("ocr", {"mode": "money_retry"})` (chế độ nằm trong params, `run` đọc `params["mode"]` như mọi chế độ OCR) để nav tạm nhường và dựng lại đúng cơ chế OCR live. Nếu `mode` phiên là "money_retry" thì sẽ rơi vào `nav_live.run`.
3. **Thứ tự `end`:** brief nói "nói kết quả; end" (giống OCR live, đã chạy được trên kính); sơ đồ spec §4 vẽ `end` trước audio. Làm theo brief; camera chạy thêm ~vài trăm ms (receiver bỏ khung). Đổi dễ nếu muốn.
4. **"Không có tiền" không đọc lại** (giữ câu cũ "Không thấy tờ tiền nào..."); bàn đo spec xếp nó vào "từ chối" nên con số đọc-lại 53 % của spec gồm cả ca này. Nếu muốn khớp 100 % với bảng spec thì đổi điều kiện trong `_money` (một dòng), nhưng hint "lại gần" cho ảnh trống không hợp.
5. **Lượt chắc không còn stream trong `route()`:** `_money` chờ đọc xong (~190 ms) rồi mới trả `Reply`; trước đây `Reply` trả ngay còn đọc nằm trong `SyncIter`. Đo: thời gian tới câu nói bằng nhau (187/200 ms), nhưng khung `reply` giờ tới kính sau lúc đọc xong thay vì trước. Chưa đo p90 end-to-end qua TTS/WS thật.
6. **Lượt đọc lại tăng số ca nói sai** (spec: 7 -> 9). `MONEY_RETRY_PROB=0.9995` là đòn bẩy nếu muốn chặt hơn (chưa đo).
7. Lỗi mạng ở lượt 1 -> nói câu `UNSURE` cũ, không đọc lại (đọc lại cũng sẽ hỏng).
8. `bench/money_blur.py` và mục báo cáo MONEY_OCR_CAI_TIEN.md nằm ở `SeeVia_system/evaluations` (không có git), không nằm trong commit; bản `vh-ocr/evaluations` là bản cũ, không đổi.
9. Dòng đồng tác giả của commit là `Claude Sonnet 5.5` (đúng model thực hiện, theo hướng dẫn attribution của phiên) thay vì `Claude Opus 5.5` ghi trong brief.

## Sửa sau review (2 phát hiện)

- **A. Đồng hồ đọc lại** (`lanes/ocr_live._money_retry`): `settle_end` và `deadline` giờ tính từ SAU khi `send_text(cam)` xong (gửi chậm không ăn vào thời gian chỉnh tay / hạn đọc). Khung bị bỏ theo lúc NHẬN: `_Mailbox.put` ghi `received_at`, `take` đặt `taken_at` cho khung vừa trả; điều kiện bỏ là `box.taken_at < settle_end` thay cho `time.monotonic()` lúc xử lý. Test mới: `test_money_retry_clocks_start_after_cam_is_sent` (cam gửi 0,6 s), `test_money_retry_settle_uses_receive_time_not_processing_time` (nhận 0,3 s, xử lý 1,0 s, settle 0,6 s).
- **B. Mất nhãn top-1** (`handlers/read_money.top_labels`): thiếu logprobs hoặc không tính được `prefix_prob` thì trả `[(nhãn, p hoặc None)]` thay vì `[]`, nên `hint` thấy "không rõ" và nói "Lùi ra xa". Test mới `test_unsure_without_logprobs_still_says_step_back`. LƯU Ý: assert cũ ở `test_top_labels_without_alternatives_or_logprobs_is_top1_only` (`== []` khi thiếu logprobs) mã hoá chính lỗi này nên phải đổi thành `== [("không rõ", None)]`.
- `config.py`: thêm dòng chú thích MONEY_RETRY=0 chỉ tắt đọc lại; khôi phục hoàn toàn cần thêm MONEY_MIN_PROB=0.995.
