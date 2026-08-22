# T15 — OCR: chất lượng đọc chữ (model, khung hình, hướng ảnh)

| | |
|---|---|
| **Mã spec** | H0 H1 H2 H3 H4 H5 H6 H7 |
| **SPEC gốc** | mục 25, 27.5 |
| **Repo đụng** | Server kính · Firmware (tài liệu + cấu hình camera) |
| **Trạng thái** | READY — H2/H7 **có điều kiện** |
| **Chặn bởi** | — (độc lập T14, chạy song song được) |
| **Chặn** | T17/F5 (thang chất lượng ảnh) |

> Nguồn: một **ca thật** — ảnh chụp cuốn brochure RMIT đặt trên bàn, Gemini
> không đọc ra chữ nào.
>
> Mục 4/T14 lo **ngữ cảnh** OCR. Task này lo chuyện trước đó: **đọc được hay
> không**.

---

## 1. Hiện trạng

`models/ocr/__init__.py:24` `read_stream` gọi đúng **một** lượt Gemini, model lấy
từ `config.GEMINI_MODEL` (`config.py:95`). Không có bước tiền xử lý ảnh nào giữa
bytes của kính và `types.Part.from_bytes` (`models/vlm/client.py:97-105`) —
**không xoay, không crop, không tăng tương phản**.

Việc chỉnh hướng ảnh **đang được giao hết cho prompt**
(`models/ocr/prompts.py:13-21`):

> "Ảnh có thể bị nghiêng hoặc ngược chiều — tự xoay lại trong đầu rồi hãy đọc."

Gate ảnh (`pipeline/image_quality.py:106` `reject_reason`, `:62`
`_NEEDS_SHARPNESS`) **cố ý không** chặn `ocr` theo độ nét — chỉ `money` mới chặn.
**Quyết định đó vẫn đúng, task này không đụng vào.**

### 25.1 — chạy model `-lite` cho tác vụ khó nhất pipeline

`models/.env` đặt `GEMINI_MODEL=gemini-3.5-flash-lite`. Biến này dùng chung cho
**mọi** handler VLM: `ocr`, `space`, `hazard`, `find`, `money`, `chat`.

Trong nhóm đó `ocr` đòi hỏi cao nhất: `space`/`hazard` chỉ cần nhận ra khối lớn,
sai vài chi tiết vẫn ra câu trả lời có ích; **`ocr` sai một ký tự là đọc sai**.

**Không đổi thẳng được**: nâng `GEMINI_MODEL` kéo theo `space`/`hazard` chậm hơn
— mà hai cái đó là intent đi bộ, cần nhanh.

Cùng lý do đã tách `GEMINI_INTENT_MODEL` (`config.py:121`) và
`GEMINI_SEARCH_MODEL` (`:100`): mỗi bước có ràng buộc riêng thì phải có biến riêng.

### 25.2 — ba lỗi **khung hình**, không phải lỗi model

Ca thật hỏng ở ba chỗ cùng lúc:

```
1. xoay 180°            — chữ lộn ngược hoàn toàn
2. góc chụp sát mặt bàn — perspective gắt, dòng chữ bị nén dẹp còn vài pixel
3. chữ quá nhỏ trong khung — hơn nửa khung là mặt bàn trống
```

**Lỗi (3) là lỗi giết chết.** Dưới khoảng **20 px chiều cao ký tự**, không model
nào — VLM hay OCR chuyên biệt — đọc chắc được; nó chuyển sang **đoán theo hình
dạng từ**. Lỗi (2) nhân thêm (3).

**Không sửa được bằng cách đổi model. Phải sửa ở lúc chụp.**

### 25.3 — người khiếm thị không biết mình chụp hỏng ở đâu

`KHONG_CO_CHU` → câu duy nhất nghe được là `_NO_TEXT_MESSAGE`
(`models/ocr/__init__.py:10`): *"Không thấy rõ chữ trong ảnh, vui lòng chụp
lại."*

Câu này **không nói phải sửa cái gì**. Người sáng nhìn màn hình là biết ngay "à,
chụp xa quá"; người khiếm thị chụp lại **y hệt tư thế cũ**, hỏng y hệt. Lần chụp
thứ hai **không được cấp thêm một thông tin nào** so với lần một.

### 25.4 / 27.5 — H0 ✅ **ĐÃ CÓ CÂU TRẢ LỜI**

Firmware chốt **1280×720, JPEG quality 18** (`src/camera/camera_device.cpp`),
~67 KB — khớp đúng **37/37** ảnh đo được trong `storage/`.

Vậy `CLAUDE.md` và docstring `pipeline/image_quality.py:8` ghi **1600×1200 là
sai tài liệu**, không phải firmware vừa đổi cấu hình.

1280×720 = 0.92 MP so với 1600×1200 = 1.92 MP — **chưa tới một nửa số pixel**, và
tỉ lệ 16:9 cắt mất chiều dọc, **đúng chiều mà một trang giấy cần nhất**.

### 25.5 — không có số liệu về tỉ lệ đọc hỏng

`KHONG_CO_CHU` không được đếm ở đâu. Không biết OCR hỏng 5 % hay 50 % số lượt →
**không có mốc để nói bất kỳ cải tiến nào dưới đây có tác dụng hay không**.

---

## 2. Việc phải làm — theo đúng thứ tự này

Thứ tự **không tuỳ ý**: mỗi bước đổi mốc so sánh của bước sau.

### H0 ✅ — sửa tài liệu + đo lại ngưỡng blur

Đã xác minh. Việc còn lại:

1. Sửa **1280×720** ở: `CLAUDE.md`, docstring `pipeline/image_quality.py:8`,
   bảng **F4** (T17).
2. **Đo lại ngưỡng Laplacian** trên chính bộ ảnh 1280×720. Bộ số cũ
   (min 0.70 / median 19.38 / max 108.94, đo trên 83 request "1600×1200") đang
   **mô tả một cấu hình không chạy**.
3. **F5 phải viết lại thang chất lượng.** Spec ghi `jpeg_q 8` và `q15`, nhưng
   esp32-camera dùng thang **0–63, số nhỏ = nét hơn**, và bản thật đang ở **18**.
   Quy hết số trong F4/F5 về thang đó, nếu không là **đọc ngược**.

> ⚠️ `photoCapture()` đã chụp **một loạt rồi giữ khung nét nhất** vào PSRAM, và
> board có sẵn `photoMeasureSharpness()`. Nghĩa là ảnh gate nhận được **đã là
> khung tốt nhất của loạt** — ngưỡng blur phải đo trên **phân bố đó**, không phải
> trên ảnh chụp đơn.

### H5 — log `KHONG_CO_CHU` (rẻ, làm sớm, tạo mốc)

Ghi kèm `sharpness` / `brightness` **đã đo sẵn ở gate**
(`pipeline/image_quality.py:74` `measure`) — không tính lại.

Có số này mới trả lời được *"OCR hỏng bao nhiêu phần trăm"*, và mới biết H1–H3
kéo được xuống bao nhiêu.

### H1 — tách `GEMINI_OCR_MODEL`

```python
# config.py, cạnh GEMINI_SEARCH_MODEL (:100)
GEMINI_OCR_MODEL = get("GEMINI_OCR_MODEL", "gemini-3.5-flash")   # KHÔNG -lite
```

`models/ocr/__init__.py` truyền model này xuống `vlm.generate_stream` — hiện
`models/vlm/client.py:106-140` **hardcode `config.GEMINI_MODEL`**, thêm tham số
`model: str | None = None`.

**Handler khác không đổi một dòng.**

Rẻ nhất trong task này và **phải làm trước**, vì nó đổi **mốc so sánh** cho mọi
mục sau: đo H2/H3 trên nền model lite là **đo nhầm**.

Đổi lại: OCR chậm hơn. Chấp nhận được — `ocr` vốn là intent người dùng chờ lâu
nhất, và **đọc sai đắt hơn đọc chậm**.

### H4 — bench trước khi chốt, **không chốt theo cảm giác**

Script chạy trên bộ ảnh thật trong `storage/`:

```
model:    gemini-3.5-flash-lite × gemini-3.5-flash × gemini-2.5-flash
biến thể: nguyên bản × xoay 180° × crop vùng chữ
đo:       đọc đúng / đọc sai / KHONG_CO_CHU  +  p50, p95 độ trễ
```

Bộ ảnh **phải gồm cả ca hỏng** (ảnh brochure lộn ngược ở 25.2) lẫn ca thường —
không thì chỉ đo được một đầu của phân bố.

Cùng nguyên tắc đã dùng cho `GEMINI_INTENT_MODEL` (`config.py:104-121`) và ngưỡng
blur: **có bảng số trong repo thì mới được chốt**.

### H3 — 🔴 câu hướng dẫn chụp **cụ thể và tăng dần** (lợi nhất trên công)

```
lần 1: "Không thấy rõ chữ. Đưa kính lại gần trang giấy hơn, cách khoảng một
        gang tay."
lần 2: "Vẫn chưa đọc được. Hướng kính thẳng xuống trang giấy, đừng chụp chếch
        từ bên cạnh."
lần 3: "Chưa đọc được. Thử đặt trang giấy lên mặt phẳng, chỗ đủ sáng."
```

Đếm lần bằng `attempt` của pending (T03/21.2) — **không dựng bộ đếm riêng**.

Ba câu cố định → dựng sẵn audio qua `pipeline/phrases.py` (T06/G5).

**Đây là mục lợi nhất trên công bỏ ra của cả task**: không tốn compute, không tốn
độ trễ, và nó sửa đúng nguyên nhân số một (25.2) mà H1 **không chạm tới được**.

**Độc lập H0–H2, làm song song được.**

### H2 — retry xoay 180°, **chỉ trên đường hỏng** (có điều kiện)

Lượt đầu trả `KHONG_CO_CHU` → xoay 180° bằng PIL rồi gọi lại **một lần**.
Đường thành công không đổi → **không tốn một mili giây nào** của lượt đọc được.

Chỉ 180°, **không quét cả 4 hướng**: mỗi hướng là một lượt gọi nữa, và kính đeo
đầu thì lỗi hay gặp là lộn ngược chứ không phải nằm ngang.

> ⚠️ Làm H2 **sau** khi đo H1/H4. Có khả năng bản không `-lite` tự xử lý được
> ảnh ngược — lúc đó H2 là **công thừa**. Đừng làm cả hai rồi mới đo.

### H6 — khung hình hơn độ phân giải

Nâng 1280×720 → 1600×1200 chỉ tăng chiều cao ký tự ~**1.5×**; đưa kính lại gần
để chữ chiếm trọn khung thì tăng **3–5×**.

Kết luận cho T17/F5: tầng ảnh lớn dành cho `ocr` là **đúng nhưng không đủ** —
không có H3 thì tầng đó chỉ chụp nét hơn **đúng cái khung hình sai**.

### H7 — OCR chuyên biệt: **phương án cuối** (có điều kiện)

Chỉ khi H1+H3+H4 đo xong **vẫn không đạt**.

**Không quay lại PaddleOCR local.** Lý do đã ghi ở `models/ocr/prompts.py:3-6`
(CPU mất hàng chục giây), và còn một lý do nặng hơn: **PaddleOCR hỏng trên đúng
ca 25.2** — perspective gắt cộng chữ nhỏ là điểm yếu chung của mọi OCR, nó không
cứu được gì mà mất thêm 20 s.

Nếu vẫn cần: Google Cloud Vision `DOCUMENT_TEXT_DETECTION` (~200–400 ms, chịu ảnh
xoay/nghiêng tốt hơn VLM), lấy text rồi đẩy sang Gemini dịch.

Đổi lại: quay về kiến trúc **hai chặng** vừa bỏ, mất khả năng "vừa đọc vừa dịch
trong một lượt", thêm một nhà cung cấp phải quản key + hạn mức. **Chỉ trả cái
giá đó khi có số của H4 chứng minh là cần.**

---

## 3. Hợp đồng đổi

Không đổi hợp đồng mạng. Nhưng **sửa tài liệu là bắt buộc** — ghi vào
`CONTRACTS.md`: camera thật = **1280×720, esp32-camera quality 18 (thang 0–63,
nhỏ = nét)**.

---

## 4. Test

### 4.1 Unit — `tests/test_ocr_quality.py` (mới)

```
test_ocr_model_is_separate                   # H1
  GEMINI_OCR_MODEL ≠ GEMINI_MODEL
  → space/hazard/find/money VẪN dùng model cũ

test_vlm_accepts_model_param                 # H1
  generate_stream(model=...) hoạt động, mặc định vẫn config.GEMINI_MODEL

test_rotate_retry_only_on_sentinel           # H2
  lượt đầu ra chữ    → gọi Gemini ĐÚNG 1 lần
  lượt đầu sentinel  → gọi ĐÚNG 2 lần (bản gốc + xoay 180°)
  (đếm số lời gọi, không đọc log)

test_no_infinite_retry                       # H2
  ảnh tường trắng → sentinel, KHÔNG retry vô hạn

test_rotate_disabled_does_not_crash           # H2 tắt
  → ra KHONG_CO_CHU bình thường

test_guidance_escalates                       # 🔴 H3
  attempt 1/2/3 → BA câu KHÁC nhau
test_guidance_all_prebuilt                    # H3 + G5
  cả ba câu nằm trong tập collect() của phrases.py

test_attempt_counter_from_pending             # H3
  dùng pending.attempt, KHÔNG có bộ đếm riêng

test_no_text_logged_with_metrics               # H5
  KHONG_CO_CHU → log có sharpness + brightness
  → lấy từ gate, KHÔNG đo lại
```

### 4.2 Đo — không phải test tự động

| Script | Ra file |
|---|---|
| `tools/bench_ocr_matrix.py` (H4) | `docs/tasks/measurements/H4.md` |
| `tools/measure_laplacian_720p.py` (H0) | `docs/tasks/measurements/H0-blur-720p.md` |

Bộ ảnh: `storage/` + **ảnh brochure lộn ngược của ca 25.2** (phải giữ lại làm
fixture, đặt trong `tests/fixtures/`).

### 4.3 Ngân sách

```
test_ocr_p95_within_budget                    # sau H1
  p95 độ trễ ocr vẫn nằm trong bảng G1 (T21)
  ⚠️ bảng G1 CHƯA CHỐT SỐ CHO OCR — xem mục 6
```

### 4.4 Thủ công — bắt buộc, đây là task về ảnh thật

| Kịch bản | Đạt khi |
|---|---|
| Chụp brochure lộn ngược (ca 25.2) | đọc ra chữ, hoặc ra hướng dẫn **cụ thể** |
| Chụp xa, chữ nhỏ | nghe câu **"đưa kính lại gần, khoảng một gang tay"** |
| Chụp chếch từ bên cạnh, thử lại | lần 2 nghe câu **khác** lần 1 |
| Thử 3 lần liên tiếp | ba câu khác nhau, không lặp |
| Chụp tường trắng | KHONG_CO_CHU, không treo, không retry mãi |

---

## 5. DoD

```bash
pytest tests/test_ocr_quality.py -q
python tools/bench_ocr_matrix.py               # H4
```

- [ ] Tài liệu sửa về **1280×720** ở cả 3 chỗ (`CLAUDE.md`, `image_quality.py:8`, bảng F4)
- [ ] Ngưỡng Laplacian **đo lại trên ảnh 720p**, có bảng số trong repo
- [ ] Thang chất lượng quy về **0–63 (nhỏ = nét)** ở mọi tài liệu
- [ ] `GEMINI_OCR_MODEL` tách riêng, handler khác không đổi
- [ ] `measurements/H4.md` có ma trận 3 model × 3 biến thể, kèm ca hỏng thật
- [ ] Ba câu hướng dẫn H3 khác nhau, đều dựng sẵn audio, dùng `pending.attempt`
- [ ] `KHONG_CO_CHU` được đếm (H5) — có số trước/sau để chứng minh cải tiến
- [ ] H2 **chỉ làm nếu H4 chứng minh là cần** — không thì ghi "không cần, xem H4"
- [ ] H7 **không làm** trừ khi có số chứng minh

---

## 6. Câu hỏi phải chốt

1. **Bản không `-lite` có tự xử lý được ảnh xoay 180° không?** Chưa đo. Quyết
   định **H2 có tồn tại hay không** nằm ở câu trả lời này.
2. 🔴 **Ngân sách độ trễ cho `ocr` là bao nhiêu (G1)?** Bảng G1 (T21) **chưa chốt
   số cho `ocr`**. Không có nó thì không nói được H1 "chậm hơn" là chấp nhận được
   hay không.
3. **Có nâng camera lên 1600×1200 không?** OV2640 lên tới UXGA, đổi ở
   `camera_device.cpp`. Nhưng đổi sang 4:3 là **đổi luôn khung nhìn**, và H6 đã
   kết luận khung hình quan trọng hơn số pixel. **Làm H3 trước, rồi đo lại.**
