# T17 — Tách ảnh sang `/frame` + FrameBuffer + ảnh phân tầng

| | |
|---|---|
| **Mã spec** | F3 F4 F5 · ~~F2 (HUỶ)~~ · 27.1 27.5 |
| **SPEC gốc** | mục 19 (F3–F5), 27.1, 27.5 |
| **Repo đụng** | Server kính · **Firmware** |
| **Trạng thái** | READY (F5 chờ T15/H0 quy lại thang số) |
| **Chặn bởi** | **T01** (`X-Turn-Id` để ghép ảnh với lượt) |
| **Chặn** | T18 (F6 dùng chung hạ tầng downlink) |

> 🔴 **F2 (đảo thứ tự part: audio trước ảnh) ĐÃ BỊ HUỶ.** Thi công đúng như spec
> phần II viết sẽ làm **CHẬM ĐI**. Đọc mục 1.1 trước khi làm gì.

---

## 1. Hiện trạng

### 1.1 🔴 Vì sao F2 bị huỷ (27.1)

F2 giả định luồng `[image ~2s][audio]` — ảnh chặn STT hai giây.
**Bản firmware thật không chạy như vậy** (`src/audio/audio_service.cpp`):

```
t=0   BẤM NÚT   apiBegin() -> photoCapture() -> apiPushImage()   > ảnh đi NGAY
                apiAudioOpen()                                   > mở part audio
...   GIỮ NÚT   nén ADPCM, đẩy từng khối 256 B   > tiếng đi TRONG LÚC ĐANG NÓI
t=T   NHẢ NÚT   còn lại 0-101 ms
```

Số đo thật (README firmware §4): đẩy ảnh 25 KB mất **289 ms**, và 289 ms đó nằm
**trong lúc người dùng còn đang nói** — **không tốn của đường tới hạn một mili
giây nào**. Không phải 1–2 giây như F2 ước tính.

**Đảo thứ tự part thì hỏng:** part `audio` chỉ đóng được lúc nhả nút, mà
multipart là **tuần tự** → ảnh buộc phải đợi tới **sau** nhả nút. Ảnh chuyển từ
"miễn phí" thành **"+289 ms trên đường tới hạn"**.

→ Cách đúng để ảnh không chắn audio là **F3**, vốn đã có sẵn trong spec.
F3 lên **thay chỗ F2** trong bảng thứ tự mục 22.

### 1.2 Server kính

`app.py:449-452` — ảnh và audio nằm chung một multipart.
`:479` `image.file.read()` · `:483` `audio.file.read()` — **đọc hết mới chạy**.

Ảnh 1280×720 (~67 KB) gửi kèm **mọi** lượt, kể cả **10/15 intent không hề đọc
ảnh**: `chat`, `music_*`, `nav_*`, `contact_call`, `emergency_call`, `ride_*`,
`cancel`, `repeat`.

---

## 2. Việc phải làm

### F3 — tách ảnh sang `POST /frame`

```
socket A → POST /process   audio ADPCM, chunked, giữ mở, nhận audio stream về
socket B → POST /frame     ảnh, fire-and-forget, cùng X-Turn-Id
```

Server giữ **FrameBuffer theo device** (ring 1–3 frame + timestamp). Handler
**không đọc bytes trực tiếp từ request nữa**:

```python
frames.latest(device_id, max_age_ms=800)
```

🔴 **Đây là chỗ quan trọng nhất của cả phần II: handler không cần biết frame tới
từ đâu.** Ảnh tới trước hay sau lượt audio, tới một tấm hay vài tấm — **cùng một
API, handler không phải sửa**.

Audio không còn đợi ảnh một byte nào.

Ca phải xử lý:
```
/frame tới TRƯỚC /process     → thường gặp nhất (board chụp lúc bấm nút)
/frame tới SAU /process        → handler chờ tối đa max_age rồi xử lý không ảnh
/frame KHÔNG BAO GIỜ tới       → handler xử lý được, KHÔNG crash
frame quá max_age              → coi như không có ảnh
```

### F4 — bảng: chức năng nào cần kính gửi gì

**Đây là hợp đồng giữa firmware và server. Mọi thay đổi phải sửa ở đây trước.**

| Chức năng | Audio | Ảnh | Độ phân giải | quality* | Ghi chú |
|---|---|---|---|---|---|
| `chat` | ✅ | ❌ | — | — | không đọc ảnh |
| `ocr` | ✅ | ✅ | **tầng cao** | nét nhất | chữ nhỏ cần nét |
| `ocr` follow-up | ✅ | ❌ | — | — | dùng `last_ocr` đã cache (T14/E3) |
| `describe_space` | ✅ | ✅ | tầng thấp | — | |
| `describe_hazard` | ✅ | ✅ | tầng thấp | — | theo lượt (T16) |
| `find_object` | ✅ | ✅ | tầng giữa | — | |
| `read_money` | ✅ | ✅ | tầng giữa | — | |
| `contact_call` | ✅ | ❌ | — | — | |
| `emergency_call` | ✅ | ❌ | — | — | **không được chờ ảnh** |
| `nav_start` / `nav_stop` | ✅ | ❌ | — | — | |
| `ride_quote` / `ride_confirm` | ✅ | ❌ | — | — | |
| `music_*` | ✅ | ❌ | — | — | |
| `cancel` / `repeat` | ✅ | ❌ | — | — | không mạng ngoài, không LLM |
| trả lời pending ("ừ", "người thứ hai") | ✅ | ❌ | — | — | **không chụp lại ảnh** |

\* 🔴 **Số cụ thể phải lấy từ T15/H0** — spec cũ ghi `1600x1200 q8` / `640x480
q15`, cả hai đều sai: camera thật là **1280×720**, và esp32-camera dùng thang
**0–63, số nhỏ = nét hơn** (bản thật đang ở **18**). Điền số vào bảng này **sau
khi** T15/H0 quy lại.

### Kính không biết trước intent — chọn cách gửi

```
(a) SONG SONG  — kính cứ gửi ảnh qua socket B; server dùng nếu cần, bỏ nếu không
    ưu:    0 ms thêm vào đường tới hạn
    nhược: tốn băng thông cho 10/15 intent

(b) HAI PHA   — kính gửi audio trước; server biết intent rồi mới XIN ảnh qua
    kênh downlink (T18/F6); kính gửi khi được xin
    ưu:    tiết kiệm băng thông và pin
    nhược: +1 RTT (~80–300 ms) cho các intent CÓ dùng ảnh
```

**Chốt: (a) cho tầng ảnh nhỏ, (b) cho tầng ảnh lớn.**

### F5 — ảnh phân tầng

```
gửi NGAY, không hỏi   : tầng thấp  (~30–50 KB)  → space / hazard / find / money
gửi khi server XIN    : tầng cao                → CHỈ `ocr`
```

Chỉ `ocr` mới phải trả giá một vòng hỏi-đáp, và `ocr` vốn là intent người dùng
chấp nhận chờ lâu hơn.

> 🔴 **Ngưỡng Laplacian phải đo lại cho TỪNG TẦNG.**
> `pipeline/image_quality.py` đo trên một độ phân giải, và comment trong chính
> file đó đã ghi rõ **resize làm hỏng đúng tín hiệu tần số cao cần đo**. Dùng
> chung số cũ cho tầng thấp là **sai âm thầm — không có log nào báo**.

> ⚠️ **H6 (T15) đã kết luận: khung hình quan trọng hơn số pixel.** Tầng ảnh lớn
> cho `ocr` là *đúng nhưng không đủ* — không có H3 thì tầng đó chỉ chụp nét hơn
> **đúng cái khung hình sai**. Làm T15/H3 trước hoặc song song.

### F8 — bẫy phía server (ghi lại, xem T02)

`audio.file.read()` (`app.py:483`) hiện đọc hết audio mới chạy. Muốn STT
streaming (T21/G3) thì phải đổi sang đọc theo chunk — **làm sau F3**.

---

## 3. Hợp đồng đổi

Ghi toàn bộ bảng F4 + hai tầng ảnh vào `CONTRACTS.md`, mục *Kính gửi gì cho
lượt nào*.

```
POST /frame
  X-Device-Id   BẮT BUỘC
  X-Turn-Id     BẮT BUỘC   (ghép với lượt audio tương ứng)
  X-Capture-Ts  nên có
  body: JPEG
  → 204, fire-and-forget, KHÔNG trả gì cho board đợi
```

---

## 4. Test

### 4.1 FrameBuffer — `tests/test_frame_buffer.py` (mới)

```
test_frame_before_process
test_frame_after_process
  handler chờ tối đa max_age rồi xử lý không ảnh
test_frame_never_arrives
  handler xử lý được, KHÔNG crash
test_frame_older_than_max_age
  frames.latest() trả None, handler không crash

test_ring_keeps_latest
  gửi 5 frame → giữ 1-3 frame mới nhất
test_frames_isolated_per_device
test_frame_matched_by_turn_id
  frame của turn khác KHÔNG bị dùng nhầm
```

### 4.2 Handler không biết nguồn frame — ca chốt của F3

```
test_handler_api_unchanged
  cùng một handler chạy được với:
    ảnh trong multipart (đường cũ)
    ảnh từ /frame (đường mới)
  → KHÔNG có nhánh if nào trong handler
```

### 4.3 F4 — bảng hợp đồng

```
test_image_free_intents_never_wait_for_frame   × 10 intent
  chat · music_* · nav_* · contact_call · emergency_call · ride_* · cancel · repeat
  → 0 ms chờ frame

test_emergency_never_waits_for_frame           # 🔴 ca an toàn
test_pending_answer_does_not_request_frame     # "ừ", "người thứ hai"
test_ocr_followup_does_not_request_frame       # T14/E3
```

### 4.4 F5 — phân tầng

```
test_low_tier_used_for_space_find_money_hazard
test_high_tier_requested_only_for_ocr
test_blur_threshold_per_tier                   # 🔴
  tầng thấp và tầng cao dùng NGƯỠNG KHÁC NHAU
  → KHÔNG dùng chung số cũ
```

### 4.5 Giao thức (mục 23 spec)

```
thiếu X-Device-Id ở /frame     → từ chối rõ ràng
/frame không có X-Turn-Id       → từ chối
multipart cũ vẫn chạy           → giai đoạn chuyển
```

### 4.6 Thủ công / đo — firmware

| Kiểm | Cách | Kỳ vọng |
|---|---|---|
| Ảnh vẫn đi trong lúc nói | log timestamp `/frame` vs `/process` | `/frame` xong **trước** khi nhả nút |
| Không đảo thứ tự part | đọc `audio_service.cpp` | ảnh vẫn đi trước, **F2 không được thi công** |
| Băng thông tiết kiệm | đếm byte/lượt cho 10 intent không ảnh | giảm ~67 KB/lượt |
| RTT qua Cloudflare tunnel | đo thật | quyết định (a) hay (b) cho tầng cao — xem mục 6 |

---

## 5. DoD

```bash
pytest tests/test_frame_buffer.py -q
```

- [ ] **F2 KHÔNG được thi công** — có comment trong repo firmware ghi rõ lý do (27.1)
- [ ] `POST /frame` chạy, fire-and-forget, 204
- [ ] `frames.latest(device_id, max_age_ms)` là API **duy nhất** handler dùng
- [ ] Bốn ca thời điểm frame (4.1) xanh
- [ ] 10 intent không ảnh **không chờ frame một ms nào**
- [ ] Bảng F4 điền **số thật từ T15/H0**, không còn `1600x1200`/`q8`/`q15`
- [ ] Ngưỡng blur đo riêng cho từng tầng, có bảng số trong repo
- [ ] Đường multipart cũ vẫn chạy được trong giai đoạn chuyển

---

## 6. Câu hỏi phải chốt

1. 🔴 **(a) song song hay (b) hai pha cho tầng ảnh lớn?** Đang đề xuất (a) cho
   tầng thấp và (b) cho tầng cao. **Cần đo RTT thật qua Cloudflare tunnel để
   chốt: nếu RTT > 400 ms thì (b) mất giá.** Chưa đo.
2. **Ngưỡng blur cho từng tầng** — chưa đo. Phải chụp mẫu ở từng tầng **native**
   rồi tính lại phân bố Laplacian, **không suy ra từ số của tầng khác**.
3. **`max_age_ms` là bao nhiêu?** Spec đề xuất 800 ms. Board chụp lúc bấm nút,
   người dùng nói 2–4 giây → frame sẽ **luôn** già hơn 800 ms khi handler chạy.
   **Con số này gần như chắc chắn sai, phải đo lại.**
4. **Có nâng tầng cao lên 1600×1200 không?** Xem câu 3 của T15 — đổi sang 4:3 là
   đổi khung nhìn.
