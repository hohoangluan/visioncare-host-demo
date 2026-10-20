"""Sinh reports/HAZARD.md từ JSON mới nhất của Gói H (C1a detect, C1b logic, C1c latency).

Dùng: python -m bench.report_hazard [--dir results/hazard] [--out reports/HAZARD.md] [--any]
Mặc định chỉ lấy file chạy ĐỦ (*_detect.json, *_logic.json, *_latency.json); --any lấy cả file chạy thử (--limit / --seeds nhỏ).
"""

import argparse
import glob
import json
import os

from bench import common

BASELINES_CHECKED = "2026-10-20"


def latest(d: str, suffix: str, any_: bool) -> str | None:
    pat = f"*_{suffix}*.json" if any_ else f"*_{suffix}.json"
    files = sorted(glob.glob(os.path.join(d, pat)), key=os.path.getmtime)
    return files[-1] if files else None


def pct(x: dict | None, d: int = 1) -> str:
    if not x or x.get("value") is None or x["value"] != x["value"]:
        return "—"
    return f"{100 * x['value']:.{d}f} % [{100 * x['ci'][0]:.{d}f}–{100 * x['ci'][1]:.{d}f}]"


def num(x, d=2) -> str:
    return "—" if x is None or x != x else f"{x:.{d}f}"


def lat_row(name: str, s: dict) -> str:
    return f"| {name} | {s['n']} | {s['p50_ms']} | {s['p90_ms']} | {s['p99_ms']} |" if s.get("n") else f"| {name} | 0 | — | — | — |"


def sec_detect(data: dict, path: str) -> list[str]:
    L = []
    meta = data["meta"]; cfg = meta["config"]
    L += ["## C1a — Phát hiện vật cản (Obstacle-Dataset test)", "",
          f"Nguồn: `{os.path.relpath(path, common.EVAL_DIR)}` · {meta['time']} · {cfg['n_images']} ảnh"
          + (f" (**chạy thử --limit {cfg['limit']}**)" if cfg.get("limit") else "") + f" · {cfg['note']}.", "",
          "Dữ liệu: Obstacle-Dataset (Tang et al., *A dataset for the recognition of obstacles on blind sidewalk*, Universal Access in the "
          "Information Society 22(1):69–82, 2023; online 2021), tập TEST, 15 lớp, nhãn VOC. Model: `live.hazard.OnnxYolo.detect` (YOLO11n COCO, ONNX tĩnh 320). "
          "**Số chính = nhóm `non_coco`** (tên file 6–9 chữ số: VOC + ảnh tác giả tự thu); nhóm `coco` (tên 12 chữ số = id COCO, có thể nằm trong train của YOLO) báo riêng để thấy mức thổi phồng.", "",
          "Metric chính: **recall@IoU0,5 không phân lớp** của hộp GT **trong lối đi** (tâm x∈[0,3;0,7], diện tích chuẩn hoá ≥0,02), ngưỡng vận hành score ≥0,35. "
          "CI 95 % bootstrap theo ảnh. Hộp `difficult` bị loại.", ""]
    for sz, blk in data["imgsz"].items():
        M = blk["metrics"]
        L += [f"### imgsz {sz}", "", "| nhóm | biến thể | ảnh | GT trong lối | **recall trong lối (không phân lớp)** | recall trong lối (đúng lớp, 9 lớp ánh xạ) | recall mọi hộp | precision vận hành (đúng lớp) | mAP@0,5 (9 lớp) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for g in ("non_coco", "coco", "all"):
            for v in ("orig", "glass"):
                m = M[g][v]
                mp = m["mAP50_mapped"]
                L.append(f"| {g}{' (**chính**)' if g == 'non_coco' else ''} | {v} | {m['n_images']} | {m['n_gt_inlane']} | **{pct(m['recall_inlane_agnostic'])}** | "
                         f"{pct(m['recall_inlane_classaware_mapped'])} | {pct(m['recall_all_agnostic'])} | {pct(m['precision_op_classaware'])} | "
                         f"{num(mp['map'], 3) if mp['map'] is not None else '—'} [{num(mp['ci'][0], 3)}–{num(mp['ci'][1], 3)}] ({mp['n_classes']} lớp) |")
        L.append("")
        L += ["Ghép đôi `orig` → `glass` (QVGA + JPEG q15) theo hộp GT trong lối đi (CI của Δ bootstrap theo ảnh):", "",
              "| nhóm | hộp | recall orig | recall glass | Δ | CI Δ | orig bắt, glass trượt | glass bắt, orig trượt |", "|---|---|---|---|---|---|---|---|"]
        for g in ("non_coco", "coco"):
            p = M[g]["paired_glass_vs_orig_inlane"]
            if p.get("n_boxes"):
                L.append(f"| {g} | {p['n_boxes']} | {100 * p['orig_recall']:.1f} % | {100 * p['glass_recall']:.1f} % | {100 * p['delta']:+.1f} đ.% | "
                         f"[{100 * p['delta_ci_by_image'][0]:+.1f}, {100 * p['delta_ci_by_image'][1]:+.1f}] | {p['orig_only']} | {p['glass_only']} |")
        L.append("")
        for v in ("glass", "orig"):
            m = M["non_coco"][v]
            L += [f"Theo lớp — nhóm `non_coco`, biến thể `{v}` (6 lớp ngoài COCO: {', '.join('`%s`' % c for c in ['reflective_cone', 'warning_column', 'spherical_roadblock', 'ashcan', 'pole', 'tricycle'])} "
                  "— recall không phân lớp > 0 chỉ do detector COCO gán nhầm lớp khác; đúng lớp = 0 theo thiết kế):", "",
                  "| lớp | GT (không difficult) | GT trong lối | recall trong lối (không phân lớp) | recall mọi hộp (không phân lớp) | AP@0,5 |", "|---|---|---|---|---|---|"]
            for c, row in m["per_class"].items():
                ap = row.get("ap")
                aps = "ngoài COCO" if ap is None and c in ("reflective_cone", "warning_column", "spherical_roadblock", "ashcan", "pole", "tricycle") else (
                    "—" if not ap or ap["ap"] is None else f"{ap['ap']:.3f} [{ap['ci'][0]:.3f}–{ap['ci'][1]:.3f}]")
                L.append(f"| {c} | {row['recall_all_agnostic']['den']} | {row['recall_inlane_agnostic']['den']} | {pct(row['recall_inlane_agnostic'])} | {pct(row['recall_all_agnostic'])} | {aps} |")
            L.append("")
        s = M["non_coco"]["glass"]["recall_inlane_agnostic_by_source"]
        L += ["Recall trong lối (glass) theo nguồn ảnh: " + "; ".join(f"{k}: {pct(v)} (n_hộp={v['den']}, {v['n_images']} ảnh)" for k, v in s.items()) + ".", ""]
        a = M["non_coco"]["glass"]["recall_inlane_agnostic_anyscore"]
        L += [f"Trần khi bỏ ngưỡng 0,35 (score ≥0,001), non_coco/glass: {pct(a)} — phần chênh với số chính là hộp bị ngưỡng vận hành cắt.", ""]
        nc = blk.get("negative_control")
        if nc:
            a, b = nc["recall_inlane_agnostic_non_coco_glass"], M["non_coco"]["glass"]["recall_inlane_agnostic"]
            L += [f"Đối chứng âm (ghép detection của ảnh i với GT của ảnh i+1): recall trong lối non_coco/glass = {pct(a)} so với số thật {pct(b)}. "
                  "Không về 0 vì vật lớn ở giữa ảnh dễ trùng IoU ≥0,5 ngẫu nhiên — đây là mức chance; số thật phải cao hơn rõ.", ""]
        L += ["Độ trễ `detect()` mỗi ảnh (glass), warm-up 20:", "", "| chặng | n | p50 ms | p90 ms | p99 ms |", "|---|---|---|---|---|", lat_row("detect (GPU)", blk["latency"]["detect_glass"]), ""]
        L += [f"Kiểm nội bộ: số ảnh mà lượt vận hành khác lượt AP (lọc ≥0,35) = {blk['info']['op_vs_any_mismatch_images']}; tên GT bị bỏ: {blk['info']['skipped_gt_names']}; provider `{blk['info']['provider']}`.", ""]
    g0 = meta["gpu_at_start"]
    L += [f"GPU lúc bắt đầu/kết thúc: `{g0}` → `{meta['gpu_at_end']}` (CUDA_VISIBLE_DEVICES={meta['cuda_visible_devices']}).", ""]
    return L


def sec_logic(data: dict, path: str) -> list[str]:
    meta = data["meta"]; cfg = meta["config"]; M = data["metrics"]; o = M["overall"]
    L = ["## C1b — Logic mức + cảnh báo (`HazardTracker` + `AntiAnnoy`, baseline)", "",
         f"Nguồn: `{os.path.relpath(path, common.EVAL_DIR)}` · {meta['time']} · {cfg['seeds']} seed × {len(cfg['types'])} loại kịch bản.", "",
         "Dữ liệu: **tổng hợp** (không có benchmark công khai cho cảnh báo va chạm theo thời gian). Chuỗi hộp 8 fps từ camera pin-hole "
         f"{cfg['camera']['w']}×{cfg['camera']['h']}, HFOV {cfg['camera']['hfov_deg']}°, cao {cfg['camera']['height_m']} m, nhìn thẳng. "
         f"Nhãn đúng bằng hình học: `t_danger` = khung đầu tiên khoảng cách < {cfg['danger']['z_m']} m **và** |lệch ngang| < {cfg['danger']['lane_half_m']} m. "
         f"\"Kịp thời\" = bíp mức ≥2 đầu tiên trước `t_danger` ≥ {cfg['lead_required_s']} s. Mô phỏng đúng đường nóng: `assess` → mức < HAZARD_MIN_LEVEL({cfg['hazard_min_level']}) coi là 0 → `AntiAnnoy.step`, đồng hồ giả 125 ms/khung. CI bootstrap theo kịch bản.", "",
         "### Tóm tắt (gộp đều các loại — mỗi loại cùng số seed nên tỉ trọng là do thiết kế bộ kịch bản, đọc bảng theo loại bên dưới)", "",
         f"- **Tỉ lệ cảnh báo kịp thời** (kịch bản nguy hiểm, n={o['n_positive']}): **{pct(o['timely_rate'])}**; trượt (không bíp trước t_danger): {pct(o['miss_rate'])}; muộn: {100 * o['late_rate']['value']:.1f} %.",
         (f"- Lead time (kịch bản có bíp, n={o['lead_time_s']['n_with_beep']}): p50 {o['lead_time_s']['p50']:.2f} s, p90 {o['lead_time_s']['p90']:.2f} s." if o.get("lead_time_s") else "- Lead time: không có bíp."),
         f"- **Báo nhầm/phút** (kịch bản an toàn, n={o['n_safe']}, {o['false_alarms_per_min']['total_minutes']:.1f} phút): {o['false_alarms_per_min']['value']:.2f} [{o['false_alarms_per_min']['ci'][0]:.2f}–{o['false_alarms_per_min']['ci'][1]:.2f}] ({o['false_alarms_per_min']['total_beeps']} bíp); "
         f"kịch bản an toàn có ≥1 bíp: {pct(o['safe_scenarios_with_beep'])}.",
         f"- Số lần gửi / kịch bản: {o['sent_per_scenario']['value']:.2f}; số lần đổi mức gửi đi / kịch bản: {o['sent_level_changes_per_scenario']['value']:.2f}; số lần đổi mức theo khung / kịch bản: {o['frame_level_changes_per_scenario']['value']:.2f}.", "",
         "### Theo loại kịch bản", "",
         "| loại | nhãn | n | kịp thời | trượt | lead p50 (s) | báo nhầm/phút | bíp/kịch bản |", "|---|---|---|---|---|---|---|---|"]
    for t, b in M["by_type"].items():
        if b["label"] == "positive":
            lt = b.get("lead_time_s")
            L.append(f"| {t} | nguy hiểm | {b['n_positive']} | {pct(b['timely_rate'], 0)} | {pct(b['miss_rate'], 0)} | {num(lt['p50']) if lt else '—'} | — | {b['sent_per_scenario']['value']:.2f} |")
        else:
            f = b["false_alarms_per_min"]
            L.append(f"| {t} | an toàn | {b['n_safe']} | — | — | — | {f['value']:.2f} ({f['total_beeps']} bíp/{f['total_minutes']:.1f} phút) | {b['sent_per_scenario']['value']:.2f} |")
    lat = data["latency"]; a = lat["assess_step_per_frame_us"]; d = lat["algo_delay_ms"]
    L += ["", "### Độ trễ", "",
          f"- `assess()+step()` mỗi khung (CPU, {a['n']} khung): p50 {a['p50_us']} µs, p90 {a['p90_us']} µs, p99 {a['p99_us']} µs (≪ 1 ms).",
          f"- **Trễ thuật toán** (khung chờ xác nhận từ đầu đoạn liên tiếp mức ≥{cfg['hazard_min_level']} đến bíp đầu × 125 ms; n={d.get('n', 0)} kịch bản có bíp): "
          + (f"p50 {d['p50_ms']} ms, p90 {d['p90_ms']} ms, p99 {d['p99_ms']} ms." if d.get("n") else "—"), "",
          "### Đối chứng (kiểm bàn đo không gian lận)", "", "| đối chứng | kỳ vọng | kết quả | đạt |", "|---|---|---|---|"]
    for k, v in data["controls"].items():
        if isinstance(v, dict):
            res = {kk: vv for kk, vv in v.items() if kk not in ("expect", "pass", "n")}
            L.append(f"| {k} | {v['expect']} | {res} | {'đạt' if v['pass'] else '**KHÔNG ĐẠT**'} |")
    L += ["", "### Giả định của bộ kịch bản (đọc trước khi dùng số)", "",
          f"- Kích thước vật (cao×rộng m): {cfg['objects']}. Cột = `parking_meter`, ghế đá = `bench` (kind tĩnh COCO gần nhất) — detector COCO thật **không thấy cột** (xem C1a); C1b kiểm logic với detector lý tưởng.",
          f"- Hộp nhỏ hơn {cfg['min_box_px']} px (ở 320×240) coi là detector không thấy. Đầu lắc: ±{100 * cfg['shake']['size']:.0f} % kích thước, ±{100 * cfg['shake']['pos_of_box']:.0f} % **kích thước hộp** cho vị trí. Chập chờn: mỗi khung mất detection với xác suất {cfg['flicker_p']:.2f}. Score ngẫu nhiên {cfg['score_range']} (logic mức không dùng score).",
          "- Tốc độ \"xe máy 4 m/s\" hiểu là **tốc độ tiến lại gần tổng cộng** (người ngược chiều 2,4 m/s cũng là tổng, theo PLAN). Vật tiến thẳng có lệch ngang ngẫu nhiên U(−0,4; 0,4) m — luôn trong lối.",
          "- \"Trong lối\" của nhãn dùng lệch ngang của **tâm** vật (|X| < 0,6 m), không tính bề rộng vật.",
          "- Không có benchmark công khai cho TTC người đi bộ — **không có baseline công bố để đối chiếu C1b**.", ""]
    return L


def sec_latency(data: dict, path: str) -> list[str]:
    meta = data["meta"]; cfg = meta["config"]
    L = ["## C1c — Độ trễ đường nóng phía server", "",
         f"Nguồn: `{os.path.relpath(path, common.EVAL_DIR)}` · {meta['time']} · {cfg['note']}. Ảnh Obstacle-Dataset thu rộng 320 giữ tỉ lệ + JPEG q15 (như kính gửi); một tracker xuyên suốt, thứ tự ảnh cố định (seed 0). Không gồm mạng/kính/Cloudflare.", ""]
    for sz, r in data["by_imgsz"].items():
        lat = r["latency"]
        L += [f"### imgsz {sz} ({r['n_frames']} khung, provider `{r['provider']}`)", "", "| chặng | n | p50 ms | p90 ms | p99 ms |", "|---|---|---|---|---|"]
        for k, name in (("decode", "decode JPEG (cv2.imdecode)"), ("detect", "detect (OnnxYolo)"), ("assess", "assess"), ("step", "AntiAnnoy.step"),
                        ("total", "**tổng 4 chặng**"), ("process_frame_plus_step", "đối chiếu: `nav_live.process_frame`+step")):
            L.append(lat_row(name, lat[k]))
        b = r["budget"]
        L += ["", f"assess p50/p90/p99 = {lat['assess_us']['p50_us']}/{lat['assess_us']['p90_us']}/{lat['assess_us']['p99_us']} µs; step = {lat['step_us']['p50_us']}/{lat['step_us']['p90_us']}/{lat['step_us']['p99_us']} µs. JPEG q15 trung bình {lat['jpeg_bytes_mean']:.0f} byte.",
              f"Ngân sách server p90 ≤ {b['server_p90_ms']} ms: p90 tổng = {b['total_p90_ms']} ms → **{'trong ngân sách' if b['within_budget'] else 'VƯỢT ngân sách'}**.", ""]
    g = meta["gpu_at_start"]
    L += [f"GPU lúc bắt đầu `{g}` → kết thúc `{meta['gpu_at_end']}` (CUDA_VISIBLE_DEVICES={meta['cuda_visible_devices']}); GPU có thể đang chia sẻ — đọc util trước khi so với mốc cũ (4,90/5,26 ms).", ""]
    return L


def baselines() -> list[str]:
    return [
        "## Baseline công bố (chép từ bài gốc)", "",
        f"Đối chiếu ngày {BASELINES_CHECKED}. **Chưa đối chiếu được bài gốc của dataset**: Tang et al., UAIS 22(1):69–82 (doi 10.1007/s10209-021-00837-9) — trang Springer chuyển hướng đăng nhập, "
        "không đọc được bảng; repo `github.com/TW0521/Obstacle-Dataset` có README (train 5.066 / test 1.583 / val 1.266, 15 lớp) nhưng **không đăng kết quả mAP**. → *chưa đối chiếu*.", "",
        "Bài dùng dataset làm baseline: He & Saha, *Investigating YOLO Models Towards Outdoor Obstacle Detection For Visually Impaired People*, arXiv:2312.07571 (10/2023). "
        "**Đã đối chiếu với PDF** (người dùng chép Table 1–7 từ PDF, 2026-10-20; khớp toàn bộ số trích trước đó qua HTML). **Table 6** (tổng thể, 15 lớp):", "",
        "| Model (huấn luyện trên train của Obstacle-Dataset) | Precision@0,5 | Recall@0,5 | mAP@0,5 |", "|---|---|---|---|",
        "| YOLOv5 | 0,781 | 0,682 | 0,742 |", "| YOLOv6 | 0,786 | 0,714 | 0,784 |", "| **YOLOv7** (tốt nhất) | 0,786 | 0,778 | **0,817** |",
        "| YOLOv8 | 0,80 | 0,682 | 0,758 |", "| YOLO-NAS-S | 0,7888 | 0,5941 | 0,6673 |", "| YOLO-NAS-M | 0,7875 | 0,6206 | 0,6906 |",
        "| YOLO-NAS-L | 0,7853 | 0,6274 | 0,698 |", "",
        "mAP@0,5 theo lớp (Table 3 YOLOv7, Table 4 YOLOv8; 1.262 ảnh, 7.938 nhãn) — đặt cạnh AP@0,5 zero-shot của SeeVia ở bảng theo lớp phía trên:", "",
        "| Lớp | YOLOv7 | YOLOv8 | Lớp | YOLOv7 | YOLOv8 |", "|---|---|---|---|---|---|",
        "| stop_sign | 0,874 | 0,832 | reflective_cone | 0,944 | 0,896 |",
        "| person | 0,749 | 0,677 | ashcan | 0,904 | 0,870 |",
        "| bicycle | 0,728 | 0,624 | warning_column | 0,898 | 0,872 |",
        "| bus | 0,800 | 0,659 | spherical_roadblock | 0,958 | 0,953 |",
        "| truck | 0,626 | 0,542 | pole | 0,642 | 0,625 |",
        "| car | 0,764 | 0,700 | tricycle | 0,947 | 0,916 |",
        "| motorbike | 0,727 | 0,685 | dog | 0,822 | 0,717 |",
        "| fire_hydrant | 0,871 | 0,807 | | | |", "",
        "Lưu ý về chính bài: (1) các bảng ghi **1.262 ảnh** — gần với tập **val** (README: 1.266) chứ không phải test 1.583 mà SeeVia đo → **khác tập chấm**; "
        "(2) mâu thuẫn nội bộ nhỏ: YOLOv8 recall 0,683 (Table 4) vs 0,682 (Table 6); YOLO-NAS-M Table 5 (P 0,7589 / R 0,6148 / mAP 0,6829) vs Table 6 (0,7875 / 0,6206 / 0,6906); "
        "(3) Table 7: ngưỡng score 0,3 → 0,7 đổi recall YOLO-NAS-L 0,785 → 0,456 — cùng hiện tượng ngưỡng 0,35 cắt recall ở SeeVia.", "",
        "`METRICS.md` còn trích PMC 11645096 (YOLO-OD): bài đó dùng **bộ dữ liệu khác** (6.276 ảnh, 4 lớp: car, person, traffic cone, pothole; nguồn Baidu AI Studio) — **không phải** Obstacle-Dataset, không dùng làm baseline ở đây.", ""]


def limits() -> list[str]:
    return ["## Giới hạn / không so trực tiếp được", "",
            "- **Không so ngang hàng với baseline bài**: bài huấn luyện YOLO trên train của Obstacle-Dataset (có cả 6 lớp ngoài COCO), SeeVia dùng YOLO11n COCO **zero-shot**; mAP của ta chỉ tính 9 lớp ánh xạ được, ngưỡng AP quét 0,001–1, NMS 0,45 của VH.",
            "- Nhóm `coco` có thể đã nằm trong dữ liệu huấn luyện YOLO11n (COCO train2017) → số đẹp giả; chỉ `non_coco` là số trung thực. Nguồn `voc` cũng là PASCAL VOC (không nằm trong COCO train nhưng cùng phân phối).",
            "- Recall/precision phụ thuộc ngưỡng vận hành 0,35 của `config.HAZARD_MIN_SCORE`; AP dùng ngưỡng 0,001 bằng cách đặt tạm `config.HAZARD_MIN_SCORE` (không sửa file VH).",
            "- Ảnh `glass` giữ tỉ lệ gốc, rộng 320; kính thật gửi QVGA 320×240 (có thể khác tỉ lệ).",
            "- C1b là kiểm chứng LOGIC trên dữ liệu tổng hợp với detector lý tưởng (mọi vật trong ảnh đều được thấy, hộp hoàn hảo trừ nhiễu mô phỏng) — không thay dữ liệu thật; không có baseline công bố.",
            "- C1c chỉ đo phía server (decode → detect → assess → step); chưa gồm mạng, kính, Cloudflare. GPU dùng chung nên p99 có thể nhiễu.",
            "- Phạm vi: chỉ đo baseline, không thử cải tiến (PLAN, bổ sung 2026-10-20).", ""]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(common.RESULTS, "hazard"))
    ap.add_argument("--out", default=os.path.join(common.REPORTS, "HAZARD.md"))
    ap.add_argument("--any", action="store_true", help="cho phép file chạy thử (--limit / --seeds nhỏ)")
    args = ap.parse_args()
    L = ["# HAZARD — Vật cản (C1a phát hiện · C1b logic · C1c độ trễ)", "",
         "Sinh tự động bởi `bench/report_hazard.py` từ JSON mới nhất trong `results/hazard/`. Đây là **baseline đo, không phải cải tiến**.", ""]
    srcs = {}
    for suf, fn in (("detect", sec_detect), ("logic", sec_logic), ("latency", sec_latency)):
        p = latest(args.dir, suf, args.any)
        srcs[suf] = p
        if p:
            L += fn(json.load(open(p, encoding="utf-8")), p)
        else:
            L += [f"## {suf}", "", f"_Chưa có kết quả đủ trong `{args.dir}` (chạy `run_hazard.sh`)._", ""]
    L += baselines() + limits()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
        f.flush(); os.fsync(f.fileno())
    print("ghi", args.out, {k: (os.path.basename(v) if v else None) for k, v in srcs.items()})


if __name__ == "__main__":
    main()
