# Voice server v2 hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sửa mọi hạn chế trong `docs/HANDOFF_VOICE_V2.md`: độ trễ thấp nhất (một WebSocket phiên qua Cloudflare), intent chính xác nhất (tập gold do sol 6.1 dựng + chỉnh prompt Gemma), làn D an toàn không thêm trễ, bảo mật, và chạy được trọn luồng kính → server kính → app server → "điện thoại" giả lập → callback.

**Architecture:** Giữ nguyên lõi v2 (`pipeline/turn.py`, `final_router`, `lanes/*`, `live/*`); thêm công cụ dữ liệu/đo (`tools/intent_gold/`, `tools/eval_intent.py`), một đầu vào mới `WS /v2/session` dùng lại lõi, lớp xác thực/giới hạn, và một transport `webhook` + điện thoại giả lập ở app server.

**Tech Stack:** Python 3.11, FastAPI/Starlette, httpx, websockets 16, numpy/scipy/soundfile, sherpa-onnx Zipformer, VieNeu TTS, Gemma 4 qua vLLM (UIT), 9router (`cx/gpt-6.1-sol`, chỉ offline), app server FastAPI + PostgreSQL (docker).

**Spec:** `docs/superpowers/specs/2026-10-19-voice-v2-hardening-design.md` (đọc kèm `docs/HANDOFF_VOICE_V2.md` và spec v2 `docs/superpowers/specs/2026-10-19-voice-server-architecture-design.md`).

## CHẾ ĐỘ NHANH (người dùng, 2026-10-19 — ĐÈ lên mọi chỗ khác trong plan này và plan 2)

> "mẫu vừa vừa thôi, đủ sài thôi 200-300 mẫu" · "sử dụng thêm vad cho tối ưu khâu stt" ·
> "dùng thời gian tối thiểu cho flow đúng ... không cần kỹ test quá nhiều" ·
> "flow đúng và tối ưu nhanh nhất về latency"

- **Ưu tiên duy nhất:** luồng chạy đúng đầu-cuối + độ trễ thấp nhất. Mọi thứ khác cắt.
- **Tập gold:** 200–300 dòng TỔNG (dev+test, gồm biến thể STT một mức SNR 10 dB). Chỉ số đích
  "≥ 96%" giữ làm hướng, không chặn tiến độ; Task 4 tối đa 3 vòng chỉnh prompt.
- **Test:** mỗi task chỉ 1–3 test cho hành vi chính (luồng đúng + một ca an toàn quan trọng),
  bỏ các test phụ liệt kê trong task. Không làm yếu test cũ đang có.
- **Review:** chỉ review (sonnet) các task rủi ro: 6 (an toàn làn D), 9 (xác thực), 10 (WS
  phiên), 15 (luồng đầy đủ); plan 2: C2, C5. Task khác: implementer tự kiểm + chạy toàn bộ test
  rồi commit, controller xem nhanh `git diff --stat`. Một review cuối toàn nhánh.
- **Cắt / thu nhỏ:** Task 14 chỉ giữ turn id trong log + `turns.jsonl` (cue clips làm nếu còn
  thời gian); Task 16 chỉ chạy N=1 và N=4; Task 13 chỉ phần huỷ khi kính ngắt; Task 17 chỉ
  `FIRMWARE_ENDPOINTS.md`, test ffmpeg skip, bàn giao (Dockerfile/README cập nhật tối thiểu).
- **Thêm Task 2b (VAD cho STT)** ngay sau Task 2 — xem dưới.

### Task 2b: VAD (Silero qua sherpa-onnx) cho đường STT

**Files:** Create `VH/pipeline/vad.py`; Modify `VH/pipeline/stt_stream.py`, `VH/pipeline/turn.py`, `VH/config.py`; Test `VH/tests/test_v2_units.py`.

**Interfaces / hành vi:**
- Model: `silero_vad.onnx` của sherpa-onnx (tải file model vào `VH/models/vad/`, KHÔNG cài gói; `sherpa_onnx.VoiceActivityDetector`/`VadModelConfig` có sẵn trong venv — kiểm trước, thiếu thì BLOCKED). CPU là đúng ở đây (model ~2 MB, < 1 ms/khung) — không vi phạm luật GPU vì đây không phải lùi từ GPU.
- `vad.Segmenter` chạy trên PCM 16 kHz khi audio tới: biết `speech_started`, `speech_ended_at` (im lặng ≥ `VAD_END_SILENCE_S`, mặc định 0,35 s), và đoạn có tiếng.
- Dùng cho độ trễ: (1) partial STT chỉ chạy khi có tiếng mới; (2) bản ghi cuối chỉ giải đoạn có tiếng (cắt im lặng đầu/cuối — giải nhanh hơn, bớt chữ rác do nhiễu); (3) **chốt sớm**: khi VAD báo hết câu mà nút còn giữ, chạy luôn STT cuối + intent + chạy trước làn A/D (không tác dụng phụ) trên đoạn đó; lúc nhả nút nếu không có tiếng mới thì dùng thẳng kết quả → bỏ `final_stt` + `intent` khỏi đường chờ; (4) cả lượt không có tiếng → `no_speech` ngay khi nhả nút, không gọi Gemma.
- Đo trước/sau trên `tools/bench_live.py` (cột `final_stt`, `intent`, nhả nút → tiếng đầu) và WER/intent trên các biến thể STT của tập gold: chỉ giữ khi nhanh hơn và không làm tụt độ chính xác (memory người dùng: chỉ đổi khi đo ra nhanh hơn).
- [ ] Test: `test_vad_trims_silence`, `test_early_final_reused_on_release`, `test_no_speech_skips_classifier`. Cài → PASS → đo → Commit (ghi số đo trong commit message).

## Global Constraints

- Repo server kính: `SeeVia_system/visioncare-host-demo` (gọi tắt `VH`), nhánh `voice-v2-hardening`. App server: `SeeVia_system/app-demo-backend/server` (gọi tắt `AB`, repo git riêng — tạo nhánh `voice-v2-hardening` ở đó trước khi sửa). Mỗi task một commit; KHÔNG push. Cuối commit message thêm dòng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python của VH: `~/.venvs/seevia/bin/python`. **Không cài/gỡ gói** trong venv này (torch ghim CUDA 13; cài thường sẽ hạ 6 gói `nvidia-*`). Gói cần có sẵn: websockets, httpx, numpy, scipy, soundfile, sherpa_onnx, vieneu, pytest. Thiếu gì → dừng, báo lại.
- Test VH: `cd VH && CUDA_VISIBLE_DEVICES=<gpu trống> ~/.venvs/seevia/bin/python -m pytest -q -p no:cacheprovider -W ignore::DeprecationWarning tests/`. Hiện chỉ đúng 2 test hỏng (`tests/test_adpcm.py::*ffmpeg*bit_for_bit`, ffmpeg 4.2 thiếu cờ `-block_size`) — Task 15 sửa cho chúng tự skip. Không được làm hỏng test khác, không làm yếu assertion.
- GPU dùng chung 8×2080 Ti: chọn GPU trống bằng `nvidia-smi --query-gpu=index,memory.used --format=csv,noheader`; OOM thì đổi GPU, **không lùi về CPU**.
- Không dùng `pkill -f` theo mẫu có số cổng (khớp cả shell); tắt server bằng `fuser -k <port>/tcp`.
- NFS `/workingspace_aiclub` từng bị quota cắt file âm thầm: sau khi ghi file > 64 KB, kiểm tra kích thước (`stat -c %s`).
- 9router (`http://localhost:20128/v1`, khoá `NINE_ROUTER_API_KEY` và model `NINE_ROUTER_MODEL=cx/gpt-6.1-sol` trong `SeeVia_system/.env`) **chỉ dùng trong `tools/`**, không bao giờ trong code runtime của server. Không in khoá ra log.
- Mọi thay đổi chạm đường chờ phải kèm số đo p50/p90 trước/sau cùng điều kiện, ghi trong commit message hoặc docstring như lệ hiện tại (`pipeline/intent_classifier.py`). Thay đổi prompt Gemma: không tăng p50 quá +10 ms.
- Code mới theo phong cách hiện có: docstring/chú thích tiếng Việt, giải thích "vì sao", số đo kèm ngày.
- Bí mật: không đưa token/khoá vào code, fixture, log, commit. Biến mới thêm vào `config.py` (mục "Voice server v2") và `.env.example` với giá trị trống.

## Review Focus

1. **Kính ngắt kết nối giữa lượt** (WiFi rớt, bấm nút lần nữa): lệnh làn D đang chờ đọc xong phải bị huỷ, Gemma/TTS dừng, không rò task. → test trong Task 6 (huỷ lệnh khi có lượt mới) và Task 13 (đóng stream dừng generator).
2. **Bản ghi STT rỗng/rác hoặc chỉ có tạp âm**: không được rơi vào làn D; phải ra `no_speech` hoặc làn A. → test trong Task 6 (`test_keyword_only_never_triggers_lane_d`) và Task 4 (gold có câu rác).
3. **Hai kính cùng lúc**: không lẫn lịch sử chat, trạng thái nhạc/chỉ đường, pending slot, lệnh chờ. → test trong Task 8 (`test_history_isolated_per_device`, `test_device_state_isolated`).
4. **Token sai/thiếu, body khổng lồ, gửi dồn dập** qua tunnel công khai: 401/413/429 đúng, server không tốn RAM. → test trong Task 9.
5. **WebSocket phiên bị Cloudflare cắt idle / mở lại giữa chừng**: phiên mới thay phiên cũ của cùng thiết bị, lượt đang dở bị huỷ sạch. → test trong Task 10 (`test_new_session_replaces_old`).

---

## Phần I — Độ chính xác intent

### Task 1: Client sol cho công cụ offline + dựng tập gold

**Files:**
- Create: `VH/tools/intent_gold/__init__.py`, `VH/tools/intent_gold/sol.py`, `VH/tools/intent_gold/build.py`, `VH/tools/intent_gold/stt_variants.py`
- Create (dữ liệu, sinh ra bằng script): `VH/data/intent/gold_dev.jsonl`, `VH/data/intent/gold_test.jsonl`, `VH/data/intent/gold_review.jsonl`, `VH/data/intent/gold_build_log.json`
- Test: `VH/tests/test_intent_gold.py`

**Interfaces:**
- Produces:
  - `sol.ask_json(system: str, user: str, schema: dict, effort: str = "high", timeout: float = 120) -> dict` — đọc `NINE_ROUTER_API_KEY/NINE_ROUTER_API_URL/NINE_ROUTER_MODEL` từ `SeeVia_system/.env` (đường dẫn tương đối từ `VH/..`), gọi `/chat/completions` với `reasoning_effort`, `response_format` json_schema; thử lại 4 lần, backoff 4 s; trả dict đã parse. sol trả một tool call/response và không kèm text — dùng `response_format`, KHÔNG dùng tools.
  - `sol.ask_many(jobs: list[tuple[str,str,dict]], effort: str, concurrency: int = 6) -> list[dict | None]`.
  - Dòng gold (mọi file `gold_*.jsonl`), khoá cố định:
    `{"id": str, "group": str, "text": str, "source_text": str, "variant": "clean"|"stt_snr20"|"stt_snr10"|"stt_snr5", "device": {"music_playing": bool, "navigating": bool, "alerting": bool, "ride_quote_pending": bool}, "label": <17 nhãn của models.clef.LABELS>, "ocr_mode": "read"|"summarize"|"reread"|"raw"|"specialized", "needs_web": bool, "params": {"contact_name"?: str, "destination"?: str, "song"?: str}, "label_source": "agree"|"sol_adjudicated"|"user", "origin": "eval"|"train"|"suspect"|"rejected"|"sol_gen"}`
    `group` = id của câu gốc; mọi biến thể STT dùng chung `group`.

- [ ] **Step 1: Viết test** `tests/test_intent_gold.py` (không gọi mạng, monkeypatch `sol.ask_json`):
  - `test_split_keeps_groups_together`: 40 dòng, 10 group × 4 biến thể → không group nào có mặt ở cả dev và test.
  - `test_split_stratified`: mỗi nhãn có ≥ 2 group thì có mặt ở cả hai phía; tỉ lệ test ≈ 0,4 (±0,1).
  - `test_consensus_rules`: cũ=sol=gemma → `label_source="agree"`; lệch, phân xử ra nhãn rõ → `"sol_adjudicated"`; phân xử trả `"uncertain": true` → vào review, không vào dev/test.
  - `test_review_capped_at_60`: 100 câu bất định → `gold_review.jsonl` có ≤ 60 dòng (ưu tiên câu làn D), phần còn lại bị loại và đếm trong log.
- [ ] **Step 2:** chạy test, thấy FAIL (module chưa có).
- [ ] **Step 3: Cài `build.py`** với các bước con chạy được riêng (`--stage relabel|generate|variants|adjudicate|split|all`), mỗi bước ghi file trung gian vào `VH/data/intent/gold_work/` để chạy lại không tốn quota:
  1. `relabel`: mọi câu từ `eval/train/suspect/rejected` (bỏ trùng theo văn bản chuẩn hoá) → sol (effort `high`) với system prompt = định nghĩa 17 nhãn (`models.clef.LABELS`) + định nghĩa `ocr_mode` (thêm `raw` "đọc nguyên văn, không dịch/chỉnh", `specialized` "văn bản chuyên ngành: thuốc, hợp đồng, kỹ thuật") + `needs_web` + tham số làn D + bối cảnh thiết bị. Câu tắt/dừng trống không ("tắt đi", "dừng lại") nhân thành 3 bản theo bối cảnh: đang phát nhạc / đang chỉ đường / đang bật cảnh báo.
  2. `generate`: sol (effort `low`) sinh ~600 câu mới, mỗi lô 30 câu theo một "ô" cố định: các cặp hay nhầm (chat↔ocr, chat↔space, chat↔hazard, chat↔nav_start, chat↔music_play), câu có "gọi"/"đi tới"/"đọc" mà KHÔNG phải lệnh ("hôm qua tôi gọi cho mẹ rồi"), phương ngữ Bắc/Trung/Nam, câu cụt do nhả nút sớm, câu ngoài phạm vi/vô nghĩa, câu chêm từ đệm ("ờ", "à mà"), câu chat cần tra web (thời tiết, tỉ số, giá vàng). Mỗi câu kèm nhãn đầy đủ. Sau đó đưa qua `relabel` một lần nữa (sol effort `high`) — nhãn sinh và nhãn chấm phải khớp, không khớp thì đi phân xử.
  3. `variants` (gọi `stt_variants.py`): câu sạch → VieNeu TTS (`pipeline.tts`, GPU) → trộn nhiễu ở SNR 20/10/5 dB → Zipformer (`pipeline.stt`) → bản ghi. Nhiễu tổng hợp: pink noise + "babble" (cộng 3 câu TTS khác, mỗi câu −12 dB) + ù tần thấp; seed cố định. Bỏ biến thể có bản ghi rỗng nhưng ghi số lượng.
  4. `adjudicate`: chạy Gemma hiện tại (`pipeline.intent_classifier.classify`) trên câu sạch; nếu nhãn cũ (nếu có), sol, Gemma khớp → `agree`; lệch → sol (effort `high`) lượt "phân xử" thấy câu, bối cảnh, các nhãn ứng viên và lý do; schema có `{"label", "ocr_mode", "needs_web", "params", "uncertain": bool, "reason"}`.
  5. `split`: seed 2026; tách theo `group`, phân tầng theo nhãn, tỉ lệ test 0,4. Câu review ra `gold_review.jsonl` (≤ 60, ưu tiên làn D).
  `gold_build_log.json`: số câu mỗi nguồn/bước, số lệch, số bị loại, số lượt sol, thời gian.
- [ ] **Step 4:** chạy test, PASS.
- [ ] **Step 5: Chạy thật** `cd VH && CUDA_VISIBLE_DEVICES=<gpu> ~/.venvs/seevia/bin/python -m tools.intent_gold.build --stage all` (chạy nền; ước 30–60 phút). Kỳ vọng: `gold_dev` + `gold_test` ≥ 3.000 dòng gộp biến thể, mỗi nhãn ≥ 20 group; kiểm tra `wc -l` và `stat -c %s`.
- [ ] **Step 6: Commit** code + 4 file dữ liệu (không commit `gold_work/`, thêm vào `.gitignore`).

### Task 2: Bộ đo intent `tools/eval_intent.py`

**Files:**
- Create: `VH/tools/eval_intent.py`
- Test: `VH/tests/test_eval_intent.py`

**Interfaces:**
- Consumes: dòng gold (Task 1); `pipeline.intent_classifier.classify(text, device) -> ClefResult | None`; `pipeline.intent_early.keyword_rule(text)`; `lanes.phone.extract(intent, text) -> dict`.
- Produces: CLI `python -m tools.eval_intent --gold data/intent/gold_dev.jsonl [--backend gemma|clef|keyword] [--params] [--out results/<name>.jsonl] [--baseline results/<other>.jsonl] [--concurrency 8] [--min-snr 10]`. Mỗi dòng kết quả: `{"id","group","variant","gold","pred","ocr_mode_pred","needs_web_pred","confidence","seconds","params_pred","action_fp": bool}`. Hàm thuần dùng lại được: `summarize(rows: list[dict], min_snr: int = 10) -> dict` trả `{"acc","acc_by_variant","acc_by_group_all_variants","p50_ms","p90_ms","confusion": {gold: {pred: n}},"action_fp","action_fp_rows","ask_rate"}`; `discordant(a: list[dict], b: list[dict]) -> {"a_only": n, "b_only": n, "p_value": float}` (McNemar chính xác, nhị thức hai phía).
  - `action_fp` = pred thuộc làn D (`intent_early.LANE[pred]=="D"`) VÀ (pred ≠ gold HOẶC tham số trích sai). Tham số đúng khi so sau chuẩn hoá (thường hoá, bỏ dấu câu, `phone._clean`) bằng nhau hoặc một bên chứa bên kia.
  - Khi có ngưỡng `--gate <p>`: câu làn D có `confidence < p` coi là "hỏi lại" (không phải FP, tính vào `ask_rate`).

- [ ] **Step 1: Test** `test_summarize_counts`, `test_action_fp_wrong_param` (gold contact_call "mẹ", pred contact_call "mẹ vợ"… → so chứa nhau thì đúng; "Nam" vs "Lan" → FP), `test_gate_moves_fp_to_ask`, `test_discordant_mcnemar` (a_only=10, b_only=2 → p≈0,039), `test_min_snr_excludes_snr5`.
- [ ] **Step 2:** FAIL. **Step 3:** cài; gọi mạng song song bằng `asyncio.Semaphore(concurrency)`; in bảng tóm tắt + top 15 cặp nhầm. **Step 4:** PASS.
- [ ] **Step 5: Đo mốc** `--backend gemma --params` trên `gold_dev` → `results/baseline_gemma_dev.jsonl` (thư mục `VH/results/` vào `.gitignore`, nhưng commit bản tóm tắt `docs/benchmarks/INTENT_GOLD.md` gồm bảng acc/p50/p90/FP cho gemma, clef, keyword).
- [ ] **Step 6: Commit.**

### Task 3: Độ tin cậy thật từ logprobs của Gemma

**Files:**
- Modify: `VH/models/llm/client.py` (thêm `complete_raw`), `VH/pipeline/intent_classifier.py`
- Test: `VH/tests/test_v2_units.py` (thêm)

**Interfaces:**
- Produces: `llm.complete_raw(messages, max_tokens=None, **extra) -> dict` (trả nguyên `choices[0]`, gồm `logprobs` nếu có); `llm.generate_json(prompt, schema, max_tokens=120, logprobs: bool = False) -> dict` — khi `logprobs=True` dict trả về có thêm khoá `"_label_prob": float | None`. `ClefResult.confidence` của đường Gemma = xác suất nhãn (∏ exp(logprob) các token tạo nên giá trị của trường `intent`), `None` từ server → giữ 1.0 và log warning MỘT lần. Thêm `ClefResult.source: str = "gemma"|"clef"` (Clef đặt `"clef"`).
- [ ] **Step 1: Kiểm UIT có trả logprobs với structured output không**: một lệnh curl/python tới UIT (`config.LLM_BASE_URLS[0]`, CA bundle `certs/uit-ca-bundle.pem`) với `logprobs: true, top_logprobs: 1`. Ghi kết quả vào docstring. Nếu không hỗ trợ → báo lại ngay (BLOCKED), không tự đổi hướng.
- [ ] **Step 2: Test** `test_label_prob_from_logprobs` (fake response: token `{"`, `intent`, `":"`, `music`, `_play`, `"` với logprob cho trước → prob = exp(lp(music)+lp(_play))), `test_label_prob_missing_logprobs_is_one`, `test_clef_result_source`.
- [ ] **Step 3:** cài. Ghép token theo offset ký tự: dò vị trí giá trị `intent` trong chuỗi content, cộng logprob các token chồng lên đoạn đó. **Step 4:** PASS + đo p50/p90 bằng `tools/eval_intent.py` trên 200 câu `gold_dev` trước/sau (logprobs không được làm chậm quá +10 ms).
- [ ] **Step 5: Commit.**

### Task 4: Chỉnh prompt bộ phân loại + luật từ khoá + prompt trích tham số

Task thực nghiệm (không TDD): mỗi vòng đổi MỘT trục, chạy `tools/eval_intent.py` trên `gold_dev`, so với vòng tốt nhất trước bằng `discordant` và p50/p90.

**Files:**
- Modify: `VH/pipeline/intent_classifier.py` (`_PREFIX`, `_SCHEMA`, có thể `_context`), `VH/models/clef/client.py` (`LABELS` mô tả nhãn — dùng chung cho Clef; đổi mô tả thì đo cả Clef), `VH/pipeline/intent_early.py` (`_RULES`), `VH/lanes/phone.py` (`_EXTRACT_PROMPT`, `_SLOT_DESC`)
- Create: `VH/docs/benchmarks/INTENT_GOLD.md` (cập nhật từ Task 2: bảng từng vòng)

- [ ] **Step 1:** Trục lần lượt: (a) mô tả nhãn — ranh giới chat↔space↔hazard, ocr↔chat, nav_start cần điểm đến, "gọi/đi tới" không phải lệnh → chat; (b) 1–2 ví dụ few-shot tĩnh mỗi nhãn hay nhầm, đặt trong `_PREFIX`; (c) rút gọn đầu ra (khoá JSON ngắn như `"i"`, `"m"`, `"w"`; ánh xạ ngược trong `_gemma`) — chỉ giữ nếu p50 giảm; (d) thêm `raw`/`specialized` vào enum `ocr_mode` (Task 11 dùng). Ví dụ few-shot lấy từ `train`/`sol_gen` của dev, KHÔNG lấy câu thuộc `gold_test`.
- [ ] **Step 2:** Luật từ khoá: đo độ chính xác từng luật trên gold (`--backend keyword`, thêm thống kê theo luật). Luật có precision < 90% thì sửa hoặc bỏ. Luật vẫn chỉ phục vụ đoán sớm + đường dự phòng (Task 6 cấm làn D).
- [ ] **Step 3:** Prompt trích tham số: đo `--params` trên câu làn D của dev; sửa prompt nếu sai > 3%.
- [ ] **Step 4: Chọn ngưỡng cổng** `ACTION_MIN_CONFIDENCE`: nhỏ nhất sao cho `action_fp = 0` trên dev; ghi `ask_rate` tương ứng.
- [ ] **Step 4b: Hedge (đo):** trong `EarlyIntent._hedged`/`intent_classifier.classify`, bắn lượt Gemma thứ hai nếu lượt đầu chưa về sau `INTENT_HEDGE_AFTER_S` (mặc định = p90 đo ở Task 2). Giữ chỉ khi p90 giảm rõ trên 200 câu dev và số request/lượt tăng < 10%; không thì để cờ tắt (`INTENT_HEDGE_AFTER_S=0`).
- [ ] **Step 5: Chạy `gold_test` MỘT lần** với bản chốt + ngưỡng chốt. Ghi vào `INTENT_GOLD.md`: acc (gộp SNR ≥ 10), acc theo biến thể, acc theo group, p50/p90, action_fp, ask_rate, so với mốc bằng McNemar. Cập nhật docstring số đo đầu `pipeline/intent_classifier.py`.
- [ ] **Step 6: Commit** (thông điệp ghi acc dev/test, p50/p90 trước/sau).

## Phần II — An toàn làn D

### Task 5: Đăng ký lệnh chờ theo thiết bị (`pipeline/pending_action.py`)

**Files:**
- Create: `VH/pipeline/pending_action.py`
- Test: `VH/tests/test_v2_units.py`

**Interfaces:**
- Produces:
  - `schedule(device: str, delay_s: float, fn: Callable[[], None], label: str) -> PendingAction` — chạy `fn` trong thread sau `delay_s` nếu chưa bị huỷ; mỗi thiết bị tối đa một lệnh chờ (lệnh mới huỷ lệnh cũ).
  - `cancel(device: str, reason: str) -> bool` — True nếu có lệnh bị huỷ; log `làn D huỷ <label>: <reason>`.
  - `PendingAction.fired: threading.Event`, `.cancelled: threading.Event`.
  - `readback_delay(text: str) -> float` = `tts.speaking_seconds(text) + config.V2_AUDIO_PREROLL_SECONDS + config.ACTION_READBACK_MARGIN_S` (mới, mặc định `0.15`).
- [ ] **Step 1: Test** `test_schedule_fires_after_delay`, `test_cancel_before_fire`, `test_new_schedule_replaces_old`, `test_cancel_after_fire_returns_false`, `test_devices_independent`.
- [ ] **Step 2–4:** FAIL → cài (`threading.Timer` hoặc một thread nền với `Event.wait`) → PASS.
- [ ] **Step 5: Commit.**

### Task 6: Cổng an toàn làn D trong router

**Files:**
- Modify: `VH/pipeline/intent_early.py` (`EarlyIntent.decide`), `VH/pipeline/final_router.py` (`_lane_d`, `_lane_c` nhánh `nav_start`, `route`), `VH/lanes/phone.py`, `VH/pipeline/cues.py`, `VH/pipeline/turn.py`, `VH/app.py` (`turn_lane`), `VH/config.py`
- Test: `VH/tests/test_v2_units.py`, `VH/tests/test_v2_api.py`

**Interfaces:**
- Consumes: `ClefResult.confidence/source` (Task 3), `pending_action.schedule/cancel/readback_delay` (Task 5), `ACTION_MIN_CONFIDENCE` (Task 4; mặc định trong `config.py` = giá trị Task 4 chốt).
- Produces:
  - `Decision.source` có thêm giá trị `"keyword-blocked"`; `Decision.backend: str` (`"gemma"|"clef"|""`).
  - `phone.CONFIRM_INTENTS = {"contact_call", "emergency_call", "ride_quote", "ride_confirm", "music_play"}` (đọc lại + cửa sổ huỷ); `nav_start` cũng đọc lại điểm đến nhưng cảnh báo làn C bật ngay (không chờ).
  - `phone.readback(intent: str, params: dict) -> str`, câu cố định: contact_call `"Đang gọi cho {contact_name}."`; emergency_call `"Đang gọi người thân khẩn cấp, bấm nút để huỷ."` (khẩn cấp = gọi người thân đã cài trong app, không phải 115); ride_quote `"Đang tìm xe đi {destination}."`; ride_confirm `"Đang xác nhận chuyến xe."` / `"Đang huỷ chuyến xe."`; music_play `"Đang mở {song}."` (thiếu song: `"Đang mở nhạc."`); nav_start `"Đang mở chỉ đường tới {destination}."`.
  - `phone.ask_confirm(intent, params) -> str`: `"Gọi cho {contact_name} phải không?"`, `"Gọi người thân khẩn cấp phải không?"`, `"Đặt xe đi {destination} phải không?"`, `"Mở {song} phải không?"`, `"Xác nhận chuyến xe phải không?"`, `"Chỉ đường tới {destination} phải không?"`. Lưu `phone.set_pending_confirm(device, intent, params)`; lượt sau: câu khớp `^(đúng|phải|ừ|ừm|có|ok|đồng ý|gọi đi|được)\b` → chạy (vẫn đọc lại + cửa sổ huỷ); khớp `không|thôi|huỷ|hủy|sai` → câu `"Đã huỷ."`; khác → bỏ pending, xử lý câu như lượt mới. TTL 30 s.
- Hành vi:
  - `decide`: bộ phân loại hỏng/quá hạn và luật từ khoá ra nhãn làn D → `Decision("", source="keyword-blocked")` → router trả cue `system_busy` (cue có sẵn) — KHÔNG chạy làn D. Luật ra làn A/B/C giữ như cũ.
  - `_lane_d` / nhánh `nav_start`: nếu `d.backend != "gemma"` hoặc `d.confidence < ACTION_MIN_CONFIDENCE` → hỏi lại (`ask_confirm`). Ngược lại: `Reply(speech=[readback])` ngay, và `pending_action.schedule(device, readback_delay(readback), run, label=intent)` với `run` = gọi `phone.run_background(...)` (đầu ra kết quả: Task 10 đọc qua socket phiên; với POST thì giữ cách hiện có — `speech()` sau readback trong cùng response là KHÔNG được vì lệnh chưa chạy; dùng `run_background(..., deliver=None)` và để kết quả đọc ở lượt sau / qua live outbox như `nav_start` hiện nay). Ngoại lệ `music_stop`, `music_volume`, `nav_stop`, `alert_*`: chạy ngay như cũ.
  - `turn_lane` (POST) và mọi lượt mới của cùng thiết bị: gọi `pending_action.cancel(device, "lượt mới")` TRƯỚC khi xử lý. Bypass "đang phát nhạc/chỉ đường" giữ nguyên.
- [ ] **Step 1: Test** `test_keyword_only_never_triggers_lane_d` (classifier trả None, câu "gọi cho mẹ" → không có lệnh nào được schedule, cue `system_busy`), `test_keyword_still_routes_lane_a_when_model_down` ("trước mặt có gì" → space), `test_low_confidence_asks_back`, `test_clef_backend_asks_back`, `test_confirmed_yes_runs_with_readback`, `test_confirmed_no_cancels`, `test_readback_then_action_fires_after_delay` (fake `run_background`, delay rút ngắn qua `ACTION_READBACK_MARGIN_S` âm/monkeypatch), `test_new_turn_cancels_pending_action` (API: POST turn "gọi cho mẹ" rồi POST turn mới ngay → fake app server không nhận lệnh), `test_rubbish_transcript_no_action` (bản ghi "ờ ờ" → không làn D).
- [ ] **Step 2–4:** FAIL → cài → PASS; chạy toàn bộ `tests/`.
- [ ] **Step 5: Commit.**

## Phần III — Logic làn A/B, trạng thái theo thiết bị

### Task 7: Tra web bằng SerpAPI + câu cảnh báo khi không tra được + câu đệm

**Files:**
- Modify: `VH/models/search/client.py` (thay Google CSE bằng SerpAPI), `VH/models/search/__init__.py`, `VH/lanes/general.py`, `VH/pipeline/final_router.py` (`_lane_a`), `VH/pipeline/cues.py` (cue `searching` nếu đo ra có lợi), `VH/config.py`, `VH/.env.example`
- Test: `VH/tests/test_v2_units.py`

**Interfaces:**
- Produces: `search.available() -> bool` (= có `SERPAPI_API_KEY`); `search.search(query: str, num: int = 5) -> list[dict] | None` giữ nguyên chữ ký, mỗi dict `{"title", "snippet"}`; ưu tiên đưa `answer_box` (thời tiết, tỉ số, tỷ giá) và `knowledge_graph` thành dòng đầu, rồi `organic_results`. Gọi `https://serpapi.com/search.json` với `engine=google`, `hl=vi`, `gl=vn`, `google_domain=google.com.vn`, `api_key`, trần `SEARCH_TIMEOUT_S`. Lỗi/hết giờ → `None`.
  - `general.messages(..., search: list[dict] | None, search_failed: bool = False)`: `search_failed=True` → chèn `handlers.chat._SEARCH_UNAVAILABLE_INSTRUCTION` vào system prompt.
  - `_lane_a`: `needs_web` và (`not search.available()` hoặc `search.search` trả `None`) → `search_failed=True`; không dùng câu trả lời chạy trước (speculation) trong ca này.
- [ ] **Step 1: Test** `test_needs_web_without_key_injects_unavailable`, `test_search_none_injects_unavailable`, `test_serpapi_answer_box_first` (fake JSON SerpAPI), `test_speculation_discarded_when_search_failed`.
- [ ] **Step 2–4:** FAIL → cài → PASS.
- [ ] **Step 5: Câu đệm (đo):** khi `needs_web` và có khoá: thử phát câu dựng sẵn `"Để tôi tra cứu."` (thêm vào bảng câu dựng sẵn của `pipeline/phrases.py`/cue `searching`) trong lúc chờ SerpAPI. Đo trên 10 câu thời tiết/tin tức bằng `tools/bench_live.py` (khi có khoá; chưa có khoá → để cờ `SEARCH_FILLER=1` mặc định bật, ghi "chưa đo" trong bàn giao).
- [ ] **Step 6: Commit.**

### Task 8: Lịch sử chat và trạng thái thiết bị theo device id

**Files:**
- Create: `VH/pipeline/device_ctx.py`
- Modify: `VH/handlers/chat.py` (`_HISTORY`, `_recent_turns`, `reset_history`, `_remember`), `VH/handlers/action_flow.py` (`device_state`, `mark_active`, `mark_inactive`, `note_result`, `remember/recall/forget`), `VH/services/action_callbacks.py` (giữ device theo request_id), `VH/lanes/general.py`, `VH/lanes/phone.py` (`run_background` copy context), `VH/app.py` (`turn_lane`, `/process`, callback `/internal/action-results`)
- Test: `VH/tests/test_v2_units.py`, `VH/tests/test_device_state.py`, `VH/tests/test_chat.py`

**Interfaces:**
- Produces: `device_ctx.current: ContextVar[str]` (mặc định `config.VISIONCARE_DEVICE_ID`); `device_ctx.use(device: str)` context manager; `device_ctx.run_in_thread(fn, *args) -> threading.Thread` (dùng `contextvars.copy_context().run`). Mọi kho trạng thái trong `chat`/`action_flow` thành `dict[device, ...]` đọc bằng `device_ctx.current.get()`; chữ ký public giữ nguyên (test cũ không đổi). Callback từ app server tra device qua registry (lưu device lúc `run_action` đăng ký request_id).
- [ ] **Step 1: Test** `test_history_isolated_per_device`, `test_device_state_isolated` (kính A đang phát nhạc, kính B không → bypass chỉ áp cho A), `test_callback_updates_right_device`, `test_background_thread_keeps_device`.
- [ ] **Step 2–4:** FAIL → cài → PASS; toàn bộ test cũ vẫn PASS.
- [ ] **Step 5: Commit.**

## Phần IV — Giao thức, bảo mật, độ trễ

### Task 9: Xác thực thiết bị, trần kích thước, rate limit

**Files:**
- Create: `VH/pipeline/guard.py`
- Modify: `VH/app.py` (`/process`, `/v2/image`, `/v2/turn`, `/v2/live`), `VH/pipeline/stt_stream.py` (trần audio), `VH/lanes/ocr_live.py` + `VH/lanes/nav_live.py` (trần khung), `VH/config.py`, `VH/.env.example`, `VH/tools/bench_live.py`, `VH/demo-web/app.js` (gửi token), `VH/tests/conftest.py`
- Test: `VH/tests/test_guard.py`, chỉnh fixture các test API để gửi token

**Interfaces:**
- Produces:
  - `guard.token_ok(headers_or_value) -> bool`: chấp nhận `Authorization: Bearer <t>` hoặc `X-Device-Token: <t>`; so bằng `hmac.compare_digest` với `config.VISIONCARE_DEVICE_CLIENT_TOKEN`. Token cấu hình rỗng → mọi request kính bị từ chối 503 `{"error":"device token not configured"}` và log ERROR một lần lúc khởi động (KHÔNG có ngoại lệ localhost).
  - `guard.RateLimiter(rate_per_min: float, burst: int)` với `.allow(key: str) -> bool` (token bucket, khoá theo device id).
  - Giá trị cấu hình mới: `DEVICE_MAX_IMAGE_BYTES=2_000_000`, `DEVICE_MAX_AUDIO_S=30`, `LIVE_MAX_FRAME_BYTES=300_000`, `DEVICE_TURNS_PER_MIN=30`, `DEVICE_IMAGES_PER_MIN=40`, `LIVE_MAX_FPS=15`.
  - Mã: thiếu/sai token → 401 (WS: đóng mã 4401); ảnh quá trần → 413 (đọc body theo stream, dừng khi vượt, không `await request.body()` cả cục); audio quá 30 s → `StreamingTranscriber` ngừng nhận, lượt kết thúc với phần đã có (log WARNING); vượt rate → 429; khung live quá trần/quá fps → bỏ khung, không đóng phiên.
  - `/process` (firmware cũ) cũng đòi token; vì firmware chưa gửi được thì 401 với audio báo lỗi? → KHÔNG: trả 401 JSON như mọi endpoint (người dùng chọn "khoá hết, firmware sửa theo").
  - `/internal/action-results` giữ `VISIONCARE_CALLBACK_TOKEN` như hiện có.
- [ ] **Step 1: Test** `test_missing_token_401` (cả 5 endpoint), `test_wrong_token_401`, `test_token_not_configured_503`, `test_bearer_and_header_both_ok`, `test_image_over_cap_413_without_reading_all` (body generator 3 MB, đếm byte đã đọc ≤ 2 MB + 1 chunk), `test_audio_capped_30s`, `test_rate_limit_429`, `test_ws_bad_token_4401`, `test_live_oversize_frame_dropped`.
- [ ] **Step 2–4:** FAIL → cài → PASS; toàn bộ test PASS.
- [ ] **Step 5: Commit.**

### Task 10: `WS /v2/session` — một WebSocket mỗi kính

**Files:**
- Create: `VH/live/device_session.py` (vòng đời socket, multiplex), `VH/live/ws_adapter.py` (giả `WebSocket` cho `ocr_live.run`/`nav_live.run`)
- Modify: `VH/app.py` (endpoint), `VH/pipeline/turn.py` (nhận body là async iterator — đã đúng; thêm tham số `on_cancel`), `VH/app.py::_v2_response` (tách phần sinh audio thành hàm dùng chung: `_reply_audio(reply, cue_ok, response_format, released) -> tuple[dict, Iterator[bytes] | None]`), `VH/tools/bench_live.py` (`--ws`)
- Test: `VH/tests/test_v2_session.py`

**Interfaces:**
- Consumes: `guard.token_ok`, `guard.RateLimiter` (Task 9); `pending_action.cancel` (Task 5); `turn_v2.run(device, turn_id, content_type, body, state)`; `_reply_audio` (tách từ `_v2_response`).
- Produces — giao thức (JSON text; binary có byte đầu là loại):
  - kính → server: `{"t":"hello","device":str,"token":str,"cue_version":int,"fw":str,"accept":str}` (bắt buộc là khung đầu; sai token → đóng 4401); `{"t":"turn_start","turn":str,"t_press_ms":int}`; binary `0x01`+JPEG (ảnh lượt, gắn vào `image_buffer.put(device, turn, ...)`); binary `0x03`+ADPCM (audio lượt); `{"t":"turn_end","turn":str,"t_release_ms":int}`; binary `0x04`+JPEG (khung live); `{"t":"cancel"}`; `{"t":"played","turn":str,"first_byte_ms":int,"first_audio_ms":int}` (Task 14 ghi lại); `{"t":"ping"}`.
  - server → kính: `{"t":"hello_ok","session":str,"cue_version":int,"ping_s":25}`; `{"t":"reply","turn":str,"cues":[...],"live":"ocr"|"nav"|null,"audio":{"format":str,"sample_rate":16000,"preroll_s":float}|null}`; binary `0x02`+khối audio; `{"t":"reply_end","turn":str}`; các khung live hiện có (`cam`, `capture`, `cue`, `hazard`, `end`) giữ nguyên định dạng của `live/protocol.py`; `{"t":"pong"}`; `{"t":"error","code":"rate_limited"|"too_large"|"bad_frame"}`.
  - Ngữ nghĩa: `turn_start` mới hoặc `cancel` → huỷ lượt đang chạy (task `turn.run`, stream audio), huỷ live đang chạy, `pending_action.cancel`. Có `reply.live` → sau `reply_end` server chạy luôn runner live trên cùng socket qua `ws_adapter` (khung `0x04` được chuyển thành định dạng runner mong đợi). Phiên mới của cùng `device` → đóng phiên cũ (mã 4000).
  - `ws_adapter.LiveSocket` có đúng các method mà `ocr_live.run`/`nav_live.run`/`receive_frames`/`speak_ws` đang gọi trên `WebSocket` (implementer đọc hai file đó và liệt kê; chỉ cài những method đó).
- [ ] **Step 1: Test** (TestClient websocket, model giả như `test_v2_api.py`): `test_hello_required_first`, `test_bad_token_closes_4401`, `test_turn_roundtrip_chat` (turn_start → 0x01 → nhiều 0x03 → turn_end → nhận `reply` rồi binary 0x02 rồi `reply_end`), `test_partial_runs_before_turn_end` (đoán sớm được gọi trước `turn_end` — chính là lợi ích qua Cloudflare), `test_cancel_mid_reply_stops_audio`, `test_new_turn_cancels_previous`, `test_live_ocr_over_session` (reply live=ocr → server gửi `cam`, nhận 0x04, gửi `capture`…), `test_new_session_replaces_old`, `test_ping_pong`.
- [ ] **Step 2–4:** FAIL → cài → PASS; toàn bộ test PASS.
- [ ] **Step 5: Bench** `tools/bench_live.py --ws` (cùng các luồng chat/space/ocr/tiền/gọi điện/hazard như chế độ POST, cột giống hệt); chạy local 4 lượt/luồng cả hai chế độ, ghi bảng vào commit message. (Đo qua Cloudflare do controller chạy ở Task 17.)
- [ ] **Step 6: Commit.**

### Task 11: OCR — chế độ nguyên văn/chuyên ngành, ưu tiên ảnh UXGA

**Files:**
- Modify: `VH/pipeline/intent_classifier.py` (enum `ocr_mode` nếu Task 4 chưa thêm), `VH/models/clef/client.py` (`_OCR_MODES`), `VH/pipeline/intent_early.py` (luật "nguyên văn|đọc y nguyên|từng chữ" → raw; "chuyên ngành|hợp đồng|đơn thuốc|toa thuốc|hướng dẫn sử dụng" → specialized), `VH/lanes/ocr_live.py` (`_prompt`, `run`), `VH/pipeline/final_router.py` (`_lane_b` truyền mode)
- Test: `VH/tests/test_v2_units.py`

**Interfaces:**
- `ocr_live._prompt(mode)` nhận thêm `raw`, `specialized`, ánh xạ sang prompt tương ứng của `models/ocr/prompts.py` (`Mode.RAW`, `Mode.SPECIALIZED`) — dùng lại văn bản prompt đó, không viết mới.
- `ocr_live.run`: khi hết trần căn khung, thứ tự ảnh = `hi_res or fallback_jpeg or best_vga`.
- [ ] **Step 1: Test** `test_ocr_mode_raw_prompt`, `test_ocr_mode_specialized_prompt`, `test_keyword_raw_mode`, `test_timeout_prefers_uxga_fallback`.
- [ ] **Step 2–4:** FAIL → cài → PASS. **Step 5: Commit.**

### Task 12: `/process` (firmware cũ) chạy pipeline v2; gỡ đường Gemini

**Files:**
- Modify: `VH/app.py` (`process`), `VH/pipeline/phrases.py` (bỏ phụ thuộc `handlers/waiting.py` nếu có), `VH/tests/test_app.py`
- Delete (chỉ khi `grep -rn` xác nhận không còn ai import): `VH/models/vlm/`, `VH/pipeline/intent_local.py`, `VH/handlers/waiting.py`, `VH/pipeline/router.py`, `VH/pipeline/intent.py`, test tương ứng của chúng
- Test: `VH/tests/test_app.py`

**Interfaces:**
- `/process` giữ nguyên hợp đồng HTTP (multipart `audio` + `image` tuỳ chọn, `Accept`/`RESPONSE_FORMAT`, câu mở đầu `_RECEIVED_MESSAGE`, luôn trả audio, đòi token theo Task 9). Bên trong: `image_buffer.put(device, turn_id, image)` với `turn_id = "process-<n>"`; audio WAV/ADPCM → một async iterator một mảnh → `turn_v2.run(...)` → `_reply_audio(reply, cue_ok=False, ...)`, nối sau câu mở đầu. Làn B/C rơi về một lần: B đọc thẳng ảnh (không mở live); C chỉ gửi lệnh điện thoại + câu xác nhận (không có WS).
- [ ] **Step 1:** Viết lại các test trong `test_app.py` đang mock Gemini/`intent_local` thành test hợp đồng `/process` với model giả của v2 (giữ nguyên mọi assertion về hợp đồng HTTP: mã, header, định dạng audio, câu mở đầu, câu lỗi). Test mới: `test_process_routes_through_v2`, `test_process_ocr_single_shot`, `test_process_nav_no_live`.
- [ ] **Step 2–4:** FAIL → cài → PASS; xoá module chết, `grep` sạch, toàn bộ test PASS.
- [ ] **Step 5: Commit.**

### Task 13: Huỷ khi kính ngắt, ưu tiên âm hazard, dùng `hello`/`cue_version`

**Files:**
- Modify: `VH/app.py` (stream audio), `VH/pipeline/speech.py` (`sync_iter` dừng khi bị đóng), `VH/lanes/nav_live.py` (trộn hazard và `session.outbox`), `VH/lanes/ocr_live.py` + `VH/lanes/nav_live.py` (đọc `hello`, `cue_version`)
- Test: `VH/tests/test_v2_units.py`, `VH/tests/test_v2_api.py`

**Interfaces:**
- Đóng `StreamingResponse` giữa chừng (client ngắt) → generator audio `close()` → task `llm.stream_chat` bị huỷ và TTS dừng trong ≤ 0,5 s (đếm bằng fake LLM ghi lại `cancelled`).
- nav_live: khung `hazard` luôn gửi ngay; audio từ `outbox` chỉ gửi khi không có hazard mức ≥ 2 trong 1,5 s gần nhất, và bị ngắt (dừng gửi phần còn lại, đưa lại vào đầu hàng đợi) khi hazard mức ≥ 2 tới.
- `hello` trên `/v2/live`: lưu `cue_version`; kính cũ hơn `cues.CUE_VERSION` → cue live gửi dạng audio TTS thay vì `{"t":"cue"}`.
- [ ] **Step 1: Test** `test_client_disconnect_cancels_llm`, `test_hazard_preempts_outbox_audio`, `test_live_old_cue_version_speaks_cue`.
- [ ] **Step 2–4:** FAIL → cài → PASS. **Step 5: Commit.**

### Task 14: Quan sát — turn id xuyên log, metrics JSONL, mốc thời gian từ kính; clip cue cho flash

**Files:**
- Create: `VH/pipeline/metrics.py`, `VH/tools/make_cue_clips.py`
- Modify: `VH/app.py` (filter logging thêm `[dev turn]`), `VH/pipeline/turn.py` (ghi metrics), `VH/live/device_session.py` (khung `played`), `VH/config.py`
- Test: `VH/tests/test_v2_units.py`

**Interfaces:**
- `metrics.record_turn(row: dict) -> None` ghi một dòng JSON vào `<STORAGE_DIR>/metrics/turns.jsonl` (append, thread-safe, xoay file khi > 50 MB). Dòng: `{"ts","device","turn","transport":"post"|"ws"|"process","intent","lane","source","confidence", ...timings của TurnResult, "glasses": {"t_press_ms","t_release_ms","first_byte_ms","first_audio_ms"}|null}`. Khung `played` tới sau → ghi một dòng bổ sung `{"turn", "glasses": {...}}` (không sửa dòng cũ).
- Log: `logging.Filter` gắn `device`/`turn` từ contextvar (`device_ctx`, Task 8) vào mọi dòng log của lượt.
- `tools/make_cue_clips.py --out <dir>`: với mỗi id trong bảng cue (`pipeline/cues.py`), dựng audio bằng TTS hiện tại → ADPCM WAV 16 kHz (`pipeline/adpcm.py`) → `<dir>/<id>.wav` + `<dir>/manifest.json` `{"cue_version": CUE_VERSION, "clips": {id: {"file","bytes","seconds","text"}}}`. Âm không lời (`hazard_1..3`, `shutter`): sinh bằng numpy (bíp sin 1 kHz 80 ms / bíp nhanh 3×60 ms / âm liên tục 600 ms / tiếng "tách" nhiễu 30 ms).
- [ ] **Step 1: Test** `test_record_turn_appends_jsonl`, `test_log_filter_has_turn`, `test_played_frame_recorded`, `test_cue_manifest_complete` (mọi id trong `cues` có clip, ADPCM header hợp lệ).
- [ ] **Step 2–4:** FAIL → cài → PASS; chạy `make_cue_clips.py` thật (GPU) ra `VH/assets/cues/` và commit (kiểm kích thước).
- [ ] **Step 5: Commit.**

## Phần V — Trọn luồng có điện thoại giả lập, tải đồng thời, tài liệu

### Task 15: App server — transport `webhook` + điện thoại giả lập + E2E trọn luồng

**Files (repo AB, nhánh `voice-v2-hardening`):**
- Modify: `AB/src/app/adapters/delivery.py` (thêm `WebhookDeliveryAdapter`), `AB/src/app/config.py` (`DeliveryTransport.WEBHOOK`, `DELIVERY_WEBHOOK_URL`)
- Create: `AB/scripts/phone_sim.py`, `AB/tests/test_webhook_delivery_adapter.py`
**Files (repo VH):**
- Create: `VH/tools/e2e_full.py`, `VH/docs/E2E_FULL_FLOW.md`

**Interfaces:**
- `WebhookDeliveryAdapter.send_command(...)`: POST tới `DELIVERY_WEBHOOK_URL` đúng **data payload** mà `_build_message` dựng cho FCM (dùng chung một hàm dựng payload — tách `_command_data(operation) -> dict[str,str]` ra từ `_build_message`, FCM và webhook cùng gọi), header `X-Push-Token: <push_token>`; trả `DeliveryOutcome` giống adapter fake/FCM (2xx → sent; lỗi mạng/5xx → transient; 4xx → permanent). Theo `AB/claude.md`: adapter không đổi trạng thái operation; test trên PostgreSQL thật (`compose.test.yaml`).
- `phone_sim.py` (aiohttp hoặc FastAPI+uvicorn có sẵn trong env của AB): đăng ký thiết bị qua `POST /api/v1/device/register` (token `DEVICE_API_TOKEN` từ `SeeVia_system/.env`, `push_token="sim"`), nhận webhook, sau độ trễ cấu hình (mặc định 0,3–1,0 s ngẫu nhiên seed cố định) gửi `POST /api/v1/device/report` với `result` đúng schema `contracts/contract-matrix.md` cho từng action. Kịch bản cấu hình bằng JSON `--scenario`: danh bạ (`"mẹ"` → 1 số; `"Nam"` → 2 số → `MULTIPLE_CONTACTS_FOUND`; tên lạ → `CONTACT_NOT_FOUND`), ride quote/confirm, music play/stop/volume, navigation start/stop, emergency (rút ngắn). Ghi mọi lệnh nhận được vào `phone_sim_log.jsonl` (để E2E kiểm "không có lệnh ngoài ý muốn").
- `tools/e2e_full.py`: dựng/kiểm tra stack (postgres docker + AB uvicorn `DELIVERY_TRANSPORT=webhook` + phone_sim + VH server với `VISIONCARE_HOST_URL` trỏ AB), chạy kịch bản kính giả lập qua `WS /v2/session` (dùng lại client của `bench_live.py --ws`): gọi mẹ, gọi Nam (nhiều số), gọi rồi bấm huỷ ngay (phone_sim KHÔNG được nhận lệnh), đặt xe → xác nhận, phát nhạc → bấm nút dừng, dẫn đường → hazard → dừng, cấp cứu, câu chat không được sinh lệnh nào. Mỗi kịch bản: PASS/FAIL + mốc nhả nút → tiếng đầu, nhả nút → lệnh tới điện thoại, lệnh → kết quả đọc cho người dùng. Không dùng app server `:8001` đang chạy của người dùng — dựng cổng riêng (vd. 18001) để không đụng nó; có cờ `--app-url` để chạy với app server thật khi người dùng bật.
- [ ] **Step 1:** Test adapter (`test_webhook_sends_fcm_payload`, `test_webhook_5xx_transient`, `test_webhook_4xx_permanent`) trong AB theo cách chạy test của AB (`AB/README.md`); FAIL → cài → PASS; toàn bộ test AB PASS (`ruff`/`mypy` nếu repo có cấu hình).
- [ ] **Step 2:** Commit trong AB.
- [ ] **Step 3:** `phone_sim.py` + `e2e_full.py` + `E2E_FULL_FLOW.md` (lệnh chạy, kết quả mẫu). Chạy thật toàn bộ kịch bản; mọi kịch bản PASS; dán bảng kết quả vào `E2E_FULL_FLOW.md`.
- [ ] **Step 4:** Commit trong VH.

### Task 15b: Điện thoại giả lập khớp app Android + checklist máy thật

App điện thoại do người dùng tự làm trên máy họ (clone về); server này KHÔNG cài JDK/Android
SDK, không sửa code trong `mobile/`. Việc ở đây: `phone_sim` phát report y hệt app thật, và
một checklist để người dùng chạy trên điện thoại thật.

**Files:**
- Modify: `AB/scripts/phone_sim.py` (report từng action lấy đúng trường/giá trị mà
  `app-demo-backend/mobile/app/src/main/java/com/youreyes/app/actions/*Actions.kt` dựng — chỉ ĐỌC
  file Kotlin, ghi nguồn từng trường trong chú thích)
- Create: `AB/tests/fixtures/server_payloads/*.json` (payload `WebhookDeliveryAdapter` gửi cho cả
  9 action, ghi lại từ Task 15 — người dùng dùng lại cho test phía app), `VH/docs/E2E_REAL_PHONE.md`

- [ ] **Step 1:** đối chiếu và sửa `phone_sim.py` theo các `*Actions.kt`; chạy lại `e2e_full.py` PASS.
- [ ] **Step 2:** lưu 9 payload mẫu + một file README ngắn mô tả từng trường.
- [ ] **Step 3:** `E2E_REAL_PHONE.md`: build/cài APK, cấu hình server/token, ghép kính, rồi
  `tools/e2e_full.py --app-url <app server thật> --no-phone-sim` với từng kịch bản (gọi mẹ, tên
  trùng, huỷ cuộc gọi bằng nút, Spotify phát/dừng/âm lượng, Maps dẫn đường, Grab báo giá/xác
  nhận/huỷ, khẩn cấp gọi người thân + SMS) và cột "kết quả mong đợi".
- [ ] **Step 4:** Commit trong AB và VH.

### Task 16: Bench tải đồng thời

**Files:**
- Create: `VH/tools/bench_load.py`
- Modify: `VH/models/llm/client.py` (bộ đếm request đang bay + tổng mỗi lượt, đọc qua `llm.stats()`)

**Interfaces:**
- `bench_load.py --base <url> --glasses N --turns M --mix chat:4,space:2,ocr:2,call:1,nav:1` mở N phiên `WS /v2/session` song song, mỗi phiên M lượt cách nhau 2–5 s; in p50/p90/max nhả nút → tiếng đầu theo luồng, `starve`, số request Gemma đồng thời tối đa (`llm.stats()["max_inflight"]` qua endpoint debug `GET /v2/debug/stats` chỉ bật khi `V2_DEBUG_STATS=1`), lỗi.
- [ ] **Step 1:** cài; chạy N = 1, 4, 8 (local, phone_sim của Task 15). Ghi bảng vào `docs/benchmarks/LOAD_V2.md`; nêu N lớn nhất mà p90 chat ≤ 1,2× p90 lúc N=1 và max_inflight ≤ 40.
- [ ] **Step 2: Commit.**

### Task 17: Đo qua Cloudflare + tài liệu firmware + dọn tài liệu/vận hành

Controller (không phải subagent) chạy phần đo qua tunnel vì cần bật server công khai rồi tắt ngay.

**Files:**
- Create: `VH/docs/FIRMWARE_ENDPOINTS.md`
- Modify: `VH/Dockerfile`, `VH/start-demo.ps1`, `VH/README.md`, `VH/docs/KIEN_TRUC_SERVER.md`, `VH/docs/HANDOFF_VOICE_V2.md`, `VH/tests/test_adpcm.py` (skip khi ffmpeg thiếu `-block_size`: dò bằng `ffmpeg -h encoder=adpcm_ima_wav`), `VH/config.py` (ghi chú `HF_HUB_OFFLINE`)
- [ ] **Step 1:** `FIRMWARE_ENDPOINTS.md` cho người viết firmware ESP32-S3: token (cách lưu, header/`hello`), `WS /v2/session` đầy đủ khung (Task 10) + ví dụ chuỗi khung cho một lượt chat, OCR live, nav; ping 25 s, mở lại khi rớt (backoff 0,5→8 s); máy trạng thái kính; mã đóng (4000 bị thay, 4401 token); trần (ảnh 2 MB, audio 30 s, khung live 300 KB, 15 fps); 429; khung `played` với 4 mốc; định dạng audio ra; clip cue trong flash (`assets/cues/manifest.json`, `cue_version`); đường POST/`/process` còn giữ (đều đòi token).
- [ ] **Step 2:** kiểm giấy phép/chính sách watermark của vieneu (`perth`): ghi kết luận vào bàn giao, KHÔNG cài/gỡ gói. Sửa test ffmpeg tự skip; Dockerfile (nền CUDA, torch CUDA 13, thứ tự `onnxruntime-gpu`, cổng 18888, biến mới), `start-demo.ps1`, README, `KIEN_TRUC_SERVER.md`.
- [ ] **Step 3 (controller):** bật server cổng 18888, chạy `bench_live.py --ws` và chế độ POST qua `https://api.visioncare-host.uk` (`--resolve` như bản bàn giao), 4 lượt/luồng; tắt server ngay (`fuser -k 18888/tcp`). Ghi bảng local vs Cloudflare (POST cũ vs WS).
- [ ] **Step 4:** viết lại `HANDOFF_VOICE_V2.md`: cái đã sửa (kèm số), cái còn lại cần người dùng (khoá SerpAPI, app server thật, ghi âm kính, firmware, quyết định gậy, hazard ngoài đường).
- [ ] **Step 5: Commit.**
