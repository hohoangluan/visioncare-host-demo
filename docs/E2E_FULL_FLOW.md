# E2E trọn luồng: kính giả lập -> VH -> app server -> điện thoại giả lập

`tools/e2e_full.py` dựng cả chuỗi thật và chạy các kịch bản bằng giọng nói tổng hợp (VieNeu -> ADPCM,
phát đúng nhịp thời gian thực như người giữ nút) qua `WS /v2/session`:

```
kính giả (WS /v2/session) -> VH voice server (:18893) -> app server AB (:18001, DELIVERY_TRANSPORT=webhook)
      -> phone_sim (:18002, báo kết quả đúng khuôn app Android) -> AB -> callback VH -> VH đọc kết quả
```

Không đụng app server `:8001` của người dùng. Mọi tiến trình và postgres test do công cụ dựng đều bị tắt khi xong.

## Chạy

```bash
cd VH
# VH cần GPU (CUDA_VISIBLE_DEVICES chọn GPU cho TTS của công cụ; --gpu chọn GPU cho server VH). Chọn GPU còn trống bằng nvidia-smi.
CUDA_VISIBLE_DEVICES=2 ~/.venvs/seevia/bin/python tools/e2e_full.py --gpu 3
CUDA_VISIBLE_DEVICES=2 ~/.venvs/seevia/bin/python tools/e2e_full.py --gpu 3 --only call_mom call_cancel nav
```

Cần: docker (postgres `compose.test.yaml` của AB, cổng 55435, project `vh-e2e-full`), `AB/.venv` (`uv sync --frozen`),
`SeeVia_system/.env` (token công khai, callback, khoá mã hoá; chỉ đọc, không in), `.env` của VH (Clef/Gemma).
Cờ chính: `--only`, `--keep` (giữ stack để soi log trong `results/e2e_full/`), `--scenario` (JSON cho phone_sim),
`--street` (ảnh đường phố cho hazard; mặc định `$E2E_STREET_IMAGE`), `--json-out`, `--app-url` + `--no-phone-sim`
(điện thoại thật, xem `docs/E2E_REAL_PHONE.md`).

VH được khởi động với `VISIONCARE_DEVICE_ID` KHÁC id kính (`e2e-wrong-default`): nếu lệnh làn D nào mất `device_ctx`
(lỗi Task 16 đã sửa ở `pending_action`) thì AB trả `GLASSES_DEVICE_NOT_LINKED` và kịch bản hỏng ngay. Duy nhất một dòng
`ERROR ... GLASSES_DEVICE_NOT_LINKED` trong `results/e2e_full/vh.log` là phép dò vị trí lúc khởi động, đúng như thiết kế.

## Cách đo

| Cột | Mốc |
|---|---|
| nhả nút -> tiếng đầu | từ lúc gửi `turn_end` tới khối `0x02` đầu tiên (lượt đầu của kịch bản, tức câu đọc lại / trả lời) |
| nhả nút -> lệnh ĐT | từ `turn_end` của lượt kích hoạt (lượt "Đúng." nếu server hỏi lại) tới dòng `command` trong `phone_sim_log.jsonl` (cùng máy, cùng đồng hồ). Gồm cả thời gian đọc lại + cửa sổ huỷ làn D. |
| lệnh -> kết quả đọc | từ lúc ĐT `report` tới khối audio đầu tiên sau đó. `-` = người dùng KHÔNG nghe được gì. |
| hỏi lại | server có hỏi "...phải không?" (Gemma dưới `ACTION_MIN_CONFIDENCE` 0,999); kịch bản trả lời "Đúng." rồi đi tiếp |

Kịch bản huỷ: huỷ ngay sau `reply_end` (lệnh chờ còn trong cửa sổ đọc lại), rồi chờ 7 s và đòi phone_sim KHÔNG nhận lệnh nào:
bằng khung `cancel`, bằng lượt mới (`turn_start`), và bằng cách đóng socket. Kịch bản chat đòi 0 lệnh. `alert` kiểm live nav
sống qua lượt chat bằng cách reset chống-làm-phiền (khung trống) rồi cho đường phố lại và đòi hazard mới. OCR được kiểm cả đọc
thẳng ảnh buffer lẫn live qua session (`cam` -> khung 0x04 -> `capture` UXGA -> audio -> `end`).

## Kết quả đợt sửa cuối (2026-10-19, GPU 6, nhánh wt-task-15B = voice-v2-hardening 5f8bb02 + commit "đợt sửa cuối plan 1")

Chỉ chạy lại các kịch bản từng FAIL + `call_cancel` (1 lượt mỗi kịch bản), theo brief đợt sửa cuối:
`--only call_mom call_nam ride music nav emergency call_cancel`.

| Kịch bản | Kết quả | hỏi lại | nhả nút -> tiếng đầu (ms) | nhả nút -> lệnh ĐT (ms) | lệnh -> kết quả đọc (ms) | sửa ở commit | ghi chú |
|---|---|---|---|---|---|---|---|
| call_mom | PASS | không | 523 | 2524 | 858 | đợt sửa cuối (B1, C1) | `contact_call` name=mẹ, kết quả đọc qua `result-<id>` |
| call_nam | PASS | không | 504 | 2415 | 483 | đợt sửa cuối (B1) | ĐT báo `MULTIPLE_CONTACTS_FOUND`, người dùng nghe được |
| ride (đặt xe -> xác nhận) | PASS | không | 550 | 3018 | 842 | đợt sửa cuối (B4) | `ride_quote` gửi ngay; "xác nhận" gửi `ride_confirm {quote_id, confirm:true}` |
| music (phát -> tăng âm lượng lúc đang phát -> bấm nút dừng) | PASS | không | 560 | 3076 | 992 | đợt sửa cuối (B1, B3) | volume có lời = `music_volume`; bấm nút không lời = `music_stop` |
| nav (dẫn đường -> hazard -> chat giữa chừng -> bấm nút dừng) | PASS | không | 555 | 3355 | 873 | đợt sửa cuối (B2, B3, I4) | chat không tắt nav; bấm nút gửi `navigation_stop` + khung `end` |
| emergency | PASS | không | 502 | 3712 | 823 | đợt sửa cuối (B1) | `emergency_call` đúng, kết quả đọc |
| call_cancel (khung cancel) | PASS | không | 526 | - | - | đợt sửa cuối (C1) | ĐT không nhận lệnh nào |

`nhả nút -> lệnh ĐT` tăng ~0,3 s so với trước vì cửa sổ huỷ làn D giờ đếm từ lúc khối audio đọc lại đầu tiên tới kính (C1/I1),
không phải từ lúc `route()` xong. `vh.log`: 0 traceback, 0 `aclose`, 0 dòng httpx/SerpAPI (I3).

Ở lần chạy đầu (trước khi sửa, 71f2659 + e2e_full) bảng có 7 FAIL, đều do B1/B2; xem cột "trạng thái" dưới đây.

## Lỗi tìm thấy ở VH

| Mã | Lỗi | Trạng thái |
|---|---|---|
| B1 | Kết quả của hành động làn D chạy nền (`contact_call`, `emergency_call`, `ride_*`, `music_play`) không bao giờ được đọc (`_fire_after_readback` gọi `run_background(deliver=None)`); `MULTIPLE_CONTACTS_FOUND`/`CONTACT_NOT_FOUND`/lỗi cũng im. | Đã sửa ở commit "Task 15B fix": kính có phiên WS nhận khung `reply` `result-<request_id>` + 0x02 + `reply_end`, xếp hàng sau lượt đang phát (một kênh audio có thứ tự `DeviceSession._audio_lock`, I4); bỏ câu xác nhận đầu vì đã đọc lại. Kính POST/`/process` không đổi. Test `test_lane_d_result_is_pushed_as_server_reply`; mô tả khung ở `FIRMWARE_ENDPOINTS.md` §2.2. |
| B2 | Bấm nút dừng chỉ đường gửi `navigation_stop` nhưng không đóng live nav (không `end`, hazard vẫn chạy). | Đã sửa ở cùng commit: `_bypass` gọi `sessions.close_device(device, "nav")`. Test `test_button_stop_navigation_also_closes_nav_live`. |
| B3 | `_bypass` nuốt mọi lần bấm khi đang phát nhạc/dẫn đường ("tăng âm lượng" = dừng nhạc; chat = dừng dẫn đường). | Đã sửa ở cùng commit theo quyết định controller: chỉ áp khi lượt không có lời (no_speech); lượt có lời được phân loại bình thường. Test `test_button_press_without_speech_stops_music_but_speech_is_classified`. |
| B4 | Lượt "đặt xe" đọc "Đang tìm xe" nhưng chưa gửi gì; `ride_confirm` không bao giờ được gửi. | Đã sửa ở cùng commit: `handle_quote` gửi `ride_quote` ngay; `handle_confirm` gửi `ride_confirm {quote_id, confirm}` (huỷ = `confirm:false`) bằng `quote_id` đã nhớ; `tests/test_services.py` viết lại. |
| (nhỏ) | `Task exception was never retrieved: aclose(): asynchronous generator is already running` khi đóng socket giữa câu chat dài (thấy một lần ở e548c10). | Không tái hiện được, nhưng đợt sửa cuối chặn tận gốc: mọi chỗ lặp generator audio async (`_send_reply`, `_stream_until_disconnect`, outbox nav, OCR live, cue đọc thay clip) dùng `contextlib.aclosing`, nên bị huỷ giữa câu thì generator đóng ngay trong task đó, không để GC gọi `aclose()` lúc nó đang chạy. |

Quan sát: Gemma >= 0,999 chạy thẳng ở hầu hết lượt lệnh (hỏi lại "phải không?" -> "Đúng." chạy đúng ở một lần chạy trước, lệnh vẫn tới ĐT).
Nhả nút -> lệnh ĐT (2,1-3,4 s) chủ yếu là thời gian đọc lại + cửa sổ huỷ làn D (`readback_delay` + `ACTION_TTS_LEAD_S`), không phải
mạng/AB: lệnh từ VH tới ĐT giả mất < 0,1 s. Kết quả được đọc 0,5-0,85 s sau khi ĐT báo.
