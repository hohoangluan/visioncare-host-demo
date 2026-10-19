# Gọi điện / nhắn tin qua kính — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kính gọi/nhận cuộc gọi và nhắn tin với app người thân qua server, không dùng trình gọi/SMS của hệ điều hành; khẩn cấp gọi lần lượt người thân.

**Architecture:** Tín hiệu kính → VH → AB → FCM → app; âm thanh kính ↔ VH (cầu âm thanh) ↔ app qua WebSocket. AB lưu quan hệ người thân, cuộc gọi, tin nhắn.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic + PostgreSQL (AB), websockets, httpx, numpy, `pipeline/adpcm.py` (VH).

**Spec:** `docs/superpowers/specs/2026-10-19-glasses-calls-messages-design.md`

**Điều kiện bắt đầu:** plan `docs/superpowers/plans/2026-10-19-voice-v2-hardening.md` đã xong tới Task 15 (cần `WS /v2/session`, `pipeline/guard.py`, `pipeline/pending_action.py`, transport `webhook` + `phone_sim`).

## Global Constraints

- Mọi ràng buộc chung của plan `2026-10-19-voice-v2-hardening.md` (mục Global Constraints) áp dụng nguyên văn: venv, GPU, không cài gói, NFS, commit, không push, Co-Authored-By.
- AB theo `app-demo-backend/claude.md`: router → service → repository; adapter không đổi trạng thái; migration Alembic cho mọi thay đổi schema; test trên PostgreSQL thật (`compose.test.yaml`); không đổi ngầm endpoint/contract cũ; cập nhật OpenAPI (`scripts/export_openapi.py`) và `contracts/` khi thêm endpoint; không log số điện thoại/tin nhắn/token dạng thô.
- Không sửa code `app-demo-backend/mobile/` (người dùng tự làm app theo hợp đồng Task C8).
- Số cố định từ spec: chuông `CALL_RING_TIMEOUT_S=30`; khẩn cấp tối đa 3 vòng; jitter `CALL_JITTER_MS=60`, bỏ khung trễ > 200 ms; PCM16LE 16 kHz mono khung 20 ms (640 B); mic kính khung `0x05`; `CALL_HALF_DUPLEX` mặc định 0, giảm 20 dB khi bật; trễ một chiều mục tiêu ≤ 400 ms qua Cloudflare.
- Câu nói cố định (đúng nguyên văn): "Đang gọi cho {name}." · "Bạn muốn gọi ai: {a} hay {b}?" · "Chưa có người thân tên {name} trong danh sách." · "{name} chưa nghe máy. Bạn muốn nhắn tin không?" · "{name} đang gọi. Bấm nút để nghe." · "Nhắn cho {name}: {text}." · "{name} nhắn: {text}" · "Đang gọi người thân khẩn cấp, bấm nút để huỷ." · "Không có tin nhắn mới." · tin khẩn cấp "KHẨN CẤP: {owner} cần giúp. Vị trí: {map_url}".

## Review Focus

1. **Hai đầu cùng cúp / mạng rớt giữa cuộc gọi**: trạng thái AB và VH khớp nhau (`ended`), không còn task cầu âm thanh treo. → test ở C5 (`test_bridge_peer_disconnect_ends_call`) và C2 (`test_hangup_idempotent`).
2. **Người không có link `active` dùng token/endpoint** (gọi, nhắn, mở media WS bằng token đã dùng): bị từ chối. → C1/C2/C3/C5.
3. **Tên người thân trùng / gần giống / không dấu**: khớp đúng, trùng thì hỏi lại, không gọi bừa. → C1 (`test_alias_match_*`), C6.
4. **Tin nhắn tới khi kính đang trong lượt hoặc cuộc gọi**: không chen ngang, không mất. → C7 (`test_incoming_message_queued_while_busy`).
5. **Khẩn cấp không ai nghe**: chuỗi đi hết 3 vòng rồi dừng, kính được báo; bấm nút dừng chuỗi. → C4.

---

### Task C1 (AB): Quan hệ người thân `care_links`

**Files:** Create `AB/src/app/models/care_link.py`, `AB/src/app/repositories/care_link.py`, `AB/src/app/services/care.py`, `AB/src/app/schemas/care.py`, `AB/src/app/api/care.py`, migration `AB/alembic/versions/20261019_0008_care_links.py`; Modify `AB/src/app/application.py` (router), `AB/src/app/models/__init__.py`; Test `AB/tests/test_care_api.py`.

**Interfaces (Produces):**
- App API (bearer app session như các route hiện có): `POST /api/v1/care/invite {phone_number, display_name, aliases: [str], emergency: bool, priority: int}` (owner mời; tạo `pending`; user người thân phải tồn tại theo `phone_number`, không thì `404 USER_NOT_FOUND`); `POST /api/v1/care/{link_id}/accept` (chỉ relative); `GET /api/v1/care/links` (cả hai vai); `PATCH /api/v1/care/{link_id}` (owner sửa aliases/emergency/priority); `DELETE /api/v1/care/{link_id}` (→ `revoked`).
- `services.care.resolve_alias(owner_user_id: str, alias: str) -> list[CareLink]` — chỉ link `active`; chuẩn hoá: lower, bỏ dấu câu, bỏ khoảng trắng thừa; khớp bằng nhau với alias hoặc display_name, cả bản có dấu lẫn bản bỏ dấu (`unicodedata` NFD bỏ dấu, "đ"→"d").
- [ ] Test: `test_invite_accept_flow`, `test_only_relative_can_accept`, `test_unique_pair`, `test_revoked_not_resolved`, `test_alias_match_accent_insensitive` ("me" khớp "mẹ"), `test_alias_match_multiple` (hai link alias "nam" → 2), `test_no_raw_phone_in_logs`.
- [ ] FAIL → cài → PASS (toàn bộ test AB). Commit.

### Task C2 (AB): Cuộc gọi — trạng thái, API, FCM, callback, hết giờ chuông

**Files:** Create `AB/src/app/models/call.py`, `AB/src/app/repositories/call.py`, `AB/src/app/services/call.py`, `AB/src/app/schemas/call.py`, `AB/src/app/api/calls.py`, migration `..._0009_calls.py`; Modify `AB/src/app/api/service.py` (route cho glasses-server), `AB/src/app/adapters/delivery.py` (dựng payload FCM mới — dùng chung hàm dựng data đã tách ở plan trước Task 15), `AB/src/app/adapters/callback.py` + `AB/src/app/workers/callback.py` (callback mới), `AB/src/app/workers/timeout.py` (hết giờ chuông); Test `AB/tests/test_calls_api.py`.

**Interfaces (Produces):**
- Glasses-server (token public hiện có, scope mới `calls:manage`): `POST /api/v1/service/call/start {user_id, glasses_device_id, contact_alias, media_token, request_id}` → `200 {call_id, relative: {display_name}}` | lỗi `CONTACT_NOT_FOUND`, `MULTIPLE_CONTACTS_FOUND {candidates:[display_name]}`; `POST /api/v1/service/call/{id}/hangup {reason}`; `POST /api/v1/service/call/{id}/answer {media_token}` (kính nghe cuộc gọi tới).
- App: `POST /api/v1/calls {owner_user_id}` (relative gọi kính) → `{call_id}`; `POST /api/v1/calls/{id}/answer` → `{media_url, media_token}`; `POST /api/v1/calls/{id}/reject`; `POST /api/v1/calls/{id}/hangup`; `GET /api/v1/calls/{id}`.
- FCM data `type`: `call_incoming {call_id, from_display_name, emergency}`, `call_answered {call_id, media_url, media_token}` (cho chiều to_glasses), `call_ended {call_id, reason}`.
- Callback tới VH (`CALLBACK_URL` gốc, đường mới `/internal/calls`): `{event: "call_answered"|"call_rejected"|"call_ended"|"call_missed"|"call_incoming", call_id, glasses_device_id, peer_display_name, media_token?}`.
- Máy trạng thái: `ringing→active|rejected|missed|ended(huỷ)`, `active→ended`; chuyển lặp là no-op idempotent; `media_token` chỉ lưu hash.
- [ ] Test: `test_start_resolves_alias`, `test_start_multiple_candidates`, `test_answer_returns_media_token_once`, `test_reject_callbacks_glasses`, `test_ring_timeout_marks_missed` (`CALL_RING_TIMEOUT_S` rút ngắn trong test), `test_hangup_idempotent`, `test_relative_without_link_cannot_call`, `test_fcm_payload_call_incoming`.
- [ ] FAIL → cài → PASS. Export OpenAPI. Commit.

### Task C3 (AB): Tin nhắn

**Files:** Create `AB/src/app/models/message.py`, repository/service/schema/api `messages`, migration `..._0010_messages.py`; Modify `api/service.py`, delivery + callback; Test `AB/tests/test_messages_api.py`.

**Interfaces (Produces):** glasses-server `POST /api/v1/service/messages/send {user_id, contact_alias, text, request_id}` (lỗi giống call/start), `GET /api/v1/service/messages/unread?user_id=` , `POST /api/v1/service/messages/{id}/read`; app `POST /api/v1/messages {owner_user_id, text, request_id}`, `GET /api/v1/messages?with=<user_id>&before=<ts>&limit=50`; FCM `message_in {message_id, from_display_name, text}`; callback VH `/internal/messages {event:"message_received", message_id, glasses_device_id, from_display_name, text}`; `request_id` trùng → trả bản cũ, không gửi lại; text 1–1000 ký tự.
- [ ] Test: `test_send_from_glasses_pushes_relative`, `test_send_from_relative_callbacks_glasses`, `test_idempotent_request_id`, `test_unread_and_mark_read`, `test_no_link_forbidden`, `test_text_length_validated`. FAIL → cài → PASS. Commit.

### Task C4 (AB): Khẩn cấp gọi người thân

**Files:** Create `AB/src/app/services/emergency.py`, `AB/src/app/workers/emergency.py`; Modify `api/service.py` (`POST /api/v1/service/emergency/start {user_id, glasses_device_id, request_id}`, `POST /api/v1/service/emergency/{id}/stop`), `workers/runner.py`; Test `AB/tests/test_emergency_relatives.py`.

**Interfaces:** chuỗi: lấy link `emergency=true` theo `priority`; ngay lúc bắt đầu gửi tin khẩn cấp (câu cố định ở Global Constraints; vị trí qua operation `location_get` sẵn có với trần 5 s, lỗi thì bỏ phần vị trí) tới tất cả; gọi lần lượt bằng service của C2 (`emergency=true`, mỗi người 30 s), hết danh sách lặp, tối đa 3 vòng; có người nghe → dừng chuỗi, callback `call_answered` như C2; hết 3 vòng → callback `/internal/calls {event:"emergency_exhausted"}`; `stop` dừng ngay. `media_token` cho từng lượt gọi: VH gửi kèm danh sách token (3 vòng × số người) trong `emergency/start` (`media_tokens: [str]`) để AB không phải gọi ngược VH.
- [ ] Test: `test_emergency_messages_all_then_calls_in_priority`, `test_emergency_stops_on_answer`, `test_emergency_three_rounds_then_exhausted`, `test_emergency_stop`, `test_location_failure_still_messages`. FAIL → cài → PASS. Commit.

### Task C5 (VH): Cầu âm thanh + `WS /v2/call` + chế độ gọi trong phiên kính

**Files:** Create `VH/live/call_bridge.py`, `VH/live/jitter.py`; Modify `VH/app.py` (`WS /v2/call`, `POST /internal/calls`), `VH/live/device_session.py` (khung `0x05`, `call_answer`, `call_hangup`, gửi `call_state`, nút trong lúc gọi), `VH/config.py`; Test `VH/tests/test_call_bridge.py`.

**Interfaces (Produces):**
- `call_bridge.calls.create(call_id: str, device: str, peer: str, direction: str) -> Call` (sinh `media_token` bằng `secrets.token_urlsafe(16)`, một lần, hạn = chuông + 10 s); `Call.attach_glasses(send_audio: Callable[[bytes], Awaitable], send_state)`; `Call.attach_app(ws)` khi app mở `/v2/call?token=`; `Call.from_glasses(adpcm: bytes)`; `Call.hangup(reason: str, by: "glasses"|"app"|"server")` (báo AB `service/call/{id}/hangup` nếu không phải từ AB); `calls.by_device(device) -> Call | None`.
- `jitter.JitterBuffer(target_ms=60, max_late_ms=200)`: `push(frame, seq_ts)`, `pop() -> bytes | None` (trả im lặng khi thiếu).
- `/internal/calls` (token `VISIONCARE_CALLBACK_TOKEN` như `/internal/action-results`): xử lý `call_answered|call_rejected|call_ended|call_missed|call_incoming|emergency_exhausted` → cập nhật `Call` + gửi `call_state`/câu nói cho kính.
- Phiên kính khi có `Call` của thiết bị: `0x05` → bridge; `turn_start` bị bỏ qua khi đang `active`/`ringing_out` (nút = `call_hangup` theo spec §6); làn C dừng khi `active`.
- `CALL_HALF_DUPLEX=1`: khi đầu app có năng lượng > ngưỡng (RMS > -40 dBFS) trong 100 ms gần nhất, giảm mic kính 20 dB.
- [ ] Test (WS giả hai đầu, AB giả bằng `httpx.MockTransport`): `test_token_single_use`, `test_audio_glasses_to_app_pcm16`, `test_audio_app_to_glasses_adpcm`, `test_jitter_reorders_and_drops_late`, `test_glasses_hangup_notifies_ab`, `test_bridge_peer_disconnect_ends_call`, `test_half_duplex_ducks_mic`, `test_turn_start_ignored_during_call`.
- [ ] FAIL → cài → PASS (toàn bộ VH). Commit.

### Task C6 (VH): Làn D gọi điện + khẩn cấp đi luồng mới; cuộc gọi tới kính

**Files:** Modify `VH/pipeline/final_router.py` (`_lane_d` cho `contact_call`, `emergency_call`), `VH/lanes/phone.py`, `VH/pipeline/cues.py` (cue `call_ringing`, `call_connected`, `call_ended`, `message_in`), `VH/services/visioncare_client.py` (hàm gọi API mới: `call_start`, `call_hangup`, `call_answer`, `emergency_start`, `emergency_stop`, `messages_send`, `messages_unread`, `message_read` — async httpx, cùng token/base URL hiện có), `VH/live/device_session.py`; Test `VH/tests/test_v2_calls_routing.py`.

**Interfaces:** `contact_call` → (cổng an toàn + đọc lại của plan trước giữ nguyên) → `call_bridge.calls.create` + `visioncare_client.call_start(...)`; `MULTIPLE_CONTACTS_FOUND` → hỏi "Bạn muốn gọi ai: {a} hay {b}?" (pending lượt sau, khớp câu trả lời với candidates); `CONTACT_NOT_FOUND` → câu cố định; `call_missed` → câu cố định + pending có/không → có thì chuyển `message_send` hỏi nội dung. `emergency_call` → đọc lại → `emergency_start` (kèm `media_tokens`); bấm nút khi chuỗi đang chuông → `emergency_stop`. `call_incoming` khi kính không có phiên WS → trả AB `409 GLASSES_OFFLINE`. Kính chỉ dùng POST (không phiên) gọi `contact_call` → câu "Kính cần cập nhật để gọi điện." (không gọi AB).
- [ ] Test: `test_contact_call_starts_ab_call_after_readback`, `test_multiple_candidates_asks_then_calls_choice`, `test_contact_not_found_message`, `test_missed_offers_message`, `test_emergency_start_and_stop_on_press`, `test_incoming_call_offline_409`, `test_incoming_call_press_answers`, `test_post_only_glasses_cannot_call`. FAIL → cài → PASS. Commit.

### Task C7 (VH): Nhắn tin bằng giọng nói + nhãn intent mới

**Files:** Modify `VH/models/clef/client.py` (`LABELS` thêm `message_send`: "nhắn tin / gửi lời nhắn cho người thân", `message_read`: "đọc / nghe tin nhắn mới"), `VH/pipeline/intent_early.py` (`LANE` → D; luật đoán sớm "nhắn cho|nhắn tin|gửi tin" / "đọc tin nhắn|có tin nhắn"), `VH/lanes/phone.py` (`SLOT`/trích tham số `contact_name` + `text`), `VH/pipeline/final_router.py`, `VH/live/device_session.py` (hàng đợi tin tới), `VH/tools/intent_gold/build.py` (cho phép `--labels message_send,message_read` sinh thêm câu), `data/intent/gold_*.jsonl`; Test `VH/tests/test_v2_messages.py`.

**Interfaces:** `message_send` thuộc `phone.CONFIRM_INTENTS` (đọc lại "Nhắn cho {name}: {text}." + cửa sổ huỷ) → `messages_send`; thiếu `text` → hỏi "Bạn muốn nhắn gì cho {name}?" (pending). `message_read` → `messages_unread` → đọc từng tin "{name} nhắn: {text}" rồi `message_read`; không có → "Không có tin nhắn mới.". Tin tới (`/internal/messages`): phiên rảnh → cue `message_in` + đọc + đánh dấu đã đọc; bận (lượt đang chạy, cuộc gọi, live OCR) → xếp hàng, đọc ngay khi rảnh; kính không có phiên → để chưa đọc (AB giữ).
- [ ] Gold: sinh ≥ 150 câu mỗi nhãn mới + câu gây nhầm (nhắn ↔ gọi ↔ chat "mẹ có nhắn gì không" ...) bằng `tools/intent_gold`, chạy lại `split` giữ nguyên phân chia cũ (câu cũ không đổi phía), chạy `tools/eval_intent.py` trên dev: độ chính xác các nhãn cũ không giảm (McNemar không có ý nghĩa thống kê theo chiều xấu), `action_fp = 0` sau cổng; chạy test 1 lần, ghi vào `docs/benchmarks/INTENT_GOLD.md`.
- [ ] Test: `test_message_send_readback_then_sends`, `test_message_send_asks_text_when_missing`, `test_message_read_reads_unread`, `test_message_read_none`, `test_incoming_message_announced_when_idle`, `test_incoming_message_queued_while_busy`. FAIL → cài → PASS. Commit.

### Task C8: Mô phỏng người thân, E2E, hợp đồng cho app, tài liệu firmware

**Files:** Create `AB/scripts/relative_sim.py`, `VH/tools/e2e_calls.py`, `app-demo-backend/docs/CALLS_MESSAGES_APP_CONTRACT.md`; Modify `VH/docs/FIRMWARE_ENDPOINTS.md` (khung cuộc gọi §6 spec), `AB/contracts/*` (OpenAPI xuất lại).

**Interfaces:** `relative_sim.py --user <phone> --scenario <json>`: đăng nhập user người thân, đăng ký thiết bị (`push_token="sim"`), nhận webhook FCM (transport `webhook`), hành xử theo kịch bản (nghe sau N s / từ chối / không nghe / gọi kính / nhắn tin), mở `WS /v2/call`, phát WAV PCM16 và ghi tiếng nhận ra file. `e2e_calls.py`: dựng stack như `tools/e2e_full.py` của plan trước + relative_sim; kịch bản: gọi mẹ (nghe), gọi Nam (2 người trùng → chọn), gọi rồi bấm huỷ trong lúc đọc lại (AB không có call), mẹ không nghe → nhắn tin, mẹ gọi kính → kính nghe, nhắn đi/nhắn tới (kính rảnh và đang bận), khẩn cấp (người 1 không nghe, người 2 nghe), khẩn cấp hết 3 vòng (rút ngắn chuông trong test). Đo: nhả nút → chuông tới app; nghe → tiếng đầu; trễ một chiều mỗi hướng (chèn "tách" 5 ms, dò tương quan chéo). Hợp đồng app: mọi endpoint/payload/màn hình/quyền ở spec §7, có ví dụ JSON.
- [ ] Chạy mọi kịch bản local → PASS, bảng số đo vào `VH/docs/E2E_FULL_FLOW.md` (mục cuộc gọi). Commit cả hai repo.

### Task C9 (controller): đo qua Cloudflare + bàn giao

- [ ] Bật VH cổng 18888 (tunnel `api.visioncare-host.uk`), chạy `e2e_calls.py` qua tên miền (relative_sim ở máy này, đi qua Cloudflare), tắt server ngay (`fuser -k 18888/tcp`). So trễ một chiều với mục tiêu ≤ 400 ms; nếu vượt rõ → ghi đề xuất WebRTC vào bàn giao, không tự làm.
- [ ] Cập nhật `VH/docs/HANDOFF_VOICE_V2.md`: đã làm, số đo, việc người dùng (làm app theo hợp đồng, AEC firmware, đo trên kính thật).
