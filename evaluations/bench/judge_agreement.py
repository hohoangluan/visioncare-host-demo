"""Đồng thuận giám khảo C4 (VizWiz-VQA): Gemma-chấm (trong bench) vs Codex gpt-6-luna chấm MÙ có nhìn ảnh.

Đầu vào: results/vqa_vizwiz/codex_judge/{blind.csv, judge_codex.csv} + JSON C4 mới nhất. Ra: reports/VQA_JUDGE_CODEX.md + JSON.
Codex không phải người — đây là giám khảo độc lập thứ hai (khác họ model), không thay được người chấm.

    python -m bench.judge_agreement
"""

import csv
import glob
import json
import os

import numpy as np

from bench import common

J = os.path.join(common.RESULTS, "vqa_vizwiz", "codex_judge")


def kappa(a: list[int], b: list[int]) -> float:
    a, b = np.array(a), np.array(b)
    po = float((a == b).mean())
    pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def is_unans(s: str) -> bool:
    s = s.strip().lower()
    return s == "unanswerable" or s.startswith("quality issues are too severe")


def acc(refused: bool, matches: list[int], answers: list[str]) -> float:
    m = [i for i, a in enumerate(answers) if is_unans(a)] if refused else [i for i in matches if not is_unans(answers[i])]
    return min(len(m) / 3, 1.0)


def ci(x) -> dict:
    v, lo, hi = common.bootstrap_ci(np.asarray(x, dtype=float))
    return {"value": v, "ci": [lo, hi], "n": len(x)}


def main() -> None:
    blind = {int(r["row"]): r for r in csv.DictReader(open(os.path.join(J, "blind.csv"), encoding="utf-8"))}
    cx = {}
    for r in csv.DictReader(open(os.path.join(J, "judge_codex.csv"), encoding="utf-8")):
        try:
            cx[int(r["row"])] = r
        except (KeyError, ValueError):
            continue
    ps = {p["image"]: p for p in json.load(open(sorted(glob.glob(os.path.join(common.RESULTS, "vqa_vizwiz", "2026*_general_space.json")))[-1],
                                                 encoding="utf-8"))["per_sample"]}
    rows = []
    for k, b in sorted(blind.items()):
        if k not in cx:
            continue
        p = ps[os.path.basename(b["image_path"])]
        c = cx[k]
        cm = [int(x) for x in str(c.get("matches", "")).replace(",", ";").split(";") if x.strip().isdigit() and int(x) < 10]
        rows.append({"image": p["image"], "answerable": p["answerable"],
                     "g_refused": int(bool(p["refused"])), "c_refused": int(str(c["refused"]).strip() == "1"),
                     "g_acc": p["vqa_acc"], "c_acc": acc(str(c["refused"]).strip() == "1", cm, p["gt_answers"]),
                     "c_hall": int(str(c["hallucination"]).strip() == "1"),
                     "c_img_answerable": int(str(c.get("image_answerable", "")).strip() == "1"), "c_note": c.get("note", "")})
    una = [r for r in rows if r["answerable"] == 0]
    ans = [r for r in rows if r["answerable"] == 1]
    res = {"n_judged": len(rows), "n_blind": len(blind),
           "refused_agreement": ci([int(r["g_refused"] == r["c_refused"]) for r in rows]),
           "refused_kappa": kappa([r["g_refused"] for r in rows], [r["c_refused"] for r in rows]),
           "vqa_acc_gemma_judge": ci([r["g_acc"] for r in rows]), "vqa_acc_codex_judge": ci([r["c_acc"] for r in rows]),
           "vqa_acc_paired": common.paired([r["g_acc"] for r in rows], [r["c_acc"] for r in rows]),
           "hallucination_unanswerable_codex": ci([r["c_hall"] for r in una]),
           "not_refused_unanswerable_codex": ci([1 - r["c_refused"] for r in una]),
           "codex_thinks_answerable_on_unanswerable": ci([r["c_img_answerable"] for r in una]),
           "hallucination_answerable_codex": ci([r["c_hall"] for r in ans]),
           "rows": rows}
    res["meta"] = common.run_meta({"judge": "codex gpt-6-luna, mù (không thấy phán quyết Gemma), có nhìn ảnh"})
    common.write_result("vqa_vizwiz", "judge_codex", res)

    def p(d):
        return f"{100 * d['value']:.1f} % [{100 * d['ci'][0]:.1f}; {100 * d['ci'][1]:.1f}] (n={d['n']})"
    L = ["# C4 — Đồng thuận giám khảo: Gemma-chấm vs Codex-chấm (VizWiz-VQA)", "",
         f"Codex `gpt-6-luna` chấm **mù** (không thấy phán quyết của Gemma), **có nhìn ảnh**, {len(rows)}/{len(blind)} dòng: 50 mẫu kiểm tay + toàn bộ câu unanswerable "
         "của mẫu 300. Codex là giám khảo độc lập thứ hai (khác họ model với Gemma), **không thay được người chấm**.", "",
         "| Chỉ số | Giá trị [CI 95 %] |", "|---|---|",
         f"| Đồng thuận 'từ chối' Gemma vs Codex | {p(res['refused_agreement'])} · κ = {res['refused_kappa']:.2f} |",
         f"| VQA acc theo Gemma-chấm | {p(res['vqa_acc_gemma_judge'])} |",
         f"| VQA acc theo Codex-chấm (cùng dòng) | {p(res['vqa_acc_codex_judge'])} · Δ {100 * res['vqa_acc_paired']['delta']:+.1f} đ.% "
         f"[{100 * res['vqa_acc_paired']['delta_ci'][0]:+.1f}; {100 * res['vqa_acc_paired']['delta_ci'][1]:+.1f}] |",
         f"| **Bịa thật trên câu unanswerable** (Codex nhìn ảnh: khẳng định điều ảnh không cho thấy) | **{p(res['hallucination_unanswerable_codex'])}** |",
         f"| Không từ chối trên câu unanswerable (Codex) | {p(res['not_refused_unanswerable_codex'])} |",
         f"| Codex cho rằng ảnh VẪN trả lời được dù nhãn đa số 'unanswerable' | {p(res['codex_thinks_answerable_on_unanswerable'])} |",
         f"| Bịa trên câu trả lời được (Codex) | {p(res['hallucination_answerable_codex'])} |", "",
         "Đọc: số bịa của bench (`VQA.md`, 'không khớp người nào' 41,3 %) là cận trên vì gộp cả câu né tránh; số Codex ở đây đo **bịa thật** bằng cách nhìn ảnh."]
    # Đối chứng âm: 20 câu trả lời bị TRÁO sang ảnh khác (phải bị đánh bịa) + 10 câu thật (không được đánh bịa), Codex không biết dòng nào.
    cpath, kpath = os.path.join(J, "judge_control.csv"), os.path.join(J, "control_key.json")
    if os.path.exists(cpath) and os.path.exists(kpath):
        key = {int(k): v for k, v in json.load(open(kpath)).items()}
        got = {}
        for r in csv.DictReader(open(cpath, encoding="utf-8")):
            try:
                got[int(r["row"])] = int(str(r["hallucination"]).strip() == "1")
            except (KeyError, ValueError):
                continue
        sw = [got[k] for k, v in key.items() if v == 1 and k in got]
        ge = [got[k] for k, v in key.items() if v == 0 and k in got]
        if sw and ge:
            ok = np.mean(sw) >= 0.8 and np.mean(ge) <= 0.2
            res["control"] = {"swapped_flagged": float(np.mean(sw)), "n_swapped": len(sw),
                              "genuine_flagged": float(np.mean(ge)), "n_genuine": len(ge), "pass": bool(ok)}
            L += ["", "## Đối chứng âm (Codex có thật sự nhìn ảnh không)", "",
                  f"Codex chấm thêm 30 dòng không biết trước: {len(sw)} dòng câu trả lời bị **tráo sang ảnh khác** và {len(ge)} dòng thật.",
                  f"- Dòng tráo bị đánh bịa: **{100 * np.mean(sw):.0f} %** (cần ≥ 80 %) · dòng thật bị đánh bịa: **{100 * np.mean(ge):.0f} %** (cần ≤ 20 %)",
                  f"- Kết luận: **{'ĐẠT — tin được phán quyết nhìn ảnh của Codex' if ok else 'KHÔNG ĐẠT — Codex có thể không nhìn ảnh; đừng dùng số bịa ở trên'}**."]
            common.write_result("vqa_vizwiz", "judge_codex_control", res["control"])
    out = os.path.join(common.REPORTS, "VQA_JUDGE_CODEX.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("ghi", out, {k: v for k, v in res.items() if k not in ("rows", "meta")})


if __name__ == "__main__":
    main()
