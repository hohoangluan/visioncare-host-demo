"""Sinh reports/QUALITY.md (C5) và reports/STT.md (C6) từ JSON mới nhất trong results/.

    python -m bench.report_quick

Ưu tiên file `*_full.json`; nếu chỉ có bản `--limit` thì vẫn sinh nhưng ghi BANNER "BẢN THỬ".
Số baseline công bố chép từ bài gốc (đã mở PDF arXiv và đối chiếu bảng/trang) — không phải đoán.
"""
import glob
import json
import os

from bench import common


def latest(task: str, prefer: str = "_full.json", exclude: str = "_greedy") -> tuple[str | None, bool]:
    files = sorted(f for f in glob.glob(os.path.join(common.RESULTS, task, "*.json")) if exclude not in os.path.basename(f))
    full = [f for f in files if f.endswith(prefer)]
    if full:
        return full[-1], True
    return (files[-1], False) if files else (None, False)


def pct(d: dict, nd: int = 2) -> str:
    v, (lo, hi) = d["value"], d["ci"]
    if v != v:
        return "n/a"
    return f"{v * 100:.{nd}f} % [{lo * 100:.{nd}f}; {hi * 100:.{nd}f}]"


def banner(path: str, is_full: bool, meta: dict) -> str:
    rel = os.path.relpath(path, common.EVAL_DIR)
    s = f"Nguồn: `{rel}` (chạy {meta['time']}, VH `{meta['vh_commit']}`{' + sửa chưa commit' if meta['vh_dirty'] else ''}, host {meta['host']}).\n"
    if not is_full:
        s = ("> **BẢN THỬ (`--limit`), KHÔNG dùng làm số liệu.** Chưa có file `*_full.json`; số dưới đây chỉ để kiểm đường ống.\n\n") + s
    return s


def quality() -> str | None:
    path, full = latest("quality_vizwiz")
    if not path:
        return None
    d = json.load(open(path, encoding="utf-8"))
    m, meta, cfg = d["metrics"], d["meta"], d["meta"]["config"]
    L = ["# C5 — Cổng chất lượng ảnh (VizWiz-QualityIssues val)\n", banner(path, full, meta)]
    L.append(f"""## Dữ liệu và cách chấm

- Tập: VizWiz-QualityIssues **val** (Chiu, Zhao, Gurari, *Assessing Image Quality Issues for Real-World Problems*, CVPR 2020, arXiv 2003.12511), ảnh do người khiếm thị chụp. Dùng {cfg['n_images']} ảnh (val đủ = 7.750); {cfg['n_measure_none']} ảnh `measure()` trả None.
- Nhãn dương = >= {cfg['pos_min']}/5 người gán lỗi đó (DRK, BRT, BLR) hoặc `unrecognizable`.
- Đường chạy: `pipeline.image_quality.measure()` + `check()` của VH, ngưỡng hiện tại `IMAGE_MIN_BRIGHTNESS={cfg['min_brightness']}`, `IMAGE_MAX_BRIGHTNESS={cfg['max_brightness']}`, `IMAGE_MIN_SHARPNESS={cfg['min_sharpness']}`. Thiết bị: {cfg['device']}.
- Ánh xạ: TỐI <-> DRK, CHÓI <-> BRT, MỜ <-> BLR. Intent không-money: `need_sharpness=False` (chỉ luật sáng/tối); money: thêm luật nét.
- Mọi số kèm [CI 95 %] bootstrap 1.000 lần theo ảnh.
""")
    w = m["wrong_retake"]
    L.append("## Metric chính — chụp lại OAN\n\nOAN = ảnh bị từ chối vì lỗi R mà đa số (>= 3/5) người gán nói KHÔNG có lỗi R.\n")
    L.append("| Intent | Tỉ lệ bị từ chối | **Chụp lại oan (trên mọi ảnh)** | Oan / số bị từ chối | Từ chối nhưng ảnh không `unrecognizable` |\n|---|---|---|---|---|")
    for k, name in (("nomoney", "không-money (sáng/tối)"), ("money", "money (+ độ nét)")):
        x = w[k]
        sh = x["wrong_share_of_rejections"]
        L.append(f"| {name} | {pct(x['reject_rate'])} | **{pct(x['wrong_rate_over_all_images'])}** ({x['wrong_rate_over_all_images']['k']}/{x['wrong_rate_over_all_images']['n']}) | "
                 f"{'n/a' if sh is None else f'{sh*100:.1f} %'} | {pct(x['reject_but_not_unrecognizable_rate'])} |")
    L.append("\nPhân theo lý do (số ảnh bị từ chối / số oan): " + "; ".join(
        f"{k}: " + ", ".join(f"{f} {x['by_reason'][f]}/{x['wrong_by_reason'][f]}" for f in ("DRK", "BRT", "BLR")) for k, x in w.items()) + ".\n")

    L.append("## Precision / recall / F1 ở ngưỡng hiện tại\n")
    L.append("| Lỗi (luật) | n dương | n bị bắt | Precision | Recall | F1 |\n|---|---|---|---|---|---|")
    names = {"DRK": "TỐI (DRK)", "BRT": "CHÓI (BRT)", "BLR": "MỜ (BLR) — chỉ money"}
    for f, x in m["prf_current_threshold"].items():
        L.append(f"| {names[f]} | {x['n_pos']} | {x['n_pred_pos']} | {pct(x['precision'])} | {pct(x['recall'])} | {pct(x['f1'])} |")
    L.append("\nGhi chú: MỜ ở bảng trên tính luật nét như thể áp cho mọi ảnh (chỉ intent money dùng thật).\n")

    L.append("## AUROC của điểm sáng / nét (không phụ thuộc ngưỡng)\n")
    L.append("| Điểm -> nhãn | AUROC | n dương |\n|---|---|---|")
    for k, x in m["auroc"].items():
        L.append(f"| {k} | {x['value']:.3f} [{x['ci'][0]:.3f}; {x['ci'][1]:.3f}] | {x['n_pos']} |")
    L.append("\nRecall ảnh `unrecognizable` (vô dụng thật) mà cổng bắt: " + "; ".join(
        f"{k} {pct(x)} (n dương {x['n_pos']})" for k, x in m["unrecognizable_recall"].items()) + ".\n")

    L.append("## Ngưỡng tối ưu F1: chọn trên nửa A (seed 0), báo trên nửa B\n")
    L.append("| Lỗi | Ngưỡng hiện tại | Ngưỡng chọn trên A | F1 trên B (hiện tại) | F1 trên B (chọn từ A) | Recall B (hiện tại -> chọn) |\n|---|---|---|---|---|---|")
    for f, x in m["tuned_halfAB"].items():
        L.append(f"| {f} | {x['threshold_current']:.1f} | {x['threshold_tuned_on_A']:.1f} | {pct(x['on_B_current']['f1'])} | {pct(x['on_B_tuned']['f1'])} | "
                 f"{pct(x['on_B_current']['recall'], 1)} -> {pct(x['on_B_tuned']['recall'], 1)} |")
    L.append("\nĐọc: CI hai cột F1 không chồng nhau mới đáng tin là ngưỡng khác tốt hơn. Cổng cố ý chỉ chặn outlier cực đoan (docstring `image_quality.py`) nên F1 thấp ở ngưỡng hiện tại là THIẾT KẾ, không phải lỗi; metric an toàn là oan.\n")

    lt = d["latency"]
    s = lt["measure"]
    L.append(f"""## Độ trễ

`measure()` mỗi ảnh (CPU, ảnh gốc, n={s['n']}): **p50 {s['p50_ms']} ms / p90 {s['p90_ms']} ms / p99 {s['p99_ms']} ms** (mean {s['mean_ms']}, max {s['max_ms']}).
Kích thước ảnh VizWiz trung vị {lt['image_size_median_wh'][0]}x{lt['image_size_median_wh'][1]} (ảnh kính là 1600x1200, 1,92 MP) và {lt['image_bytes_median']/1024:.0f} KB — {lt['note']}. Tải CPU lúc chạy (loadavg) không kiểm soát được, p99 dễ nhiễu.
""")
    L.append("""## Baseline công bố (chép từ bài gốc, đã mở PDF arXiv 2003.12511v2)

Chiu et al., CVPR 2020. **Phân loại lỗi — Table 4 (Supplementary, mục 8, PDF trang 12)**, mô hình Xception huấn luyện có giám sát:

| Phương pháp | Chỉ số | BLR | BRT | DRK |
|---|---|---|---|---|
| Xception | precision | 80.1 | 62.9 | 58.5 |
| Xception | recall | 80.1 | 49.8 | 57.3 |
| Xception | F1 | 80.1 | 55.6 | 57.9 |
| Random guessing | F1 | 40.4 | 4.5 | 7.0 |

**Unrecognizable — Table 1 (mục 4.2, PDF trang 6):** ResNet-152 AP 80.0 / recall 75.1 / F1 71.2; SIFT 87.2 / 42.3 / 56.9; HOG+SVM 56.4 / 41.2 / 47.6; random 16.6 / 14.6 / 15.5.
Chia tập trong bài: 52,5 % / 37,5 % / 10 % trên 39.181 ảnh (train/val/test).

## Giới hạn / không so trực tiếp được

- Baseline là **CNN học có giám sát** trên train của chính bộ này; cổng SeeVia là 2 phép đo thủ công (Laplacian, độ sáng trung bình) đặt ngưỡng **cực đoan có chủ ý**. F1 của ta thấp hơn là điều mong đợi; so sánh có ý nghĩa là AUROC (ngưỡng-độc-lập) và tỉ lệ oan, chứ không phải F1.
- Ta chấm trên **val công khai** (7.750), bài chấm trên phần test riêng (10 % của 39.181, không công bố nhãn) → khác tập; cách chuyển nhãn cũng khác (bài dùng đa số của 5 người cho nhãn nhị phân, ta cũng vậy nhưng ngưỡng >= 3 là quy ước của ta).
- BLR của VizWiz đo "mờ" cảm nhận bởi người; nhãn không phụ thuộc loại máy. Ảnh VizWiz do điện thoại chụp, khác camera kính (1600x1200, đặc trưng sharpness thấp hệ thống — docstring module).
- Độ trễ đo ở độ phân giải VizWiz, không phải ảnh kính; ngưỡng sharpness 5 được đặt cho ảnh kính nên có thể không tương thích phân bố VizWiz (xem AUROC).
- Không đánh giá được cổng ở intent `hazard`/`find` riêng; cả ba intent không-money dùng chung luật sáng/tối.
""")
    return "\n".join(L)


def stt() -> str | None:
    path, full = latest("stt_vivos")
    if not path:
        return None
    d = json.load(open(path, encoding="utf-8"))
    m, meta, cfg, lt = d["metrics"], d["meta"], d["meta"]["config"], d["latency"]
    gl = sorted(glob.glob(os.path.join(common.RESULTS, "stt_vivos", "*greedy_search.json")))
    g_full = [f for f in gl if f.endswith("_full_greedy_search.json")]
    g_path, g_full = (g_full[-1], True) if g_full else ((gl[-1], False) if gl else (None, False))
    L = ["# C6 — STT Zipformer-vi 30M (VIVOS test)\n", banner(path, full, meta)]
    pu = lt["per_utt"]
    L.append(f"""## Dữ liệu và cách chấm

- Tập: VIVOS test (Luong & Vu, 2016; AILAB VNU-HCM), {cfg['n_utts']}/{cfg['n_utts_all']} câu, {cfg['n_speakers']} người nói, tổng {cfg['audio_total_s']/60:.1f} phút audio.
- Đường chạy: `pipeline.stt.transcribe(wav_bytes)` của VH (cả giải WAV + `_normalize` như production). **{cfg['device']}**, {cfg['num_threads']} luồng, giải mã `{cfg['decoding']}` (beam {cfg['beam_paths']} đường, hotword lệnh {'bật' if cfg['hotwords'] else 'tắt'} điểm {cfg['hotwords_score']}; hotword tên người thân: {cfg['user_hotwords'] or 'không đặt'}).
- Chuẩn hoá chấm: `tools.bench_stt_compare.normalize` của VH (NFC, chữ thường, bỏ dấu câu). WER/CER gộp toàn tập (tổng lỗi / tổng từ), CI 95 % bootstrap 1.000 lần theo câu. Thư viện `jiwer`.
- Tải CPU máy lúc đầu {cfg['loadavg_start'][0]:.1f} / cuối {lt['loadavg_end'][0]:.1f} (máy dùng chung — trễ có thể nhiễu).
""")
    L.append("## Kết quả\n")
    L.append("| Chỉ số | Giá trị [CI 95 %] |\n|---|---|")
    L.append(f"| **WER** | **{pct(m['wer'])}** |\n| CER | {pct(m['cer'])} |")
    w, b = m["worst_speaker"], m["best_speaker"]
    L.append(f"| WER người nói **tệ nhất** ({w['id']}, {w['n_utts']} câu) | {pct(w, 1)} |\n| WER người nói tốt nhất ({b['id']}, {b['n_utts']} câu) | {pct(b, 1)} |")
    L.append(f"| Số câu hypothesis rỗng | {m['empty_hyp']} |")
    if g_path and g_path != path:
        gd = json.load(open(g_path, encoding="utf-8"))
        L.append(f"| (tham chiếu) WER giải mã `greedy_search`, cùng tập | {pct(gd['metrics']['wer'])}{'' if g_full else ' — bản thử'} |")
    L.append("")
    L.append("Người nói theo WER giảm dần (mỗi người ~40 câu → CI rộng, đừng đọc chênh vài điểm):\n")
    L.append("| Người nói | Số câu | WER [CI] |\n|---|---|---|")
    for k, x in sorted(m["per_speaker_wer"].items(), key=lambda kv: -kv[1]["value"]):
        L.append(f"| {k} | {x['n_utts']} | {pct(x, 1)} |")
    L.append(f"""
## Độ trễ

Mỗi câu (`transcribe`, CPU, n={pu['n']}): **p50 {pu['p50_ms']} ms / p90 {pu['p90_ms']} ms / p99 {pu['p99_ms']} ms** (mean {pu['mean_ms']}, max {pu['max_ms']}).
RTF: median {lt['rtf_median']:.3f}, p90 {lt['rtf_p90']:.3f}, gộp (tổng thời gian / tổng audio) {lt['rtf_total']:.3f}.
Lưu ý: câu VIVOS dài hơn câu lệnh kính (VIVOS trung bình {cfg['audio_total_s']/max(cfg['n_utts'],1):.1f} s/câu; config.py đo lệnh ~1-2 s) nên trễ tuyệt đối cao hơn trễ thật; dùng RTF để so.
""")
    L.append("""## Baseline công bố (chép từ bài gốc, đã mở PDF arXiv 2406.02555)

Le, Nguyen & Nguyen (VinAI), *PhoWhisper: Automatic Speech Recognition for Vietnamese*, ICLR 2024 Tiny Papers — **Table 2 (trang 2), WER %**, cột VIVOS:

| Mô hình | #tham số | WER VIVOS |
|---|---|---|
| wav2vec2-base-vietnamese-250h | 95M | 10.83 |
| wav2vec2-base-vi-vlsp2020 | 95M | 9.90 |
| wav2vec2-large-vi-vlsp2020 | 317M | 8.61 |
| PhoWhisper-tiny | 39M | 10.41 |
| PhoWhisper-base | 74M | 8.46 |
| PhoWhisper-small | 244M | 6.33 |
| PhoWhisper-medium | 769M | 4.97 |
| PhoWhisper-large | 1.55B | 4.67 |

Vietnamese Open ASR Leaderboard: **chưa đối chiếu** (chưa mở được bảng gốc có Zipformer trong đợt này).

## Giới hạn / không so trực tiếp được

- **Bài PhoWhisper nhét VIVOS train (13,94 h) vào dữ liệu huấn luyện**; Zipformer-vi 30M của VH lấy từ `hynt/Zipformer-30M-RNNT-6000h` (Hugging Face, theo `models/stt/README.md`; tên nêu 6000 h huấn luyện) — **chưa kiểm** tập huấn luyện đó có chứa VIVOS hay không, nên không biết số có bị thổi phồng không.
- Bài báo không nêu quy tắc chuẩn hoá WER chi tiết (hoa/thường, dấu câu); ta chuẩn hoá thường + bỏ dấu câu, VIVOS vốn không dấu câu. Chênh nhỏ có thể do cách chuẩn hoá.
- Zipformer 30M là mô hình nhỏ chạy CPU 2 luồng cho **câu lệnh ngắn**; so với PhoWhisper-large 1,55B là so khác hạng cân. Mục đích là đặt SeeVia cạnh mốc công bố, không phải để thắng.
- Production giải mã beam + hotword **lệnh kính** (MẸ, GỌI CHO…) có thể làm WER đọc văn xuôi VIVOS lệch nhẹ so với greedy; dòng "tham chiếu greedy" (nếu có) cho biết lệch bao nhiêu.
- WER theo người nói: mỗi người ~40 câu nên CI rộng; "người tệ nhất" là cực trị của 19 giá trị nhiễu (winner's curse) — dùng để chỉ hướng, không kết luận.
""")
    return "\n".join(L)


def main() -> None:
    os.makedirs(common.REPORTS, exist_ok=True)
    for name, fn in (("QUALITY.md", quality), ("STT.md", stt)):
        text = fn()
        if text is None:
            print("bỏ qua", name, "(chưa có JSON)")
            continue
        p = os.path.join(common.REPORTS, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        print("ghi", p, len(text), "ký tự")


if __name__ == "__main__":
    main()
