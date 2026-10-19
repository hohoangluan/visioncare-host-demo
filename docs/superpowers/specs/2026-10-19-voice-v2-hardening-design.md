# Voice server v2 — khắc phục hạn chế, tối ưu độ trễ và độ chính xác

Ngày: 2026-10-19. Đầu vào: `docs/HANDOFF_VOICE_V2.md` mục "Hạn chế cần giải quyết"
(A lỗi đã biết · B chưa kiểm trên thật · C hạ tầng). Nền: spec
`2026-10-19-voice-server-architecture-design.md` (gọi tắt "spec v2", số mục §x là của nó).

## 1. Ý định

Người dùng (chủ dự án) yêu cầu khắc phục **tất cả** hạn chế trong bản bàn giao, "từ
Cloudflare đến logic, độ chính xác", với hai tiêu chí, theo thứ tự:

1. **Độ trễ thấp nhất có thể** — "latency phải thấp, càng thấp càng tốt".
2. **Độ chính xác cao nhất** — "tốt nhất, chính xác nhất".

Được phép dùng `cx/gpt-6.1-sol` qua 9router (local, `http://localhost:20128/v1`, khoá
trong `SeeVia_system/.env`: `NINE_ROUTER_API_KEY`, `NINE_ROUTER_MODEL`) để **tạo tập gold** cho
việc chỉnh prompt Gemma. Mức reasoning do builder chọn.

## 2. Mục tiêu, không làm, phản mục tiêu

**Mục tiêu (đo được):**

| Chỉ số | Hiện tại | Đích |
|---|---|---|
| Intent đúng trên tập gold-test (§4) | 89,4% trên eval cũ (chưa kiểm lại nhãn) | ≥ 96%, đo trên test chưa từng dùng để chỉnh |
| Câu làn D bị kích hoạt sai (FP hành động) trên gold-test | chưa đo | 0 trên tập test; mọi FP còn lại phải qua chốt xác nhận §5 |
| Độ trễ phân loại Gemma p50 / p90 | 161 / 191 ms | không tăng quá +10 ms p50 (mục tiêu giảm) |
| Nhả nút → tiếng đầu qua Cloudflare (chat/space/OCR/tiền) | 980 / 802 / 973 / 888 ms | ≤ mức local hiện tại (747 / 652 / 806 / 535) — tức lấy lại toàn bộ phần mất do Cloudflare gom body |
| Câu bịa số liệu khi cần tra web mà không tra được | có | 0 |

**Quy tắc chung cho mọi thay đổi:** đổi gì cũng phải đo **độ trễ p50/p90 cùng điều kiện
trước/sau** (memory người dùng: "chỉ đổi khi đo ra nhanh hơn"); thay đổi chỉ vì độ chính
xác được nhận khi độ trễ không xấu đi quá ngưỡng nói ở từng mục. Một biến mỗi thí nghiệm.

**Không làm:** viết firmware ESP32 (chỉ định nghĩa giao thức + client giả lập trong
`tools/`); sửa app server `:8001`, FCM, Android; thử phần cứng P0 (§3 spec v2); đổi STT
(Zipformer giữ), Clef local (đã bỏ), LAN Gemma (đã bỏ).

**Phản mục tiêu:**
- gọi nhầm người / gọi cấp cứu nhầm / đặt xe nhầm (kể cả khi intent "đúng" theo số);
- thêm một lượt hỏi-đáp vào đường chờ bình thường để đổi lấy an toàn;
- tập gold "tự khớp chính nó" (prompt chỉnh trên đúng tập dùng để báo số; nhãn gold do
  chính Gemma sinh) — memory `uit-dsc-2026-mo-tip-tu-ca-le-la-bay`, `one-variable-per-experiment`;
- chặn kính thật vì xác thực/giới hạn đặt sai.

## 3. Bối cảnh đã biết (số đo, ràng buộc)

- Cloudflare gom đủ body `POST /v2/turn` mới chuyển (upload≈0 dù audio 2,75 s), nên
  partial STT/đoán sớm/prewarm không chạy trước lúc nhả nút. **WebSocket qua Cloudflare
  không bị gom** (làn C: khung → hazard 37–73 ms). Mỗi `/v2/image` và `/v2/turn` là một
  bắt tay TLS riêng từ kính (ESP32-S3 mbedTLS: thường vài trăm ms, chưa đo).
- Firmware v2 **chưa có** → đổi giao thức lúc này không phá kính nào; `/process` cũ phải
  tiếp tục chạy.
- STT thật kém hơn FLEURS nhiều: Zipformer WER 21,5% trên VietMed (đa vùng miền)
  (`docs/EXTERNAL_VALIDATION_DATASETS.md`). Bộ phân loại intent nhận **bản ghi STT**,
  nên phải chịu được lỗi STT; eval hiện tại là văn bản sạch.
- Gemma UIT: giới hạn 40 request đồng thời mỗi khoá; vLLM có prefix cache (đã prewarm).
  Gemma không trả độ tin cậy (`confidence=1.0` cứng trong `intent_classifier.py`).
- sol qua 9router: ~3,6–5 s/lượt, một tool call mỗi response (memory
  `agent-on-sol-9router`). Chỉ dùng **offline** (tạo/chấm gold), không bao giờ trên đường chờ.
- GPU dùng chung 8×2080 Ti: chọn GPU trống, không lùi về CPU.

## 4. Độ chính xác intent: tập gold + chỉnh prompt Gemma

### 4.1. Dựng tập gold

Nguồn câu, theo thứ tự ưu tiên:
1. `data/intent/eval.jsonl` (358) + `train.jsonl` (1075) + `suspect/rejected` — **gán lại
   nhãn** bằng sol, reasoning high, mỗi câu kèm định nghĩa nhãn + bối cảnh thiết bị; sol
   trả nhãn + `ocr_mode` + `needs_web` + tham số làn D + lý do ngắn.
2. Câu mới do sol sinh để phủ chỗ yếu: các cặp nhầm đã thấy (chat↔ocr/space/hazard/
   nav_start/music_play), câu mơ hồ, câu tắt/dừng trống không theo từng bối cảnh thiết bị,
   câu "đi tới"/"gọi" mà KHÔNG phải lệnh (vd. "hôm qua tôi gọi cho mẹ rồi"), phương ngữ
   Bắc/Trung/Nam, câu cụt do nhả nút sớm, câu ngoài phạm vi.
3. **Biến thể lỗi STT thật**: văn bản → VieNeu TTS (nhiều giọng nếu có) → trộn nhiễu
   đường phố/quạt ở vài mức SNR → Zipformer → bản ghi. Nhãn đi theo câu gốc. Đây là phần
   gần nhất với đầu vào thật khi chưa có ghi âm kính.

Đối chiếu nhãn: nhãn cũ, sol, và Gemma hiện tại. Ba bên khớp → nhận. Lệch → sol chấm lại
một lượt riêng (reasoning high, prompt "phân xử", thấy cả các nhãn ứng viên); vẫn mơ hồ →
đưa vào `data/intent/gold_review.jsonl` cho người dùng duyệt (giới hạn ≤ 60 câu), không tự
quyết. Ghi rõ nguồn từng nhãn (`label_source`).

Chia: `gold_dev` (chỉnh prompt) và `gold_test` (chỉ chạy khi chốt), tách theo **câu gốc**
(mọi biến thể STT của một câu ở cùng một phía), giữ tỉ lệ nhãn. Tính sai số chuẩn của
độ chính xác trên test và so A/B bằng **câu bất đồng** (memory
`judge-by-discordant-questions`), không bằng chênh lệch trung bình.

### 4.2. Chỉnh bộ phân loại Gemma

Các trục thử, mỗi lượt đổi một trục, đo cả đúng/sai lẫn p50/p90 trên `gold_dev`:
- định nghĩa nhãn (ranh giới chat↔space↔hazard, ocr↔chat, "đi tới" có/không điểm đến);
- ví dụ few-shot **tĩnh** đặt trong prefix (prefix cache làm phần này gần như miễn phí
  về prefill — phải đo để chắc);
- rút gọn đầu ra (khoá JSON ngắn, enum ngắn) để bớt token decode;
- **độ tin cậy thật** từ `logprobs` của token nhãn (vLLM), thay `confidence=1.0`; dùng ở §5.
- bối cảnh thiết bị đặt cuối (giữ prefix cache).

Chốt bản tốt nhất bằng một lần chạy `gold_test`. Cập nhật docstring số đo trong
`pipeline/intent_classifier.py` như lệ hiện tại.

Luật từ khoá `intent_early._RULES` cũng đo trên cùng gold (độ chính xác theo từng luật) —
luật nào sai nhiều thì sửa/bỏ; luật vẫn chỉ dùng cho đoán sớm và cho làn không có tác dụng
phụ (§5).

Tham số làn D (`phone.extract`): đo trên gold (tên người, điểm đến, bài hát) cùng cách;
chỉnh prompt trích nếu sai.

## 5. An toàn hành động làn D — không thêm độ trễ

1. **Luật từ khoá không bao giờ tự kích hoạt làn D.** Khi bộ phân loại hỏng/quá hạn:
   từ khoá chỉ được đưa câu vào làn A/B/C-thông-tin; câu khớp luật làn D thì trả cue
   `system_busy` (hoặc câu "chưa nghe rõ, bạn nói lại nhé").
2. **Cổng tin cậy**: làn D chỉ chạy khi xác suất nhãn (logprob, §4.2) ≥ ngưỡng chỉnh trên
   `gold_dev` sao cho FP hành động = 0. Dưới ngưỡng → hỏi lại đúng một câu ngắn có tên/điểm
   đến ("Gọi cho Mẹ phải không?") và chờ lượt sau (cơ chế `pending` đã có). Ca này hiếm,
   nên không thêm độ trễ ở ca thường.
3. **Đọc lại + cửa sổ huỷ bằng chính câu đọc lại**: với `contact_call`, `ride_*`,
   `emergency_call`, `music_play`, server phát ngay câu đọc lại ("Đang gọi cho Mẹ.") rồi
   mới gửi `run_action` khi câu đó phát xong (ước tính ~1 s). Bấm nút trong lúc đó
   (kính đóng kết nối / mở lượt mới) → huỷ lệnh. Tiếng đầu vẫn ra ngay như hiện nay; chỉ
   lệnh điện thoại đi trễ bằng độ dài câu đọc lại. `emergency_call`: câu "Đang gọi cấp
   cứu, bấm nút để huỷ." — đây là lựa chọn của Claude, người dùng kiểm (§10).
4. `music_stop`, `music_volume`, `nav_stop`, `alert_*` không cần đọc lại (hoàn tác được).

## 6. Độ trễ: một WebSocket phiên cho mỗi kính

Thay ba kết nối (`/v2/image`, `/v2/turn`, `/v2/live`) bằng **một** WebSocket mở sẵn
`WS /v2/session`, kính giữ nó suốt lúc bật (ping/pong ≤ 30 s để Cloudflare không cắt idle
~100 s). Lợi: audio tới server theo từng mảnh qua Cloudflare (lấy lại đoán sớm/prewarm:
ước 0,1–0,15 s), không còn bắt tay TLS mỗi lượt, ảnh và audio cùng một đường nên không
còn ca "ảnh về sau audio" do hai kết nối riêng tranh nhau.

Khung (đề xuất, builder hoàn thiện; giữ nguyên ý nghĩa của §5.3 spec v2):

| Hướng | Khung | Nội dung |
|---|---|---|
| kính → server | text `hello` | `device`, `token`, `cue_version`, `fw` |
| kính → server | text `turn_start` | `turn` id; ngay lúc bấm nút |
| kính → server | binary `0x01` | JPEG (ảnh lúc bấm nút, hoặc khung live) |
| kính → server | binary `0x03` | khối ADPCM của lượt hiện tại |
| kính → server | text `turn_end` | nhả nút |
| kính → server | text `cancel` | bấm nút khi đang phát / đang live |
| server → kính | text `reply` | `cues`, `live` (ocr\|nav\|null), các trường audio |
| server → kính | binary `0x02` | audio ADPCM trả lời |
| server → kính | text `cam`/`capture`/`cue`/`hazard`/`end` | như §5.3 spec v2 |

Yêu cầu: dùng lại nguyên `pipeline/turn.py`, `final_router`, `lanes/*`, `live/*` (đổi
nguồn body và đích audio, không viết lại logic); `POST /v2/*` và `/process` vẫn chạy;
đệm audio đầu (`V2_AUDIO_PREROLL_SECONDS`) đo lại qua Cloudflare. Kèm client giả lập
trong `tools/bench_live.py` (`--ws`) đo cùng các luồng như bảng Cloudflare trong bản bàn
giao, local và qua `api.visioncare-host.uk`.

Các tối ưu độ trễ khác, mỗi cái đo riêng, chỉ giữ cái nhanh hơn:
- câu đệm dựng sẵn khi cần tra web ("Để tôi tra cứu.") phát ngay trong lúc chờ search;
- hedge Gemma phân loại (bắn lượt thứ hai sau p90 nếu lượt đầu chưa về) — chỉ khi đo ra
  giảm p90 mà không làm tràn trần 40 request/khoá;
- `tools/make_cue_clips.py` (§15 spec v2): clip cue cho flash kính, xoá đường TTS của cue.

## 7. Sửa lỗi logic và độ chính xác khác (nhóm A)

- **Tra web**: khi `needs_web` mà không tra được → chèn
  `handlers/chat.py::_SEARCH_UNAVAILABLE_INSTRUCTION` vào system prompt làn A. Nguồn tra:
  **SerpAPI** (người dùng cấp khoá, `SERPAPI_API_KEY`) thay Google CSE trong `models/search`;
  dùng cả answer box/knowledge graph (thời tiết, tỉ số) chứ không chỉ snippet; trần thời
  gian như `SEARCH_TIMEOUT_S`. 9router **không** nằm trên đường chạy thật.
- **Trạng thái theo kính**: lịch sử chat (`handlers/chat._HISTORY`) và `device_state()`
  khoá theo device id.
- **OCR**: thêm `raw`, `specialized` vào `ocr_mode` (schema Gemma, Clef, luật từ khoá),
  ánh xạ sang `prompts.Mode`; hết trần căn khung ưu tiên `fallback_jpeg` (UXGA lúc bấm nút)
  trước khung VGA.
- **`/process`**: chuyển sang pipeline v2 (Image Buffer + `turn.run` không partial), như
  §5.4 spec v2; sau đó bỏ `models/vlm`, `pipeline/intent_local.py`, `handlers/waiting.py`
  nếu không còn ai dùng.
- **Huỷ khi kính ngắt**: đóng kết nối giữa chừng phải dừng Gemma và TTS (test).
- **Trộn âm**: định nghĩa thứ tự ưu tiên khi hazard và audio `session.outbox` đến cùng lúc
  (hazard luôn thắng, audio làn D đợi).
- Watermark VieNeu: kiểm giấy phép; nếu bắt buộc thì cài đúng gói (hỏi người dùng trước
  khi đụng venv).

## 8. Bảo mật và vận hành (nhóm C)

- Xác thực: token thiết bị `VISIONCARE_DEVICE_CLIENT_TOKEN` trên **mọi** endpoint của kính,
  kể cả `/process` (người dùng: khoá hết, firmware sẽ sửa theo). Không cấu hình token thì
  server từ chối khởi động endpoint kính (không có chế độ "chỉ localhost" vì cloudflared
  cũng vào từ localhost). Viết `docs/FIRMWARE_ENDPOINTS.md`: hướng dẫn đầy đủ cho người
  viết firmware (header, token, khung WebSocket §6, máy trạng thái, mã lỗi, ví dụ).
- Trần: ảnh ≤ 2 MB, audio ≤ 30 s mỗi lượt, khung live ≤ 300 KB; rate limit theo thiết bị.
- LLM dự phòng khi Gemma UIT hỏng: **không làm** ở vòng này (9router không được dùng trên
  đường chạy thật); UIT hỏng thì cue `system_busy` như hiện tại. Ghi rõ trong bàn giao.
- Quan sát: request/turn id xuyên suốt log; mỗi lượt ghi một dòng JSONL số đo chặng
  (`storage/metrics/turns.jsonl`); kính gửi 4 mốc (bấm, nhả, byte đầu, tiếng đầu) trong
  khung `turn_end`/`ack` để server ghi lại.
- Khởi động: `HF_HUB_OFFLINE=1` khi đã đủ file; tài liệu VRAM/GPU.
- Tài liệu: Dockerfile, `start-demo.ps1`, README, `docs/KIEN_TRUC_SERVER.md`, bản bàn giao.
- Test: 2 test ffmpeg tự skip khi thiếu cờ `-block_size`; test cho mọi mục trên; bench tải
  đồng thời (N kính giả lập) đo p50/p90 và số request UIT mỗi lượt.

## 9. Không làm được nếu thiếu người dùng (ghi lại, không chặn phần còn lại)

| Cần | Để làm gì |
|---|---|
| Khoá SerpAPI (người dùng sẽ cấp) | tra web thật |
| Bật app server `:8001` (người dùng sẽ bật) | đo làn D thật, pending-slot, callback |
| Ghi âm (`request*.wav`) + ảnh OV2640 từ kính | đánh giá STT/intent/OCR trên dữ liệu thật |
| Người dùng có đi gậy không | quyết hazard có cần vật ngang đầu/mặt đất |
| Firmware theo §6 | đo phần WiFi, xác nhận lợi ích TLS |

Hazard ngoài đường (tỉ lệ báo nhầm): đo được phần nào trên video đường phố công khai
(dashcam/đi bộ) nếu tìm được nguồn phù hợp giấy phép; không có thì để lại.

## 10. Lựa chọn do Claude quyết (người dùng kiểm khi đọc)

Chốt sau vòng đọc của builder:

- **Định nghĩa "≥ 96%"**: đo trên `gold_test` gộp câu sạch + biến thể STT ở SNR vừa
  (≥ 10 dB); SNR thấp hơn báo riêng, không tính vào đích. Báo thêm theo từng câu gốc
  (đúng ở mọi biến thể). Câu đang chờ người dùng duyệt nằm ngoài `gold_test` cho tới khi
  có nhãn; test vẫn đóng băng được ngay. Không đạt 96% thì vẫn giao bản tốt nhất nếu nó
  hơn bản hiện tại ở câu bất đồng, và báo con số thật — không dừng §5–§8.
- **FP hành động** = lệnh điện thoại được GỬI mà sai intent HOẶC sai tham số (gọi nhầm
  người). Câu bị cổng §5.2 chặn và hỏi lại không tính FP (tính vào "tỉ lệ hỏi lại", báo
  riêng). Ngưỡng chỉnh trên intent + tham số cùng lúc.
- **Làn D khi nhãn không đến từ Gemma** (Clef dự phòng / LLM dự phòng): không có
  logprob đã hiệu chuẩn → luôn hỏi lại kèm tham số ("Gọi cho Mẹ phải không?"). Ca hiếm,
  chỉ xảy ra khi UIT hỏng.
- **Live + lượt mới trên cùng socket**: giữ hành vi hiện tại — bấm nút khi đang live thì
  đóng live (đang chỉ đường thì bấm = dừng, như bypass cũ). Nhưng khung ảnh vẫn gắn loại
  luồng (`0x01` ảnh lượt, `0x04` khung live) để sau này chạy song song không phải đổi
  giao thức firmware.

- Một WebSocket phiên duy nhất thay vì nhiều POST nhỏ: đã thấy WS qua Cloudflare không
  bị gom; bỏ được TLS mỗi lượt.
- Cửa sổ huỷ = thời gian phát câu đọc lại (~1 s), không thêm thời gian chờ riêng; áp cả
  cho cấp cứu.
- Cổng tin cậy bằng logprob nhãn của Gemma; ngưỡng chọn để FP hành động trên dev = 0.
- sol reasoning high cho gán nhãn/phân xử, low cho sinh câu hàng loạt.
- Ngưỡng độ trễ cho thay đổi prompt: không quá +10 ms p50.
- Thứ tự làm: §4 (gold + prompt) → §5 → §6 → §7 → §8.
- Git (người dùng đồng ý): nhánh mới `voice-v2-hardening`; commit đầu = toàn bộ phần chưa
  commit hiện có (làm mốc đo), sau đó mỗi thay đổi một commit. Không push.
