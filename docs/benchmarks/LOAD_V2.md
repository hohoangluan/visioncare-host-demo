# Bench tải đồng thời `WS /v2/session` (Task 16)

Đo 2026-10-19 (21:57-22:03 giờ máy), chế độ nhanh: chỉ N = 1 và N = 4 kính. Công cụ: `tools/bench_load.py`
(dùng lại `one_turn_ws` của `bench_live.py`). Mỗi kính một socket `/v2/session`, lượt cách nhau 2-5 s,
mix `chat:4,space:2,ocr:2,call:1,nav:1`, seed 7. Số liệu = **nhả nút -> khối audio đầu (ms)**.

## Điều kiện (đọc trước khi dùng số)

- Server VH `uvicorn --loop uvloop --http httptools`, `ONNX_DEVICE=cuda`, GPU 1 (2080 Ti), `V2_DEBUG_STATS=1`.
  GPU dùng chung: lúc đo GPU 1 đã ở 94-99% utilization (agent khác chạy cùng lúc), Gemma là `llm.uit.edu.vn`
  qua mạng. Con số tuyệt đối nhiễu; so N=1 với N=4 chạy liền nhau thì tương đối công bằng.
- Luồng `call` thật: AB (cổng 18011, PostgreSQL test 55437) + `phone_sim` (18012) nhận lệnh webhook, cả 4 kính ghép cùng
  một user. Luồng `nav` = "Bật cảnh báo vật cản" (ảnh cảnh tổng hợp), lượt chỉ trả cue nên không có audio:
  cột `rep` (khung `reply`) thay cho audio.
- Mẫu nhỏ (chat 11 và 13 lượt): p90 chỉ là mẫu thứ 10/12 trong dãy sắp xếp; đọc p50 là chính, p90 là gợi ý.

## Kết quả

N = 1 (24 lượt, 359 s):

| luồng | n | lỗi | p50 | p90 | max | rep p50 | rep p90 | starve p90 | starve max |
|---|---|---|---|---|---|---|---|---|---|
| chat | 11 | 0 | 872 | 922 | 1383 | 268 | 288 | 68 | 79 |
| space | 3 | 0 | 669 | 735 | 735 | 144 | 189 | 21 | 21 |
| ocr | 4 | 0 | 854 | 877 | 877 | 259 | 264 | 88 | 88 |
| call | 2 | 0 | 600 | 606 | 606 | 172 | 176 | 0 | 0 |
| nav | 4 | 0 | (cue) | | | 177 | 218 | 0 | 0 |

N = 4 (32 lượt, 160 s):

| luồng | n | lỗi | p50 | p90 | max | rep p50 | rep p90 | starve p90 | starve max |
|---|---|---|---|---|---|---|---|---|---|
| chat | 13 | 0 | 1073 | 1404 | 2152 | 278 | 1382 | 4471 | 4971 |
| space | 9 | 0 | 907 | 1220 | 2237 | 197 | 244 | 3175 | 3221 |
| ocr | 4 | 0 | 1427 | 1441 | 1441 | 293 | 333 | 5422 | 5422 |
| call | 3 | 0 | 747 | 2433 | 2433 | 220 | 1694 | 222 | 222 |
| nav | 3 | 0 | (cue) | | | 227 | 474 | 0 | 0 |

| | N=1 | N=4 |
|---|---|---|
| `max_inflight` request Gemma | 3 | 5 |
| tổng request Gemma / lượt | 3,5 (85/24) | 3,5 (113/32) |
| lỗi / socket rớt | 0 | 0 |
| call thực thi tới phone_sim | có | có (8/8 lượt trong chạy thử riêng) |

`starve` = tổng ms đứt tiếng nếu loa phát ngay khi có byte đầu (xem `_starvation_ms`); `max_inflight` đo bằng
bộ đếm trong `models/llm/client.py` (đọc qua `GET /v2/debug/stats`).

## Kết luận

- Tiêu chí của plan: p90 chat <= 1,2x p90 lúc N=1 và `max_inflight` <= 40.
  - `max_inflight`: 5 ở N=4, rất xa trần 40 (mỗi lượt ~3,5 request, phần lớn chồng nhau không quá 3).
  - p90 chat: 1404 / 922 = **1,52x** (p50: 1073 / 872 = 1,23x). **N lớn nhất đạt tiêu chí trong hai mức đã đo là N = 1**;
    chưa đo N = 2, 3 nên chưa biết ngưỡng thật nằm giữa 1 và 4.
- Nút thắt không phải Gemma mà là **TTS cùng GPU**: `rep` (cue/reply) hầu như không đổi (chat p50 268 -> 278 ms) nhưng
  `starve` nhảy từ <= 90 ms lên 3-5 s. TTS chạy RTF ~0,76 mỗi luồng, 4 luồng chồng nhau cùng một GPU đang bận
  thì vượt thời gian thực, nên chữ đầu tới chậm và các mảnh sau tới trễ hơn tốc độ loa phát. Chỗ cần xem tiếp là đệm
  preroll (`V2_AUDIO_PREROLL_SECONDS`) hoặc hàng đợi TTS theo kính, không phải số kết nối Gemma.
- Tác dụng phụ: bench phát hiện lỗi cách ly kính ở Task 6 (lệnh chờ làn D chạy trên `threading.Timer` mất `device_ctx`,
  `call_service_api` gửi `device_id` mặc định thay vì kính thật). Đã sửa trong `pipeline/pending_action.py`
  (test `test_pending_action_runs_in_its_device_context`).

## Chạy lại

```bash
V2_DEBUG_STATS=1 CUDA_VISIBLE_DEVICES=<gpu trống> ONNX_DEVICE=cuda ~/.venvs/seevia/bin/python \
  -m uvicorn app:app --host 127.0.0.1 --port 18894 --loop uvloop --http httptools
python tools/bench_load.py --base http://127.0.0.1:18894 --glasses 4 --turns 8 --street <ảnh cảnh> --out out.json
python tools/bench_load.py --resummarize out.json
```

Luồng `call` cần `VISIONCARE_HOST_URL` trỏ AB thật + `phone_sim` (xem báo cáo Task 15); thiếu thì bỏ `call` khỏi `--mix`.
