"""H4 (T15) -- bench 3 model x 3 bien the OCR tren anh that, ghi ra
docs/tasks/measurements/H4.md.

Goi Gemini THAT (khong mock) qua models.vlm.client.generate_stream(...,
model=...) -- tham so `model` la phan T15/H1 them vao. Khong phai test tu
dong (xem tests/test_ocr_quality.py cho phan do); day la script do so, dung
tinh than "co bang so thi moi duoc chot" (AGENT_RULES muc A9).

Chay: .venv/Scripts/python.exe tools/bench_ocr_matrix.py
Ton API quota that + vai phut dong ho (27 luot goi = 3 anh x 3 bien the x 3
model).
"""
from __future__ import annotations

import io
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

# Console Windows mặc định cp1252 -> in tiếng Việt (output thật từ Gemini) làm
# crash UnicodeEncodeError giữa chừng bench, mất hết kết quả đã gọi tốn tiền.
# reconfigure() an toàn: Python 3.7+, no-op nếu stream không hỗ trợ.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from models.ocr import prompts  # noqa: E402
from models.vlm import client as vlm_client  # noqa: E402
from models.vlm.client import VLMError  # noqa: E402

MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash"]

REPORT_PATH = str(PROJ / "docs" / "tasks" / "measurements" / "H4.md")
MEASURED_DATE = "2026-08-22"


@dataclass
class BaseImage:
    name: str
    path: str
    expect_no_text: bool  # True: dung ra PHAI la KHONG_CO_CHU (ca hong that)
    expect_keywords: tuple  # match khong phan biet hoa thuong
    crop_box: tuple | None
    crop_scale: float
    note: str


# Ba anh nay duoc chon bang cach quet toan bo storage/ that (xem
# docs/tasks/reports/T15.md muc "Da lam" cho cach chon): 187/477 file trong
# storage/ la anh that hop le (con lai la fixture "fake img" cua test cu, xem
# canh bao trong file report). request53.jpg va request323.jpg la anh CAMERA
# THAT, khong phai anh dung.
BASE_IMAGES = [
    BaseImage(
        name="screenshot_UI",
        path="tests/fixtures/ocr_screenshot.png",
        expect_no_text=False,
        expect_keywords=("constraint", "gioi han", "bo nho", "ram", "han"),
        crop_box=(0, 0, 879, 277),
        crop_scale=1.4,
        note="chu render may tinh, canh sac net nhan tao -- ca DE",
    ),
    BaseImage(
        name="request53_paradox",
        path="storage/request53.jpg",
        expect_no_text=False,
        expect_keywords=("paradox",),
        crop_box=(330, 560, 820, 720),
        crop_scale=2.0,
        note=(
            "ANH CAMERA THAT (1280x720, sharp=95.3 do bang "
            "pipeline.image_quality._sharpness -- anh net nhat trong 187 anh "
            "that co trong storage/), chu logo ao nho trong khung rong -- ca VUA"
        ),
    ),
    BaseImage(
        name="request323_overexposed",
        path="storage/request323.jpg",
        expect_no_text=True,
        expect_keywords=(),
        crop_box=(300, 100, 1100, 650),
        crop_scale=1.3,
        note=(
            "ANH CAMERA THAT chup hong: chay sang gan het khung "
            "(bright=225.6, sharp=2.9 -- do bang dung ham "
            "pipeline.image_quality._sharpness/measure production, khong "
            "dung lai thuat toan khac). DAY LA CA HONG THAT lay tu storage/, "
            "khong phai anh dung de mo phong ca 25.2."
        ),
    ),
]


def _encode_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _variants(base: BaseImage) -> dict:
    img = Image.open(PROJ / base.path)

    orig_bytes = _encode_jpeg(img)

    rotated = img.transpose(Image.ROTATE_180)
    rotated_bytes = _encode_jpeg(rotated)

    if base.crop_box:
        cropped = img.crop(base.crop_box)
        if base.crop_scale != 1.0:
            cropped = cropped.resize(
                (int(cropped.width * base.crop_scale), int(cropped.height * base.crop_scale)),
                Image.LANCZOS,
            )
    else:
        cropped = img
    cropped_bytes = _encode_jpeg(cropped)

    return {
        "nguyen ban": orig_bytes,
        "xoay 180 do": rotated_bytes,
        "crop vung chu": cropped_bytes,
    }


def _classify(base: BaseImage, output: str):
    """Tra (nhan, dung_ky_vong)."""
    if prompts.NO_TEXT_SENTINEL in output:
        return "KHONG_CO_CHU", base.expect_no_text
    low = output.lower()
    if base.expect_keywords and any(k in low for k in base.expect_keywords):
        return "doc dung", True
    return "doc sai", False


@dataclass
class Result:
    model: str
    image: str
    variant: str
    label: str
    matches_expected: bool
    latency_s: float
    output_snippet: str


def run():
    results = []
    for base in BASE_IMAGES:
        variants = _variants(base)
        for variant_name, image_bytes in variants.items():
            for model in MODELS:
                started = time.monotonic()
                try:
                    text = "".join(
                        vlm_client.generate_stream(
                            prompts.build("normal"), image=image_bytes, model=model
                        )
                    )
                    elapsed = time.monotonic() - started
                    label, ok = _classify(base, text)
                    snippet = text.strip().replace("\n", " ")[:140]
                except VLMError as exc:
                    elapsed = time.monotonic() - started
                    label, ok = "ERROR", False
                    snippet = str(exc)[:140]
                results.append(
                    Result(model, base.name, variant_name, label, ok, elapsed, snippet)
                )
                print(
                    f"{model:24s} {base.name:24s} {variant_name:14s} -> "
                    f"{label:12s} {'OK' if ok else 'X':2s} {elapsed:5.2f}s  {snippet}"
                )
    return results


def _latency_stats(results):
    by_model = {}
    for r in results:
        if r.label != "ERROR":
            by_model.setdefault(r.model, []).append(r.latency_s)
    stats = {}
    for model, lats in by_model.items():
        lats_sorted = sorted(lats)
        n = len(lats_sorted)
        p50 = statistics.median(lats_sorted)
        p95_idx = min(n - 1, int(round(0.95 * (n - 1))))
        p95 = lats_sorted[p95_idx]
        stats[model] = (p50, p95, n)
    return stats


def _rotation_answer(results):
    """Cau hoi mo #1 (T15 muc 6): model KHONG -lite co tu doc duoc anh xoay
    180 khong? Chi xet hai anh co chu that (bo qua ca overexposed vi ca do du
    khong xoay cung khong co chu)."""
    lines = []
    for model in MODELS:
        rows = [
            r for r in results
            if r.model == model and r.variant == "xoay 180 do"
            and r.image != "request323_overexposed"
        ]
        n_ok = sum(1 for r in rows if r.matches_expected)
        lines.append(f"- `{model}`: {n_ok}/{len(rows)} anh xoay 180 doc dung")
    return lines


# Phân tích viết tay sau khi đọc số của lượt đo ngày 2026-08-22 (xem lịch sử
# git cho đúng bảng số gốc nếu một lượt chạy lại sau này ra số khác — mô hình
# Gemini không xác định 100%). Giữ cố định ở đây để lượt chạy lại không làm
# mất kết luận, dù bảng số phía trên có thể xê dịch nhẹ giữa các lần chạy.
_STATIC_ANALYSIS = """---

## Phân tích & khuyến nghị (đo ngày 2026-08-22, xem lịch sử git nếu số phía trên đã đổi ở lượt chạy khác)

### H1 — khuyến nghị `GEMINI_OCR_MODEL = "gemini-3.5-flash"` (đã đặt trong `config.py`)

- `gemini-3.5-flash-lite` (model `space`/`hazard` vẫn dùng, không đổi): rẻ nhất
  nhưng ở lượt đo gốc đã bỏ sót đúng ca khó nhất (chữ nhỏ trong khung rộng —
  khớp cảnh báo 25.2 "chữ quá nhỏ trong khung là lỗi giết chết").
- `gemini-3.5-flash`: ở lượt đo gốc 0 lượt bỏ sót trên ảnh có chữ thật — đánh
  đổi độ trễ cao hơn chấp nhận được theo đúng lý do nêu ở H1 ("đọc sai đắt
  hơn đọc chậm").
- `gemini-2.5-flash`: cũng không bỏ sót nhưng dính lỗi hạ tầng 503
  UNAVAILABLE (Google báo "high demand") và độ trễ p95 cao hơn hẳn — kém ổn
  định hơn, không chọn.

### H2 — KHÔNG CẦN, xem mục "Câu hỏi mở #1" ở trên

Ở lượt đo gốc, cả 3 model — kể cả `-lite` — tự đọc đúng ảnh xoay 180° qua
đúng câu prompt hiện có ("Ảnh có thể bị nghiêng hoặc ngược chiều — tự xoay
lại trong đầu rồi hãy đọc"), không cần gọi lại Gemini lần hai. Điều kiện của
task ("H2 chỉ làm nếu H4 chứng minh là cần") không thoả trên bộ ảnh này —
KHÔNG cài retry xoay 180°. Trả lời câu hỏi mở #1 (T15 mục 6): có, bản không
`-lite` (và cả `-lite`) tự xử lý được ảnh xoay 180° trên mẫu đo này.

### H7 — không đụng tới

Không lượt nào ở lượt đo gốc cho thấy Gemini đọc kém vì bản thân công nghệ
VLM — lỗi duy nhất là hạ tầng 503 tạm thời, không phải lỗi đọc. Không đủ căn
cứ để trả giá kiến trúc hai chặng (Cloud Vision + dịch) như H7 mô tả.

### Phát hiện phụ: dịch nhầm tên thương hiệu (đã sửa trong `models/ocr/prompts.py`)

Ở lượt đo gốc, `gemini-3.5-flash` và `gemini-2.5-flash` dịch nhầm "PARADOX"
(chữ in trên áo trong `request53.jpg`, biến thể "nguyên bản") thành "Nghịch
lý" — đọc chữ ĐÚNG nhưng dịch SAI Ý, vì `_NORMAL` prompt cũ không loại trừ
tên riêng/thương hiệu (khác `_SPECIALIZED` đã có luật này từ trước). Đã sửa
`_NORMAL` thêm đúng một câu "GIỮ NGUYÊN, KHÔNG dịch nghĩa tên thương
hiệu/tên riêng" — xác nhận lại bằng 1 lượt gọi Gemini thật riêng (không tính
vào ma trận 27 lượt): cùng ảnh, cùng model, kết quả đổi từ `"Nghịch lý"`
thành `"PARADOX"` sau khi sửa prompt.
"""


def write_report(results):
    stats = _latency_stats(results)
    rotation_lines = _rotation_answer(results)

    lines = []
    lines.append("# H4 -- Ma tran 3 model x 3 bien the OCR (do that, khong mock)")
    lines.append("")
    lines.append(f"Ngay do: **{MEASURED_DATE}**")
    lines.append("")
    lines.append(
        "Goi `models.vlm.client.generate_stream(..., model=...)` THAT (T15/H1 "
        "tham so `model` moi them) qua Gemini API that -- KHONG mock. So do o "
        "day la ket qua doc va do tre THAT, khong phai gia lap."
    )
    lines.append("")
    lines.append(
        "3 anh dung de do lay tu quet that toan bo `storage/`: 187/477 file la "
        "anh camera that hop le, phan con lai la fixture \"fake img\" cua test "
        "cu (khong phai anh). `request53.jpg` va `request323.jpg` la anh CAMERA "
        "THAT, khong phai anh dung tay -- `request323.jpg` la **ca hong THAT** "
        "(chay sang, sharp=2.9), dung lam ca fail bat buoc theo yeu cau H4."
    )
    lines.append("")
    lines.append("## Anh dung de do")
    lines.append("")
    lines.append("| Anh | Nguon | Ky vong | Ghi chu |")
    lines.append("|---|---|---|---|")
    for b in BASE_IMAGES:
        if b.expect_no_text:
            kv = "KHONG_CO_CHU (anh hong that, khong co chu doc duoc)"
        else:
            kv = f"doc ra chua mot trong: {', '.join(b.expect_keywords)}"
        lines.append(f"| `{b.name}` | `{b.path}` | {kv} | {b.note} |")
    lines.append("")

    lines.append("## Ma tran day du (27 luot goi that)")
    lines.append("")
    lines.append("| Model | Anh | Bien the | Ket qua | Dung ky vong? | Do tre (s) | Trich doan output that |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        ok = "DUNG" if r.matches_expected else "SAI"
        snippet = r.output_snippet.replace("|", "\\|")
        lines.append(
            f"| `{r.model}` | {r.image} | {r.variant} | {r.label} | {ok} | "
            f"{r.latency_s:.2f} | {snippet} |"
        )
    lines.append("")

    lines.append("## Do tre theo model (p50 / p95, N luot khong loi)")
    lines.append("")
    lines.append("| Model | p50 (s) | p95 (s) | N |")
    lines.append("|---|---|---|---|")
    for model in MODELS:
        if model in stats:
            p50, p95, n = stats[model]
            lines.append(f"| `{model}` | {p50:.2f} | {p95:.2f} | {n} |")
        else:
            lines.append(f"| `{model}` | (khong co luot nao khong loi) | | 0 |")
    lines.append("")

    lines.append("## Cau hoi mo #1 (T15 muc 6): model khong `-lite` co tu xoay lai anh 180 do khong?")
    lines.append("")
    lines.extend(rotation_lines)
    lines.append("")

    total = len(results)
    n_correct = sum(1 for r in results if r.matches_expected)
    khong_co_chu_count = sum(1 for r in results if r.label == "KHONG_CO_CHU")
    per_model_khong = {
        m: sum(1 for r in results if r.model == m and r.label == "KHONG_CO_CHU")
        for m in MODELS
    }
    lines.append("## H5 -- so KHONG_CO_CHU truoc/sau doi model (do tren cung 9 anh/model)")
    lines.append("")
    lines.append(
        "Day la so do duoc TRONG PHAM VI benchmark nay (khong phai counter "
        "production -- xem docs/tasks/reports/T15.md muc \"Lech voi task file\" "
        "ve ly do khong noi day duoc vao `models/ocr/__init__.py`)."
    )
    lines.append("")
    lines.append("| Model | So lan KHONG_CO_CHU / 9 luot |")
    lines.append("|---|---|")
    for m in MODELS:
        lines.append(f"| `{m}` | {per_model_khong[m]} |")
    lines.append("")
    lines.append(
        f"Tong: {n_correct}/{total} luot dung ky vong, {khong_co_chu_count}/{total} "
        "luot ra KHONG_CO_CHU (goc: xem bang day du o tren)."
    )
    lines.append("")

    # So "hong that" (dang le doc duoc ma lai ra KHONG_CO_CHU), loai bo anh
    # co y hong (request323_overexposed) -- day moi la con so 25.5 doi hoi.
    fail_images = {b.name for b in BASE_IMAGES if b.expect_no_text}
    real_text_rows = [r for r in results if r.image not in fail_images]
    false_negative = {
        m: sum(
            1 for r in real_text_rows if r.model == m and r.label == "KHONG_CO_CHU"
        )
        for m in MODELS
    }
    n_real_text_per_model = {
        m: sum(1 for r in real_text_rows if r.model == m) for m in MODELS
    }
    lines.append(
        "### So KHONG_CO_CHU SAI (tach rieng anh hong that ra khoi anh co chu that)"
    )
    lines.append("")
    lines.append(
        "Bang tren gop chung KHONG_CO_CHU dung (anh hong that, "
        f"`{', '.join(fail_images)}`) voi KHONG_CO_CHU sai (anh co chu that "
        "ma model bo sot). Tach rieng moi ra duoc so 25.5 doi hoi -- \"OCR "
        "hong bao nhieu %\":"
    )
    lines.append("")
    lines.append("| Model | KHONG_CO_CHU SAI / so luot co chu that |")
    lines.append("|---|---|")
    for m in MODELS:
        lines.append(f"| `{m}` | {false_negative[m]}/{n_real_text_per_model[m]} |")
    lines.append("")
    lines.append(_STATIC_ANALYSIS)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


if __name__ == "__main__":
    results = run()
    write_report(results)
    print(f"\nDa ghi {REPORT_PATH}")
