# H0 — Ngưỡng Laplacian variance đo lại trên ảnh 1280×720

Ngày đo: **2026-08-22**

Nguồn cấu hình: `CONTRACTS.md` mục 1, quyết định #6 — camera thật **1280×720,
JPEG quality 18** trên thang esp32-camera **0–63, số nhỏ = ảnh nét hơn**.

⚠️ **Số trong file này là ĐỀ XUẤT, chưa áp dụng.** `config.IMAGE_MIN_SHARPNESS`
trong `config.py` **không bị đổi** bởi phép đo này (đúng phạm vi task, xem mục
5 của prompt H0). Việc áp ngưỡng mới thuộc wave sau.

---

## 1. Ảnh dùng để đo và nguồn gốc — đọc kỹ trước khi tin số dưới đây

Bốn ảnh fixture duy nhất có trên máy này (`test_bang_am_thanh/*/` rỗng):

| File | Kích thước gốc | Xử lý | Ghi chú nguồn gốc |
|---|---|---|---|
| `tests/fixtures/space_room.jpg` | 1280×720 | không resize | **native 720p sẵn có trong repo test fixtures** |
| `tests/fixtures/find_snack.jpg` | 1280×720 | không resize | như trên |
| `tests/fixtures/money_notes.jpg` | 1280×720 | không resize | như trên |
| `tests/fixtures/ocr_screenshot.png` | 879×554 | **resize Lanczos → 1280×720** | ảnh chụp màn hình UI, không phải ảnh chụp cảnh vật |

🔴 **Cảnh báo bắt buộc, theo AGENT_RULES rule 9:**

1. **Không ảnh nào trong bốn ảnh trên được xác nhận là ảnh chụp thật từ phần
   cứng ESP32/OV2640 ở quality 18.** Ba ảnh có sẵn kích thước 1280×720 (không
   cần resize) nhưng đây là fixture test của repo — không có metadata hay
   nguồn nào xác nhận chúng được camera thật chụp ra ở đúng cấu hình
   quality 18. `ocr_screenshot.png` chắc chắn **không** phải ảnh camera — đây
   là ảnh chụp màn hình (UI, chữ render, cạnh sắc nét nhân tạo), và còn phải
   **resize** từ 879×554 lên 1280×720 nên tần số cao bị thêm/bớt bởi phép nội
   suy Lanczos, không phản ánh cảm biến thật.
2. Vì vậy: **bộ số trong file này là số đo trên ảnh thay thế, không phải số đo
   trên ảnh chụp thật ở cấu hình thật.** Đúng tinh thần rule 9 — đây không phải
   "chưa đo" (đã đo, có bảng số), nhưng là **số đo tạm/provisional trên proxy**,
   không phải số cuối. Cỡ mẫu cũng nhỏ (n=3 ảnh chụp cảnh thật khả dụng, cộng 1
   ảnh screenshot ngoại lệ) — quá nhỏ để chốt một ngưỡng production.
3. `ocr_screenshot.png` bị coi là **ngoại lệ, không dùng để đề xuất ngưỡng**:
   nội dung UI có variance Laplacian cao bất thường (xem bảng bên dưới, sharp
   = 1192 so với 46–95 của ba ảnh cảnh thật) vì cạnh chữ render máy tính sắc
   hơn hẳn cạnh trong ảnh chụp quang học. Số của nó được liệt kê để minh bạch,
   không được gộp vào min/median/max dùng để đề xuất ngưỡng.

**Kết luận về tính hợp lệ của phép đo:** đây là phép đo **thay thế tạm thời**
trên ảnh có đúng kích thước 1280×720 (3/4 ảnh không cần resize), **không phải**
phép đo trên ảnh chụp thật bằng phần cứng ở quality 18. Cần đo lại bằng ảnh
capture thật từ board (hoặc từ `storage/` nếu có ảnh production hậu-H0) trước
khi coi ngưỡng này là chung cuộc.

---

## 2. Công cụ và thuật toán

Không tạo file trong `tools/` (ngoài phạm vi file được phép sửa của task này —
xem mục "Lệch với task file"). Đo bằng script tạm trong scratchpad, gọi thẳng
hàm `_sharpness()` thật của `pipeline/image_quality.py` (không viết lại thuật
toán, để đảm bảo đúng 100% phép tính production: convolution Laplacian 3×3
float64 thủ công bằng numpy, **không dùng** `PIL.ImageFilter.Kernel` — module
gốc đã ghi chú kernel đó tự clamp giá trị về [0,255] khiến variance sai lệch
cả chục lần).

Môi trường: `.venv/Scripts/python.exe`. Đã kiểm tra sẵn có: `opencv-python
4.10.0` (cv2), `numpy 2.3.5`, `Pillow 12.3.0`. **Không dùng cv2** cho phép đo
này để giữ nhất quán tuyệt đối với hàm production (dùng PIL + numpy, không
dùng cv2).

Script (chạy trong scratchpad, không phải file repo):

```python
import sys
sys.path.insert(0, r"D:\Study\innostar\Sever_test")
import numpy as np
from PIL import Image, ImageFilter
from pipeline.image_quality import _sharpness  # tái sử dụng đúng hàm production

FIXTURES_DIR = r"D:\Study\innostar\Sever_test\tests\fixtures"
FILES = ["ocr_screenshot.png", "space_room.jpg", "find_snack.jpg", "money_notes.jpg"]
TARGET_SIZE = (1280, 720)
MILD_BLUR_RADIUS = 1   # PIL ImageFilter.GaussianBlur, tái lập được
HEAVY_BLUR_RADIUS = 4

def to_arr(img):
    return np.asarray(img.convert("L"), dtype=np.float64)

for fname in FILES:
    img = Image.open(f"{FIXTURES_DIR}/{fname}")
    if img.size != TARGET_SIZE:
        img = img.resize(TARGET_SIZE, Image.LANCZOS)   # duy nhất ocr_screenshot.png
    img = img.convert("RGB")
    sharp = _sharpness(to_arr(img))
    mild  = _sharpness(to_arr(img.filter(ImageFilter.GaussianBlur(radius=MILD_BLUR_RADIUS))))
    heavy = _sharpness(to_arr(img.filter(ImageFilter.GaussianBlur(radius=HEAVY_BLUR_RADIUS))))
    print(fname, sharp, mild, heavy)
```

**Cách tạo "mờ nhẹ" / "mờ nặng":** `PIL.ImageFilter.GaussianBlur(radius=r)` áp
lên ảnh RGB **trước khi** chuyển sang grayscale và tính Laplacian — đây là
phép blur tái lập được 100% (cùng bán kính ra cùng kết quả), không phải blur
thật từ rung tay/lệch tiêu cự, nhưng là chuẩn phổ biến để tạo ảnh mờ tổng hợp.
Bán kính (`r=1` mờ nhẹ, `r=4` mờ nặng) được chọn sau khi quét dải `r ∈
{0.5,1,1.5,2,3,4,6,8}` trên `space_room.jpg` để tìm mức có độ tách biệt rõ so
với ảnh gốc mà chưa chạm đáy bão hoà (từ `r≈6` trở lên variance gần như đi
ngang — bị chặn dưới bởi nhiễu nén JPEG, không giảm thêm được nhiều):

```
space_room.jpg  gốc=95.26  r0.5=53.05  r1=13.06  r1.5=5.13  r2=3.24
                r3=2.15  r4=1.79  r6=1.54  r8=1.45
```

---

## 3. Kết quả — cỡ mẫu n=3 ảnh cảnh thật (+ 1 ảnh screenshot liệt kê riêng)

| File | sharp (gốc) | mờ nhẹ (r=1) | mờ nặng (r=4) |
|---|---|---|---|
| `space_room.jpg` | 95.26 | 13.06 | 1.79 |
| `find_snack.jpg` | 75.49 | 11.08 | 1.66 |
| `money_notes.jpg` | 46.43 | 8.08 | 1.53 |
| `ocr_screenshot.png` *(ngoại lệ, không tính vào min/median/max bên dưới)* | 1192.16 | 194.96 | 1.16 |

**Tổng hợp trên n=3 ảnh cảnh thật (loại `ocr_screenshot.png`):**

| Nhóm | n | min | median | max |
|---|---|---|---|---|
| sharp (ảnh gốc, không blur) | 3 | 46.43 | 75.49 | 95.26 |
| mờ nhẹ (GaussianBlur r=1) | 3 | 8.08 | 11.08 | 13.06 |
| mờ nặng (GaussianBlur r=4) | 3 | 1.53 | 1.66 | 1.79 |

Khoảng cách giữa nhóm "mờ nặng" (max 1.79) và nhóm "mờ nhẹ" (min 8.08) là
khoảng **4.5×**, không chồng lấn trong mẫu này.

---

## 4. Đề xuất ngưỡng (PROPOSED, chưa áp dụng)

`config.IMAGE_MIN_SHARPNESS` hiện tại (`config.py:142`) = **5** — con số này
được set từ trước, không rõ nguồn gốc đo trên cấu hình nào (không phải từ bộ
số 1600×1200 cũ ghi trong docstring, vì bộ đó ghi min=0.70, không phải 5).

Trên mẫu 720p đo được ở đây, ngưỡng 5 tình cờ **nằm gọn trong khoảng trống**
giữa "mờ nặng" (max 1.79) và "mờ nhẹ" (min 8.08) — nghĩa là nếu ngưỡng 5 tiếp
tục được dùng, nó sẽ **loại đúng nhóm mờ nặng, giữ lại đúng nhóm mờ nhẹ và
nhóm nét** trên bộ mẫu nhỏ này.

**Đề xuất:** giữ `IMAGE_MIN_SHARPNESS` ở khoảng **4–6** (ví dụ giữ nguyên 5),
nằm trong dải trống [1.79, 8.08] đo được. **Đây là con số PROPOSED, không phải
số chốt**, vì ba lý do:

1. n=3 ảnh cảnh thật — quá nhỏ để chốt ngưỡng production.
2. Không ảnh nào được xác nhận là ảnh chụp thật bằng phần cứng ở quality 18
   (mục 1 ở trên).
3. "Mờ" ở đây là Gaussian blur tổng hợp, không phải mờ thật do rung tay/lệch
   nét — nhiễu nén JPEG, ánh sáng, và đặc điểm ống kính OV2640 thật có thể cho
   phân bố khác.

**Việc cần làm trước khi chốt** (ghi lại theo đúng ghi chú trong
`pipeline/image_quality.py` — gate hiện tại đo trên **khung đã được board chọn
là nét nhất của cả loạt** qua `photoCapture()` + `photoMeasureSharpness()`, nên
ngưỡng cuối cùng phải đo trên đúng phân bố đó, không phải trên ảnh chụp đơn
lẻ như phép đo tạm này):

- Thu thập ảnh chụp thật từ board ở đúng cấu hình 1280×720/quality 18 (ví dụ từ
  `storage/` nếu có, hoặc log request thật sau khi hệ thống chạy ở cấu hình
  mới).
- Đo lại đúng script này trên bộ ảnh thật đó, cỡ mẫu đủ lớn (khuyến nghị theo
  đúng tinh thần bộ số cũ: ~80+ request như lần đo 1600×1200 trước đây).
- So khớp lại khoảng trống mờ-nhẹ/mờ-nặng trên ảnh thật trước khi đổi
  `config.IMAGE_MIN_SHARPNESS`.

---

## 5. Giới hạn của phép đo này

- Cỡ mẫu rất nhỏ (n=3 ảnh cảnh thật, 1 ảnh ngoại lệ) — không đủ để chốt ngưỡng
  production, chỉ đủ để có một con số đề xuất tạm và một khoảng an toàn ban đầu.
- Không xác nhận được nguồn gốc ảnh là capture thật từ ESP32/OV2640 ở quality
  18 — xem cảnh báo ở mục 1.
- "Mờ" là Gaussian blur tổng hợp (PIL `ImageFilter.GaussianBlur`), không phải
  mờ vật lý thật (rung tay, lệch tiêu cự, chuyển động).
- Gate thật trong production đo trên khung **đã được board chọn là nét nhất
  của một loạt ảnh** (`photoCapture()` + `photoMeasureSharpness()`), phép đo
  này đo trên ảnh đơn — hai phân bố có thể không giống nhau.
- Đo 1 lần cho mỗi ảnh (không lặp lại/không có nhiều điều kiện sáng khác
  nhau).
