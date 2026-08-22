# RUNBOOK — thứ tự thi công & checklist giao cho subagent

Ngày lập: 2026-08-22 · Đi kèm [`00-INDEX.md`](00-INDEX.md) và
[`CONTRACTS.md`](CONTRACTS.md)

File này để **giao việc cho AI subagent chạy tuần tự hoặc song song**. Mỗi task
có: điều kiện vào, prompt copy-paste, điều kiện ra.

---

## 0. Luật chung — dán vào **mọi** prompt subagent

```
LUẬT BẮT BUỘC

1. Đọc docs/tasks/CONTRACTS.md TRƯỚC. Đó là nguồn sự thật. Task file mô tả
   việc phải làm; CONTRACTS mô tả thứ hai bên phải đồng ý.

2. Số dòng trong task file có thể đã trôi. VERIFY bằng grep/read trước khi
   sửa. Không sửa mù theo số dòng.

3. TDD: viết test đỏ trước, rồi mới viết code. Test nào đã liệt kê trong mục
   4 của task file thì phải có đủ, đúng tên.

4. KHÔNG báo xong khi chưa chạy lệnh trong mục 5 (DoD) và nhìn thấy output
   xanh. Dán output vào báo cáo.

5. Task nào phụ thuộc repo khác mà repo đó chưa xong -> đánh dấu PARTIAL,
   ghi RÕ ca nào còn hỏng. Dùng @pytest.mark.xfail(reason="Txx: ...").
   KHÔNG xoá test, KHÔNG báo xanh giả.

6. Gặp mục "Câu hỏi phải chốt" chưa có đáp án -> làm hết phần KHÔNG phụ thuộc
   câu đó, rồi HỎI. Đừng tự chốt thay người dùng những câu đánh dấu 🔴.

7. Không mở rộng phạm vi. find_object và read_money KHÔNG ĐỤNG (spec mục 7).
   handlers/describe_hazard.py chỉ được thêm comment (E6).

8. Ba nguyên tắc xuyên suốt ở CONTRACTS mục 0 thắng mọi tối ưu. Đặc biệt:
   emergency_call không đi qua bất kỳ bước xác minh nào.

9. Có bảng số thì mới được chốt. Ngưỡng nào chưa đo thì ghi "chưa đo", đừng
   copy số cũ của cấu hình khác.

10. Báo cáo cuối theo mẫu ở RUNBOOK mục 5.
```

---

## 1. Đợt 0 — ĐO TRƯỚC, chưa code gì

> Ba việc này rẻ và **đổi mốc so sánh của mọi thứ sau đó**. Bỏ qua là đo nhầm
> toàn bộ.

- [ ] **G10** — miếng kết thúc chunked (**T02**). Một lệnh `curl`. Có thể là
      **30 giây mỗi lượt** — khoản lớn nhất phần II.
- [ ] **H0** — sửa tài liệu 1280×720 + đo lại ngưỡng Laplacian (**T15**).
      Đã biết câu trả lời, chỉ còn sửa và đo.
- [ ] **P7** — dựng bảng đối chiếu mã lỗi (**T20**). Đọc code, chưa sửa gì.
      Chặn D4.

**Ra:** `measurements/G10.md`, `measurements/H0-blur-720p.md`,
`measurements/P7-error-matrix.md`

**Chạy song song được cả ba.**

---

## 2. Sơ đồ phụ thuộc

```
T02(G10) ─┐
          ├──────────────────────────────► T21 (ngân sách)
T22(TLS) ─┤                                  ▲
          └──► T18 (SSE) ──► T19 (gọi đến)   │
                 ▲                            │
T01 (ids) ───────┼──► T17 (/frame) ───────────┘
   │             │
   └──► T03 (session/pending)
           │
           ├──► T04 (router) ──────┐
           ├──► T05 (intent) ──┐   │
           └──► T06 (slots) ───┤   │
                    ▲          │   │
T20 (mã lỗi) ───────┘          │   │
                               ▼   ▼
T07 (vị trí) ──► T05/A3    T08 T10 T12 T16
   │                            (chức năng)
   ├──► T13 (chat) ◄── T14 (ocr context)
   └──► T11 (ride) ◄── ⛔ Farefeed

T15 (ocr chất lượng)  ── độc lập, chạy song song bất cứ lúc nào
T23 (capabilities)    ── độc lập
```

---

## 3. Các đợt

### Đợt 1 — nền tảng (tuần tự, không song song được)

| # | Task | Vì sao ở đây |
|---|---|---|
| 1 | **T01** Định danh thiết bị & lượt | chặn nhiều nhất trong cả spec |
| 2 | **T03** Phiên & pending | 6 task chức năng gọi vào |
| 3 | **T04** Router & ngắt lời | 21.1 là lỗi thật, và G2 retrofit sau rất đắt |

- [ ] T01 · [ ] T03 · [ ] T04

> ⚠️ **G2 (generation counter) phải có mặt từ commit đầu của T03**, kể cả khi
> T04 chưa dùng tới. Thêm sau rất đắt.

### Đợt 2 — chạy song song được (3 nhánh)

| Nhánh | Task | Ghi chú |
|---|---|---|
| **A** | **T07** Vị trí | độc lập; mở khoá T05/A3, T11/R6, T13 |
| **B** | **T15** OCR chất lượng | hoàn toàn độc lập |
| **C** | **T22** Bật TLS *(firmware)* | chặn phát hành; chặn T18 T21 |

- [ ] T07 · [ ] T15 · [ ] T22

### Đợt 3 — trục intent/slot (T05 và T06 song song được)

| # | Task | Ghi chú |
|---|---|---|
| 4 | **T05** Intent & schema slot | A3 cần T07 xong |
| 5 | **T06** Bảng chính sách slot | D4 cần T20 (đợt 0) |

- [ ] T05 · [ ] T06

### Đợt 4 — chức năng (song song hết, 5 nhánh)

Mỗi task một session độc lập. Chúng chỉ giao nhau ở `slots.py` và `test_slots.py`
— **quy ước: mỗi task chỉ thêm ca của mình vào `test_slots.py`, không sửa ca của
task khác.**

- [x] **T08** Gọi danh bạ · PARTIAL — server xong, chờ app P1/P2 + đo danh bạ thật
- [x] **T09** Gọi khẩn cấp · PARTIAL — khóa an toàn xanh; chờ abort, classifier thấp, T21/P11
- [x] **T10** Chỉ đường · PARTIAL — server xong; D4 xfail vì app chưa phát mã
- [x] **T12** Nhạc
- [x] **T14** OCR ngữ cảnh
- [x] **T16** Không gian & vật cản

### Đợt 5 — phụ thuộc đợt 4

- [x] **T13** Chat & lịch sử *(PARTIAL: code xong, chờ đo Gemini/prefix thật)*
- [ ] **T11** Đặt xe *(cần T07; R1-R3/R5 ⛔ BLOCKED)*
- [ ] **T23** Quyền & cấu hình *(độc lập, chèn đâu cũng được)*

### Đợt 6 — hạ tầng đường truyền

| # | Task | Ghi chú |
|---|---|---|
| 6 | **T17** Tách `/frame` | 🔴 **F2 KHÔNG thi công** |
| 7 | **T18** Downlink SSE | đo RAM **sau** T22 |
| 8 | **T19** Cuộc gọi đến | cả 4 repo, từ số không |

- [ ] T17 · [ ] T18 · [ ] T19

### Đợt 7 — chốt số

- [ ] **T21** Ngân sách độ trễ · phải sau T02 + T22

---

## 4. Prompt mẫu — copy-paste cho subagent

### 4.1 Task thường

```
Thực hiện task docs/tasks/T08-contact-call.md trong repo D:\Study\innostar\Sever_test.

Đọc theo thứ tự:
  1. docs/tasks/CONTRACTS.md          (nguồn sự thật, đọc TRƯỚC)
  2. docs/tasks/T08-contact-call.md   (task)
  3. docs/tasks/00-INDEX.md           (nếu cần tra ngược)

<dán LUẬT BẮT BUỘC ở RUNBOOK mục 0>

Điều kiện vào: T03, T05, T06 đã xong.
Điều kiện ra:  mọi ô checkbox ở mục 5 (DoD) của task file đã tick, kèm output
               của lệnh pytest trong mục đó.
```

### 4.2 Task chỉ ĐO (đợt 0)

```
Thực hiện MỤC 2.1 (G10) của docs/tasks/T02-chunked-end-tts-rate.md.

CHỈ ĐO, KHÔNG SỬA CODE. Kết quả ghi vào docs/tasks/measurements/G10.md kèm
ngày và endpoint đã đo. Chạy HAI lần: localhost:8000 và qua Cloudflare tunnel.

Khác nhau -> thủ phạm là tunnel, không phải Starlette. Ghi kết luận đó vào file.
Rồi DỪNG LẠI và báo cáo, đừng tự sửa.
```

### 4.3 Task đụng repo khác

```
Task docs/tasks/T11-ride.md đụng 3 repo:
  server kính  D:\Study\innostar\Sever_test
  server app   D:\Study\innostar\app_demo_backend\apps\backend
  app Android  D:\Study\innostar\app_demo_backend\apps\android

Mục 0 của task file chia rõ LÀM ĐƯỢC NGAY và BLOCKED.
CHỈ làm phần "làm được ngay" (R4, R6, R7, P3, P4, P5).
Phần BLOCKED: viết test kèm @pytest.mark.xfail(reason="R1: chưa có quyền
partner Farefeed"), KHÔNG xoá.

Trạng thái task giữ PARTIAL. Không được đổi thành READY.
```

### 4.4 Task khoá an toàn (T09)

```
Task docs/tasks/T09-emergency-call.md.

CẢNH BÁO: task này phần lớn là KHOÁ LẠI hành vi đúng, không phải thêm tính
năng. Mỗi dòng code thêm vào phải trả lời được: nó có làm CHẬM cuộc gọi cấp
cứu không?

handlers/phone.py:50-65 KHÔNG ĐỔI LOGIC.

Ba test khoá (test_emergency_number_not_in_slots, test_emergency_never_asks_back,
test_emergency_never_reads_back) là khoá an toàn. Ai xoá phải giải trình.

So p50 ack trước/sau. Chậm đi thì rollback.
```

---

## 5. Mẫu báo cáo subagent

```markdown
## Txx — <tên task>

Trạng thái: DONE | PARTIAL | BLOCKED

### Đã làm
- <mã spec>: <file:line đã sửa>

### Chưa làm & vì sao
- <mã spec>: chặn bởi <Txx / câu hỏi mở số N ở CONTRACTS mục 7>

### Test
```
$ pytest <lệnh trong DoD>
<dán output THẬT, không tóm tắt>
```
- Thêm mới: N test
- xfail: N test, lý do: ...
- Sửa test cũ: <file>, vì sao

### Số đo (nếu có)
- Ghi vào measurements/<file>.md

### Lệch với task file
- <chỗ nào task file mô tả sai thực tế code — RẤT QUAN TRỌNG, ghi lại>

### DoD
- [x] ... / [ ] ... (ô nào chưa tick thì giải thích)

### Cần người dùng chốt
- <câu hỏi 🔴 gặp phải>
```

Mục **"Lệch với task file"** là mục dễ bị bỏ qua nhất và có giá trị cao nhất —
task file viết từ spec, mà spec có chỗ đã trôi so với code (ví dụ: T07 phát hiện
C2/P9 đã xong một phần, số dòng của `ride.py`/`music.py`/`navigation.py` đã trôi).

---

## 6. Checklist tổng

### Đợt 0 — đo trước
- [x] G10 chunked end *(T02)* → `measurements/G10.md` — CÓ tới, README firmware sai
- [x] H0 tài liệu + blur 720p *(T15)* → `measurements/H0-blur-720p.md` — đề xuất, provisional
- [x] P7 bảng mã lỗi *(T20)* → `measurements/P7-error-matrix.md` — 10 orphan/8 mute (không phải 9/7)

### Đợt 1 — nền tảng
- [x] T01 Định danh thiết bị & lượt
- [x] T03 Phiên & pending
- [x] T04 Router & ngắt lời

### Đợt 2 — song song
- [x] T07 Vị trí
- [x] T15 OCR chất lượng
- [x] T22 Bật TLS *(code xong, số đo phần cứng chờ controller)*

### Đợt 3 — intent/slot
- [x] T05 Intent & schema slot
- [x] T06 Bảng chính sách slot

### Đợt 4 — chức năng
- [x] T08 Gọi danh bạ *(PARTIAL: server xong, chờ app P1/P2 + số đo thật)*
- [x] T09 Gọi khẩn cấp *(PARTIAL: chờ abort + classifier thấp + T21/P11)*
- [x] T10 Chỉ đường *(PARTIAL: server xong, D4 chờ nguồn mã phía app)*
- [x] T12 Nhạc
- [x] T14 OCR ngữ cảnh
- [x] T16 Không gian & vật cản

### Đợt 5
- [x] T13 Chat & lịch sử *(PARTIAL: chờ đo Gemini/prefix thật)*
- [ ] T11 Đặt xe
- [ ] T23 Quyền & cấu hình

### Đợt 6 — đường truyền
- [ ] T17 Tách `/frame`
- [ ] T18 Downlink SSE
- [ ] T19 Cuộc gọi đến

### Đợt 7
- [ ] T21 Ngân sách độ trễ

### Cổng phát hành
- [ ] 🔴 T22 xong — **HTTPS bật, bắt gói xác nhận**
- [ ] 🔴 T11: P4/P5 xong — không còn chuyến nào đi tới toạ độ hằng số
- [x] 🔴 T09: 3 test khoá emergency xanh
- [ ] T21: mọi dòng ngân sách có số đo **trên bản TLS**
- [x] T20: không mã lỗi nào rơi vào im lặng

---

## 7. Việc KHÔNG được làm

| Việc | Vì sao | Nguồn |
|---|---|---|
| **F2** đảo thứ tự part multipart | làm **chậm đi** 289 ms, không nhanh lên | 27.1 / T17 |
| **Earcon phía server** | board đã có `cueSent()` ở 0 ms → bíp hai lần | 27.7 / T21 |
| Thêm bước xác minh cho **`emergency_call`** | nguyên tắc xuyên suốt #3 | mục 10 / T09 |
| Nhét `command_text` vào **`describe_hazard`** | giảm báo cáo vật cản người dùng không hỏi — đúng cái sắp làm họ vấp | E6 / T16 |
| Nhét `command_text` nguyên văn vào **`describe_space`** | thổi bay ngân sách 40 từ + bộ luật đã đo | E5 / T16 |
| Đưa **lịch sử hội thoại** vào `space`/`hazard` | ảnh mới mỗi lượt; mô tả cũ **là thông tin sai** | nguyên tắc #2 / T16 |
| Thay chỗ hở "**bài tự hết**" bằng TTL đoán mò | đã đo, đã chấp nhận | `action_flow.py:78-86` / T12 |
| Đụng **`find_object`** / **`read_money`** | ngoài phạm vi, đang đúng | mục 7 / T16 |
| Quay lại **PaddleOCR local** | CPU hàng chục giây, **và hỏng trên đúng ca 25.2** | H7 / T15 |
| Lái UI Grab bằng **AccessibilityService** | vi phạm ToS, ban tài khoản thật, người khiếm thị không phát hiện được | T11 mục 7 |
| Tắt TLS để bù độ trễ | ảnh trong nhà + giọng nói đi bản rõ | 27.3 / T22 |
| Rơi ngầm về `config.VISIONCARE_DEVICE_ID` khi thiếu header | trộn session giữa hai người dùng thật, không log nào báo | T01 |

---

## 8. Đường găng

**Ngắn nhất tới "hệ thống hội thoại chạy đúng":**

```
G10 → T01 → T03 → T04 → T05+T06 → T08/T10/T12
```

**Ngắn nhất tới "được phép phát hành":**

```
T22 (TLS)  +  T11/P4,P5 (toạ độ)  +  T09 (khoá emergency)
```

**Đang chờ người ngoài team:**

| Chờ ai | Chặn | Task |
|---|---|---|
| Grab — quyền partner Farefeed | R1 R2 R3 R5 | T11 |
| Team app — P1 `contact_list` | T08 chạy đủ hay nửa vời | T08 |
| Team app — P7 nguồn mã lỗi | D4 | T20 T10 |
| Chốt nội bộ — ai geocode | R + P4/P5 | T11 |

**Bốn thứ này nên khởi động ngay hôm nay**, song song với đợt 0 — chúng có thời
gian chờ dài nhất và không phụ thuộc code.
