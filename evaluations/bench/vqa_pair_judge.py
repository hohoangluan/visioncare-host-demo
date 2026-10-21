"""C4 — so ghép đôi MÙ hai prompt trả lời câu hỏi về ảnh (VizWiz-VQA test 300): `space` (cũ) vs `ask` (mới, 2026-10-21).

Vì sao: chấm tay 50 câu (handcheck_50_human.csv) — lỗi chung là trả lời THỪA và KHÔNG TẬP TRUNG vào câu hỏi; VQA acc
không bắt được lỗi này (câu dài vẫn "khớp" đáp án). Giám khảo nhìn ảnh, thấy hai câu trả lời theo thứ tự ngẫu nhiên
(không biết câu nào của prompt nào), chấm từng câu + chọn câu tốt hơn.

Giám khảo: Codex (nếu có trên máy) hoặc Claude Sonnet subagent nhìn ảnh — cùng BRIEF. Đối chứng âm cài lẫn (giám khảo không biết): 15 dòng một câu bị TRÁO sang ảnh khác (phải bị đánh bịa/sai),
15 dòng hai câu Y HỆT nhau (phải ra 'tie'). Không đạt thì không tin phán quyết.

    python -m bench.vqa_pair_judge build   # -> results/vqa_vizwiz/pair_judge/{blind.csv, key.json, BRIEF.md}
    python -m bench.vqa_pair_judge report  # -> reports/VQA_ASK.md (+ JSON)
"""

import argparse
import csv
import glob
import json
import os
import random
import re

import numpy as np

from bench import common

TASK = "vqa_vizwiz"
# Lượt xác nhận (2026-10-21): PAIR_JUDGE_DIR = thư mục chấm riêng (không lẫn judge.csv cũ), PAIR_JUDGE_NEW = JSON câu trả lời `ask` mới,
# PAIR_JUDGE_REPORT = tên báo cáo (mặc định VQA_ASK.md).
D = os.environ.get("PAIR_JUDGE_DIR") or os.path.join(common.RESULTS, TASK, "pair_judge")
VAL = os.path.join(common.DATAS, "vizwiz", "val")
HUMAN = os.path.join(os.path.dirname(common.EVAL_DIR), "handcheck_50_human.csv")
N_SWAP, N_SAME = 15, 15

BRIEF = """# Việc: so sánh MÙ hai câu trả lời của trợ lý cho người khiếm thị (VizWiz-VQA)

Bạn là giám khảo. Đây là câu trả lời câu hỏi CHO NGƯỜI MÙ: người hỏi không tự nhìn được ảnh, chỉ NGHE câu trả lời một lần.
File `blind.csv` (cùng thư mục) có {n} dòng. Mỗi dòng: ảnh do người khiếm thị chụp (`image_path`), câu hỏi
(`question_en`, bản dịch `question_vi`), 10 đáp án tiếng Anh của 10 người (`gt_answers_en`; "unanswerable" = người đó cho rằng
ảnh không đủ để trả lời), và HAI câu trả lời tiếng Việt `answer_1`, `answer_2` (sẽ được ĐỌC THÀNH TIẾNG cho người mù nghe).

## Với MỖI dòng, theo thứ tự `row`:
1. **Mở và NHÌN ảnh** bằng công cụ xem ảnh (bắt buộc).
2. Chấm RIÊNG từng câu trả lời k = 1, 2:
   - `direct_k` (0/1): 1 nếu CÂU ĐẦU TIÊN trả lời thẳng câu hỏi — hoặc nói thẳng là không trả lời được. Mở đầu bằng loại phòng,
     bối cảnh, hay mô tả vật khác rồi mới trả lời = 0. Không trả lời câu hỏi ở đâu cả = 0.
   - `extra_k` (0/1): 1 nếu có ý KHÔNG cần cho câu hỏi: tả căn phòng, mặt bàn, bàn tay, đồ xung quanh; nói tên thiết bị khi chỉ
     hỏi nội dung màn hình; hỏi lại "bạn có muốn tôi đọc..."; nhắc lại ý đã nói. Nếu câu hỏi NHỜ mô tả/tóm tắt thì chi tiết
     liên quan KHÔNG tính là thừa.
   - `correct_k` (0/1): 1 nếu nội dung trả lời câu hỏi ĐÚNG với ảnh (nhìn ảnh + đối chiếu đáp án người). Từ chối đúng lúc (ảnh
     thật sự không đủ) = 1; từ chối khi ảnh đủ để trả lời = 0.
   - `halluc_k` (0/1): 1 nếu câu trả lời KHẲNG ĐỊNH điều ảnh KHÔNG cho thấy hoặc trái với ảnh.
   - `refused_k` (0/1): 1 nếu câu trả lời nói không thấy rõ / không trả lời được / bảo chụp lại.
   - `fix_k` (0/1, chỉ khi refused_k = 1, còn lại để 0): 1 nếu có nêu LÝ DO và MỘT CÁCH SỬA cụ thể (xoay vật, đưa xa/gần, bật đèn...).
3. `better`: `1`, `2` hoặc `tie` — câu nào tốt hơn CHO NGƯỜI MÙ NGHE (đúng trước, rồi trúng câu hỏi, rồi ngắn gọn). Giống hệt nhau = tie.
4. `note`: ≤ 15 từ tiếng Việt.
5. Ghi NGAY dòng đó vào `judge.csv` (cùng thư mục), cột:
   `row,direct_1,extra_1,correct_1,halluc_1,refused_1,fix_1,direct_2,extra_2,correct_2,halluc_2,refused_2,fix_2,better,note`
   (CSV chuẩn, dòng đầu là tên cột). Nếu `judge.csv` đã có dòng nào thì bỏ qua các `row` đã có và làm tiếp.

## Cấm
- Không sửa `blind.csv`, không tạo file khác, không đoán khi chưa xem ảnh. Không cố đoán câu nào "mới/cũ" — chấm theo nội dung.
- Không hỏi lại. Làm hết {n} dòng.
"""

COLS = ["row", "direct_1", "extra_1", "correct_1", "halluc_1", "refused_1", "fix_1",
        "direct_2", "extra_2", "correct_2", "halluc_2", "refused_2", "fix_2", "better", "note"]
FIELDS = ["direct", "extra", "correct", "halluc", "refused", "fix"]


def latest(intent: str) -> dict:
    if intent == "ask" and os.environ.get("PAIR_JUDGE_NEW"):
        with open(os.environ["PAIR_JUDGE_NEW"], encoding="utf-8") as f:
            d = json.load(f)
        d["_path"] = os.environ["PAIR_JUDGE_NEW"]
        return d
    files = sorted(f for f in glob.glob(os.path.join(common.RESULTS, TASK, f"*_general_{intent}.json")))
    if not files:
        raise SystemExit(f"chưa có kết quả test cho intent {intent}")
    with open(files[-1], encoding="utf-8") as f:
        d = json.load(f)
    d["_path"] = files[-1]
    return d


def build(n_real: int | None = None) -> None:
    old, new = latest("space"), latest("ask")
    O = {x["image"]: x for x in old["per_sample"] if not x.get("error")}
    N = {x["image"]: x for x in new["per_sample"] if not x.get("error")}
    imgs = [k for k in O if k in N]
    rng = random.Random(0)
    if n_real and n_real < len(imgs):
        # Giữ đủ 50 câu đã chấm tay (để hiệu chỉnh giám khảo theo người), phần còn lại lấy ngẫu nhiên.
        hand = [k for k in imgs if k in human_labels()]
        rest = [k for k in imgs if k not in hand]
        imgs = hand + rng.sample(rest, n_real - len(hand))
    rows, key = [], []
    for k in imgs:
        flip = rng.random() < 0.5
        a, b = (N[k], O[k]) if flip else (O[k], N[k])
        rows.append((k, a["output"], b["output"]))
        key.append({"image": k, "kind": "real", "ans1": "ask" if flip else "space", "ans2": "space" if flip else "ask"})
    # Đối chứng âm: tráo câu trả lời từ ảnh khác (lấy từ prompt cũ để có nội dung cụ thể) / hai câu y hệt
    ctrl = rng.sample(imgs, N_SWAP + N_SAME)
    for i, k in enumerate(ctrl):
        if i < N_SWAP:
            other = rng.choice([x for x in imgs if x != k])
            pos = rng.choice([1, 2])
            pair = (O[other]["output"], N[k]["output"]) if pos == 1 else (N[k]["output"], O[other]["output"])
            rows.append((k, *pair))
            key.append({"image": k, "kind": "swap", "swapped_pos": pos, "from": other})
        else:
            rows.append((k, N[k]["output"], N[k]["output"]))
            key.append({"image": k, "kind": "same"})
    order = list(range(len(rows)))
    rng.shuffle(order)
    os.makedirs(D, exist_ok=True)
    with open(os.path.join(D, "blind.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row", "image_path", "question_en", "question_vi", "gt_answers_en", "answer_1", "answer_2"])
        for r, i in enumerate(order):
            k, a1, a2 = rows[i]
            x = O[k]
            w.writerow([r, os.path.join(VAL, k), x["question_en"], x["question_vi"],
                        " | ".join(f"{j}:{a}" for j, a in enumerate(x["gt_answers"])), a1.replace("\n", " "), a2.replace("\n", " ")])
    with open(os.path.join(D, "key.json"), "w", encoding="utf-8") as f:
        json.dump({"old": old["_path"], "new": new["_path"], "rows": [key[i] for i in order]}, f, ensure_ascii=False, indent=0)
    with open(os.path.join(D, "BRIEF.md"), "w", encoding="utf-8") as f:
        f.write(BRIEF.format(n=len(rows)))
    print(f"{len(rows)} dòng ({len(imgs)} thật + {N_SWAP} tráo + {N_SAME} y hệt) -> {D}")


def ci(x) -> dict:
    x = np.asarray(x, dtype=float)
    v, lo, hi = common.bootstrap_ci(x)
    return {"value": v, "ci": [lo, hi], "n": int(len(x))}


def pct(e: dict) -> str:
    return f"{100 * e['value']:.1f} % [{100 * e['ci'][0]:.1f}; {100 * e['ci'][1]:.1f}]"


def human_labels() -> dict:
    """Mã hoá ghi chú chấm tay (bản cũ, prompt space): thừa / không trả lời trúng câu hỏi."""
    out = {}
    if not os.path.exists(HUMAN):
        return out
    extra = re.compile(r"thừa|dư|dài|lan man|chỉ cần|là đủ|là được|không cần")
    off = re.compile(r"không trả lời (?:câu hỏi|đúng)|không tập trung|trọng tâm|tập trung vào những|tự trả lời kiểu khác|vấn đề khác|xử lý od|luồng của module od")
    with open(HUMAN, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            note = r["human_note"].lower()
            out[r["image"]] = {"extra": int(bool(extra.search(note))), "offfocus": int(bool(off.search(note))),
                               "halluc": int(r["human_hallucination"] or 0), "answerable": int(r["human_image_answerable"] or 0)}
    return out


def report() -> None:
    with open(os.path.join(D, "key.json"), encoding="utf-8") as f:
        K = json.load(f)
    with open(os.path.join(D, "judge.csv"), encoding="utf-8") as f:
        J = {int(r["row"]): r for r in csv.DictReader(f)}
    old, new = latest("space"), latest("ask")
    O = {x["image"]: x for x in old["per_sample"]}
    N = {x["image"]: x for x in new["per_sample"]}
    real, swap, same = [], [], []
    for r, k in enumerate(K["rows"]):
        if r not in J:
            continue
        j = J[r]
        g = lambda f, p: int(float(j[f"{f}_{p}"] or 0))  # noqa: E731
        if k["kind"] == "real":
            pos = {k["ans1"]: 1, k["ans2"]: 2}
            rec = {"image": k["image"], "better": j["better"].strip(), "pos_new": pos["ask"]}
            for v in ("space", "ask"):
                for f in FIELDS:
                    rec[f"{v}_{f}"] = g(f, pos[v])
            real.append(rec)
        elif k["kind"] == "swap":
            sp = k["swapped_pos"]
            swap.append({"bad_flag": g("halluc", sp) or (1 - g("correct", sp)), "true_flag": g("halluc", 3 - sp)})
        else:
            same.append(j["better"].strip() == "tie")
    n = len(real)
    res = {"n_real": n, "n_rows_judged": len(J), "n_rows": len(K["rows"]), "old": K["old"], "new": K["new"]}
    for f in FIELDS:
        a = np.array([x[f"space_{f}"] for x in real]); b = np.array([x[f"ask_{f}"] for x in real])
        res[f] = {"space": ci(a), "ask": ci(b), "delta": ci(b - a),
                  "space_only": int(((a == 1) & (b == 0)).sum()), "ask_only": int(((a == 0) & (b == 1)).sum())}
    better = [x["better"] for x in real]
    win = lambda x: 1.0 if x["better"] == str(x["pos_new"]) else (0.5 if x["better"] == "tie" else 0.0)  # noqa: E731
    res["pref"] = {"ask": sum(1 for x in real if x["better"] == str(x["pos_new"])),
                   "space": sum(1 for x in real if x["better"] not in ("tie", str(x["pos_new"]))),
                   "tie": better.count("tie"), "win_rate_ask": ci([win(x) for x in real]),
                   "pos1_rate": ci([x["better"] == "1" for x in real])}
    # Nhóm câu hỏi: trả lời được / không (nhãn đa số VizWiz)
    for name, cond in (("answerable", 1), ("unanswerable", 0)):
        sub = [x for x in real if O[x["image"]]["answerable"] == cond]
        res[f"by_{name}"] = {f: {"space": ci([x[f"space_{f}"] for x in sub]), "ask": ci([x[f"ask_{f}"] for x in sub])}
                             for f in FIELDS}
        res[f"by_{name}"]["n"] = len(sub)
    w_old = np.array([O[x["image"]]["words"] if "words" in O[x["image"]] else len(O[x["image"]]["output"].split()) for x in real])
    w_new = np.array([N[x["image"]]["words"] for x in real])
    res["words"] = {"space_median": float(np.median(w_old)), "ask_median": float(np.median(w_new)),
                    "space_mean": ci(w_old), "ask_mean": ci(w_new), "ratio_mean": float(w_new.mean() / w_old.mean())}
    ab = sorted(glob.glob(os.path.join(common.RESULTS, TASK, "*_latency_ab.json")))
    if ab:  # gọi mới, xen kẽ trên cùng ảnh — số trong cache của hai prompt là của hai ngày khác nhau
        with open(ab[-1], encoding="utf-8") as f:
            a = json.load(f)
        res["latency"] = {**a["latency"], "paired": a["paired_delta_ask_minus_space"], "source": ab[-1]}
    else:
        res["latency"] = {"space": old["latency"], "ask": new["latency"]}
    res["gemma_judge"] = {"space": old["metrics"], "ask": new["metrics"]}
    res["control"] = {"swap_flagged": ci([x["bad_flag"] for x in swap]) if swap else None,
                      "swap_true_flagged_halluc": ci([x["true_flag"] for x in swap]) if swap else None,
                      "same_tie": ci(same) if same else None}
    ok = swap and same and res["control"]["swap_flagged"]["value"] >= 0.8 and res["control"]["same_tie"]["value"] >= 0.8
    res["control"]["pass"] = bool(ok)
    # Hiệu chỉnh giám khảo bằng người: trên 50 câu chấm tay (bản cũ)
    H = human_labels()
    cal = [(H[x["image"]], x) for x in real if x["image"] in H]
    if cal:
        def agree(hk, ck, inv=False):
            h = np.array([c[0][hk] for c in cal]); c = np.array([(1 - c[1][ck]) if inv else c[1][ck] for c in cal])
            return {"agree": float((h == c).mean()), "human_pos": int(h.sum()), "codex_pos": int(c.sum()), "both": int(((h == 1) & (c == 1)).sum()), "n": len(cal)}
        res["human_calibration"] = {"extra": agree("extra", "space_extra"), "offfocus": agree("offfocus", "space_direct", inv=True),
                                    "halluc": agree("halluc", "space_halluc")}
        res["human_subset_50"] = {f: {"space": float(np.mean([c[1][f"space_{f}"] for c in cal])),
                                      "ask": float(np.mean([c[1][f"ask_{f}"] for c in cal]))} for f in FIELDS}
    common.write_result(TASK, "pair_judge", res)
    write_md(res)


def write_md(r: dict) -> None:
    lat = r["latency"]
    L = lambda d: f"{d['p50_ms']:.0f} / {d['p90_ms']:.0f} / {d['p99_ms']:.0f}"  # noqa: E731
    names = {"direct": "Câu đầu trả lời thẳng câu hỏi ↑", "extra": "Có nội dung thừa ↓", "correct": "Đúng với ảnh ↑",
             "halluc": "Bịa (khẳng định điều ảnh không có) ↓", "refused": "Từ chối", "fix": "Từ chối CÓ lý do + cách sửa ↑"}
    out = ["# C4 — Hỏi về ảnh: prompt `space` (cũ) vs `ask` (mới) — so ghép đôi MÙ", "",
           f"VizWiz-VQA val, mẫu test 300 (seed 0), {r['n_real']} câu ghép đôi. Giám khảo: {r.get('judge', 'Claude Sonnet')} **nhìn ảnh**, thấy 2 câu trả lời "
           "theo thứ tự ngẫu nhiên, không biết câu nào của prompt nào. Prompt `ask` chỉnh trên 100 câu dev KHÁC 300 câu này. "
           "CI 95 % bootstrap; Δ = ask − space theo cặp; cột 'chỉ cũ / chỉ mới' = số câu bất đồng.", "",
           "| Chỉ số | space (cũ) | ask (mới) | Δ [CI] | chỉ cũ / chỉ mới |", "|---|---|---|---|---|"]
    for f in FIELDS:
        e = r[f]
        d = e["delta"]
        out.append(f"| {names[f]} | {pct(e['space'])} | {pct(e['ask'])} | {100 * d['value']:+.1f} đ.% [{100 * d['ci'][0]:+.1f}; {100 * d['ci'][1]:+.1f}] | {e['space_only']} / {e['ask_only']} |")
    w = r["words"]
    out += [f"| Số từ (trung vị) | {w['space_median']:.0f} | {w['ask_median']:.0f} | ×{w['ratio_mean']:.2f} (trung bình) | |",
            f"| Thời gian đọc TTS ước tính (~3,6 từ/s, trung vị) | {w['space_median'] / 3.6:.1f} s | {w['ask_median'] / 3.6:.1f} s | | |", "",
            f"**Chọn câu tốt hơn:** ask {r['pref']['ask']} · space {r['pref']['space']} · hoà {r['pref']['tie']} — "
            f"tỉ lệ thắng của ask (hoà = ½) {pct(r['pref']['win_rate_ask'])}. Kiểm thiên vị vị trí: chọn câu số 1 {pct(r['pref']['pos1_rate'])}.", "",
            "## Theo loại câu hỏi (nhãn đa số VizWiz)", "", "| Nhóm | n | Chỉ số | space | ask |", "|---|---|---|---|---|"]
    for name in ("answerable", "unanswerable"):
        b = r[f"by_{name}"]
        for f in ("direct", "extra", "correct", "halluc", "refused", "fix"):
            out.append(f"| {name} | {b['n']} | {names[f]} | {pct(b[f]['space'])} | {pct(b[f]['ask'])} |")
    g = r["gemma_judge"]
    gk = lambda m, k: pct(m[k]) if k in m else "—"  # noqa: E731
    out += ["", "## Chỉ số cũ của bàn đo (Gemma-chấm, VQA acc chuẩn VizWiz)", "",
            "| Chỉ số | space | ask |", "|---|---|---|",
            f"| VQA acc (tất cả) | {gk(g['space'], 'vqa_acc_all')} | {gk(g['ask'], 'vqa_acc_all')} |",
            f"| VQA acc (câu trả lời được) | {gk(g['space'], 'vqa_acc_answerable')} | {gk(g['ask'], 'vqa_acc_answerable')} |",
            f"| Không từ chối trên câu unanswerable | {gk(g['space'], 'fabricate_rate_unanswerable')} | {gk(g['ask'], 'fabricate_rate_unanswerable')} |",
            f"| Từ chối trên câu trả lời được | {gk(g['space'], 'refusal_rate_answerable')} | {gk(g['ask'], 'refusal_rate_answerable')} |",
            "", "## Độ trễ (LLM xa Gemma 4 26B; ms p50 / p90 / p99)", "",
            ("Gọi MỚI trên cùng ảnh, hai prompt xen kẽ, thứ tự đảo ngẫu nhiên (`bench/vqa_latency_ab.py`)." if "paired" in lat
             else "Lấy từ cache của từng lượt chạy (khác thời điểm)."), "",
            "| | space | ask | Δ ghép đôi (ask − space) [CI] |", "|---|---|---|---|",
            *[f"| {lab} | {L(lat['space'][m])} | {L(lat['ask'][m])} | "
              + (f"{lat['paired'][m]['delta_mean_ms']:+.0f} ms [{lat['paired'][m]['ci'][0]:+.0f}; {lat['paired'][m]['ci'][1]:+.0f}]" if "paired" in lat else "—") + " |"
              for m, lab in (("ttft", "TTFT — câu nói đầu ra khỏi `general.answer` (≥ 2 từ + dấu câu, hoặc 8 từ)"), ("total", "Tổng — hết câu trả lời"))],
            "", "TTFT của `ask` cao hơn vì câu nói đầu giờ là ĐÁP ÁN (thường đủ 8 từ mới cắt), còn `space` cắt ngay ở \"Trong nhà.\" — "
            "đáp án thật của `space` thường nằm ở câu 2–3, tức sau mốc 'tổng' của câu đầu.", ""]
    c = r["control"]
    out += ["## Đối chứng âm (giám khảo có thật sự nhìn ảnh / đọc kỹ không)", "",
            f"- Câu bị tráo sang ảnh khác bị đánh bịa hoặc sai: **{pct(c['swap_flagged'])}** (cần ≥ 80 %)",
            f"- Hai câu y hệt được chấm hoà: **{pct(c['same_tie'])}** (cần ≥ 80 %)",
            f"- Kết luận: **{'ĐẠT' if c['pass'] else 'KHÔNG ĐẠT — không tin phán quyết'}**", ""]
    if "human_calibration" in r:
        h = r["human_calibration"]
        out += ["## Đối chiếu giám khảo với người chấm tay (50 câu, bản cũ)", "",
                "Ghi chú tay được mã hoá: 'thừa' = ghi chú có *thừa/dư/dài/lan man/chỉ cần/là đủ*; 'không trúng câu hỏi' = *không trả lời câu hỏi/không tập trung/trọng tâm*.", "",
                "| Nhãn | Người = 1 | Giám khảo = 1 | Cả hai | Đồng ý |", "|---|---|---|---|---|"]
        for k, lab in (("extra", "Thừa"), ("offfocus", "Không trúng câu hỏi (giám khảo: direct = 0)"), ("halluc", "Bịa")):
            e = h[k]
            out.append(f"| {lab} | {e['human_pos']} | {e['codex_pos']} | {e['both']} | {100 * e['agree']:.0f} % (n={e['n']}) |")
        s = r["human_subset_50"]
        out += ["", "Trên đúng 50 câu bạn đã chấm: " + " · ".join(
            f"{names[f].split(' ↑')[0].split(' ↓')[0]} {100 * s[f]['space']:.0f} % → {100 * s[f]['ask']:.0f} %" for f in ("direct", "extra", "correct", "halluc")), ""]
    out += routing_md()
    out += [f"Nguồn: `{os.path.relpath(r['old'], common.EVAL_DIR)}` (space), `{os.path.relpath(r['new'], common.EVAL_DIR)}` (ask). "
            "Chạy lại: `python -m bench.vqa_pair_judge build` → giám khảo (Sonnet subagent theo `BRIEF.md`, hoặc Codex `run.sh`) → `report`."]
    path = os.path.join(common.REPORTS, os.environ.get("PAIR_JUDGE_REPORT", "VQA_ASK.md"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("ghi", path)


def routing_md() -> list[str]:
    """Định tuyến câu hỏi VizWiz qua bộ phân loại production + hồi quy trên gold intent (results/intent_ask/)."""
    d = os.path.join(common.RESULTS, "intent_ask")
    out = []
    try:
        b = json.load(open(os.path.join(d, "route_vizwiz_before.json"), encoding="utf-8"))
        a = json.load(open(os.path.join(d, "route_vizwiz_after.json"), encoding="utf-8"))
    except OSError:
        return out
    from collections import Counter
    cb, ca = Counter(v["intent"] for v in b.values()), Counter(v["intent"] for v in a.values())
    note = {"chat": "trả lời KHÔNG có ảnh", "ocr": "đọc cả văn bản, bỏ qua câu hỏi", "space": "mô tả không gian",
            "ask": "trả lời đúng câu hỏi (mới)", "find": "tìm đồ", "money": "đọc tiền", "nav_start": "dẫn đường"}
    out += ["## Định tuyến: câu hỏi về ảnh đi vào chức năng nào (300 câu VizWiz đã dịch, bộ phân loại Gemma production)", "",
            "| Intent | Đường xử lý | Trước | Sau |", "|---|---|---|---|"]
    for k in sorted(set(cb) | set(ca), key=lambda k: -cb.get(k, 0) - ca.get(k, 0)):
        out.append(f"| `{k}` | {note.get(k, '')} | {cb.get(k, 0)} ({100 * cb.get(k, 0) / len(b):.0f} %) | {ca.get(k, 0)} ({100 * ca.get(k, 0) / len(a):.0f} %) |")
    rows = []
    for g in ("dev", "test"):
        try:
            base = open(os.path.join(d, f"base_{g}.log"), encoding="utf-8").read()
            fin = open(os.path.join(d, f"final_{g}.log"), encoding="utf-8").read()
        except OSError:
            continue
        acc = lambda t: re.search(r"acc=([\d.]+)\s+p50=(\d+)ms\s+p90=(\d+)ms", t).groups()  # noqa: E731
        mc = re.search(r"\{'a_only': (\d+), 'b_only': (\d+), 'p_value': ([\d.e-]+)\}", fin).groups()
        (ab, pb, qb), (af, pf, qf) = acc(base), acc(fin)
        rows.append(f"| gold {g} | {100 * float(ab):.1f} % | {100 * float(af):.1f} % | {mc[0]} / {mc[1]} (p = {float(mc[2]):.2f}) | {pb} / {qb} → {pf} / {qf} |")
    if rows:
        out += ["", "Hồi quy bộ phân loại trên tập gold intent của VH (nhãn cũ, chưa có `ask` — câu hỏi một chi tiết in trên nhãn mà gold "
                "ghi `ocr` nay ra `ask` bị tính là SAI ở đây):", "",
                "| Tập | acc trước | acc sau | được / mất (McNemar) | p50 / p90 ms |", "|---|---|---|---|---|", *rows]
    return out + [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "report"])
    ap.add_argument("--n-real", type=int, default=None, help="số cặp thật (mặc định: cả 300)")
    a = ap.parse_args()
    build(a.n_real) if a.cmd == "build" else report()


if __name__ == "__main__":
    main()
