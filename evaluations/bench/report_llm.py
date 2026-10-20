"""Sinh reports/OCR.md, reports/MONEY.md, reports/VQA.md từ JSON MỚI NHẤT của gói L (không gọi lại LLM).

python -m bench.report_llm [--include-limit] [--out-dir DIR]
Mặc định bỏ qua các file chạy thử (tên chứa `_limit`); --include-limit để kiểm định dạng.
"""

import argparse
import csv
import glob
import json
import os
import re

from bench import common

# ----------------------------------------------------------------------------- baseline chép từ BÀI GỐC (đã mở bản PDF 2026-10-20)

BASE_VINTEXT = """| Phương pháp (bảng gốc) | Không từ điển (H-mean) | Có từ điển (H-mean) |
|---|---|---|
| Mask TextSpotter v3 (alphabet: Anh + ký tự dẫn xuất) | 53,4 | 57,4 |
| ABCNet (alphabet: Anh + ký tự dẫn xuất) | 50,6 | 55,1 |
| ABCNet (alphabet: Anh + ký hiệu dấu) | 54,2 | 58,5 |
| ABCNet+D (đề xuất, alphabet Anh + ký hiệu dấu) | 57,4 | 63,6 |
| Mask TextSpotter v3+D (alphabet Anh + ký hiệu dấu) | 68,5 | 70,3 |

Nguồn: Nguyen et al., *Dictionary-guided Scene Text Recognition*, CVPR 2021, **Bảng 5** (PDF trang 8, số trang in 7390), "Recognition accuracy (H-mean) on the VinText dataset".
Bản PDF: openaccess.thecvf.com/content/CVPR2021/papers/Nguyen_Dictionary-Guided_Scene_Text_Recognition_CVPR_2021_paper.pdf."""

BASE_SROIE = """| Hạng | Đội (bảng gốc) | Hmean Task 3 (%) |
|---|---|---|
| 1 | Ping An Property & Casualty Insurance Company | 90,49 |
| 2 | EAST det + Multi-class classification (Baidu) | 89,70 |
| 3 | H&H Lab (HUST_VLRGROUP / HUAWEI_CLOUD_EI) | 89,63 |
| 4 | CLOVA OCR | 89,05 |
| 5 | NiuBiHongHang | 87,61 |

Nguồn: Huang et al., *ICDAR2019 Competition on Scanned Receipt OCR and Information Extraction*, arXiv 2103.10213, **Hình 5** ("Top 10 methods for Task 3"), trang 5.
Ba cột số trong hình (Recall / Precision / Hmean; hàng thứ 6: 83,00 / 83,24 / 83,12) — bảng này chép cột cuối. Văn bản bài (trang 5) xác nhận chỉ một phương pháp vượt 90 % Hmean (90,49 %)."""

BASE_VITEXTVQA = """| Mô hình (bảng gốc) | F1 (%) | EM (%) |
|---|---|---|
| M4C base | 25,46 | 10,26 |
| BLIP-2 large | 38,47 | 15,58 |
| LaTr large | 42,34 | 20,94 |
| SaL base | 43,49 | 20,11 |
| PreSTU large (tốt nhất trong nhóm baseline) | 44,93 | 22,64 |
| ViTextBLIP-2 (đề xuất) | 53,95 | 25,48 |

Nguồn: arXiv 2404.10652, **Bảng 6** (trang 15) "Results of models on the ViTextVQA test set" (chép 6/10 hàng; đủ ở bài).

| 100 mẫu ngẫu nhiên của test (Bảng 7, trang 16) | F1 0-shot | EM 0-shot | Tốt nhất (số-shot) F1 / EM |
|---|---|---|---|
| GPT-4o | 55,51 | 25,00 | 76,67 (3-shot) / 56,00 (3-shot) |
| Gemini-1.5-flash | 57,75 | 26,00 | 64,40 (5-shot) / 39,00 (5-shot) |
| QwenVL-7b | 53,80 | 28,00 | 54,85 (3-shot) / 36,00 (1-, 3-shot) |
| Người | 96,42 | 88,00 | — |

Metric bài gốc (mục 5.4): EM = tỉ lệ dự đoán khớp hoàn toàn đáp án; F1 = trùng lặp token giữa dự đoán và đáp án. Bản arXiv đã tải 2026-10-20 (có thể khác bản hội nghị)."""

BASE_VIZWIZ = """| Phương pháp (bảng gốc, tập TEST VizWiz 2018) | Accuracy (VQA) | Unanswerable (độ chính xác, Bảng 4) |
|---|---|---|
| Q+I [18] dùng nguyên (huấn luyện trên VQA 2.0) | 0,137 | 0,070 |
| Q+I+BUA [6] dùng nguyên | 0,134 | 0,060 |
| FT [6] (tinh chỉnh trên VizWiz) | 0,475 | 0,776 |
| VizWiz [6] (huấn luyện chỉ trên VizWiz) | 0,469 | 0,805 |
| Con người | 0,75 | — |

Nguồn: Gurari et al., *VizWiz Grand Challenge: Answering Visual Questions from Blind People*, CVPR 2018 (arXiv 1802.08218): **Bảng 3** (trang 7, cột Acc), **Bảng 4** (trang 8, cột Unans); "human performance 0.75 accuracy" ở trang 7.
Dự đoán câu hỏi có trả lời được hay không (Bảng 6, PDF trang 14, tài liệu bổ sung): mô hình Q+I đạt Average Precision 0,717, Average F1 0,648; ảnh đơn (I) AP 0,640."""

LIMIT_NOTE = "**ĐÂY LÀ LẦN CHẠY THỬ (--limit), không dùng làm số liệu.**\n\n"


# ----------------------------------------------------------------------------- tiện ích


def latest(task: str, include_limit: bool, pattern: str = "*.json") -> str | None:
    files = sorted(glob.glob(os.path.join(common.RESULTS, task, pattern)))
    files = [f for f in files if re.match(r"\d{8}-\d{4}_", os.path.basename(f))]  # chỉ file kết quả có dấu thời gian
    if not include_limit:
        files = [f for f in files if "_limit" not in os.path.basename(f)]
    return files[-1] if files else None


def load(task: str, include_limit: bool, pattern: str = "*.json"):
    p = latest(task, include_limit, pattern)
    return (p, json.load(open(p, encoding="utf-8"))) if p else (None, None)


def pct(m: dict | None, nd: int = 1) -> str:
    if not m:
        return "—"
    v, (lo, hi) = m["value"], m["ci"]
    if v != v:
        return "n/a"
    return f"{100 * v:.{nd}f} % [{100 * lo:.{nd}f}; {100 * hi:.{nd}f}]"


def lat_lines(d: dict) -> str:
    out = []
    for k, name in (("ttft", "TTFT (mảnh đầu ra khỏi `spoken()`/`answer()`)"), ("total", "Tổng thời gian")):
        s = d["latency"].get(k, {})
        if s.get("n"):
            out.append(f"- **{name}**: p50 {s['p50_ms']:.0f} ms · p90 {s['p90_ms']:.0f} ms · p99 {s['p99_ms']:.0f} ms (n = {s['n']})")
        else:
            out.append(f"- **{name}**: không có mẫu")
    return "\n".join(out)


def head(d: dict, path: str) -> str:
    m = d["meta"]
    lim = m["config"].get("limit")
    s = (LIMIT_NOTE if lim else "") + (
        f"_Chạy {m['time']} trên {m['host']}; VH commit `{m['vh_commit']}`{' (có thay đổi chưa commit)' if m['vh_dirty'] else ''}; "
        f"file `{os.path.relpath(path, common.EVAL_DIR)}`; lỗi mạng sau thử lại: {d.get('n_errors', 0)} mẫu._\n\n")
    return s


def missing(title: str, task: str) -> str:
    return f"## {title}\n\n**Chưa chạy** — không có `results/{task}/*.json` (chạy `./run_llm.sh`).\n\n"


def table(rows: list[tuple[str, str]], header=("Metric", "Giá trị (95 % CI bootstrap theo mẫu)")) -> str:
    return "\n".join([f"| {header[0]} | {header[1]} |", "|---|---|", *[f"| {a} | {b} |" for a, b in rows]]) + "\n\n"


# ----------------------------------------------------------------------------- các mục


def sec_c2a(inc: bool) -> str:
    p, d = load("ocr_vintext", inc)
    if not d:
        return missing("C2a — OCR nguyên văn: VinText test", "ocr_vintext")
    m = d["metrics"]
    rows = [("**Tỉ lệ con số SAI được nói ra** (số đầu ra không có trong GT / tổng số trong đầu ra) — metric chính", pct(m.get("num_wrong_rate"))),
            ("  — bản khoan dung với GT tách hộp (số 'sai' mà vẫn là đoạn liền của dãy chữ số GT thì tha)", pct(m.get("num_wrong_rate_lenient"))),
            ("Ảnh có ít nhất 1 con số sai", pct(m.get("img_with_wrong_number"))),
            ("Tỉ lệ số bỏ sót (số GT không có trong đầu ra)", pct(m.get("num_missed_rate"))),
            ("BoW precision (trung bình theo ảnh)", pct(m.get("bow_precision"))),
            ("BoW recall", pct(m.get("bow_recall"))),
            ("BoW F1", pct(m.get("bow_f1"))),
            ("CER (từ chối tính = 100 %)", pct(m.get("cer"))),
            ("CER (chỉ ảnh không từ chối)", pct(m.get("cer_nonrefused"))),
            ("Tỉ lệ từ chối (`KHONG_CO_CHU` / 'không thấy chữ')", pct(m.get("refusal_rate")))]
    return (f"## C2a — OCR đọc nguyên văn: VinText test\n\n{head(d, p)}"
            "**Dữ liệu.** VinText (Nguyen et al., *Dictionary-guided Scene Text Recognition*, CVPR 2021): 300 ảnh test `im1201..im1500` (đủ tập), chữ cảnh Việt có dấu. "
            "Dữ liệu chỉ cho nghiên cứu/giáo dục, trích dẫn bài CVPR 2021.\n\n"
            "**Cách đo.** `lanes.ocr_live.spoken(jpeg, \"raw\", \"bench\")` (đường production: resize 1600 px q90, prompt `_RAW`, temperature 0, câu đầu cắt ≤ 8 từ). "
            f"{d['n_scored']}/{d['n_images']} ảnh được chấm. Số = chuỗi chữ số (nhóm phân nghìn gộp, bỏ dấu), so multiset với GT; "
            "BoW = multiset từ (NFC, chữ thường, bỏ dấu câu, giữ dấu tiếng Việt); CER trên GT sắp trên→dưới, trái→phải. Hộp `###` bị bỏ.\n\n"
            + table(rows) + lat_lines(d) + "\n\n"
            "### Baseline công bố\n\n" + BASE_VINTEXT + "\n\n"
            "### Giới hạn / không so trực tiếp được\n\n"
            "- **Không so được** với bảng trên: bài đo end-to-end (phát hiện + nhận dạng, H-mean theo hộp); SeeVia chỉ đọc cả ảnh ra một đoạn văn. Không có số baseline nào cho 'số bịa'.\n"
            "- GT chỉ có các hộp được gán nhãn (bỏ `###` không đọc được) → chữ thật mà LLM đọc thêm bị tính là sai: BoW precision và 'số sai' **bị thổi phồng** (thấp hơn thực tế khi người dùng muốn nghe hết). Recall và 'số bỏ sót' công bằng hơn.\n"
            "- GT tách số thành nhiều hộp ('0','2') còn LLM viết liền ('02') → số 'sai' giả; bản khoan dung ở trên gỡ phần này.\n"
            "- Đầu ra có thể bị cắt/đổi theo cách đọc của LLM (không theo đúng thứ tự hộp) nên CER chỉ là thước tương đối.\n\n")


def sec_c2b(inc: bool) -> str:
    p, d = load("ocr_sroie", inc)
    if not d:
        return missing("C2b — OCR hỏi số tiền / ngày: SROIE test", "ocr_sroie")
    m = d["metrics"]
    rows = []
    for k, name in (("total", "Tổng tiền"), ("date", "Ngày")):
        rows += [(f"**{name}: tỉ lệ NÓI SAI** (nêu giá trị khác GT) — metric chính", pct(m.get(f"{k}_wrong_rate"))),
                 (f"{name}: nói sai / số lần có trả lời", pct(m.get(f"{k}_wrong_given_answered"))),
                 (f"{name}: Exact match", pct(m.get(f"{k}_em"))),
                 (f"{name}: từ chối", pct(m.get(f"{k}_refusal_rate"))),
                 (f"{name}: không phân tích được (không số/ngày, không phải từ chối)", pct(m.get(f"{k}_unparsed_rate")))]
    return (f"## C2b — OCR hỏi số tiền / ngày: SROIE test\n\n{head(d, p)}"
            f"**Dữ liệu.** SROIE ICDAR 2019 (Huang et al., ICDAR 2019), bản đăng lại jsdnrs/ICDAR2019-SROIE trên HuggingFace, test {d['n_receipts']} hoá đơn "
            "(ảnh JPEG; hoá đơn Malaysia, tiếng Anh). Mỗi hoá đơn 2 câu hỏi tiếng Việt: \"Tổng số tiền phải trả trên hoá đơn này là bao nhiêu?\" / \"Hoá đơn này ghi ngày nào?\".\n\n"
            "**Cách đo.** VH **chưa có đường production riêng cho 'hỏi về chữ'** (chế độ chỉ có trong `docs/ARCHITECTURE_OCR.md`; `final_router` gọi `ocr_live.spoken(.., mode)` không truyền câu hỏi). "
            "Bàn đo dùng `prompts._COMMON` + câu hỏi qua đúng `ocr_live.read_image` (resize 1600 px q90, temperature 0, max_tokens 1024, xử lý sentinel) rồi `short_first_sentence`. "
            "Total = **số đầu tiên** trong câu trả lời, so ±0,005 với GT; date = ngày đầu tiên đọc được (dd/mm/yy(yy), dd MON yy, 'ngày D tháng M năm Y'…), so (ngày, tháng, năm), mơ hồ ngày/tháng đọc theo d/m/y. "
            "Mỗi câu: đúng / **nói sai** / từ chối ('không đọc chắc', 'chụp lại', sentinel) / không phân tích được.\n\n"
            + table(rows) + lat_lines(d) + "\n\n"
            "### Baseline công bố\n\n" + BASE_SROIE + "\n\n"
            "### Giới hạn / không so trực tiếp được\n\n"
            "- **Không so trực tiếp**: bảng gốc là F1 trích 4 trường (company, date, address, total) của hệ chuyên dụng trên văn bản đã OCR; ở đây là câu hỏi tự nhiên bằng tiếng Việt về 2 trường, chấm đúng/sai tuyệt đối. Bài không công bố riêng total/date.\n"
            "- Quy tắc 'số đầu tiên' có thể chấm sai khi câu trả lời nêu số khác trước tổng; đã ghi `output` đầy đủ ở `per_sample` để chấm lại không cần gọi LLM.\n"
            "- Ảnh SROIE nhỏ hơn ảnh kính (UXGA 1600×1200) và là hoá đơn Malaysia (RM) — không đại diện hoá đơn Việt.\n\n")


def sec_c2c(inc: bool) -> str:
    p, d = load("ocr_vitextvqa", inc)
    if not d:
        return missing("C2c — OCR hỏi đáp tiếng Việt: ViTextVQA test", "ocr_vitextvqa")
    m = d["metrics"]
    rows = [("**EM** (khớp hoàn toàn sau chuẩn hoá, max qua đáp án) — metric bài gốc", pct(m.get("em"))),
            ("**F1 token** (max qua đáp án) — metric bài gốc", pct(m.get("f1"))),
            ("Đáp án nằm trong câu trả lời (không phạt văn nói)", pct(m.get("answer_contained"))),
            ("Bịa số khi GT có số (nêu số không có trong đáp án)", pct(m.get("fabricated_number_when_gt_has_number"))),
            ("Tỉ lệ từ chối", pct(m.get("refusal_rate")))]
    return (f"## C2c — OCR hỏi đáp tiếng Việt: ViTextVQA test\n\n{head(d, p)}"
            f"**Dữ liệu.** ViTextVQA (arXiv 2404.10652), bản đăng lại xuandin/ViTextVQA trên HuggingFace; mẫu {d['n_questions']} câu hỏi `sample(seed=0)` "
            "(nhóm theo (ảnh, câu hỏi): nhiều dòng annotation cùng câu = nhiều đáp án chấp nhận, lấy max).\n\n"
            "**Cách đo.** Như C2b (`ask_prompt` + `ocr_live.spoken`; VH chưa có đường 'hỏi về chữ' riêng). Chuẩn hoá: NFC, chữ thường, dấu câu→khoảng trắng; "
            "chữ số nối qua `.`/`,` (nhãn gốc đã tách token kiểu '0938 . 938 . 616') ở cả hai phía. "
            "Bịa số = GT có chuỗi số, câu trả lời không từ chối và nêu một chuỗi số không có trong GT.\n\n"
            + table(rows) + lat_lines(d) + "\n\n"
            "### Baseline công bố\n\n" + BASE_VITEXTVQA + "\n\n"
            "### Giới hạn / không so trực tiếp được\n\n"
            "- Metric giống bài gốc nhưng **tập mẫu khác** (300 câu, không phải 100 mẫu của Bảng 7, không phải cả test) và tiền xử lý đáp án nhóm theo câu hỏi → so *tham khảo*, không so trực tiếp. SeeVia chạy zero-shot, văn nói tiếng Việt dài hơn đáp án ngắn nên EM/F1 bị phạt; dùng 'đáp án nằm trong câu trả lời' để đọc đúng năng lực.\n"
            "- Các mô hình ở Bảng 6 được huấn luyện trên ViTextVQA; SeeVia thì không.\n"
            "- Dữ liệu HF đăng lại, licence không ghi trên thẻ; chỉ dùng đánh giá.\n\n")


def build_ocr(inc: bool) -> str:
    return ("# Báo cáo OCR — đọc chữ bằng LLM (Gemma 4 26B)\n\n"
            "Sinh tự động bởi `bench/report_llm.py` từ JSON mới nhất trong `results/`. Số liệu = METRICS.md C2a/C2b/C2c.\n\n"
            + sec_c2a(inc) + sec_c2b(inc) + sec_c2c(inc))


# ---------------------------------------------------------------------------- MONEY


def sec_money_one(label: str, task_pattern: str, inc: bool) -> str:
    p, d = load("money_vnd", inc, task_pattern)
    if not d:
        return f"### {label}\n\n**Chưa chạy.**\n\n"
    m = d["metrics"]
    rows = [("**Tỉ lệ ĐỌC SAI mệnh giá** (nêu mệnh giá khác GT) — metric chính", pct(m.get("read_wrong_rate"))),
            ("**Tỉ lệ bịa tiền** (ảnh KHÔNG có tiền mà nêu mệnh giá)", pct(m.get("fabricate_rate"))),
            ("Accuracy (đúng mệnh giá, ảnh có tiền)", pct(m.get("accuracy"))),
            ("Sai / số lần có trả lời", pct(m.get("wrong_given_answered"))),
            ("Từ chối / 'chụp lại' (ảnh có tiền)", pct(m.get("refusal_rate"))),
            ("Không phân tích được mệnh giá", pct(m.get("unparsed_rate"))),
            ("Nêu nhiều mệnh giá khác nhau", pct(m.get("multi_value_rate"))),
            ("Cổng chất lượng ảnh `reject_reason('money')` sẽ chặn", pct(m.get("gate_reject_rate_money")))]
    per = d.get("per_denomination", {})
    dn = "| Mệnh giá | Accuracy | Nói sai |\n|---|---|---|\n" + "\n".join(
        f"| {int(k):,} | {pct(v['accuracy'])} | {pct(v['wrong'])} |".replace(",", ".") for k, v in per.items()) + "\n\n"
    conf = d.get("confusion", {})
    cols = sorted({c for r in conf.values() for c in r}, key=lambda c: (not c.isdigit(), int(c) if c.isdigit() else 0, c))
    cm = ("| GT \\ nói | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols) + "\n" +
          "\n".join(f"| {('không tiền' if k == '0' else k)} | " + " | ".join(str(r.get(c, 0)) for c in cols) + " |" for k, r in conf.items()) + "\n\n")
    return (f"### {label}\n\n{head(d, p)}{d['n_images']} ảnh. " + "\n\n" + table(rows) + lat_lines(d) +
            "\n\n**Accuracy từng mệnh giá**\n\n" + dn + "**Ma trận nhầm** (hàng = GT, cột = mệnh giá đầu tiên được nêu; `none` = không nêu mệnh giá; `multi` = nêu ≥ 2 mệnh giá khác nhau)\n\n" + cm)


def build_money(inc: bool) -> str:
    return ("# Báo cáo đọc tiền VND (C3)\n\n"
            "**Dữ liệu cộng đồng (Kaggle), không có bài báo/baseline — chỉ chứng minh SeeVia đọc được tiền VND, không chứng minh hiệu quả.**\n\n"
            "Sinh tự động bởi `bench/report_llm.py`.\n\n"
            "**Dữ liệu.** `nguyentrongdai/vietnamese-currency` (Kaggle, licence 'Unknown'): ảnh PNG 192×144 webcam, 11 mệnh giá (200 đ … 500.000 đ) + thư mục `000000` không có tiền. "
            "Mẫu 30 ảnh/thư mục (360), **trải đều theo chỉ số khung** (sắp theo số trong tên file), không ngẫu nhiên. PNG → JPEG q90 trước khi gửi.\n\n"
            "**Cách đo.** Câu hỏi \"Đây là tờ tiền bao nhiêu?\". Mệnh giá trích từ câu trả lời (chữ số + nghìn/ngàn/triệu/đồng, số có dấu chấm phân nghìn, hoặc chữ 'năm mươi nghìn'…); "
            "chỉ nhận 11 mệnh giá hợp lệ. Đúng = chỉ nêu đúng mệnh giá GT; sai = nêu mệnh giá khác (hoặc nhiều mệnh giá khác nhau); từ chối = không nêu giá và nói không thấy/chụp lại. Ảnh không tiền: nêu bất kỳ mệnh giá = bịa.\n\n"
            + sec_money_one("Đường `general.answer(\"money\", …)` (theo PLAN/METRICS)", "*general*.json", inc)
            + sec_money_one("Đường `ocr_live.spoken(jpeg, \"money\")` (đường thật của làn B trong `pipeline/final_router.py`)", "*ocr_spoken*.json", inc)
            + "### Baseline công bố\n\n**Không có** — không tồn tại bộ tiền VND công khai có bài báo + baseline (đã tra 2026-10-20; BankNote-Net của Microsoft không có VND và chỉ công bố embedding). Không đối chiếu.\n\n"
            "### Giới hạn / không so trực tiếp được\n\n"
            "- Một người, một phông nền, webcam 192×144 (thấp hơn ảnh kính 1600 px); khung video gần trùng nhau → **CI bootstrap theo ảnh lạc quan**, số này **không tổng quát** ra ngoài đời.\n"
            "- Licence Kaggle không rõ; chỉ dùng đánh giá nội bộ.\n"
            "- Ảnh nhỏ hơn mọi ảnh thật của kính nên cổng chất lượng ảnh (`gate_reject_rate_money`) có thể chặn khác ngoài đời.\n")


# ---------------------------------------------------------------------------- VQA


def handcheck_agreement() -> str:
    path = os.path.join(common.RESULTS, "vqa_vizwiz", "handcheck_50.csv")
    if not os.path.exists(path):
        return "_Chưa có `handcheck_50.csv`._\n\n"
    rows = list(csv.DictReader(open(path, encoding="utf-8", newline="")))
    done = [r for r in rows if r.get("human_refused", "").strip() in ("0", "1") and r.get("human_n_match", "").strip().isdigit()]
    if not done:
        return (f"Kiểm tay: file `results/vqa_vizwiz/handcheck_50.csv` ({len(rows)} mẫu) **chưa có người chấm** — "
                "điền cột `human_refused` (0/1) và `human_n_match` (số đáp án EN trong 10 mà câu trả lời khớp nghĩa), rồi chạy lại báo cáo.\n\n")
    n = len(done)
    agree_ref = sum(1 for r in done if r["human_refused"].strip() == str(int(r["llm_refused"] == "True")))
    h_acc = [min(int(r["human_n_match"]) / 3, 1) for r in done]
    l_acc = [float(r["llm_vqa_acc"]) if r["llm_vqa_acc"] not in ("", "None") else 0.0 for r in done]
    same = sum(1 for a, b in zip(h_acc, l_acc) if abs(a - b) < 1e-9)
    mad = sum(abs(a - b) for a, b in zip(h_acc, l_acc)) / n
    return (f"Kiểm tay (n = {n}/{len(rows)}): đồng thuận 'từ chối' LLM-chấm vs người **{agree_ref}/{n} = {100 * agree_ref / n:.0f} %**; "
            f"VQA acc trùng khít {same}/{n} = {100 * same / n:.0f} %, lệch tuyệt đối trung bình {mad:.3f} (người TB {sum(h_acc) / n:.3f} vs LLM TB {sum(l_acc) / n:.3f}).\n\n")


def build_vqa(inc: bool) -> str:
    p, d = load("vqa_vizwiz", inc)
    if not d:
        return "# Báo cáo hỏi đáp theo ảnh — VizWiz-VQA\n\n" + missing("C4", "vqa_vizwiz")
    m = d["metrics"]
    # Tách "không từ chối" trên câu unanswerable: nhãn unanswerable là ĐA SỐ 10 người, thiểu số vẫn có đáp án thật
    # -> trả lời khớp đáp án thiểu số không phải bịa. Tính lại từ per_sample, không gọi LLM.
    una = [x for x in d.get("per_sample", []) if x.get("answerable") == 0 and not x.get("error")]

    def share(f):
        if not una:
            return None
        v, lo, hi = common.bootstrap_ci([1.0 if f(x) else 0.0 for x in una])
        return {"value": v, "ci": [lo, hi]}

    rows = [("**Không từ chối trên câu unanswerable** (trước đây gọi là 'bịa') — metric chính", pct(m.get("fabricate_rate_unanswerable"))),
            ("  — trong đó trả lời KHỚP đáp án của thiểu số người gán (không phải bịa)", pct(share(lambda x: not x["refused"] and x.get("llm_matches")))),
            ("  — trong đó **không khớp người nào** (cận trên của bịa thật; gồm cả câu né kiểu 'hỏi riêng' — cần chấm tay)", pct(share(lambda x: not x["refused"] and not x.get("llm_matches")))),
            ("  — nếu tính cả cổng chất lượng ảnh của production (`reject_reason('space')` chặn = từ chối)", pct(m.get("fabricate_rate_unanswerable_with_gate"))),
            ("**VQA accuracy** toàn mẫu (LLM chấm khớp nghĩa × min(#trùng/3, 1))", pct(m.get("vqa_acc_all"))),
            ("VQA accuracy — câu trả lời được (answerable = 1)", pct(m.get("vqa_acc_answerable"))),
            ("VQA accuracy — câu unanswerable (từ chối khớp 'unanswerable' của người)", pct(m.get("vqa_acc_unanswerable"))),
            ("Tỉ lệ từ chối toàn mẫu", pct(m.get("refusal_rate"))),
            ("Từ chối khi câu trả lời được (từ chối oan)", pct(m.get("refusal_rate_answerable"))),
            ("Precision 'từ chối đúng' (từ chối ∧ unanswerable / từ chối)", pct(m.get("refusal_precision"))),
            ("Recall 'từ chối đúng' (từ chối / unanswerable)", pct(m.get("refusal_recall"))),
            ("Cổng chất lượng ảnh sẽ chặn", pct(m.get("gate_reject_rate")))]
    return ("# Báo cáo hỏi đáp theo ảnh — VizWiz-VQA (C4)\n\nSinh tự động bởi `bench/report_llm.py`.\n\n"
            f"## C4 — VizWiz-VQA val\n\n{head(d, p)}"
            f"**Dữ liệu.** VizWiz-VQA (Gurari et al., CVPR 2018) tập **val** 4.319 câu (ảnh do người khiếm thị chụp); mẫu {d['n_questions']} câu `sample(seed=0)`: "
            f"{d['n_answerable']} answerable, {d['n_unanswerable']} unanswerable. CC BY 4.0 theo vizwiz.org.\n\n"
            "**Cách đo.** Câu hỏi EN dịch sang tiếng Việt một lần bằng LLM (`results/vqa_vizwiz/questions_vi.json`, người xem lại được). "
            "Trả lời bằng đường production `lanes.general.answer(\"space\", câu_vi, ảnh 896 px)` — lưu ý intent `space` dùng prompt mô tả không gian, câu hỏi chỉ nằm ở dòng 'Người dùng nói'. "
            "Chấm: LLM (temperature 0, JSON schema, có ví dụ) nhận câu hỏi + câu trả lời VN + 10 đáp án EN → `{refused, matches}`; "
            "VQA acc = min(#người trùng/3, 1) (đáp án 'unanswerable' tính trùng khi trợ lý từ chối, xác định bằng mã). Bàn đo KHÔNG chạy cổng chất lượng trước LLM (đo LLM thuần); dòng 'có cổng' tính thêm.\n\n"
            + table(rows) + lat_lines(d) + "\n\n" + handcheck_agreement() +
            "### Baseline công bố\n\n" + BASE_VIZWIZ + "\n\n"
            "### Giới hạn / không so trực tiếp được\n\n"
            "- **Không so ngang** với bảng gốc: khác protocol (val vs test; trợ lý zero-shot trả lời văn nói tiếng Việt, câu hỏi dịch qua LLM, LLM chấm khớp nghĩa; bài gốc phân loại đáp án đóng/gần-chính-xác). Công thức acc ở đây là min(n/3, 1) đơn giản, **không phải** leave-one-out chính thức. Chỉ để tham chiếu cỡ số.\n"
            "- LLM chấm cùng họ với LLM được chấm (Gemma): có thể lệch; độ đồng thuận với người ở mục kiểm tay (cần điền `handcheck_50.csv`).\n"
            "- Dịch EN→VN có thể làm lệch câu hỏi; câu hỏi `Summary`/'tóm tắt' vốn khó.\n"
            "- Intent `space` không phải intent sản phẩm sẽ chọn cho mọi câu hỏi; kết quả là cho đường 'hỏi chung theo ảnh' mà PLAN quy định.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-limit", action="store_true", help="cho phép dùng file chạy thử (--limit)")
    ap.add_argument("--out-dir", default=common.REPORTS)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    for name, text in (("OCR.md", build_ocr(a.include_limit)), ("MONEY.md", build_money(a.include_limit)),
                       ("VQA.md", build_vqa(a.include_limit))):
        path = os.path.join(a.out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        print(path, len(text))


if __name__ == "__main__":
    main()
