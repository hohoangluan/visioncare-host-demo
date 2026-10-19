# Bàn giao: voice server v2 (cập nhật 2026-10-19)

Spec gốc: `docs/superpowers/specs/2026-10-19-voice-server-architecture-design.md`.
Luồng v2 (`/v2/image`, `/v2/turn`, `/v2/live`) đã xây xong và chạy đầu-cuối trên
máy này. **Chưa commit gì** (cả phần có từ trước phiên này lẫn phần mới).

## Việc còn lại (theo thứ tự)

1. **Cloudflare chặn streaming audio lên server — quyết định cách xử lý** (kết quả đo 2026-10-19 bên dưới).
   Cloudflare gom đủ body `POST /v2/turn` rồi mới chuyển cho server (`upload=` ≈ 0 trong log dù audio dài 2–2,75 s;
   chạy thẳng local thì `upload` ≈ `audio`). Hệ quả: partial STT, đoán sớm, prewarm không chạy trước lúc nhả nút;
   intent cuối mất ~0,25 s thay vì ~0,05–0,1 s (cache từ partial). Phản hồi audio (server → kính) thì stream bình thường.
   WebSocket qua Cloudflare không bị gom (đã thấy ở làn C: khung → hazard 37–73 ms). Hướng sửa (cần người dùng chọn,
   đụng giao thức firmware): (a) đẩy audio qua WebSocket (`WS /v2/turn`), hoặc (b) chia audio thành nhiều POST nhỏ
   keep-alive (`POST /v2/audio?turn=..&seq=n`, mỗi cái ~0,3 s ≈ 2,4 KB). Ước tính lợi ≈ 0,1–0,15 s nhả nút → tiếng đầu.
   Bench qua tên miền: `tools/bench_live.py --base https://api.visioncare-host.uk --resolve api.visioncare-host.uk=104.21.67.134 ...`
   (`--resolve` vì resolver máy này từng cache NXDOMAIN; IP lấy bằng `dig api.visioncare-host.uk @1.1.1.1 +short`).
   Tunnel `api.visioncare-host.uk` → `http://localhost:18888` do người dùng cấu hình, đã chạy; server **không có xác thực**,
   chỉ bật khi đo và tắt ngay sau đó (`fuser -k 18888/tcp`).
   Chưa đo: phần WiFi của kính (cần log 4 mốc trên kính); ảnh UXGA qua WiFi upstream có thể về SAU audio (bench: `/v2/image`
   qua Cloudflare 0,3–0,6 s, có lần 2,5 s → lượt đó phải chờ ảnh tới `IMAGE_WAIT_S`=1,5 s trước khi trả lời làn A/B);
   mỗi `/v2/image` và `/v2/turn` là một kết nối TLS riêng từ kính (spec §17).
2. Làn D (gọi điện, nhạc...) mới đo tới câu báo lỗi: app server `:8001` đang nghe cổng nhưng không
   trả lời ("Server disconnected without sending a response"). Cần bật nó rồi đo lại.
3. Commit (hỏi người dùng).

Đã xong trong phiên này: đo qua Cloudflare (mục 1); cắt câu TTS đầu ≤ 8 từ cho OCR (`lanes/ocr_live.py::spoken`): OCR nhả nút → tiếng đầu
1,02–1,05 s → 0,79–0,86 s.

## Hạn chế cần giải quyết (ưu tiên P1 > P2 > P3; "đã xác nhận" = có bằng chứng, "chưa kiểm" = nghi vấn)

### A. Lỗi / hành vi sai đã biết (sửa được trong code)

- **P1 · Chat cần tra web mà không có khoá Google thì Gemma tự bịa** (đã xác nhận). `.env` không có
  `GOOGLE_SEARCH_API_KEY`/`GOOGLE_SEARCH_CX`, nên `models/search` không bao giờ chạy; `pipeline/final_router.py:112`
  bỏ qua tra cứu mà `lanes/general.py::messages` không thêm câu cảnh báo (code cũ có sẵn:
  `handlers/chat.py::_SEARCH_UNAVAILABLE_INSTRUCTION`). Hỏi thời tiết/tin tức sẽ ra số bịa. Sửa: khi `needs_web` mà
  không tra được thì chèn câu đó vào system prompt; cần người dùng cấp khoá Google để chạy thật.
- **P1 · Hành động điện thoại dựa trên intent chỉ đúng 89,4%** (đã xác nhận: 38/358 sai; nhầm nhiều nhất chat→ocr 8,
  chat→space 7, chat→hazard 6, chat→nav_start 4, chat→music_play 3). Spec coi "gọi nhầm người" là phản mục tiêu.
  Chưa có chính sách xác nhận cho gọi điện/đặt xe/phát nhạc/khẩn cấp (chỉ ride có đọc lại). Bộ đo
  `data/intent/eval.jsonl` là văn bản tổng hợp, KHÔNG phải kết quả STT từ ghi âm kính.
- **P1 · Luật từ khoá dự phòng có thể kích hoạt hành động** (đã xác nhận trong code): `intent_early.EarlyIntent.decide`
  dùng luật từ khoá khi model lỗi, kể cả làn D ("gọi" → contact_call, "đi đến" → nav_start). Sửa: keyword-only chỉ
  được vào làn A/B/C-thông-tin, làn D cần nhãn từ model.
- **P1 · Không xác thực + không giới hạn kích thước** (đã xác nhận): `/v2/*` chỉ dựa vào `X-Device-Id` tự khai; `/v2/image`
  `await request.body()` không giới hạn; `/v2/turn` không giới hạn độ dài audio (`StreamingTranscriber` cứ tích luỹ)
  nên một kết nối treo là tốn RAM mãi. Tunnel công khai làm việc này thành rủi ro thật. Sửa: token thiết bị
  (`VISIONCARE_DEVICE_CLIENT_TOKEN` đã có trong `.env.example`), trần ~30 s audio, trần ~2 MB ảnh, rate limit.
- **P2 · `/process` (firmware cũ) chưa chuyển sang pipeline v2** (spec §5.4; đã xác nhận): vẫn chạy Gemini cũ mà
  `.env` không có `GEMINI_API_KEY`, và `models/intent_encoder` không tồn tại, nên có thể đang hỏng (chưa chạy thử).
  Spec cũng muốn bỏ `models/vlm`, `pipeline/intent_local.py`, `handlers/waiting.py` — chưa bỏ (còn được `/process` và
  `pipeline/phrases.py` dùng).
- **P2 · OCR mất chế độ "nguyên văn"/"chuyên ngành"** (đã xác nhận): `handlers/ocr.py` cũ có RAW/SPECIALIZED;
  `lanes/ocr_live.py::_prompt` chỉ có read(dịch)/summarize/money, và schema Clef/Gemma chỉ có `read|summarize|reread`.
  Sửa: thêm `raw`, `specialized` vào `ocr_mode` (`models/clef/client.py`, `pipeline/intent_classifier.py`) và ánh xạ sang `prompts.Mode`.
- **P2 · Hết trần căn khung OCR đọc ảnh VGA thay vì UXGA** (đã xác nhận): `lanes/ocr_live.py::run` có
  `image = hi_res or best_vga or fallback_jpeg`; nếu lệnh `capture` không về, OCR chạy trên khung VGA 640 px (kém).
  Spec nói "chụp luôn và đọc thử" ở UXGA. Cân nhắc ưu tiên `fallback_jpeg` (ảnh UXGA lúc bấm nút) trước VGA.
- **P2 · Lịch sử chat và `device_state()` dùng chung toàn cục** (đã xác nhận, kế thừa code cũ): `handlers/chat._HISTORY`,
  `handlers/action_flow` — nhiều kính sẽ lẫn hội thoại và trạng thái nhạc/chỉ đường. Sửa: khoá theo device id.
- **P3 · Cảnh báo watermark** (đã xác nhận): log `Watermarker init failed — output audio will NOT be watermarked`
  (gói `perth` cài không phải resemble-perth). Kiểm tra giấy phép/chính sách của vieneu có bắt buộc không.
- **P3 · Làn `find` chưa có object detector** (spec §10): hiện Gemma đọc một ảnh buffer, không dẫn căn khung realtime.

### B. Chưa kiểm chứng trên thiết bị / dữ liệu thật

- **P1 · Mọi số đo dùng dữ liệu tổng hợp**: audio lệnh sinh từ TTS, ảnh chữ vẽ bằng OpenCV, MỘT ảnh xe buýt cho làn C. Chưa có ghi âm
  từ kính (`request*.wav`) hay ảnh OV2640 thật. WER 8,96% là giọng đọc FLEURS. Việc cần làm: thu ghi âm thật, chạy lại
  `tools/bench_stt_compare.py` và chuỗi STT → intent; đánh giá lại ChunkFormer trên dữ liệu đó.
- **P1 · P0 phần cứng của spec §3 chưa làm**: đổi framesize OV2640 lúc chạy, fps thật qua WiFi+TLS, WebSocket client
  trên ESP32-S3 song song I2S, khoảng cách đọc sách với lens 120°. Kính chưa có firmware cho giao thức v2.
- **P1 · Làn B căn khung chưa hiệu chuẩn**: `OCR_MIN_LINE_PX=28`, lề 2%, tràn 90%, `hold_still` = 0,5× độ nét tốt nhất,
  `OCR_GOOD_FRAMES=3`; hậu xử lý PP-OCRv4 tự viết (ngưỡng 0,3, nở hộp 0,4×chiều cao) chỉ thử với chữ tổng hợp. Hướng `look_*`
  (hướng QUAY ĐẦU) chưa kiểm với camera thật.
- **P1 · Làn C chưa biết tỉ lệ báo nhầm ngoài đường** (phản mục tiêu #1 của spec): luật mức/chống làm phiền là bản đầu,
  chỉ thử một ảnh. YOLO COCO không thấy cột, bậc thềm, ổ gà. Chưa quyết người dùng có dùng gậy không (quyết định này
  quyết định có cần ước độ sâu vật ngang đầu / vật mặt đất). Âm báo hazard + audio làn D từ `session.outbox` có thể chồng nhau
  trên kính; chưa định nghĩa ai trộn.
- **P1 · Làn D chưa chạy thật**: app server `:8001` không trả lời. Pending-slot ("Bạn muốn đi đâu?" → lượt sau),
  nhánh `music_play` tự hỏi riêng, callback FCM, `phone.run_background` và việc đọc kết quả qua `session.outbox` (mất nếu WS
  đã đóng trước khi có kết quả) chỉ có test với handler giả.
- **P2 · Tải đồng thời chưa thử**: nhiều kính cùng lúc; TTS dùng chung một model (`max_streams=16`). UIT giới hạn 40 request
  đồng thời MỖI KHOÁ, mà một lượt có thể bắn ~4–6 request (ước tính: ≤ 2 phân loại partial + 1 cuối + 1 câu trả lời đoán trước +
  prewarm + trích tham số); đoán sai là phí.
- **P2 · Huỷ khi kính ngắt giữa chừng** (spec §17) chưa test: `StreamingResponse` bị đóng có dừng Gemma/TTS không.
- **P2 · Server dựa vào kính tự đóng WebSocket khi bấm nút** (spec: "bấm nút ở bất kỳ trạng thái nào đóng mọi kết nối");
  tin `hello` của kính bị bỏ qua, `cue_version` trong `hello` không dùng.
- **P2 · Chưa có clip cue trong flash**: `tools/make_cue_clips.py` (spec §15) chưa tạo; `pipeline/cues.py` `CUE_VERSION=2`.
  Kính cũ (không gửi `X-Cue-Version`) nghe cue bằng TTS (câu đã dựng sẵn).

### C. Hạ tầng / vận hành

- **P1 · Cloudflare không stream upload** (mục "Việc còn lại" số 1) và ảnh UXGA qua WiFi có thể tới sau audio.
- **P1 · Một điểm hỏng duy nhất: Gemma UIT**. LAN đã chết, không có LLM cục bộ dự phòng; UIT hỏng thì chỉ còn cue. Clef chỉ
  dự phòng phân loại, không trả lời được. Cần LLM dự phòng hoặc chấp nhận rủi ro; cũng cần `certs/uit-ca-bundle.pem` trong mọi môi trường chạy.
- **P2 · Dockerfile, `start-demo.ps1`, README, `docs/KIEN_TRUC_SERVER.md` chưa cập nhật cho v2** (nền CUDA, torch + CUDA 13,
  thứ tự cài `onnxruntime-gpu`, cổng 18888, biến môi trường mới trong `config.py`).
- **P2 · Khởi động**: lần đầu ~3 phút dựng sẵn 113 câu TTS (cache `models/.cache/tts_phrases`, dựng lại khi đổi giọng/phiên bản
  vieneu); vieneu gọi HEAD lên huggingface.co lúc nạp (cần mạng; file voices trả 404 mỗi lần). Sau khi đã tải đủ, đặt `HF_HUB_OFFLINE=1`.
- **P2 · GPU dùng chung 8×2080 Ti**: không có cơ chế chiếm VRAM trước, đã gặp OOM; server dùng ~1,8 GB (TTS PyTorch + CUDA graph +
  YOLO + PP-OCR). `ONNX_GPU_ID` là chỉ số TƯƠNG ĐỐI theo `CUDA_VISIBLE_DEVICES`.
- **P3 · Test**: 2 test ffmpeg (`tests/test_adpcm.py`, so bit-for-bit) hỏng vì ffmpeg 4.2 của máy không có cờ `-block_size`
  (nên tự skip khi thiếu cờ); test API dùng `MorphDetector` + model giả chứ không phải PP-OCR/Gemma thật; chưa có test hồi quy độ trễ
  hay test qua Cloudflare.
- **P3 · Quan sát**: chưa có số liệu 4 mốc từ kính (bấm, nhả, byte đầu, tiếng đầu), chưa có request id xuyên suốt, chưa có metrics.
- **P3 · Repo**: chưa commit; thay đổi có sẵn từ trước phiên lẫn với phần mới; `models/*` bị ignore nên file ONNX phải tải/tạo lại (xem "Chạy lại").

## Chạy lại

```bash
# Chọn GPU còn trống (máy dùng chung 8x RTX 2080 Ti, KHÔNG lùi về CPU khi GPU đầy)
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
S=<thư mục tạm>; mkdir -p $S
cd visioncare-host-demo
CUDA_VISIBLE_DEVICES=<gpu A> STORAGE_DIR=$S/storage ONNX_DEVICE=cuda nohup ~/.venvs/seevia/bin/python \
  -m uvicorn app:app --host 127.0.0.1 --port 18888 --loop uvloop --http httptools > $S/server.log 2>&1 &
# đợi dòng "Application startup complete" (lần đầu ~3 phút dựng sẵn 113 câu TTS, sau đó ~25 s)
curl -sL -o $S/bus.jpg https://ultralytics.com/images/bus.jpg      # ảnh đường phố có xe, cho đo làn C
CUDA_VISIBLE_DEVICES=<gpu B> ~/.venvs/seevia/bin/python tools/bench_live.py \
  --base http://127.0.0.1:18888 --runs 4 --cache $S/bench_audio --street $S/bus.jpg
# test (đúng 2 test hỏng là phép so với ffmpeg 4.2 cũ của máy: test_adpcm.py::*ffmpeg*bit_for_bit)
CUDA_VISIBLE_DEVICES=<gpu> ~/.venvs/seevia/bin/python -m pytest -q -p no:cacheprovider -W ignore::DeprecationWarning tests/
```

Tắt server: `fuser -k 18888/tcp` (đừng dùng `pkill -f "...18888"`: nó khớp luôn shell đang chạy).
Model ONNX không nằm trong git (`models/*` bị ignore): `models/hazard/yolo11n.onnx` tạo bằng
`tools/export_hazard_onnx.py` (cần `ultralytics`, chạy trong env tạm), `models/text_det/ch_PP-OCRv4_det_infer.onnx`
tải từ HF `SWHL/RapidOCR` (`PP-OCRv4/`). `.env` có Clef/UIT key; **không có GEMINI_API_KEY**
(đường `/process` cũ dùng Gemini nên có thể không chạy được, chưa kiểm).

## Môi trường: các bẫy đã dính

- Venv `~/.venvs/seevia` (Python 3.11). `vieneu>=3.8.3` (bản 1.x làm server chết khởi động).
- `vieneu` kéo gói `onnxruntime` CPU đè lên `onnxruntime-gpu`. Sửa: `uv pip uninstall onnxruntime onnxruntime-gpu`
  rồi `uv pip install --reinstall "onnxruntime-gpu[cuda,cudnn]"`. Hỏi người dùng trước khi gỡ/cài lại gói.
- **Không** `uv pip install` gói mới có phụ thuộc: torch ghim CUDA 13.0 còn onnxruntime-gpu cần cuDNN 9.27,
  cài thường sẽ hạ cấp 6 gói `nvidia-*`. Dùng `--no-deps`.
- Nạp `onnxruntime` TRƯỚC `sherpa_onnx` (sherpa mang `libonnxruntime.so` riêng, ngược lại thì segfault khi
  TTS GPU nạp). Đã làm ở đầu `app.py` và `pipeline/stt.py`. `models/onnx_session.py` gọi `ort.preload_dlls()`,
  thiếu thì CUDA provider lặng lẽ rơi về CPU.
- `pipeline/tts.py` vá `OnnxV3LiteEngine._fetch` (hard link) vì onnxruntime 1.31 từ chối file `.data` qua symlink HF.
- Ghi file lớn lên `/workingspace_aiclub` (NFS) có thể bị cắt âm thầm: build ở thư mục tạm, kiểm size.

## Quyết định đã chốt (kèm số đo)

| Quyết định | Số đo |
|---|---|
| Intent: **Gemma UIT** trước, Clef API dự phòng (`pipeline/intent_classifier.py`, `INTENT_BACKEND=auto`) | `data/intent/eval.jsonl` 358 câu: Gemma 89,4% p50 161 ms; Clef API 82,4% p50 486 ms (riêng RTT Cloudflare 423 ms) |
| Chỉ dùng Gemma **UIT**; bỏ LAN `192.168.20.150:8899` | LAN nhận TCP rồi "Empty reply" mọi đường dẫn |
| **Clef local đã thử và bỏ** (đừng làm lại) | `Cloudflare/clef-flash` 9B mở (Apache-2.0). Bản `meossistant/clef-flash-4bit` chạy được trên 2080 Ti (Turing, fp16, 6,1 GB) nhưng **2.000–2.200 ms/lượt** (~913 token prompt) so với Gemma 160 ms; độ chính xác chỉ đo 27/30. Ý tưởng còn lại nếu cần bỏ phụ thuộc mạng ngoài: bộ phân loại nhỏ chuyên 17 nhãn |
| STT giữ **Zipformer** (CPU) | FLEURS-vi 200 câu: WER 8,96% vs ChunkFormer 10,19%; ChunkFormer chỉ nhanh hơn ở câu ≥ 3 s (57 vs 87 ms), thua ở câu 1 s (53 vs 36 ms) |
| ONNX trên GPU (`ONNX_DEVICE=auto`) | hazard YOLO11n@320: 9,2 ms (CPU 33); PP-OCRv4 det VGA: 20,9 ms (CPU 103) |
| TTS trên GPU (`TTS_DEVICE=auto`, backend PyTorch) | chunk đầu 126 ms, RTF 0,76 (ONNX/CPU: 1220 ms, RTF 3,2) |
| Đệm audio `/v2/turn` = 0,2 s (người dùng chọn tốc độ) | đệm 0: loa đói tối đa 177 ms trên localhost; với 0,2 s 28/28 lượt `starve=0` (localhost) |
| Gọi kép bộ phân loại khi lượt trên partial chưa xong; lỗi/quá hạn + không khớp từ khoá → làn chat (lệch spec §7.3: spec nói cue `system_busy`) | Clef từng có lượt > 1 s, khiến câu chat bình thường nhận "hệ thống bận" |

Lệch/thêm so với spec (đã giải thích trong code): chạy trước (speculative) câu trả lời làn A và trích tham số
làn D song song với intent cuối, huỷ nếu nhãn khác (`SPECULATIVE_FINAL`); làn B đọc ngay ảnh buffer nếu detector
chữ báo đạt, khỏi mở WebSocket (`OCR_ACCEPT_BUFFER`); tờ tiền luôn đọc ảnh buffer; `nav_start` trả cue ngay, kết quả
điện thoại đọc sau qua WS; hazard dùng YOLO (xe/người) và để vật mặt đất cho gậy. Ý tưởng chưa làm (P3): ước độ sâu
cho vật ngang đầu, gộp mức cao nhất vào `live/hazard.py`.

## Kết quả đo gần nhất (localhost, server GPU, bench giả lập kính; nhả nút → tiếng đầu)

chat 0,62–0,87 s · space 0,52–0,67 s · OCR 0,79–0,86 s · tiền 0,57–0,67 s · gọi điện 0,60–0,65 s (chỉ tới câu báo lỗi) ·
bật cảnh báo → header cue 0,36–0,46 s · khung → bíp hazard 15–18 ms. Chi tiết từng chặng nằm trong log `v2 turn ...` của server.

## Qua Cloudflare (bench trên chính máy server → điểm Hồng Kông → tunnel → server, KHÔNG gồm WiFi kính)

Nhả nút → tiếng đầu, median (min–max), 4 lượt/luồng, cùng code, local so với qua Cloudflare:
chat 747 → 980 ms (+233) · space 652 → 802 (+150) · OCR 806 → 973 (+166) · tiền 535 → 888 (+354).
Header trả về sau nhả nút: +270 ms (phần ~0,12 s là mất cache intent do không stream, còn lại là RTT hai chiều).
Khung → hazard qua WebSocket: 17 ms → 37–73 ms (tối đa 129 ms; mục tiêu < 300 ms vẫn dư xa).
`/v2/image` 0,03 s → 0,3–0,6 s (ngoài đường chờ nếu tới trước lúc nhả nút).
Loa đứt tiếng (đệm 0,2 s): qua Cloudflare 1/36 lượt có đứt 906 ms (0/48 lượt local) → đệm 0,2 s đủ phần lớn; nếu sau này
thấy đứt lặp lại thì tăng `V2_AUDIO_PREROLL_SECONDS` lên 0,4–0,5.

## Bản đồ code mới

`app.py` (3 endpoint v2 ở cuối file) · `config.py` (mục "Voice server v2") · `pipeline/`: `turn.py` (điều phối một lượt),
`stt_stream.py`, `intent_early.py`, `intent_classifier.py`, `prewarm.py`, `final_router.py`, `image_buffer.py`, `cues.py`,
`reply.py`, `speech.py` · `lanes/`: `general.py` (A), `ocr_live.py` (B), `nav_live.py` (C), `phone.py` (D) ·
`live/`: `protocol.py`, `session.py`, `text_align.py`, `hazard.py` · `models/`: `net.py`, `onnx_session.py`, `llm/`, `clef/`, `search/` ·
`tools/`: `bench_live.py`, `bench_stt_compare.py`, `export_hazard_onnx.py` · `tests/`: `test_v2_units.py`, `test_v2_api.py`.
