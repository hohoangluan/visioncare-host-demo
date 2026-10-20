"""C4 — Hỏi đáp theo ảnh trên VizWiz-VQA val (METRICS.md C4). python -m bench.vqa_vizwiz [--limit N]

Mẫu 300 câu `sample(seed=0)`. Câu hỏi EN dịch sang tiếng Việt MỘT lần bằng LLM (cache results/vqa_vizwiz/questions_vi.json).
Trả lời: `general.answer("space", câu_vi, ảnh 896 px)` (đường production làn A). Chấm: LLM (temperature 0) nhận câu hỏi +
câu trả lời VN + 10 đáp án EN -> JSON {"refused", "matches"}; VQA acc = min(#người trùng/3, 1).
Câu trả lời bị chấm 'từ chối' thì khớp với các đáp án "unanswerable" (xác định bằng mã, không nhờ LLM).
Ghi results/vqa_vizwiz/handcheck_50.csv để người chấm tay.
"""

import argparse
import csv
import json
import os

import numpy as np

from bench import common

common.setup(gpu=False)

from bench import llm_common as L  # noqa: E402

TASK = "vqa_vizwiz"
VZ = os.path.join(common.DATAS, "vizwiz")
OUT_DIR = os.path.join(common.RESULTS, TASK)

TRANSLATE_PROMPT = (
    "Dịch câu hỏi sau sang tiếng Việt tự nhiên, văn nói, đúng như một người khiếm thị sẽ hỏi trợ lý về bức ảnh họ vừa chụp. "
    "Giữ nguyên ý, không thêm bớt, không giải thích. Chỉ trả về đúng câu đã dịch.\n\nCâu hỏi: {q}"
)

JUDGE_PROMPT = """Bạn chấm câu trả lời của một trợ lý thị giác (tiếng Việt) cho người khiếm thị, đối chiếu với 10 đáp án tiếng Anh do người thật viết.

Câu hỏi (tiếng Anh): {q_en}
Câu hỏi (tiếng Việt): {q_vi}
Câu trả lời của trợ lý: {answer}

10 đáp án người viết (đánh số từ 0):
{answers}

Nhiệm vụ:
1. "refused": true nếu trợ lý NÓI THẲNG là không thấy rõ / không đọc được / không trả lời được / yêu cầu chụp lại / không đủ thông tin trong ảnh để trả lời. Trợ lý chỉ mô tả cảnh chung chung rồi KHÔNG trả lời câu hỏi, hoặc trả lời một điều thực chất có trong ảnh, thì KHÔNG phải từ chối (false).
2. "matches": danh sách chỉ số các đáp án (0-9) mà câu trả lời của trợ lý CÓ CÙNG NGHĨA (cùng thông tin cốt lõi, không cần giống từ; khác ngôn ngữ, đồng nghĩa, diễn đạt dài hơn đều được). Nếu trợ lý từ chối thì matches để rỗng (hệ thống tự xử lý). Không khớp đáp án nào thì để rỗng.

Ví dụ 1: câu hỏi "What color is this shirt?"; trợ lý nói "Áo màu xanh dương." ; đáp án [blue, blue, navy blue, blue, dark blue, blue, blue, black, blue, blue] -> {{"refused": false, "matches": [0,1,2,3,4,5,6,8,9]}} (navy/dark blue cùng nghĩa với xanh dương; black thì không).
Ví dụ 2: câu hỏi "What does this say?"; trợ lý nói "Không thấy rõ chữ, bạn chụp lại giúp." ; đáp án [unanswerable, quality issues are too severe to recognize visual content, unanswerable, unanswerable, ...] -> {{"refused": true, "matches": []}}.
Ví dụ 3: câu hỏi "Is this milk?"; trợ lý nói "Đây là hộp sữa tươi." ; đáp án [yes, yes, yes, milk, yes, yes, yes, yes, no, yes] -> {{"refused": false, "matches": [0,1,2,3,4,5,6,7,9]}} (câu trả lời khẳng định đây là sữa nên khớp "yes" và "milk").

Chỉ trả về JSON."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"refused": {"type": "boolean"},
                   "matches": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 9}}},
    "required": ["refused", "matches"],
}


def is_unans(ans: str) -> bool:
    a = L.nfc_lower(ans).strip()
    return a == "unanswerable" or a.startswith("quality issues are too severe")


async def translate(items: list[dict], cache_path: str) -> dict:
    from models import llm
    tr = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    import asyncio
    for i, it in enumerate(items):
        if it["image"] in tr:
            continue
        for attempt in range(3):
            try:
                text = await llm.complete([llm.user_message(TRANSLATE_PROMPT.format(q=it["question"]))],
                                          max_tokens=120, temperature=0.0)
                tr[it["image"]] = text.strip().strip('"')
                break
            except Exception as exc:  # noqa: BLE001
                print("translate lỗi", repr(exc)[:150], flush=True)
                await asyncio.sleep(1 + attempt)
        else:
            tr[it["image"]] = None
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(tr, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        print(f"[translate] {i + 1}/{len(items)} {it['question'][:50]!r} -> {tr[it['image']]!r}", flush=True)
    return tr


async def judge(it: dict, q_vi: str, answer: str, jcache: L.Cache) -> dict:
    """LLM chấm; cache theo ảnh. Trả {"refused", "matches"} (matches đã hợp nhất theo luật từ chối)."""
    from models import llm
    key = it["image"]
    hit = jcache.get(key)
    if hit is not None:
        return hit
    answers = "\n".join(f"{i}: {a['answer']}" for i, a in enumerate(it["answers"]))
    prompt = JUDGE_PROMPT.format(q_en=it["question"], q_vi=q_vi, answer=answer, answers=answers)
    err = None
    import asyncio
    for attempt in range(3):
        try:
            obj = await llm.generate_json(prompt, JUDGE_SCHEMA, max_tokens=120)
            m = sorted({int(i) for i in obj.get("matches", []) if 0 <= int(i) < len(it["answers"])})
            out = {"refused": bool(obj.get("refused")), "llm_matches": m}
            jcache.put(key, out)
            return jcache.get(key)
        except Exception as exc:  # noqa: BLE001
            err = repr(exc)[:200]
            await asyncio.sleep(1 + attempt)
    return {"refused": None, "llm_matches": [], "error": err}


def vqa_acc(it: dict, j: dict) -> tuple[float, list[int]]:
    """min(#đáp án trùng/3, 1). Từ chối -> trùng với các đáp án unanswerable; ngược lại -> chỉ số LLM chấm (bỏ unanswerable)."""
    if j.get("refused"):
        m = [i for i, a in enumerate(it["answers"]) if is_unans(a["answer"])]
    else:
        m = [i for i in j["llm_matches"] if not is_unans(it["answers"][i]["answer"])]
    return min(len(m) / 3.0, 1.0), m


async def run(args):
    import config
    from lanes import general
    from pipeline import image_quality
    from pipeline.image_buffer import resize_jpeg
    from models import llm

    os.makedirs(OUT_DIR, exist_ok=True)
    allv = json.load(open(os.path.join(VZ, "vqa", "val.json"), encoding="utf-8"))
    items = common.sample(allv, 300, seed=0)
    if args.limit:
        items = items[: args.limit]
    tr = await translate(items, os.path.join(OUT_DIR, "questions_vi.json"))
    items = [it for it in items if tr.get(it["image"])]

    cfg_parts = {"task": TASK, "system": general._VISION_SYSTEM, "space": general._vision_task("space", ""),
                 "translate": TRANSLATE_PROMPT}
    cache = L.Cache(TASK, L.cfg_hash(cfg_parts))
    jcache = L.Cache(TASK, L.cfg_hash({"judge": JUDGE_PROMPT, "schema": JUDGE_SCHEMA, "ans": cache.cfg}), name="judge_cache.jsonl")

    def load(it):
        with open(os.path.join(VZ, "val", it["image"]), "rb") as f:
            return L.to_jpeg(f.read(), quality=90)

    def factory(it):
        return general.answer("space", tr[it["image"]], resize_jpeg(load(it), config.LLM_IMAGE_MAX_SIDE))

    res = await L.run_items(items, lambda it: it["image"], factory, cache, TASK)

    per, ttft, total = [], [], []
    for it in items:
        r = res[it["image"]]
        row = {"image": it["image"], "question_en": it["question"], "question_vi": tr[it["image"]],
               "answer_type": it.get("answer_type"), "answerable": int(it["answerable"]),
               "gt_answers": [a["answer"] for a in it["answers"]], "output": r["text"], "ttft_ms": r.get("ttft_ms"),
               "total_ms": r.get("total_ms"), "error": r.get("error"), "cached": r["cached"],
               "gate_reason": image_quality.reject_reason("space", load(it))}
        if "error" not in r:
            ttft.append(r["ttft_ms"])
            total.append(r["total_ms"])
            j = await judge(it, tr[it["image"]], r["text"], jcache)
            row.update(judge_error=j.get("error"), refused=j["refused"], llm_matches=j["llm_matches"])
            if j["refused"] is not None:
                row["vqa_acc"], row["matched"] = vqa_acc(it, j)
        per.append(row)
        print(f"[judge] {row['image']} refused={row.get('refused')} acc={row.get('vqa_acc')} ans={r['text'][:60]!r}", flush=True)

    ok = [x for x in per if not x["error"] and x.get("refused") is not None]
    una = [x for x in ok if x["answerable"] == 0]
    ans = [x for x in ok if x["answerable"] == 1]
    A = lambda rows, f: np.array([f(x) for x in rows], dtype=float)  # noqa: E731
    metrics = {}
    if ok:
        metrics["vqa_acc_all"] = L.ci_entry(A(ok, lambda x: x["vqa_acc"]))
        # Độ chính xác chỉ trên câu trả lời được: câu bị từ chối vẫn tính (acc 0 trừ khi người cũng nói unanswerable)
        if ans:
            metrics["vqa_acc_answerable"] = L.ci_entry(A(ans, lambda x: x["vqa_acc"]))
        if una:
            metrics["vqa_acc_unanswerable"] = L.ci_entry(A(una, lambda x: x["vqa_acc"]))
            metrics["fabricate_rate_unanswerable"] = L.ci_entry(A(una, lambda x: not x["refused"]))
        metrics["refusal_rate"] = L.ci_entry(A(ok, lambda x: x["refused"]))
        if ans:
            metrics["refusal_rate_answerable"] = L.ci_entry(A(ans, lambda x: x["refused"]))
        # Nếu có cổng chất lượng ảnh như production (reject_reason): bị cổng chặn = từ chối (không gọi LLM)
        if una:
            metrics["fabricate_rate_unanswerable_with_gate"] = L.ci_entry(
                A(una, lambda x: (not x["refused"]) and x["gate_reason"] is None))
        metrics["gate_reject_rate"] = L.ci_entry(A(ok, lambda x: x["gate_reason"] is not None))
        # từ chối đúng: dương = trợ lý từ chối; nhãn dương thật = answerable == 0
        tp = sum(1 for x in ok if x["refused"] and x["answerable"] == 0)
        fp = sum(1 for x in ok if x["refused"] and x["answerable"] == 1)
        fn = sum(1 for x in ok if not x["refused"] and x["answerable"] == 0)
        metrics["refusal_precision"] = L.ci_entry(
            A([x for x in ok if x["refused"]], lambda x: x["answerable"] == 0)) if tp + fp else None
        metrics["refusal_recall"] = L.ci_entry(A(una, lambda x: x["refused"])) if tp + fn else None
    # Kiểm tay: 50 mẫu seed 0 trong mẫu đã chạy
    hand = common.sample(per, 50, seed=0)
    csv_path = os.path.join(OUT_DIR, "handcheck_50.csv")
    old = {}
    if os.path.exists(csv_path):  # giữ phần người chấm đã điền
        with open(csv_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                old[row["image"]] = row
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        cols = ["image", "question_en", "question_vi", "answerable_gt", "gt_answers_en", "answer_vi", "llm_refused",
                "llm_matches", "llm_vqa_acc", "human_refused", "human_n_match", "human_note"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for x in hand:
            o = old.get(x["image"], {})
            w.writerow({"image": x["image"], "question_en": x["question_en"], "question_vi": x["question_vi"],
                        "answerable_gt": x["answerable"], "gt_answers_en": " | ".join(f"{i}:{a}" for i, a in enumerate(x["gt_answers"])),
                        "answer_vi": x["output"].replace("\n", " "), "llm_refused": x.get("refused"),
                        "llm_matches": ",".join(map(str, x.get("llm_matches", []))), "llm_vqa_acc": x.get("vqa_acc"),
                        "human_refused": o.get("human_refused", ""), "human_n_match": o.get("human_n_match", ""),
                        "human_note": o.get("human_note", "")})
    payload = {"meta": common.run_meta({"task": TASK, "limit": args.limit, "cfg_hash": cache.cfg, "sample": 300, "seed": 0,
                                        "intent": "space", "translate_prompt": TRANSLATE_PROMPT, "judge_prompt": JUDGE_PROMPT,
                                        "judge": "llm.generate_json (json_schema), temperature 0",
                                        "acc_formula": "min(#đáp án trùng/3, 1) trên 10 đáp án (không phải leave-one-out chính thức)"}),
               "metrics": {k: v for k, v in metrics.items() if v}, "n_questions": len(items), "n_judged": len(ok),
               "n_errors": sum(1 for x in per if x["error"] or x.get("refused") is None),
               "n_unanswerable": len(una), "n_answerable": len(ans),
               "latency": {"ttft": common.latency_summary(ttft), "total": common.latency_summary(total)},
               "handcheck_csv": csv_path, "per_sample": per}
    path = common.write_result(TASK, f"general_space{'_limit%d' % args.limit if args.limit else ''}", payload, args.out)
    print(path)
    for k, v in payload["metrics"].items():
        print(f"{k}: {v['value']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}] n={v['n']}")
    print("latency", payload["latency"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="chỉ N câu đầu của mẫu 300")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    L.new_loop_run(run(args))


if __name__ == "__main__":
    main()
