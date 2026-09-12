# Điều phối subagent hoàn thành 23 task hội thoại — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chạy hết 23 task trong `docs/tasks/` bằng subagent theo 8 đợt, mỗi đợt có cổng kiểm chứng bằng test thật, không đợt nào để hai agent ghi đè file của nhau.

**Architecture:** Phiên chính đóng vai **điều phối** — không tự code task nào. Mỗi task một subagent `general-purpose` chạy nền, đọc `CONTRACTS.md` + task file của nó, làm TDD, ghi báo cáo vào file riêng. Sau mỗi đợt, phiên chính chạy cổng: chạy pytest thật, gọi subagent `cavecrew-reviewer` review diff, gộp thay đổi hợp đồng, cập nhật tiến độ, rồi commit. Ba cơ chế chống xung đột: **một file một chủ trong mỗi đợt**, **agent không được gọi git ghi**, **agent không sửa `CONTRACTS.md` mà ghi delta ra file riêng**.

**Tech Stack:** Python 3 + FastAPI + pytest (391 test hiện có, chạy bằng `.venv/Scripts/python.exe -m pytest`), ESP32 Arduino (repo firmware), Claude Code Agent tool.

**Spec:**
- `docs/tasks/RUNBOOK.md` — thứ tự thi công (plan này thi hành nó)
- `docs/tasks/CONTRACTS.md` — nguồn sự thật liên repo
- `docs/tasks/00-INDEX.md` — bản đồ task ↔ mã spec ↔ file code
- `docs/tasks/T01..T23-*.md` — 23 task file
- `SPEC_CAI_THIEN_HOI_THOAI.md` — spec gốc

---

## Global Constraints

Mọi task trong plan này ngầm mang theo cả mục này.

| # | Ràng buộc | Giá trị chính xác |
|---|---|---|
| GC1 | Thư mục làm việc chính | `D:\Study\innostar\Sever_test` |
| GC2 | Repo server app | `D:\Study\innostar\app_demo_backend\apps\backend` (cổng 8001) |
| GC3 | Repo app Android | `D:\Study\innostar\app_demo_backend\apps\android` |
| GC4 | Repo firmware | `D:\Study\innostar\your-eyes-esp32-firmware` |
| GC5 | Lệnh chạy test | `.venv/Scripts/python.exe -m pytest <đường dẫn> -q` |
| GC6 | Baseline test | 391 test collect được trước khi bắt đầu (đo lại ở Task 0) |
| GC7 | **Agent KHÔNG được chạy lệnh git ghi** (`add`/`commit`/`checkout`/`reset`/`stash`/`merge`). Chỉ phiên chính commit, mỗi đợt một lượt. Lý do: 6 agent song song đụng `index.lock` là hỏng repo. |
| GC8 | **Agent KHÔNG sửa `docs/tasks/CONTRACTS.md`, `00-INDEX.md`, `RUNBOOK.md`, `PROGRESS.md`.** Thay đổi hợp đồng ghi ra `docs/tasks/contract-deltas/<Txx>.md`. Phiên chính gộp ở cổng đợt. |
| GC9 | **Một file một chủ trong mỗi đợt.** Bảng chủ sở hữu nằm trong từng Task dưới đây. Agent chạm file không thuộc mình → dừng, báo cáo, không sửa. |
| GC10 | Báo cáo agent ghi vào `docs/tasks/reports/<Txx>.md` theo mẫu ở `RUNBOOK.md` mục 5 |
| GC11 | Số đo ghi vào `docs/tasks/measurements/<tên ở CONTRACTS mục 8>.md`, kèm **ngày** + **cấu hình TLS bật/tắt** + **endpoint** |
| GC12 | 🔴 `emergency_call` không đi qua bất kỳ bước xác minh nào (CONTRACTS mục 0, nguyên tắc 3) |
| GC13 | `find_object.py`, `read_money.py` **không đụng**. `describe_hazard.py` **chỉ thêm comment** |
| GC14 | F2 (đảo thứ tự part multipart) **BỊ HUỶ** — thi công sẽ chậm đi 289 ms |
| GC15 | G8 — **không thêm earcon phía server**; board đã có `cueSent()` ở 0 ms |
| GC16 | Camera thật = **1280×720, quality 18** (thang 0–63, nhỏ = nét) |
| GC17 | TTL pending: `confirm` 25 s · `select` 45 s · `fill` **120 s** |
| GC18 | Thiếu `X-Device-Id` → từ chối rõ ràng, **cấm** rơi ngầm về `config.VISIONCARE_DEVICE_ID` |
| GC19 | Đầu ra audio cho board: mono, 16000 Hz, prelude 60 byte ra trước, `x-audio-format` khớp tuyệt đối 4 byte đầu của thân |
| GC20 | Chưa đo thì ghi "chưa đo". Cấm copy số của cấu hình khác. |

---

## Ba lệch với runbook — phải xử trước khi thi công

Đọc chéo `RUNBOOK.md` với `00-INDEX.md` và `.gitignore` ra ba chỗ hở. Plan này vá cả ba; ghi lại đây để lần sau không ai tưởng là bỏ sót ngẫu nhiên.

**L1 — `docs/` đang bị gitignore.**
`.gitignore:14` có dòng `docs/`. Nghĩa là **toàn bộ** `docs/tasks/` (RUNBOOK, CONTRACTS, 23 task file, mọi file measurements) **không nằm trong git**. Chạy hết 8 đợt xong, mọi bảng số đo — thứ mà chính repo này đặt luật "có bảng số thì mới được chốt" — vẫn nằm ngoài lịch sử. Task 0 vá.

**L2 — T02 và T20 chỉ có mặt ở đợt 0, phần còn lại không thuộc đợt nào.**
Checklist `RUNBOOK.md` mục 6 chỉ có "G10 chunked end *(T02)*" và "P7 bảng mã lỗi *(T20)*" ở đợt 0. Nhưng:
- T02 còn `tests/test_audio_contract.py` (5 ca khoá F8) + G11 (tỉ lệ nhả TTS ≥ 1.30×). Đường găng ghi "T21 phải sau T02" — nghĩa là T02 **đầy đủ**, không chỉ G10.
- T20 còn `tests/test_error_contract.py` + `_DEFAULT_POLICY` + gỡ `xfail` cho T06/D4. T06 (đợt 3) và T10 (đợt 4) đều chờ nó.

Plan này đưa **T02-phần-còn-lại** và **T20-phần-còn-lại** vào Đợt 2 (Task 3), trước T06.

**L3 — Đợt 4 có 6 agent song song cùng ghi `handlers/slots.py` + `tests/test_slots.py`.**
Runbook đặt quy ước "mỗi task chỉ thêm ca của mình". Quy ước đó chống được người, không chống được 6 agent chạy đồng thời cùng gọi Edit trên một file. Plan này khoá cứng:
- **T06 (Đợt 3) định nghĩa TRỌN bảng `SLOTS` cho cả 6 slot ở CONTRACTS mục 4.2 ngay từ đầu.** Đợt 4 chỉ *đọc* `slots.py`, không sửa bảng.
- Mỗi task đợt 4 viết test slot của mình vào **file riêng**, không chung `tests/test_slots.py`.

---

## File Structure

### File hạ tầng điều phối (Task 0 tạo)

| File | Trách nhiệm |
|---|---|
| `docs/tasks/AGENT_RULES.md` | Khối LUẬT BẮT BUỘC + luật chống xung đột. Mọi prompt subagent trỏ vào đây thay vì dán lại 10 dòng luật × 23 lần. |
| `docs/tasks/PROGRESS.md` | Bảng trạng thái 23 task. **Chỉ phiên chính ghi.** |
| `docs/tasks/reports/` | `Txx.md` — báo cáo của từng agent. Một agent một file, không đụng nhau. |
| `docs/tasks/contract-deltas/` | `Txx.md` — thay đổi hợp đồng agent đề nghị. Phiên chính gộp vào `CONTRACTS.md` ở cổng đợt. |
| `docs/tasks/measurements/` | Đã có `README.md`. 11 file số đo theo CONTRACTS mục 8. |

### File code — chủ sở hữu theo đợt

Bảng này là bản mở rộng của "Tra ngược: file code → task" ở `00-INDEX.md`, thêm cột đợt để thấy được hai task cùng đợt có đụng nhau không.

| File | Chủ ở đợt nào | Ai đọc-không-sửa |
|---|---|---|
| `app.py` | Đợt 1 → T01 · Đợt 2 → T02 · Đợt 6 → T17 | mọi task khác |
| `config.py` | Đợt 1 → T01, T03 · Đợt 2 → T07, T15 (qua **marker riêng**, xem Task 0 bước 5) | |
| `pipeline/router.py` | Đợt 1 → T04 | T05 T09 |
| `pipeline/intent.py` | Đợt 3 → T05 | Đợt 4 chỉ đọc |
| `pipeline/phrases.py` | Đợt 2 → T15 · Đợt 3 → T06 · Đợt 5 → T11 | |
| `pipeline/image_quality.py` | Đợt 2 → T15 · Đợt 6 → T17 | |
| `handlers/slots.py` **(mới)** | Đợt 3 → **T06 viết trọn bảng** | Đợt 4 chỉ đọc |
| `handlers/action_flow.py` | Đợt 1 → T03 · Đợt 3 → T06 · Đợt 5 → T11 | |
| `handlers/chat.py` | Đợt 2 → T07 · Đợt 5 → T13 | T14 đọc |
| `handlers/result_speech.py` | Đợt 2 → **T20** · Đợt 3 → T06 · Đợt 4 → T08 | |
| `handlers/phone.py` | Đợt 4 → T08 (T09 **chỉ thêm comment**, GC12) | |
| `handlers/contact_match.py` **(mới)** | Đợt 4 → T08 | |
| `handlers/music.py` + `music_*.py` | Đợt 4 → T12 | |
| `handlers/navigation.py` | Đợt 4 → T10 | |
| `handlers/ocr.py`, `models/ocr/prompts.py` | Đợt 2 → T15 (prompts) · Đợt 4 → T14 (ocr.py) | |
| `models/vlm/client.py` | Đợt 2 → T15 | |
| `handlers/describe_space.py` | Đợt 4 → T16 | |
| `handlers/describe_hazard.py` | Đợt 4 → T16 **chỉ comment** | |
| `handlers/ride.py`, `ride_*.py` | Đợt 5 → T11 | |
| `requirements.txt` | Đợt 4 → T08 (`rapidfuzz`) | |
| `handlers/find_object.py`, `read_money.py` | **KHÔNG AI** (GC13) | |

### File test — mỗi task một file riêng, không dùng chung

| Task | File test |
|---|---|
| T01 | `tests/test_protocol_ids.py` |
| T02 | `tests/test_audio_contract.py` |
| T03 | `tests/test_pending.py`, `tests/test_session_isolation.py`, `tests/test_device_state.py` *(viết lại)* |
| T04 | `tests/test_router_priority.py`, `tests/test_bargein.py`, `tests/test_router.py` *(sửa)* |
| T05 | `tests/test_intent_slots.py` |
| T06 | `tests/test_slots.py` **(chỉ T06 tạo và sở hữu)** |
| T07 | `tests/test_location_degraded.py` |
| T08 | `tests/test_contact_match.py`, `tests/test_slots_contact.py` |
| T09 | `tests/test_emergency_detect.py`, `tests/test_emergency_cancel.py` |
| T10 | `tests/test_navigation.py` |
| T11 | `tests/test_ride_quote.py` |
| T12 | `tests/test_music_slots.py` |
| T13 | `tests/test_chat.py` *(sửa)* |
| T14 | `tests/test_ocr_context.py` |
| T15 | `tests/test_ocr_quality.py` |
| T16 | `tests/test_space_focus.py` |
| T17 | `tests/test_frame_buffer.py` |
| T18 | `tests/test_events_channel.py` |
| T19 | `tests/test_incoming_call.py` |
| T20 | `tests/test_error_contract.py` |
| T21 | `tests/test_latency_budget.py` |
| T23 | `tests/test_capabilities.py` |

> ⚠️ DoD của T08 / T09 / T10 / T12 ghi `pytest tests/test_slots.py -k <từ khoá>`. Vì L3, đổi thành file riêng của từng task. Điều này **phải nói trong prompt agent** — nếu không agent sẽ mở `tests/test_slots.py` ra sửa đúng như task file bảo.

---

## Task 0: Hạ tầng điều phối

**Files:**
- Modify: `.gitignore:14`
- Create: `docs/tasks/AGENT_RULES.md`
- Create: `docs/tasks/PROGRESS.md`
- Create: `docs/tasks/reports/.gitkeep`, `docs/tasks/contract-deltas/.gitkeep`
- Modify: `config.py` (thêm 4 marker rỗng ở cuối file)

**Interfaces:**
- Produces: `docs/tasks/AGENT_RULES.md` — mọi prompt subagent ở Task 1–9 mở đầu bằng "Đọc `docs/tasks/AGENT_RULES.md` trước"
- Produces: marker `# === T01 ===`, `# === T03 ===`, `# === T07 ===`, `# === T15 ===` trong `config.py` — bốn agent này Edit đúng marker của mình, không tranh dòng cuối file

- [ ] **Step 1: Ghi baseline test — biết trước cái gì đang đỏ**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -20
```

Chép nguyên output vào `docs/tasks/PROGRESS.md` mục "Baseline". Nếu có test đỏ **từ trước**, ghi tên ra — nếu không, đợt 1 sẽ bị đổ oan.

- [ ] **Step 2: Bỏ gitignore cho `docs/tasks` và `docs/superpowers`**

`docs/` bị chặn cả thư mục thì không `!` lại được file bên trong. Phải đổi thành chặn nội dung rồi mở lại hai nhánh:

```bash
cd "d:/Study/innostar/Sever_test"
python - <<'PY'
from pathlib import Path
p = Path(".gitignore")
s = p.read_text(encoding="utf-8")
assert "\ndocs/\n" in s, "không tìm thấy dòng docs/ — đọc lại .gitignore"
s = s.replace("\ndocs/\n", "\ndocs/*\n!docs/tasks/\n!docs/superpowers/\n")
p.write_text(s, encoding="utf-8")
PY
git check-ignore -v docs/tasks/RUNBOOK.md docs/demo-format-bat-buoc.md
```

Kỳ vọng: `docs/demo-format-bat-buoc.md` **vẫn bị ignore** (54 KB, không thuộc plan này), `docs/tasks/RUNBOOK.md` **không còn dòng nào in ra**.

- [ ] **Step 3: Tạo `docs/tasks/AGENT_RULES.md`**

```markdown
# AGENT_RULES — luật bắt buộc cho mọi subagent

## A. Luật gốc (RUNBOOK mục 0)

1. Đọc `docs/tasks/CONTRACTS.md` TRƯỚC. Đó là nguồn sự thật. Task file mô tả
   việc phải làm; CONTRACTS mô tả thứ hai bên phải đồng ý.
2. Số dòng trong task file có thể đã trôi. VERIFY bằng grep/read trước khi sửa.
   Không sửa mù theo số dòng.
3. TDD: viết test đỏ trước, rồi mới viết code. Test nào đã liệt kê trong mục 4
   của task file thì phải có đủ, đúng tên.
4. KHÔNG báo xong khi chưa chạy lệnh trong mục DoD và nhìn thấy output xanh.
   Dán output THẬT vào báo cáo, không tóm tắt.
5. Task nào phụ thuộc repo khác mà repo đó chưa xong -> đánh dấu PARTIAL, ghi RÕ
   ca nào còn hỏng. Dùng `@pytest.mark.xfail(reason="Txx: ...")`.
   KHÔNG xoá test, KHÔNG báo xanh giả.
6. Gặp mục "Câu hỏi phải chốt" chưa có đáp án -> làm hết phần KHÔNG phụ thuộc
   câu đó, rồi HỎI trong báo cáo. Đừng tự chốt thay người dùng những câu 🔴.
7. Không mở rộng phạm vi. `handlers/find_object.py` và `handlers/read_money.py`
   KHÔNG ĐỤNG (spec mục 7). `handlers/describe_hazard.py` chỉ được thêm comment.
8. Ba nguyên tắc xuyên suốt ở CONTRACTS mục 0 thắng mọi tối ưu. Đặc biệt:
   `emergency_call` không đi qua bất kỳ bước xác minh nào.
9. Có bảng số thì mới được chốt. Ngưỡng nào chưa đo thì ghi "chưa đo", đừng copy
   số cũ của cấu hình khác.
10. Báo cáo cuối theo mẫu ở mục C dưới đây.

## B. Luật chống xung đột — vì bạn đang chạy song song với agent khác

B1. KHÔNG chạy bất kỳ lệnh git nào ghi vào repo: `add` `commit` `checkout`
    `reset` `stash` `merge` `rebase` `clean`. Chỉ đọc: `git status`, `git diff`,
    `git log`, `git grep` được phép. Phiên điều phối commit, không phải bạn.

B2. KHÔNG sửa bốn file này — chúng thuộc phiên điều phối:
      docs/tasks/CONTRACTS.md
      docs/tasks/00-INDEX.md
      docs/tasks/RUNBOOK.md
      docs/tasks/PROGRESS.md
    Cần đổi hợp đồng -> ghi đề nghị vào `docs/tasks/contract-deltas/<Txx>.md`
    theo mẫu ở mục D. Phiên điều phối sẽ gộp.

B3. Prompt của bạn có bảng "FILE BẠN ĐƯỢC SỬA". Ngoài bảng đó thì KHÔNG SỬA,
    kể cả khi task file bảo sửa. Gặp trường hợp đó -> ghi vào mục "Lệch với task
    file" của báo cáo rồi làm tiếp phần còn lại.

B4. Sửa `config.py`: chỉ thay thế đúng dòng marker `# === <Txx> ===` của bạn.
    Không thêm vào cuối file, không sửa marker của task khác.

B5. Chạy test bằng `.venv/Scripts/python.exe -m pytest <đường dẫn cụ thể> -q`.
    KHÔNG chạy `pytest tests` toàn bộ — agent khác đang sửa file khác, test của
    họ đỏ dở là bình thường và không phải việc của bạn.

## C. Mẫu báo cáo — ghi vào docs/tasks/reports/<Txx>.md

    ## Txx — <tên task>

    Trạng thái: DONE | PARTIAL | BLOCKED

    ### Đã làm
    - <mã spec>: <file:line đã sửa>

    ### Chưa làm & vì sao
    - <mã spec>: chặn bởi <Txx / câu hỏi mở số N ở CONTRACTS mục 7>

    ### Test
    ```
    $ .venv/Scripts/python.exe -m pytest <lệnh trong DoD> -q
    <dán output THẬT, không tóm tắt>
    ```
    - Thêm mới: N test
    - xfail: N test, lý do: ...
    - Sửa test cũ: <file>, vì sao

    ### Số đo (nếu có)
    - Ghi vào measurements/<file>.md

    ### Lệch với task file
    - <chỗ nào task file mô tả sai thực tế code>

    ### DoD
    - [x] ... / [ ] ... (ô nào chưa tick thì giải thích)

    ### Cần người dùng chốt
    - <câu hỏi 🔴 gặp phải>

Mục "Lệch với task file" là mục dễ bị bỏ qua nhất và có giá trị cao nhất — task
file viết từ spec, mà spec có chỗ đã trôi so với code.

## D. Mẫu contract-delta — ghi vào docs/tasks/contract-deltas/<Txx>.md

    ## Đề nghị sửa CONTRACTS.md — từ Txx

    ### Mục <số mục ở CONTRACTS>
    Hiện tại:
    ```
    <trích nguyên văn>
    ```
    Đề nghị:
    ```
    <bản mới>
    ```
    Vì sao: <một câu>
```

- [ ] **Step 4: Tạo `docs/tasks/PROGRESS.md`**

```markdown
# PROGRESS — trạng thái 23 task

Chỉ phiên điều phối ghi file này. Agent ghi `reports/<Txx>.md`.

## Baseline (điền ở Task 0 bước 1)

```
<dán output pytest tests -q>
```

## Bảng trạng thái

| Task | Đợt | Trạng thái | Agent | Report | Ghi chú |
|---|---|---|---|---|---|
| G10 (T02§2.1) | 0 | ⬜ | | | chỉ đo |
| H0 (T15§H0) | 0 | ⬜ | | | chỉ đo |
| P7 (T20§P7) | 0 | ⬜ | | | chỉ đọc code |
| T01 | 1 | ⬜ | | | |
| T03 | 1 | ⬜ | | | |
| T04 | 1 | ⬜ | | | |
| T02 (còn lại) | 2 | ⬜ | | | |
| T07 | 2 | ⬜ | | | |
| T15 | 2 | ⬜ | | | |
| T20 (còn lại) | 2 | ⬜ | | | |
| T22 | 2 | ⬜ | | | firmware |
| T05 | 3 | ⬜ | | | |
| T06 | 3 | ⬜ | | | |
| T08 | 4 | ⬜ | | | PARTIAL nếu chưa P1/P2 |
| T09 | 4 | ⬜ | | | 🔴 khoá an toàn |
| T10 | 4 | ⬜ | | | |
| T12 | 4 | ⬜ | | | |
| T14 | 4 | ⬜ | | | |
| T16 | 4 | ⬜ | | | |
| T11 | 5 | ⬜ | | | 🔴 PARTIAL, ⛔ Farefeed |
| T13 | 5 | ⬜ | | | |
| T23 | 5 | ⬜ | | | |
| T17 | 6 | ⬜ | | | F2 KHÔNG thi công |
| T18 | 6 | ⬜ | | | |
| T19 | 6 | ⬜ | | | |
| T21 | 7 | ⬜ | | | |

Ký hiệu: ⬜ chưa · 🟡 đang chạy · ✅ DONE · 🟠 PARTIAL · ⛔ BLOCKED

## Câu hỏi 🔴 agent đẩy lên (phiên điều phối gom, hỏi người dùng một lượt/đợt)

| Đợt | Task | Câu hỏi | Đã chốt? |
|---|---|---|---|
```

- [ ] **Step 5: Seed marker `config.py` — chống bốn agent tranh dòng cuối file**

Bốn task đụng `config.py` theo `00-INDEX.md`: T01, T03, T07, T15. T01/T03 ở đợt 1 (tuần tự, không sao), T07/T15 ở đợt 2 (song song, có sao). Seed marker cho cả bốn để agent nào cũng có mỏ neo Edit **duy nhất** của riêng mình:

```bash
cd "d:/Study/innostar/Sever_test"
cat >> config.py <<'PY'


# ─── Vùng cấu hình theo task (docs/tasks/) ────────────────────────────────
# Mỗi task chỉ thay marker của chính nó. Marker là mỏ neo Edit duy nhất, để
# nhiều agent chạy song song không cùng tranh dòng cuối file.

# === T01 ===
# === T03 ===
# === T07 ===
# === T15 ===
PY
.venv/Scripts/python.exe -c "import config; print('config.py import OK')"
```

Kỳ vọng: in ra `config.py import OK`.

- [ ] **Step 6: Tạo thư mục báo cáo & delta**

```bash
cd "d:/Study/innostar/Sever_test"
mkdir -p docs/tasks/reports docs/tasks/contract-deltas
touch docs/tasks/reports/.gitkeep docs/tasks/contract-deltas/.gitkeep
ls docs/tasks/
```

- [ ] **Step 7: Commit**

```bash
cd "d:/Study/innostar/Sever_test"
git add .gitignore config.py docs/tasks docs/superpowers
git commit -m "chore(tasks): hạ tầng điều phối subagent cho 23 task

- .gitignore: mở lại docs/tasks + docs/superpowers (trước đó docs/ bị chặn cả
  cây, mọi bảng số đo nằm ngoài git)
- AGENT_RULES.md: luật gốc + luật chống xung đột khi chạy song song
- PROGRESS.md: bảng trạng thái 23 task
- config.py: marker theo task, chống agent tranh dòng cuối file

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 1: Đợt 0 — ba phép đo, chưa code gì

**Files:**
- Create: `docs/tasks/measurements/G10.md`, `H0-blur-720p.md`, `P7-error-matrix.md`
- Create: `docs/tasks/reports/T02-G10.md`, `T15-H0.md`, `T20-P7.md`
- Create: `tools/measure_chunked_end.sh`

**Interfaces:**
- Consumes: `docs/tasks/AGENT_RULES.md` (Task 0)
- Produces: ngưỡng Laplacian trên 720p (H0) → T15 và T17 dùng · bảng mã lỗi hai chiều (P7) → T20 và T06/D4 dùng · kết luận miếng kết thúc chunked (G10) → T02 và T21 dùng

> Ba việc này rẻ và **đổi mốc so sánh của mọi thứ sau đó**. G10 có thể đang là **30 giây mỗi lượt** — lớn hơn tổng mọi khoản tối ưu còn lại trong spec cộng lại.

**Chủ sở hữu file trong đợt này:** ba agent ghi ba file measurement khác nhau + ba file report khác nhau. Chỉ G10 tạo file code (`tools/measure_chunked_end.sh`). Không chồng lấn.

- [ ] **Step 1: Kiểm điều kiện vào — server có chạy không**

G10 cần server sống ở cả `localhost:8000` lẫn tunnel.

```bash
cd "d:/Study/innostar/Sever_test"
curl -s -o /dev/null -w "localhost:8000 -> %{http_code}\n" http://localhost:8000/docs
```

Không phải `200` → chạy `./start-demo.ps1` trước, và lấy URL tunnel từ output của nó. Không có tunnel thì vẫn dispatch agent G10 nhưng **báo trước cho nó là chỉ đo được localhost** — nửa phép đo này vẫn có giá trị (loại trừ Starlette), nhưng chưa kết luận được.

- [ ] **Step 2: Dispatch ba agent song song — cả ba trong MỘT message**

```
Agent(subagent_type: "general-purpose", run_in_background: true,
      description: "Đo G10 chunked end",
      prompt: """
Repo: D:\Study\innostar\Sever_test

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md   (luật bắt buộc — đọc trước, tuân đủ cả mục A và B)
  2. docs/tasks/CONTRACTS.md     (nguồn sự thật)
  3. docs/tasks/T02-chunked-end-tts-rate.md

Việc: THỰC HIỆN MỤC 2.1 (G10) của T02. CHỈ ĐO, KHÔNG SỬA CODE SERVER.

FILE BẠN ĐƯỢC SỬA (ngoài bảng này không sửa gì):
  - tools/measure_chunked_end.sh          (tạo mới)
  - docs/tasks/measurements/G10.md        (tạo mới)
  - docs/tasks/reports/T02-G10.md         (tạo mới)

Cách làm:
  1. Viết tools/measure_chunked_end.sh — chạy lại được, nhận endpoint làm tham
     số, dùng `curl -v --raw` và tìm chuỗi `0\r\n\r\n` ở cuối thân.
  2. Chạy HAI lần: một qua http://localhost:8000/process, một qua URL tunnel
     Cloudflare. Không có tunnel thì đo localhost và GHI RÕ là thiếu nửa kia.
  3. Ghi vào measurements/G10.md: ngày đo, endpoint đầy đủ, output curl thật,
     và kết luận theo bảng ở T02 mục 2.1:
       - miếng kết thúc CÓ tới  -> README firmware sai, sửa README, không đụng server
       - KHÔNG tới              -> phải đóng kết nối tường minh
       - localhost có / tunnel không -> thủ phạm là tunnel, KHÔNG phải Starlette
  4. DỪNG LẠI. Không tự sửa gì. Phần sửa thuộc Đợt 2.

Xong thì ghi báo cáo theo mẫu ở AGENT_RULES mục C vào docs/tasks/reports/T02-G10.md.
""")

Agent(subagent_type: "general-purpose", run_in_background: true,
      description: "Đo H0 blur 720p",
      prompt: """
Repo: D:\Study\innostar\Sever_test

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md
  2. docs/tasks/CONTRACTS.md
  3. docs/tasks/T15-ocr-quality.md   (CHỈ phần H0, phần còn lại làm ở Đợt 2)

Việc: H0 — sửa tài liệu về 1280×720 và ĐO LẠI ngưỡng Laplacian trên ảnh 720p.

Bối cảnh đã chốt (CONTRACTS quyết định #6): camera thật là 1280×720, quality 18
trên thang esp32-camera 0-63 (NHỎ = NÉT). Tài liệu đang ghi 1600x1200 — sai.
Ngưỡng Laplacian hiện có đo trên độ phân giải cũ nên đang so sai mốc.

FILE BẠN ĐƯỢC SỬA:
  - docs/tasks/measurements/H0-blur-720p.md   (tạo mới)
  - docs/tasks/reports/T15-H0.md              (tạo mới)
  - CLAUDE.md                                  (chỉ dòng nói 1600x1200)
  - pipeline/image_quality.py                  (CHỈ comment mô tả độ phân giải ở
                                                đầu file, KHÔNG đổi ngưỡng — đổi
                                                ngưỡng là việc của Đợt 2)

Cách làm:
  1. Grep tìm mọi chỗ ghi 1600x1200 / 1600×1200 trong repo này. Liệt kê ra.
     Sửa những chỗ nằm trong bảng FILE BẠN ĐƯỢC SỬA. Chỗ nằm ngoài -> ghi ra
     mục "Lệch với task file" để phiên điều phối xử.
  2. Đo Laplacian variance trên ảnh 720p thật. Không có ảnh fixture 720p thì
     resize ảnh có sẵn về 1280x720 và GHI RÕ là ảnh resize, không phải chụp thật
     — đó là số tạm, không phải số chốt.
  3. Ghi bảng số vào measurements/H0-blur-720p.md: ngày, nguồn ảnh, cỡ mẫu,
     variance của ảnh nét / ảnh mờ vừa / ảnh mờ hẳn, và ngưỡng ĐỀ NGHỊ.
  4. Quy mọi thang chất lượng trong tài liệu về 0-63 (nhỏ = nét).
  5. KHÔNG đổi ngưỡng trong code. Chỉ đề nghị số trong file đo.

Xong thì báo cáo theo mẫu AGENT_RULES mục C.
""")

Agent(subagent_type: "general-purpose", run_in_background: true,
      description: "Dựng P7 error matrix",
      prompt: """
Repo: D:\Study\innostar\Sever_test
Repo app Android (CHỈ ĐỌC): D:\Study\innostar\app_demo_backend\apps\android
Repo server app (CHỈ ĐỌC): D:\Study\innostar\app_demo_backend\apps\backend

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md
  2. docs/tasks/CONTRACTS.md         (đặc biệt mục 5.5 — đang bỏ trống, bạn điền)
  3. docs/tasks/T20-error-contract.md
  4. endpoint.md                     (hợp đồng endpoint đã chép sang repo này)

Việc: P7 — dựng bảng đối chiếu mã lỗi HAI CHIỀU. ĐỌC CODE, CHƯA SỬA GÌ.

Bối cảnh: hiện có 9 mã MỒ CÔI (server kính có câu trả lời, app không bao giờ
phát) và 7 mã KHÔNG CÂU (app phát, server kính không có câu). Con số này lấy từ
task file — VERIFY lại bằng grep, đừng chép.

FILE BẠN ĐƯỢC SỬA:
  - docs/tasks/measurements/P7-error-matrix.md   (tạo mới)
  - tests/fixtures/app_error_codes.txt           (tạo mới)
  - docs/tasks/reports/T20-P7.md                 (tạo mới)
KHÔNG sửa handlers/result_speech.py — đó là Đợt 2.

Cách làm:
  1. Chiều 1: liệt kê mọi mã trong `_ERROR_SPEECH` của handlers/result_speech.py
     (grep tìm, số dòng trong task file có thể đã trôi).
  2. Chiều 2: liệt kê mọi mã lỗi app Android và server app THẬT SỰ phát ra.
     Grep trong hai repo kia. Ghi cả file:line nguồn.
  3. Ghi tests/fixtures/app_error_codes.txt — danh sách mã app phát, kèm NGÀY và
     COMMIT HASH của repo app lúc bạn đọc (`git -C <repo app> rev-parse HEAD`).
     Không có hash thì bảng này vô giá trị sau một tuần.
  4. Dựng bảng trong measurements/P7-error-matrix.md, mỗi dòng một mã, cột:
       mã | app có phát? (file:line) | server có câu? (file:line) | retryable/terminal | quyết định (a) thêm câu / (b) xoá mã
  5. Đề nghị `_DEFAULT_POLICY` — mã lạ rơi vào đâu. Nguyên tắc 21.7: KHÔNG mã
     nào được rơi vào im lặng.
  6. Ghi đề nghị nội dung CONTRACTS mục 5.5 vào
     docs/tasks/contract-deltas/T20.md theo mẫu AGENT_RULES mục D.
     KHÔNG tự sửa CONTRACTS.md.

Câu hỏi 🔴 chưa chốt liên quan: "App có kiểm được địa điểm không?" (chặn
INVALID_DESTINATION / D4). Tìm câu trả lời trong code app; không tìm được thì
ghi vào mục "Cần người dùng chốt", đừng tự chốt.

Xong thì báo cáo theo mẫu AGENT_RULES mục C.
""")
```

- [ ] **Step 3: Đọc ba báo cáo, kiểm ba file đo có số thật**

```bash
cd "d:/Study/innostar/Sever_test"
cat docs/tasks/reports/T02-G10.md docs/tasks/reports/T15-H0.md docs/tasks/reports/T20-P7.md
ls -la docs/tasks/measurements/
```

Cổng: mỗi file measurement phải có **ngày**, **endpoint/cấu hình**, **số thật**. File nào chỉ có chữ mà không có số → gửi lại agent đó bằng `SendMessage`, đừng tự điền hộ (GC20).

- [ ] **Step 4: Gộp contract-delta của T20 vào `CONTRACTS.md` mục 5.5**

Đọc `docs/tasks/contract-deltas/T20.md`, tự tay sửa `CONTRACTS.md` mục 5.5 từ "🔴 chưa chốt, xem T20" thành bảng thật. Giữ nguyên các mục khác.

- [ ] **Step 5: Test không được đỏ thêm**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
```

Kỳ vọng: giống hệt baseline ở Task 0 bước 1. Đợt 0 gần như không đụng code — đỏ thêm là dấu hiệu agent H0 đã sửa `image_quality.py` quá tay.

- [ ] **Step 6: Cập nhật PROGRESS + commit**

Tick 3 dòng đợt 0 trong `docs/tasks/PROGRESS.md` thành ✅, điền câu hỏi 🔴 agent đẩy lên vào bảng cuối file. Tick 3 ô đợt 0 ở `RUNBOOK.md` mục 6.

```bash
cd "d:/Study/innostar/Sever_test"
git add docs/tasks tools/measure_chunked_end.sh tests/fixtures/app_error_codes.txt CLAUDE.md pipeline/image_quality.py
git commit -m "measure: đợt 0 — G10 chunked end, H0 blur 720p, P7 error matrix

Ba phép đo đổi mốc so sánh của mọi task sau. Chưa sửa logic server.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Khởi động bốn việc chờ người ngoài — HÔM NAY, song song với đợt 1**

Không phải việc code, nhưng thời gian chờ dài nhất. Hỏi người dùng bốn câu, ghi vào bảng cuối `PROGRESS.md`:

1. Đã liên hệ Grab xin quyền partner Farefeed chưa? *(chặn T11 R1 R2 R3 R5)*
2. Team app có làm được P1 `contact_list` không? *(quyết T08 chạy đủ hay nửa vời)*
3. Ai geocode `address → lat/lng` — server app 8001? *(chặn T11 P4 P5)*
4. Ngân sách `ocr` là bao nhiêu? *(chặn T15 nghiệm thu, T21)*

---

## Task 2: Đợt 1 — nền tảng T01 → T03 → T04 (tuần tự)

**Files:**
- T01: `app.py`, `config.py` (marker `# === T01 ===`), `tests/test_protocol_ids.py`, firmware `src/net/api_client.cpp`
- T03: `handlers/action_flow.py`, `config.py` (marker `# === T03 ===`), `tests/test_pending.py`, `tests/test_session_isolation.py`, `tests/test_device_state.py`
- T04: `pipeline/router.py`, `tests/test_router_priority.py`, `tests/test_bargein.py`, `tests/test_router.py`

**Interfaces:**
- Consumes: AGENT_RULES (Task 0)
- Produces (T01): `contextvars.ContextVar` mang `device_id` + `turn_id` xuống handler — **T03 T17 T18 T19 và cả nhóm B, D đều đọc**
- Produces (T03): `Session` khoá theo `device_id`, `Pending` 9 trường có `kind` quyết định TTL, `generation` counter — **T04 T05 T06 và 6 task chức năng đọc**
- Produces (T04): thứ tự 6 bước router + khung slot validator — **T08 T10 T12 cắm danh sách từ chối vào**

> **Ba task này KHÔNG song song được.** T03 sửa file T01 vừa sửa, T04 sửa cái T03 vừa dựng. Chạy chồng lên nhau là hỏng. Mỗi bước dispatch **một** agent, đợi xong, kiểm, rồi mới dispatch bước sau.

- [ ] **Step 1: Dispatch T01, đợi xong**

```
Agent(subagent_type: "general-purpose", run_in_background: false,
      description: "T01 protocol ids",
      prompt: """
Repo server kính: D:\Study\innostar\Sever_test
Repo firmware:    D:\Study\innostar\your-eyes-esp32-firmware

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md
  2. docs/tasks/CONTRACTS.md      (đặc biệt mục 2.1)
  3. docs/tasks/T01-protocol-ids.md

Điều kiện vào: không có. Đây là task chặn nhiều nhất trong cả spec.

FILE BẠN ĐƯỢC SỬA:
  server kính:
    - app.py
    - config.py  -> CHỈ thay dòng `# === T01 ===`, không thêm cuối file
    - tests/test_protocol_ids.py                       (tạo mới)
    - docs/tasks/reports/T01.md                        (tạo mới)
    - docs/tasks/contract-deltas/T01.md                (nếu cần đổi hợp đồng)
  firmware:
    - src/net/api_client.cpp

Ba điểm dễ làm sai nhất, đọc kỹ:

(1) Header, KHÔNG phải form field. Server phải đọc được X-Device-Id TRƯỚC khi
    body upload xong — đó là toàn bộ lý do chọn header.

(2) Thiếu X-Device-Id -> TỪ CHỐI RÕ RÀNG. CẤM rơi ngầm về
    config.VISIONCARE_DEVICE_ID. Rơi ngầm biến lỗi cấu hình firmware thành trộn
    session giữa hai người dùng thật, và KHÔNG CÓ LOG NÀO BÁO. Giai đoạn chuyển:
    cho fallback nhưng logger.warning MỖI LẦN, có cờ config.REQUIRE_DEVICE_ID
    bật được để test ca từ chối.

(3) device_id xuống handler bằng contextvars.ContextVar đặt ở app.py, KHÔNG
    thêm tham số vào chữ ký handler. Có 15 handler — thêm tham số là 15 chỗ sửa
    và 15 chỗ quên.

Firmware: thêm 3 header + setNoDelay(true) trên socket THẬT của api_client.cpp
(wifi_manager.cpp:520 đã có nhưng đó là đường chẩn đoán, không phải socket thật).
Ghi comment nói rõ X-Turn-Id có HAI vai trò: idempotency và barge-in (T04/G4).

Test: 7 ca ở mục 4.1 và 4.2 của task file, đúng tên.
DoD: .venv/Scripts/python.exe -m pytest tests/test_protocol_ids.py -q

Câu hỏi 🔴 CHƯA CHỐT — làm phần không phụ thuộc rồi HỎI, đừng tự chốt:
  - Cửa sổ idempotency bao lâu? (đề xuất 60 s — dùng tạm, ghi là tạm)
  - device_id lấy từ MAC WiFi hay NVS?
  - Giai đoạn chuyển kéo dài bao lâu trước khi REQUIRE_DEVICE_ID=1?

Ô DoD "ba header ra dây thật từ board" cần phần cứng — bạn không có. Để trống,
ghi rõ là chờ kiểm tay. ĐỪNG tick.

Báo cáo theo mẫu AGENT_RULES mục C vào docs/tasks/reports/T01.md.
""")
```

- [ ] **Step 2: Cổng T01**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_protocol_ids.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -rn "VISIONCARE_DEVICE_ID" app.py handlers/ pipeline/
```

Cổng: `test_protocol_ids.py` xanh đủ 7 ca · tổng test không đỏ thêm so với baseline · grep cuối **không** ra chỗ nào trong handler còn đọc thẳng hằng số (GC18).

- [ ] **Step 3: Review T01 bằng subagent trước khi xây T03 lên trên**

```
Agent(subagent_type: "cavecrew-reviewer", run_in_background: false,
      description: "Review T01 diff",
      prompt: """
Review diff chưa commit trong D:\Study\innostar\Sever_test (git diff + git diff --cached
+ file mới trong git status).

Bối cảnh: đây là T01 (docs/tasks/T01-protocol-ids.md) — task nền, T03/T04/T17/T18/T19
xây lên trên. Sai ở đây là sửa lại rất đắt.

Soi bốn thứ, bỏ qua nit định dạng:
  1. Có đường nào còn rơi ngầm về config.VISIONCARE_DEVICE_ID mà không warning không?
  2. ContextVar có bị rò giữa hai request đồng thời không? (contextvars trong async
     phải set trong scope request, không set ở module level)
  3. Idempotency: hai POST cùng X-Turn-Id — lượt hai có thật sự KHÔNG gọi API,
     hay chỉ không ghi kết quả?
  4. Test có thật sự đỏ trước khi có code không, hay chỉ assert vào cái sẵn có?
""")
```

Xử findings 🔴/🟠 rồi mới đi tiếp. Findings nhỏ ghi vào PROGRESS, làm sau.

- [ ] **Step 4: Commit T01**

```bash
cd "d:/Study/innostar/Sever_test"
git add app.py config.py tests/test_protocol_ids.py docs/tasks
git commit -m "feat(protocol): X-Device-Id / X-Turn-Id bắt buộc trên /process (T01/F1)

device_id xuống handler qua ContextVar, không thêm tham số vào 15 chữ ký.
Thiếu X-Device-Id -> từ chối; giai đoạn chuyển có REQUIRE_DEVICE_ID=0 + warning.
X-Turn-Id chống gửi lặp trong cửa sổ 60s (tạm, chờ chốt).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git -C "d:/Study/innostar/your-eyes-esp32-firmware" add -A && \
git -C "d:/Study/innostar/your-eyes-esp32-firmware" commit -m "feat(net): gửi X-Device-Id/X-Turn-Id/X-Capture-Ts + setNoDelay trên socket thật (T01/F1,F7)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Dispatch T03, đợi xong**

```
Agent(subagent_type: "general-purpose", run_in_background: false,
      description: "T03 session pending",
      prompt: """
Repo: D:\Study\innostar\Sever_test

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md
  2. docs/tasks/CONTRACTS.md          (đặc biệt mục 4.1 — TTL theo kind)
  3. docs/tasks/T03-session-pending.md
  4. docs/tasks/reports/T01.md        (T01 vừa xong — ContextVar tên gì, đọc ra sao)

Điều kiện vào: T01 XONG. device_id đã có trong ContextVar — dùng nó, đừng dựng lại.

FILE BẠN ĐƯỢC SỬA:
  - handlers/action_flow.py
  - config.py  -> CHỈ thay dòng `# === T03 ===`
  - tests/test_pending.py            (tạo mới)
  - tests/test_session_isolation.py  (tạo mới)
  - tests/test_device_state.py       (viết lại)
  - docs/tasks/reports/T03.md
  - docs/tasks/contract-deltas/T03.md (nếu cần)

⚠️ QUAN TRỌNG NHẤT: `generation` counter (G2) PHẢI có mặt từ commit đầu, kể cả
khi T04 chưa dùng tới. Thêm sau rất đắt — nó xuyên qua mọi chỗ tạo/đọc pending.

TTL theo kind (CONTRACTS mục 4.1, đã chốt, KHÔNG tự đổi):
  confirm 25 s · select 45 s · select bảng giá xe 45 s · fill 120 s
`asked_at` tính TỪ LÚC TTS PHÁT XONG, không phải lúc server tạo pending. Ước
lượng được thì ước lượng, nhưng phải có comment ghi rõ đây là ước lượng.

MỘT pending / device. Không stack, không lồng (CONTRACTS quyết định #9). Assert
trong CODE, không chỉ trong test.

HAI CHỖ KHÔNG ĐỤNG:
  - Chỗ hở "bài tự hết" ở handlers/action_flow.py:78-86 GIỮ NGUYÊN. Đã đo, đã
    chấp nhận. Cấm thay bằng TTL đoán mò.
  - `_ACTIVE.clear()` ở action_flow.py:136 thì NGƯỢC LẠI — phải bỏ. Đọc task file.
Số dòng có thể đã trôi sau T01 — grep verify, đừng sửa mù.

DoD:
  .venv/Scripts/python.exe -m pytest tests/test_pending.py tests/test_session_isolation.py tests/test_device_state.py -q

Câu hỏi 🔴 chưa chốt: cache vị trí toàn cục hay theo device? Làm phần không phụ
thuộc, rồi hỏi.

Báo cáo vào docs/tasks/reports/T03.md.
""")
```

- [ ] **Step 6: Cổng T03**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_pending.py tests/test_session_isolation.py tests/test_device_state.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -n "generation" handlers/action_flow.py
sed -n '70,95p' handlers/action_flow.py
```

Cổng: 3 file test xanh · `generation` có mặt · chỗ hở "bài tự hết" **vẫn còn nguyên** (đọc bằng mắt đoạn `sed` in ra).

- [ ] **Step 7: Commit T03**

```bash
cd "d:/Study/innostar/Sever_test"
git add handlers/action_flow.py config.py tests/test_pending.py tests/test_session_isolation.py tests/test_device_state.py docs/tasks
git commit -m "feat(session): Session khoá theo device, Pending có kind + TTL + generation (T03/B2,B4,B6,B7)

generation counter có từ commit đầu dù T04 chưa dùng — retrofit sau rất đắt.
TTL: confirm 25s / select 45s / fill 120s. Một pending / device, có assert.
Chỗ hở 'bài tự hết' giữ nguyên có chủ đích.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Dispatch T04, đợi xong**

```
Agent(subagent_type: "general-purpose", run_in_background: false,
      description: "T04 router bargein",
      prompt: """
Repo: D:\Study\innostar\Sever_test

Đọc theo thứ tự:
  1. docs/tasks/AGENT_RULES.md
  2. docs/tasks/CONTRACTS.md          (mục 0 nguyên tắc 1, và mục 4.3 thứ tự router)
  3. docs/tasks/T04-router-bargein.md
  4. docs/tasks/reports/T03.md        (generation counter tên gì, pending đọc ra sao)

Điều kiện vào: T01 + T03 XONG.

FILE BẠN ĐƯỢC SỬA:
  - pipeline/router.py
  - tests/test_router_priority.py   (tạo mới)
  - tests/test_bargein.py           (tạo mới)
  - tests/test_router.py            (sửa)
  - tests/test_device_state.py      (sửa tiếp phần barge-in)
  - docs/tasks/reports/T04.md
KHÔNG sửa handlers/action_flow.py — T03 vừa chốt xong.

🔴 THỨ TỰ 6 BƯỚC — đây là thứ DỄ BỊ VIẾT LẠI SAI NHẤT TRONG CẢ SPEC:

  1. EMERGENCY                 <- tuyệt đối
  2. PENDING TẤT ĐỊNH          <- ừ/không/số thứ tự/thôi/nói lại
  3. STOP / LỆNH TOÀN CỤC      <- chèn vào ĐÂY
  4. PENDING ĐIỀN SLOT         <- qua slot validator
  5. CANCEL / REPEAT
  6. INTENT DETECT

Bước 3 nằm GIỮA hai pha pending — không phải trên cả hai, không phải dưới cả
hai. Viết đúng thứ tự trong code, kèm comment trỏ về spec 21.1.

Nguyên tắc 1 của CONTRACTS: trạng thái là GỢI Ý CHO BỘ PHÂN LOẠI, KHÔNG PHẢI
HÀNG RÀO Ở ROUTER. Người dùng phải nói được bất cứ gì, bất cứ lúc nào. Hai
nhánh bypass ở router.py:71-82 phải xoá (grep verify số dòng).

Barge-in (G4): X-Turn-Id mới phải huỷ ĐƯỢC CẢ LLM stream LẪN TTS stream của
lượt cũ. Dùng generation counter của T03.

Regex barge-in cục bộ CHỈ chạy khi có task đang chạy — chạy luôn là tốn vô ích.

Lock phải đo được ≤ 5 ms. Test 4.3 chạy THẬT, không skip.

DoD:
  .venv/Scripts/python.exe -m pytest tests/test_router.py tests/test_router_priority.py tests/test_bargein.py tests/test_device_state.py -q

Slot validator: chỉ dựng KHUNG. T08/T10/T12 sẽ cắm danh sách từ chối của họ vào
ở đợt 4. Ghi rõ interface khung đó trong báo cáo — ba task kia đọc để cắm đúng.

Báo cáo vào docs/tasks/reports/T04.md.
""")
```

- [ ] **Step 9: Cổng T04 — kiểm bằng mắt thứ tự 6 bước**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_router.py tests/test_router_priority.py tests/test_bargein.py tests/test_device_state.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -n -E "EMERGENCY|PENDING|STOP|CANCEL|INTENT|21\.1" pipeline/router.py
```

Cổng: 4 file test xanh · grep in ra 6 mốc **đúng thứ tự trên xuống** · `STOP` nằm **giữa** hai `PENDING`. Sai thứ tự → gửi lại agent, đây là chỗ đắt nhất để sai.

- [ ] **Step 10: Review đợt 1 + commit T04**

```
Agent(subagent_type: "cavecrew-reviewer", run_in_background: false,
      description: "Review đợt 1",
      prompt: """
Review 3 commit cuối trong D:\Study\innostar\Sever_test (git log -3 --stat, git diff HEAD~3).

Bối cảnh: T01 (device/turn id) + T03 (session/pending) + T04 (router/barge-in).
Đây là nền — 20 task còn lại xây lên trên.

Soi:
  1. Thứ tự 6 bước router có đúng CONTRACTS mục 4.3 không? STOP có nằm GIỮA hai
     pha pending không?
  2. generation counter có đủ để huỷ CẢ LLM stream lẫn TTS stream không, hay chỉ
     đánh dấu rồi vẫn chạy tiếp?
  3. Có state toàn cục nào còn chưa khoá theo device_id không?
     (trước T01 có: _LAST_IDS, _ACTIVE, _HISTORY, _LOCATION_CACHE)
  4. Có test nào xanh vì mock quá tay — mock chính cái đang muốn kiểm?
Bỏ qua nit định dạng.
""")
```

```bash
cd "d:/Study/innostar/Sever_test"
git add pipeline/router.py tests/ docs/tasks
git commit -m "feat(router): 6 bước ưu tiên + barge-in theo turn (T04/B1,21.1,G2,G4)

Xoá 2 nhánh bypass ở router — trạng thái là gợi ý cho bộ phân loại, không phải
hàng rào ở router. STOP nằm giữa hai pha pending, đúng 21.1.
X-Turn-Id mới huỷ cả LLM stream lẫn TTS stream qua generation của T03.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Cập nhật `PROGRESS.md`: T01 T03 T04 → ✅. Tick 3 ô đợt 1 ở `RUNBOOK.md`.

---

## Task 3: Đợt 2 — năm nhánh song song

**Files:**

| Agent | File được sửa |
|---|---|
| **T02** (còn lại) | `app.py`, `tests/test_audio_contract.py`, `tools/measure_chunked_end.sh`, `docs/tasks/measurements/G11.md` |
| **T07** Vị trí | `handlers/chat.py`, `config.py` marker `# === T07 ===`, `tests/test_location_degraded.py`, `tests/test_chat.py` |
| **T15** OCR chất lượng | `pipeline/image_quality.py`, `pipeline/phrases.py`, `models/ocr/prompts.py`, `models/vlm/client.py`, `config.py` marker `# === T15 ===`, `tests/test_ocr_quality.py`, `tools/bench_ocr_matrix.py`, `measurements/H4.md` |
| **T20** (còn lại) | `handlers/result_speech.py`, `tests/test_error_contract.py` |
| **T22** TLS | **chỉ repo firmware** + `measurements/F9.md` |

**Interfaces:**
- Consumes: T01 ContextVar · T03 Session/Pending · đợt 0: `G10.md`, `H0-blur-720p.md`, `P7-error-matrix.md`
- Produces (T15): ngưỡng blur theo tầng trên 720p → **T17 dùng** · `GEMINI_OCR_MODEL` tách riêng → **T14 dùng**
- Produces (T20): `_DEFAULT_POLICY` + bảng mã lỗi chốt → **T06/D4 và T10/D4 gỡ xfail nhờ nó**
- Produces (T22): `API_USE_TLS 1` + `measurements/F9.md` → **T18 đo RAM và T21 đo ngân sách đều phải trên bản này**
- Produces (T02): kết luận G10 + tỉ lệ G11 → **T21**

**Vì sao năm cái này song song được:** `00-INDEX.md` bảng "file code → task" cho thấy năm nhóm file rời nhau. Hai chỗ có thể đụng — `config.py` (T07 và T15) đã tách bằng marker riêng ở Task 0; `CONTRACTS.md` thì không ai được sửa (GC8).

- [ ] **Step 1: Kiểm điều kiện vào**

```bash
cd "d:/Study/innostar/Sever_test"
ls docs/tasks/measurements/G10.md docs/tasks/measurements/H0-blur-720p.md docs/tasks/measurements/P7-error-matrix.md
grep -c "=== T07 ===\|=== T15 ===" config.py
git log --oneline -4
```

Cổng: 3 file đo có mặt · 2 marker còn nguyên trong `config.py` · 3 commit đợt 1 đã vào.

- [ ] **Step 2: Dispatch năm agent — cả năm trong MỘT message**

Prompt chung của mọi agent đợt này mở đầu giống nhau:

```
Repo: D:\Study\innostar\Sever_test
Đọc: 1) docs/tasks/AGENT_RULES.md  2) docs/tasks/CONTRACTS.md  3) <task file>
Điều kiện vào: T01 T03 T04 đã xong (đọc docs/tasks/reports/T01.md, T03.md, T04.md
nếu cần biết interface). Đợt 0 đã đo xong — ĐỌC file measurement liên quan trước
khi chọn số, ĐỪNG đo lại.
Bạn đang chạy SONG SONG với 4 agent khác. Tuân AGENT_RULES mục B tuyệt đối.
```

Rồi riêng từng agent:

```
Agent(#1, general-purpose, background) — "T02 phần còn lại: khoá F8 + đo G11"
  Task file: docs/tasks/T02-chunked-end-tts-rate.md, mục 2.2, 2.3, 4.2, 4.3
  ĐỌC TRƯỚC: docs/tasks/measurements/G10.md — G10 đã đo ở đợt 0, kết luận nằm
  trong đó. Thi hành kết luận đó:
    - miếng kết thúc CÓ tới -> sửa README firmware, KHÔNG đụng app.py
    - KHÔNG tới             -> đóng kết nối tường minh sau chunk cuối
  FILE ĐƯỢC SỬA: app.py, tests/test_audio_contract.py (mới),
    docs/tasks/measurements/G11.md (mới), docs/tasks/reports/T02.md,
    và README của repo firmware nếu G10 kết luận vậy.
  Năm test khoá F8 (mục 4.2), đúng tên:
    test_adpcm_is_mono_16k
    test_prelude_is_first_60_bytes
    test_prelude_size_field_when_length_unknown
    test_x_audio_format_matches_body_magic
    test_wav_format_never_for_board
  Đây là KHOÁ LẠI hành vi đúng đang có, không phải thêm tính năng. Board tin 4
  BYTE ĐẦU CỦA THÂN, không tin header HTTP — đi nhầm nhánh ADPCM/PCM là SNR
  -11 dB và KHÔNG CÓ LOG NÀO BÁO.
  G11: test_tts_release_rate_at_least_1_30x, đánh @pytest.mark.perf, KHÔNG chạy
  trong CI mặc định. Đo tỉ lệ (giây tiếng)/(giây đồng hồ) từ chunk đầu tới chunk
  cuối, ngưỡng ≥ 1.30. Ghi SỐ THẬT vào measurements/G11.md.
  Không đạt 1.30 -> ĐỪNG tự sửa. Ghi vào báo cáo: flush từng câu (rẻ) hay sinh
  song song (đắt) — để người dùng chốt.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_audio_contract.py -q
       .venv/Scripts/python.exe -m pytest tests/test_audio_contract.py -m perf -q

Agent(#2, general-purpose, background) — "T07 vị trí"
  Task file: docs/tasks/T07-location.md  (C1-C5, P8, P9)
  FILE ĐƯỢC SỬA: handlers/chat.py, config.py (CHỈ dòng `# === T07 ===`),
    tests/test_location_degraded.py (mới), tests/test_chat.py,
    docs/tasks/reports/T07.md
  Trọng tâm: `_location_text()` KHÔNG BAO GIỜ được trả "". Cache rỗng -> trả
  khối cấm bịa. Trả "" là prompt vừa nói "chưa có vị trí" vừa bảo LLM "tra quanh
  người dùng" — LLM sẽ bịa một thành phố.
  loop() và toàn thân refresh_location_once phải có try/except. result['lat']
  đổi sang .get() — thiếu thì coi như hỏng, không ném.
  Backoff 15/30/60 -> 240, ĐO ĐƯỢC bằng test. logger.error sau 3 lần hỏng liên tiếp.
  to_vn_time_str: HOẶC chạy đúng HOẶC xoá hẳn — không để dạng hỏng câm.
  P8 (getCurrentLocation + play-services-location) nằm ở repo app Android —
  KHÔNG có trong bảng file bạn được sửa. Ghi PARTIAL, nói rõ server kính hết câm
  nhưng nguồn vị trí vẫn chưa có.
  Câu hỏi 🔴: cache vị trí toàn cục hay theo device? Làm phần không phụ thuộc,
  rồi hỏi.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_location_degraded.py tests/test_chat.py -q

Agent(#3, general-purpose, background) — "T15 OCR chất lượng"
  Task file: docs/tasks/T15-ocr-quality.md  (H0-H7)
  ĐỌC TRƯỚC: docs/tasks/measurements/H0-blur-720p.md — H0 đã đo ở đợt 0. Dùng
  ngưỡng đề nghị trong đó, ĐỪNG đo lại từ đầu.
  FILE ĐƯỢC SỬA: pipeline/image_quality.py, pipeline/phrases.py,
    models/ocr/prompts.py, models/vlm/client.py, config.py (CHỈ `# === T15 ===`),
    tests/test_ocr_quality.py (mới), tools/bench_ocr_matrix.py (mới),
    docs/tasks/measurements/H4.md (mới), docs/tasks/reports/T15.md
  H4: ma trận 3 model x 3 biến thể, PHẢI có ca hỏng thật trong bảng.
  H2 CHỈ LÀM NẾU H4 chứng minh là cần. Không cần thì ghi "không cần, xem H4".
  H7 KHÔNG LÀM trừ khi có số chứng minh. Quay lại PaddleOCR local là CPU hàng
  chục giây VÀ hỏng trên đúng ca 25.2 — đã biết trước.
  H3: ba câu hướng dẫn KHÁC NHAU, đều dựng sẵn audio, dùng pending.attempt.
  H5: đếm KHONG_CO_CHU, có số trước/sau.
  GEMINI_OCR_MODEL tách riêng — handler khác KHÔNG đổi model.
  Ngân sách ocr là câu hỏi 🔴 chưa chốt -> nghiệm thu để treo, ghi vào báo cáo.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_ocr_quality.py -q
       .venv/Scripts/python.exe tools/bench_ocr_matrix.py

Agent(#4, general-purpose, background) — "T20 phần còn lại: hợp đồng mã lỗi"
  Task file: docs/tasks/T20-error-contract.md
  ĐỌC TRƯỚC: docs/tasks/measurements/P7-error-matrix.md — bảng hai chiều đã dựng
  ở đợt 0. Thi hành quyết định (a)/(b) đã ghi trong từng dòng của bảng đó.
  FILE ĐƯỢC SỬA: handlers/result_speech.py, tests/test_error_contract.py (mới),
    docs/tasks/reports/T20.md, docs/tasks/contract-deltas/T20-final.md
  `_DEFAULT_POLICY` PHẢI tồn tại. Nguyên tắc 21.7: KHÔNG MÃ NÀO ĐƯỢC RƠI VÀO IM
  LẶNG. Mã lạ chưa từng thấy cũng phải có câu.
  retryable / terminal xác định cho MỌI mã.
  ⚠️ Ô DoD "T06/D4 đã bỏ xfail" — T06 CHƯA TỒN TẠI (đợt 3). Bỏ trống ô đó, ghi
  rõ là chuyển giao cho T06. ĐỪNG tạo handlers/slots.py — đó là file của T06.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_error_contract.py -q

Agent(#5, general-purpose, background) — "T22 bật TLS firmware"
  Repo chính của bạn: D:\Study\innostar\your-eyes-esp32-firmware
  Task file: D:\Study\innostar\Sever_test\docs\tasks\T22-firmware-tls.md
  FILE ĐƯỢC SỬA:
    firmware: src/app_config.h (API_USE_TLS 1), src/net/api_client.cpp
    server kính: CHỈ docs/tasks/measurements/F9.md và docs/tasks/reports/T22.md
    — TUYỆT ĐỐI không sửa file .py nào; 4 agent khác đang sửa chúng.
  🔴 ĐÂY LÀ CỔNG PHÁT HÀNH. Chưa bật TLS thì ảnh trong nhà và giọng nói của
  người khiếm thị đang đi BẢN RÕ.
  Cấm tắt TLS để bù độ trễ. Chậm thì tìm cách khác (nới keepalive, warm-up).
  measurements/F9.md phải có p50/p95 cho CẢ lượt nóng LẪN lượt nguội. Lượt nguội
  là lượt phải bắt tay TLS lại — đó mới là ca đau.
  Chạy 50 lượt liên tiếp: không rớt, không rò RAM. Có số.
  Cần phần cứng thật. Không có board -> làm hết phần sửa code + viết quy trình
  đo, đánh dấu PARTIAL, ghi rõ ô nào chờ kiểm tay. ĐỪNG bịa số.
  setNoDelay(true) trên socket THẬT của api_client.cpp — T01 có thể đã làm, kiểm
  trước, đừng làm hai lần.
  Xong phải ghi trong báo cáo: "T21 phải đo lại TOÀN BỘ trên bản TLS=1".
```

- [ ] **Step 3: Đợi cả năm, đọc năm báo cáo**

```bash
cd "d:/Study/innostar/Sever_test"
cat docs/tasks/reports/T02.md docs/tasks/reports/T07.md docs/tasks/reports/T15.md docs/tasks/reports/T20.md docs/tasks/reports/T22.md
```

- [ ] **Step 4: Cổng đợt 2**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_audio_contract.py tests/test_location_degraded.py tests/test_ocr_quality.py tests/test_error_contract.py tests/test_chat.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -n "=== T0[17] ===\|=== T15 ===" config.py
ls docs/tasks/measurements/
```

Cổng:
- 5 file test xanh, tổng test không đỏ thêm
- `config.py` marker T07 và T15 **đều đã được thay** (grep không còn ra dòng marker rỗng của hai cái đó) và file vẫn import được
- `measurements/` có thêm `G11.md`, `H4.md`, `F9.md`
- `_DEFAULT_POLICY` tồn tại: `grep -n "_DEFAULT_POLICY" handlers/result_speech.py`

- [ ] **Step 5: Review đợt 2**

```
Agent(subagent_type: "cavecrew-reviewer", run_in_background: false,
      description: "Review đợt 2",
      prompt: """
Review git diff HEAD trong D:\Study\innostar\Sever_test — 4 task chạy song song
đã ghi vào cùng cây thư mục.

Soi ĐÚNG BỐN thứ này, bỏ qua nit:
  1. Có agent nào sửa file ngoài phần của mình không? Bảng chủ sở hữu:
       T02 -> app.py, tests/test_audio_contract.py
       T07 -> handlers/chat.py, config.py(T07), tests/test_location_degraded.py, tests/test_chat.py
       T15 -> pipeline/image_quality.py, pipeline/phrases.py, models/ocr/prompts.py,
              models/vlm/client.py, config.py(T15), tests/test_ocr_quality.py
       T20 -> handlers/result_speech.py, tests/test_error_contract.py
     File nào bị sửa mà không thuộc bảng -> báo NGAY, đó là va chạm.
  2. config.py: hai khối T07 và T15 có ghi đè nhau không? Có key nào trùng tên
     mà khác giá trị không?
  3. _location_text() có đường nào còn trả chuỗi rỗng không?
  4. _DEFAULT_POLICY có thật sự bắt được mã CHƯA TỪNG THẤY, hay chỉ bắt danh
     sách cứng đã liệt kê?
""")
```

- [ ] **Step 6: Gộp contract-delta + commit 5 commit tách rời**

Gộp `docs/tasks/contract-deltas/*.md` vào `CONTRACTS.md`: T02 → mục 2.4 (bảng ràng buộc audio), T20-final → mục 5.5, T22 → mục 1 quyết định #7 ghi "đã bật, xem F9.md".

Commit **tách theo task** để `git bisect` còn dùng được:

```bash
cd "d:/Study/innostar/Sever_test"
git add app.py tests/test_audio_contract.py docs/tasks/measurements/G11.md && \
  git commit -m "test(audio): khoá 5 ràng buộc F8 + đo tỉ lệ nhả TTS (T02/G11,F8)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/chat.py tests/test_location_degraded.py tests/test_chat.py && \
  git commit -m "fix(location): _location_text không bao giờ trả rỗng, backoff 15/30/60->240 (T07/C1-C5)

Cache rỗng trả khối cấm bịa. Trả rỗng là prompt vừa nói chưa có vị trí vừa bảo
LLM tra quanh người dùng — nó sẽ bịa một thành phố.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add pipeline/image_quality.py pipeline/phrases.py models/ tests/test_ocr_quality.py tools/bench_ocr_matrix.py docs/tasks/measurements/H4.md && \
  git commit -m "feat(ocr): ngưỡng blur đo trên 720p, tách GEMINI_OCR_MODEL, ma trận H4 (T15/H0-H5)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/result_speech.py tests/test_error_contract.py && \
  git commit -m "feat(errors): _DEFAULT_POLICY — không mã lỗi nào rơi vào im lặng (T20/P7,21.7)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add config.py CONTRACTS.md docs/tasks && \
  git commit -m "chore(tasks): gộp hợp đồng đợt 2, cập nhật tiến độ

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git -C "d:/Study/innostar/your-eyes-esp32-firmware" add -A && \
  git -C "d:/Study/innostar/your-eyes-esp32-firmware" commit -m "feat(net): API_USE_TLS 1 — cổng phát hành (T22/F9,27.3)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Cập nhật `PROGRESS.md` 5 dòng đợt 2 · tick `RUNBOOK.md`.

---

## Task 4: Đợt 3 — trục intent/slot (T05 ‖ T06)

**Files:**
- T05: `pipeline/intent.py`, `pipeline/intent_local.py`, `tests/test_intent_slots.py`, `tests/test_intent.py`, `measurements/A2.md`
- T06: `handlers/slots.py` **(mới)**, `handlers/action_flow.py`, `handlers/result_speech.py`, `pipeline/phrases.py`, `tests/test_slots.py`, `tests/test_phrases.py`, `tests/test_services.py`

**Interfaces:**
- Consumes: T03 `Pending`/`kind` · T04 khung slot validator · T07 (cho A3) · T20 `_DEFAULT_POLICY` (cho D4)
- Produces (T05): schema 7 slot mới, `song` còn alias — **T08 T10 T11 T12 T16 tiêu thụ**
- Produces (T06): `handlers/slots.py` với **bảng `SLOTS` TRỌN VẸN cả 6 slot** ở CONTRACTS mục 4.2 — **cả đợt 4 chỉ đọc, không ai sửa bảng**

> 🔴 **Điểm khác runbook (L3).** Runbook để đợt 4 tự thêm slot của mình vào `slots.py`. Sáu agent song song cùng Edit một file là hỏng. T06 viết **trọn** bảng ngay tại đây — dữ liệu đã có sẵn ở CONTRACTS mục 4.2, không phải đoán.

- [ ] **Step 1: Kiểm điều kiện vào**

```bash
cd "d:/Study/innostar/Sever_test"
grep -n "_DEFAULT_POLICY" handlers/result_speech.py
grep -n "_location_text" handlers/chat.py
```

Cổng: cả hai grep ra kết quả (T20 và T07 đã xong — T05/A3 cần T07, T06/D4 cần T20).

- [ ] **Step 2: Dispatch hai agent song song**

```
Agent(#1, general-purpose, background) — "T05 intent & schema slot"
  Repo: D:\Study\innostar\Sever_test
  Đọc: AGENT_RULES.md, CONTRACTS.md, docs/tasks/T05-intent-slots.md,
       docs/tasks/reports/T03.md, T04.md, T07.md
  FILE ĐƯỢC SỬA: pipeline/intent.py, pipeline/intent_local.py,
    tests/test_intent_slots.py (mới), tests/test_intent.py, tests/test_intent_local.py,
    docs/tasks/measurements/A2.md (mới), docs/tasks/reports/T05.md
  ⚠️ KHÔNG tạo và KHÔNG sửa handlers/slots.py — agent T06 đang viết file đó
  ngay lúc này. Bạn định nghĩa SCHEMA slot ở tầng intent; T06 định nghĩa CHÍNH
  SÁCH slot (hỏi lại / readback / risk / TTL). Hai việc khác nhau.
  - Schema đủ 7 slot mới, `song` giữ alias (đừng phá đường cũ).
  - A2 phải có CẢ BA VẾ. Kiểm bằng test so chuỗi trên prompt, không đọc bằng mắt.
  - A3 chỉ chèn vị trí khi CÓ VỊ TRÍ THẬT. T07 xong rồi -> dùng _location_text()
    của handlers/chat.py, đừng dựng lại. Vị trí rỗng -> KHÔNG chèn.
  - B3: có pending thì SetFit KHÔNG được gọi. Test kiểm bằng MOCK, không đọc log.
  - cancel / repeat bắt được KHÔNG CẦN Gemini, đo < 300 ms.
  - measurements/A2.md: bảng ca STT sai -> slot trích được, SỐ ĐO THẬT.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_intent.py tests/test_intent_local.py tests/test_intent_slots.py -q
       (ca -m llm cần API key — chạy được thì chạy, không thì ghi rõ là chưa chạy)

Agent(#2, general-purpose, background) — "T06 bảng chính sách slot"
  Repo: D:\Study\innostar\Sever_test
  Đọc: AGENT_RULES.md, CONTRACTS.md (mục 4.2 — bảng SLOTS, và mục 0 nguyên tắc 3),
       docs/tasks/T06-slot-policy.md, docs/tasks/reports/T03.md, T04.md, T20.md
  FILE ĐƯỢC SỬA: handlers/slots.py (TẠO MỚI — bạn là chủ duy nhất),
    handlers/action_flow.py, handlers/result_speech.py, pipeline/phrases.py,
    tests/test_slots.py (mới), tests/test_phrases.py, tests/test_services.py,
    docs/tasks/reports/T06.md
  ⚠️ KHÔNG sửa pipeline/intent.py — agent T05 đang sửa nó.

  🔴 KHÁC TASK FILE — ĐỌC KỸ: task file để đợt 4 tự thêm slot của họ vào bảng.
  Đổi lại: BẠN viết TRỌN bảng SLOTS ngay bây giờ, đủ cả 6 slot ở CONTRACTS mục
  4.2, vì đợt 4 có 6 agent chạy song song và không thể cùng sửa một file.
  Sáu slot, chép đúng từ CONTRACTS mục 4.2:
    contact_name      | "Bạn muốn gọi cho ai?"             | low_conf | high | fill
    destination       | "Bạn muốn đi đâu?"                 | low_conf | high | fill
    ride_destination  | "Bạn muốn đi đâu?"                 | always   | high | fill
    song_title        | "Bạn muốn nghe bài hát nào?"       | never    | low  | fill
    artist            | "Bạn muốn nghe của ca sĩ nào?"     | never    | low  | fill
    volume_direction  | "Bạn muốn tăng hay giảm âm lượng?" | never    | low  | fill

  🔴 `emergency_number` KHÔNG CÓ MẶT TRONG BẢNG. CỐ Ý. Viết assert trong CODE:
       assert "emergency_number" not in SLOTS, "<lý do>"
     kèm comment giải thích: emergency_call không đi qua BẤT KỲ bước xác minh
     nào (CONTRACTS mục 0 nguyên tắc 3). Có slot cho nó là tự động sinh ra bước
     hỏi lại — đúng thứ tuyệt đối không được có.

  - handlers/slots.py là CHỖ DUY NHẤT định nghĩa câu hỏi lại. 5 hằng số. Sau khi
    xong, grep phải chứng minh không câu nào bị dựng sẵn ở hai nơi.
  - pipeline/phrases.py:47 phải thấy slots.py (grep verify số dòng).
  - D4: T20 đã xong -> dùng _DEFAULT_POLICY thật, KHÔNG xfail. Mã nào
    P7-error-matrix.md ghi là app KHÔNG phát -> không dựng câu cho nó.
  - Ba test khoá emergency phải xanh. Ai xoá phải giải trình.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_slots.py tests/test_phrases.py tests/test_services.py -q
```

- [ ] **Step 3: Cổng đợt 3 — kiểm assert emergency bằng mắt**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_intent.py tests/test_intent_local.py tests/test_intent_slots.py tests/test_slots.py tests/test_phrases.py tests/test_services.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -n "emergency_number" handlers/slots.py
grep -rn "Bạn muốn gọi cho ai\|Bạn muốn đi đâu\|Bạn muốn nghe bài" --include="*.py" . | grep -v "^./tests"
.venv/Scripts/python.exe -c "from handlers.slots import SLOTS; print(sorted(SLOTS)); assert len(SLOTS)==6"
```

Cổng:
- 6 file test xanh
- `grep emergency_number` ra **dòng assert**, không ra dòng khai báo slot (GC12)
- grep câu hỏi ra **đúng một chỗ mỗi câu** — trùng hai chỗ nghĩa là chưa gom hết
- `SLOTS` có đủ 6 khoá

- [ ] **Step 4: Review + commit**

```
Agent(cavecrew-reviewer) — "Review đợt 3: T05 intent + T06 slot policy.
  git diff HEAD trong D:\Study\innostar\Sever_test.
  Soi: (1) T05 và T06 có sửa chồng file nhau không; (2) assert emergency_number
  có kèm comment lý do và có chạy ở import time không, hay chỉ nằm trong test;
  (3) A3 có chèn vị trí kể cả khi rỗng không; (4) có câu hỏi lại nào còn bị dựng
  sẵn ở hai nơi không."
```

```bash
cd "d:/Study/innostar/Sever_test"
git add pipeline/intent.py pipeline/intent_local.py tests/test_intent*.py docs/tasks/measurements/A2.md && \
  git commit -m "feat(intent): schema 7 slot + A2 ba vế + A3 chèn vị trí thật (T05/A1-A3,B3,B5)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/slots.py handlers/action_flow.py handlers/result_speech.py pipeline/phrases.py tests/test_slots.py tests/test_phrases.py tests/test_services.py docs/tasks && \
  git commit -m "feat(slots): bảng chính sách slot trọn 6 slot, gom câu hỏi lại về một chỗ (T06/D1,D3-D5,G5)

emergency_number CỐ Ý vắng mặt, có assert kèm lý do trong code: emergency_call
không đi qua bất kỳ bước xác minh nào.
Bảng viết trọn ngay tại đây (khác runbook) vì đợt 4 có 6 agent song song không
thể cùng sửa slots.py.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Đợt 4 — sáu chức năng song song

**Files — bảng chủ sở hữu, không dòng nào giao nhau:**

| Agent | File code | File test |
|---|---|---|
| **T08** Gọi danh bạ | `handlers/contact_match.py` *(mới)*, `handlers/phone.py`, `handlers/result_speech.py`, `requirements.txt` | `tests/test_contact_match.py`, `tests/test_slots_contact.py` |
| **T09** Gọi khẩn cấp | *(gần như không sửa code — xem dưới)* | `tests/test_emergency_detect.py`, `tests/test_emergency_cancel.py` |
| **T10** Chỉ đường | `handlers/navigation.py` | `tests/test_navigation.py` |
| **T12** Nhạc | `handlers/music.py`, `music_play.py`, `music_stop.py`, `music_volume.py` | `tests/test_music_slots.py` |
| **T14** OCR ngữ cảnh | `handlers/ocr.py`, `models/ocr/__init__.py` | `tests/test_ocr_context.py`, `tests/test_models_ocr.py` |
| **T16** Không gian & vật cản | `handlers/describe_space.py`, `handlers/describe_hazard.py` *(chỉ comment)* | `tests/test_space_focus.py` |

**KHÔNG AI ĐƯỢC SỬA trong đợt này:** `handlers/slots.py` (T06 đã chốt) · `pipeline/router.py` · `pipeline/intent.py` · `handlers/action_flow.py` · `tests/test_slots.py` · `config.py` · `handlers/find_object.py` · `handlers/read_money.py`

**Interfaces:**
- Consumes: `handlers.slots.SLOTS` (T06, chỉ đọc) · schema slot T05 · khung validator T04 · `_DEFAULT_POLICY` T20
- Produces (T14): `session.last_ocr` + `_remember` dùng lại ở T13 (đợt 5)
- Produces (T08): `speak_result` trả **tuple** — mọi chỗ gọi phải cập nhật

> ⚠️ **Xung đột `handlers/result_speech.py`:** T08 cần đổi `speak_result` sang trả tuple, T06 vừa sửa file đó ở đợt 3. Trong đợt 4 chỉ **T08** được sửa file này — năm agent kia đọc thôi.

- [ ] **Step 1: Kiểm điều kiện vào**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -c "from handlers.slots import SLOTS; print(len(SLOTS), sorted(SLOTS))"
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -5
git status --short
```

Cổng: `SLOTS` đủ 6 · toàn bộ test xanh (hoặc đúng bằng baseline) · `git status` **sạch** — đợt 4 sáu agent chạy song song, có thay đổi chưa commit từ trước là không tách nổi ai làm gì.

- [ ] **Step 2: Dispatch sáu agent — cả sáu trong MỘT message**

Khối mở đầu chung:

```
Repo: D:\Study\innostar\Sever_test
Đọc: 1) docs/tasks/AGENT_RULES.md  2) docs/tasks/CONTRACTS.md  3) <task file>
     4) docs/tasks/reports/T06.md — bảng SLOTS đã chốt, đọc để biết dùng thế nào

Điều kiện vào: T03 T04 T05 T06 XONG.

🔴 KHÁC TASK FILE, ĐỌC KỸ — bạn đang chạy song song với 5 agent khác:
  (a) handlers/slots.py ĐÃ CHỐT ở T06, đủ 6 slot. BẠN CHỈ ĐỌC, KHÔNG SỬA.
      Task file bảo "dời _ASK_X sang slots.py" -> việc đó T06 làm rồi, kiểm lại
      thấy có thì thôi; thiếu thì ghi vào "Lệch với task file", ĐỪNG tự thêm.
  (b) tests/test_slots.py thuộc T06. DoD của bạn ghi `pytest tests/test_slots.py
      -k <từ khoá>` -> đổi thành file riêng của bạn (tên ghi trong phần dưới).
  (c) Chỉ sửa file trong bảng FILE BẠN ĐƯỢC SỬA. Ngoài bảng -> ghi "Lệch với
      task file", làm tiếp phần còn lại.
```

Rồi riêng từng agent:

```
Agent(#1) — T08 Gọi danh bạ · docs/tasks/T08-contact-call.md
  FILE ĐƯỢC SỬA: handlers/contact_match.py (mới), handlers/phone.py,
    handlers/result_speech.py, requirements.txt,
    tests/test_contact_match.py (mới), tests/test_slots_contact.py (mới),
    docs/tasks/measurements/D7-thresholds.md, docs/tasks/reports/T08.md
  - App so khớp tên BẰNG NHAU TUYỆT ĐỐI (ActionRegistry.kt:110) — không có tìm
    mờ nào. Fuzzy PHẢI nằm ở server kính (D7).
  - rapidfuzz vào requirements.txt KÈM COMMENT LÝ DO.
  - speak_result trả TUPLE — bạn là agent DUY NHẤT được sửa result_speech.py
    trong đợt này. Cập nhật mọi chỗ gọi.
  - Số điện thoại đầy đủ KHÔNG RỜI KHỎI ĐIỆN THOẠI. Chỉ 3-4 chữ số cuối, và chỉ
    khi cần phân biệt (CONTRACTS quyết định #8).
  - Ngưỡng 88/70/margin 8 cần DANH BẠ THẬT để đo. Không có -> ghi "chưa đo" và
    dùng số đề xuất, ĐỪNG chốt (GC20).
  - P1 (contact_list) / P2 nằm ở repo app — không thuộc bạn. Trạng thái task giữ
    PARTIAL, ghi RÕ ca nào còn hỏng (ca "tên đặt lạ").
  DoD: .venv/Scripts/python.exe -m pytest tests/test_contact_match.py tests/test_slots_contact.py -q

Agent(#2) — T09 Gọi khẩn cấp · docs/tasks/T09-emergency-call.md
  🔴 CẢNH BÁO: task này PHẦN LỚN LÀ KHOÁ LẠI HÀNH VI ĐÚNG, KHÔNG PHẢI THÊM TÍNH
  NĂNG. Mỗi dòng code bạn thêm phải trả lời được: nó có làm CHẬM cuộc gọi cấp
  cứu không? Không trả lời được -> đừng thêm.
  FILE ĐƯỢC SỬA: tests/test_emergency_detect.py (mới),
    tests/test_emergency_cancel.py (mới), docs/tasks/reports/T09.md
    handlers/phone.py CHỈ ĐƯỢC THÊM COMMENT — agent T08 đang sửa logic file đó
    ngay lúc này. Cần đổi logic -> DỪNG, ghi vào báo cáo, để phiên điều phối xử.
  - handlers/phone.py:50-65 KHÔNG ĐỔI LOGIC (grep verify, số dòng có thể trôi).
  - Assert D5 (`emergency_number not in SLOTS`) đã có ở T06 — KIỂM nó tồn tại,
    đừng viết lại.
  - Emergency bỏ qua: readback · pending · gate ảnh · hàng đợi barge-in. Kiểm
    từng cái bằng test, không đọc code bằng mắt.
  - Cửa sổ huỷ KHÔNG PHẢI CÂU HỎI. Action gửi TRƯỚC khi cửa sổ mở.
  - Ba test khoá là KHOÁ AN TOÀN: test_emergency_number_not_in_slots,
    test_emergency_never_asks_back, test_emergency_never_reads_back.
  - So p50 ack TRƯỚC/SAU. Chậm đi -> nói rõ trong báo cáo là phải rollback.
    Ngân sách: < 300 ms.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_emergency_detect.py tests/test_emergency_cancel.py -q

Agent(#3) — T10 Chỉ đường · docs/tasks/T10-navigation.md
  FILE ĐƯỢC SỬA: handlers/navigation.py, tests/test_navigation.py,
    docs/tasks/reports/T10.md
  - _ASK_DESTINATION đã dời sang slots.py ở T06 — KIỂM, đừng dời lại.
  - Ack PHẢI CÓ TÊN ĐIỂM ĐẾN.
  - readback = low_conf, chạy đúng CẢ HAI nhánh (đủ tin / không đủ tin).
  - Pending readback dùng kind="confirm" -> TTL 25 s, KHÔNG phải 120 s. Để 120 s
    là người dùng quên ngữ cảnh rồi "ừ" cho việc khác.
  - Validator TỪ CHỐI ĐỘNG TỪ MỆNH LỆNH ("dẫn tôi", "đi tới") làm điểm đến.
  - D4 (INVALID_DESTINATION): T20 đã xong, đọc measurements/P7-error-matrix.md.
    Bảng đó ghi app CÓ phát mã này -> làm thật. Ghi KHÔNG phát -> giữ xfail với
    lý do trỏ T20, ĐỪNG báo xong.
  - Trạng thái task giữ PARTIAL cho tới khi có nguồn mã lỗi thật.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_navigation.py -q

Agent(#4) — T12 Nhạc · docs/tasks/T12-music.md
  FILE ĐƯỢC SỬA: handlers/music.py, handlers/music_play.py, handlers/music_stop.py,
    handlers/music_volume.py, tests/test_music_slots.py (mới),
    docs/tasks/reports/T12.md
  ⚠️ tests/test_services.py thuộc T06 (đợt 3, đã commit). Cần sửa nó -> ghi vào
    "Lệch với task file", để phiên điều phối xử sau đợt.
  - A4: xoá 4 thứ heuristic khỏi music.py. Kiểm bằng GREP, có test chứng minh.
  - Nối "Title - Artist" CHỈ KHI CẢ HAI CÓ.
  - Ba slot có pending; `known` mang song_title sang lượt sau.
  - _PENDING_SONG và remember/recall/forget của nó: XOÁ.
  - handle_volume VẪN KHÔNG mặc định "tăng". Đoán sai hướng âm lượng cho người
    khiếm thị là tệ hơn hỏi lại.
  - 🔴 Chỗ hở "bài tự hết" ở handlers/action_flow.py:78-86: GIỮ NGUYÊN, và bạn
    KHÔNG được sửa action_flow.py. Viết TEST KHOÁ nó lại trong file test của
    bạn. Cấm thay bằng TTL đoán mò — đã đo, đã chấp nhận.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_music_slots.py -q

Agent(#5) — T14 OCR ngữ cảnh · docs/tasks/T14-ocr-context.md
  FILE ĐƯỢC SỬA: handlers/ocr.py, models/ocr/__init__.py,
    tests/test_ocr_context.py (mới), tests/test_models_ocr.py,
    docs/tasks/reports/T14.md
  ⚠️ models/ocr/prompts.py do T15 sửa ở đợt 2 (đã commit) — bạn sửa được, nhưng
    ĐỌC diff của T15 trước để không đạp lên ngưỡng vừa đo.
  ⚠️ handlers/chat.py thuộc T13 (đợt 5). Task file bảo dùng lại helper _remember
    của T13 — T13 CHƯA CHẠY. Bạn tự viết _remember trong phạm vi của mình và GHI
    RÕ trong báo cáo là T13 phải gom lại. ĐỪNG sửa chat.py.
  - build(mode, command_text) nhận VÀ DÙNG câu hỏi, CẢ HAI VẾ có trong prompt.
  - handlers/ocr.py hiện VỨT command_text — đó là bug chính.
  - session.last_ocr ghi khi THÀNH CÔNG; KHÔNG ghi khi sentinel hoặc stream lỗi.
    Ghi khi lỗi = follow-up đọc lại rác.
  - Follow-up đi TEXT-ONLY. Test phải ĐẾM ĐƯỢC là không có ảnh.
  - Ca "bẫy ảnh mới" (mục 4.2) phải xanh.
  - TTL 5 phút; hết hạn -> đường cũ.
  - Nguyên tắc 2 của CONTRACTS: cache thứ ĐỨNG YÊN (chữ trên giấy). Đây là chỗ
    ĐƯỢC cache — khác hẳn T16.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_ocr_context.py tests/test_models_ocr.py -q

Agent(#6) — T16 Không gian & vật cản · docs/tasks/T16-space-hazard.md
  FILE ĐƯỢC SỬA: handlers/describe_space.py,
    handlers/describe_hazard.py (CHỈ THÊM COMMENT E6, không đổi một dòng logic),
    tests/test_space_focus.py (mới), docs/tasks/reports/T16.md
  🔴 handlers/find_object.py và handlers/read_money.py: KHÔNG ĐỤNG. Spec mục 7
  ghi rõ ngoài phạm vi, hai handler đó đang đúng.
  - space nhận `focus`, KHÔNG nhận command_text nguyên văn. Nhét nguyên văn vào
    là thổi bay ngân sách 40 từ + bộ luật đã đo.
  - focus=None -> prompt GIỐNG HỆT bản hiện tại. Test SO CHUỖI, không so ý.
  - Ngân sách 40 từ + 3 phần + 6 điều cấm: còn nguyên.
  - focus="behind" -> câu dựng sẵn, 0 lời gọi VLM. Camera không nhìn ra sau được.
  - 🔴 KHÔNG đưa lịch sử hội thoại vào space/hazard. Ảnh mới mỗi lượt; mô tả cũ
    LÀ THÔNG TIN SAI (CONTRACTS nguyên tắc 2). Viết comment nói rõ trong code.
  - hazard: KHÔNG nhét command_text (E6). Làm vậy là giảm báo cáo vật cản người
    dùng không hỏi — đúng cái sắp làm họ vấp. Chỉ thêm comment giải thích.
  - 6 test khoá hazard phải xanh.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_space_focus.py -q
```

- [ ] **Step 3: Cổng đợt 4 — kiểm va chạm file trước khi kiểm test**

```bash
cd "d:/Study/innostar/Sever_test"
git status --short
git diff --stat
```

Đối chiếu danh sách file bị đổi với bảng chủ sở hữu ở đầu Task 5. File nào **không** nằm trong bảng, hoặc `handlers/slots.py` / `pipeline/router.py` / `handlers/action_flow.py` / `config.py` bị đổi → có agent vượt rào. Xử trước, đừng chạy test rồi mới phát hiện.

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_contact_match.py tests/test_slots_contact.py tests/test_emergency_detect.py tests/test_emergency_cancel.py tests/test_navigation.py tests/test_music_slots.py tests/test_ocr_context.py tests/test_models_ocr.py tests/test_space_focus.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -12
git diff --stat handlers/find_object.py handlers/read_money.py handlers/describe_hazard.py
```

Cổng:
- 9 file test xanh, tổng test không đỏ thêm
- `find_object.py` / `read_money.py`: **0 dòng đổi** (GC13)
- `describe_hazard.py`: chỉ dòng comment (`git diff handlers/describe_hazard.py` đọc bằng mắt — mọi dòng `+` phải bắt đầu bằng `#`)

- [ ] **Step 4: Cổng an toàn emergency — chạy riêng, không gộp**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_emergency_detect.py tests/test_emergency_cancel.py tests/test_slots.py -k emergency -q -v
grep -n "emergency_number" handlers/slots.py
git diff handlers/phone.py
```

Cổng: ba test khoá xanh · assert `emergency_number not in SLOTS` còn nguyên · `handlers/phone.py` đoạn `:50-65` không đổi logic (đọc diff bằng mắt — dòng `+` không phải comment là dấu hiệu đỏ). Đây là cổng phát hành, không tick lấy lệ.

- [ ] **Step 5: Review đợt 4**

```
Agent(cavecrew-reviewer) — "Review git diff HEAD trong D:\Study\innostar\Sever_test.
  Sáu task chức năng chạy song song: T08 T09 T10 T12 T14 T16.
  Soi:
    1. Có file nào bị hai agent cùng sửa không? Bảng chủ sở hữu ở
       docs/superpowers/plans/2026-08-22-subagent-orchestration-23-task.md Task 5.
    2. speak_result đổi sang trả tuple (T08) — còn chỗ gọi nào chưa cập nhật không?
       grep mọi caller.
    3. T09: có dòng nào THÊM VÀO đường tới hạn của emergency_call không? Mỗi dòng
       thêm là thêm ms cho cuộc gọi cấp cứu.
    4. T16: describe_space có nhận command_text nguyên văn ở đường nào không?
       describe_hazard có đổi logic không?
    5. T14: session.last_ocr có bị ghi ở nhánh lỗi/sentinel không?
    6. Có test nào xanh nhờ mock đúng cái nó định kiểm không?"
```

- [ ] **Step 6: Commit sáu commit tách rời + cập nhật tiến độ**

```bash
cd "d:/Study/innostar/Sever_test"
git add handlers/contact_match.py handlers/phone.py handlers/result_speech.py requirements.txt tests/test_contact_match.py tests/test_slots_contact.py docs/tasks/measurements/D7-thresholds.md && \
  git commit -m "feat(contact): tìm mờ danh bạ ở server kính, speak_result trả tuple (T08/D2,D6-D9)

App so khớp tên bằng nhau tuyệt đối nên fuzzy phải nằm ở đây.
Số đầy đủ không rời khỏi điện thoại — chỉ 3-4 chữ số cuối khi cần phân biệt.
PARTIAL: chờ P1 contact_list phía app.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add tests/test_emergency_detect.py tests/test_emergency_cancel.py && \
  git commit -m "test(emergency): khoá 3 hành vi an toàn của emergency_call (T09/D5,21.5)

Khoá lại hành vi đúng, không thêm tính năng. Không dòng nào vào đường tới hạn.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/navigation.py tests/test_navigation.py && \
  git commit -m "feat(nav): ack có tên điểm đến, readback low_conf, pending confirm 25s (T10/D1,D3,D4)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/music*.py tests/test_music_slots.py && \
  git commit -m "refactor(music): xoá 4 heuristic A4, ba slot qua pending (T12/A4,A1,D1,D4)

handle_volume vẫn không mặc định tăng. Chỗ hở 'bài tự hết' giữ nguyên, có test khoá.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/ocr.py models/ocr/__init__.py tests/test_ocr_context.py tests/test_models_ocr.py && \
  git commit -m "feat(ocr): dùng command_text trong prompt, follow-up text-only qua last_ocr (T14/E1-E3)

Cache chữ trên giấy — thứ đứng yên. TTL 5 phút. Không ghi last_ocr ở nhánh lỗi.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/describe_space.py handlers/describe_hazard.py tests/test_space_focus.py docs/tasks && \
  git commit -m "feat(space): nhận focus thay vì command_text nguyên văn (T16/E5,E6)

focus=None -> prompt giống hệt bản cũ. Không đưa lịch sử vào space/hazard: ảnh
mới mỗi lượt, mô tả cũ là thông tin sai. hazard chỉ thêm comment.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Đợt 5 — T13 ‖ T11 ‖ T23

**Files:**

| Agent | File được sửa |
|---|---|
| **T13** Chat & lịch sử | `handlers/chat.py`, `tests/test_chat.py`, `measurements/G7.md` |
| **T11** Đặt xe | `handlers/ride.py`, `ride_quote.py`, `ride_confirm.py`, `pipeline/phrases.py`, `handlers/action_flow.py`, `tests/test_ride_quote.py` |
| **T23** Quyền & cấu hình | `services/` (client capabilities), `tests/test_capabilities.py` |

**Interfaces:**
- Consumes: T07 `_location_text()` · T14 `_remember` bản tạm · T06 `SLOTS` · T20 mã lỗi
- Produces (T13): `_remember()` **helper dùng chung** — gom bản tạm của T14 về đây
- Produces (T23): hợp đồng `capabilities_get` enum đóng → nuôi lại T07/P8 và T09/P11

> T11 sửa `handlers/action_flow.py` và `pipeline/phrases.py` — hai file T06 chốt ở đợt 3. Trong đợt 5 chỉ T11 được sửa chúng.

- [ ] **Step 1: Dispatch ba agent song song**

```
Agent(#1) — T13 Chat & lịch sử · docs/tasks/T13-chat-search.md
  Đọc thêm: docs/tasks/reports/T14.md — T14 viết _remember bản TẠM trong phạm vi
  của nó và ghi lại là bạn phải gom. Đọc rồi gom, đừng để hai bản.
  FILE ĐƯỢC SỬA: handlers/chat.py, handlers/ocr.py (CHỈ đoạn gọi _remember),
    tests/test_chat.py, docs/tasks/measurements/G7.md, docs/tasks/reports/T13.md
  - Lịch sử nằm trong Session (T03), ghi CẢ LƯỢT ACTION — không chỉ lượt chat.
  - _remember() thành helper DÙNG CHUNG. Không copy sang 6 handler.
  - E4: chèn transcript KÈM câu "bỏ qua nếu không liên quan". Thiếu câu đó thì
    hỏi "mấy giờ rồi" sau khi đọc giấy sẽ bị kéo về tờ giấy.
  - G7: tiền tố BẤT BIẾN của prompt phải GIỐNG HỆT giữa hai lượt — prefix cache
    chỉ ăn khi khớp từ byte đầu. Test ĐO ĐƯỢC, ghi số vào measurements/G7.md.
  - _SYSTEM_PROMPT KHÔNG ĐỔI MỘT CHỮ sau khi tách. Test so chuỗi.
  - Không còn ca prompt vừa nói "chưa có vị trí" vừa bảo "tra quanh người dùng"
    (T07 đã sửa nguồn, bạn kiểm đường prompt).
  DoD: .venv/Scripts/python.exe -m pytest tests/test_chat.py -q

Agent(#2) — T11 Đặt xe · docs/tasks/T11-ride.md
  🔴 TASK NÀY PHẦN LỚN BỊ CHẶN. Mục 0 của task file chia rõ LÀM ĐƯỢC NGAY và
  BLOCKED. CHỈ làm phần làm được ngay: R4, R6, R7, P3, P4, P5.
  FILE ĐƯỢC SỬA: handlers/ride.py, handlers/ride_quote.py, handlers/ride_confirm.py,
    pipeline/phrases.py, handlers/action_flow.py, tests/test_ride_quote.py,
    docs/tasks/reports/T11.md
  - 🔴 _DEMO_CURRENT_LOCATION PHẢI XOÁ. Không còn đường nào rơi về Quận 1. Đây
    là cổng phát hành: người khiếm thị đặt xe tới một toạ độ hằng số là sự cố
    thật, không phải bug demo.
  - Không có vị trí -> TỪ CHỐI ĐẶT, có test. Dùng _location_text() của T07.
  - Pending ride dùng kind="select", TTL 45 s. Hết hạn -> GỌI LẠI. CẤM đọc lại
    giá cũ — giá có surge.
  - Câu bàn giao nói rõ CÒN MỘT CHẠM (deeplink, không phải đã đặt xong).
  - _WAITING_IN_APP thừa nhận không theo dõi được chuyến.
  - R1 R2 R3 R5: @pytest.mark.xfail(reason="R1: chưa có quyền partner Farefeed").
    KHÔNG XOÁ TEST.
  - AccessibilityService lái UI Grab: KHÔNG LÀM. Vi phạm ToS, ban tài khoản thật,
    và người khiếm thị không phát hiện được khi nó hỏng.
  - Trạng thái giữ PARTIAL. KHÔNG được đổi thành READY.
  Câu hỏi 🔴: ai geocode address -> lat/lng? Chưa chốt. Làm phần không phụ thuộc.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_ride_quote.py -q

Agent(#3) — T23 Quyền & cấu hình · docs/tasks/T23-capabilities.md
  FILE ĐƯỢC SỬA: services/ (file client capabilities — grep tìm chỗ gọi server
    app), tests/test_capabilities.py (mới), docs/tasks/reports/T23.md,
    docs/tasks/contract-deltas/T23.md
  ⚠️ KHÔNG sửa handlers/chat.py (T13 đang sửa) và handlers/ride*.py (T11 đang sửa).
  - capabilities_get là ENUM ĐÓNG, không phải dict tự do. Danh sách đủ ở
    CONTRACTS mục 5.4 — chép đúng, không thêm bớt.
  - Server kính CACHE, làm mới khi gặp mã lỗi về quyền.
  - Câu lỗi CHỈ ĐÚNG THỨ ĐANG THIẾU. Test SO CHUỖI. "Thiếu quyền" chung chung
    thì người khiếm thị không biết vào đâu để bật.
  - emergency_contact kiểm LÚC GHÉP MÁY, nhắc MỘT LẦN. Nhắc mỗi lượt là phiền.
  - Thiếu quyền PHỤ KHÔNG CHẶN việc thử.
  - App cũ không có endpoint -> THOÁI HOÁ ÊM, không crash.
  - P10/P11 phần app Android không thuộc bạn -> PARTIAL, ghi rõ.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_capabilities.py -q
```

- [ ] **Step 2: Cổng đợt 5**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_chat.py tests/test_ride_quote.py tests/test_capabilities.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -12
grep -rn "_DEMO_CURRENT_LOCATION" --include="*.py" .
grep -rn "def _remember" --include="*.py" .
```

Cổng:
- 3 file test xanh, tổng không đỏ thêm
- 🔴 `_DEMO_CURRENT_LOCATION` grep ra **rỗng** — đây là cổng phát hành
- `_remember` định nghĩa ở **đúng một chỗ** (T13 đã gom bản tạm của T14)

- [ ] **Step 3: Review + commit**

```
Agent(cavecrew-reviewer) — "Review git diff HEAD. T13 + T11 + T23 song song.
  Soi: (1) va chạm file giữa ba agent; (2) còn đường nào đặt xe được khi không
  có vị trí không; (3) _remember có đúng một bản không, hay T14 còn bản riêng;
  (4) tiền tố prompt của chat có thật sự bất biến giữa hai lượt không — kiểm
  cả chỗ nối chuỗi có timestamp/uuid lọt vào; (5) capabilities có enum đóng thật
  hay vẫn nhận key lạ."
```

```bash
cd "d:/Study/innostar/Sever_test"
git add handlers/chat.py handlers/ocr.py tests/test_chat.py docs/tasks/measurements/G7.md && \
  git commit -m "feat(chat): lịch sử trong Session, _remember gom một chỗ, E4 transcript (T13/B4,E4,G7)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add handlers/ride*.py pipeline/phrases.py handlers/action_flow.py tests/test_ride_quote.py && \
  git commit -m "fix(ride): xoá _DEMO_CURRENT_LOCATION, không vị trí thì từ chối đặt (T11/P3-P5,R4,R6,R7)

Không còn đường nào rơi về toạ độ Quận 1 hằng số — đó là cổng phát hành.
Pending select 45s, hết hạn gọi lại, cấm đọc giá cũ vì có surge.
R1 R2 R3 R5 xfail chờ quyền partner Farefeed. Trạng thái PARTIAL.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git add services/ tests/test_capabilities.py docs/tasks && \
  git commit -m "feat(capabilities): enum đóng, cache + làm mới khi lỗi quyền (T23/P10,P11,26.7)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Đợt 6 — hạ tầng đường truyền T17 → T18 → T19

**Files:**
- T17: `app.py`, `pipeline/image_quality.py`, `handlers/*` (đọc frame qua API mới), `tests/test_frame_buffer.py`, firmware
- T18: `app.py`, `tests/test_events_channel.py`, `measurements/F6-ram.md`, firmware
- T19: `app.py`, `services/action_callbacks.py`, `tests/test_incoming_call.py`, + server app + app Android + firmware

**Interfaces:**
- Consumes: T01 `X-Device-Id`/`X-Turn-Id` · T22 `API_USE_TLS 1` (T18 đo RAM **sau** TLS) · T15 ngưỡng blur theo tầng
- Produces (T17): `frames.latest(device_id, max_age_ms)` — **API DUY NHẤT** handler dùng để lấy ảnh
- Produces (T18): kênh SSE `GET /events` — **T19 xây trên nó**

> **Tuần tự.** Cả ba sửa `app.py`. T19 không có kênh SSE của T18 thì không chạy được (DoD của T19 ghi thẳng như vậy).

- [ ] **Step 1: T17 — dispatch, đợi xong**

```
Agent(general-purpose, foreground) — T17 Tách /frame · docs/tasks/T17-frame-channel.md
  Đọc: AGENT_RULES.md, CONTRACTS.md (mục 2.2, mục 3), task file,
       docs/tasks/measurements/H0-blur-720p.md, H4.md (số tầng lấy từ đây)
  FILE ĐƯỢC SỬA: app.py, pipeline/image_quality.py, handlers/ (chỗ đọc ảnh),
    tests/test_frame_buffer.py (mới), docs/tasks/reports/T17.md, + repo firmware
  🔴 F2 (đảo thứ tự part multipart) KHÔNG ĐƯỢC THI CÔNG. Đo rồi: làm CHẬM ĐI
  289 ms. Viết COMMENT trong repo firmware ghi rõ lý do (27.1) để lần sau không
  ai "tối ưu" lại nó.
  - POST /frame: fire-and-forget, trả 204, KHÔNG trả gì cho board đợi.
  - frames.latest(device_id, max_age_ms) là API DUY NHẤT handler dùng. Handler
    KHÔNG ĐƯỢC BIẾT frame tới từ đâu (multipart cũ hay /frame mới).
  - 10/15 intent KHÔNG đọc ảnh (bảng ở CONTRACTS mục 3). Chúng KHÔNG ĐƯỢC CHỜ
    frame một mili-giây nào. Test đếm được.
  - Bảng F4 điền SỐ THẬT từ H0/H4 — không còn 1600x1200 / q8 / q15.
  - Ngưỡng blur đo RIÊNG cho từng tầng, có bảng số.
  - Đường multipart cũ VẪN CHẠY trong giai đoạn chuyển.
  Câu hỏi 🔴 chưa chốt: max_age_ms bao nhiêu (800 ms gần như chắc chắn sai) và
  RTT thật qua Cloudflare tunnel. Chưa đo được -> dùng số tạm, GHI RÕ là tạm, hỏi.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_frame_buffer.py -q
```

Cổng T17:

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_frame_buffer.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -rn "1600x1200\|1600×1200" --include="*.py" --include="*.md" . | grep -v "^./docs/tasks/measurements"
grep -rn "frames.latest" --include="*.py" handlers/ | head
```

Cổng: test xanh · không còn `1600x1200` trong code/docs đang dùng · handler đọc ảnh **chỉ** qua `frames.latest`. Commit rồi mới đi tiếp.

- [ ] **Step 2: T18 — dispatch, đợi xong**

```
Agent(general-purpose, foreground) — T18 Downlink SSE · docs/tasks/T18-downlink-sse.md
  Đọc: AGENT_RULES.md, CONTRACTS.md (mục 2.3), task file,
       docs/tasks/measurements/F9.md (T22 — TLS đã bật, RAM phải đo TRÊN BẢN ĐÓ)
  FILE ĐƯỢC SỬA: app.py, tests/test_events_channel.py (mới),
    docs/tasks/measurements/F6-ram.md (mới), docs/tasks/reports/T18.md, + firmware
  - GET /events: text/event-stream, board mở và GIỮ. Heartbeat mỗi N giây.
  - MỘT KÊNH, HAI MỤC ĐÍCH: frame_request + call_incoming + ping.
    KHÔNG ĐẺ RA KÊNH THỨ HAI. T19 dùng lại kênh này.
  - Board rớt -> server DỌN. Không treo generator, không tích sự kiện chờ một
    board đã chết.
  - Board tự nối lại sau khi server restart.
  - 🔴 RAM PHẢI ĐO VỚI 2 SOCKET + TLS BẬT. Đo trên TLS=0 là số vô nghĩa (quyết
    định #7). Ghi vào measurements/F6-ram.md kèm cấu hình.
  - Kênh KHÔNG được làm chậm lượt /process thường. Đo trước/sau, có số.
  Không có board thật -> làm hết phần server + viết quy trình đo, PARTIAL, ghi
  rõ ô RAM chờ phần cứng. ĐỪNG BỊA SỐ RAM.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_events_channel.py -q
```

Cổng T18: test xanh · `measurements/F6-ram.md` có số **hoặc** ghi rõ "chờ phần cứng" · `grep -n "TLS" docs/tasks/measurements/F6-ram.md` phải ra dòng ghi cấu hình. Commit.

- [ ] **Step 3: T19 — dispatch, đợi xong**

```
Agent(general-purpose, foreground) — T19 Cuộc gọi đến · docs/tasks/T19-incoming-call.md
  ⚠️ Task này đụng CẢ BỐN REPO và làm từ số không:
    server kính  D:\Study\innostar\Sever_test
    server app   D:\Study\innostar\app_demo_backend\apps\backend
    app Android  D:\Study\innostar\app_demo_backend\apps\android
    firmware     D:\Study\innostar\your-eyes-esp32-firmware
  Đọc: AGENT_RULES.md, CONTRACTS.md (mục 5.3), task file, docs/tasks/reports/T18.md
  Điều kiện vào: T18 XONG. Không có kênh SSE thì task này không chạy được.
  FILE ĐƯỢC SỬA: app.py, services/action_callbacks.py,
    tests/test_incoming_call.py (mới), docs/tasks/reports/T19.md,
    docs/tasks/contract-deltas/T19.md, + ba repo kia
  - services/action_callbacks.py hiện TỪ CHỐI callback không có request_id đã
    đăng ký. Event tự phát CẦN ĐƯỜNG RIÊNG: POST /internal/device-events.
    ĐỪNG nhét vào /internal/action-results.
  - Cắt TTS ≤ 200 ms, đo được.
  - 🔴 PENDING CÒN NGUYÊN sau cuộc gọi đến. Có test. Người dùng đang trả lời một
    câu hỏi thì có người gọi tới — mất pending là mất cả ngữ cảnh.
  - Cửa sổ intent 15 s, ĐÓNG khi hết chuông.
  - call_ended KHÔNG phát câu nào.
  - 🔴 Số đầy đủ KHÔNG BAO GIỜ rời khỏi điện thoại, KHÔNG BAO GIỜ được đọc
    (CONTRACTS quyết định #8). Chỉ number_tail.
  - announce_caller đủ 3 mức: name | number_only | ring_only. Mặc định "name".
  - Dùng LẠI kênh SSE của T18. Không mở kênh mới.
  7 kịch bản mục 4.5 cần thử tay — không có phần cứng thì viết kịch bản kiểm ra
  báo cáo, đánh dấu chờ, ĐỪNG tick.
  DoD: .venv/Scripts/python.exe -m pytest tests/test_incoming_call.py -q
```

- [ ] **Step 4: Cổng đợt 6 + review + commit**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_frame_buffer.py tests/test_events_channel.py tests/test_incoming_call.py -q
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -12
grep -rn "phone_number\|number_tail" handlers/ services/ app.py | grep -v test
```

Cổng: 3 file test xanh · grep cuối không cho thấy số đầy đủ nào bị log/đọc ra.

```
Agent(cavecrew-reviewer) — "Review 3 commit cuối: T17 /frame + T18 SSE + T19 cuộc
  gọi đến. Soi: (1) có kênh downlink thứ hai nào bị đẻ ra không; (2) generator SSE
  có dọn khi client rớt không, hay rò task; (3) pending có sống sót qua cuộc gọi
  đến không; (4) có đường nào số điện thoại đầy đủ đi ra khỏi app không (log,
  response, trace); (5) 10 intent không ảnh có bị chờ frame không."
```

```bash
cd "d:/Study/innostar/Sever_test"
git add app.py services/action_callbacks.py tests/ docs/tasks && \
  git commit -m "feat(downlink): /frame fire-and-forget + SSE /events + cuộc gọi đến (T17,T18,T19)

frames.latest là API duy nhất handler dùng — handler không biết ảnh tới từ đâu.
Một kênh SSE phục vụ cả frame_request lẫn call_incoming.
Event tự phát đi /internal/device-events, không nhét vào /internal/action-results.
F2 KHÔNG thi công — đo rồi, chậm đi 289ms.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Đợt 7 — T21 ngân sách độ trễ

**Files:**
- Create: `tests/test_latency_budget.py`, `tools/measure_budget.py`, `docs/tasks/measurements/G1.md`
- Modify: `app.py`, `handlers/*` (thêm deadline cho lời gọi ngoài)

**Interfaces:**
- Consumes: **T02** (`G10.md` + `G11.md` — hai khoản đầu ra đã biết) · **T22** (`F9.md` — TLS bật) · **T17** (tầng frame)
- Produces: bảng G1 với số thật → cổng phát hành

- [ ] **Step 1: Kiểm điều kiện vào — nghiêm, đây là chỗ dễ đo nhầm nhất**

```bash
cd "d:/Study/innostar/Sever_test"
ls docs/tasks/measurements/G10.md docs/tasks/measurements/G11.md docs/tasks/measurements/F9.md
grep -n "API_USE_TLS" "d:/Study/innostar/your-eyes-esp32-firmware/src/app_config.h"
```

Cổng: ba file đo có mặt · `API_USE_TLS` phải là `1`. Còn `0` → **DỪNG**, T21 không chạy. Đo trên bản không TLS là số vô nghĩa (CONTRACTS quyết định #7) và sẽ phải đo lại toàn bộ.

- [ ] **Step 2: Dispatch T21**

```
Agent(general-purpose, foreground) — T21 Ngân sách độ trễ · docs/tasks/T21-latency-budget.md
  Đọc: AGENT_RULES.md, CONTRACTS.md (mục 6), task file, và BA file đo:
       measurements/G10.md, G11.md, F9.md
  Điều kiện vào: T02 + T22 + T17 XONG. TLS đang BẬT.
  FILE ĐƯỢC SỬA: app.py, handlers/ (thêm deadline), tests/test_latency_budget.py
    (mới), tools/measure_budget.py (mới), docs/tasks/measurements/G1.md (mới),
    docs/tasks/reports/T21.md
  Ngân sách (CONTRACTS mục 6) — MỌI SỐ ĐO TRÊN BẢN TLS=1:
    emergency_call ack        < 300 ms
    cancel / repeat / stop    < 300 ms
    trả lời pending tất định  < 400 ms
    contact_call ack          < 600 ms
    hazard                    < 800 ms
    chat                      < 1.0 s
    ocr / space / find / money< 1.2 s   (ocr 🔴 chưa chốt riêng)
  DÒNG THỨ HAI, ĐO KHÁC HẲN (G11): tỉ lệ (giây tiếng)/(giây đồng hồ) ≥ 1.30×.
  TTFB đạt mà tỉ lệ này không đạt thì NGƯỜI DÙNG VẪN KHÔNG NGHE GÌ cho tới khi
  sinh xong cả câu. Dòng này phải cùng xanh với dòng TTFB.
  - MỌI lời gọi ngoài có DEADLINE. Quá deadline -> câu dựng sẵn, KHÔNG treo im lặng.
  - Lock ≤ 5 ms, đo TRỰC TIẾP (T04 đã có test, dùng lại).
  - contact_call ack TRƯỚC kết quả API.
  - 🔴 KHÔNG thêm earcon phía server (G8). Board đã có cueSent() ở 0 ms — thêm
    nữa là BÍP HAI LẦN. Viết comment ghi rõ lý do.
  - Trace G9 đủ trường, khoá bằng turn_id.
  - CI phải FAIL khi vượt ngân sách, không chỉ cảnh báo.
  - Dòng nào chưa đo được -> ghi "chưa đo". CẤM copy số của cấu hình khác (GC20).
  DoD: .venv/Scripts/python.exe -m pytest tests/test_latency_budget.py -m perf -q
       .venv/Scripts/python.exe tools/measure_budget.py
```

- [ ] **Step 3: Cổng T21**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests/test_latency_budget.py -m perf -q
.venv/Scripts/python.exe tools/measure_budget.py
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -10
grep -n "TLS" docs/tasks/measurements/G1.md
grep -rn "earcon" --include="*.py" . | grep -v test
```

Cổng: test perf xanh · `G1.md` ghi rõ đo trên `TLS=1` · mọi dòng có số **hoặc** chữ "chưa đo" (không có ô trống) · grep `earcon` không ra chỗ nào server phát tiếng (GC15).

- [ ] **Step 4: Review + commit**

```
Agent(cavecrew-reviewer) — "Review git diff HEAD — T21 ngân sách độ trễ.
  Soi: (1) có lời gọi ngoài nào còn KHÔNG có deadline không — liệt kê mọi
  await/request ra ngoài; (2) deadline hết hạn có thật sự trả câu dựng sẵn hay
  ném exception rồi im lặng; (3) CI có fail thật khi vượt ngân sách không, hay
  chỉ print cảnh báo; (4) có số nào trong G1.md trông giống copy từ file đo cũ
  (không TLS) không."
```

```bash
cd "d:/Study/innostar/Sever_test"
git add app.py handlers/ tests/test_latency_budget.py tools/measure_budget.py docs/tasks && \
  git commit -m "perf(budget): bảng ngân sách G1 đo trên TLS=1, deadline cho mọi lời gọi ngoài (T21/G1,G3,G5,G6,G9)

Dòng G11 (tỉ lệ nhả TTS >= 1.30x) đo riêng — TTFB đạt mà tỉ lệ không đạt thì
người dùng vẫn không nghe gì cho tới khi sinh xong cả câu.
Không thêm earcon phía server: board đã có cueSent() ở 0ms.
CI fail khi vượt ngân sách, không chỉ cảnh báo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: Cổng phát hành & báo cáo tổng

**Files:**
- Modify: `docs/tasks/PROGRESS.md`, `docs/tasks/RUNBOOK.md`, `docs/tasks/00-INDEX.md`, `docs/tasks/CONTRACTS.md`
- Create: `docs/tasks/FINAL-REPORT.md`

- [ ] **Step 1: Chạy năm cổng phát hành của `RUNBOOK.md` mục 6**

```bash
cd "d:/Study/innostar/Sever_test"
echo "=== Cổng 1: TLS bật ==="
grep -n "API_USE_TLS" "d:/Study/innostar/your-eyes-esp32-firmware/src/app_config.h"
cat docs/tasks/measurements/F9.md | head -30

echo "=== Cổng 2: không còn toạ độ hằng số ==="
grep -rn "_DEMO_CURRENT_LOCATION\|10\.7[0-9]*, *106\.[0-9]*" --include="*.py" .

echo "=== Cổng 3: ba test khoá emergency ==="
.venv/Scripts/python.exe -m pytest tests/ -k emergency -q

echo "=== Cổng 4: mọi dòng ngân sách có số trên bản TLS ==="
cat docs/tasks/measurements/G1.md

echo "=== Cổng 5: không mã lỗi nào rơi vào im lặng ==="
.venv/Scripts/python.exe -m pytest tests/test_error_contract.py -q
grep -n "_DEFAULT_POLICY" handlers/result_speech.py
```

Cổng nào đỏ → ghi vào `FINAL-REPORT.md` mục "Chưa qua cổng", **không** báo xong.

- [ ] **Step 2: Chạy toàn bộ test, so với baseline**

```bash
cd "d:/Study/innostar/Sever_test"
.venv/Scripts/python.exe -m pytest tests -q 2>&1 | tail -20
.venv/Scripts/python.exe -m pytest tests -q -m perf 2>&1 | tail -10
.venv/Scripts/python.exe -m pytest tests -q -rx 2>&1 | grep -i xfail
```

Ghi: tổng test (baseline 391 → bao nhiêu), số xfail và **lý do từng cái** (mỗi xfail phải trỏ về một task hoặc một câu hỏi 🔴 chưa chốt — xfail không lý do là báo xanh giả).

- [ ] **Step 3: Kiểm 12 việc KHÔNG ĐƯỢC LÀM ở `RUNBOOK.md` mục 7**

```bash
cd "d:/Study/innostar/Sever_test"
git diff 07409c1..HEAD --stat -- handlers/find_object.py handlers/read_money.py
git diff 07409c1..HEAD -- handlers/describe_hazard.py
grep -rn "earcon" --include="*.py" . | grep -v test
grep -rn "AccessibilityService" "d:/Study/innostar/app_demo_backend/apps/android" 2>/dev/null | head
grep -rn "PaddleOCR\|paddleocr" --include="*.py" --include="*.txt" .
grep -rn "command_text" handlers/describe_space.py handlers/describe_hazard.py
grep -n "API_USE_TLS" "d:/Study/innostar/your-eyes-esp32-firmware/src/app_config.h"
grep -rn "VISIONCARE_DEVICE_ID" app.py handlers/ pipeline/
```

Kỳ vọng, từng dòng một:
- `find_object.py` / `read_money.py`: **0 file changed**
- `describe_hazard.py`: mọi dòng `+` bắt đầu bằng `#`
- `earcon`: không có ở phía server
- `AccessibilityService`: không có
- `PaddleOCR`: không quay lại
- `command_text` trong `describe_space.py`: không nhận nguyên văn (chỉ `focus`)
- `API_USE_TLS`: `1`
- `VISIONCARE_DEVICE_ID`: chỉ còn ở `config.py`, không handler nào đọc thẳng

- [ ] **Step 4: Viết `docs/tasks/FINAL-REPORT.md`**

```markdown
# FINAL-REPORT — 23 task, 8 đợt

Ngày: <ngày chạy xong> · Baseline: 391 test · Hiện tại: <N> test

## Trạng thái 23 task
<bảng: task | trạng thái DONE/PARTIAL/BLOCKED | report | lý do nếu không DONE>

## Năm cổng phát hành
| Cổng | Kết quả | Bằng chứng |
|---|---|---|
| TLS bật + bắt gói xác nhận | | measurements/F9.md |
| T11 P4/P5 — không toạ độ hằng số | | grep _DEMO_CURRENT_LOCATION rỗng |
| T09 — 3 test khoá emergency xanh | | output pytest |
| T21 — mọi dòng ngân sách có số trên TLS | | measurements/G1.md |
| T20 — không mã lỗi nào im lặng | | _DEFAULT_POLICY + test |

## 11 bảng số đo (CONTRACTS mục 8)
<bảng: file | có/thiếu | ngày đo | cấu hình TLS>

## xfail — <N> cái, từng cái một lý do
<bảng: test | lý do | mở khoá bởi>

## Câu hỏi 🔴 còn treo
<gom từ PROGRESS.md — cái nào đã chốt trong lúc chạy, cái nào vẫn treo>

## Lệch với task file — gom từ 23 báo cáo
<mục giá trị cao nhất: chỗ nào spec/task file đã trôi so với code thật>

## Việc còn lại cần phần cứng / người ngoài team
<mọi ô DoD chưa tick vì thiếu board, thiếu danh bạ thật, thiếu quyền Farefeed>
```

- [ ] **Step 5: Cập nhật `RUNBOOK.md`, `00-INDEX.md`, `PROGRESS.md`, commit cuối**

Tick mọi ô đã xong ở `RUNBOOK.md` mục 6. Cập nhật cột "Trạng thái" của `00-INDEX.md` bảng task (READY → DONE/PARTIAL). Điền `PROGRESS.md` lần cuối.

```bash
cd "d:/Study/innostar/Sever_test"
git add docs/tasks
git commit -m "docs(tasks): báo cáo tổng 23 task + kiểm 5 cổng phát hành

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Báo cáo cho người dùng**

Nói thẳng ba con số: bao nhiêu task DONE / PARTIAL / BLOCKED · bao nhiêu cổng phát hành qua / chưa qua · bao nhiêu xfail và mở khoá bằng gì. Cổng nào chưa qua thì nói rõ **chưa được phát hành**, đừng làm tròn lên.

---

## Ghi chú vận hành

**Số agent song song tối đa:** đợt 4 có sáu. Nếu harness chậm hoặc context nặng, chia hai nửa — `T09 T16 T14` (ba cái sạch nhất, gần như không đụng file chung) rồi `T08 T10 T12`. Thứ tự này không đổi kết quả vì cả sáu chỉ đọc `slots.py`.

**Agent trả về PARTIAL:** đó là kết quả **đúng**, không phải thất bại. `00-INDEX.md` đã đánh dấu T08 T10 T11 là PARTIAL từ đầu. Đừng ép agent làm cho xanh — ép là sinh ra xfail giả hoặc test mock chính cái nó định kiểm.

**Agent báo xong mà không có output pytest:** gửi lại bằng `SendMessage`, đừng tự chạy hộ. Luật 4 của AGENT_RULES tồn tại vì agent hay báo xong theo suy luận.

**Va chạm file phát hiện ở cổng:** `git diff` file đó, giữ phiên bản của chủ sở hữu theo bảng, gửi agent kia làm lại phần của nó. Đừng gộp tay hai bản — hai agent có hai mô hình khác nhau về file đó, gộp tay là sinh ra bản thứ ba không ai kiểm.

**Câu hỏi 🔴 gom một lượt mỗi đợt**, không hỏi lẻ từng agent. `PROGRESS.md` có bảng cuối để gom.
