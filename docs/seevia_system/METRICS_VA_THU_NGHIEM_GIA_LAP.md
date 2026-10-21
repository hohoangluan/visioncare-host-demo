# Metric và quy trình thử nghiệm SeeVia khi chưa có kính

Ngày lập: 18/10/2026 (Asia/Ho_Chi_Minh). Phạm vi: `visioncare-host-demo` và
`app-demo-backend/server`. Đối chiếu trực tiếp source hiện có; số liệu lịch sử
trong README không được xem là kết quả của lần chạy này.

## 1. Quy ước đo

Dùng đồng hồ monotonic (`time.perf_counter()` / `time.monotonic()`) cho khoảng
thời gian; dùng UTC hoặc ngày giờ có timezone cho thời điểm ghi nhận.
`t0_client` là lúc bắt đầu gửi HTTP, sau khi đã chuẩn bị file audio/ảnh và
multipart. Không cộng thời gian tạo audio đầu vào bằng TTS vào latency server.
`t0_server` trong `app.process()` bắt đầu sau bước multipart của framework;
vì vậy không bao gồm toàn bộ upload và parse multipart.

Giả lập ở đây có ba mức cần phân biệt:

1. **Logic/API với mock**: chạy code server thật, thay STT/Gemini/TTS hoặc
   phone delivery ở boundary bằng fake. Đánh giá hành vi và hợp đồng; không
   suy ra tốc độ hay độ chính xác model thật.
2. **Microbenchmark cục bộ**: đo codec/quality gate thật với tín hiệu/ảnh tổng
   hợp. Latency CPU có giá trị cho chính fixture và máy đo; không đại diện mic,
   OCR, tiền thật hoặc chất lượng thị giác thực tế.
3. **Server với model thật**: gửi WAV/ADPCM/ảnh qua socket tới server đã nạp
   model. Chưa có kính vẫn đo được lớp này, nhưng cần model, credential,
   dataset có nhãn; thiết bị âm thanh/Android vẫn là một phép đo khác.

## 2. Metric đã có trong source và cách tính

| Metric | Công thức / mốc | Ý nghĩa và giới hạn | Nguồn |
|---|---|---|---|
| `stt` | thời gian gọi `stt.transcribe(audio)` | Có decode WAV, resample, inference; có thể gồm load nếu chưa warm | `pipeline/router.py::_resolve`, `pipeline/stt.py` |
| `phân-loại` | thời gian `intent.detect_with_params(text)` | Local encoder/head hoặc Gemini, kể cả slot/fallback | `pipeline/router.py::_resolve` |
| `handler` | từ gọi handler đến `next(pieces)` | Mảnh text đầu, không phải toàn bộ Gemini; có thể là thông báo tiến độ của action | `pipeline/router.py::_resolve` |
| `xử lý` | từ vào `process()` đến dựng `_stream_audio` | Hiện có câu ack đứng trước router: không được gọi chỉ số này là tổng STT+intent+Gemini | `app.py::process` |
| `ttfb` trong log server | thời gian từ `t0_server` đến yield payload đầu, bỏ `prelude` WAV | Thời điểm server nhả audio, thường là ack; không phải lúc client nghe và không phải nội dung hữu ích | `app.py::_stream_audio` |
| `tổng` trong log | hết iterator audio − `t0_server` | Sinh/gửi hết stream ở server; chưa phải hết phát ở client | `app.py::_stream_audio` |
| `audio` trong log | số byte payload / byte rate định dạng | Xấp xỉ thời lượng stream; MP3 có padding, ADPCM có padding block | `app.py::_stream_audio` |
| `t_headers` | nhận xong HTTP headers − `t0_client` | Bao gồm connect/upload/xử lý trước headers trên đường client đo | `tools/bench_e2e.py` |
| `t_first_byte` | body byte đầu − `t0_client` | ADPCM WAV có header 60 byte ra trước payload | `tools/bench_e2e.py` |
| `t_first_audio` | byte audio đầu sau header WAV − `t0_client` | Vẫn có thể là ack; không tự tách được ack/tiến độ/kết quả | `tools/bench_e2e.py` |
| `t_total` phía client | EOF stream − `t0_client` | Thời gian nhận hết; không phải thời điểm loa phát xong | `tools/bench_e2e.py` |
| Tỷ lệ nhả | thời lượng audio / (EOF − byte body đầu) | Chỉ số tốc độ trung bình; >1 không chứng minh không hụt ở mọi thời điểm | `tools/bench_e2e.py::_ratio` |
| Brightness | mean pixel grayscale, [0,255] | Ở độ phân giải gốc | `pipeline/image_quality.py::measure` |
| Sharpness | variance của `up+down+left+right−4*center`, float64, bỏ biên 1 pixel | Không resize; không phải confidence OCR/money | `pipeline/image_quality.py::_sharpness` |
| Intent confidence | xác suất lớp top-1 | Logistic head: softmax đa lớp, sigmoid nhị phân | `pipeline/intent_local.py::_probabilities` |
| Intent margin | p(top-1) − p(top-2) | Local chỉ nhận khi qua cả confidence và margin | `pipeline/intent_local.py::classify` |
| Accuracy eval khi train | số dự đoán đúng / số câu eval | Chỉ số được tính khi train; không chứng minh accuracy cấu hình deployment | `tools/train_intent_setfit.py` |

Các đường dẫn `pipeline/`, `tools/`, `app.py` trong bảng thuộc
`visioncare-host-demo/`. Source chưa cung cấp một bộ exporter thống nhất cho
mọi metric, chưa có tracing stage đầy đủ cho mỗi request.

## 3. Bốn mốc người dùng quan tâm

| Mốc | Định nghĩa cần dùng | Khi chưa có thiết bị |
|---|---|---|
| `T_ack` | từ bắt đầu gửi đến bắt đầu nghe tiếng xác nhận | Có thể đo `ack_payload_ready` tại server/client làm proxy, phải ghi rõ; chưa đo loa thật |
| `T_first_useful` | đến bắt đầu nghe thông tin trả lời đúng câu hỏi | Cần gắn timestamp và vị trí sample bắt đầu nội dung; loại ack và câu trấn an |
| `T_total` (nghe) | đến hết phát toàn bộ audio | Không bằng EOF HTTP; cần mô hình playback hoặc đo thiết bị |
| `T_action` | đến lúc Android thực sự hoàn tất hành động | Report fake chỉ cho `simulated_action_completion`; chưa chứng minh FCM/Android thật |

Ở playback giả lập, mỗi chunk có mốc tới `a_i`, thời lượng `d_i`. Khi chunk
đầu được phép phát tại `s`, cập nhật `play_end=max(play_end,a_i)+d_i`.
Mỗi lần `a_i>play_end` sau khi đã bắt đầu phát là một underrun; cộng chênh
lệch để ra tổng thời gian hụt. Nếu chunk chứa ack trước nội dung, thời điểm
nghe nội dung còn chịu hàng đợi sample của ack, pause và câu trấn an.

`AUDIO_PREROLL_SECONDS=2` là **hai giây nội dung audio**, không phải hai giây
đồng hồ. TTS sinh nhanh hơn realtime hoặc cache ack có thể gom đủ sớm hơn 2s.
Vì thế kết luận “preroll 2s luôn làm latency tối thiểu 2s” trong trao đổi cũ
không đúng với source. Cần đo thời gian gom và điểm bắt đầu nội dung riêng.

## 4. Công thức audio, tốc độ và buffering

- PCM16 mono 16 kHz: `byte_rate=16000*1*2=32000 B/s`;
  `duration=payload_bytes/32000`. Bỏ RIFF header nếu là WAV.
- IMA ADPCM: block 256 byte, `samples_per_block=1+2*(256−4)=505`;
  `byte_rate=16000*256/505=8110.891089… B/s`.
  `duration=N_complete_blocks*505/16000`, trừ padding bằng số sample thật
  trong `fact` nếu có. Header HTTP làm tròn byte rate xuống 8110.
- MP3 CBR 32 kbps: `byte_rate=32000/8=4000 B/s`; phép chia byte chỉ xấp
  xỉ vì frame padding/encoder delay. Dùng decoder/ffprobe nếu cần chính xác.
- `RTF=thời_gian_xử_lý/thời_lượng_audio_đầu_vào` cho STT, hoặc chia cho
  thời_lượng_audio_đầu_ra cho TTS. RTF nhỏ tốt; tốc độ sinh là `1/RTF`.
- `preroll_target_bytes=floor(preroll_seconds*byte_rate)`; block/chunk có thể
  làm lượng gom vượt mục tiêu. Audio ngắn hơn mục tiêu vẫn được flush ở EOF.
- `throughput_Bps=payload_bytes/thời_gian_nhận`; cần nói rõ mẫu số có gồm
  thời gian chờ trước payload hay không. Không nhầm throughput mạng với RTF.
- Không thể kết luận không underrun chỉ từ duration/tổng. Cần lịch chunk và
  buffer còn lại trước **từng lần** chunk mới đến.

Đầu vào raw ADPCM dùng `application/octet-stream` được `ensure_wav()` bọc
RIFF để decode. ADPCM WAV và PCM WAV có sẵn đi qua đường khác. Không dùng
`audioop` cho biến thể block IMA này. `Accept: audio/wav` chọn PCM WAV đầy đủ;
để chọn ADPCM dùng `audio/wav;codec=ima_adpcm` hoặc mặc định hiện tại.

## 5. Metric accuracy cần đo với dữ liệu có nhãn

Các công thức dưới đây là yêu cầu đánh giá, chưa phải số đo hiện có của
deployment. Ô chưa đo phải để trống, tuyệt đối không điền 0 thay “chưa biết”.

| Metric | Công thức | Cần có |
|---|---|---|
| STT WER | `(S+D+I)/N_reference_words` | transcript chuẩn, quy tắc Unicode/case/dấu câu/chuẩn hoá số cố định; WER có thể >1 |
| STT CER | edit distance theo ký tự / số ký tự tham chiếu | Quy tắc có/không khoảng trắng, NFC Unicode |
| Intent accuracy | đúng / N | Label chuẩn, tách train/eval và kiểm tra trùng |
| Precision lớp k | `TP_k/(TP_k+FP_k)` | Confusion matrix; mẫu số 0 thì N/A |
| Recall lớp k | `TP_k/(TP_k+FN_k)` | Tính cả câu lớp k bị bỏ/fallback khi đánh giá local selective |
| F1 lớp k | `2PR/(P+R)` | Macro-F1 lấy trung bình các lớp, weighted-F1 theo support |
| Local coverage | local nhận / N | Confidence/margin **thực sự** đang dùng |
| Selective accuracy | local đúng / local nhận | Không đồng nhất với accuracy toàn pipeline |
| Gemini fallback rate | request thực gọi Gemini để phân loại/slot / N | Không luôn bằng 1−coverage: local ra label nhưng cần slot vẫn gọi Gemini |
| Slot exact match | mọi slot đúng / N cần slot | Chuẩn hoá tên/số/địa chỉ theo quy tắc công bố |
| Vision correctness | đúng / N ảnh có ground truth | OCR CER/WER; tiền exact denomination/set; find hướng/vật; hazard FP/FN riêng |
| False accept/reject ảnh | ảnh xấu lọt / ảnh xấu; ảnh tốt bị chặn / ảnh tốt | Nhãn chất lượng thực, không suy từ ảnh noise tổng hợp |
| HTTP success rate | HTTP 2xx / N | Chỉ kiểm transport |
| Semantic success rate | câu trả lời/action đúng, đủ, không lỗi / N | Ground truth và phân loại nội dung; 200 audio báo lỗi là semantic failure |

Default source hiện là confidence **0.50**, margin **0.15**, param confidence
**0.75**; README/comment có chỗ nói 0.80/0.50. Phải ghi giá trị runtime.
`eval.jsonl` có thể dùng kiểm tra dữ liệu; thiếu model thì không được phát
sinh accuracy giả từ nhãn hay dùng mock “đo” accuracy AI.

## 6. Backend: trạng thái, idempotency, retry và callback

Backend có 13 action route trong `server/src/app/actions.py` (khác 15 intent
đang map handler trong voice router). `202` là accept/persist, chưa phải
delivery hay completion. Mốc backend có thể dùng để tính:

- Accept latency: response 202 − bắt đầu POST.
- Delivery lag: adapter trả SENT − accept; fake không gồm FCM.
- Report latency: nhận/commit report − accept; fake không gồm Android.
- Callback lag: callback thành công − terminal state; retry count là số lần
  thử trừ 1. Poll observation lag: lúc client quan sát terminal − lúc terminal.
- Action success/timeout/failure rate: số operation từng terminal state / số
  operation độc nhất (không đếm duplicate POST thành action mới).
- Idempotency: cùng ID/cùng payload phải trả operation cũ, không tạo thực thi
  thứ hai; cùng ID/khác payload phải conflict 409.
- Duplicate/conflicting/late report, sai owner/device, lease recovery và race
  phải kiểm trên PostgreSQL thật. Thời gian một pytest test bao gồm setup,
  assertion, clock giả, DB cleanup; **không** gọi nó là action latency.

Một số test dùng fake clock để ép timeout/retry: test chạy vài ms không có
nghĩa timeout cấu hình chỉ vài ms. Phải giữ nguyên kỳ vọng contract trong test.

## 7. Tóm tắt thống kê và CSV

Với một ca/cấu hình, sau cold run riêng, nên có ≥30 warm repetitions. Báo
`n`, lỗi, mean, p50, p95, p99; p99 trên 30 mẫu chỉ là mô tả đuôi với độ tin
cậy thấp. Dùng percentile tuyến tính: sort `x`, `h=(n−1)*q`, nội suy giữa
`floor(h)` và `ceil(h)`; không trộn cold/warm, mock/model thật, độ phân giải,
codec, concurrency hoặc lỗi vào một nhóm latency thành công.

CSV hợp nhất dùng UTF-8 BOM để mở trong Excel; mỗi dòng có loại bản ghi
(`test_case`, `measurement`, `summary`, `unavailable`), nhóm, case, stage,
status, số lần lặp, giá trị/đơn vị, mode và ghi chú bằng chứng. Thời gian test
được đặt tên `test_call_duration_s`; stage benchmark dùng `latency_s`.
Không có metric nào được nội suy để lấp chỗ thiếu model/thiết bị.

## 8. Phạm vi chạy được và ca cần ưu tiên

Đầu tiên chạy suite voice sẵn có (mock AI), backend suite trên PostgreSQL
riêng với fake delivery. Sau đó đo encode/decode PCM↔ADPCM và quality gate
với fixture tổng hợp, tuần tự và concurrency 2/5. Test logic có clock giả
không dùng để tính p95 inference. Ghi cả failure có sẵn, không sửa assertion
hoặc source production để làm đẹp kết quả.

Các ca cần lưu ý từ source:

- Router đang bypass STT/intent khi music hoặc navigation bật, biến mọi yêu
  cầu thành stop; kiểm tra “tăng âm lượng” và “đọc chữ” dưới trạng thái đó.
- Quality gate bỏ qua ảnh không decode được (`measure=None`); cần ghi nhận
  pass-through, không báo là ảnh đã được validate thành công.
- Money hiện gọi Gemini bằng prompt; quality gate ngoài handler không thay
  thế một bộ kiểm tra mệnh giá xác định.
- Callback delivery lỗi vĩnh viễn, duplicate/report muộn, lease/retry cần
  đọc kết quả test thực tế; không mặc định lỗi mô tả trong trao đổi cũ còn nguyên.

Chưa thể kết luận WER, accuracy intent/vision, Gemini TTFT, TTS model latency,
T_first_useful nghe thật, underrun phần cứng hay FCM/Android completion nếu
chưa có model/dataset/credential/thiết bị tương ứng.

## 9. Bằng chứng sau lần chạy

Kết quả nằm trong `experiments/2026-10-18/results.csv`: **22.838 dòng dữ
liệu**, gồm 21.351 observation đo, 766 kết quả test/probe, 711 nhóm thống kê
và 10 mục chưa đo được. CSV dùng UTF-8 BOM. Thống kê được kiểm tra lại bằng
`experiments/verify_results.py`; bằng chứng ở `verification.log`.

### Các phép đã chạy

- **1.620 request HTTP loopback**: PCM WAV / ADPCM WAV / raw ADPCM đầu vào;
  PCM stream / ADPCM WAV đầu ra; preroll 0 / 0,5 / 2 giây; concurrency
  1 / 2 / 5; mỗi cấu hình 30 request warm. Có warmup riêng không đưa vào
  percentile. STT, intent, handler và TTS được giả lập tại boundary; codec,
  multipart, socket, routing, quality gate và streaming dùng code thật.
- **90 vòng backend warm** với PostgreSQL thật và delivery/report giả lập,
  mỗi mức concurrency 1 / 2 / 5 có 30 vòng, thêm một warmup mỗi mức. Đã kiểm
  tra accept 202, delivery, report, status succeeded, replay cùng ID và
  conflict 409. Không thực hiện cuộc gọi điện thoại thật.
- **1.302 observation microbenchmark**: codec với tone 0,5 / 3 / 10 giây;
  quality gate với ảnh tổng hợp 640×480 và 1600×1200, gồm normal, dark,
  bright, flat, corrupt, cho OCR/money/chat. Mỗi ca gồm một first observation
  và 30 warm observation. First observation không đại diện cold start model.
- Suite voice: **374 passed, 2 failed, 15 skipped**. Suite backend:
  **370 passed, 1 failed**, bao gồm **84 integration test passed** trên
  PostgreSQL thật. Thời gian pytest trong CSV là `test_call_duration_s`.
- Bốn probe riêng xác nhận yêu cầu “tăng âm lượng” / “đọc chữ” bị chuyển
  thành stop khi music hoặc navigation đang bật. Các dòng này đánh dấu
  failed theo kỳ vọng giữ nguyên câu lệnh; không gọi action thật.

### Kết quả backend minh hoạ

Đơn vị ms; số liệu từ ASGI HTTP trong tiến trình và PostgreSQL qua TCP.
Engine thử nghiệm dùng NullPool; worker được gọi trực tiếp, không bao gồm
đợi polling, FCM, Android hoặc callback vận hành thực tế.

| Concurrency | Accept p50 / p95 | Vòng accept→delivery giả→report→status p50 / p95 |
|---|---:|---:|
| 1 | 27,006 / 28,787 | 139,522 / 151,077 |
| 2 | 32,415 / 37,636 | 203,488 / 210,592 |
| 5 | 63,230 / 69,908 | 407,822 / 413,685 |

Các request HTTP giả lập dùng delay có chủ đích: STT 20 ms, intent 10 ms,
handler 30 ms, TTS 4×5 ms; ack cache là tone 0,5 giây, pause 0,45 giây,
answer là tone 1 giây. `passed` ở phép này nghĩa là HTTP/codec/waveform đúng
fixture, **không phải OCR đúng hay AI đạt latency dưới 1 giây**.
`useful_payload_ready_s` đo lúc prefix audio chứa sample nội dung đã tới;
`simulated_useful_playback_s` tính thêm hàng đợi phát ack/pause. Không có
tiếng nói hoặc loa thật trong phép này. Không đo cold start model.

### Lỗi và giới hạn giữ lại

1. Voice: kết quả decode ADPCM của source và FFmpeg **không bit-exact** trên
   fixture test. Ví dụ mẫu đầu source ra 11, FFmpeg ra 13. Đây là mismatch
   đã quan sát, chưa kết luận bên nào phù hợp decoder trên kính.
2. Voice: FFmpeg **4.2.7** trên máy không hỗ trợ option `-block_size 256`
   của test encode chiều ngược. Test này lỗi môi trường/công cụ; không được
   xem là đã chứng minh tương thích chiều FFmpeg→source.
3. Backend: test và script OpenAPI dùng `parents[3]`, trỏ lên thư mục
   `SeeVia_system/contracts` thay vì `app-demo-backend/contracts`. Kiểm tra
   tường minh thư mục đúng cũng thấy hai artifact khác output sinh trong
   môi trường dependency của lần này. Chưa sửa source/artifact hoặc kết
   luận drift chỉ do đường dẫn; cần đối chiếu thêm với môi trường lockfile.
4. 15 test voice cần Gemini thật được suite bỏ qua do thiếu API key.
   Không có model STT/TTS/intent đã triển khai hoặc dataset giọng nói/ảnh
   có nhãn. WER/CER, accuracy AI, Gemini TTFT, latency inference thật,
   thời điểm nghe thật, underrun phần cứng và Android completion đều
   `not_measured`, giá trị để trống.

Môi trường: Python **3.13.15**, PostgreSQL **16**, FFmpeg **4.2.7**;
dependency cài riêng trong `/tmp/seevia-experiment-venv`, danh sách chính
xác ở `packages.txt`. Lần chạy này resolve dependency trong khoảng phiên
bản khai báo, **không phải** môi trường tái tạo bằng `uv sync --frozen`.
CPU/môi trường và thời điểm bắt đầu có trong `environment.json`. Các phép
đo chạy trên server hiện có, không phải máy vật lý dành riêng cho benchmark.
Container PostgreSQL thử nghiệm đã được xóa sau khi xuất và kiểm tra CSV.
Không sửa code production để làm test đạt.

### Đối chiếu và chạy lại

Đứng tại thư mục gốc `SeeVia_system`, dùng interpreter môi trường thử nghiệm:

```bash
/tmp/seevia-experiment-venv/bin/python experiments/run_simulations.py
# Sau khi PostgreSQL thử nghiệm đã được dựng và migrate bằng integration suite:
TEST_DATABASE_URL=postgresql+asyncpg://seevia_test:seevia_test@127.0.0.1:55439/seevia_metrics_test \
  /tmp/seevia-experiment-venv/bin/python experiments/backend_probe.py
/tmp/seevia-experiment-venv/bin/python experiments/run_simulations.py --aggregate-only
/tmp/seevia-experiment-venv/bin/python experiments/verify_results.py
```

`run_simulations.py` đọc `voice-tests.xml` và `backend-tests.xml` có sẵn để
gộp kết quả suite; không tự chạy lại pytest. Muốn kết quả suite mới, chạy
`python -m pytest tests -q --junitxml=<đường dẫn XML> -o junit_duration_report=call`
trong từng thư mục server; đặt `TEST_DATABASE_URL` cho backend. Chỉ dùng DB
tạm có tên chứa `test`; integration suite tự migrate. Database đã dọn nên
phải dựng lại trước khi chạy backend. Cần môi trường cho phép socket loopback.
Verifier hiện kiểm tra đúng quy mô dataset của lần chạy này.

Log gốc, JUnit XML, observation backend và package manifest nằm cùng CSV.
Các file `*-diagnostic.log` ghi lần chẩn đoán sandbox chặn socket, không phải
kết quả suite cuối. Phần thống kê chỉ lấy các dòng `phase=warm`,
`status=passed`; các dòng `unavailable` và test thất bại không bị loại khỏi CSV.
