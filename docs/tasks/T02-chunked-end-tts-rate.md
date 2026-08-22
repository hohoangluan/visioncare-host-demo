# T02 — Miếng kết thúc chunked & tốc độ nhả TTS

| | |
|---|---|
| **Mã spec** | **G10** · G11 · F8 |
| **SPEC gốc** | 27.4(a), 27.4(b), 27.8, F8 (mục 19) |
| **Repo đụng** | Server kính · Firmware (chỉ đọc/đối chiếu) |
| **Trạng thái** | READY |
| **Chặn bởi** | — |
| **Chặn** | T21 (bảng ngân sách G1 vô nghĩa nếu chưa biết hai khoản này) |

> 🔴 **Làm task này TRƯỚC MỌI TASK KHÁC.** G10 là **một lệnh curl**, và nếu
> README firmware đúng thì nó đang là **30 giây mỗi lượt** — lớn hơn tổng mọi
> khoản tối ưu còn lại trong spec cộng lại.

---

## 1. Hiện trạng

### (a) Khoảng im 30 giây ở cuối lượt

README firmware §4:

> Board **không** đòi miếng kết thúc `0\r\n\r\n` của chunked (server hiện không
> gửi) — nó dựa vào khoảng im 30 giây để biết đã hết.

`BODY_GAP_MS = 30000`.

**Mâu thuẫn phải kiểm chứng:** `app.py:536` dùng `StreamingResponse`, mà
Starlette + uvicorn **bình thường có** gửi miếng kết thúc khi generator cạn.
Nghĩa là một trong hai:

```
(1) README firmware đã cũ            → sửa tài liệu, không mất gì
(2) Cloudflare tunnel đệm/nuốt nó    → mỗi lượt +30 s, phải đóng tường minh
```

**Chưa ai đo.** Đừng đoán, đừng sửa mù.

### (b) Tốc độ nhả TTS quyết định lúc loa kêu — không phải TTFB

README §3.3: board so **giây tiếng nhận được** với **giây đồng hồ**.

| Server nhả | Board làm |
|---|---|
| ≥ 1.30× | đệm 400 ms rồi phát |
| ≥ 1.12× | đệm 1500 ms |
| < 1.12× và **không** biết tổng độ dài | **đợi nhận xong hết rồi mới phát** |

Luồng ADPCM không có `Content-Length` → rơi đúng vào ô cuối.

Hệ quả: **TTFB 600 ms mà TTS sinh chậm hơn thời gian thực thì người dùng không
nghe gì cho tới khi sinh xong cả câu trả lời.** Bảng ngân sách G1 đo TTFB nên
**không nhìn thấy** khoản này.

Ngưỡng phải vượt: **10.4 KB/s** với ADPCM 16 kHz.

### (c) Ràng buộc F8 — board tin thân, không tin header

`app.py` đang tuân (`:286` `prelude`, `:310-311` nhả prelude ngay). Ghi lại để
không ai phá:

```
mono bắt buộc              — ADPCM stereo board từ chối thẳng
16 000 Hz bắt buộc         — khác đi thì mỗi lượt board đổi sample rate I2S 2 lần
prelude 60 byte ra TRƯỚC   — board đọc header WAV trên luồng
chưa biết độ dài           → ghi size 0 hoặc 0xFFFFFFFF
keep-alive                 → thân trả về phải được đọc HẾT, không thì hai luồng
                             lệch vĩnh viễn
```

Mã đọc phía board tin **4 byte đầu của thân**, không tin header HTTP. Đi nhầm
nhánh ADPCM/PCM → SNR **−11 dB**, nghe ra là "loa rè", **không có log nào báo**.
Nên `x-audio-format` và thân phải khớp tuyệt đối.

`RESPONSE_FORMAT == "wav"` (`app.py:467`, nhánh `:523`) gom trọn body rồi mới
gửi → **không được dùng cho board**.

---

## 2. Việc phải làm

### 2.1 G10 — đo trước, sửa sau

```bash
# qua ĐÚNG tunnel, không phải localhost — Cloudflare mới là nghi phạm
curl -v --raw -X POST https://<tunnel>/process \
     -H 'Accept: audio/adpcm' \
     -F audio=@sample.wav -F image=@fixture.jpg \
     -o /dev/null 2>&1 | tail -30
```

Tìm `0\r\n\r\n` ở cuối.

| Kết quả | Việc |
|---|---|
| **Có** tới | README firmware sai → sửa README, đóng task, **không đụng server** |
| **Không** tới | đóng kết nối tường minh sau chunk cuối; nếu do tunnel thì cân nhắc `Content-Length` khi biết trước độ dài |

Chạy **hai lần**: một qua `localhost:8000`, một qua tunnel. Khác nhau → thủ phạm
là tunnel, không phải Starlette.

### 2.2 G11 — đo tỉ lệ nhả TTS

Thêm vào bảng ngân sách (T21) một dòng riêng, đo **từ chunk đầu tới chunk cuối**:

```
tỉ lệ = (giây tiếng đã gửi) / (giây đồng hồ đã trôi)   PHẢI ≥ 1.30
```

Ba việc kéo tỉ lệ lên (README liệt kê):

1. **flush ngay từng câu** — không gom
2. **sinh câu n+1 song song** với lúc đang đẩy câu n
3. **không chèn im lặng dẫn đầu**

### 2.3 Ghi ràng buộc F8 thành test khoá

Không phải sửa code — là **khoá lại** hành vi đúng đang có, để refactor sau
không phá âm thầm.

---

## 3. Hợp đồng đổi

Không đổi hợp đồng. Ghi vào `CONTRACTS.md` mục *Đầu ra audio cho board* toàn bộ
bảng ở 1(c) — đây là ràng buộc **cứng**, vi phạm thì không có log nào báo.

---

## 4. Test

### 4.1 Đo — không phải test tự động

`tools/measure_chunked_end.sh` **(mới)** — script G10 ở 2.1, chạy được lặp lại.
Kết quả ghi vào `docs/tasks/measurements/G10.md`, kèm ngày và endpoint đã đo.

**Nguyên tắc chung của repo: có bảng số thì mới được chốt** (giống
`config.py:104-121` và ngưỡng blur).

### 4.2 Unit — khoá ràng buộc F8

`tests/test_audio_contract.py` **(mới)**:

```
test_adpcm_is_mono_16k
  mọi đường ADPCM → 1 kênh, 16000 Hz

test_prelude_is_first_60_bytes
  chunk đầu tiên CHÍNH LÀ prelude, không có gì trước nó

test_prelude_size_field_when_length_unknown
  size = 0 hoặc 0xFFFFFFFF, không phải số bịa

test_x_audio_format_matches_body_magic
  header x-audio-format khớp 4 byte đầu của thân
  (đi nhầm nhánh = SNR -11 dB, không log nào báo)

test_wav_format_never_for_board
  Accept của board → KHÔNG rơi vào nhánh app.py:523 (gom trọn body)
```

### 4.3 Tỉ lệ nhả — test đo được

```
test_tts_release_rate_at_least_1_30x
  giả lập câu trả lời 40 từ
  đo (giây tiếng)/(giây đồng hồ) từ chunk đầu tới chunk cuối
  → ≥ 1.30, nếu không thì board sẽ ĐỢI XONG HẾT mới phát
```

Test này **fail được** trên máy chậm — đánh dấu `@pytest.mark.perf`, không chạy
trong CI mặc định, nhưng phải chạy tay trước khi chốt T21.

---

## 5. DoD

```bash
bash tools/measure_chunked_end.sh          # G10
pytest tests/test_audio_contract.py -q
pytest tests/test_audio_contract.py -m perf -q   # G11
```

- [ ] `docs/tasks/measurements/G10.md` có kết quả **localhost và tunnel**, kèm ngày
- [ ] Kết luận G10 đã ghi rõ: sửa README firmware **hoặc** đóng kết nối tường minh
- [ ] Tỉ lệ nhả TTS đo được, ghi số thật vào `measurements/G11.md`
- [ ] `tests/test_audio_contract.py` xanh, đủ 5 ca F8
- [ ] `CONTRACTS.md` có bảng ràng buộc audio cho board

---

## 6. Câu hỏi phải chốt

1. **Miếng kết thúc có tới board không?** ← chính là G10, chưa đo. Đây là 30 giây
   mỗi lượt nếu README firmware đúng.
2. Không đạt 1.30× thì làm gì trước — **flush từng câu** hay **sinh song song**?
   Cái đầu rẻ hơn nhiều, đo xem có đủ không rồi hãy làm cái sau.
