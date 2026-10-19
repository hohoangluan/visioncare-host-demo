# Bàn giao: voice server v2 (2026-10-19, nhánh `voice-v2-hardening`, `5963ad5`)

Kết quả plan 1 (sửa mọi hạn chế của bản v2 đầu): đã gộp xong, test **429 pass / 2 skip** (2 test ffmpeg tự skip vì ffmpeg 4.2
của máy không có cờ `-block_size`). Chưa push. Spec: `docs/superpowers/specs/2026-10-19-voice-server-architecture-design.md`
và `...-voice-v2-hardening-design.md`. Giao thức cho firmware: `docs/FIRMWARE_ENDPOINTS.md`.

## 1. Đã đổi gì (kèm số)

| Mảng | Thay đổi | Số đo |
|---|---|---|
| Intent (Gemma UIT, Clef dự phòng) | Nhãn ngắn `structured_outputs` (`INTENT_FORMAT=choice`, mặc định); `ocr_mode`/`needs_web` bằng luật (`INTENT_AUX=rules`). Quay lại bản cũ: `INTENT_FORMAT=json` / `INTENT_AUX=gemma` | accuracy test 0,888 -> 0,953; lệnh làn D nhầm 7 -> 0; p50 264 -> ~74 ms, p90 ~83 ms. Ngưỡng chạy lệnh `ACTION_MIN_CONFIDENCE=0.999` (thấp hơn còn 1–2 FP); hỏi lại "...phải không?" ~10% lệnh làn D |
| VAD (Silero) | chốt đoạn nói sớm, không chờ nhả nút | nhả nút -> tiếng đầu p50 824 -> 682 ms; giữ nút 1 s sau khi nói 769 -> 464 ms |
| Tải đồng thời | `tools/bench_load.py`, `docs/benchmarks/LOAD_V2.md` | N=4 kính: p90 chat 1,52× N=1 (p50 1,23×); `max_inflight` Gemma 5 (trần 40). Nút thắt là **TTS dùng chung GPU**, không phải Gemma: đứt tiếng p90 từ <= 90 ms lên 3–5 s ở N=4. N=2,3 chưa đo |
| Giao thức | `WS /v2/session` một socket mỗi kính; hàng đợi audio theo phiên; khung `result-*` server chủ động đẩy; nav sống qua lượt mới | chi tiết `FIRMWARE_ENDPOINTS.md` |
| An toàn làn D | cửa sổ huỷ đếm từ audio đọc lại đầu tiên tới kính; lượt mới/`cancel`/rớt mạng huỷ lệnh; nhãn không rõ độ tin cậy -> hỏi lại | E2E `call_cancel` PASS (điện thoại không nhận lệnh) |
| Xác thực + trần | token kính cho mọi endpoint, trần ảnh 2 MB / audio 30 s, rate limit | mục 3 |
| Kết quả lệnh điện thoại | được đọc cho người dùng (`result-<id>`); `ride_quote`/`ride_confirm` gửi đúng; nút dừng chỉ đường đóng nav live | E2E bên dưới |

### E2E (`tools/e2e_full.py`, kính giả -> VH -> app server -> phone_sim, GPU 6, 1 lượt/kịch bản, tất cả PASS)

| Kịch bản | nhả nút -> tiếng đầu | nhả nút -> lệnh ĐT | lệnh -> kết quả được đọc |
|---|--:|--:|--:|
| call_mom | 523 | 2524 | 858 |
| call_nam (`MULTIPLE_CONTACTS_FOUND` được đọc) | 504 | 2415 | 483 |
| ride (quote rồi confirm) | 550 | 3018 | 842 |
| music (có lời = âm lượng; bấm không lời = dừng) | 560 | 3076 | 992 |
| nav (hazard, chat giữa chừng, bấm dừng) | 555 | 3355 | 873 |
| emergency | 502 | 3712 | 823 |
| call_cancel | 526 | - | - |

Đơn vị ms. "Lệnh ĐT" gồm cả thời gian đọc lại + cửa sổ huỷ (cố ý), mạng VH -> ĐT < 0,1 s. `vh.log`: 0 traceback. Trước đợt sửa cuối
có 7 FAIL (kết quả không đọc, nút dừng không đóng nav, ride không gửi confirm). Chi tiết `docs/E2E_FULL_FLOW.md`.

### Qua Cloudflare (`5963ad5`, trung vị nhả nút -> tiếng đầu, ms; bench trên máy server, **không gồm WiFi kính**)

| lượt | local POST | local WS | CF POST | CF WS |
|---|--:|--:|--:|--:|
| chat | 776 | 688 | 848 | 775 |
| space | 656 | 593 | 736 | 657 |
| ocr | 726 | 655 | 872 | 773 |
| money | 609 | 539 | 805 | 680 |
| contact | 537 | 444 | 708 | 619 |

Header: local ~130–220, CF POST ~385–510, CF WS ~285–335. Ảnh POST qua CF 400–590 ms (local 10–60). Edge của hostname = HKG;
TLS ~70–130 ms mỗi kết nối; chặng edge -> cloudflared -> origin ~150–240 ms. WS nhanh hơn POST **70–125 ms**; phần Cloudflare còn lại
80–175 ms là chặng tunnel. Không có thay đổi code nào đo ra nhanh hơn nên không đổi gì. Số thô: `.superpowers/sdd/2026-10-19-voice-v2-hardening/cf-bench/`.

Đo lại sau khi đổi rule Cloudflare (2026-10-20): header POST nhanh hơn 60–170 ms, ảnh POST 400–590 → 224–420 ms, nhưng
tiếng đầu gần như không đổi (CF POST chat 848 → 843, contact 708 → 703; CF WS 619–815, trong nhiễu n=4). Edge vẫn HKG,
nút thắt vẫn là chặng tunnel.

## 2. Quyết định tôi đã thay bạn

Toàn văn (kèm "cost if wrong") nằm trong ledger `.superpowers/sdd/2026-10-19-voice-v2-hardening/progress.md` (git-ignored, `grep Ruling`).

- Ngưỡng `ACTION_MIN_CONFIDENCE=0.999`: nhỏ nhất cho 0 FP trên dev và test; cái giá là thêm ~1 câu "...phải không?" mỗi 11–20 lệnh làn D.
- Nhãn ngắn thay JSON cho intent (nhanh hơn 183 ms p50 mọi lượt, độ chính xác giảm không có ý nghĩa thống kê, FP vẫn 0); `needs_web`/`ocr_mode` bằng luật.
- Luật từ khoá **không** kích làn D; chỉ dừng/chỉnh nhạc và dừng chỉ đường được chạy khi bộ phân loại hỏng (đảo ngược được, người khiếm thị phải tắt được tiếng).
- "Có/đúng" chỉ tính là xác nhận khi cả câu <= 3 từ và toàn từ đồng ý (tương tự "không/thôi"); trả lời một câu hỏi thiếu thông tin vẫn bị hỏi xác nhận lại.
- Thêm 0,4 s (`ACTION_TTS_LEAD_S`) vào cửa sổ huỷ để TTS không ăn mất thời gian huỷ: lệnh chạy chậm hơn 0,4 s.
- Nav **không** bị lượt mới tắt (hazard vẫn chạy khi hỏi giữa đường); OCR live thì bị tắt.
- Kết quả lệnh điện thoại đọc chủ động qua phiên WS (`result-*`), xếp hàng sau lượt đang phát.
- Bypass "dừng nhạc/dừng chỉ đường" chỉ khi bấm nút **không nói**; có lời thì phân loại bình thường.
- Giữ Clef làm dự phòng (bạn chốt); chỉ tối ưu Gemma.
- Chạy song song bằng worktree; chế độ nhanh (review chỉ T6/T9/T10/T15/C2/C5 + cuối); review cuối dùng opus.

Lệch spec còn giữ: lỗi/quá hạn bộ phân loại mà không khớp từ khoá thì vào làn chat (spec §7.3 nói cue `system_busy`), vì Clef từng có lượt
> 1 s khiến câu chat thường nhận "hệ thống bận". Chạy trước câu trả lời làn A và trích tham số làn D (`SPECULATIVE_FINAL`); làn B đọc ngay
ảnh buffer nếu detector chữ báo đạt (`OCR_ACCEPT_BUFFER`).

## 3. Token (đã thống nhất)

`SeeVia_system/.env` là **nguồn duy nhất**: `VISIONCARE_CLIENT_TOKEN`, `VISIONCARE_CALLBACK_TOKEN` và `VISIONCARE_DEVICE_CLIENT_TOKEN`
(mới). `docker-compose.yml` truyền `VISIONCARE_DEVICE_CLIENT_TOKEN` vào container glasses; `demo.sh` tự sinh nó nếu thiếu.
`VH/.env` giữ bản sao **giống hệt**. `VISIONCARE_DEVICE_CLIENT_TOKEN` là token của kính cho mọi endpoint kính (rỗng -> 503/4401).
Đừng `source` file `.env` trong shell (từng lộ khoá); đọc bằng Python. Khoá SerpAPI đã có và đã kiểm (tra web chạy thật).

## 4. Việc còn lại cho bạn

1. **Điện thoại thật + app server `:8001`**: bật app server và chạy lại theo `docs/E2E_REAL_PHONE.md` (`tools/e2e_full.py --app-url ... --no-phone-sim`).
   Mọi E2E hiện dùng phone_sim; `:8001` từng nghe cổng nhưng không trả lời.
2. **Ghi âm giọng thật**: mọi số đo VAD/STT/intent dùng giọng TTS và văn bản tổng hợp (bộ `data/intent/eval.jsonl` không phải đầu ra STT
   từ kính). Cần ghi âm từ kính thật rồi chạy lại `tools/bench_stt_compare.py` và chuỗi STT -> intent.
3. **Giấy phép trọng số vieneu trên HuggingFace** (neuphonic/pnnbao): code vieneu 3.8.3 là Apache-2.0, nhưng giấy phép trọng số model/voice
   chưa kiểm được (cache cục bộ không có README model). Xác nhận trước khi phát hành thương mại. Server chạy không watermark
   (`perth` cài trong venv là gói khác `resemble-perth`).
4. **App server (AB)**: `deadline_at = created_at + 1 s` trong `_command_data` có vẻ sai so với hợp đồng 30–90 s (app bỏ qua); app không
   bao giờ trả `NO_ACTIVE_PLAYBACK`; `emergency_call` luôn `answered:false`. Cần quyết hợp đồng đúng.
5. **Độ trễ chặng tunnel Cloudflare**: còn ~80–175 ms sau khi đã dùng WS (edge HKG, chặng edge -> cloudflared -> origin ~150–240 ms,
   TLS 70–130 ms/kết nối). Giảm phần này là việc hạ tầng tunnel (vị trí chạy cloudflared / tuyến tới edge), chưa có thử nghiệm nào; phần WiFi
   của kính cũng chưa đo (cần log 4 mốc trên kính, khung `played`).
6. **I6 — token theo từng kính** (plan 2): hiện một token dùng chung và `device_id` do client tự khai, ai có token đều kích được lệnh trên kính
   khác. Plan 2 (gọi điện tới người thân) cần token theo kính / ràng buộc `device_id` với token. Xem `docs/superpowers/NEXT_SESSION.md`.

Chưa kiểm chứng (không chặn, nhưng cần biết): firmware kính chưa có bản cho giao thức v2 (WebSocket client trên ESP32-S3 song song I2S, đổi
framesize OV2640 lúc chạy, fps thật qua WiFi+TLS); ngưỡng căn khung OCR và luật mức hazard là bản đầu, chỉ thử bằng dữ liệu tổng hợp/một ảnh
(chưa biết tỉ lệ báo nhầm ngoài đường); Gemma UIT là điểm hỏng duy nhất (không có LLM cục bộ dự phòng, Clef chỉ phân loại); tải N=2,3 và
đứt tiếng ở N=4; log 4 mốc từ kính chưa có số.

## 5. Chạy lại

Nhanh: `./run.sh` (tự chọn GPU trống, cổng 18888, chờ sẵn sàng), `./run.sh stop`, `./run.sh log`. Lệnh tay:

```bash
# Chọn GPU còn trống (máy dùng chung 8x RTX 2080 Ti; GPU đầy thì đổi GPU, KHÔNG lùi về CPU)
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
S=<thư mục tạm>; mkdir -p $S
cd visioncare-host-demo
CUDA_VISIBLE_DEVICES=<gpu A> STORAGE_DIR=$S/storage ONNX_DEVICE=cuda nohup ~/.venvs/seevia/bin/python \
  -m uvicorn app:app --host 127.0.0.1 --port 18888 --loop uvloop --http httptools --ws-max-size 2100000 > $S/server.log 2>&1 &
# đợi "Application startup complete" (lần đầu ~3 phút dựng sẵn 113 câu TTS, sau đó ~25 s)
CUDA_VISIBLE_DEVICES=<gpu B> ~/.venvs/seevia/bin/python tools/bench_live.py --base http://127.0.0.1:18888 --runs 4 --ws
# test
CUDA_VISIBLE_DEVICES=<gpu> ~/.venvs/seevia/bin/python -m pytest -q -p no:cacheprovider
# E2E trọn luồng (docs/E2E_FULL_FLOW.md)
CUDA_VISIBLE_DEVICES=<gpu> ~/.venvs/seevia/bin/python tools/e2e_full.py --gpu <gpu khác>
```

Bench qua tên miền: thêm `--base https://api.visioncare-host.uk --resolve api.visioncare-host.uk=<IP edge từ dig @1.1.1.1>`; bench cần token
trong môi trường (`.superpowers/.../cf-bench/run_bench.py` nạp bằng Python). Tunnel trỏ về `http://localhost:18888`; chỉ bật server lúc đo
và tắt ngay (`fuser -k 18888/tcp`, đừng `pkill -f`).

Model ONNX không nằm trong git (`models/*` bị ignore): `models/hazard/yolo11n.onnx` tạo bằng `tools/export_hazard_onnx.py` (cần `ultralytics`,
chạy trong env tạm), `models/text_det/ch_PP-OCRv4_det_infer.onnx` tải từ HF `SWHL/RapidOCR` (`PP-OCRv4/`); `certs/uit-ca-bundle.pem` cần ở mọi môi trường.
Lần đầu nạp xong, đặt `HF_HUB_OFFLINE=1`.

## 6. Bẫy môi trường

- Venv `~/.venvs/seevia` (Python 3.11), `vieneu>=3.8.3`. `vieneu` kéo `onnxruntime` CPU đè `onnxruntime-gpu`: gỡ cả hai rồi
  `uv pip install --reinstall "onnxruntime-gpu[cuda,cudnn]"`. **Hỏi bạn trước khi gỡ/cài lại gói**; gói mới dùng `--no-deps` (torch ghim CUDA 13.0,
  cài thường hạ cấp 6 gói `nvidia-*`).
- Nạp `onnxruntime` TRƯỚC `sherpa_onnx` (ngược lại segfault khi TTS GPU nạp); `models/onnx_session.py` gọi `ort.preload_dlls()`, thiếu thì CUDA
  provider lặng lẽ rơi về CPU. `ONNX_GPU_ID` là chỉ số TƯƠNG ĐỐI theo `CUDA_VISIBLE_DEVICES`.
- GPU dùng chung không có cơ chế chiếm VRAM: đã gặp OOM; server dùng ~1,8 GB.
- Ghi file lớn lên `/workingspace_aiclub` (NFS) có thể bị cắt âm thầm khi quota hết: build ở thư mục tạm rồi `cp` và kiểm size.

## 7. Bản đồ code

`app.py` (endpoint v2 ở cuối file) · `config.py` (mục "Voice server v2") · `live/`: `device_session.py` (`WS /v2/session`), `ws_adapter.py`,
`protocol.py`, `session.py`, `hazard.py` · `pipeline/`: `turn.py`, `stt_stream.py`, `intent_early.py`, `intent_classifier.py`, `final_router.py`,
`pending_action.py`, `guard.py`, `cues.py`, `image_buffer.py`, `speech.py` · `lanes/`: `general.py` (A), `ocr_live.py` (B), `nav_live.py` (C),
`phone.py` (D) · `assets/cues/` (clip flash) · `tools/`: `bench_live.py`, `bench_load.py`, `e2e_full.py`, `make_cue_clips.py`.
